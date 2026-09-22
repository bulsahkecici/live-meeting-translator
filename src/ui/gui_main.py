import sys
import logging
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QPlainTextEdit, QFrame, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QIcon, QColor, QPalette, QFont

from src.config import Config
from src.pipeline import TranslationPipeline
from src.utils import setup_logging
from src.ui.gui_overlay import SubtitleOverlay

# --- Log Handler ---
class QtLogHandler(logging.Handler, QObject):
    log_signal = pyqtSignal(str, str) # level, message

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(record.levelname, msg)

# --- Worker Thread ---
class PipelineWorker(QThread):
    finished = pyqtSignal()
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.pipeline = None
        self._is_running = False
        self._stop_requested = threading.Event()

    def run(self):
        try:
            self.pipeline = TranslationPipeline(self.config)
            if self._stop_requested.is_set():
                self.pipeline.stop()
            self._is_running = True
            self.pipeline.run_live()
        except Exception as e:
            logging.error(f"Pipeline crashed: {e}")
        finally:
            self._is_running = False
            self.finished.emit()

    def stop(self):
        self._stop_requested.set()
        if self.pipeline:
            self.pipeline.stop()

# --- Main Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Zoom Live Translate")
        self.resize(500, 600)
        
        # Init logic
        self.config = Config()
        self.worker = None
        self._closing = False
        self.overlay = SubtitleOverlay()
        
        # Setup Logging (GUI specific handler)
        # Note: File logging is already set up in main.py
        self.log_handler = QtLogHandler()
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S'))
        logging.getLogger().addHandler(self.log_handler)
        self.log_handler.log_signal.connect(self.handle_log)
        
        # UI Setup
        self.init_ui()
        self.apply_theme()
        
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Header
        header_Layout = QVBoxLayout()
        title_lbl = QLabel("ZOOM LIVE TRANSLATE")
        title_lbl.setStyleSheet("font-size: 24px; font-weight: 900; letter-spacing: 2px; color: #00FFCC;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        subtitle_lbl = QLabel("Real-time Turkish to English AI Translation")
        subtitle_lbl.setStyleSheet("font-size: 12px; color: #aaaaaa; margin-bottom: 20px;")
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        header_Layout.addWidget(title_lbl)
        header_Layout.addWidget(subtitle_lbl)
        layout.addLayout(header_Layout)
        
        # Status
        self.status_indicator = QLabel("STOPPED")
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_indicator.setStyleSheet("""
            background-color: #333333; 
            color: #FF5555; 
            border-radius: 5px; 
            padding: 8px; 
            font-weight: bold;
        """)
        layout.addWidget(self.status_indicator)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("START LISTENING")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setMinimumHeight(50)
        self.btn_start.clicked.connect(self.toggle_start)
        
        controls_layout.addWidget(self.btn_start)
        layout.addLayout(controls_layout)
        
        # Options
        self.chk_overlay = QCheckBox("Show Subtitle Overlay")
        self.chk_overlay.setChecked(True)
        self.chk_overlay.setStyleSheet("color: white; font-size: 14px;")
        self.chk_overlay.toggled.connect(self.toggle_overlay)
        layout.addWidget(self.chk_overlay)
        
        # Console
        console_frame = QFrame()
        console_frame.setStyleSheet("background-color: #111; border-radius: 10px; border: 1px solid #333;")
        console_layout = QVBoxLayout(console_frame)
        
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background: transparent; color: #ccc; font-family: Consolas, monospace; border: none;")
        console_layout.addWidget(self.console)
        
        layout.addWidget(console_frame)
        
        # Footer
        footer_lbl = QLabel("AI Powered by Whisper & DeepL")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_lbl.setStyleSheet("color: #555; font-size: 10px;")
        layout.addWidget(footer_lbl)

    def apply_theme(self):
        # Dark Theme
        self.setStyleSheet("background-color: #1E1E1E;")
        
        # Button Style
        self.update_button_style(False)

    def update_button_style(self, running):
        if running:
            self.btn_start.setText("STOP LISTENING")
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #FF5555;
                    color: white;
                    border: none;
                    border-radius: 25px;
                    font-weight: bold;
                    font-size: 16px;
                }
                QPushButton:hover { background-color: #FF3333; }
            """)
            self.status_indicator.setText("LISTENING & TRANSLATING")
            self.status_indicator.setStyleSheet("background-color: #004400; color: #00FF00; border-radius: 5px; padding: 8px; font-weight: bold;")
        else:
            self.btn_start.setText("START LISTENING")
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #00AAFF;
                    color: white;
                    border: none;
                    border-radius: 25px;
                    font-weight: bold;
                    font-size: 16px;
                }
                QPushButton:hover { background-color: #0088CC; }
            """)
            self.status_indicator.setText("READY")
            self.status_indicator.setStyleSheet("background-color: #333333; color: #AAAAAA; border-radius: 5px; padding: 8px; font-weight: bold;")

    def toggle_start(self):
        if self.worker and self.worker.isRunning():
            # Stop
            self.btn_start.setEnabled(False)
            self.btn_start.setText("STOPPING...")
            self.worker.stop()
            # Finished signal will handle cleanup
        else:
            # Start
            self.console.clear()
            self.status_indicator.setText("INITIALIZING (Downloading Model...)")
            self.status_indicator.setStyleSheet("background-color: #AA5500; color: #FFFFFF; border-radius: 5px; padding: 8px; font-weight: bold;")
            self.worker = PipelineWorker(self.config)
            self.worker.finished.connect(self.on_worker_finished)
            self.worker.start()
            self.update_button_style(True)
            self.toggle_overlay(self.chk_overlay.isChecked())

    def on_worker_finished(self):
        self.update_button_style(False)
        self.btn_start.setEnabled(True)
        self.status_indicator.setText("STOPPED")
        if self._closing:
            QTimer.singleShot(0, self.close)

    def toggle_overlay(self, visible):
        if visible and self.worker and self.worker.isRunning():
            self.overlay.show()
        else:
            self.overlay.hide()
            
    def handle_log(self, level, msg):
        # Safety check: if console not ready yet, skip
        if not hasattr(self, 'console'):
            return

        # Append to console
        color = "#ccc"
        if level == "WARNING": color = "#FFCC00"
        if level == "ERROR": color = "#FF5555"
        
        try:
            self.console.appendHtml(f'<span style="color:{color}">{msg}</span>')
            self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())
        except Exception:
            pass
        
        # Parse for Overlay
        # Look for "STT result: 'text'"
        if "STT result: '" in msg:
            try:
                text = msg.split("STT result: '")[1].split("' (detected")[0]
                self.overlay.update_text(source_text=text)
            except:
                pass
                
        # Look for "Translation completed ...: 'text'"
        if "Translation completed" in msg and ": '" in msg:
            try:
                text = msg.split(": '")[-1].rstrip("'")
                self.overlay.update_text(target_text=text)
            except:
                pass

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self._closing = True
            self.worker.stop()
            event.ignore()
            return
        self.overlay.close()
        event.accept()

def run_gui():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
