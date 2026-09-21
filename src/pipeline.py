"""Main translation pipeline."""
import logging
import time
import numpy as np
try:
    import noisereduce as nr
    NOISE_REDUCE_AVAILABLE = True
except ImportError:
    NOISE_REDUCE_AVAILABLE = False

from .backend_factory import PipelineComponents, create_pipeline_components
from .utils import get_tmp_dir

logger = logging.getLogger(__name__)


class TranslationPipeline:
    """Main translation pipeline orchestrating all components."""
    
    def __init__(self, config, components: PipelineComponents = None):
        """Initialize from config or a complete injected component bundle."""
        self.config = config
        self.tmp_dir = get_tmp_dir()

        if components is None:
            components = create_pipeline_components(config)

        self.audio_input = components.audio_input
        self.audio_output = components.audio_output
        self.vad = components.vad
        self.stt = components.stt
        self.translator = components.translator
        self.tts = components.tts
        
        logger.info("Translation pipeline initialized")
    
    def process_segment(self, audio_bytes: bytes) -> bool:
        """
        Process a single audio segment through the pipeline.
        
        Args:
            audio_bytes: Raw audio bytes (int16, mono)
        
        Returns:
            True if successful, False otherwise
        """
        start_time = time.time()
        
        # Clear audio input queue backlog before processing to prevent latency buildup
        # This ensures we process recent speech, not old buffered audio
        queue_size_before = self.audio_input.queue_size()
        if queue_size_before > 50:  # If queue has significant backlog
            self.audio_input.clear_queue()
            logger.debug(f"Cleared audio queue backlog ({queue_size_before} chunks)")
        
        # Noise Reduction
        if NOISE_REDUCE_AVAILABLE:
            try:
                # Convert to numpy (int16)
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                # Convert to float32 for processing
                audio_float = audio_np.astype(np.float32) / 32768.0
                
                # Apply noise reduction (stationary=True for general background noise)
                # This is fast enough for segments (1-5s) on modern CPUs
                clean_float = nr.reduce_noise(
                    y=audio_float, 
                    sr=self.audio_input.sample_rate, 
                    stationary=True,
                    n_fft=512  # Lower n_fft for speed
                )
                
                # Convert back to int16 bytes
                clean_int16 = (clean_float * 32768.0).astype(np.int16)
                audio_bytes = clean_int16.tobytes()
                logger.info("Noise reduction applied")
            except Exception as e:
                logger.warning(f"Noise reduction failed: {e}")

        # STT
        logger.info("Processing segment: STT...")
        tr_text = self.stt.transcribe(audio_bytes, self.audio_input.sample_rate)
        
        if not tr_text:
            logger.warning("STT returned no text, skipping segment")
            return False
        
        stt_time = time.time() - start_time
        logger.info(f"STT completed in {stt_time:.2f}s: '{tr_text}'")
        
        # Warn if STT detected common phrases that might be false positives
        common_false_positives = [
            "videoyu izlediğiniz için teşekkürler",
            "videoyu izlediğiniz için",
            "thank you for watching",
            "bir sonraki videoda görüşürüz"
        ]
        tr_lower = tr_text.lower()
        for phrase in common_false_positives:
            if phrase in tr_lower:
                logger.warning(
                    f"STT detected common phrase '{phrase}' - "
                    "This might be a false positive from background audio. "
                    "Please verify if you actually said this."
                )
        
        # Translation
        translate_start = time.time()
        logger.info("Translating...")
        en_text = self.translator.translate(tr_text)
        
        if not en_text:
            logger.error(
                f"Translation failed for: '{tr_text}'. "
                "Printing Turkish text for manual translation."
            )
            print(f"\n[TURKISH] {tr_text}")
            print("[ENGLISH] <translation failed - please translate manually>\n")
            return False
        
        translate_time = time.time() - translate_start
        logger.info(f"Translation completed in {translate_time:.2f}s: '{en_text}'")
        
        # Print for manual fallback
        print(f"\n[TURKISH] {tr_text}")
        print(f"[ENGLISH] {en_text}\n")
        
        # TTS
        tts_start = time.time()
        logger.info("Synthesizing speech...")
        
        wav_path = self.tmp_dir / f"tts_{int(time.time() * 1000)}.wav"
        success = self.tts.synthesize_to_wav(
            en_text,
            wav_path,
            sample_rate=self.audio_output.sample_rate
        )
        
        if not success:
            logger.error(f"TTS failed for: '{en_text}'. Text printed above for manual use.")
            return False
        
        tts_time = time.time() - tts_start
        logger.info(f"TTS completed in {tts_time:.2f}s")
        
        # Audio output
        output_start = time.time()
        logger.info("Playing audio...")
        play_success = self.audio_output.play_wav(wav_path, blocking=True)
        
        if not play_success:
            logger.error("Audio playback failed")
            return False
        
        output_time = time.time() - output_start
        total_time = time.time() - start_time
        
        logger.info(
            f"Segment processing complete: "
            f"STT={stt_time:.2f}s, "
            f"Translate={translate_time:.2f}s, "
            f"TTS={tts_time:.2f}s, "
            f"Output={output_time:.2f}s, "
            f"Total={total_time:.2f}s"
        )
        
        # Cleanup
        try:
            wav_path.unlink()
        except Exception as e:
            logger.warning(f"Could not delete temp WAV: {e}")
        
        return True
    
    def run_live(self):
        """Run live translation pipeline."""
        logger.info("Starting live translation pipeline...")
        
        try:
            self.audio_input.start()
            
            logger.info("Listening for speech. Speak in Turkish...")
            print("\n=== LIVE TRANSLATION ACTIVE ===")
            print("Speak in Turkish. Pause after each sentence.\n")
            
            self._running = True
            while self._running:
                # Read audio data
                audio_chunk = self.audio_input.read(timeout=0.1)
                
                if audio_chunk is None:
                    continue
                
                # Process through VAD
                segment = self.vad.process_audio(audio_chunk)
                
                if segment:
                    # Process segment
                    self.process_segment(segment)
                    # Drop backlog accumulated while STT/Translate/TTS was running
                    self.audio_input.clear_queue()
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            print("\n=== STOPPING ===")
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            raise
        finally:
            # Flush VAD
            final_segment = self.vad.flush()
            if final_segment:
                self.process_segment(final_segment)
            
            self.audio_input.stop()
            logger.info("Pipeline stopped")
    
    def stop(self):
        """Stop the live translation loop."""
        self._running = False
        logger.info("Stopping pipeline requested...")

    def run_dryrun(self, text: str):
        """
        Run dry-run mode: text -> translate -> TTS -> output.
        
        Args:
            text: Turkish text to process
        """
        logger.info(f"Dry-run mode: processing text '{text}'")
        
        # Translation
        en_text = self.translator.translate(text)
        
        if not en_text:
            logger.error("Translation failed")
            print(f"[TURKISH] {text}")
            print("[ENGLISH] <translation failed>")
            return
        
        print(f"[TURKISH] {text}")
        print(f"[ENGLISH] {en_text}")
        
        # TTS
        wav_path = self.tmp_dir / f"dryrun_{int(time.time() * 1000)}.wav"
        success = self.tts.synthesize_to_wav(
            en_text,
            wav_path,
            sample_rate=self.audio_output.sample_rate
        )
        
        if not success:
            logger.error("TTS failed")
            return
        
        # Output
        self.audio_output.play_wav(wav_path, blocking=True)
        
        # Cleanup
        try:
            wav_path.unlink()
        except Exception:
            pass
    
    def run_test(self):
        """Run test mode: TTS test phrase -> output."""
        test_text = "This is a test of the translation system. One, two, three."
        logger.info(f"Test mode: synthesizing '{test_text}'")
        
        wav_path = self.tmp_dir / f"test_{int(time.time() * 1000)}.wav"
        success = self.tts.synthesize_to_wav(
            test_text,
            wav_path,
            sample_rate=self.audio_output.sample_rate
        )
        
        if not success:
            logger.error("TTS test failed")
            return
        
        print(f"\nPlaying test phrase: '{test_text}'")
        self.audio_output.play_wav(wav_path, blocking=True)
        
        # Cleanup
        try:
            wav_path.unlink()
        except Exception:
            pass
    
    def run_beep(self):
        """Run beep mode: generate beep -> output."""
        logger.info("Beep mode: generating 440Hz beep")
        print("\nPlaying 440Hz beep for 0.5 seconds...")
        self.audio_output.play_beep(frequency=440.0, duration=0.5, blocking=True)
