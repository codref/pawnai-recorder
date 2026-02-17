"""Audio file storage management for PawnAI Recorder.

This module provides storage and file management functionality for recordings.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class StorageManager:
    """Manages audio file storage and metadata."""

    def __init__(self, storage_dir: str = "audio/") -> None:
        """Initialize storage manager.

        Args:
            storage_dir: Root directory for audio storage
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def list_recordings(self) -> List[Dict[str, Any]]:
        """List all stored recordings.

        Returns:
            List of recording metadata dictionaries
        """
        recordings = []
        try:
            for audio_file in self.storage_dir.glob("*.flac"):
                recording_info = {
                    "name": audio_file.stem,
                    "path": str(audio_file),
                    "size": audio_file.stat().st_size,
                    "created": audio_file.stat().st_ctime,
                }
                recordings.append(recording_info)
        except Exception as e:
            logger.error(f"Error listing recordings: {e}")

        return recordings

    def get_recording_metadata(self, filename: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific recording.

        Args:
            filename: Name of the recording file

        Returns:
            Recording metadata dictionary or None if not found
        """
        try:
            file_path = self.storage_dir / filename
            if file_path.exists():
                return {
                    "name": file_path.stem,
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                    "created": file_path.stat().st_ctime,
                }
        except Exception as e:
            logger.error(f"Error getting recording metadata: {e}")

        return None

    def delete_recording(self, filename: str) -> bool:
        """Delete a recording file.

        Args:
            filename: Name of the recording file

        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = self.storage_dir / filename
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Deleted recording: {filename}")
                return True
        except Exception as e:
            logger.error(f"Error deleting recording: {e}")

        return False
