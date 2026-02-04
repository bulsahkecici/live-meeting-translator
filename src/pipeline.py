"""Main translation pipeline."""
import logging
import time
from pathlib import Path
from typing import Optional
import numpy as np
try:
    import noisereduce as nr
    NOISE_REDUCE_AVAILABLE = True
except ImportError:
    NOISE_REDUCE_AVAILABLE = False


from .audio_in import AudioInput
from .audio_out import AudioOutput
from .vad import VAD
from .stt_whisper import STTWhisper
from .translate_deepl import DeepLTranslator
from .tts_base import TTSEngine
from .tts_sapi import SapiTTSEngine
from .tts_edge import EdgeTTSEngine
from .tts_clone_stub import CloneTTSEngineStub
from .config import Config
from .utils import get_tmp_dir

logger = logging.getLogger(__name__)


class TranslationPipeline:
    """Main translation pipeline orchestrating all components."""
    
    def __init__(self, config: Config):
        """Initialize pipeline with configuration."""
        self.config = config
        self.tmp_dir = get_tmp_dir()
        
        # Initialize components
        self._init_audio()
        self._init_vad()
        self._init_stt()
        self._init_translator()
        self._init_tts()
        
        logger.info("Translation pipeline initialized")
    
    def _init_audio(self):
        """Initialize audio input and output."""
        from .devices import find_device
        
        # Input device
        input_config = self.config.audio_input
        audio_config = self.config.get('audio', {})
        
        input_idx = find_device(
            name_substring=input_config.get('name_substring', ''),
            index_override=input_config.get('index_override'),
            is_input=True
        )
        
        if input_idx is None:
            raise RuntimeError("Could not find audio input device")
        
        # Compat: Try new format first, then old format, then default
        input_sr = (
            input_config.get('sample_rate') or
            audio_config.get('input_sample_rate') or
            16000
        )
        
        self.audio_input = AudioInput(
            device_index=input_idx,
            sample_rate=input_sr,
            channels=1,
            dtype='int16',
            blocksize=self.config.pipeline_config.get('audio_buffer_size', 4800)
        )
        
        # Output device
        output_config = self.config.audio_output
        output_idx = find_device(
            name_substring=output_config.get('name_substring', 'CABLE Input'),
            index_override=output_config.get('index_override'),
            is_input=False
        )
        
        if output_idx is None:
            raise RuntimeError("Could not find audio output device")
        
        # Compat: Try new format first, then old format, then default
        output_sr = (
            output_config.get('sample_rate') or
            audio_config.get('output_sample_rate') or
            48000
        )
        
        self.audio_output = AudioOutput(
            device_index=output_idx,
            sample_rate=output_sr,
            channels=1,
            dtype='int16'
        )
        
        # Log effective config
        logger.info(
            f"Effective audio config: input={input_sr}Hz, output={output_sr}Hz"
        )
    
    def _init_vad(self):
        """Initialize VAD."""
        vad_config = self.config.vad_config
        
        # Compat: Support both new and old key names
        silence_ms = (
            vad_config.get('silence_threshold_ms') or
            vad_config.get('silence_ms') or
            600
        )
        min_speech_ms = (
            vad_config.get('min_speech_duration_ms') or
            vad_config.get('min_speech_ms') or
            800
        )
        max_segment_ms = (
            vad_config.get('max_segment_duration_ms') or
            vad_config.get('max_segment_ms') or
            8000
        )
        
        self.vad = VAD(
            sample_rate=self.audio_input.sample_rate,
            frame_duration_ms=vad_config.get('frame_duration_ms', 30),
            silence_threshold_ms=silence_ms,
            min_speech_duration_ms=min_speech_ms,
            max_segment_duration_ms=max_segment_ms,
            aggressiveness=vad_config.get('aggressiveness', 2)
        )
        
        # Log effective VAD config
        logger.info(
            f"Effective VAD config: silence={silence_ms}ms, "
            f"min_speech={min_speech_ms}ms, max_segment={max_segment_ms}ms"
        )
    
    def _init_stt(self):
        """Initialize STT."""
        stt_config = self.config.stt_config
        self.stt = STTWhisper(
            model=stt_config.get('model', 'small'),
            compute_type=stt_config.get('compute_type', 'int8'),
            device=stt_config.get('device', 'cpu'),
            language=stt_config.get('language', 'tr'),
            beam_size=stt_config.get('beam_size', 1)
        )
    
    def _init_translator(self):
        """Initialize translator."""
        if not self.config.deepl_api_key:
            raise RuntimeError("DeepL API key not configured")
        
        translate_config = self.config.translate_config
        self.translator = DeepLTranslator(
            api_key=self.config.deepl_api_key,
            source_lang=translate_config.get('source_lang', 'TR'),
            target_lang=translate_config.get('target_lang', 'EN'),
            cache_size=translate_config.get('cache_size', 128),
            timeout_seconds=translate_config.get('timeout_seconds', 10),
            retry_max_attempts=translate_config.get('retry_max_attempts', 3),
            retry_backoff=translate_config.get('retry_backoff', [0.5, 1.0, 2.0, 4.0])
        )
    
    def _init_tts(self):
        """Initialize TTS engine based on config."""
        tts_config = self.config.tts_config
        engine_name = tts_config.get('engine', 'sapi').lower()
        
        if engine_name == 'sapi':
            sapi_config = tts_config.get('sapi', {})
            self.tts = SapiTTSEngine(
                voice_substring=sapi_config.get('voice_substring', ''),
                sample_rate=tts_config.get('sample_rate', 48000)
            )
        elif engine_name == 'edge':
            edge_config = tts_config.get('edge', {})
            self.tts = EdgeTTSEngine(
                voice=edge_config.get('voice', 'en-US-AriaNeural'),
                rate=edge_config.get('rate', '+0%'),
                pitch=edge_config.get('pitch', '+0Hz'),
                sample_rate=tts_config.get('sample_rate', 48000)
            )
        elif engine_name == 'clone':
            clone_config = tts_config.get('clone', {})
            self.tts = CloneTTSEngineStub(
                sample_wav_path=clone_config.get('sample_wav_path', ''),
                model_name=clone_config.get('model_name', 'xtts-v2'),
                language=clone_config.get('language', 'en'),
                sample_rate=tts_config.get('sample_rate', 48000)
            )
        else:
            raise ValueError(f"Unknown TTS engine: {engine_name}")
        
        if not self.tts.is_available():
            logger.warning(
                f"TTS engine '{engine_name}' not available. "
                "Falling back to SAPI."
            )
            self.tts = SapiTTSEngine(
                sample_rate=tts_config.get('sample_rate', 48000)
            )
    
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
        queue_size_before = self.audio_input._queue.qsize()
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

