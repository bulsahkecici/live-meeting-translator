"""Voice Activity Detection using webrtcvad."""
import webrtcvad
import numpy as np
import logging
from typing import Optional, List
from collections import deque

logger = logging.getLogger(__name__)


class VAD:
    """Voice Activity Detection with silence-based segmentation."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        silence_threshold_ms: int = 600,
        min_speech_duration_ms: int = 800,
        max_segment_duration_ms: int = 8000,
        aggressiveness: int = 2
    ):
        """
        Initialize VAD.
        
        Args:
            sample_rate: Audio sample rate (must be 8000, 16000, 32000, or 48000)
            frame_duration_ms: Frame duration in milliseconds (10, 20, or 30)
            silence_threshold_ms: Silence duration to end segment
            min_speech_duration_ms: Minimum speech duration to process
            max_segment_duration_ms: Maximum segment duration before force-ending
            aggressiveness: VAD aggressiveness (0-3)
        """
        if sample_rate not in [8000, 16000, 32000, 48000]:
            raise ValueError(
                f"Sample rate {sample_rate} not supported by webrtcvad. "
                "Must be 8000, 16000, 32000, or 48000."
            )
        
        if frame_duration_ms not in [10, 20, 30]:
            raise ValueError(
                f"Frame duration {frame_duration_ms}ms not supported. "
                "Must be 10, 20, or 30."
            )
        
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.silence_threshold_ms = silence_threshold_ms
        self.min_speech_duration_ms = min_speech_duration_ms
        self.max_segment_duration_ms = max_segment_duration_ms
        
        # Calculate frame size
        self.frame_size = int(sample_rate * frame_duration_ms / 1000)
        
        # Initialize VAD
        self.vad = webrtcvad.Vad(aggressiveness)
        
        # Ring buffer for frames
        self.frame_buffer: deque = deque(maxlen=100)
        
        # Current segment
        self.current_segment: List[bytes] = []
        self.silence_frames: int = 0
        self.speech_frames: int = 0
        self.segment_start_time: Optional[float] = None
        
        logger.info(
            f"VAD initialized: rate={sample_rate}Hz, "
            f"frame={frame_duration_ms}ms, "
            f"silence_threshold={silence_threshold_ms}ms, "
            f"min_speech={min_speech_duration_ms}ms, "
            f"max_segment={max_segment_duration_ms}ms"
        )
    
    def process_audio(self, audio_bytes: bytes) -> Optional[bytes]:
        """
        Process audio data and return segment when speech ends.
        
        Args:
            audio_bytes: Raw audio bytes (int16, mono)
        
        Returns:
            Complete segment bytes or None if no segment ready
        """
        # Convert bytes to numpy array
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        
        # Process in frames
        num_frames = len(audio) // self.frame_size
        
        for i in range(num_frames):
            start_idx = i * self.frame_size
            end_idx = start_idx + self.frame_size
            
            if end_idx > len(audio):
                break
            
            frame = audio[start_idx:end_idx]
            frame_bytes = frame.tobytes()
            
            # Check if frame is speech
            is_speech = self.vad.is_speech(frame_bytes, self.sample_rate)
            
            if is_speech:
                self.silence_frames = 0
                self.speech_frames += 1
                
                if self.segment_start_time is None:
                    self.segment_start_time = len(self.current_segment) * self.frame_duration_ms / 1000.0
                    logger.debug("Speech segment started")
                
                self.current_segment.append(frame_bytes)
            else:
                self.silence_frames += 1
                
                # Add silence frames to segment (for context)
                if len(self.current_segment) > 0:
                    self.current_segment.append(frame_bytes)
            
            # Check for segment completion
            silence_duration_ms = self.silence_frames * self.frame_duration_ms
            
            # Force end if max duration reached
            if len(self.current_segment) > 0:
                segment_duration_ms = len(self.current_segment) * self.frame_duration_ms
                if segment_duration_ms >= self.max_segment_duration_ms:
                    logger.debug(
                        f"Segment force-ended: max duration reached "
                        f"({segment_duration_ms}ms)"
                    )
                    return self._finalize_segment()
            
            # End on silence threshold
            if silence_duration_ms >= self.silence_threshold_ms and len(self.current_segment) > 0:
                segment_duration_ms = len(self.current_segment) * self.frame_duration_ms
                
                # Check minimum speech duration
                if segment_duration_ms >= self.min_speech_duration_ms:
                    logger.debug(
                        f"Segment ended: silence threshold reached "
                        f"({silence_duration_ms}ms silence, "
                        f"{segment_duration_ms}ms total)"
                    )
                    return self._finalize_segment()
                else:
                    # Too short, discard
                    logger.debug(
                        f"Segment too short ({segment_duration_ms}ms), discarding"
                    )
                    self._reset_segment()
        
        return None
    
    def _finalize_segment(self) -> bytes:
        """Finalize current segment and return as bytes."""
        if not self.current_segment:
            return b''
        
        # Concatenate all frames
        segment_bytes = b''.join(self.current_segment)
        
        # Log segment info
        duration_ms = len(self.current_segment) * self.frame_duration_ms
        logger.info(
            f"VAD segment finalized: {duration_ms:.0f}ms, "
            f"{len(segment_bytes)} bytes"
        )
        
        # Reset for next segment
        self._reset_segment()
        
        return segment_bytes
    
    def _reset_segment(self):
        """Reset current segment state."""
        self.current_segment = []
        self.silence_frames = 0
        self.speech_frames = 0
        self.segment_start_time = None
    
    def flush(self) -> Optional[bytes]:
        """
        Flush any pending segment (useful on shutdown).
        
        Returns:
            Final segment bytes or None
        """
        if len(self.current_segment) > 0:
            segment_duration_ms = len(self.current_segment) * self.frame_duration_ms
            if segment_duration_ms >= self.min_speech_duration_ms:
                return self._finalize_segment()
            else:
                self._reset_segment()
        return None

