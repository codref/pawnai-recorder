"""Configuration management for PawnAI Recorder.

This module provides configuration constants and the :class:`AppConfig` class
which merges defaults with values from an optional YAML file
(``.pawnai-recorder.yml`` in the working directory).

Audio constants
---------------
- ``RATE``               – sample rate in Hz (default 16 000)
- ``CHUNK``              – PyAudio buffer size in frames
- ``CHANNEL``            – number of input channels (default 1 / mono)
- ``RECORDING_CHUNK_SIZE`` – how many PyAudio chunks form one saved file
- ``FILE_EXTENSION``     – audio container/codec (default ``'flac'``)
- ``CHUNK_DIR``          – default output directory (``'audio/'``)

Timestamp / filename formatting
-------------------------------
Filenames are built from a configurable template so that metadata such as the
recording device ID can be embedded without any post-processing.

- ``DATETIME_FORMAT``   – :func:`~datetime.datetime.strftime` pattern for the
  ``{ts}`` placeholder.  Default: ``'%y%m%d%H%M%S'``  → ``'231015143022'``.
- ``TIMESTAMP_FORMAT``  – Python format string applied to produce the session /
  chunk stem.  Supported placeholders:

  ==================  =====================================================
  Placeholder         Example value
  ==================  =====================================================
  ``{ts}``            ``231015143022``  (shaped by ``DATETIME_FORMAT``)
  ``{device_id}``     ``3``  (numeric device ID; ``'default'`` when absent)
  ==================  =====================================================

  Examples::

      '{ts}'                  # 231015143022_01.flac   (default)
      '{ts}_dev{device_id}'   # 231015143022_dev3_01.flac
      '{device_id}/{ts}'      # 3/231015143022_01.flac

Configuration file (``recording:`` section)
-------------------------------------------
All constants above can be overridden at runtime via ``.pawnai-recorder.yml``
placed in the project root:

.. code-block:: yaml

    recording:
      rate: 16000
      chunk_size: 120
      file_extension: flac
      output_dir: audio/
      timestamp_format: "{ts}_dev{device_id}"
      datetime_format: "%Y%m%d_%H%M%S"
"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 1)  # 1000ms
CHANNEL = 1
RECORDING_CHUNK_SIZE = 120
FILE_EXTENSION = 'flac'  # Use 'flac' (lossless), 'ogg' (lossy), 'wav', 'mp3', etc.
CHUNK_DIR = 'audio/'

# Timestamp / filename formatting
# Template variables available in TIMESTAMP_FORMAT:
#   {ts}        - datetime string formatted by DATETIME_FORMAT (strftime)
#   {device_id} - numeric audio device ID (or 'default' when not set)
DATETIME_FORMAT = '%y%m%d%H%M%S'
TIMESTAMP_FORMAT = '{ts}'  # default: datetime only, e.g. '231015143022'
S3_CONFIG_FILE = '.pawnai-recorder.yml'

# Local recording log
LOG_FILE = 'recordings.jsonl'

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
            'timestamp_format': TIMESTAMP_FORMAT,
            'datetime_format': DATETIME_FORMAT,
        }
        self._load_yaml_config()

    def _load_yaml_config(self) -> None:
        """Load optional YAML configuration from project root."""
        config_path = Path.cwd() / S3_CONFIG_FILE
        if not config_path.exists():
            return

        content = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        if not content:
            return

        if not isinstance(content, dict):
            raise ValueError(f"Configuration in {S3_CONFIG_FILE} must be a mapping")

        recording_config = content.get('recording')
        if isinstance(recording_config, dict):
            for key in self._config.keys():
                if key in recording_config:
                    self._config[key] = recording_config[key]

        for key, value in content.items():
            if key == 'recording':
                continue
            self._config[key] = value

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

    def get_s3_config(self) -> Optional[Dict[str, Any]]:
        """Get S3 configuration mapping, if present."""
        s3_config = self._config.get('s3')
        if isinstance(s3_config, dict):
            return s3_config
        return None

    def get_log_path(self, output_dir: Optional['Path'] = None) -> 'Path':
        """Return the recording log file path.

        The log file name is taken from the ``log.file`` key in
        ``.pawnai-recorder.yml`` when present, otherwise from the
        :data:`LOG_FILE` constant.  The file is placed inside *output_dir*
        (defaults to :meth:`get_output_dir`).

        Args:
            output_dir: Directory that will contain the log file.  When
                ``None`` the configured ``output_dir`` is used.

        Returns:
            Absolute path including the log filename.
        """
        log_config = self._config.get('log')
        log_file = LOG_FILE
        if isinstance(log_config, dict):
            log_file = log_config.get('file', LOG_FILE)
        base = Path(output_dir) if output_dir is not None else self.get_output_dir()
        return base / log_file
