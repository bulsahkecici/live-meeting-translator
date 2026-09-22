"""Configuration-driven construction of the current pipeline backends."""
from dataclasses import dataclass
from importlib import import_module
import logging
from typing import Any, Optional

from .backend_interfaces import (
    AudioInputBackend,
    AudioOutputBackend,
    SpeechToTextBackend,
    TranslatorBackend,
)
from .runtime_platform import RuntimePlatform
from .tts_base import TTSEngine

logger = logging.getLogger(__name__)


def _load_symbol(module_name: str, symbol_name: str):
    """Load a concrete backend only when the factory actually selects it."""
    return getattr(import_module(module_name, package=__package__), symbol_name)


@dataclass(frozen=True)
class PipelineComponents:
    """Complete dependency bundle consumed by ``TranslationPipeline``."""

    audio_input: AudioInputBackend
    audio_output: AudioOutputBackend
    vad: Any
    stt: SpeechToTextBackend
    translator: TranslatorBackend
    tts: TTSEngine


class BackendFactory:
    """Translate existing configuration into the current implementations."""

    def __init__(
        self,
        config: Any,
        runtime_platform: Optional[RuntimePlatform] = None
    ):
        self.config = config
        self.runtime_platform = runtime_platform or RuntimePlatform.detect()

    def create_audio_input(
        self,
        input_config: Optional[dict] = None,
        *,
        audio_config: Optional[dict] = None,
        pipeline_config: Optional[dict] = None,
    ) -> AudioInputBackend:
        """Create the existing sounddevice input implementation."""
        find_device = _load_symbol(".devices", "find_device")
        audio_input_class = _load_symbol(".audio_in", "AudioInput")
        input_config = (
            self.config.audio_input if input_config is None else input_config
        )
        audio_config = (
            self.config.get("audio", {}) if audio_config is None else audio_config
        )
        pipeline_config = (
            self.config.pipeline_config
            if pipeline_config is None
            else pipeline_config
        )

        input_idx = find_device(
            name_substring=input_config.get("name_substring", ""),
            index_override=input_config.get("index_override"),
            is_input=True,
        )
        if input_idx is None:
            raise RuntimeError("Could not find audio input device")

        input_sr = (
            input_config.get("sample_rate")
            or audio_config.get("input_sample_rate")
            or 16000
        )
        audio_input = audio_input_class(
            device_index=input_idx,
            sample_rate=input_sr,
            channels=input_config.get("channels", 1),
            dtype="int16",
            blocksize=pipeline_config.get("audio_buffer_size", 4800),
            mix_to_mono=input_config.get("mix_to_mono", False),
        )
        return audio_input

    def create_audio_output(self) -> AudioOutputBackend:
        """Create the existing sounddevice output implementation."""
        find_device = _load_symbol(".devices", "find_device")
        audio_output_class = _load_symbol(".audio_out", "AudioOutput")
        output_config = self.config.audio_output
        audio_config = self.config.get("audio", {})

        output_idx = find_device(
            name_substring=output_config.get("name_substring", "CABLE Input"),
            index_override=output_config.get("index_override"),
            is_input=False,
        )
        if output_idx is None:
            raise RuntimeError("Could not find audio output device")

        output_sr = (
            output_config.get("sample_rate")
            or audio_config.get("output_sample_rate")
            or 48000
        )
        audio_output = audio_output_class(
            device_index=output_idx,
            sample_rate=output_sr,
            channels=1,
            dtype="int16",
        )
        return audio_output

    def create_vad(self, sample_rate: int, vad_config: Optional[dict] = None):
        """Create the unchanged VAD implementation from compatible config keys."""
        vad_class = _load_symbol(".vad", "VAD")
        vad_config = self.config.vad_config if vad_config is None else vad_config
        silence_ms = (
            vad_config.get("silence_threshold_ms")
            or vad_config.get("silence_ms")
            or 600
        )
        min_speech_ms = (
            vad_config.get("min_speech_duration_ms")
            or vad_config.get("min_speech_ms")
            or 800
        )
        max_segment_ms = (
            vad_config.get("max_segment_duration_ms")
            or vad_config.get("max_segment_ms")
            or 8000
        )
        vad = vad_class(
            sample_rate=sample_rate,
            frame_duration_ms=vad_config.get("frame_duration_ms", 30),
            silence_threshold_ms=silence_ms,
            min_speech_duration_ms=min_speech_ms,
            max_segment_duration_ms=max_segment_ms,
            aggressiveness=vad_config.get("aggressiveness", 2),
        )
        logger.info(
            "Effective VAD config: silence=%sms, min_speech=%sms, "
            "max_segment=%sms",
            silence_ms,
            min_speech_ms,
            max_segment_ms,
        )
        return vad

    def create_stt(self, stt_config: Optional[dict] = None) -> SpeechToTextBackend:
        """Create the configured STT backend; faster-whisper remains the default."""
        stt_config = self.config.stt_config if stt_config is None else stt_config
        backend_name = stt_config.get("backend", "faster-whisper").lower()
        logger.info("Selecting STT backend: %s", backend_name)
        if backend_name in {"faster-whisper", "whisper"}:
            stt_class = _load_symbol(".stt_whisper", "STTWhisper")
            return stt_class(
                model=stt_config.get("model", "small"),
                compute_type=stt_config.get("compute_type", "int8"),
                device=stt_config.get("device", "cpu"),
                language=stt_config.get("language", "tr"),
                beam_size=stt_config.get("beam_size", 1),
            )
        if backend_name == "mlx-whisper":
            if not self.runtime_platform.is_apple_silicon:
                raise RuntimeError(
                    "The mlx-whisper STT backend requires Apple Silicon macOS"
                )
            stt_class = _load_symbol(".stt_mlx", "MLXWhisperBackend")
            return stt_class(
                model=stt_config.get(
                    "model", "mlx-community/whisper-small-mlx"
                ),
                language=stt_config.get("language", "tr"),
                beam_size=stt_config.get("beam_size", 1),
            )
        raise ValueError(f"Unknown STT backend: {backend_name}")

    def create_translator(
        self,
        translate_config: Optional[dict] = None,
    ) -> TranslatorBackend:
        """Create the configured translator; DeepL remains the default."""
        translate_config = (
            self.config.translate_config
            if translate_config is None
            else translate_config
        )
        backend_name = translate_config.get("backend", "deepl").lower()
        if backend_name != "deepl":
            raise ValueError(f"Unknown translator backend: {backend_name}")
        if not self.config.deepl_api_key:
            raise RuntimeError("DeepL API key not configured")

        translator_class = _load_symbol(".translate_deepl", "DeepLTranslator")
        return translator_class(
            api_key=self.config.deepl_api_key,
            source_lang=translate_config.get("source_lang", "TR"),
            target_lang=translate_config.get("target_lang", "EN"),
            cache_size=translate_config.get("cache_size", 128),
            timeout_seconds=translate_config.get("timeout_seconds", 10),
            retry_max_attempts=translate_config.get("retry_max_attempts", 3),
            retry_backoff=translate_config.get(
                "retry_backoff", [0.5, 1.0, 2.0, 4.0]
            ),
        )

    def create_tts(self) -> TTSEngine:
        """Create the configured TTS engine with a platform-valid fallback."""
        tts_config = self.config.tts_config
        engine_name = tts_config.get("engine", "sapi").lower()
        sample_rate = tts_config.get("sample_rate", 48000)

        if engine_name == "sapi":
            if not self.runtime_platform.supports_sapi:
                raise RuntimeError("SAPI TTS is supported only on Windows")
            sapi_config = tts_config.get("sapi", {})
            tts_class = _load_symbol(".tts_sapi", "SapiTTSEngine")
            tts = tts_class(
                voice_substring=sapi_config.get("voice_substring", ""),
                sample_rate=sample_rate,
            )
        elif engine_name == "edge":
            edge_config = tts_config.get("edge", {})
            tts_class = _load_symbol(".tts_edge", "EdgeTTSEngine")
            tts = tts_class(
                voice=edge_config.get("voice", "en-US-AriaNeural"),
                rate=edge_config.get("rate", "+0%"),
                pitch=edge_config.get("pitch", "+0Hz"),
                sample_rate=sample_rate,
            )
        elif engine_name == "clone":
            clone_config = tts_config.get("clone", {})
            tts_class = _load_symbol(".tts_clone_stub", "CloneTTSEngineStub")
            tts = tts_class(
                sample_wav_path=clone_config.get("sample_wav_path", ""),
                model_name=clone_config.get("model_name", "xtts-v2"),
                language=clone_config.get("language", "en"),
                sample_rate=sample_rate,
            )
        else:
            raise ValueError(f"Unknown TTS engine: {engine_name}")

        if tts.is_available():
            return tts

        if not self.runtime_platform.supports_sapi:
            raise RuntimeError(
                f"TTS engine '{engine_name}' is unavailable and SAPI fallback "
                "is supported only on Windows"
            )

        logger.warning(
            "TTS engine '%s' not available. Falling back to SAPI.",
            engine_name,
        )
        sapi_class = _load_symbol(".tts_sapi", "SapiTTSEngine")
        return sapi_class(sample_rate=sample_rate)

    def create_components(self) -> PipelineComponents:
        """Build all components in the legacy observable construction order."""
        audio_input = self.create_audio_input()
        audio_output = self.create_audio_output()
        logger.info(
            "Effective audio config: input=%sHz, output=%sHz",
            audio_input.sample_rate,
            audio_output.sample_rate,
        )
        vad = self.create_vad(audio_input.sample_rate)
        stt = self.create_stt()
        translator = self.create_translator()
        tts = self.create_tts()
        return PipelineComponents(
            audio_input=audio_input,
            audio_output=audio_output,
            vad=vad,
            stt=stt,
            translator=translator,
            tts=tts,
        )


def create_pipeline_components(
    config: Any,
    runtime_platform: Optional[RuntimePlatform] = None
) -> PipelineComponents:
    """Convenience entry point for normal application startup."""
    return BackendFactory(config, runtime_platform).create_components()
