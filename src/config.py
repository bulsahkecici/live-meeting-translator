"""Configuration management for zoom_live_translate."""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()


class Config:
    """Centralized configuration manager."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration from YAML file and environment variables."""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        
        self.config_path = Path(config_path)
        
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {self.config_path}\n"
                "Please copy config.yaml.example to config.yaml and configure it."
            )
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f) or {}
        
        if not self._config:
            logger.warning(
                "config.yaml is empty; using defaults. "
                "Copy config.yaml.example -> config.yaml and customize it."
            )
        
        # Load DeepL API key from environment
        self.deepl_api_key = os.getenv("DEEPL_API_KEY")
        if not self.deepl_api_key:
            logger.warning(
                "DEEPL_API_KEY not found in environment. "
                "Translation will fail. Set it in .env file."
            )
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-separated path.
        
        Example: config.get('audio.input.sample_rate')
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    @property
    def audio_input(self) -> Dict[str, Any]:
        """Audio input device configuration."""
        return self.get('audio.input', {})
    
    @property
    def audio_output(self) -> Dict[str, Any]:
        """Audio output device configuration."""
        return self.get('audio.output', {})
    
    @property
    def vad_config(self) -> Dict[str, Any]:
        """VAD configuration."""
        return self.get('vad', {})
    
    @property
    def stt_config(self) -> Dict[str, Any]:
        """STT configuration."""
        return self.get('stt', {})
    
    @property
    def translate_config(self) -> Dict[str, Any]:
        """Translation configuration."""
        return self.get('translate', {})
    
    @property
    def tts_config(self) -> Dict[str, Any]:
        """TTS configuration."""
        return self.get('tts', {})
    
    @property
    def logging_config(self) -> Dict[str, Any]:
        """Logging configuration."""
        return self.get('logging', {})
    
    @property
    def pipeline_config(self) -> Dict[str, Any]:
        """Pipeline configuration."""
        return self.get('pipeline', {})

    @property
    def incoming_subtitles_config(self) -> Dict[str, Any]:
        """Optional English-to-Turkish incoming subtitle configuration."""
        return self.get('incoming_subtitles', {})
