import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.gui_main import IncomingSubtitleWorker, MainWindow, PipelineWorker


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

    def test_outgoing_worker_requests_immediate_cancel(self):
        worker = PipelineWorker(config=None)
        worker.pipeline = Mock()

        worker.stop()

        deadline = time.monotonic() + 1
        while not worker.pipeline.stop.called and time.monotonic() < deadline:
            time.sleep(0.01)
        worker.pipeline.stop.assert_called_once_with(cancel=True)

    def test_worker_stop_does_not_block_the_gui_thread(self):
        stop_started = threading.Event()
        release_stop = threading.Event()
        worker = PipelineWorker(config=None)
        worker.pipeline = Mock()

        def blocking_stop(*, cancel):
            self.assertTrue(cancel)
            stop_started.set()
            release_stop.wait(1)

        worker.pipeline.stop.side_effect = blocking_stop

        started = time.monotonic()
        worker.stop()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.1)
        self.assertTrue(stop_started.wait(1))
        release_stop.set()

    def test_incoming_worker_stop_is_also_dispatched_off_gui_thread(self):
        worker = IncomingSubtitleWorker(config=None)
        worker.pipeline = Mock()

        worker.stop()

        deadline = time.monotonic() + 1
        while not worker.pipeline.stop.called and time.monotonic() < deadline:
            time.sleep(0.01)
        worker.pipeline.stop.assert_called_once_with(cancel=True)

    def test_stop_session_polls_even_before_finished_signal_arrives(self):
        running_worker = Mock()
        running_worker.isRunning.return_value = True
        self.window.worker = running_worker

        with patch("src.ui.gui_main.QTimer.singleShot") as single_shot:
            self.window.stop_session()

        running_worker.stop.assert_called_once_with()
        single_shot.assert_called_once_with(
            0,
            self.window._finalize_session_if_stopped,
        )
        running_worker.isRunning.return_value = False
        self.window._finish_poll_scheduled = False
        self.window._stopping = False

    def test_exit_control_is_distinct_from_session_stop(self):
        self.assertEqual(self.window.btn_start.text(), "OTURUMU BAŞLAT")
        self.assertEqual(self.window.btn_exit.text(), "UYGULAMAYI KAPAT")

    def test_running_primary_control_requests_stop_and_window_close(self):
        running_worker = Mock()
        running_worker.isRunning.return_value = True
        self.window.worker = running_worker

        with patch.object(self.window, "request_close") as request_close:
            self.window.toggle_start()

        request_close.assert_called_once_with()

    def test_running_primary_control_label_states_that_window_will_close(self):
        self.window.update_button_style(True)

        self.assertEqual(
            self.window.btn_start.text(),
            "OTURUMU DURDUR VE KAPAT",
        )

    def test_exit_requests_cancel_then_closes_after_workers_finish(self):
        running_worker = Mock()
        running_worker.isRunning.return_value = True
        self.window.worker = running_worker

        with patch("src.ui.gui_main.QTimer.singleShot") as single_shot:
            self.window.request_close()

        self.assertTrue(self.window._closing)
        self.assertFalse(self.window.btn_exit.isEnabled())
        self.assertEqual(self.window.btn_exit.text(), "KAPATILIYOR…")
        running_worker.stop.assert_called_once_with()
        single_shot.assert_called_once_with(
            0,
            self.window._finalize_session_if_stopped,
        )
        running_worker.isRunning.return_value = False
        self.window._finish_poll_scheduled = False
        self.window._stopping = False
        self.window._closing = False

    def test_finished_session_restores_start_button(self):
        stopped_worker = Mock()
        stopped_worker.isRunning.return_value = False
        self.window.worker = stopped_worker
        self.window.incoming_worker = None
        self.window._stopping = True
        self.window.btn_start.setEnabled(False)
        self.window.update_button_style(True)

        self.window._finalize_session_if_stopped()

        self.assertTrue(self.window.btn_start.isEnabled())
        self.assertEqual(self.window.btn_start.text(), "OTURUMU BAŞLAT")
        self.assertEqual(self.window.status_indicator.text(), "DURDURULDU")


if __name__ == "__main__":
    unittest.main()
