"""Minimal interfaces used by the translation pipeline."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class SpeechToTextBackend(ABC):
    """Convert a mono PCM speech segment to text."""

    @abstractmethod
    def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000
    ) -> Optional[str]:
        """Transcribe raw int16 mono audio, or return ``None`` on failure."""


class TranslatorBackend(ABC):
    """Translate one text segment for the live pipeline."""

    @abstractmethod
    def translate(self, text: str) -> Optional[str]:
        """Translate text, or return ``None`` on failure."""


class AudioInputBackend(ABC):
    """Audio-input operations required by ``TranslationPipeline``."""

    sample_rate: int

    @abstractmethod
    def start(self) -> None:
        """Start capturing audio."""

    @abstractmethod
    def stop(self) -> None:
        """Stop capturing audio."""

    @abstractmethod
    def read(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """Read one captured audio chunk."""

    @abstractmethod
    def clear_queue(self) -> None:
        """Clear captured chunks using the existing queue policy."""

    @abstractmethod
    def queue_size(self) -> int:
        """Return the number of captured chunks currently queued."""

    def dropped_chunk_count(self) -> int:
        """Return visibly rejected capture chunks, when tracked by the backend."""
        return 0


class AudioOutputBackend(ABC):
    """Audio-output operations required by ``TranslationPipeline``."""

    sample_rate: int

    @abstractmethod
    def play_wav(self, wav_path: Path, blocking: bool = True) -> bool:
        """Play a WAV file."""

    @abstractmethod
    def play_beep(
        self,
        frequency: float = 440.0,
        duration: float = 0.5,
        blocking: bool = True
    ) -> bool:
        """Play a generated beep."""
