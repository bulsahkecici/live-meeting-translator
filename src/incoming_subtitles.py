"""Incoming English audio to Turkish subtitle pipeline."""
from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, Optional

from .backend_factory import BackendFactory
from .backend_interfaces import (
    AudioInputBackend,
    SpeechToTextBackend,
    TranslatorBackend,
)
from .pipeline_runtime import (
    PipelineBackpressureError,
    PipelineMessage,
    PipelineRuntime,
)
from .stt_filters import should_suppress_stt_text

logger = logging.getLogger(__name__)

_SILENCE_HALLUCINATION_MARKER = "known silence hallucination suppressed"


@dataclass(frozen=True)
class IncomingSubtitleComponents:
    """Dependencies required by the subtitle-only incoming channel."""

    audio_input: AudioInputBackend
    vad: object
    stt: SpeechToTextBackend
    translator: TranslatorBackend


def create_incoming_subtitle_components(config) -> IncomingSubtitleComponents:
    """Build the incoming channel from its isolated configuration section."""
    settings = config.incoming_subtitles_config
    if not settings.get("enabled", False):
        raise RuntimeError("Incoming subtitles are not enabled")

    input_config = settings.get("audio_input", {})
    pipeline_config = settings.get("pipeline", {})
    factory = BackendFactory(config)
    audio_input = factory.create_audio_input(
        input_config,
        audio_config={
            "input_sample_rate": input_config.get("sample_rate", 48000),
        },
        pipeline_config={
            "audio_buffer_size": pipeline_config.get(
                "audio_buffer_size",
                14400,
            ),
        },
    )
    vad = factory.create_vad(
        audio_input.sample_rate,
        settings.get("vad", config.vad_config),
    )
    stt = factory.create_stt(settings.get("stt", {}))
    translator = factory.create_translator(settings.get("translate", {}))
    return IncomingSubtitleComponents(
        audio_input=audio_input,
        vad=vad,
        stt=stt,
        translator=translator,
    )


class IncomingSubtitlePipeline:
    """Capture conference audio and emit English/Turkish subtitle pairs."""

    def __init__(
        self,
        config,
        *,
        on_subtitle: Optional[Callable[[str, str], None]] = None,
        components: Optional[IncomingSubtitleComponents] = None,
    ):
        self.config = config
        self.settings = config.incoming_subtitles_config
        self.on_subtitle = on_subtitle
        if components is None:
            components = create_incoming_subtitle_components(config)

        self.audio_input = components.audio_input
        self.vad = components.vad
        self.stt = components.stt
        self.translator = components.translator
        self._running = False
        self._cancel_on_stop = False
        self._stop_requested = threading.Event()
        pipeline_config = self.settings.get("pipeline", {})
        self._runtime = PipelineRuntime(
            (
                ("incoming_stt", self._stage_stt),
                ("incoming_translation", self._stage_translation),
            ),
            queue_capacity=pipeline_config.get("stage_queue_capacity", 4),
            enqueue_timeout_seconds=pipeline_config.get(
                "enqueue_timeout_seconds",
                2.0,
            ),
            shutdown_timeout_seconds=pipeline_config.get(
                "shutdown_timeout_seconds",
                30.0,
            ),
            on_complete=self._on_complete,
            on_failure=self._on_failure,
            on_cancel=self._on_cancel,
        )

    def _stage_stt(self, message: PipelineMessage) -> bool:
        message.source_text = self.stt.transcribe(
            message.audio_bytes,
            self.audio_input.sample_rate,
        )
        if not message.source_text:
            logger.warning("Incoming STT returned no text")
            return False
        if should_suppress_stt_text(message.source_text):
            message.error = _SILENCE_HALLUCINATION_MARKER
            logger.info("Suppressed known incoming STT hallucination during silence")
            return False
        logger.info(
            "Incoming STT result: '%s' (language: en)",
            message.source_text,
        )
        return True

    def _stage_translation(self, message: PipelineMessage) -> bool:
        message.translated_text = self.translator.translate(message.source_text)
        if not message.translated_text:
            logger.error(
                "Incoming translation failed for: '%s'",
                message.source_text,
            )
            return False
        if should_suppress_stt_text(message.translated_text):
            message.error = _SILENCE_HALLUCINATION_MARKER
            logger.info("Suppressed known translated hallucination during silence")
            return False
        logger.info(
            "Incoming translation completed for segment %s: '%s'",
            message.sequence_id,
            message.translated_text,
        )
        return True

    def _on_complete(self, message: PipelineMessage) -> None:
        if self.on_subtitle:
            self.on_subtitle(message.source_text, message.translated_text)
        logger.info(
            "Incoming subtitle segment %s complete: stages=%s, total=%.3fs",
            message.sequence_id,
            message.stage_seconds,
            time.monotonic() - message.created_at,
        )

    def _on_failure(self, message: PipelineMessage) -> None:
        if message.error == _SILENCE_HALLUCINATION_MARKER:
            logger.info(
                "Incoming subtitle segment %s suppressed during silence",
                message.sequence_id,
            )
            return
        logger.error(
            "Incoming subtitle segment %s failed: %s",
            message.sequence_id,
            message.error,
        )

    def _on_cancel(self, message: PipelineMessage) -> None:
        logger.warning(
            "Incoming subtitle segment %s %s",
            message.sequence_id,
            message.error,
        )

    def runtime_metrics(self) -> dict:
        """Return incoming queue, timing, and capture continuity metrics."""
        metrics = self._runtime.snapshot()
        metrics["capture_dropped_chunks"] = self._capture_dropped_chunks()
        return metrics

    def _capture_dropped_chunks(self) -> int:
        counter = getattr(self.audio_input, "dropped_chunk_count", None)
        return counter() if callable(counter) else 0

    def run_live(self) -> None:
        """Capture, transcribe, and translate conference audio until stopped."""
        drain_capture = True
        drain_runtime = True
        audio_started = False
        capture_drops = self._capture_dropped_chunks()
        pending_segment = None
        self._running = True
        if self._stop_requested.is_set():
            self._running = False
        try:
            self._runtime.start()
            self.audio_input.start()
            audio_started = True
            logger.info("Incoming subtitle capture active")

            while self._running and not self._stop_requested.is_set():
                current_drops = self._capture_dropped_chunks()
                if current_drops > capture_drops:
                    raise PipelineBackpressureError(
                        "incoming audio capture queue overflowed; stopping "
                        "instead of hiding a subtitle continuity gap"
                    )
                audio_chunk = self.audio_input.read(timeout=0.1)
                if audio_chunk is None:
                    continue
                segment = self.vad.process_audio(audio_chunk)
                if segment:
                    try:
                        self._runtime.submit(segment)
                    except PipelineBackpressureError:
                        pending_segment = segment
                        raise
        except PipelineBackpressureError:
            logger.error("Incoming subtitle backpressure limit reached", exc_info=True)
            raise
        except Exception:
            drain_capture = False
            logger.error("Incoming subtitle pipeline failed", exc_info=True)
            raise
        finally:
            self._running = False
            if self._cancel_on_stop:
                drain_capture = False
                drain_runtime = False
            shutdown_deadline = self._runtime.shutdown_deadline()
            try:
                if audio_started:
                    self.audio_input.stop()
                if drain_runtime and pending_segment is not None:
                    self._runtime.submit_for_drain(
                        pending_segment,
                        deadline=shutdown_deadline,
                    )
                if drain_capture and drain_runtime:
                    while True:
                        audio_chunk = self.audio_input.read(timeout=0)
                        if audio_chunk is None:
                            break
                        segment = self.vad.process_audio(audio_chunk)
                        if segment:
                            self._runtime.submit_for_drain(
                                segment,
                                deadline=shutdown_deadline,
                            )
                    final_segment = self.vad.flush()
                    if final_segment:
                        self._runtime.submit_for_drain(
                            final_segment,
                            deadline=shutdown_deadline,
                        )
            finally:
                self._runtime.shutdown(
                    drain=drain_runtime,
                    deadline=shutdown_deadline,
                )
            logger.info(
                "Final incoming subtitle metrics: %s",
                self.runtime_metrics(),
            )

    def stop(self, *, cancel: bool = False) -> None:
        """Stop incoming capture and drain accepted speech by default."""
        self._cancel_on_stop = cancel
        self._stop_requested.set()
        self._running = False
