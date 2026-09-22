import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from src.backend_factory import BackendFactory
from src.incoming_subtitles import (
    IncomingSubtitleComponents,
    IncomingSubtitlePipeline,
)


class FakeConfig:
    deepl_api_key = "test-key"
    vad_config = {}
    pipeline_config = {}
    audio_input = {}
    stt_config = {}
    translate_config = {}

    def __init__(self, incoming=None):
        self.incoming_subtitles_config = incoming or {"pipeline": {}}

    def get(self, _key, default=None):
        return default


class FakeAudioInput:
    sample_rate = 48000

    def __init__(self):
        self.chunks = [b"captured"]
        self.started = False
        self.stopped = False
        self.cleared = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def read(self, timeout=None):
        return self.chunks.pop(0) if self.chunks else None

    def clear_queue(self):
        self.cleared += 1

    def queue_size(self):
        return len(self.chunks)

    def dropped_chunk_count(self):
        return 0


class IncomingSubtitlePipelineTests(unittest.TestCase):
    def test_live_channel_preserves_order_and_emits_reverse_translation(self):
        calls = []
        subtitles = []
        audio_input = FakeAudioInput()
        vad = Mock()
        vad.process_audio.side_effect = lambda chunk: b"segment" if chunk else None
        vad.flush.return_value = None
        stt = Mock()
        translator = Mock()
        translator.translate.side_effect = lambda text: (
            calls.append(("translate", text)) or "Merhaba"
        )
        components = IncomingSubtitleComponents(
            audio_input=audio_input,
            vad=vad,
            stt=stt,
            translator=translator,
        )
        pipeline = IncomingSubtitlePipeline(
            FakeConfig(),
            components=components,
            on_subtitle=lambda source, target: subtitles.append((source, target)),
        )

        def transcribe(audio, sample_rate):
            calls.append(("stt", audio, sample_rate))
            pipeline.stop()
            return "Hello"

        stt.transcribe.side_effect = transcribe
        pipeline.run_live()

        self.assertEqual(
            calls,
            [
                ("stt", b"segment", 48000),
                ("translate", "Hello"),
            ],
        )
        self.assertEqual(subtitles, [("Hello", "Merhaba")])
        self.assertTrue(audio_input.started)
        self.assertTrue(audio_input.stopped)
        self.assertEqual(audio_input.cleared, 0)
        metrics = pipeline.runtime_metrics()
        self.assertEqual(metrics["completed"], 1)
        self.assertEqual(metrics["failed"], 0)
        self.assertEqual(metrics["capture_dropped_chunks"], 0)
        self.assertTrue(all(depth == 0 for depth in metrics["queue_depth"].values()))

    def test_audio_factory_accepts_isolated_incoming_device_settings(self):
        constructor = Mock(return_value=Mock(sample_rate=48000))

        def load(_module_name, symbol_name):
            if symbol_name == "find_device":
                return Mock(return_value=7)
            if symbol_name == "AudioInput":
                return constructor
            self.fail(f"Unexpected symbol: {symbol_name}")

        with patch("src.backend_factory._load_symbol", side_effect=load):
            BackendFactory(FakeConfig()).create_audio_input(
                {
                    "name_substring": "BlackHole 16ch",
                    "sample_rate": 48000,
                    "channels": 2,
                    "mix_to_mono": True,
                },
                pipeline_config={"audio_buffer_size": 14400},
            )

        constructor.assert_called_once_with(
            device_index=7,
            sample_rate=48000,
            channels=2,
            dtype="int16",
            blocksize=14400,
            mix_to_mono=True,
        )

    def test_primary_mac_profile_enables_separate_reverse_channel(self):
        config_path = Path(__file__).resolve().parents[1] / "config.yaml"
        data = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
        incoming = data["incoming_subtitles"]

        self.assertTrue(incoming["enabled"])
        self.assertEqual(
            incoming["audio_input"]["name_substring"],
            "BlackHole 16ch",
        )
        self.assertEqual(incoming["stt"]["language"], "en")
        self.assertEqual(incoming["translate"]["source_lang"], "EN")
        self.assertEqual(incoming["translate"]["target_lang"], "TR")
        self.assertEqual(incoming["pipeline"]["audio_buffer_size"], 14400)


if __name__ == "__main__":
    unittest.main()
