"""Queue payload helpers shared by the microphone and sink recorders.

``transcribe-diarize`` messages may carry ``annotations`` and ``screenshots``.
Pawn ignores those keys until the contract in
``docs/PAWNAI_ANNOTATIONS_CONTRACT.md`` is implemented. They are omitted when
empty so older consumers see the same object they do today.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

DIARIZE_PER_CHUNK = "per_chunk"
DIARIZE_END_OF_SESSION = "end_of_session"
DIARIZE_MODES = (DIARIZE_PER_CHUNK, DIARIZE_END_OF_SESSION)


def resolve_diarize_mode(queue_job_config: Optional[dict], override: Optional[str]) -> str:
    """Return the diarize publish mode, with *override* winning over YAML.

    Args:
        queue_job_config: Result of :meth:`AppConfig.get_queue_job_config`.
        override: CLI value, or ``None`` to keep the configured mode.

    Raises:
        ValueError: If the resolved mode is not ``per_chunk`` or ``end_of_session``.
    """
    if override is not None:
        mode = override
    else:
        td = (queue_job_config or {}).get("transcribe_diarize") or {}
        mode = td.get("mode", DIARIZE_END_OF_SESSION)
    if mode not in DIARIZE_MODES:
        allowed = ", ".join(DIARIZE_MODES)
        raise ValueError(f"diarize mode must be one of {allowed}, got {mode!r}")
    return str(mode)


def with_diarize_mode(queue_job_config: Optional[dict], mode: str) -> Dict[str, Any]:
    """Copy *queue_job_config* with ``transcribe_diarize.mode`` set to *mode*."""
    resolve_diarize_mode(queue_job_config, mode)
    cfg = dict(queue_job_config or {})
    td = dict(cfg.get("transcribe_diarize") or {})
    td["mode"] = mode
    cfg["transcribe_diarize"] = td
    return cfg


def new_attachment_id() -> str:
    """Stable id for a note or screenshot, used to dedupe on the Pawn side."""
    return uuid.uuid4().hex


def iso_now() -> str:
    """Local time as compact ISO 8601 with the UTC offset."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def format_session_offset(seconds: float) -> str:
    """Format seconds from the start of the session as ``MM:SS.ss``."""
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    hundredths = int(round((seconds - whole) * 100))
    if hundredths >= 100:
        whole += 1
        hundredths -= 100
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{hundredths:02d}"
    return f"{minutes:02d}:{secs:02d}.{hundredths:02d}"


@dataclass
class Note:
    """A note taken during a recording.

    ``at`` is the offset from the start of the whole session (``MM:SS.ss``),
    not from the current chunk. ``offset_sec`` is that same offset in seconds.
    """

    id: str
    at: str
    text: str
    offset_sec: Optional[float] = None

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": self.id, "at": self.at, "text": self.text}
        if self.offset_sec is not None:
            payload["offset_sec"] = round(float(self.offset_sec), 3)
        return payload


@dataclass
class Shot:
    """A screenshot captured for the current session.

    ``region`` is reserved for a future crop and stays ``None`` for now.
    """

    id: str
    at: str
    s3_uri: Optional[str]
    output: str
    region: Optional[dict] = None
    local_path: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at,
            "s3_uri": self.s3_uri,
            "output": self.output,
            "region": self.region,
        }


class AttachmentTracker:
    """Thread-safe notes and screenshots, with publish-once bookkeeping.

    :meth:`take_delta` returns items not yet attached to a queue message.
    :meth:`full_set` returns every item (used for the single end-of-session
    ``transcribe-diarize`` message) and marks them published.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.notes: List[Note] = []
        self.shots: List[Shot] = []
        self._published: set = set()

    def add_note(
        self,
        text: str,
        at: Optional[str] = None,
        offset_sec: Optional[float] = None,
    ) -> Note:
        note = Note(
            id=new_attachment_id(),
            at=at or iso_now(),
            text=text,
            offset_sec=offset_sec,
        )
        with self._lock:
            self.notes.append(note)
        return note

    def add_shot(self, shot: Shot) -> Shot:
        with self._lock:
            self.shots.append(shot)
        return shot

    def take_delta(self) -> Tuple[List[dict], List[dict]]:
        """Return and mark unpublished notes and screenshots."""
        with self._lock:
            notes = [n for n in self.notes if n.id not in self._published]
            shots = [s for s in self.shots if s.id not in self._published]
            self._published.update(n.id for n in notes)
            self._published.update(s.id for s in shots)
        return [n.to_payload() for n in notes], [s.to_payload() for s in shots]

    def full_set(self) -> Tuple[List[dict], List[dict]]:
        """Return every note and screenshot and mark them published."""
        with self._lock:
            notes = list(self.notes)
            shots = list(self.shots)
            self._published.update(n.id for n in notes)
            self._published.update(s.id for s in shots)
        return [n.to_payload() for n in notes], [s.to_payload() for s in shots]

    def snapshot(self) -> Tuple[List[Note], List[Shot]]:
        with self._lock:
            return list(self.notes), list(self.shots)


def build_transcribe_diarize_payload(
    session: str,
    audio_paths: Sequence[str],
    transcribe_config: Optional[dict],
    annotations: Optional[Sequence[dict]] = None,
    screenshots: Optional[Sequence[dict]] = None,
) -> Dict[str, Any]:
    """Build one ``transcribe-diarize`` message.

    Annotation and screenshot lists are included only when non-empty.
    """
    td = transcribe_config or {}
    payload: Dict[str, Any] = {
        "command": "transcribe-diarize",
        "audio_paths": list(audio_paths),
        "threshold": td.get("threshold", 0.2),
        "cross_file_threshold": td.get("cross_file_threshold", 0.2),
        "session": session,
        "device": td.get("device", "cpu"),
    }
    if annotations:
        payload["annotations"] = list(annotations)
    if screenshots:
        payload["screenshots"] = list(screenshots)
    return payload


class ChunkPipeline:
    """Uploads become one shared ``transcribe-diarize`` publish path.

    ``per_chunk`` publishes immediately and attaches notes and screenshots
    taken since the previous publish. ``end_of_session`` accumulates object
    URIs and publishes once from :meth:`finish_transcription`, with the full
    attachment set. ``analyze`` and ``sync-siyuan`` never carry those fields.
    """

    def __init__(
        self,
        producer: Any,
        bucket: str,
        queue_job_config: Optional[dict],
        session_value,
        attachments: AttachmentTracker,
    ) -> None:
        self._producer = producer
        self._bucket = bucket
        self._queue_job_config = queue_job_config or {}
        self._session_value = session_value
        self._attachments = attachments
        self._lock = threading.Lock()
        self._uris: List[str] = []
        self._audio_finished = False

    @property
    def mode(self) -> str:
        td = self._queue_job_config.get("transcribe_diarize") or {}
        return td.get("mode", DIARIZE_END_OF_SESSION)

    def on_uploaded(self, object_key: str) -> str:
        """Record an uploaded object key.

        Returns:
            ``diarize_published`` when a per-chunk message was submitted,
            otherwise ``accumulated``.
        """
        uri = f"s3://{self._bucket}/{object_key}" if self._bucket else object_key
        if self._producer is None:
            if self.mode != DIARIZE_PER_CHUNK:
                with self._lock:
                    self._uris.append(uri)
            return "accumulated"

        if self.mode == DIARIZE_PER_CHUNK:
            notes, shots = self._attachments.take_delta()
            self._publish_diarize([uri], notes, shots)
            with self._lock:
                self._uris.append(uri)
            return "diarize_published"

        with self._lock:
            self._uris.append(uri)
        return "accumulated"

    def finish_transcription(self) -> None:
        """Publish the end-of-session diarize message, once."""
        with self._lock:
            if self._audio_finished:
                return
            self._audio_finished = True
            uris = list(self._uris)
        if self.mode != DIARIZE_END_OF_SESSION or not uris or self._producer is None:
            return
        notes, shots = self._attachments.full_set()
        self._publish_diarize(uris, notes, shots)

    def publish_session_close(self) -> None:
        """Publish ``analyze`` and ``sync-siyuan`` when those blocks are configured."""
        if self._producer is None:
            return
        session = self._session_value()
        analyze = self._queue_job_config.get("analyze")
        if analyze is not None:
            self._producer.publish({
                "command": "analyze",
                "session": session,
                "mode": analyze.get("mode", "summary"),
                "model": analyze.get("model", "gpt-4o"),
            })
        if self._queue_job_config.get("sync_siyuan") is not None:
            self._producer.publish({
                "command": "sync-siyuan",
                "session": session,
            })

    def _publish_diarize(
        self,
        uris: Sequence[str],
        notes: Sequence[dict],
        shots: Sequence[dict],
    ) -> None:
        td = self._queue_job_config.get("transcribe_diarize") or {}
        payload = build_transcribe_diarize_payload(
            session=self._session_value(),
            audio_paths=uris,
            transcribe_config=td,
            annotations=notes,
            screenshots=shots,
        )
        self._producer.publish(payload)
