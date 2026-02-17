"""Configuration management for PawnAI Recorder.

This module provides configuration management and constants for audio recording.
"""

from pathlib import Path
from typing import Any, Dict, Optional

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 1)  # 1000ms
CHANNEL = 1
RECORDING_CHUNK_SIZE = 120
FILE_EXTENSION = 'flac'  # Use 'flac' (lossless), 'ogg' (lossy), 'wav', 'mp3', etc.
CHUNK_DIR = 'audio/'

# Sample width enum (from pyaudio)
SAMPLE_WIDTH_INT16 = 2

# MP3 format requirements
MP3_REQUIRED_RATE = 16000  # MP3 must be 16kHz
MP3_REQUIRED_CHANNELS = 1  # MP3 must be mono


class AppConfig:
    """Application configuration management."""

    def __init__(self) -> None:
        """Initialize configuration with defaults."""
        self._config: Dict[str, Any] = {
            'rate': RATE,
            'chunk': CHUNK,
            'channel': CHANNEL,
            'chunk_size': RECORDING_CHUNK_SIZE,
            'file_extension': FILE_EXTENSION,
            'output_dir': CHUNK_DIR,
            'sample_width': SAMPLE_WIDTH_INT16,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value.

        Args:
            key: Configuration key
            value: Configuration value
        """
        self._config[key] = value

    def get_output_dir(self) -> Path:
        """Get output directory as Path object.

        Returns:
            Output directory path
        """
        output_dir = self._config.get('output_dir', CHUNK_DIR)
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path
