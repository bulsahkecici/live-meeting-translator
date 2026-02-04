"""Base TTS engine interface for pluggable TTS."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TTSEngine(ABC):
    """Abstract base class for TTS engines."""
    
    def __init__(self, name: str):
        """
        Initialize TTS engine.
        
        Args:
            name: Engine name (e.g., 'sapi', 'edge', 'clone')
        """
        self.name = name
        logger.info(f"Initialized TTS engine: {name}")
    
    @abstractmethod
    def synthesize_to_wav(
        self,
        text: str,
        wav_path: Path,
        sample_rate: int = 48000
    ) -> bool:
        """
        Synthesize text to WAV file.
        
        Args:
            text: Text to synthesize
            wav_path: Output WAV file path
            sample_rate: Target sample rate in Hz
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if TTS engine is available.
        
        Returns:
            True if engine can be used, False otherwise
        """
        pass

