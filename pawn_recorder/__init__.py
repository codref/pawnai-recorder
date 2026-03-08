"""pawn_recorder — core library for audio recording, storage, and processing.

Shared by pawn_recorder_cli (CLI app) and pawn_recorder_droid (Android app).
"""

from .core.config import AppConfig
from .core.log import RecordingLogger
from .core.processing import apply_gain, calculate_db_level, detect_driver_type, draw_db_bar
from .core.queue_producer import SessionQueueProducer
from .core.recording import MicrophoneStream, RecordingEngine
from .core.s3_upload import S3Uploader, build_object_key
from .core.storage import StorageManager

__version__ = "1.0.0"
__author__ = "OpenBrain Team"

__all__ = [
    "AppConfig",
    "RecordingEngine",
    "MicrophoneStream",
    "RecordingLogger",
    "S3Uploader",
    "SessionQueueProducer",
    "StorageManager",
    "calculate_db_level",
    "draw_db_bar",
    "apply_gain",
    "detect_driver_type",
    "build_object_key",
]
