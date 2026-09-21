"""Speech-to-Text using faster-whisper."""
import logging
import numpy as np
from typing import Optional
from faster_whisper import WhisperModel

from .backend_interfaces import SpeechToTextBackend

# Optional torch import for CUDA detection (not required for faster-whisper)
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None

logger = logging.getLogger(__name__)


class STTWhisper(SpeechToTextBackend):
    """Speech-to-Text using faster-whisper."""
    
    def __init__(
        self,
        model: str = "small",
        compute_type: str = "int8",
        device: str = "cpu",
        language: str = "tr",
        beam_size: int = 1
    ):
        """
        Initialize Whisper STT model.
        
        Args:
            model: Model size (tiny, base, small, medium, large)
            compute_type: int8, float16, or float32
            device: cpu or cuda (auto-detect cuda if available)
            language: Language code (tr for Turkish)
            beam_size: Beam search size (lower = faster)
        """
        # Auto-detect CUDA if available and device is "cpu" but CUDA exists
        if device == "cpu":
            if TORCH_AVAILABLE and torch.cuda.is_available():
                logger.info("CUDA available but using CPU as configured")
            else:
                logger.info("Using CPU (CUDA not available or torch not installed)")
        elif device == "cuda":
            if TORCH_AVAILABLE and torch.cuda.is_available():
                logger.info("Using CUDA")
                device = "cuda"
            else:
                logger.warning("CUDA requested but not available, falling back to CPU")
                device = "cpu"
        
        self.model_name = model
        self.compute_type = compute_type
        self.device = device
        self.language = language
        self.beam_size = beam_size
        
        logger.info(
            f"Loading Whisper model: {model}, device={device}, "
            f"compute_type={compute_type}, language={language}"
        )
        
        try:
            self.model = WhisperModel(
                model,
                device=device,
                compute_type=compute_type
            )
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            if device == "cuda":
                logger.warning(
                    f"Failed to load Whisper model with CUDA and {compute_type}: {e}. "
                    "Retrying with compute_type='float32'..."
                )
                try:
                    # First fallback: Try float32 on CUDA (supports older GPUs)
                    self.compute_type = "float32"
                    self.model = WhisperModel(
                        model,
                        device="cuda",
                        compute_type="float32"
                    )
                    logger.info("Whisper model loaded successfully (CUDA float32 fallback)")
                except Exception as cuda_e:
                    logger.warning(
                        f"Failed to load Whisper model with CUDA (float32): {cuda_e}. "
                        "Falling back to CPU with int8 quantization."
                    )
                    # Second fallback: CPU
                    try:
                        self.device = "cpu"
                        self.compute_type = "int8"
                        self.model = WhisperModel(
                            model,
                            device="cpu",
                            compute_type="int8"
                        )
                        logger.info("Whisper model loaded successfully (CPU fallback)")
                    except Exception as cpu_e:
                        logger.error(f"Failed to load Whisper model on CPU fallback: {cpu_e}", exc_info=True)
                        raise
            else:
                logger.error(f"Failed to load Whisper model: {e}", exc_info=True)
                raise
    
    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> Optional[str]:
        """
        Transcribe audio to text.
        
        Args:
            audio_bytes: Raw audio bytes (int16, mono)
            sample_rate: Sample rate in Hz
        
        Returns:
            Transcribed text or None on error
        """
        try:
            # Convert bytes to numpy array
            audio = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # Resample to 16kHz if needed (faster-whisper works best at 16kHz)
            target_sample_rate = 16000
            if sample_rate != target_sample_rate:
                # Linear interpolation resampling
                ratio = target_sample_rate / sample_rate
                num_samples = int(len(audio) * ratio)
                
                if num_samples < 1:
                    logger.error(f"Resampling would produce {num_samples} samples, too few")
                    return None
                
                indices = np.linspace(0, len(audio) - 1, num_samples)
                audio_resampled = np.interp(
                    indices,
                    np.arange(len(audio)),
                    audio.astype(np.float32)
                ).astype(np.int16)
                
                logger.info(
                    f"Resampled STT input from {sample_rate}Hz to {target_sample_rate}Hz "
                    f"({len(audio)} -> {len(audio_resampled)} samples)"
                )
                audio = audio_resampled
                sample_rate = target_sample_rate
            
            # Normalize to float32 [-1.0, 1.0]
            audio_float = audio.astype(np.float32) / 32768.0
            
            logger.debug(
                f"Transcribing audio: {len(audio)} samples, "
                f"{len(audio)/sample_rate:.2f}s duration at {sample_rate}Hz"
            )
            
            # Transcribe
            segments, info = self.model.transcribe(
                audio_float,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=False  # We do VAD separately
            )
            
            # Collect text from segments
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())
            
            text = " ".join(text_parts).strip()
            
            if text:
                logger.info(f"STT result: '{text}' (detected language: {info.language})")
            else:
                logger.warning("STT returned empty text")
            
            return text if text else None
            
        except Exception as e:
            logger.error(f"STT transcription error: {e}", exc_info=True)
            return None
