"""Edge TTS engine using Python edge-tts package."""
import asyncio
import logging
import inspect
from pathlib import Path

from .tts_base import TTSEngine

logger = logging.getLogger(__name__)

# Try to import edge_tts
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    edge_tts = None

# Edge TTS output formats for RIFF PCM
SUPPORTED_EDGE_TTS_RIFF_FORMATS = {
    8000: "riff-8khz-16bit-mono-pcm",
    16000: "riff-16khz-16bit-mono-pcm",
    24000: "riff-24khz-16bit-mono-pcm",
    48000: "riff-48khz-16bit-mono-pcm",
}

def _nearest_supported_sr(sr: int) -> int:
    return min(SUPPORTED_EDGE_TTS_RIFF_FORMATS.keys(), key=lambda x: abs(x - sr))


class EdgeTTSEngine(TTSEngine):
    """Edge TTS engine using Python edge-tts package."""
    
    def __init__(
        self,
        voice: str = "en-US-AriaNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        sample_rate: int = 48000
    ):
        """
        Initialize Edge TTS engine.
        
        Args:
            voice: Edge TTS voice name
            rate: Speech rate adjustment
            pitch: Pitch adjustment
            sample_rate: Target sample rate
        """
        super().__init__("edge")
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.sample_rate = sample_rate
        self._supports_output_format = False
        
        if not EDGE_TTS_AVAILABLE:
            logger.warning("edge-tts Python package not installed")
        else:
            # Check if edge_tts.Communicate supports output_format parameter
            # Assume support by default (newer versions might hide it in **kwargs or change signature)
            self._supports_output_format = True
    
    def synthesize_to_wav(
        self,
        text: str,
        wav_path: Path,
        sample_rate: int = 48000
    ) -> bool:
        """
        Synthesize text to WAV file using Edge TTS.
        
        Args:
            text: Text to synthesize
            wav_path: Output WAV file path
            sample_rate: Target sample rate (must be 8000, 16000, 24000, or 48000)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            logger.error("Edge TTS not available (edge-tts package not installed)")
            return False
        
        if not text or not text.strip():
            logger.warning("Empty text for TTS")
            return False
        
        try:
            return asyncio.run(self._synthesize_async(text, wav_path, sample_rate))
        except Exception as e:
            logger.error(f"Edge TTS synthesis error: {e}", exc_info=True)
            return False
    
    async def _synthesize_async(
        self,
        text: str,
        wav_path: Path,
        sample_rate: int
    ) -> bool:
        """Async synthesis using edge_tts. Produces RIFF/WAV (PCM) output."""
        try:
            if not EDGE_TTS_AVAILABLE:
                logger.error("Edge TTS not available (edge-tts package not installed)")
                return False

            sr = sample_rate
            if sr not in SUPPORTED_EDGE_TTS_RIFF_FORMATS:
                nearest = _nearest_supported_sr(sr)
                logger.warning(f"Edge TTS: sample_rate {sr} not supported, using {nearest}")
                sr = nearest

            # Note: edge-tts 7.2.0+ no longer accepts output_format parameter
            # The library now defaults to WAV format which is what we need
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch
            )

            logger.debug(f"Synthesizing with Edge TTS (voice={self.voice}): '{text[:50]}...'")

            # Preferred: let edge_tts write the file
            if hasattr(communicate, "save"):
                await communicate.save(str(wav_path))
            else:
                # Fallback: stream bytes and write to file
                audio_bytes = b""
                async for chunk in communicate.stream():
                    if isinstance(chunk, dict) and chunk.get("type") == "audio":
                        audio_bytes += chunk.get("data", b"")
                    elif isinstance(chunk, (bytes, bytearray)):
                        audio_bytes += bytes(chunk)

                if not audio_bytes:
                    logger.error("Edge TTS returned no audio data")
                    return False

                wav_path.write_bytes(audio_bytes)


            # Check if output is WAV or MP3
            with open(wav_path, "rb") as f:
                header = f.read(4)
            
            # If MP3, convert to WAV
            if header != b"RIFF":
                logger.info("Edge TTS output is MP3, converting to WAV...")
                try:
                    # Import pydub for MP3 conversion
                    from pydub import AudioSegment
                    
                    # Read MP3 and convert to WAV
                    mp3_path = wav_path.with_suffix('.mp3')
                    wav_path.rename(mp3_path)
                    
                    audio = AudioSegment.from_mp3(str(mp3_path))
                    
                    # Export as WAV with target sample rate
                    audio = audio.set_frame_rate(sr)
                    audio = audio.set_channels(1)  # Mono
                    audio.export(str(wav_path), format="wav")
                    
                    # Clean up MP3 file
                    mp3_path.unlink()
                    logger.info(f"Converted MP3 to WAV: {wav_path}")
                    
                except ImportError:
                    logger.error(
                        "Edge TTS output is MP3 but pydub is not installed. "
                        "Install with: pip install pydub"
                    )
                    return False
                except Exception as e:
                    logger.error(f"Failed to convert MP3 to WAV: {e}", exc_info=True)
                    return False

            logger.info(f"Edge TTS synthesis successful: {wav_path}")
            return True

        except TypeError as e:
            # Most common cause: output_format unsupported on older edge-tts
            logger.error(f"Edge TTS API mismatch: {e}. Try: pip install -U edge-tts", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Edge TTS async synthesis error: {e}", exc_info=True)
            return False
    
    def is_available(self) -> bool:
        """Check if Edge TTS is available (requires edge-tts with output_format support)."""
        return EDGE_TTS_AVAILABLE and self._supports_output_format
