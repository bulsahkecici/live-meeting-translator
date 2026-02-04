"""Voice cloning TTS engine stub (placeholder for future implementation)."""
import logging
from pathlib import Path

from .tts_base import TTSEngine

logger = logging.getLogger(__name__)


class CloneTTSEngineStub(TTSEngine):
    """Placeholder for voice cloning TTS engine."""
    
    def __init__(
        self,
        sample_wav_path: str = "",
        model_name: str = "xtts-v2",
        language: str = "en",
        sample_rate: int = 48000
    ):
        """
        Initialize voice cloning TTS engine stub.
        
        Args:
            sample_wav_path: Path to reference audio (not used in stub)
            model_name: Model name (placeholder)
            language: Language code
            sample_rate: Target sample rate
        """
        super().__init__("clone")
        self.sample_wav_path = sample_wav_path
        self.model_name = model_name
        self.language = language
        self.sample_rate = sample_rate
        
        logger.warning(
            "Voice cloning TTS engine is not implemented. "
            "This is a placeholder stub."
        )
    
    def synthesize_to_wav(
        self,
        text: str,
        wav_path: Path,
        sample_rate: int = 48000
    ) -> bool:
        """
        Synthesize text to WAV file (NOT IMPLEMENTED).
        
        Args:
            text: Text to synthesize
            wav_path: Output WAV file path
            sample_rate: Target sample rate
        
        Returns:
            False (always fails)
        """
        logger.error(
            "Voice cloning TTS is not implemented. "
            "Please use 'sapi' or 'edge' engine instead."
        )
        return False
    
    def is_available(self) -> bool:
        """Check if voice cloning is available (always False for stub)."""
        return False

