"""Local JSONL recording log for PawnAI Recorder.

Appends structured JSON Lines entries to a log file alongside the audio files,
capturing session metadata, per-chunk file paths, S3 upload status, and
duration information.

Record types
------------
``session`` (event=``"start"``)
    Written once at the beginning of a recording run with device info and
    recording configuration.

``chunk``
    Written once per saved audio file chunk with the local file path,
    per-chunk duration, and S3 upload result.

``session`` (event=``"end"``)
    Written once when a recording run finishes with total duration and final
    chunk count.

Example log lines::

    {"type":"session","event":"start","session_id":"260223143022","conversation_id":"mtg-01","device_id":3,"device_name":"USB PnP Audio Device","sample_rate":16000,"channels":1,"format":"flac","started_at":"2026-02-23T14:30:22"}
    {"type":"chunk","session_id":"260223143022","chunk_index":1,"file_path":"audio/260223143022_01.flac","started_at":"2026-02-23T14:30:22","duration_sec":120.0,"s3_object_key":"conversations/mtg-01/260223143022/260223143022_01.flac","s3_uploaded":true}
    {"type":"session","event":"end","session_id":"260223143022","ended_at":"2026-02-23T14:32:22","total_duration_sec":120.0,"chunk_count":1}
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


class RecordingLogger:
    """Appends JSONL log entries for recording sessions and per-chunk files.

    Thread-safe: multiple chunk-saving threads may call :meth:`write_chunk`
    concurrently.  A single :class:`threading.Lock` serialises file writes.

    Args:
        log_path: Path to the ``.jsonl`` log file.  Parent directories are
            created automatically.
    """

    def __init__(self, log_path: Path) -> None:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path = log_path
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_session_start(
        self,
        session_id: str,
        conversation_id: Optional[str],
        device_id: Optional[int],
        device_name: str,
        sample_rate: int,
        channels: int,
        format: str,
        started_at: Optional[datetime] = None,
    ) -> None:
        """Append a session-start record.

        Args:
            session_id: Unique session identifier (timestamp string).
            conversation_id: Optional conversation grouping label.
            device_id: Numeric audio device ID (``None`` = system default).
            device_name: Human-readable device name.
            sample_rate: Actual sample rate negotiated with the device (Hz).
            channels: Number of recorded channels.
            format: Audio file format/extension (e.g. ``'flac'``).
            started_at: Session start time.  Defaults to ``datetime.now()``.
        """
        self._append({
            "type": "session",
            "event": "start",
            "session_id": session_id,
            "conversation_id": conversation_id,
            "device_id": device_id,
            "device_name": device_name,
            "sample_rate": sample_rate,
            "channels": channels,
            "format": format,
            "started_at": _iso(started_at),
        })

    def write_chunk(
        self,
        session_id: str,
        chunk_index: int,
        file_path: str,
        started_at: Optional[datetime],
        duration_sec: float,
        s3_object_key: Optional[str] = None,
        s3_uploaded: bool = False,
    ) -> None:
        """Append a per-chunk record.

        Args:
            session_id: Parent session identifier.
            chunk_index: 1-based chunk sequence number.
            file_path: Local path to the saved audio file.
            started_at: Timestamp when this chunk's recording started.
            duration_sec: Duration of this chunk in seconds.
            s3_object_key: S3 object key if the file was uploaded, else ``None``.
            s3_uploaded: ``True`` if the S3 upload completed successfully.
        """
        self._append({
            "type": "chunk",
            "session_id": session_id,
            "chunk_index": chunk_index,
            "file_path": file_path,
            "started_at": _iso(started_at),
            "duration_sec": round(duration_sec, 3),
            "s3_object_key": s3_object_key,
            "s3_uploaded": s3_uploaded,
        })

    def write_session_end(
        self,
        session_id: str,
        ended_at: Optional[datetime] = None,
        total_duration_sec: float = 0.0,
        chunk_count: int = 0,
    ) -> None:
        """Append a session-end record.

        Args:
            session_id: Session identifier matching the earlier start record.
            ended_at: Session end time.  Defaults to ``datetime.now()``.
            total_duration_sec: Cumulative audio duration across all chunks (s).
            chunk_count: Total number of chunks saved in this session.
        """
        self._append({
            "type": "session",
            "event": "end",
            "session_id": session_id,
            "ended_at": _iso(ended_at),
            "total_duration_sec": round(total_duration_sec, 3),
            "chunk_count": chunk_count,
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, record: dict) -> None:
        """Serialise *record* as JSON and append it to the log file."""
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)


def _iso(dt: Optional[datetime]) -> str:
    """Return a compact ISO 8601 string for *dt*, defaulting to now."""
    if dt is None:
        dt = datetime.now()
    return dt.replace(microsecond=0).isoformat()
