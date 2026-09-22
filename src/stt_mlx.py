"""Apple Silicon speech recognition using MLX Whisper."""
from importlib import import_module
import logging
import threading
from typing import Callable, Optional

import numpy as np

from .backend_interfaces import SpeechToTextBackend

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000


def pcm16_to_float32(
    audio_bytes: bytes,
    sample_rate: int,
    target_sample_rate: int = TARGET_SAMPLE_RATE,
) -> np.ndarray:
    """Convert mono PCM16 bytes to a normalized in-memory waveform."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be greater than zero")
    if len(audio_bytes) % np.dtype(np.int16).itemsize:
        raise ValueError("PCM16 audio must contain complete 16-bit samples")

    audio = np.frombuffer(audio_bytes, dtype=np.int16)
    if audio.size == 0:
        raise ValueError("PCM16 audio is empty")

    if sample_rate != target_sample_rate:
        sample_count = int(audio.size * target_sample_rate / sample_rate)
        if sample_count < 1:
            raise ValueError("resampling would produce no audio samples")
        indices = np.linspace(0, audio.size - 1, sample_count)
        audio = np.interp(
            indices,
            np.arange(audio.size),
            audio.astype(np.float32),
        ).astype(np.int16)

    return audio.astype(np.float32) / 32768.0


def _load_mlx_runtime():
    """Load the installed MLX runtime only when this backend is selected."""
    try:
        mlx_whisper = import_module("mlx_whisper")
        transcribe_module = import_module("mlx_whisper.transcribe")
        mlx_core = import_module("mlx.core")
    except ModuleNotFoundError as exc:
        missing_root = (exc.name or "").split(".")[0]
        if missing_root in {"mlx", "mlx_whisper"}:
            raise RuntimeError(
                "The 'mlx-whisper' package is required for the mlx-whisper "
                "STT backend"
            ) from exc
        raise RuntimeError(f"Failed to initialize MLX Whisper: {exc}") from exc
    except ImportError as exc:
        raise RuntimeError(f"Failed to initialize MLX/Metal: {exc}") from exc

    try:
        shared_stream = mlx_core.new_thread_unsafe_stream(mlx_core.gpu)
    except Exception as exc:
        raise RuntimeError(f"Failed to initialize MLX/Metal: {exc}") from exc

    def run_on_stream(operation: Callable):
        # The model is preloaded during pipeline construction, then used by
        # the single STT worker. MLX's regular streams are bound to their
        # creation thread, so use one explicitly shareable stream and keep all
        # access serialized in MLXWhisperBackend.
        with mlx_core.stream(shared_stream):
            result = operation()
            mlx_core.synchronize(shared_stream)
            return result

    def preload(model_name: str):
        return run_on_stream(
            lambda: transcribe_module.ModelHolder.get_model(
                model_name,
                mlx_core.float16,
            )
        )

    return mlx_whisper.transcribe, preload, run_on_stream


class MLXWhisperBackend(SpeechToTextBackend):
    """MLX Whisper adapter for raw mono PCM16 pipeline segments."""

    def __init__(
        self,
        model: str = "mlx-community/whisper-small-mlx",
        language: str = "tr",
        beam_size: int = 1,
        *,
        transcribe_fn: Optional[Callable] = None,
        model_loader: Optional[Callable[[str], object]] = None,
        stream_runner: Optional[Callable[[Callable], object]] = None,
    ):
        self.model_name = model
        self.language = language
        self.beam_size = beam_size
        if beam_size != 1:
            raise ValueError(
                "mlx-whisper 0.4.3 supports only greedy decoding; "
                "configure beam_size: 1"
            )

        if transcribe_fn is None:
            if model_loader is not None:
                raise ValueError("model_loader requires an injected transcribe_fn")
            transcribe_fn, model_loader, stream_runner = _load_mlx_runtime()
        elif model_loader is None:
            model_loader = lambda _model_name: None

        self._transcribe_fn = transcribe_fn
        self._stream_runner = stream_runner or (lambda operation: operation())
        self._stream_lock = threading.Lock()
        logger.info(
            "Loading MLX Whisper model: %s, device=metal, dtype=float16, "
            "language=%s",
            model,
            language,
        )
        try:
            model_loader(model)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load MLX Whisper model '{model}': {exc}"
            ) from exc
        logger.info("MLX Whisper model loaded successfully")

    def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = TARGET_SAMPLE_RATE,
    ) -> Optional[str]:
        """Transcribe raw mono PCM16 audio entirely in memory."""
        try:
            waveform = pcm16_to_float32(audio_bytes, sample_rate)
            logger.debug(
                "Transcribing audio with MLX: %s samples, %.2fs at %sHz",
                waveform.size,
                waveform.size / TARGET_SAMPLE_RATE,
                TARGET_SAMPLE_RATE,
            )
            with self._stream_lock:
                result = self._stream_runner(
                    lambda: self._transcribe_fn(
                        waveform,
                        path_or_hf_repo=self.model_name,
                        language=self.language,
                        task="transcribe",
                        temperature=0.0,
                        verbose=None,
                        word_timestamps=False,
                    )
                )
            raw_text = result.get("text") if isinstance(result, dict) else None
            text = " ".join(raw_text.split()) if isinstance(raw_text, str) else ""
            if not text:
                logger.warning("STT returned empty text")
                return None

            detected_language = result.get("language", self.language)
            logger.info(
                "STT result: '%s' (detected language: %s)",
                text,
                detected_language,
            )
            return text
        except Exception as exc:
            logger.error("MLX STT transcription error: %s", exc, exc_info=True)
            return None
