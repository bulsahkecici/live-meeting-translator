"""Bidirectional meeting translation GUI."""
import logging
import sys
import threading

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.incoming_subtitles import IncomingSubtitlePipeline
from src.pipeline import TranslationPipeline
from src.ui.gui_overlay import SubtitleOverlay


class QtLogHandler(logging.Handler, QObject):
    """Forward standard logging records to the Qt event loop."""

    log_signal = pyqtSignal(str, str, str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        self.log_signal.emit(record.levelname, record.name, self.format(record))


class PipelineWorker(QThread):
    """Run the existing Turkish-to-English audio pipeline."""

    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.pipeline = None
        self._stop_requested = threading.Event()

    def run(self):
        try:
            self.pipeline = TranslationPipeline(self.config)
            if self._stop_requested.is_set():
                self.pipeline.stop(cancel=True)
            self.pipeline.run_live()
        except Exception as exc:
            logging.error("Outgoing pipeline crashed: %s", exc, exc_info=True)
            self.error.emit(str(exc))

    def stop(self):
        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        if self.pipeline:
            threading.Thread(
                target=self.pipeline.stop,
                kwargs={"cancel": True},
                name="outgoing-pipeline-stop",
                daemon=True,
            ).start()


class IncomingSubtitleWorker(QThread):
    """Run the English-to-Turkish subtitle-only pipeline."""

    subtitle = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.pipeline = None
        self._stop_requested = threading.Event()

    def run(self):
        try:
            self.pipeline = IncomingSubtitlePipeline(
                self.config,
                on_subtitle=self.subtitle.emit,
            )
            if self._stop_requested.is_set():
                self.pipeline.stop(cancel=True)
            self.pipeline.run_live()
        except Exception as exc:
            logging.error("Incoming subtitle pipeline crashed: %s", exc, exc_info=True)
            self.error.emit(str(exc))

    def stop(self):
        if self._stop_requested.is_set():
            return
        self._stop_requested.set()
        if self.pipeline:
            threading.Thread(
                target=self.pipeline.stop,
                kwargs={"cancel": True},
                name="incoming-pipeline-stop",
                daemon=True,
            ).start()


class DirectionCard(QFrame):
    """One compact source/target transcript card."""

    def __init__(
        self,
        eyebrow: str,
        title: str,
        route: str,
        source_caption: str,
        target_caption: str,
        accent: str,
    ):
        super().__init__()
        self.setObjectName("directionCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(8)

        eyebrow_label = QLabel(eyebrow.upper())
        eyebrow_label.setStyleSheet(
            f"color: {accent}; font-size: 10px; font-weight: 800; "
            "letter-spacing: 1.5px;"
        )
        title_label = QLabel(title)
        title_label.setStyleSheet(
            "color: #F5F7FA; font-size: 20px; font-weight: 750;"
        )
        route_label = QLabel(route)
        route_label.setStyleSheet("color: #7D8799; font-size: 11px;")

        source_label = QLabel(source_caption.upper())
        source_label.setStyleSheet(
            "color: #7D8799; font-size: 9px; font-weight: 700; "
            "letter-spacing: 1px; margin-top: 8px;"
        )
        self.source_text = QLabel("Konuşma bekleniyor…")
        self.source_text.setWordWrap(True)
        self.source_text.setMinimumHeight(42)
        self.source_text.setStyleSheet(
            "color: #C8D0DC; font-size: 15px; line-height: 1.35;"
        )

        target_label = QLabel(target_caption.upper())
        target_label.setStyleSheet(
            f"color: {accent}; font-size: 9px; font-weight: 700; "
            "letter-spacing: 1px; margin-top: 8px;"
        )
        self.target_text = QLabel("—")
        self.target_text.setWordWrap(True)
        self.target_text.setMinimumHeight(58)
        self.target_text.setStyleSheet(
            f"color: {accent}; font-size: 19px; font-weight: 650; "
            "line-height: 1.4;"
        )

        layout.addWidget(eyebrow_label)
        layout.addWidget(title_label)
        layout.addWidget(route_label)
        layout.addWidget(source_label)
        layout.addWidget(self.source_text)
        layout.addWidget(target_label)
        layout.addWidget(self.target_text)
        layout.addStretch()

    def set_transcript(self, source: str = None, target: str = None):
        if source:
            self.source_text.setText(source)
        if target:
            self.target_text.setText(target)

    def reset(self):
        self.source_text.setText("Konuşma bekleniyor…")
        self.target_text.setText("—")


class MainWindow(QMainWindow):
    """Control both meeting directions without mixing their audio routes."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Meeting Bridge — TR ⇄ EN")
        self.resize(920, 820)
        self.setMinimumSize(780, 680)

        self.config = Config()
        self.worker = None
        self.incoming_worker = None
        self._closing = False
        self._stopping = False
        self._finish_poll_scheduled = False
        self._ready_channels = set()
        self.overlay = SubtitleOverlay()

        self.log_handler = QtLogHandler()
        self.log_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S")
        )
        logging.getLogger().addHandler(self.log_handler)
        self.log_handler.log_signal.connect(self.handle_log)

        self.init_ui()
        self.apply_theme()

    @property
    def incoming_enabled(self) -> bool:
        return self.config.incoming_subtitles_config.get("enabled", False)

    def init_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        brand.setSpacing(2)
        title = QLabel("MEETING BRIDGE")
        title.setStyleSheet(
            "color: #F5F7FA; font-size: 25px; font-weight: 850; "
            "letter-spacing: 2px;"
        )
        subtitle = QLabel("Gerçek zamanlı Türkçe ⇄ İngilizce görüşme asistanı")
        subtitle.setStyleSheet("color: #7D8799; font-size: 12px;")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()

        self.status_indicator = QLabel("HAZIR")
        self.status_indicator.setObjectName("statusPill")
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_indicator.setMinimumWidth(150)
        header.addWidget(self.status_indicator)
        layout.addLayout(header)

        route_bar = QFrame()
        route_bar.setObjectName("routeBar")
        route_layout = QHBoxLayout(route_bar)
        route_layout.setContentsMargins(16, 11, 16, 11)
        outgoing_input = self.config.audio_input.get("name_substring") or "Varsayılan giriş"
        outgoing_output = (
            self.config.audio_output.get("name_substring") or "Varsayılan çıkış"
        )
        incoming_config = self.config.incoming_subtitles_config
        incoming_input = incoming_config.get("audio_input", {}).get(
            "name_substring",
            "Ayrı konferans girişi",
        )
        self.outgoing_route_status = QLabel(
            f"●  SİZ: {outgoing_input} → {outgoing_output}"
        )
        self.incoming_route_status = QLabel(
            f"●  ZOOM: {incoming_input} → Türkçe altyazı"
            if self.incoming_enabled
            else "●  GELEN ALTYAZI DEVRE DIŞI"
        )
        self.outgoing_route_status.setStyleSheet("color: #58D6C7; font-size: 11px;")
        self.incoming_route_status.setStyleSheet("color: #B59CFF; font-size: 11px;")
        route_layout.addWidget(self.outgoing_route_status)
        route_layout.addStretch()
        route_layout.addWidget(self.incoming_route_status)
        layout.addWidget(route_bar)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        outgoing_stt = self.config.stt_config.get("backend", "faster-whisper")
        outgoing_tts = self.config.tts_config.get("engine", "sapi")
        incoming_stt = incoming_config.get("stt", {}).get(
            "backend",
            "faster-whisper",
        )
        self.outgoing_card = DirectionCard(
            "Siz → Karşı taraf",
            "Türkçe konuşun",
            f"{outgoing_stt}  •  DeepL  •  {outgoing_tts} TTS",
            "Algılanan Türkçe",
            "Zoom'a gönderilen İngilizce",
            "#58D6C7",
        )
        self.incoming_card = DirectionCard(
            "Karşı taraf → Siz",
            "İngilizceyi takip edin",
            f"{incoming_input}  •  {incoming_stt}  •  DeepL",
            "Algılanan İngilizce",
            "Türkçe altyazı",
            "#B59CFF",
        )
        cards.addWidget(self.outgoing_card)
        cards.addWidget(self.incoming_card)
        layout.addLayout(cards, stretch=1)
        if not self.incoming_enabled:
            self.incoming_card.source_text.setText("Yapılandırmada devre dışı")

        controls = QHBoxLayout()
        self.btn_start = QPushButton("OTURUMU BAŞLAT")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setMinimumHeight(54)
        self.btn_start.setToolTip(
            "Çeviri oturumunu başlatır veya durdurur; pencere açık kalır."
        )
        self.btn_start.clicked.connect(self.toggle_start)
        controls.addWidget(self.btn_start, stretch=1)

        self.btn_exit = QPushButton("UYGULAMAYI KAPAT")
        self.btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exit.setMinimumHeight(54)
        self.btn_exit.setToolTip("Çeviri oturumunu iptal eder ve pencereyi kapatır.")
        self.btn_exit.setStyleSheet(
            "QPushButton { background-color: #273247; color: #D7DEEA; "
            "border: 1px solid #3A4962; border-radius: 12px; "
            "font-size: 12px; font-weight: 750; padding: 0 16px; } "
            "QPushButton:hover { background-color: #34425A; }"
        )
        self.btn_exit.clicked.connect(self.request_close)
        controls.addWidget(self.btn_exit)

        self.chk_overlay = QCheckBox("Türkçe altyazıyı ekran üstünde göster")
        self.chk_overlay.setChecked(True)
        self.chk_overlay.toggled.connect(self.toggle_overlay)
        controls.addWidget(self.chk_overlay)
        layout.addLayout(controls)

        console_frame = QFrame()
        console_frame.setObjectName("consoleFrame")
        console_layout = QVBoxLayout(console_frame)
        console_layout.setContentsMargins(14, 10, 14, 10)
        console_title = QLabel("OTURUM GÜNLÜĞÜ")
        console_title.setStyleSheet(
            "color: #667085; font-size: 9px; font-weight: 700; "
            "letter-spacing: 1px;"
        )
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(130)
        self.console.setFont(QFont("Menlo", 10))
        console_layout.addWidget(console_title)
        console_layout.addWidget(self.console)
        layout.addWidget(console_frame)

    def apply_theme(self):
        self.setStyleSheet(
            """
            QWidget#root { background-color: #0C111B; }
            QFrame#routeBar {
                background-color: #111927;
                border: 1px solid #223047;
                border-radius: 10px;
            }
            QFrame#directionCard {
                background-color: #121A28;
                border: 1px solid #25334A;
                border-radius: 16px;
            }
            QFrame#consoleFrame {
                background-color: #0A0F18;
                border: 1px solid #1B2638;
                border-radius: 12px;
            }
            QPlainTextEdit {
                background: transparent;
                color: #8B96A8;
                border: none;
                selection-background-color: #31405A;
            }
            QCheckBox { color: #AAB4C3; font-size: 12px; spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QLabel#statusPill {
                background-color: #182231;
                color: #9BA8BA;
                border: 1px solid #2B3A50;
                border-radius: 14px;
                padding: 7px 14px;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1px;
            }
            """
        )
        self.update_button_style(False)

    def update_button_style(self, running: bool):
        if running:
            self.btn_start.setText("OTURUMU DURDUR VE KAPAT")
            self.btn_start.setStyleSheet(
                "QPushButton { background-color: #E85D75; color: white; "
                "border: none; border-radius: 12px; font-size: 14px; "
                "font-weight: 800; letter-spacing: 1px; } "
                "QPushButton:hover { background-color: #F06A82; }"
            )
        else:
            self.btn_start.setText("OTURUMU BAŞLAT")
            self.btn_start.setStyleSheet(
                "QPushButton { background-color: #58D6C7; color: #07110F; "
                "border: none; border-radius: 12px; font-size: 14px; "
                "font-weight: 850; letter-spacing: 1px; } "
                "QPushButton:hover { background-color: #70E3D5; }"
            )

    def _workers(self):
        return [worker for worker in (self.worker, self.incoming_worker) if worker]

    def _any_worker_running(self) -> bool:
        return any(worker.isRunning() for worker in self._workers())

    def toggle_start(self):
        if self._any_worker_running():
            self.request_close()
        else:
            self.start_session()

    def start_session(self):
        self.console.clear()
        self.outgoing_card.reset()
        self.incoming_card.reset()
        if not self.incoming_enabled:
            self.incoming_card.source_text.setText("Yapılandırmada devre dışı")
        self._stopping = False
        self._ready_channels.clear()
        self.status_indicator.setText("BAŞLATILIYOR")
        self.status_indicator.setStyleSheet(
            "background-color: #3A2D12; color: #FFD166; border: 1px solid "
            "#6B5422; border-radius: 14px; padding: 7px 14px; "
            "font-size: 10px; font-weight: 800; letter-spacing: 1px;"
        )
        self.update_button_style(True)

        self.worker = PipelineWorker(self.config)
        self.worker.error.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)

        if self.incoming_enabled:
            self.incoming_worker = IncomingSubtitleWorker(self.config)
            self.incoming_worker.subtitle.connect(self.handle_incoming_subtitle)
            self.incoming_worker.error.connect(self.on_worker_error)
            self.incoming_worker.finished.connect(self.on_worker_finished)
        else:
            self.incoming_worker = None
            self.incoming_route_status.setText("●  GELEN ALTYAZI DEVRE DIŞI")

        self.worker.start()
        if self.incoming_worker:
            self.incoming_worker.start()

    def stop_session(self):
        if self._stopping:
            return
        logging.info("GUI session stop requested")
        self._stopping = True
        self.btn_start.setEnabled(False)
        self.btn_start.setText("OTURUM İPTAL EDİLİYOR…")
        self.status_indicator.setText("DURDURULUYOR")
        for worker in self._workers():
            if worker.isRunning():
                worker.stop()
        self._schedule_finish_poll()

    def request_close(self):
        """Cancel active work and close once both worker threads have exited."""
        if self._closing:
            return
        logging.info("GUI application close requested")
        self._closing = True
        self.btn_exit.setEnabled(False)
        self.btn_exit.setText("KAPATILIYOR…")
        if self._any_worker_running():
            self.stop_session()
            self._schedule_finish_poll()
            return
        self.close()

    def on_worker_error(self, message: str):
        self.status_indicator.setText("HATA")
        self.status_indicator.setStyleSheet(
            "background-color: #401923; color: #FF8FA3; border: 1px solid "
            "#713044; border-radius: 14px; padding: 7px 14px; "
            "font-size: 10px; font-weight: 800; letter-spacing: 1px;"
        )
        self.console.appendPlainText(f"HATA  {message}")
        if not self._stopping:
            self.stop_session()

    def on_worker_finished(self):
        self._schedule_finish_poll()

    def _schedule_finish_poll(self, delay_ms: int = 0):
        if not self._finish_poll_scheduled:
            self._finish_poll_scheduled = True
            QTimer.singleShot(delay_ms, self._finalize_session_if_stopped)

    def _finalize_session_if_stopped(self):
        self._finish_poll_scheduled = False
        if self._any_worker_running():
            if not self._stopping:
                self.stop_session()
            self._schedule_finish_poll(50)
            return

        self.update_button_style(False)
        self.btn_start.setEnabled(True)
        if self.status_indicator.text() != "HATA":
            self.status_indicator.setText("DURDURULDU")
        self.overlay.hide()
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _mark_ready(self, channel: str):
        self._ready_channels.add(channel)
        expected = {"outgoing"}
        if self.incoming_enabled:
            expected.add("incoming")
        if expected.issubset(self._ready_channels):
            self.status_indicator.setText(
                "CANLI • İKİ YÖN AKTİF"
                if self.incoming_enabled
                else "CANLI • GİDEN KANAL AKTİF"
            )
            self.status_indicator.setStyleSheet(
                "background-color: #12372F; color: #65E6D5; border: 1px solid "
                "#255E53; border-radius: 14px; padding: 7px 14px; "
                "font-size: 10px; font-weight: 800; letter-spacing: 1px;"
            )
            self.toggle_overlay(self.chk_overlay.isChecked())

    def toggle_overlay(self, visible: bool):
        if visible and self._any_worker_running() and self.incoming_enabled:
            self.overlay.show()
        else:
            self.overlay.hide()

    def handle_incoming_subtitle(self, source_text: str, target_text: str):
        self.incoming_card.set_transcript(source_text, target_text)
        if self.chk_overlay.isChecked():
            self.overlay.update_text(
                source_text=source_text,
                target_text=target_text,
            )

    def handle_log(self, level: str, logger_name: str, message: str):
        if not hasattr(self, "console"):
            return
        self.console.appendPlainText(f"{level:<7} {message}")
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )

        if "Listening for speech" in message:
            self._mark_ready("outgoing")
        if "Incoming subtitle capture active" in message:
            self._mark_ready("incoming")

        if (
            logger_name == "src.pipeline"
            and "Outgoing STT completed for segment" in message
            and ": '" in message
        ):
            try:
                text = message.rsplit(": '", 1)[1].rstrip("'")
                self.outgoing_card.set_transcript(source=text)
            except (IndexError, AttributeError):
                pass

        if (
            logger_name == "src.pipeline"
            and "Translation completed for segment" in message
            and ": '" in message
        ):
            try:
                text = message.rsplit(": '", 1)[1].rstrip("'")
                self.outgoing_card.set_transcript(target=text)
            except (IndexError, AttributeError):
                pass

    def closeEvent(self, event):
        if self._any_worker_running():
            self._closing = True
            self.stop_session()
            event.ignore()
            return
        logging.getLogger().removeHandler(self.log_handler)
        self.overlay.close()
        event.accept()


def run_gui():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
