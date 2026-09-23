import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.backend_factory import BackendFactory, PipelineComponents
from src.pipeline import TranslationPipeline
from src.runtime_platform import OperatingSystem, RuntimePlatform


class FakeConfig:
    def __init__(
        self,
        *,
        stt=None,
        translate=None,
        tts=None,
        audio=None,
        vad=None,
        pipeline=None,
        deepl_api_key="test-key",
    ):
        self._audio = audio or {}
        self._stt = stt or {}
        self._translate = translate or {}
        self._tts = tts or {}
        self._vad = vad or {}
        self._pipeline = pipeline or {}
        self.deepl_api_key = deepl_api_key

    def get(self, key, default=None):
        return {"audio": self._audio}.get(key, default)

    @property
    def audio_input(self):
        return self._audio.get("input", {})

    @property
    def audio_output(self):
        return self._audio.get("output", {})

    @property
    def stt_config(self):
        return self._stt

    @property
    def translate_config(self):
        return self._translate

    @property
    def tts_config(self):
        return self._tts

    @property
    def vad_config(self):
        return self._vad

    @property
    def pipeline_config(self):
        return self._pipeline


class FakeAudioInput:
    sample_rate = 16000

    def __init__(self, queued_chunks=0, chunks=None):
        self.cleared = 0
        self.queued_chunks = queued_chunks
        self.chunks = list(chunks or [])
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def read(self, timeout=None):
        return self.chunks.pop(0) if self.chunks else None

    def clear_queue(self):
        self.cleared += 1

    def queue_size(self):
        return self.queued_chunks


class FakeAudioOutput:
    sample_rate = 48000

    def __init__(self, calls):
        self.calls = calls

    def play_wav(self, wav_path, blocking=True):
        self.calls.append(("output", wav_path.exists(), blocking))
        return True

    def play_beep(self, frequency=440.0, duration=0.5, blocking=True):
        return True


class FakeSTT:
    def __init__(self, calls):
        self.calls = calls

    def transcribe(self, audio_bytes, sample_rate=16000):
        self.calls.append(("stt", audio_bytes, sample_rate))
        return "merhaba"


class FakeTranslator:
    def __init__(self, calls):
        self.calls = calls

    def translate(self, text):
        self.calls.append(("translate", text))
        return "hello"


class FakeTTS:
    def __init__(self, calls):
        self.calls = calls

    def synthesize_to_wav(self, text, wav_path, sample_rate=48000):
        self.calls.append(("tts", text, sample_rate))
        wav_path.touch()
        return True

    def is_available(self):
        return True


class FakeVAD:
    def __init__(self, segment=None):
        self.segment = segment

    def process_audio(self, audio_chunk):
        segment, self.segment = self.segment, None
        return segment

    def flush(self):
        return None


class PipelineInjectionTests(unittest.TestCase):
    def test_injected_backends_run_in_existing_synchronous_order(self):
        calls = []
        components = PipelineComponents(
            audio_input=FakeAudioInput(),
            audio_output=FakeAudioOutput(calls),
            vad=FakeVAD(),
            stt=FakeSTT(calls),
            translator=FakeTranslator(calls),
            tts=FakeTTS(calls),
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ), patch("src.pipeline.NOISE_REDUCE_AVAILABLE", False):
            pipeline = TranslationPipeline(FakeConfig(), components=components)
            self.assertTrue(pipeline.process_segment(b"pcm"))

        self.assertEqual(
            calls,
            [
                ("stt", b"pcm", 16000),
                ("translate", "merhaba"),
                ("tts", "hello", 48000),
                ("output", True, True),
            ],
        )

    def test_process_segment_no_longer_clears_capture_backlog(self):
        calls = []
        audio_input = FakeAudioInput(queued_chunks=51)
        components = PipelineComponents(
            audio_input=audio_input,
            audio_output=FakeAudioOutput(calls),
            vad=FakeVAD(),
            stt=FakeSTT(calls),
            translator=FakeTranslator(calls),
            tts=FakeTTS(calls),
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ), patch("src.pipeline.NOISE_REDUCE_AVAILABLE", False):
            pipeline = TranslationPipeline(FakeConfig(), components=components)
            self.assertTrue(pipeline.process_segment(b"pcm"))

        self.assertEqual(audio_input.cleared, 0)

    def test_run_live_uses_workers_without_clearing_capture_backlog(self):
        calls = []
        audio_input = FakeAudioInput(chunks=[b"chunk"])
        components = PipelineComponents(
            audio_input=audio_input,
            audio_output=FakeAudioOutput(calls),
            vad=FakeVAD(segment=b"segment"),
            stt=FakeSTT(calls),
            translator=FakeTranslator(calls),
            tts=FakeTTS(calls),
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch(
            "src.pipeline.get_tmp_dir", return_value=Path(tmp_dir)
        ):
            pipeline = TranslationPipeline(FakeConfig(), components=components)

            original_transcribe = pipeline.stt.transcribe

            def transcribe_and_stop(audio_bytes, sample_rate=16000):
                result = original_transcribe(audio_bytes, sample_rate)
                pipeline.stop()
                return result

            pipeline.stt.transcribe = Mock(side_effect=transcribe_and_stop)
            pipeline.run_live()

        pipeline.stt.transcribe.assert_called_once_with(b"segment", 16000)
        self.assertEqual(audio_input.cleared, 0)
        self.assertTrue(audio_input.started)
        self.assertTrue(audio_input.stopped)
        self.assertEqual(pipeline.runtime_metrics()["completed"], 1)


class BackendFactoryTests(unittest.TestCase):
    def setUp(self):
        self.windows = RuntimePlatform.from_values("Windows", "AMD64")
        self.macos = RuntimePlatform.from_values("Darwin", "arm64")

    def test_existing_config_without_selector_uses_stt_whisper(self):
        constructor = Mock(return_value=object())
        factory = BackendFactory(FakeConfig(), self.windows)

        with patch("src.backend_factory._load_symbol", return_value=constructor) as load:
            result = factory.create_stt()

        self.assertIs(result, constructor.return_value)
        load.assert_called_once_with(".stt_whisper", "STTWhisper")
        constructor.assert_called_once_with(
            model="small",
            compute_type="int8",
            device="cpu",
            language="tr",
            beam_size=1,
        )

    def test_existing_config_without_selector_uses_deepl(self):
        constructor = Mock(return_value=object())
        factory = BackendFactory(FakeConfig(), self.windows)

        with patch("src.backend_factory._load_symbol", return_value=constructor) as load:
            result = factory.create_translator()

        self.assertIs(result, constructor.return_value)
        load.assert_called_once_with(".translate_deepl", "DeepLTranslator")
        self.assertEqual(constructor.call_args.kwargs["api_key"], "test-key")
        self.assertEqual(constructor.call_args.kwargs["source_lang"], "TR")
        self.assertEqual(constructor.call_args.kwargs["target_lang"], "EN")
        self.assertIsNone(constructor.call_args.kwargs["context"])
        self.assertIsNone(constructor.call_args.kwargs["custom_instructions"])

    def test_deepl_context_and_custom_instructions_are_configuration_driven(self):
        constructor = Mock(return_value=object())
        config = FakeConfig(
            translate={
                "context": "ExampleName is a personal name.",
                "custom_instructions": ["Keep ExampleName unchanged."],
            }
        )

        with patch("src.backend_factory._load_symbol", return_value=constructor):
            BackendFactory(config, self.windows).create_translator()

        self.assertEqual(
            constructor.call_args.kwargs["context"],
            "ExampleName is a personal name.",
        )
        self.assertEqual(
            constructor.call_args.kwargs["custom_instructions"],
            ["Keep ExampleName unchanged."],
        )

    def test_invalid_backend_names_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "Unknown STT backend: mlx"):
            BackendFactory(FakeConfig(stt={"backend": "mlx"}), self.macos).create_stt()
        with self.assertRaisesRegex(ValueError, "Unknown translator backend: local"):
            BackendFactory(
                FakeConfig(translate={"backend": "local"}), self.macos
            ).create_translator()
        with self.assertRaisesRegex(ValueError, "Unknown TTS engine: local"):
            BackendFactory(
                FakeConfig(tts={"engine": "local"}), self.macos
            ).create_tts()

    def test_existing_tts_engine_names_select_existing_implementations(self):
        cases = (
            ("sapi", ".tts_sapi", "SapiTTSEngine"),
            ("edge", ".tts_edge", "EdgeTTSEngine"),
            ("clone", ".tts_clone_stub", "CloneTTSEngineStub"),
        )
        for engine_name, module_name, symbol_name in cases:
            with self.subTest(engine=engine_name):
                engine = Mock()
                engine.is_available.return_value = True
                constructor = Mock(return_value=engine)
                factory = BackendFactory(
                    FakeConfig(tts={"engine": engine_name}), self.windows
                )

                with patch(
                    "src.backend_factory._load_symbol", return_value=constructor
                ) as load:
                    result = factory.create_tts()

                self.assertIs(result, engine)
                load.assert_called_once_with(module_name, symbol_name)

    def test_windows_preserves_unavailable_edge_to_sapi_fallback(self):
        edge = Mock()
        edge.is_available.return_value = False
        edge_constructor = Mock(return_value=edge)
        sapi_constructor = Mock(return_value=object())

        def load(module_name, symbol_name):
            if symbol_name == "EdgeTTSEngine":
                return edge_constructor
            if symbol_name == "SapiTTSEngine":
                return sapi_constructor
            self.fail(f"Unexpected symbol: {module_name}.{symbol_name}")

        factory = BackendFactory(FakeConfig(tts={"engine": "edge"}), self.windows)
        with patch("src.backend_factory._load_symbol", side_effect=load):
            result = factory.create_tts()

        self.assertIs(result, sapi_constructor.return_value)
        sapi_constructor.assert_called_once_with(sample_rate=48000)

    def test_non_windows_sapi_and_invalid_fallback_fail_explicitly(self):
        with self.assertRaisesRegex(RuntimeError, "supported only on Windows"):
            BackendFactory(
                FakeConfig(tts={"engine": "sapi"}), self.macos
            ).create_tts()

        unavailable_edge = Mock()
        unavailable_edge.is_available.return_value = False
        with patch(
            "src.backend_factory._load_symbol",
            return_value=Mock(return_value=unavailable_edge),
        ):
            with self.assertRaisesRegex(RuntimeError, "SAPI fallback"):
                BackendFactory(
                    FakeConfig(tts={"engine": "edge"}), self.macos
                ).create_tts()

    def test_legacy_audio_and_vad_keys_are_preserved(self):
        input_constructor = Mock(return_value=types.SimpleNamespace(sample_rate=22050))
        output_constructor = Mock(return_value=object())
        vad_constructor = Mock(return_value=object())
        find_device = Mock(side_effect=[3, 7])

        def load(module_name, symbol_name):
            return {
                "find_device": find_device,
                "AudioInput": input_constructor,
                "AudioOutput": output_constructor,
                "VAD": vad_constructor,
            }[symbol_name]

        config = FakeConfig(
            audio={"input_sample_rate": 22050, "output_sample_rate": 44100},
            vad={"silence_ms": 700, "min_speech_ms": 900, "max_segment_ms": 9000},
        )
        factory = BackendFactory(config, self.windows)
        with patch("src.backend_factory._load_symbol", side_effect=load):
            audio_input = factory.create_audio_input()
            factory.create_audio_output()
            factory.create_vad(audio_input.sample_rate)

        self.assertEqual(input_constructor.call_args.kwargs["sample_rate"], 22050)
        self.assertEqual(output_constructor.call_args.kwargs["sample_rate"], 44100)
        self.assertEqual(vad_constructor.call_args.kwargs["silence_threshold_ms"], 700)
        self.assertEqual(vad_constructor.call_args.kwargs["min_speech_duration_ms"], 900)
        self.assertEqual(vad_constructor.call_args.kwargs["max_segment_duration_ms"], 9000)


class RuntimePlatformTests(unittest.TestCase):
    def test_platform_capability_matrix(self):
        macos = RuntimePlatform.from_values("Darwin", "arm64")
        windows = RuntimePlatform.from_values("Windows", "AMD64")
        linux = RuntimePlatform.from_values("Linux", "x86_64")

        self.assertEqual(macos.operating_system, OperatingSystem.MACOS)
        self.assertTrue(macos.is_apple_silicon)
        self.assertFalse(macos.supports_sapi)
        self.assertFalse(macos.cuda_configuration_relevant)
        self.assertEqual(macos.virtual_audio_routing, "blackhole")

        self.assertEqual(windows.operating_system, OperatingSystem.WINDOWS)
        self.assertFalse(windows.is_apple_silicon)
        self.assertTrue(windows.supports_sapi)
        self.assertTrue(windows.cuda_configuration_relevant)
        self.assertEqual(windows.virtual_audio_routing, "vb-cable")

        self.assertEqual(linux.operating_system, OperatingSystem.LINUX)
        self.assertTrue(linux.cuda_configuration_relevant)
        self.assertIsNone(linux.virtual_audio_routing)


class ImportIsolationTests(unittest.TestCase):
    def test_device_and_pipeline_imports_do_not_load_ai_backends(self):
        script = """
import importlib.abc
import sys

blocked = {
    "faster_whisper",
    "mlx",
    "mlx_whisper",
    "requests",
    "cachetools",
    "edge_tts",
    "webrtcvad",
}

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise AssertionError(f"unexpected backend import: {fullname}")
        return None

sys.meta_path.insert(0, Blocker())
import src.devices
import src.main
import src.pipeline
print("IMPORT_ISOLATION_OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("IMPORT_ISOLATION_OK", result.stdout)

    def test_main_list_devices_branch_does_not_import_config_or_pipeline(self):
        fake_devices = types.ModuleType("src.devices")
        fake_devices.print_device_list = Mock()

        with patch.dict(
            sys.modules,
            {
                "src.devices": fake_devices,
                "src.config": None,
                "src.pipeline": None,
            },
        ), patch.object(sys, "argv", ["program", "--mode", "list-devices"]):
            import src.main

            self.assertEqual(src.main.main(), 0)

        fake_devices.print_device_list.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
