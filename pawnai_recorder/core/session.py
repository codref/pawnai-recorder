"""Live recording session shared by the CLI window and the status-bar icon.

:class:`RecordingSession` owns start/stop, force-flush, notes, and screenshots.
Audio comes from either :class:`~pawnai_recorder.core.recording.MicrophoneStream`
or :class:`SinkCapture` (a PulseAudio monitor read with ``parec``). Both publish
``transcribe-diarize`` through one :class:`~pawnai_recorder.core.jobs.ChunkPipeline`.
"""

from __future__ import annotations

import datetime
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf
from loguru import logger

from .config import AppConfig
from .jobs import (
    AttachmentTracker,
    ChunkPipeline,
    Note,
    Shot,
    format_session_offset,
    iso_now,
    new_attachment_id,
    resolve_diarize_mode,
)
from .log import RecordingLogger
from .recording import MicrophoneStream
from .s3_upload import S3Uploader


def format_stamp(
    timestamp_format: str,
    datetime_format: str,
    device_id,
    now: Optional[datetime.datetime] = None,
) -> str:
    """Build the session/chunk stem from the configured templates."""
    if now is None:
        now = datetime.datetime.now()
    ts = now.strftime(datetime_format)
    dev = device_id if device_id is not None else "default"
    return timestamp_format.format(ts=ts, device_id=dev)


def open_uploader(upload_enabled: bool) -> Optional[S3Uploader]:
    """Build an S3 uploader from ``.pawnai-recorder.yml``, or return ``None``."""
    if not upload_enabled:
        return None
    try:
        s3_config = AppConfig().get_s3_config()
        if not s3_config:
            logger.warning("S3 upload disabled: no `s3` config found in .pawnai-recorder.yml")
            return None
        return S3Uploader.from_dict(s3_config)
    except Exception as exc:
        logger.warning(f"S3 upload disabled: {exc}")
        return None


class SinkCapture:
    """Record a PulseAudio/PipeWire monitor source via ``parec``.

    The read loop runs on a background thread so the CLI window stays responsive.
    ``chunk_size`` is the number of 1-second reads that form one file, matching
    the historical ``record --sink`` command.
    """

    def __init__(
        self,
        monitor_source: str,
        rate: int,
        chunk_size: int,
        output_dir: str,
        file_format: str,
        gain: float,
        conversation_id: Optional[str],
        timestamp_format: str,
        datetime_format: str,
        recording_logger: Optional[RecordingLogger],
        uploader: Optional[S3Uploader],
        pipeline: ChunkPipeline,
        on_chunk: Optional[Callable[[dict], None]],
        initial_chunk_index: int = 0,
    ) -> None:
        self._monitor = monitor_source
        self._rate = rate
        self._chunk_size = chunk_size
        self._output_dir = output_dir if output_dir.endswith("/") else output_dir + "/"
        self._file_format = file_format
        self._gain = gain
        self._conversation_id = conversation_id
        self._timestamp_format = timestamp_format
        self._datetime_format = datetime_format
        self._recording_logger = recording_logger
        self._uploader = uploader
        self._pipeline = pipeline
        self._on_chunk = on_chunk

        self._session_id = format_stamp(timestamp_format, datetime_format, "default")
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._buf_lock = threading.Lock()
        self._read_buf: list = []
        self._read_count = 0
        self._chunk_count = initial_chunk_index
        self._total_frames = 0
        self._chunk_started_at = datetime.datetime.now()
        self._db = 0.0
        self._read_bytes = rate * 2

    @property
    def session_id(self) -> str:
        return self._session_id

    def get_current_db_level(self) -> float:
        return self._db

    def start_recording(self) -> dict:
        Path(self._output_dir).mkdir(parents=True, exist_ok=True)
        self._chunk_started_at = datetime.datetime.now()
        cmd = [
            "parec",
            f"--device={self._monitor}",
            "--format=s16le",
            f"--rate={self._rate}",
            "--channels=1",
            "--latency-msec=50",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "parec not found — install pulseaudio-utils"
            ) from exc

        if self._recording_logger is not None:
            self._recording_logger.write_session_start(
                session_id=self._session_id,
                conversation_id=self._conversation_id,
                device_id=None,
                device_name=self._monitor,
                sample_rate=self._rate,
                channels=1,
                format=self._file_format,
                started_at=self._chunk_started_at,
            )

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="parec-capture",
        )
        self._thread.start()
        return {
            "session_id": self._session_id,
            "device_name": self._monitor,
            "device_id": None,
            "sample_rate": self._rate,
            "output_dir": self._output_dir,
        }

    def stop_recording(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        if self._thread is not None:
            self._thread.join(timeout=30)
        self.force_flush()
        if self._recording_logger is not None:
            self._recording_logger.write_session_end(
                session_id=self._session_id,
                total_duration_sec=self._total_frames / self._rate if self._rate else 0.0,
                chunk_count=self._chunk_count,
            )
        self._pipeline.finish_transcription()

    def force_flush(self) -> bool:
        """Save, upload, and maybe diarize the audio gathered so far."""
        with self._buf_lock:
            if not self._read_buf:
                return False
            buf = list(self._read_buf)
            started = self._chunk_started_at
            self._read_buf = []
            self._read_count = 0
            self._chunk_count += 1
            index = self._chunk_count
            self._chunk_started_at = datetime.datetime.now()
        self._save_chunk(buf, index, started)
        return True

    def _loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while not self._stop.is_set():
            data = self._proc.stdout.read(self._read_bytes)
            if not data:
                break
            audio = np.frombuffer(data, dtype=np.int16).copy()
            rms = float(np.sqrt(np.mean(audio.astype(float) ** 2))) if audio.size else 0.0
            if rms > 0:
                db = 20 * np.log10(rms / 32768)
                self._db = max(0.0, min(120.0, db + 120))
            else:
                self._db = 0.0
            with self._buf_lock:
                self._read_buf.append(audio)
                self._read_count += 1
                full = self._read_count >= self._chunk_size
            if full:
                self.force_flush()

    def _emit(self, info: dict) -> None:
        if self._on_chunk is None:
            return
        try:
            self._on_chunk(info)
        except Exception as exc:
            logger.warning(f"Chunk listener failed: {exc}")

    def _save_chunk(self, buf: list, index: int, started_at: datetime.datetime) -> None:
        filename = f"{self._output_dir}{self._session_id}_{index:02}.{self._file_format}"
        self._emit({
            "index": index,
            "file_path": filename,
            "status": "saving",
            "duration_sec": 0.0,
            "s3_object_key": None,
            "error": None,
        })
        try:
            audio_arr = np.concatenate(buf)
            if self._gain != 1.0:
                audio_arr = np.clip(
                    audio_arr.astype(np.float32) * self._gain, -32768, 32767,
                ).astype(np.int16)
            audio_float = audio_arr.astype(np.float32) / 32768.0
            sf.write(filename, audio_float, self._rate, subtype="PCM_16")
            duration_sec = len(audio_arr) / self._rate
            self._total_frames += len(audio_arr)

            s3_object_key = None
            s3_uploaded = False
            publish_status = "saved"
            if self._uploader is not None:
                try:
                    s3_object_key = self._uploader.upload_file(
                        local_path=filename,
                        session_id=self._session_id,
                        conversation_id=self._conversation_id,
                    )
                    s3_uploaded = True
                    publish_status = self._pipeline.on_uploaded(s3_object_key)
                    logger.info(f"Uploaded to S3: s3://{self._uploader.bucket}/{s3_object_key}")
                except Exception as exc:
                    logger.warning(f"Upload failed for chunk {index}: {exc}")
                    publish_status = "upload_failed"

            if self._recording_logger is not None:
                self._recording_logger.write_chunk(
                    session_id=self._session_id,
                    chunk_index=index,
                    file_path=filename,
                    started_at=started_at,
                    duration_sec=duration_sec,
                    s3_object_key=s3_object_key,
                    s3_uploaded=s3_uploaded,
                )

            status = "saved"
            if s3_uploaded:
                status = (
                    "diarize_published" if publish_status == "diarize_published" else "uploaded"
                )
            elif self._uploader is not None:
                status = "upload_failed"
            self._emit({
                "index": index,
                "file_path": filename,
                "status": status,
                "duration_sec": duration_sec,
                "s3_object_key": s3_object_key,
                "error": None if status != "upload_failed" else "upload failed",
            })
        except Exception as exc:
            logger.error(f"Error saving {filename}: {exc}")
            self._emit({
                "index": index,
                "file_path": filename,
                "status": "upload_failed",
                "duration_sec": 0.0,
                "s3_object_key": None,
                "error": str(exc),
            })


class RecordingSession:
    """One CLI process that can start and stop takes without exiting.

    Stopping a take flushes the open chunk, publishes the end-of-session
    diarize message when that mode is selected, then publishes ``analyze`` and
    ``sync-siyuan``. The queue client stays open so the next take can reuse it.
    """

    def __init__(
        self,
        *,
        output_dir: str,
        rate: int,
        chunk_size: int,
        file_format: str,
        gain: float,
        device_id: Optional[int],
        sink: Optional[str],
        conversation_id: Optional[str],
        upload_enabled: bool,
        verbose: bool,
        timestamp_format: str,
        datetime_format: str,
        session_label: Optional[str],
        recording_logger: RecordingLogger,
        queue_producer,
        queue_job_config: dict,
        screenshot_output: Optional[str] = None,
        screenshot_every: Optional[float] = None,
    ) -> None:
        self.output_dir = output_dir if output_dir.endswith("/") else output_dir + "/"
        self.rate = rate
        self.chunk_size = chunk_size
        self.file_format = file_format
        self.gain = gain
        self.device_id = device_id
        self.sink = sink
        self.conversation_id = conversation_id
        self.upload_enabled = upload_enabled
        self.verbose = verbose
        self.timestamp_format = timestamp_format
        self.datetime_format = datetime_format
        self.session_label = session_label
        self.recording_logger = recording_logger
        self.queue_producer = queue_producer
        self.queue_job_config = queue_job_config
        self.screenshot_output = screenshot_output
        self.screenshot_every = screenshot_every

        self._uploader = open_uploader(upload_enabled)
        self._attachments = AttachmentTracker()
        self._pipeline: Optional[ChunkPipeline] = None
        self._backend = None
        self._info: Optional[dict] = None
        self._session_id = ""
        self._chunks: dict = {}
        self._state_lock = threading.Lock()
        self._running = threading.Event()
        self._take_started: Optional[float] = None
        self._recorded_sec = 0.0
        self._chunk_count = 0
        self._shot_index = 0
        self._shot_stop: Optional[threading.Event] = None
        self._shot_thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None
        self._listeners: list = []
        self.request_quit: Optional[Callable[[], None]] = None
        # PortAudio must be opened and closed on the main thread. Tray clicks
        # enqueue work here; the UI loop drains it.
        self._audio_ops: queue.Queue = queue.Queue()
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    @property
    def is_recording(self) -> bool:
        return self._running.is_set()

    @property
    def screenshots_enabled(self) -> bool:
        return bool(self.screenshot_output)

    @property
    def diarize_mode(self) -> str:
        return resolve_diarize_mode(self.queue_job_config, None)

    def session_value(self) -> str:
        """Label sent in queue messages (explicit label, else the file session id)."""
        if self.session_label is not None:
            return self.session_label
        return self._session_id

    def elapsed_sec(self) -> float:
        """Seconds of audio in this session, across pause/resume."""
        if self._running.is_set() and self._take_started is not None:
            return self._recorded_sec + (time.monotonic() - self._take_started)
        return self._recorded_sec

    def db_level(self) -> float:
        if self._backend is None:
            return 0.0
        return float(self._backend.get_current_db_level())

    def subscribe(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def snapshot(self) -> dict:
        notes, shots = self._attachments.snapshot()
        with self._state_lock:
            chunks = [self._chunks[key] for key in sorted(self._chunks)]
        info = self._info or {}
        return {
            "recording": self.is_recording,
            "session_id": self._session_id,
            "session_label": self.session_value(),
            "elapsed_sec": self.elapsed_sec(),
            "db": self.db_level(),
            "diarize_mode": self.diarize_mode,
            "chunks": chunks,
            "notes": [note.to_payload() for note in notes],
            "screenshots": [shot.to_payload() for shot in shots],
            "screenshots_enabled": self.screenshots_enabled,
            "last_error": self._last_error,
            "device_name": info.get("device_name", ""),
            "output_dir": self.output_dir,
        }

    def drain_audio_ops(self) -> None:
        """Run tray-requested start/stop/flush on the main thread."""
        while True:
            try:
                fn, box, done = self._audio_ops.get_nowait()
            except queue.Empty:
                return
            try:
                box["result"] = fn()
            except Exception as exc:
                box["exc"] = exc
            finally:
                done.set()

    def _on_main_thread(self, fn):
        if threading.current_thread() is threading.main_thread():
            return fn()
        box: dict = {}
        done = threading.Event()
        self._audio_ops.put((fn, box, done))
        if not done.wait(timeout=120):
            raise TimeoutError("audio operation timed out")
        if "exc" in box:
            raise box["exc"]
        return box.get("result")

    def start(self) -> dict:
        """Open the audio backend and begin a new take. No-op if already recording."""
        return self._on_main_thread(self._start_impl)

    def _start_impl(self) -> dict:
        if self._running.is_set():
            return dict(self._info or {})

        # Keep notes and earlier chunks. Android does the same: a new file
        # stem, and the chunk index continues so the name does not collide.
        self._last_error = None
        bucket = self._uploader.bucket if self._uploader is not None else ""
        self._pipeline = ChunkPipeline(
            producer=self.queue_producer,
            bucket=bucket,
            queue_job_config=self.queue_job_config,
            session_value=self.session_value,
            attachments=self._attachments,
        )
        self._backend = self._open_backend()
        self._session_id = self._backend.session_id
        try:
            self._info = self._backend.start_recording()
        except Exception as exc:
            self._last_error = str(exc)
            self._backend = None
            self._notify()
            raise
        self._take_started = time.monotonic()
        self._running.set()
        self._start_shot_timer()
        self._notify()
        return dict(self._info)

    def stop(self) -> None:
        """Flush, publish the closing jobs, and return to idle."""
        self._on_main_thread(self._stop_impl)

    def _stop_impl(self) -> None:
        if not self._running.is_set():
            return
        # Finish an in-flight periodic capture before the final chunk publish
        # so that screenshot is included in the closing payload.
        self._stop_shot_timer()
        if self._take_started is not None:
            self._recorded_sec += time.monotonic() - self._take_started
            self._take_started = None
        self._running.clear()
        backend = self._backend
        if backend is not None:
            backend.stop_recording()
        if self._pipeline is not None:
            self._pipeline.publish_session_close()
        self._notify()

    def toggle(self) -> None:
        self._on_main_thread(self._toggle_impl)

    def _toggle_impl(self) -> None:
        if self.is_recording:
            self._stop_impl()
        else:
            self._start_impl()

    def force_flush(self) -> bool:
        return bool(self._on_main_thread(self._flush_impl))

    def _flush_impl(self) -> bool:
        if not self.is_recording or self._backend is None:
            return False
        return bool(self._backend.force_flush())

    def add_note(self, text: str) -> Optional[Note]:
        """Store a note for the open take and append it to the JSONL log."""
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        if not self.is_recording:
            raise RuntimeError("not recording")
        offset = self.elapsed_sec()
        note = self._attachments.add_note(
            cleaned,
            at=format_session_offset(offset),
            offset_sec=offset,
        )
        self.recording_logger.write_note(
            session_id=self._session_id,
            note_id=note.id,
            at=note.at,
            text=note.text,
        )
        self._notify()
        return note

    def take_screenshot(self) -> Shot:
        """Capture ``screenshot_output`` now, upload it, and remember it for the payload."""
        if not self.screenshots_enabled:
            raise RuntimeError("screen capture is not enabled")
        if not self.is_recording:
            raise RuntimeError("not recording")

        from pawnai_recorder.desktop.capture import capture_to

        self._shot_index += 1
        dest = Path(self.output_dir) / f"{self._session_id}_shot_{self._shot_index:02d}.png"
        try:
            capture_to(dest, output=self.screenshot_output or "")
        except Exception as exc:
            self._shot_index -= 1
            self._last_error = str(exc)
            self._notify()
            raise

        s3_key = None
        s3_uri = None
        if self._uploader is not None:
            try:
                s3_key = self._uploader.upload_file(
                    local_path=str(dest),
                    session_id=self._session_id,
                    conversation_id=self.conversation_id,
                )
                s3_uri = f"s3://{self._uploader.bucket}/{s3_key}"
            except Exception as exc:
                logger.warning(f"Screenshot upload failed: {exc}")
                self._last_error = f"screenshot upload failed: {exc}"

        shot = Shot(
            id=new_attachment_id(),
            at=iso_now(),
            s3_uri=s3_uri,
            output=self.screenshot_output or "",
            region=None,
            local_path=str(dest),
        )
        self._attachments.add_shot(shot)
        self.recording_logger.write_screenshot(
            session_id=self._session_id,
            shot_id=shot.id,
            at=shot.at,
            file_path=str(dest),
            output=shot.output,
            s3_object_key=s3_key,
            s3_uri=s3_uri,
        )
        self._notify()
        return shot

    def set_error(self, message: Optional[str]) -> None:
        self._last_error = message
        self._notify()

    def quit(self) -> None:
        """Ask the UI to exit. Falls back to :meth:`close` when no UI is attached."""
        if self.request_quit is not None:
            self.request_quit()
            return
        self.close()

    def close(self) -> None:
        """Stop an open take and tear down the queue producer."""
        if self.is_recording:
            self.stop()
        producer = self.queue_producer
        self.queue_producer = None
        if producer is not None:
            producer.close()

    def _open_backend(self):
        assert self._pipeline is not None
        if self.sink:
            monitor = self.sink if self.sink.endswith(".monitor") else f"{self.sink}.monitor"
            return SinkCapture(
                monitor_source=monitor,
                rate=self.rate,
                chunk_size=self.chunk_size,
                output_dir=self.output_dir,
                file_format=self.file_format,
                gain=self.gain,
                conversation_id=self.conversation_id,
                timestamp_format=self.timestamp_format,
                datetime_format=self.datetime_format,
                recording_logger=self.recording_logger,
                uploader=self._uploader,
                pipeline=self._pipeline,
                on_chunk=self._on_chunk,
                initial_chunk_index=self._chunk_count,
            )
        return MicrophoneStream(
            rate=self.rate,
            output_dir=self.output_dir,
            chunk_size=self.chunk_size,
            device_id=self.device_id,
            show_level_meter=True,
            gain_factor=self.gain,
            file_format=self.file_format,
            conversation_id=self.conversation_id,
            upload_enabled=self._uploader is not None,
            verbose=self.verbose,
            timestamp_format=self.timestamp_format,
            datetime_format=self.datetime_format,
            recording_logger=self.recording_logger,
            queue_producer=self.queue_producer,
            session_label=self.session_label,
            queue_job_config=self.queue_job_config,
            uploader=self._uploader,
            pipeline=self._pipeline,
            on_chunk=self._on_chunk,
            initial_chunk_index=self._chunk_count,
        )

    def _on_chunk(self, info: dict) -> None:
        index = int(info["index"])
        with self._state_lock:
            self._chunks[index] = dict(info)
            if index > self._chunk_count:
                self._chunk_count = index
        self._notify()

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception as exc:
                logger.debug(f"Session listener failed: {exc}")

    def _start_shot_timer(self) -> None:
        every = self.screenshot_every
        if not self.screenshots_enabled or not every or every <= 0:
            return
        self._shot_stop = threading.Event()

        def _loop() -> None:
            assert self._shot_stop is not None
            while not self._shot_stop.wait(every):
                if not self.is_recording:
                    continue
                try:
                    self.take_screenshot()
                except Exception as exc:
                    logger.warning(f"Periodic screenshot failed: {exc}")

        self._shot_thread = threading.Thread(
            target=_loop, daemon=True, name="screenshot-timer",
        )
        self._shot_thread.start()

    def _stop_shot_timer(self) -> None:
        stop = self._shot_stop
        thread = self._shot_thread
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=15)
        self._shot_stop = None
        self._shot_thread = None
