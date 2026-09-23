"""Audio output streaming to device."""
import sounddevice as sd
import wave
import numpy as np
import logging
from pathlib import Path
from typing import Optional

from .backend_interfaces import AudioOutputBackend

logger = logging.getLogger(__name__)


class AudioOutput(AudioOutputBackend):
    """Manages audio output stream for playing WAV files."""
    
    def __init__(
        self,
        device_index: int,
        sample_rate: int = 48000,
        channels: int = 1,
        dtype: str = 'int16'
    ):
        """
        Initialize audio output.
        
        Args:
            device_index: Audio device index
            sample_rate: Sample rate in Hz
            channels: Number of channels (1 = mono)
            dtype: Data type ('int16' or 'float32')
        """
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        
        # Verify device
        device_info = sd.query_devices(device_index)
        logger.info(
            f"Audio output: device={device_info['name']}, "
            f"rate={sample_rate}Hz, channels={channels}, dtype={dtype}"
        )
    
    def play_wav(self, wav_path: Path, blocking: bool = True) -> bool:
        """
        Play WAV file to output device.
        
        Args:
            wav_path: Path to WAV file
            blocking: If True, wait for playback to complete
        
        Returns:
            True if successful, False otherwise
        """
        if not wav_path.exists():
            logger.error(f"WAV file not found: {wav_path}")
            return False
        
        try:
            # Read WAV file
            with wave.open(str(wav_path), 'rb') as wav:
                wav_sample_rate = wav.getframerate()
                wav_channels = wav.getnchannels()
                wav_sample_width = wav.getsampwidth()
                frames = wav.readframes(wav.getnframes())
            
            # Convert to numpy array
            if wav_sample_width == 2:
                audio = np.frombuffer(frames, dtype=np.int16)
            elif wav_sample_width == 4:
                audio = np.frombuffer(frames, dtype=np.int32)
            else:
                logger.error(f"Unsupported sample width: {wav_sample_width}")
                return False
            
            # Convert to mono if stereo
            if wav_channels == 2:
                audio = np.clip(audio.reshape(-1, 2).mean(axis=1), -32768, 32767).astype(np.int16)
            elif wav_channels > 2:
                audio = np.clip(audio.reshape(-1, wav_channels).mean(axis=1), -32768, 32767).astype(np.int16)
            
            # Resample if needed
            if wav_sample_rate != self.sample_rate:
                ratio = self.sample_rate / wav_sample_rate
                num_samples = int(len(audio) * ratio)
                indices = np.linspace(0, len(audio) - 1, num_samples)
                audio_resampled_float = np.interp(
                    indices,
                    np.arange(len(audio)),
                    audio.astype(np.float32)
                )
                # Clamp to int16 range to prevent overflow wrap
                audio_resampled = np.clip(audio_resampled_float, -32768, 32767).astype(np.int16)
            else:
                audio_resampled = audio
            
            # Ensure correct shape for sounddevice
            if self.channels == 1:
                audio_resampled = audio_resampled.reshape(-1, 1)
            else:
                # Duplicate for stereo
                audio_resampled = np.column_stack([audio_resampled, audio_resampled])
            
            # Convert to float32 if needed
            if self.dtype == 'float32':
                audio_resampled = audio_resampled.astype(np.float32) / 32768.0
            else:
                audio_resampled = audio_resampled.astype(np.int16)
            
            # Play audio
            logger.debug(
                f"Playing WAV: {len(audio_resampled)} samples, "
                f"{len(audio_resampled)/self.sample_rate:.2f}s"
            )
            
            sd.play(
                audio_resampled,
                samplerate=self.sample_rate,
                device=self.device_index
            )
            
            if blocking:
                sd.wait()
            
            logger.info(f"Audio playback completed: {wav_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error playing WAV: {e}", exc_info=True)
            return False
    
    def play_beep(
        self,
        frequency: float = 440.0,
        duration: float = 0.5,
        blocking: bool = True
    ) -> bool:
        """
        Generate and play a beep tone.
        
        Args:
            frequency: Frequency in Hz
            duration: Duration in seconds
            blocking: If True, wait for playback to complete
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Generate sine wave
            t = np.linspace(0, duration, int(self.sample_rate * duration))
            wave_data = np.sin(2 * np.pi * frequency * t)
            
            # Convert to int16
            if self.dtype == 'int16':
                wave_data = (wave_data * 32767).astype(np.int16)
            else:
                wave_data = wave_data.astype(np.float32)
            
            # Ensure correct shape
            if self.channels == 1:
                wave_data = wave_data.reshape(-1, 1)
            else:
                wave_data = np.column_stack([wave_data, wave_data])
            
            logger.info(f"Playing beep: {frequency}Hz for {duration}s")
            
            sd.play(
                wave_data,
                samplerate=self.sample_rate,
                device=self.device_index
            )
            
            if blocking:
                sd.wait()
            
            return True
            
        except Exception as e:
            logger.error(f"Error playing beep: {e}", exc_info=True)
            return False

    def stop_playback(self) -> None:
        """Interrupt playback started through sounddevice's convenience API."""
        sd.stop()
        logger.info("Audio playback stop requested")
