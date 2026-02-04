"""Windows SAPI TTS engine."""
import subprocess
import logging
import wave
import numpy as np
from pathlib import Path
from typing import Optional

from .tts_base import TTSEngine

logger = logging.getLogger(__name__)


class SapiTTSEngine(TTSEngine):
    """Windows SAPI TTS engine using PowerShell."""
    
    def __init__(self, voice_substring: str = "", sample_rate: int = 48000):
        """
        Initialize SAPI TTS engine.
        
        Args:
            voice_substring: Optional voice name substring to match
            sample_rate: Target sample rate (default 48000)
        """
        super().__init__("sapi")
        self.voice_substring = voice_substring
        self.sample_rate = sample_rate
        self.selected_voice: Optional[str] = None
        
        # Find and select voice
        self._select_voice()
        
        logger.info(f"SAPI TTS initialized: voice={self.selected_voice}")
    
    def _select_voice(self):
        """Select SAPI voice by substring match or use default."""
        try:
            # Get available voices
            ps_script = """
            Add-Type -AssemblyName System.Speech
            $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
            $synth.GetInstalledVoices() | ForEach-Object {
                $_.VoiceInfo.Name
            }
            $synth.Dispose()
            """
            
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.warning("Could not list SAPI voices, using default")
                self.selected_voice = None
                return
            
            voices = [v.strip() for v in result.stdout.strip().split('\n') if v.strip()]
            
            if not voices:
                logger.warning("No SAPI voices found, using default")
                self.selected_voice = None
                return
            
            logger.debug(f"Available SAPI voices: {voices}")
            
            # Match by substring
            if self.voice_substring:
                voice_lower = self.voice_substring.lower()
                for voice in voices:
                    if voice_lower in voice.lower():
                        self.selected_voice = voice
                        logger.info(f"Selected SAPI voice: {voice}")
                        return
            
            # Use first available voice
            self.selected_voice = voices[0]
            logger.info(f"Using default SAPI voice: {voices[0]}")
            
        except Exception as e:
            logger.warning(f"Error selecting SAPI voice: {e}, using default")
            self.selected_voice = None
    
    def synthesize_to_wav(
        self,
        text: str,
        wav_path: Path,
        sample_rate: int = 48000
    ) -> bool:
        """
        Synthesize text to WAV file using SAPI.
        
        Args:
            text: Text to synthesize
            wav_path: Output WAV file path
            sample_rate: Target sample rate (must be 48000 for SAPI)
        
        Returns:
            True if successful, False otherwise
        """
        if not text or not text.strip():
            logger.warning("Empty text for TTS")
            return False
        
        try:
            # SAPI typically outputs at 16kHz or 22kHz, we'll need to resample
            # But first, let's try to get it at a reasonable rate
            
            # Create PowerShell script to synthesize
            voice_select = ""
            if self.selected_voice:
                voice_select = f'$synth.SelectVoice("{self.selected_voice}")'
            
            # Escape quotes for PowerShell (do this outside f-string)
            escaped_text = text.replace('"', '\\"')
            
            ps_script = f"""
            Add-Type -AssemblyName System.Speech
            $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
            {voice_select}
            $synth.SetOutputToWaveFile("{wav_path.as_posix()}")
            $synth.Speak("{escaped_text}")
            $synth.Dispose()
            """
            
            logger.debug(f"Synthesizing with SAPI: '{text[:50]}...'")
            
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                logger.error(f"SAPI synthesis failed: {result.stderr}")
                return False
            
            if not wav_path.exists():
                logger.error(f"SAPI output file not created: {wav_path}")
                return False
            
            # SAPI WAV files are typically 16kHz or 22kHz mono 16-bit
            # We need to resample to 48kHz and ensure mono 16-bit
            self._resample_wav(wav_path, sample_rate)
            
            logger.info(f"SAPI synthesis successful: {wav_path}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("SAPI synthesis timeout")
            return False
        except Exception as e:
            logger.error(f"SAPI synthesis error: {e}", exc_info=True)
            return False
    
    def _resample_wav(self, wav_path: Path, target_rate: int):
        """
        Resample WAV file to target sample rate and ensure mono 16-bit PCM.
        
        Args:
            wav_path: WAV file path
            target_rate: Target sample rate
        """
        try:
            # Read WAV file
            with wave.open(str(wav_path), 'rb') as wav_in:
                sample_rate = wav_in.getframerate()
                channels = wav_in.getnchannels()
                sample_width = wav_in.getsampwidth()
                frames = wav_in.readframes(wav_in.getnframes())
            
            # Convert to numpy array
            if sample_width == 2:
                audio = np.frombuffer(frames, dtype=np.int16)
            elif sample_width == 4:
                audio = np.frombuffer(frames, dtype=np.int32)
            else:
                logger.error(f"Unsupported sample width: {sample_width}")
                return
            
            # Convert to mono if stereo
            if channels == 2:
                audio = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)
            elif channels > 2:
                audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
            
            # Resample if needed
            if sample_rate != target_rate:
                # Simple linear resampling (for stability, avoid scipy)
                # Calculate resampling ratio
                ratio = target_rate / sample_rate
                num_samples = int(len(audio) * ratio)
                
                # Linear interpolation
                indices = np.linspace(0, len(audio) - 1, num_samples)
                audio_resampled = np.interp(indices, np.arange(len(audio)), audio.astype(np.float32))
                audio_resampled = audio_resampled.astype(np.int16)
            else:
                audio_resampled = audio
            
            # Write WAV file (mono, 16-bit, target_rate)
            with wave.open(str(wav_path), 'wb') as wav_out:
                wav_out.setnchannels(1)  # Mono
                wav_out.setsampwidth(2)  # 16-bit
                wav_out.setframerate(target_rate)
                wav_out.writeframes(audio_resampled.tobytes())
            
            logger.debug(
                f"Resampled WAV: {sample_rate}Hz {channels}ch -> "
                f"{target_rate}Hz 1ch"
            )
            
        except Exception as e:
            logger.error(f"Error resampling WAV: {e}", exc_info=True)
    
    def is_available(self) -> bool:
        """Check if SAPI is available (Windows only)."""
        try:
            # Try to create a synthesizer
            ps_script = """
            Add-Type -AssemblyName System.Speech
            $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
            $synth.Dispose()
            exit 0
            """
            
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                timeout=5
            )
            
            return result.returncode == 0
        except Exception:
            return False

