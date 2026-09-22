import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.gui_main import MainWindow


class BidirectionalGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_incoming_and_outgoing_transcripts_update_separate_cards(self):
        self.window.handle_log(
            "INFO",
            "src.stt_whisper",
            "STT result: 'Remote English' (detected language: en)",
        )
        self.assertEqual(
            self.window.outgoing_card.source_text.text(),
            "Konuşma bekleniyor…",
        )

        self.window.handle_log(
            "INFO",
            "src.pipeline",
            "Outgoing STT completed for segment 1: 'Merhaba'",
        )
        self.window.handle_log(
            "INFO",
            "src.pipeline",
            "Translation completed for segment 1: 'Hello'",
        )
        self.window.handle_incoming_subtitle(
            "How are you?",
            "Nasılsınız?",
        )

        self.assertEqual(self.window.outgoing_card.source_text.text(), "Merhaba")
        self.assertEqual(self.window.outgoing_card.target_text.text(), "Hello")
        self.assertEqual(
            self.window.incoming_card.source_text.text(),
            "How are you?",
        )
        self.assertEqual(
            self.window.incoming_card.target_text.text(),
            "Nasılsınız?",
        )


if __name__ == "__main__":
    unittest.main()
