"""Audio recording engine for PawnAI Recorder.

This module provides real-time audio capture capabilities with support for
multiple audio devices and formats.

Main public classes
-------------------
:class:`RecordingEngine`
    Static helpers for enumerating available input devices.

:class:`MicrophoneStream`
    Streams audio from a PyAudio input device and saves it to disk in
    configurable chunks.  The stream is **non-blocking**: audio is captured
    in a callback thread and written to files by separate daemon threads so
    the caller only needs a lightweight polling loop.

Timestamp / filename formatting
-------------------------------
Every session and individual chunk file is named using a configurable
timestamp template.  Pass ``timestamp_format`` and/or ``datetime_format`` to
:class:`MicrophoneStream` (or set them as CLI options / YAML config entries)
to customise how filenames look.

Supported ``timestamp_format`` placeholders:

==================  ==========================================================
Placeholder         Example value
==================  ==========================================================
``{ts}``            ``231015143022``  (shaped by ``datetime_format``)
``{device_id}``     ``3``  (numeric device ID; ``'default'`` when not set)
==================  ==========================================================

Examples::

    # default – datetime only
    MicrophoneStream(timestamp_format='{ts}', device_id=3)
    # session_id → '231015143022'
    # files     → audio/231015143022_01.flac

    # include device ID
    MicrophoneStream(timestamp_format='{ts}_dev{device_id}', device_id=3)
    # session_id → '231015143022_dev3'
    # files     → audio/231015143022_dev3_01.flac

    # ISO-style date with device tag
    MicrophoneStream(
        timestamp_format='{ts}_dev{device_id}',
        datetime_format='%Y-%m-%dT%H%M%S',
        device_id=3,
    )
    # files → audio/2023-10-15T143022_dev3_01.flac
"""

import atexit
import datetime
import os
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from typing import Callable, Optional

import numpy as np
import pyaudio
import soundfile as sf
from loguru import logger

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from .config import (
    RATE, CHUNK, CHANNEL, RECORDING_CHUNK_SIZE, FILE_EXTENSION,
    MP3_REQUIRED_RATE, MP3_REQUIRED_CHANNELS,
    TIMESTAMP_FORMAT, DATETIME_FORMAT,
)
from .processing import apply_gain, calculate_db_level
from .config import AppConfig
from .log import RecordingLogger
from .queue_producer import SessionQueueProducer
from .s3_upload import S3Uploader

# PortAudio crashes if Pa_Initialize / Pa_Terminate run on different threads,
# or if a second instance is created while the first is still shutting down.
# One instance is created on the thread that first records and kept until exit.
_pyaudio_lock = threading.Lock()
_pyaudio_instance = None


def shared_pyaudio():
    """Return the process-wide PyAudio instance, creating it once."""
    global _pyaudio_instance
    with _pyaudio_lock:
        if _pyaudio_instance is None:
            _pyaudio_instance = pyaudio.PyAudio()
        return _pyaudio_instance


def _shutdown_pyaudio() -> None:
    global _pyaudio_instance
    with _pyaudio_lock:
        instance = _pyaudio_instance
        _pyaudio_instance = None
    if instance is not None:
        try:
            instance.terminate()
        except Exception:
            pass


atexit.register(_shutdown_pyaudio)

# ALSA plugin names that PortAudio lists as inputs but that fail to open
# under PipeWire. The real capture devices are "pulse" and the hardware input.
_UNOPENABLE_INPUT_NAMES = frozenset({
    "default",
    "sysdefault",
    "pipewire",
    "lavrate",
    "samplerate",
    "speexrate",
    "speex",
    "upmix",
    "vdownmix",
})


@contextmanager
def quiet_stderr():
    """Hide C-library noise on stderr (ALSA, JACK, PortAudio)."""
    original_stderr_fd = os.dup(2)
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null_fd, 2)
            yield
        finally:
            os.close(null_fd)
    finally:
        os.dup2(original_stderr_fd, 2)
        os.close(original_stderr_fd)


def input_candidate_order(devices: list, preferred_id: Optional[int]) -> list:
    """Order input device ids: preferred, then Pulse, then real hardware, then the rest.

    The ALSA ``default`` plugin is often PortAudio's default and refuses to
    open on PipeWire. Pulse and modest-channel hardware devices are tried next.
    """
    by_id = {device["id"]: device for device in devices}
    ordered: list = []

    def add(device_id: Optional[int]) -> None:
        if device_id in by_id and device_id not in ordered:
            ordered.append(device_id)

    add(preferred_id)
    for device in devices:
        if str(device.get("name", "")).strip().lower() == "pulse":
            add(device["id"])
    for device in devices:
        if device.get("driver") == "pulse":
            add(device["id"])
    for device in devices:
        name = str(device.get("name", "")).strip().lower()
        channels = int(device.get("channels") or 0)
        if name not in _UNOPENABLE_INPUT_NAMES and 0 < channels <= 8:
            add(device["id"])
    for device in devices:
        add(device["id"])
    return ordered


def first_openable_input(devices: list, preferred_id: Optional[int]) -> Optional[int]:
    """Return the first input device id that accepts a mono capture stream."""
    if not devices:
        return None
    audio = pyaudio.PyAudio()
    try:
        for device_id in input_candidate_order(devices, preferred_id):
            try:
                info = audio.get_device_info_by_index(device_id)
            except OSError:
                continue
            rate = int(info.get("defaultSampleRate") or RATE)
            try:
                with quiet_stderr():
                    stream = audio.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=rate,
                        input=True,
                        input_device_index=device_id,
                        frames_per_buffer=1024,
                    )
                stream.close()
                return device_id
            except OSError:
                continue
        return None
    finally:
        audio.terminate()


def format_input_open_error(device_id, device_name: str, exc: BaseException) -> str:
    """Explain a PortAudio open failure, including the usual PipeWire case."""
    message = f"Could not open input {device_id} ({device_name}): {exc}."
    if str(device_name).strip().lower() == "default":
        message += (
            " That ALSA device often fails under PipeWire;"
            " choose pulse or the hardware input from list-devices."
        )
    else:
        message += " Try another id from 'pawnai-recorder list-devices'."
    return message


class RecordingEngine:
    """Real-time audio recording engine with device and format support."""

    @staticmethod
    def list_output_devices() -> list:
        """List available PulseAudio/PipeWire output sinks and their monitor sources.

        Uses ``pactl list short sinks`` to enumerate sinks.  Each entry includes
        the sink name and the corresponding ``.monitor`` source name that can be
        passed to ``parec --device=<monitor>`` for loopback capture.

        Returns:
            List of dicts with keys: name, monitor, description, state.
            Returns an empty list if ``pactl`` is unavailable or fails.
        """
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True, text=True, timeout=3,
            )
            sinks = []
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    sink_name = parts[1].strip()
                    state = parts[4].strip() if len(parts) >= 5 else "UNKNOWN"
                    sinks.append({
                        "name": sink_name,
                        "monitor": f"{sink_name}.monitor",
                        "description": sink_name,
                        "state": state,
                    })
            # Also get human-readable descriptions
            try:
                desc_result = subprocess.run(
                    ["pactl", "list", "sinks"],
                    capture_output=True, text=True, timeout=3,
                )
                current_name = None
                desc_map: dict = {}
                for line in desc_result.stdout.splitlines():
                    line_stripped = line.strip()
                    if line_stripped.startswith("Name:"):
                        current_name = line_stripped.split(":", 1)[1].strip()
                    elif line_stripped.startswith("Description:") and current_name:
                        desc_map[current_name] = line_stripped.split(":", 1)[1].strip()
                for sink in sinks:
                    if sink["name"] in desc_map:
                        sink["description"] = desc_map[sink["name"]]
            except Exception:
                pass
            return sinks
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return []

    @staticmethod
    def list_devices(
        driver_filter: Optional[str] = None,
        audio: Optional["pyaudio.PyAudio"] = None,
    ) -> list:
        """List all available input audio devices.

        Args:
            driver_filter: Optional driver type to filter by ('pulse', 'alsa', 'jack', 'usb', 'default')
            audio: Optional existing PyAudio instance to reuse.  When provided the
                caller is responsible for calling ``audio.terminate()``; when
                omitted a temporary instance is created and terminated internally.
                Reusing an instance across enumeration **and** stream opening is
                important on PulseAudio systems — multiple rapid init/terminate
                cycles can cause PortAudio to enumerate stale ALSA virtual
                devices that have no real audio signal.

        Returns:
            List of dicts with keys: id, name, driver, channels, rate, is_default
        """
        from .processing import detect_driver_type

        _owns_audio = audio is None
        if _owns_audio:
            audio = pyaudio.PyAudio()
        try:
            device_count = audio.get_device_count()
            try:
                default_device = audio.get_default_input_device_info()
                default_device_id = int(default_device['index'])
            except OSError:
                # No default input device registered yet (e.g. PulseAudio still
                # enumerating on first PortAudio init).  Continue without marking
                # any device as default so the caller still gets the full list.
                default_device_id = -1

            devices = []

            for i in range(device_count):
                try:
                    device_info = audio.get_device_info_by_index(i)
                except OSError:
                    continue
                if device_info.get('maxInputChannels', 0) > 0:
                    device_name = device_info.get('name', 'Unknown')
                    driver_type = detect_driver_type(device_name)

                    # Skip if driver filter is specified and doesn't match
                    if driver_filter and driver_type != driver_filter.lower():
                        continue

                    channels = device_info.get('maxInputChannels', 0)
                    output_channels = device_info.get('maxOutputChannels', 0)
                    sample_rate = int(device_info.get('defaultSampleRate', 0))
                    devices.append({
                        'id': i,
                        'name': device_name,
                        'driver': driver_type,
                        'channels': channels,
                        'output_channels': output_channels,
                        'rate': sample_rate,
                        'is_default': (i == default_device_id),
                    })
        finally:
            if _owns_audio:
                audio.terminate()

        return devices


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(
        self,
        rate: int = RATE,
        chunk: int = CHUNK,
        output_dir: str = "audio/",
        chunk_size: int = RECORDING_CHUNK_SIZE,
        device_id: Optional[int] = None,
        show_level_meter: bool = True,
        gain_factor: float = 1.0,
        file_format: str = FILE_EXTENSION,
        conversation_id: Optional[str] = None,
        upload_enabled: bool = True,
        verbose: bool = False,
        timestamp_format: str = TIMESTAMP_FORMAT,
        datetime_format: str = DATETIME_FORMAT,
        recording_logger: Optional[RecordingLogger] = None,
        queue_producer: Optional[SessionQueueProducer] = None,
        session_label: Optional[str] = None,
        queue_job_config: Optional[dict] = None,
        uploader: Optional[S3Uploader] = None,
        pipeline: Optional[object] = None,
        on_chunk: Optional[Callable[[dict], None]] = None,
        initial_chunk_index: int = 0,
    ) -> None:
        """Initialize the microphone stream.

        Args:
            rate: Sample rate in Hz
            chunk: Chunk size in samples
            output_dir: Output directory for recordings
            chunk_size: Number of frames per chunk
            device_id: Audio device ID to use
            show_level_meter: Whether to show level meter
            gain_factor: Input gain factor
            file_format: Audio format (flac, ogg, wav, mp3, etc.)
            conversation_id: Optional conversation ID for S3 uploads
            upload_enabled: Whether S3 upload is enabled
            verbose: Enable verbose/debug output
            timestamp_format: Python format string for the session/chunk timestamp.
                Supported placeholders: ``{ts}`` (datetime string), ``{device_id}``.
                Example: ``'{ts}_dev{device_id}'``  →  ``'231015143022_dev3'``
            datetime_format: strftime format applied to ``{ts}``.
                Default: ``'%y%m%d%H%M%S'``

        Raises:
            ValueError: If MP3 format is requested with invalid sample rate or channels
        """
        # Validate MP3 format requirements
        if file_format.lower() == 'mp3':
            if rate != MP3_REQUIRED_RATE:
                raise ValueError(
                    f"MP3 format requires {MP3_REQUIRED_RATE}Hz sample rate, got {rate}Hz"
                )
            if CHANNEL != MP3_REQUIRED_CHANNELS:
                raise ValueError(
                    f"MP3 format requires {MP3_REQUIRED_CHANNELS} channel (mono), got {CHANNEL}"
                )

        self._rate = rate
        self._chunk = chunk
        self._channel = CHANNEL
        self._sample_width = pyaudio.paInt16
        self._output_dir = output_dir
        self._chunk_size = chunk_size
        self._device_id = device_id
        self._show_level_meter = show_level_meter
        self._gain_factor = gain_factor
        self._file_format = file_format
        self._conversation_id = conversation_id
        self._upload_enabled = upload_enabled
        self._verbose = verbose
        self._current_db_level = 0
        self._timestamp_format = timestamp_format
        self._datetime_format = datetime_format

        self._audio_interface = None
        self._audio_stream = None
        self._accepting = False

        self._recording_frames = []
        self._frames_lock = threading.Lock()
        self._count = initial_chunk_index
        self._session_id = self._build_timestamp(device_id=device_id)
        self._uploader: Optional[S3Uploader] = uploader

        # Recording logger and session tracking
        self._recording_logger = recording_logger
        self._queue_producer = queue_producer
        self._session_label = session_label
        self._queue_job_config = queue_job_config or {}
        self._pipeline = pipeline
        self._on_chunk = on_chunk
        self._session_started_at: Optional[datetime.datetime] = None
        self._total_duration_sec: float = 0.0
        self._save_lock = threading.Lock()
        self._saving_threads: list = []
        # S3 object keys collected across all chunks for the end-of-session
        # transcribe-diarize message (used when mode == 'end_of_session'
        # and no shared ChunkPipeline was supplied).
        self._s3_upload_keys: list = []

        if uploader is None:
            self._initialize_uploader()

        # Create output directory if it doesn't exist
        Path(self._output_dir).mkdir(parents=True, exist_ok=True)

    def _build_timestamp(
        self,
        dt: Optional[datetime.datetime] = None,
        device_id: Optional[int] = None,
    ) -> str:
        """Build a timestamp string from the configured format.

        Args:
            dt: Datetime to format. Defaults to ``datetime.datetime.now()``.
            device_id: Device ID to embed. Falls back to ``self._device_id`` when
                omitted; uses the string ``'default'`` if neither is set.

        Returns:
            Formatted timestamp string ready to use in filenames.
        """
        if dt is None:
            dt = datetime.datetime.now()
        ts = dt.strftime(self._datetime_format)
        dev = device_id if device_id is not None else (
            self._device_id if self._device_id is not None else 'default'
        )
        return self._timestamp_format.format(ts=ts, device_id=dev)

    def _initialize_uploader(self) -> None:
        """Initialize optional S3 uploader from YAML configuration."""
        if not self._upload_enabled:
            logger.info('S3 upload disabled by CLI flag')
            return

        try:
            app_config = AppConfig()
            s3_config = app_config.get_s3_config()
            if not s3_config:
                logger.warning('S3 upload disabled: no `s3` config found in .pawnai-recorder.yml')
                return
            self._uploader = S3Uploader.from_dict(s3_config)
        except Exception as error:
            logger.warning(f'S3 upload disabled: {error}')

    def start_recording(self) -> None:
        """Start the recording stream."""
        from contextlib import nullcontext

        silence = quiet_stderr() if not self._verbose else nullcontext()
        device_name = str(self._device_id)
        with silence:
            self._audio_interface = shared_pyaudio()
            self._accepting = True
            try:
                # Get device info and use its native sample rate
                device_info = self._audio_interface.get_device_info_by_index(self._device_id)
                device_sample_rate = int(device_info.get('defaultSampleRate', self._rate))
                device_name = device_info.get('name', 'Unknown')

                # Update the rate to match device's native rate
                self._rate = device_sample_rate
                self._session_started_at = datetime.datetime.now()

                self._device_name = device_name
                self._audio_stream = self._audio_interface.open(
                    format=self._sample_width,
                    channels=self._channel,
                    rate=self._rate,
                    input=True,
                    input_device_index=self._device_id,
                    frames_per_buffer=self._chunk,
                    stream_callback=self._fill_buffer,
                )
            except OSError as exc:
                self._release_audio()
                raise OSError(format_input_open_error(self._device_id, device_name, exc)) from exc

        if self._recording_logger is not None:
            self._recording_logger.write_session_start(
                session_id=self._session_id,
                conversation_id=self._conversation_id,
                device_id=self._device_id,
                device_name=device_name,
                sample_rate=self._rate,
                channels=self._channel,
                format=self._file_format,
                started_at=self._session_started_at,
            )

        return {
            'session_id': self._session_id,
            'device_name': device_name,
            'device_id': self._device_id,
            'sample_rate': self._rate,
            'output_dir': self._output_dir,
        }

    def _release_audio(self) -> None:
        """Close this capture stream. The shared PyAudio instance stays up.

        Terminating PortAudio here segfaults when the next take starts, and
        when stop runs on a different thread from the one that opened it.
        """
        self._accepting = False
        stream = self._audio_stream
        self._audio_stream = None
        self._audio_interface = None
        if stream is None:
            return
        try:
            if stream.is_active():
                stream.stop_stream()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def stop_recording(self) -> None:
        """Close the recording stream and save any remaining frames."""
        self._release_audio()

        self._flush_partial_buffer()

        # Wait for all chunk-saving threads to complete before writing session end
        with self._save_lock:
            threads_snapshot = list(self._saving_threads)
        for t in threads_snapshot:
            t.join(timeout=30.0)

        if self._recording_logger is not None:
            self._recording_logger.write_session_end(
                session_id=self._session_id,
                total_duration_sec=self._total_duration_sec,
                chunk_count=self._count,
            )

        # End-of-session transcribe-diarize, after every chunk file is on disk.
        if self._pipeline is not None:
            self._pipeline.finish_transcription()
        elif self._queue_producer is not None and self._s3_upload_keys:
            from .jobs import DIARIZE_END_OF_SESSION, build_transcribe_diarize_payload

            _td = self._queue_job_config.get('transcribe_diarize', {})
            if _td.get('mode', DIARIZE_END_OF_SESSION) == DIARIZE_END_OF_SESSION:
                self._queue_producer.publish(build_transcribe_diarize_payload(
                    session=self._session_value(),
                    audio_paths=list(self._s3_upload_keys),
                    transcribe_config=_td,
                ))
                logger.info(
                    f'End-of-session transcribe-diarize published '
                    f'({len(self._s3_upload_keys)} chunk(s))'
                )

        logger.info('Microphone has been closed')

    def force_flush(self) -> bool:
        """Close the current buffer early, save it, and upload it.

        Matches the Android "Force upload chunk" action. A no-op when the
        buffer is empty.

        Returns:
            ``True`` when a partial chunk was handed to a save thread.
        """
        return self._flush_partial_buffer()

    def _flush_partial_buffer(self) -> bool:
        with self._frames_lock:
            if not self._recording_frames:
                return False
            saving_frames = self._recording_frames[:]
            self._recording_frames = []
            self._count += 1
            count = self._count
        self._create_chunk_saving_thread(saving_frames, count)
        return True

    def _session_value(self) -> str:
        if self._session_label is not None:
            return self._session_label
        return self._session_id

    def _emit_chunk(self, info: dict) -> None:
        if self._on_chunk is None:
            return
        try:
            self._on_chunk(info)
        except Exception as exc:
            logger.warning(f'Chunk listener failed: {exc}')

    def _fill_buffer(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: object,
        status_flags: object,
    ) -> tuple:
        """Continuously collect data from the audio stream into the buffer.

        Args:
            in_data: The audio data as a bytes object
            frame_count: The number of frames captured
            time_info: The time information
            status_flags: The status flags

        Returns:
            Tuple of (data, status_flag)
        """
        if not self._accepting:
            return None, pyaudio.paComplete

        # Apply gain to audio data
        processed_data = apply_gain(in_data, self._gain_factor)

        # Calculate and update dB level for display (on processed data)
        if self._show_level_meter:
            self._current_db_level = calculate_db_level(processed_data, sample_width=2)

        saving_frames = None
        count = 0
        with self._frames_lock:
            self._recording_frames.append(processed_data)
            if len(self._recording_frames) >= self._chunk_size:
                saving_frames = self._recording_frames[:]
                self._recording_frames = []
                self._count += 1
                count = self._count
        if saving_frames is not None:
            self._create_chunk_saving_thread(saving_frames, count)

        return None, pyaudio.paContinue

    def get_current_db_level(self) -> float:
        """Get the current dB level.

        Returns:
            Current dB level
        """
        return self._current_db_level

    @property
    def session_id(self) -> str:
        """Timestamp session id used in filenames and queue messages."""
        return self._session_id

    def _create_chunk_saving_thread(self, saving_frames, count):
        """Create a thread to save audio chunk asynchronously.

        Args:
            saving_frames: Frames to save
            count: Chunk count
        """
        created_at = self._build_timestamp()
        chunk_started_at = datetime.datetime.now()

        saving_thread = Thread(
            target=self._save,
            args=(saving_frames, count, created_at, chunk_started_at),
            daemon=True,
        )
        saving_thread.start()
        with self._save_lock:
            self._saving_threads.append(saving_thread)
        logger.info(f'Saving chunk {count} (session: {self._session_id})')

    def _save(self, frames, count, start_time, chunk_started_at=None):
        """Save audio frames to file.

        Args:
            frames: List of audio frames
            count: Chunk number
            start_time: Start timestamp string
            chunk_started_at: datetime when this chunk started recording
        """
        # Ensure output directory has trailing slash
        output_dir = self._output_dir if self._output_dir.endswith('/') else self._output_dir + '/'
        filename = f'{output_dir}{self._session_id}_{count:02}.{self._file_format}'
        self._emit_chunk({
            "index": count,
            "file_path": filename,
            "status": "saving",
            "duration_sec": 0.0,
            "s3_object_key": None,
            "error": None,
        })

        try:
            # Convert byte frames to numpy audio array
            audio_data = np.frombuffer(b''.join(frames), dtype=np.int16)

            if self._file_format.lower() == 'mp3':
                # Save MP3 format
                self._save_mp3(filename, audio_data)
            else:
                # Normalize to float32 for soundfile (-1.0 to 1.0 range)
                audio_data = audio_data.astype(np.float32) / 32768.0

                # Write with soundfile (supports FLAC, OGG, WAV, etc.)
                sf.write(filename, audio_data, self._rate, subtype='PCM_16')

            duration_sec = len(frames) * self._chunk / self._rate
            with self._save_lock:
                self._total_duration_sec += duration_sec

            s3_object_key: Optional[str] = None
            s3_uploaded = False
            if self._uploader:
                try:
                    s3_object_key = self._uploader.upload_file(
                        local_path=filename,
                        session_id=self._session_id,
                        conversation_id=self._conversation_id,
                    )
                    s3_uploaded = True
                    logger.info(f'Uploaded to S3: s3://{self._uploader.bucket}/{s3_object_key}')
                    publish_status = self._publish_uploaded(s3_object_key)
                except Exception as error:
                    logger.warning(f'Upload failed for {filename}: {error}')
                    publish_status = "upload_failed"
            else:
                publish_status = "saved"

            if self._recording_logger is not None:
                self._recording_logger.write_chunk(
                    session_id=self._session_id,
                    chunk_index=count,
                    file_path=filename,
                    started_at=chunk_started_at,
                    duration_sec=duration_sec,
                    s3_object_key=s3_object_key,
                    s3_uploaded=s3_uploaded,
                )

            status = "saved"
            if s3_uploaded:
                status = "diarize_published" if publish_status == "diarize_published" else "uploaded"
            elif self._uploader and not s3_uploaded:
                status = "upload_failed"
            self._emit_chunk({
                "index": count,
                "file_path": filename,
                "status": status,
                "duration_sec": duration_sec,
                "s3_object_key": s3_object_key,
                "error": None if status != "upload_failed" else "upload failed",
            })

            logger.info(f'Saved: {filename} ({len(frames)} frames)')
        except Exception as e:
            logger.error(f'Error saving {filename}: {e}')
            self._emit_chunk({
                "index": count,
                "file_path": filename,
                "status": "upload_failed",
                "duration_sec": 0.0,
                "s3_object_key": None,
                "error": str(e),
            })

    def _publish_uploaded(self, object_key: str) -> str:
        """Hand an uploaded object to the shared pipeline, or publish inline."""
        if self._pipeline is not None:
            return self._pipeline.on_uploaded(object_key)

        if self._queue_producer is None or self._uploader is None:
            return "accumulated"

        from .jobs import DIARIZE_PER_CHUNK, build_transcribe_diarize_payload

        td = self._queue_job_config.get('transcribe_diarize', {})
        uri = f"s3://{self._uploader.bucket}/{object_key}"
        if td.get('mode', 'end_of_session') == DIARIZE_PER_CHUNK:
            self._queue_producer.publish(build_transcribe_diarize_payload(
                session=self._session_value(),
                audio_paths=[uri],
                transcribe_config=td,
            ))
            return "diarize_published"

        with self._save_lock:
            self._s3_upload_keys.append(uri)
        return "accumulated"

    def _save_mp3(self, filename: str, audio_data: np.ndarray) -> None:
        """Save audio data as MP3 file.

        Args:
            filename: Output MP3 file path
            audio_data: Audio data as int16 numpy array

        Raises:
            RuntimeError: If MP3 encoding fails
        """
        if PYDUB_AVAILABLE:
            # Use pydub if available
            try:
                audio_segment = AudioSegment(
                    data=audio_data.tobytes(),
                    sample_width=2,  # 16-bit = 2 bytes
                    frame_rate=self._rate,
                    channels=self._channel
                )
                audio_segment.export(filename, format="mp3", bitrate="192k")
                return
            except Exception as e:
                logger.debug(f"Pydub MP3 encoding failed, trying ffmpeg: {e}")

        # Fallback: Use ffmpeg command line
        try:
            self._save_mp3_with_ffmpeg(filename, audio_data)
        except Exception as e:
            logger.error(f"MP3 encoding failed: {e}")
            raise

    def _save_mp3_with_ffmpeg(self, filename: str, audio_data: np.ndarray) -> None:
        """Save audio data as MP3 using ffmpeg command line.

        Args:
            filename: Output MP3 file path
            audio_data: Audio data as int16 numpy array

        Raises:
            RuntimeError: If ffmpeg is not available or encoding fails
        """
        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_wav = tmp.name
            # Normalize to float32 for soundfile
            audio_float = audio_data.astype(np.float32) / 32768.0
            sf.write(tmp_wav, audio_float, self._rate, subtype='PCM_16')

        try:
            # Ensure output directory exists
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Use ffmpeg to convert WAV to MP3
            cmd = [
                'ffmpeg',
                '-i', tmp_wav,
                '-codec:a', 'libmp3lame',
                '-b:a', '192k',
                '-y',  # Overwrite output file without asking
                filename
            ]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"ffmpeg encoding complete for {filename}")
        except FileNotFoundError:
            raise RuntimeError(
                "MP3 encoding requires either 'pydub' package or 'ffmpeg' command line tool. "
                "Install with: pip install pydub or apt-get install ffmpeg"
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg stderr: {e.stderr}")
            raise RuntimeError(f"ffmpeg MP3 encoding failed: {e.stderr}")
        finally:
            # Clean up temporary WAV file
            try:
                Path(tmp_wav).unlink()
            except Exception as e:
                logger.debug(f"Error cleaning up temp file {tmp_wav}: {e}")
