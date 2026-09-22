"""Main translation pipeline."""
import logging
import threading
import time
import numpy as np
try:
    import noisereduce as nr
    NOISE_REDUCE_AVAILABLE = True
except ImportError:
    NOISE_REDUCE_AVAILABLE = False

from .backend_factory import PipelineComponents, create_pipeline_components
from .pipeline_runtime import (
    PipelineBackpressureError,
    PipelineMessage,
    PipelineRuntime,
)
from .utils import get_tmp_dir

logger = logging.getLogger(__name__)


class TranslationPipeline:
    """Main translation pipeline orchestrating all components."""
    
    def __init__(self, config, components: PipelineComponents = None):
        """Initialize from config or a complete injected component bundle."""
        self.config = config
        self.tmp_dir = get_tmp_dir()

        if components is None:
            components = create_pipeline_components(config)

        self.audio_input = components.audio_input
        self.audio_output = components.audio_output
        self.vad = components.vad
        self.stt = components.stt
        self.translator = components.translator
        self.tts = components.tts
        self._running = False
        self._cancel_on_stop = False
        self._stop_requested = threading.Event()
        pipeline_config = getattr(self.config, "pipeline_config", {})
        self._runtime = PipelineRuntime(
            (
                ("stt", self._stage_stt),
                ("translation", self._stage_translation),
                ("tts", self._stage_tts),
                ("playback", self._stage_playback),
            ),
            queue_capacity=pipeline_config.get("stage_queue_capacity", 4),
            enqueue_timeout_seconds=pipeline_config.get(
                "enqueue_timeout_seconds", 2.0
            ),
            shutdown_timeout_seconds=pipeline_config.get(
                "shutdown_timeout_seconds", 30.0
            ),
            on_complete=self._on_message_complete,
            on_failure=self._on_message_failure,
            on_cancel=self._on_message_cancel,
        )

        logger.info("Translation pipeline initialized")

    def process_segment(self, audio_bytes: bytes) -> bool:
        """Process one segment synchronously for direct and test callers."""
        message = PipelineMessage(sequence_id=0, audio_bytes=audio_bytes)
        started = time.perf_counter()
        try:
            for name, handler in (
                ("stt", self._stage_stt),
                ("translation", self._stage_translation),
                ("tts", self._stage_tts),
                ("playback", self._stage_playback),
            ):
                stage_started = time.perf_counter()
                succeeded = handler(message)
                message.stage_seconds[name] = time.perf_counter() - stage_started
                if not succeeded:
                    return False
            logger.info(
                "Segment processing complete: sequence=%s, stages=%s, total=%.3fs",
                message.sequence_id,
                message.stage_seconds,
                time.perf_counter() - started,
            )
            return True
        finally:
            self._cleanup_message(message)

    def _prepare_audio(self, audio_bytes: bytes) -> bytes:
        """Apply optional noise reduction without changing capture ordering."""
        if NOISE_REDUCE_AVAILABLE:
            try:
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                audio_float = audio_np.astype(np.float32) / 32768.0
                clean_float = nr.reduce_noise(
                    y=audio_float,
                    sr=self.audio_input.sample_rate,
                    stationary=True,
                    n_fft=512,
                )
                clean_int16 = (clean_float * 32768.0).astype(np.int16)
                logger.info("Noise reduction applied")
                return clean_int16.tobytes()
            except Exception as e:
                logger.warning(f"Noise reduction failed: {e}")
        return audio_bytes

    def _stage_stt(self, message: PipelineMessage) -> bool:
        logger.info("Processing segment %s: STT...", message.sequence_id)
        message.audio_bytes = self._prepare_audio(message.audio_bytes)
        message.source_text = self.stt.transcribe(
            message.audio_bytes,
            self.audio_input.sample_rate,
        )
        if not message.source_text:
            logger.warning("STT returned no text, skipping segment")
            return False

        logger.info(
            "Outgoing STT completed for segment %s: '%s'",
            message.sequence_id,
            message.source_text,
        )

        common_false_positives = [
            "videoyu izlediğiniz için teşekkürler",
            "videoyu izlediğiniz için",
            "thank you for watching",
            "bir sonraki videoda görüşürüz",
        ]
        tr_lower = message.source_text.lower()
        for phrase in common_false_positives:
            if phrase in tr_lower:
                logger.warning(
                    f"STT detected common phrase '{phrase}' - "
                    "This might be a false positive from background audio. "
                    "Please verify if you actually said this."
                )
        return True

    def _stage_translation(self, message: PipelineMessage) -> bool:
        logger.info("Translating segment %s...", message.sequence_id)
        message.translated_text = self.translator.translate(message.source_text)
        if not message.translated_text:
            logger.error(
                f"Translation failed for: '{message.source_text}'. "
                "Printing Turkish text for manual translation."
            )
            print(f"\n[TURKISH] {message.source_text}")
            print("[ENGLISH] <translation failed - please translate manually>\n")
            return False
        logger.info(
            "Translation completed for segment %s: '%s'",
            message.sequence_id,
            message.translated_text,
        )
        print(f"\n[TURKISH] {message.source_text}")
        print(f"[ENGLISH] {message.translated_text}\n")
        return True

    def _stage_tts(self, message: PipelineMessage) -> bool:
        logger.info("Synthesizing segment %s...", message.sequence_id)
        message.wav_path = self.tmp_dir / (
            f"tts_{message.sequence_id}_{time.time_ns()}.wav"
        )
        success = self.tts.synthesize_to_wav(
            message.translated_text,
            message.wav_path,
            sample_rate=self.audio_output.sample_rate,
        )
        if not success:
            logger.error(
                "TTS failed for segment %s: '%s'",
                message.sequence_id,
                message.translated_text,
            )
            return False
        return True

    def _stage_playback(self, message: PipelineMessage) -> bool:
        logger.info("Playing segment %s...", message.sequence_id)
        if not self.audio_output.play_wav(message.wav_path, blocking=True):
            logger.error("Audio playback failed for segment %s", message.sequence_id)
            return False
        return True

    def _on_message_complete(self, message: PipelineMessage) -> None:
        total = time.monotonic() - message.created_at
        logger.info(
            "Segment %s complete: stages=%s, end_to_end=%.3fs, queues=%s",
            message.sequence_id,
            message.stage_seconds,
            total,
            self._runtime.snapshot()["queue_depth"],
        )
        self._cleanup_message(message)

    def _on_message_failure(self, message: PipelineMessage) -> None:
        logger.error(
            "Segment %s failed without blocking later segments: %s",
            message.sequence_id,
            message.error,
        )
        self._cleanup_message(message)

    def _on_message_cancel(self, message: PipelineMessage) -> None:
        logger.warning("Segment %s %s", message.sequence_id, message.error)
        self._cleanup_message(message)

    def _cleanup_message(self, message: PipelineMessage) -> None:
        if message.wav_path is None:
            return
        try:
            message.wav_path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("Could not delete temp WAV: %s", exc)

    def runtime_metrics(self) -> dict:
        """Return queue, throughput, failure, and stage timing metrics."""
        metrics = self._runtime.snapshot()
        metrics["capture_dropped_chunks"] = self._capture_dropped_chunks()
        return metrics

    def _capture_dropped_chunks(self) -> int:
        counter = getattr(self.audio_input, "dropped_chunk_count", None)
        return counter() if callable(counter) else 0

    def run_live(self):
        """Run live translation pipeline."""
        logger.info("Starting live translation pipeline...")
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
            logger.info("Listening for speech. Speak in Turkish...")
            print("\n=== LIVE TRANSLATION ACTIVE ===")
            print("Speak in Turkish. Pause after each sentence.\n")

            while self._running and not self._stop_requested.is_set():
                current_drops = self._capture_dropped_chunks()
                if current_drops > capture_drops:
                    raise PipelineBackpressureError(
                        "audio capture queue overflowed; stopping because "
                        f"{current_drops - capture_drops} chunk(s) were rejected"
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

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            print("\n=== STOPPING ===")
        except PipelineBackpressureError:
            logger.error("Live pipeline backpressure limit reached", exc_info=True)
            raise
        except Exception as e:
            drain_capture = False
            logger.error(f"Pipeline error: {e}", exc_info=True)
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
            except Exception:
                logger.error("Failed while stopping or draining capture", exc_info=True)
                raise
            finally:
                self._runtime.shutdown(
                    drain=drain_runtime,
                    deadline=shutdown_deadline,
                )
            logger.info("Final pipeline metrics: %s", self.runtime_metrics())
            logger.info("Pipeline stopped")

    def stop(self, *, cancel: bool = False):
        """Stop capture and drain by default, or visibly cancel pending segments."""
        self._cancel_on_stop = cancel
        self._stop_requested.set()
        self._running = False
        logger.info("Stopping pipeline requested (cancel=%s)...", cancel)

    def run_dryrun(self, text: str):
        """
        Run dry-run mode: text -> translate -> TTS -> output.
        
        Args:
            text: Turkish text to process
        """
        logger.info(f"Dry-run mode: processing text '{text}'")
        
        # Translation
        en_text = self.translator.translate(text)
        
        if not en_text:
            logger.error("Translation failed")
            print(f"[TURKISH] {text}")
            print("[ENGLISH] <translation failed>")
            return
        
        print(f"[TURKISH] {text}")
        print(f"[ENGLISH] {en_text}")
        
        # TTS
        wav_path = self.tmp_dir / f"dryrun_{int(time.time() * 1000)}.wav"
        success = self.tts.synthesize_to_wav(
            en_text,
            wav_path,
            sample_rate=self.audio_output.sample_rate
        )
        
        if not success:
            logger.error("TTS failed")
            return
        
        # Output
        self.audio_output.play_wav(wav_path, blocking=True)
        
        # Cleanup
        try:
            wav_path.unlink()
        except Exception:
            pass
    
    def run_test(self):
        """Run test mode: TTS test phrase -> output."""
        test_text = "This is a test of the translation system. One, two, three."
        logger.info(f"Test mode: synthesizing '{test_text}'")
        
        wav_path = self.tmp_dir / f"test_{int(time.time() * 1000)}.wav"
        success = self.tts.synthesize_to_wav(
            test_text,
            wav_path,
            sample_rate=self.audio_output.sample_rate
        )
        
        if not success:
            logger.error("TTS test failed")
            return
        
        print(f"\nPlaying test phrase: '{test_text}'")
        self.audio_output.play_wav(wav_path, blocking=True)
        
        # Cleanup
        try:
            wav_path.unlink()
        except Exception:
            pass
    
    def run_beep(self):
        """Run beep mode: generate beep -> output."""
        logger.info("Beep mode: generating 440Hz beep")
        print("\nPlaying 440Hz beep for 0.5 seconds...")
        self.audio_output.play_beep(frequency=440.0, duration=0.5, blocking=True)
