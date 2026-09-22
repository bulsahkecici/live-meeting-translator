import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import yaml

from scripts.benchmark_stt import load_manifest
from scripts.record_stt_benchmark import parse_device
from src.backend_factory import BackendFactory, PipelineComponents
from src.backend_interfaces import SpeechToTextBackend
from src.pipeline import TranslationPipeline
from src.runtime_platform import RuntimePlatform
from src.stt_metrics import (
    character_error_rate,
    normalize_transcript,
    word_error_rate,
)
from src.stt_mlx import MLXWhisperBackend, pcm16_to_float32


class FakeConfig:
    def __init__(self, stt=None):
        self._stt = stt or {}

    @property
    def stt_config(self):
        return self._stt


class MLXBackendTests(unittest.TestCase):
    def test_backend_satisfies_contract_and_preloads_exact_model(self):
        loader = Mock()
        backend = MLXWhisperBackend(
            model="mlx-community/whisper-small-mlx",
            language="tr",
            beam_size=1,
            transcribe_fn=Mock(),
            model_loader=loader,
        )

        self.assertIsInstance(backend, SpeechToTextBackend)
        self.assertEqual(backend.model_name, "mlx-community/whisper-small-mlx")
        self.assertEqual(backend.language, "tr")
        loader.assert_called_once_with("mlx-community/whisper-small-mlx")

    def test_transcribe_uses_in_memory_waveform_and_propagates_options(self):
        transcribe = Mock(
            return_value={"text": "  Yapay   zekâ\nçalışıyor.  ", "language": "tr"}
        )
        backend = MLXWhisperBackend(
            model="mlx-community/whisper-small-mlx",
            language="tr",
            beam_size=1,
            transcribe_fn=transcribe,
        )
        pcm = np.array([-32768, 0, 32767], dtype=np.int16).tobytes()

        with self.assertLogs("src.stt_mlx", level="INFO") as logs:
            result = backend.transcribe(pcm, 16000)

        self.assertEqual(result, "Yapay zekâ çalışıyor.")
        waveform = transcribe.call_args.args[0]
        self.assertIsInstance(waveform, np.ndarray)
        self.assertEqual(waveform.dtype, np.float32)
        self.assertFalse(isinstance(waveform, (str, Path)))
        self.assertTrue(np.allclose(waveform, [-1.0, 0.0, 32767 / 32768]))
        self.assertEqual(
            transcribe.call_args.kwargs,
            {
                "path_or_hf_repo": "mlx-community/whisper-small-mlx",
                "language": "tr",
                "task": "transcribe",
                "temperature": 0.0,
                "verbose": None,
                "word_timestamps": False,
            },
        )
        self.assertTrue(any("STT result:" in message for message in logs.output))

    def test_transcribe_uses_serialized_stream_runner_from_worker_thread(self):
        transcribe = Mock(return_value={"text": "merhaba", "language": "tr"})
        runner_threads = []

        def run_on_stream(operation):
            runner_threads.append(threading.current_thread().name)
            return operation()

        backend = MLXWhisperBackend(
            transcribe_fn=transcribe,
            stream_runner=run_on_stream,
        )
        pcm = np.array([0, 1], dtype=np.int16).tobytes()
        result = {}

        worker = threading.Thread(
            target=lambda: result.setdefault("text", backend.transcribe(pcm)),
            name="test-stt-worker",
        )
        worker.start()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result["text"], "merhaba")
        self.assertEqual(runner_threads, ["test-stt-worker"])
        transcribe.assert_called_once()

    def test_non_16khz_audio_is_resampled_in_memory(self):
        pcm = np.array([-32768, -16384, 0, 32767], dtype=np.int16).tobytes()
        waveform = pcm16_to_float32(pcm, sample_rate=8000)

        self.assertEqual(waveform.dtype, np.float32)
        self.assertEqual(waveform.shape, (8,))
        self.assertAlmostEqual(float(waveform[0]), -1.0)
        self.assertAlmostEqual(float(waveform[-1]), 32767 / 32768)

    def test_empty_result_and_inference_error_return_none(self):
        empty_backend = MLXWhisperBackend(
            transcribe_fn=Mock(return_value={"text": "   ", "language": "tr"})
        )
        error_backend = MLXWhisperBackend(
            transcribe_fn=Mock(side_effect=RuntimeError("inference failed"))
        )
        pcm = np.array([0], dtype=np.int16).tobytes()

        self.assertIsNone(empty_backend.transcribe(pcm))
        self.assertIsNone(error_backend.transcribe(pcm))

    def test_unsupported_beam_search_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "only greedy decoding"):
            MLXWhisperBackend(
                beam_size=2,
                transcribe_fn=Mock(),
            )

    def test_absent_dependency_and_metal_initialization_errors_are_clear(self):
        missing = ModuleNotFoundError("No module named 'mlx_whisper'")
        missing.name = "mlx_whisper"
        with patch("src.stt_mlx.import_module", side_effect=missing):
            with self.assertRaisesRegex(RuntimeError, "mlx-whisper.*required"):
                MLXWhisperBackend()

        with patch(
            "src.stt_mlx.import_module",
            side_effect=ImportError("No Metal device available"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Failed to initialize MLX/Metal"):
                MLXWhisperBackend()


class MLXFactoryTests(unittest.TestCase):
    def setUp(self):
        self.macos = RuntimePlatform.from_values("Darwin", "arm64")
        self.windows = RuntimePlatform.from_values("Windows", "AMD64")

    def test_factory_selects_mlx_and_propagates_model_and_language(self):
        constructor = Mock(return_value=object())
        config = FakeConfig(
            {
                "backend": "mlx-whisper",
                "model": "mlx-community/whisper-large-v3-turbo",
                "language": "tr",
                "beam_size": 1,
            }
        )

        with patch("src.backend_factory._load_symbol", return_value=constructor) as load:
            result = BackendFactory(config, self.macos).create_stt()

        self.assertIs(result, constructor.return_value)
        load.assert_called_once_with(".stt_mlx", "MLXWhisperBackend")
        constructor.assert_called_once_with(
            model="mlx-community/whisper-large-v3-turbo",
            language="tr",
            beam_size=1,
        )

    def test_explicit_mlx_without_model_uses_mlx_small(self):
        constructor = Mock(return_value=object())
        with patch("src.backend_factory._load_symbol", return_value=constructor):
            BackendFactory(
                FakeConfig({"backend": "mlx-whisper"}), self.macos
            ).create_stt()

        self.assertEqual(
            constructor.call_args.kwargs["model"],
            "mlx-community/whisper-small-mlx",
        )

    def test_mlx_fails_clearly_off_apple_silicon(self):
        with self.assertRaisesRegex(RuntimeError, "requires Apple Silicon macOS"):
            BackendFactory(
                FakeConfig({"backend": "mlx-whisper"}), self.windows
            ).create_stt()

    def test_existing_default_and_invalid_backend_behavior_remain(self):
        constructor = Mock(return_value=object())
        with patch("src.backend_factory._load_symbol", return_value=constructor) as load:
            BackendFactory(FakeConfig(), self.windows).create_stt()
        load.assert_called_once_with(".stt_whisper", "STTWhisper")

        with self.assertRaisesRegex(ValueError, "Unknown STT backend: mlx"):
            BackendFactory(
                FakeConfig({"backend": "mlx"}), self.macos
            ).create_stt()

    def test_factory_created_mlx_backend_can_be_injected_into_pipeline(self):
        transcribe = Mock(return_value={"text": "merhaba", "language": "tr"})

        def constructor(**kwargs):
            return MLXWhisperBackend(
                **kwargs,
                transcribe_fn=transcribe,
                model_loader=Mock(),
            )

        with patch("src.backend_factory._load_symbol", return_value=constructor):
            stt = BackendFactory(
                FakeConfig({"backend": "mlx-whisper"}), self.macos
            ).create_stt()

        audio_input = Mock(sample_rate=16000)
        audio_input.queue_size.return_value = 0
        audio_output = Mock(sample_rate=48000)
        audio_output.play_wav.return_value = True
        translator = Mock()
        translator.translate.return_value = "hello"
        tts = Mock()

        def synthesize(_text, path, sample_rate):
            path.touch()
            return True

        tts.synthesize_to_wav.side_effect = synthesize
        components = PipelineComponents(
            audio_input=audio_input,
            audio_output=audio_output,
            vad=Mock(),
            stt=stt,
            translator=translator,
            tts=tts,
        )
        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ), patch("src.pipeline.NOISE_REDUCE_AVAILABLE", False):
            pipeline = TranslationPipeline(FakeConfig(), components=components)
            pcm = np.array([0, 1], dtype=np.int16).tobytes()
            self.assertTrue(pipeline.process_segment(pcm))

        self.assertIs(pipeline.stt, stt)
        translator.translate.assert_called_once_with("merhaba")
        tts.synthesize_to_wav.assert_called_once()
        audio_output.play_wav.assert_called_once()


class TranscriptMetricTests(unittest.TestCase):
    def test_normalization_preserves_turkish_characters(self):
        self.assertEqual(
            normalize_transcript("  İSTANBUL, IĞDIR; ŞÖĞÜÇ!  "),
            "istanbul ığdır şöğüç",
        )

    def test_known_word_and_character_error_rates(self):
        self.assertEqual(word_error_rate("bir iki üç", "bir dört üç"), 1 / 3)
        self.assertEqual(character_error_rate("şal", "sal"), 1 / 3)
        self.assertEqual(word_error_rate("", "fazla"), 1.0)
        self.assertEqual(character_error_rate("", "x"), 1.0)


class BenchmarkManifestTests(unittest.TestCase):
    def test_recorder_device_parser_accepts_index_or_name(self):
        self.assertEqual(parse_device("3"), 3)
        self.assertEqual(parse_device("MacBook Pro Mikrofonu"), "MacBook Pro Mikrofonu")

    def test_manifest_rejects_absolute_audio_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            absolute_audio_path = str(
                (Path(tmp_dir) / "not-allowed.wav").resolve()
            )
            items = [
                {
                    "id": f"item-{index}",
                    "reference_text": "örnek",
                    "category": "test",
                    "audio_filename": absolute_audio_path,
                }
                for index in range(8)
            ]
            manifest_path = Path(tmp_dir) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"schema_version": 1, "items": items}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "repository-relative"):
                load_manifest(manifest_path)


class MacDeploymentConfigTests(unittest.TestCase):
    def test_primary_mac_profile_selects_benchmarked_turbo_model(self):
        repository_root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load(
            (repository_root / "config.yaml").read_text(encoding="utf-8-sig")
        )
        example = yaml.safe_load(
            (repository_root / "config.yaml.example").read_text(encoding="utf-8")
        )

        self.assertEqual(
            config["audio"]["input"]["name_substring"],
            "MacBook Pro Mikrofonu",
        )
        self.assertEqual(
            config["audio"]["output"]["name_substring"],
            "BlackHole 2ch",
        )
        self.assertEqual(config["stt"]["backend"], "mlx-whisper")
        self.assertEqual(
            config["stt"]["model"],
            "mlx-community/whisper-large-v3-turbo",
        )
        self.assertEqual(example["stt"]["backend"], "faster-whisper")


if __name__ == "__main__":
    unittest.main()
