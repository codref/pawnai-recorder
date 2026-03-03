"""CLI commands for PawnAI Recorder.

This module provides all command-line interface commands using Typer.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
import typer
from loguru import logger
from rich.live import Live
from rich.panel import Panel
from rich.prompt import IntPrompt
from rich.table import Table

from pawnai_recorder.core import (
    MicrophoneStream,
    RecordingEngine,
)
from pawnai_recorder.core.s3_upload import S3Uploader
from pawnai_recorder.core.config import (
    AppConfig, RATE, RECORDING_CHUNK_SIZE, FILE_EXTENSION, CHUNK_DIR,
    TIMESTAMP_FORMAT, DATETIME_FORMAT,
)
from pawnai_recorder.core.log import RecordingLogger
from pawnai_recorder.cli.utils import console, suppress_stderr, make_device_table, make_level_progress, make_monitor_progress, make_sinks_table

app = typer.Typer(help="Professional audio recording and management CLI")

app_config = AppConfig()
default_output_dir = str(app_config.get("output_dir", CHUNK_DIR))
default_rate = int(app_config.get("rate", RATE))
default_chunk_size = int(app_config.get("chunk_size", RECORDING_CHUNK_SIZE))
default_file_extension = str(app_config.get("file_extension", FILE_EXTENSION))
default_timestamp_format = str(app_config.get("timestamp_format", TIMESTAMP_FORMAT))
default_datetime_format = str(app_config.get("datetime_format", DATETIME_FORMAT))


@app.command()
def list_devices(
    driver: Optional[str] = typer.Option(
        None, help="Filter by driver type: pulse, alsa, jack, usb, default"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output from audio libraries"
    ),
):
    """List all available input audio devices."""
    if verbose:
        devices = RecordingEngine.list_devices(driver_filter=driver)
    else:
        with suppress_stderr():
            devices = RecordingEngine.list_devices(driver_filter=driver)

    title = "Available Input Devices"
    if driver:
        title += f" (filtered by: {driver})"
    console.print(Panel(make_device_table(devices), title=f"[bold]{title}[/bold]"))


@app.command()
def list_sinks(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output"
    ),
):
    """List available output (speaker) sinks that can be recorded via their monitor source.

    Use the value in the 'Monitor Source' column as --sink when running the
    record command to capture what is playing on that output device.
    """
    sinks = RecordingEngine.list_output_devices()
    if not sinks:
        console.print("[warning]No PulseAudio sinks found (is pactl installed?)[/warning]")
        sys.exit(1)
    console.print(Panel(
        make_sinks_table(sinks),
        title="[bold]Available Output Sinks[/bold]",
        subtitle="[dim]Pass the Monitor Source value to: pawnai-recorder record --sink <monitor>[/dim]",
    ))


@app.command()
def record(
    duration: Optional[int] = typer.Option(
        None, help="Recording duration in seconds. Leave empty for continuous recording."
    ),
    output: str = typer.Option(default_output_dir, help="Output directory for recordings"),
    rate: int = typer.Option(default_rate, help="Sample rate in Hz"),
    chunk_size: int = typer.Option(default_chunk_size, help="Frames per chunk"),
    device_id: Optional[int] = typer.Option(
        None, help="Audio device ID to use. Leave empty to select interactively."
    ),
    sink: Optional[str] = typer.Option(
        None,
        help=(
            "PulseAudio monitor source to record from instead of a microphone. "
            "Run 'list-sinks' to see available values (e.g. alsa_output.pci-...analog-stereo.monitor). "
            "When set, --device-id is ignored."
        ),
    ),
    driver: Optional[str] = typer.Option(
        None, help="Filter devices by driver: pulse, alsa, jack, usb, default"
    ),
    gain: float = typer.Option(
        1.0, help="Input gain/amplification factor (1.0=no change, 2.0=+6dB, 0.5=-6dB)"
    ),
    format: str = typer.Option(
        default_file_extension,
        help="Audio format: flac (lossless), ogg (lossy), wav (uncompressed), mp3 (16kHz mono)",
    ),
    conversation_id: Optional[str] = typer.Option(
        None, help="Optional conversation ID to organize S3 uploads as conversation_id/timestamp/filename."
    ),
    upload: bool = typer.Option(
        True,
        "--upload/--no-upload",
        help="Enable upload by default; use --no-upload to bypass S3 upload for this recording.",
    ),
    timestamp_format: str = typer.Option(
        default_timestamp_format,
        help=(
            "Format string for the session/chunk timestamp used in filenames. "
            "Placeholders: {ts} (datetime), {device_id}. "
            "Example: '{ts}_dev{device_id}'  →  '231015143022_dev3'"
        ),
    ),
    datetime_format: str = typer.Option(
        default_datetime_format,
        help="strftime format applied to the {ts} placeholder. Default: '%%y%%m%%d%%H%%M%%S'.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output from audio libraries"
    ),
    log_file: Optional[str] = typer.Option(
        None,
        help=(
            "Override the recording log filename (relative to --output directory). "
            "Defaults to the value from .pawnai-recorder.yml or 'recordings.jsonl'."
        ),
    ),
):
    """Start a new audio recording."""
    # Configure loguru log level based on verbose flag
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="WARNING")

    # Ensure output directory ends with /
    output_dir = output if output.endswith('/') else output + '/'

    # Initialise the recording log
    _log_path = Path(output_dir) / log_file if log_file else app_config.get_log_path(Path(output_dir))
    recording_logger = RecordingLogger(_log_path)
    console.print(f'[dim]📝 Recording log: {_log_path}[/dim]')

    # ------------------------------------------------------------------
    # OUTPUT SINK path: capture via parec <sink>.monitor
    # ------------------------------------------------------------------
    if sink is not None:
        import datetime as _dt
        import soundfile as sf

        # Normalise: accept either "alsa_output.xxx" or "alsa_output.xxx.monitor"
        monitor_source = sink if sink.endswith(".monitor") else f"{sink}.monitor"

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Session ID: apply the same timestamp_format template as the mic path
        _now = _dt.datetime.now()
        _ts_str = _now.strftime(datetime_format)
        session_id = timestamp_format.format(ts=_ts_str, device_id="default")

        # ------------------------------------------------------------------
        # Initialise optional S3 uploader (same logic as MicrophoneStream)
        # ------------------------------------------------------------------
        _uploader = None
        if upload:
            try:
                _s3_cfg = app_config.get_s3_config()
                if _s3_cfg:
                    _uploader = S3Uploader.from_dict(_s3_cfg)
                else:
                    console.print("[dim]S3 upload: no config in .pawnai-recorder.yml — skipping[/dim]")
            except Exception as _e:
                console.print(f"[warning]S3 init failed: {_e}[/warning]")

        # Each parec read is exactly one second of audio at the requested rate.
        # We accumulate chunk_size reads before closing the file — identical semantics
        # to the microphone path where chunk_size counts PyAudio callbacks.
        _read_bytes = rate * 2  # s16le → 2 bytes per sample; 1 second per read
        _read_buf: list = []    # accumulated np.int16 arrays for current chunk
        _read_count = 0          # reads accumulated so far
        _chunk_count = 0
        _total_frames = 0
        _chunk_started_at = _now
        _start_time = time.time()

        # Each read = 1 s, so chunk_size reads = chunk_size seconds per file
        _chunk_sec = chunk_size

        gain_str = f"{gain:.2f}x"
        if gain != 1.0:
            gain_str += f" ({20 * np.log10(gain):+.1f} dB)"
        upload_str = "[green]enabled[/green]" if _uploader else "[yellow]disabled[/yellow]"

        console.print(Panel(
            f"[dim]Monitor:[/dim]    {monitor_source}\n"
            f"[dim]Session:[/dim]    {session_id}\n"
            f"[dim]Rate:[/dim]       {rate} Hz  |  [dim]Format:[/dim] {format.upper()}\n"
            f"[dim]Chunk size:[/dim] {chunk_size} reads ≈ {_chunk_sec:.0f} s/file\n"
            f"[dim]Gain:[/dim]       {gain_str}\n"
            f"[dim]Upload:[/dim]     {upload_str}\n"
            f"[dim]Duration:[/dim]   {f'{duration}s' if duration else 'continuous — Ctrl+C to stop'}",
            title="[bold]🔊 Recording Output Sink[/bold]",
            border_style="magenta",
        ))

        parec_cmd = [
            "parec",
            f"--device={monitor_source}",
            "--format=s16le",
            f"--rate={rate}",
            "--channels=1",
            "--latency-msec=50",
        ]
        try:
            proc = subprocess.Popen(parec_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            console.print("[error]✗ parec not found — install pulseaudio-utils[/error]")
            sys.exit(1)

        # Log session start
        recording_logger.write_session_start(
            session_id=session_id,
            conversation_id=conversation_id,
            device_id=None,
            device_name=monitor_source,
            sample_rate=rate,
            channels=1,
            format=format,
            started_at=_now,
        )

        def _flush_chunk(buf: list, idx: int, started_at: _dt.datetime) -> None:
            """Save *buf* arrays to a chunk file, upload, and log."""
            nonlocal _total_frames
            if not buf:
                return
            chunk_file = output_path / f"{session_id}_{idx:02d}.{format}"
            audio_arr = np.concatenate(buf)  # int16
            if gain != 1.0:
                audio_arr = np.clip(
                    audio_arr.astype(np.float32) * gain, -32768, 32767
                ).astype(np.int16)
            audio_float = audio_arr.astype(np.float32) / 32768.0
            sf.write(str(chunk_file), audio_float, rate, subtype="PCM_16")
            dur_sec = len(audio_arr) / rate
            _total_frames += len(audio_arr)

            # S3 upload
            s3_key: Optional[str] = None
            s3_ok = False
            if _uploader:
                try:
                    s3_key = _uploader.upload_file(
                        local_path=str(chunk_file),
                        session_id=session_id,
                        conversation_id=conversation_id,
                    )
                    s3_ok = True
                    console.print(f"[dim]⬆  Uploaded chunk {idx}: {s3_key}[/dim]")
                except Exception as _ue:
                    console.print(f"[warning]Upload failed for chunk {idx}: {_ue}[/warning]")

            # JSONL log
            recording_logger.write_chunk(
                session_id=session_id,
                chunk_index=idx,
                file_path=str(chunk_file),
                started_at=started_at,
                duration_sec=dur_sec,
                s3_object_key=s3_key,
                s3_uploaded=s3_ok,
            )
            console.print(f"[dim]💾 Saved chunk {idx}: {chunk_file} ({dur_sec:.1f} s)[/dim]")

        try:
            with make_level_progress() as progress:
                task = progress.add_task("level", total=120, db_text="-- dB")
                while True:
                    if duration and (time.time() - _start_time) >= duration:
                        break
                    data = proc.stdout.read(_read_bytes)
                    if not data:
                        break
                    audio_chunk = np.frombuffer(data, dtype=np.int16).copy()
                    _read_buf.append(audio_chunk)
                    _read_count += 1

                    # Level meter (on raw, pre-gain signal for display)
                    rms = np.sqrt(np.mean(audio_chunk.astype(float) ** 2))
                    db = max(0.0, min(120.0, 20 * np.log10(rms / 32768) + 120)) if rms > 0 else 0.0
                    progress.update(task, completed=db, db_text=f"{db:.1f} dB")

                    # Flush when we have accumulated chunk_size reads
                    if _read_count >= chunk_size:
                        _chunk_count += 1
                        _flush_chunk(_read_buf[:], _chunk_count, _chunk_started_at)
                        _read_buf = []
                        _read_count = 0
                        _chunk_started_at = _dt.datetime.now()

        except KeyboardInterrupt:
            console.print("\n[warning]⏹ Recording interrupted by user[/warning]")
        finally:
            proc.terminate()

        # Save any remaining frames that did not fill a full chunk
        if _read_buf:
            _chunk_count += 1
            _flush_chunk(_read_buf, _chunk_count, _chunk_started_at)

        # Log session end
        recording_logger.write_session_end(
            session_id=session_id,
            total_duration_sec=_total_frames / rate,
            chunk_count=_chunk_count,
        )

        console.print(
            f"[success]✓ Recorded {_total_frames / rate:.1f} s in {_chunk_count} chunk(s)[/success]"
        )
        return

    # ------------------------------------------------------------------
    # Normal INPUT (microphone) path
    # ------------------------------------------------------------------
    # List devices and get user selection if not specified
    if device_id is None:
        if verbose:
            devices = RecordingEngine.list_devices(driver_filter=driver)
        else:
            with suppress_stderr():
                devices = RecordingEngine.list_devices(driver_filter=driver)
        if not devices:
            console.print(
                "[error]✗ No input devices found"
                + (f" for driver: {driver}" if driver else "")
                + "[/error]"
            )
            sys.exit(1)

        title = "Available Input Devices"
        if driver:
            title += f" (filtered by: {driver})"
        console.print(Panel(make_device_table(devices), title=f"[bold]{title}[/bold]"))

        input_device_ids = [d['id'] for d in devices]
        try:
            import pyaudio

            if verbose:
                audio = pyaudio.PyAudio()
            else:
                with suppress_stderr():
                    audio = pyaudio.PyAudio()
            default_device = audio.get_default_input_device_info()
            default_device_id = int(default_device['index']) if default_device else -1
            if default_device_id not in input_device_ids:
                default_device_id = input_device_ids[0] if input_device_ids else 0
            audio.terminate()
            device_id = IntPrompt.ask(
                "📍 Select device ID",
                console=console,
                default=default_device_id,
            )
            if device_id not in input_device_ids:
                console.print(f"[error]✗ Invalid device ID: {device_id}[/error]")
                sys.exit(1)
        except ValueError:
            console.print("[error]✗ Invalid input[/error]")
            sys.exit(1)

    stream = None

    def signal_handler(sig, frame):
        console.print("\n[warning]⏹ Received interrupt signal, stopping recording...[/warning]")
        if stream:
            stream.stop_recording()
        # Give threads time to finish saving
        time.sleep(1)
        sys.exit(0)

    import signal

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        stream = MicrophoneStream(
            rate=rate,
            output_dir=output_dir,
            chunk_size=chunk_size,
            device_id=device_id,
            show_level_meter=True,
            gain_factor=gain,
            file_format=format,
            conversation_id=conversation_id,
            upload_enabled=upload,
            verbose=verbose,
            timestamp_format=timestamp_format,
            datetime_format=datetime_format,
            recording_logger=recording_logger,
        )
        if verbose:
            session_info = stream.start_recording()
        else:
            with suppress_stderr():
                session_info = stream.start_recording()

        # Build and display session summary Panel
        upload_str = "[green]enabled[/green]" if upload else "[yellow]bypassed (--no-upload)[/yellow]"
        gain_str = f"{gain:.2f}x"
        if gain != 1.0 and gain > 0:
            gain_str += f" ({20 * np.log10(gain):+.1f} dB)"
        duration_str = f"{duration}s" if duration else "continuous — Ctrl+C to stop"

        info_grid = Table.grid(padding=(0, 1))
        info_grid.add_column(style="dim", justify="right")
        info_grid.add_column()
        info_grid.add_row("Session ID:", session_info['session_id'])
        info_grid.add_row("Device:", f"{session_info['device_name']} (ID: {session_info['device_id']})")
        info_grid.add_row("Sample Rate:", f"{session_info['sample_rate']} Hz")
        info_grid.add_row("Format:", format.upper())
        if gain != 1.0:
            info_grid.add_row("Gain:", gain_str)
        info_grid.add_row("Upload:", upload_str)
        info_grid.add_row("Duration:", duration_str)
        info_grid.add_row("Output:", session_info['output_dir'])
        info_grid.add_row("Log:", str(_log_path))
        console.print(Panel(info_grid, title="[bold]🎙 Recording Session[/bold]", border_style="green"))

        if duration:
            start_time = time.time()
            with make_level_progress() as progress:
                task = progress.add_task("level", total=120, db_text="-- dB")
                while time.time() - start_time < duration:
                    db_level = stream.get_current_db_level()
                    progress.update(task, completed=db_level, db_text=f"{db_level:.1f} dB")
                    time.sleep(0.1)
            stream.stop_recording()
            time.sleep(1.5)
            console.print("[success]✓ Recording completed[/success]")
        else:
            console.rule("[bold]Real-time dB Level Meter[/bold] — Ctrl+C to stop")
            with make_level_progress() as progress:
                task = progress.add_task("level", total=120, db_text="-- dB")
                while True:
                    db_level = stream.get_current_db_level()
                    progress.update(task, completed=db_level, db_text=f"{db_level:.1f} dB")
                    time.sleep(0.1)

    except KeyboardInterrupt:
        console.print("[warning]⏹ Recording interrupted by user[/warning]")
        if stream:
            stream.stop_recording()
            # Wait for background threads to finish saving
            time.sleep(1.5)
    except Exception as e:
        console.print(f"[error]✗ Error during recording: {e}[/error]")
        if stream:
            stream.stop_recording()
            # Wait for background threads to finish saving
            time.sleep(1.5)
        sys.exit(1)


@app.command()
def monitor(
    duration: Optional[int] = typer.Option(
        None, help="Monitor duration in seconds. Leave empty for continuous monitoring."
    ),
    rate: int = typer.Option(default_rate, help="Sample rate in Hz"),
    chunk_size: int = typer.Option(default_chunk_size, help="Frames per chunk"),
    interval: float = typer.Option(0.2, help="Refresh interval in seconds (larger = less flicker)"),
    include_output: bool = typer.Option(
        True, "--include-output/--no-include-output",
        help="Also monitor output (speaker) devices via PulseAudio monitor sources.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output from audio libraries"
    ),
):
    """Monitor all audio devices in real-time to identify which has audio.

    Shows live audio levels for all connected input devices and, when
    --include-output is set (the default), also output devices captured via
    their PulseAudio monitor sources using parec.
    Press Ctrl+C to stop monitoring.
    """
    # Configure loguru log level based on verbose flag
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="WARNING")

    import pyaudio

    # Create a single PyAudio instance shared across enumeration AND stream
    # opening.  Multiple rapid init/terminate cycles confuse PortAudio's
    # PulseAudio backend: the first init returns stale ALSA virtual devices
    # with no audio signal, while real PulseAudio devices only appear once the
    # PA connection is fully established.  Reusing one instance avoids this.
    if verbose:
        audio = pyaudio.PyAudio()
    else:
        with suppress_stderr():
            audio = pyaudio.PyAudio()

    # Get list of all input devices, reusing the same PyAudio instance
    if verbose:
        all_input_devices = RecordingEngine.list_devices(audio=audio)
    else:
        with suppress_stderr():
            all_input_devices = RecordingEngine.list_devices(audio=audio)

    if not all_input_devices:
        audio.terminate()
        console.print("[error]✗ No input devices found[/error]")
        sys.exit(1)

    device_names = {}
    streams = {}
    available_devices = []

    def _try_open(did):
        """Open a test stream, suppressing C-level ALSA/PA stderr when not verbose."""
        if verbose:
            return audio.open(
                format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                input_device_index=did, frames_per_buffer=chunk_size, stream_callback=None,
            )
        with suppress_stderr():
            return audio.open(
                format=pyaudio.paInt16, channels=1, rate=rate, input=True,
                input_device_index=did, frames_per_buffer=chunk_size, stream_callback=None,
            )

    try:
        for dev in all_input_devices:
            did = dev['id']
            try:
                # Test if we can open stream for this device
                test_stream = _try_open(did)
                test_stream.close()
                device_names[did] = dev['name']
                available_devices.append(did)
            except Exception:
                # Device is unavailable, skip it silently
                pass

        if not available_devices:
            console.print("[error]✗ No available audio devices found[/error]")
            sys.exit(1)

        # --- output device monitoring via PulseAudio monitor sources ---
        # Each output sink exposes a "<sink>.monitor" source that parec can read.
        # We spawn one parec process per sink and read raw s16le PCM from its
        # stdout in a background thread, computing a rolling dB level.
        output_sinks: list = []         # [{name, monitor, description, state}]
        parec_procs: dict = {}          # sink_name -> subprocess.Popen
        output_levels: dict = {}        # sink_name -> float (0-120 dB scale)
        output_threads: list = []

        if include_output:
            output_sinks = RecordingEngine.list_output_devices()
            if output_sinks:
                console.print(f"[info]  Found {len(output_sinks)} output sink(s) to monitor via parec[/info]")
            else:
                console.print("[warning]  No PulseAudio sinks found (pactl unavailable?)[/warning]")

        parec_chunk = chunk_size * 2  # 16-bit = 2 bytes per sample

        def _read_parec(sink_name: str, proc, chunk_bytes: int):
            """Background thread: read raw PCM from parec stdout, update output_levels."""
            while True:
                try:
                    data = proc.stdout.read(chunk_bytes)
                    if not data:
                        break
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    rms = np.sqrt(np.mean(audio_array.astype(float) ** 2))
                    if rms > 0:
                        db = 20 * np.log10(rms / 32768)
                        db = max(0, min(120, db + 120))
                    else:
                        db = 0.0
                    output_levels[sink_name] = db
                except Exception:
                    break

        for sink in output_sinks:
            monitor_dev = sink["monitor"]
            output_levels[sink["name"]] = 0.0
            try:
                proc = subprocess.Popen(
                    [
                        "parec",
                        f"--device={monitor_dev}",
                        "--format=s16le",
                        f"--rate={rate}",
                        "--channels=1",
                        "--latency-msec=50",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                parec_procs[sink["name"]] = proc
                t = threading.Thread(
                    target=_read_parec,
                    args=(sink["name"], proc, parec_chunk),
                    daemon=True,
                )
                t.start()
                output_threads.append(t)
            except FileNotFoundError:
                console.print("[warning]  parec not found — install pulseaudio-utils to monitor outputs[/warning]")
                output_sinks = []
                break
            except Exception as exc:
                console.print(f"[warning]  Could not open monitor for {monitor_dev}: {exc}[/warning]")

        n_input = len(available_devices)
        n_output = len([s for s in output_sinks if s["name"] in parec_procs])
        console.print(f"\n[success]✓ Monitoring {n_input} input + {n_output} output device(s)[/success]")
        console.print("[info]Press Ctrl+C to stop monitoring[/info]\n")

        # Now open streams for available input devices
        for device_id in available_devices:
            try:
                streams[device_id] = _try_open(device_id)
            except Exception:
                # Skip if stream opening fails
                pass

        # Dictionary to store current dB levels
        device_levels = {device_id: 0.0 for device_id in available_devices}
        start_time = time.time()

        # Build one Progress task per device
        progress = make_monitor_progress()
        tasks = {}
        for did in sorted(available_devices):
            tasks[did] = progress.add_task(
                f"[cyan]🎤 [{did}][/cyan] {device_names[did]}",
                total=120,
                db_text="-- dB",
                status="",
            )
        # One task per output sink
        sink_tasks = {}
        for sink in output_sinks:
            if sink["name"] in parec_procs:
                label = sink["description"][:38] if len(sink["description"]) > 38 else sink["description"]
                sink_tasks[sink["name"]] = progress.add_task(
                    f"[magenta]🔊 OUT[/magenta] {label}",
                    total=120,
                    db_text="-- dB",
                    status="",
                )

        live_panel = Panel(
            progress,
            title="[bold cyan]📊 Audio Device Monitor[/bold cyan]",
            subtitle="[dim]Ctrl+C to stop | 🎤 input  🔊 output (monitor)[/dim]",
        )

        # Monitoring loop with Rich Live display
        with Live(live_panel, console=console, refresh_per_second=5, screen=False):
            while True:
                if duration and (time.time() - start_time) > duration:
                    break

                # Update levels from available input streams
                for device_id, stream in streams.items():
                    try:
                        if stream.is_active():
                            data = stream.read(chunk_size, exception_on_overflow=False)
                            audio_array = np.frombuffer(data, dtype=np.int16)
                            rms = np.sqrt(np.mean(audio_array.astype(float) ** 2))
                            if rms > 0:
                                db = 20 * np.log10(rms / 32768)
                                db = max(0, min(120, db + 120))
                            else:
                                db = 0
                            device_levels[device_id] = db
                    except Exception:
                        pass

                if device_levels:
                    max_device = max(device_levels, key=device_levels.get)
                    max_level = max(device_levels.values())
                else:
                    max_device = -1
                    max_level = 0

                for did in sorted(available_devices):
                    db_level = device_levels.get(did, 0.0)
                    status_str = "🎤 [bold green]ACTIVE[/bold green]" if did == max_device and max_level > 10 else ""
                    progress.update(tasks[did], completed=db_level, db_text=f"{db_level:.1f} dB", status=status_str)

                # Update output sink rows from parec threads
                for sink in output_sinks:
                    sname = sink["name"]
                    if sname in sink_tasks:
                        db_level = output_levels.get(sname, 0.0)
                        status_str = "🔊 [bold magenta]PLAYING[/bold magenta]" if db_level > 10 else ""
                        progress.update(sink_tasks[sname], completed=db_level, db_text=f"{db_level:.1f} dB", status=status_str)

                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n[warning]⏹ Monitoring stopped by user[/warning]")
    finally:
        # Terminate parec subprocesses
        for proc in parec_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass
        # Close all streams
        for stream in streams.values():
            try:
                stream.stop_stream()
                stream.close()
            except:
                pass
        audio.terminate()


@app.command()
def status(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output from audio libraries"
    ),
):
    """Show system, device and optional S3 storage information.

    If an S3 configuration is present in ``.pawnai-recorder.yml`` the command
    will attempt a lightweight health check on the configured bucket and
    report whether it is reachable.
    """
    # Configure loguru log level based on verbose flag
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="WARNING")

    console.rule("[bold]📋 PawnAI Recorder Status[/bold]")
    console.print()
    try:
        if verbose:
            devices = RecordingEngine.list_devices()
        else:
            with suppress_stderr():
                devices = RecordingEngine.list_devices()
        console.print(Panel(make_device_table(devices), title="[bold]Available Input Devices[/bold]"))
    except Exception as e:
        console.print(f"[error]✗ Error listing devices: {e}[/error]")

    # S3 storage status
    s3_conf = app_config.get_s3_config()
    if not s3_conf:
        console.print("[dim]S3 storage not configured[/dim]")
    else:
        try:
            uploader = S3Uploader.from_dict(s3_conf)
            available = uploader.check_bucket()
            if available:
                console.print(f"[info]S3 storage available: bucket {uploader.bucket}[/info]")
            else:
                console.print(f"[warning]S3 storage not reachable (bucket: {uploader.bucket})[/warning]")
        except Exception as e:  # include config errors
            console.print(f"[error]Failed to initialize S3 client: {e}[/error]")
