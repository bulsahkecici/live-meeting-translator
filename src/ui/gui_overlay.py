from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PyQt6.QtCore import Qt, pyqtProperty, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QPalette, QFont

class SubtitleOverlay(QWidget):
    def __init__(self):
        super().__init__()
        
        # Window setup
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool  # Doesn't show in taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # Click-through
        
        # Layout
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(50, 20, 50, 50)
        self.setLayout(layout)
        
        # Styles
        self.setStyleSheet("background: transparent;")
        
        # Source Text (Turkish)
        self.lbl_source = QLabel("")
        self.lbl_source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_source.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 200);
                font-family: 'Segoe UI', sans-serif;
                font-size: 24px;
                font-weight: bold;
                background-color: rgba(0, 0, 0, 100);
                padding: 5px 15px;
                border-radius: 10px;
            }
        """)
        self.lbl_source.hide() # Hide initially
        
        # Target Text (English)
        self.lbl_target = QLabel("")
        self.lbl_target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_target.setStyleSheet("""
            QLabel {
                color: #00FFCC; /* Neon cyan */
                font-family: 'Segoe UI', sans-serif;
                font-size: 32px;
                font-weight: 900;
                background-color: rgba(0, 0, 0, 160);
                padding: 10px 20px;
                border-radius: 15px;
                border: 2px solid rgba(0, 255, 204, 0.3);
            }
        """)
        self.lbl_target.setWordWrap(True)
        self.lbl_target.hide()
        
        layout.addWidget(self.lbl_source)
        layout.addSpacing(5)
        layout.addWidget(self.lbl_target)
        
        # Full screen geometry setup
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(0, 0, screen.width(), screen.height())
        
        # Auto-hide timer
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.clear_text)
        
    def update_text(self, source_text=None, target_text=None):
        if source_text:
            self.lbl_source.setText(source_text)
            self.lbl_source.show()
            self.lbl_source.adjustSize()
            
        if target_text:
            self.lbl_target.setText(target_text)
            self.lbl_target.show()
            self.lbl_target.adjustSize()
            
        # Reset timer (hide after 7 seconds of inactivity)
        self.hide_timer.start(7000)
        
    def clear_text(self):
        self.lbl_source.hide()
        self.lbl_target.hide()
