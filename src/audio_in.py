"""Audio input capture using sounddevice."""
import sounddevice as sd
import numpy as np
import logging
import queue
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AudioInput:
    """Manages audio input stream with callback-based capture."""
    
    def __init__(
        self,
        device_index: int,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = 'int16',
        blocksize: int = 4800,  # ~300ms at 16kHz
        callback: Optional[Callable] = None
    ):
        """
        Initialize audio input stream.
        
        Args:
            device_index: Audio device index
            sample_rate: Sample rate in Hz
            channels: Number of channels (1 = mono)
            dtype: Data type ('int16' or 'float32')
            blocksize: Block size in samples
            callback: Optional callback function(indata, frames, time, status)
        """
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self.callback = callback
        
        self.stream: Optional[sd.InputStream] = None
        # Queue with maxsize to prevent memory buildup (backpressure)
        # ~100-300 chunks: ~100 chunks = ~30s at 16kHz with 4800 block size
        queue_maxsize = 200
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        
        # Verify device
        device_info = sd.query_devices(device_index)
        logger.info(
            f"Audio input: device={device_info['name']}, "
            f"rate={sample_rate}Hz, channels={channels}, dtype={dtype}"
        )
    
    def _audio_callback(self, indata, frames, time, status):
        """Internal callback that enqueues audio data."""
        if status:
            logger.warning(f"Audio input status: {status}")
        
        # Convert to int16 if needed
        if self.dtype == 'int16':
            if indata.dtype != np.int16:
                # Normalize and convert
                indata_int16 = (indata * 32767).astype(np.int16)
            else:
                indata_int16 = indata.copy()
            
            # Ensure mono
            if indata_int16.shape[1] > 1:
                indata_int16 = indata_int16[:, 0:1]
            
            audio_bytes = indata_int16.tobytes()
        else:
            # float32
            if indata.shape[1] > 1:
                indata = indata[:, 0:1]
            audio_bytes = indata.tobytes()
        
        # Enqueue with backpressure handling: drop oldest if queue is full
        try:
            self._queue.put_nowait(audio_bytes)
        except queue.Full:
            # Queue is full - drop oldest chunk(s) to make room
            dropped = 0
            while not self._queue.empty() and dropped < 10:  # Drop up to 10 old chunks
                try:
                    self._queue.get_nowait()
                    dropped += 1
                except queue.Empty:
                    break
            
            # Now try to put the new chunk
            try:
                self._queue.put_nowait(audio_bytes)
                if dropped > 0:
                    logger.debug(
                        f"Audio queue full, dropped {dropped} old chunk(s) "
                        f"(queue size: {self._queue.qsize()})"
                    )
            except queue.Full:
                # Still full after dropping - log warning but don't crash
                logger.warning(
                    f"Audio queue still full after dropping chunks, "
                    f"skipping current chunk (queue size: {self._queue.qsize()})"
                )
        
        # User callback if provided
        if self.callback:
            try:
                self.callback(indata, frames, time, status)
            except Exception as e:
                logger.error(f"Error in audio callback: {e}", exc_info=True)
    
    def start(self):
        """Start audio input stream."""
        if self.stream is not None:
            logger.warning("Audio input stream already started")
            return
        
        try:
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=self.channels,
                samplerate=self.sample_rate,
                dtype=self.dtype,
                blocksize=self.blocksize,
                callback=self._audio_callback
            )
            self.stream.start()
            logger.info("Audio input stream started")
        except Exception as e:
            logger.error(f"Failed to start audio input: {e}", exc_info=True)
            raise
    
    def stop(self):
        """Stop audio input stream."""
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
            logger.info("Audio input stream stopped")
    
    def read(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        Read audio data from queue.
        
        Args:
            timeout: Timeout in seconds (None = non-blocking)
        
        Returns:
            Audio data as bytes or None if timeout
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def read_all(self) -> list:
        """Read all available audio data from queue (non-blocking)."""
        data = []
        while True:
            chunk = self.read(timeout=0)
            if chunk is None:
                break
            data.append(chunk)
        return data
    
    def clear_queue(self):
        """Clear the audio queue."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

