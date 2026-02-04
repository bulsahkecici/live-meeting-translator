"""Utility functions for zoom_live_translate."""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(config) -> None:
    """
    Set up logging based on configuration.
    
    Creates logs directory if needed and configures file + console logging.
    """
    log_config = config.logging_config
    
    # Create logs directory
    log_file = Path(log_config.get('file', 'logs/app.log'))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Get log level
    level_str = log_config.get('level', 'INFO').upper()
    level = getattr(logging, level_str, logging.INFO)
    
    # Configure logging
    max_bytes = log_config.get('max_bytes', 10485760)
    backup_count = log_config.get('backup_count', 5)
    
    # File handler with rotation
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.info(f"Logging initialized. Level: {level_str}, File: {log_file}")


def ensure_dir(path: Path) -> None:
    """Ensure directory exists, creating if needed."""
    path.mkdir(parents=True, exist_ok=True)


def get_tmp_dir() -> Path:
    """Get temporary directory for runtime files."""
    tmp_dir = Path(__file__).parent.parent / "tmp"
    ensure_dir(tmp_dir)
    return tmp_dir


def format_duration_ms(ms: float) -> str:
    """Format duration in milliseconds as human-readable string."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        minutes = int(ms / 60000)
        seconds = (ms % 60000) / 1000
        return f"{minutes}m {seconds:.1f}s"

