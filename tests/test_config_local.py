import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Config


class LocalConfigOverlayTests(unittest.TestCase):
    def test_local_config_recursively_overrides_shared_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            shared_path = Path(tmp_dir) / "config.yaml"
            local_path = Path(tmp_dir) / "config.local.yaml"
            shared_path.write_text(
                "translate:\n"
                "  source_lang: TR\n"
                "  target_lang: EN\n"
                "  cache_size: 128\n",
                encoding="utf-8",
            )
            local_path.write_text(
                "translate:\n"
                "  context: ExampleName is a personal name.\n"
                "  custom_instructions:\n"
                "    - Keep ExampleName unchanged.\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPL_API_KEY": "test-key"}):
                config = Config(shared_path)

        self.assertEqual(config.translate_config["source_lang"], "TR")
        self.assertEqual(config.translate_config["target_lang"], "EN")
        self.assertEqual(config.translate_config["cache_size"], 128)
        self.assertEqual(
            config.translate_config["context"],
            "ExampleName is a personal name.",
        )
        self.assertEqual(
            config.translate_config["custom_instructions"],
            ["Keep ExampleName unchanged."],
        )

    def test_non_mapping_local_config_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            shared_path = Path(tmp_dir) / "config.yaml"
            local_path = Path(tmp_dir) / "config.local.yaml"
            shared_path.write_text("translate: {}\n", encoding="utf-8")
            local_path.write_text("- invalid\n", encoding="utf-8")

            with patch.dict(os.environ, {"DEEPL_API_KEY": "test-key"}):
                with self.assertRaisesRegex(ValueError, "must contain a mapping"):
                    Config(shared_path)


if __name__ == "__main__":
    unittest.main()
