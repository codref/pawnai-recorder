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
from rich.markup import escape
from rich.prompt import IntPrompt

from pawnai_recorder.core.recording import RecordingEngine, first_openable_input
from pawnai_recorder.core.queue_producer import SessionQueueProducer
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


def _prompt_input_device(driver: Optional[str], verbose: bool) -> int:
    """Ask for an input device id. Exits the process when the choice is invalid."""
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
        raise SystemExit(1)

    title = "Available Input Devices"
    if driver:
        title += f" (filtered by: {driver})"
    console.print(Panel(make_device_table(devices), title=f"[bold]{title}[/bold]"))

    input_device_ids = [d["id"] for d in devices]
    try:
        import pyaudio

        if verbose:
            audio = pyaudio.PyAudio()
        else:
            with suppress_stderr():
                audio = pyaudio.PyAudio()
        try:
            default_device = audio.get_default_input_device_info()
            portaudio_default = int(default_device["index"]) if default_device else -1
        except OSError:
            portaudio_default = input_device_ids[0] if input_device_ids else 0
        if portaudio_default not in input_device_ids:
            portaudio_default = input_device_ids[0] if input_device_ids else 0
        audio.terminate()
        with suppress_stderr():
            default_device_id = first_openable_input(devices, portaudio_default)
        if default_device_id is None:
            console.print(
                "[error]✗ None of the listed input devices could be opened. "
                "Check that PipeWire or PulseAudio is running.[/error]"
            )
            raise SystemExit(1)
        if default_device_id != portaudio_default:
            suggested = next(d["name"] for d in devices if d["id"] == default_device_id)
            console.print(
                f"[dim]Device {portaudio_default} cannot be opened; "
                f"suggesting {default_device_id} ({escape(suggested)}).[/dim]"
            )
        chosen = IntPrompt.ask(
            "📍 Select device ID",
            console=console,
            default=default_device_id,
        )
        if chosen not in input_device_ids:
            console.print(f"[error]✗ Invalid device ID: {chosen}[/error]")
            raise SystemExit(1)
        return chosen
    except ValueError:
        console.print("[error]✗ Invalid input[/error]")
        raise SystemExit(1) from None


def _use_session_window(plain: bool) -> bool:
    """Open the Textual window on an interactive terminal when the package is installed."""
    if plain or not sys.stdout.isatty():
        return False
    try:
        import textual  # noqa: F401
    except ImportError:
        console.print(
            "[warning]textual is not installed; using the plain meter. "
            "pip install 'pawnai-recorder\\[ui\\]'[/warning]"
        )
        return False
    return True


def _run_plain(live, duration: Optional[int], quit_event: threading.Event) -> None:
    """Rich level meter. Ctrl+C, ``--duration``, or the tray Quit item ends the command."""
    try:
        info = live.start()
    except Exception as exc:
        console.print(f"[error]✗ Error during recording: {escape(str(exc))}[/error]")
        raise SystemExit(1) from exc

    duration_str = f"{duration}s" if duration else "continuous — Ctrl+C to stop"
    console.print(Panel(
        f"[dim]Session:[/dim]  {info.get('session_id')}\n"
        f"[dim]Device:[/dim]   {info.get('device_name')}\n"
        f"[dim]Diarize:[/dim]  {live.diarize_mode}\n"
        f"[dim]Duration:[/dim] {duration_str}",
        title="[bold]🎙 Recording Session[/bold]",
        border_style="green",
    ))
    started = time.time()
    try:
        with make_level_progress() as progress:
            task = progress.add_task("level", total=120, db_text="-- dB")
            while not quit_event.is_set():
                live.drain_audio_ops()
                if duration is not None and (time.time() - started) >= duration:
                    break
                db_level = live.db_level()
                progress.update(task, completed=db_level, db_text=f"{db_level:.1f} dB")
                time.sleep(0.1)
    except KeyboardInterrupt:
        console.print("\n[warning]⏹ Recording interrupted by user[/warning]")
    if live.is_recording:
        live.stop()
        console.print("[success]✓ Recording stopped[/success]")


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
    session: Optional[str] = typer.Option(
        None,
        help=(
            "Human-readable session label sent in all queue messages. "
            "Defaults to the auto-generated timestamp session ID when omitted."
        ),
    ),
    log_file: Optional[str] = typer.Option(
        None,
        help=(
            "Override the recording log filename (relative to --output directory). "
            "Defaults to the value from .pawnai-recorder.yml or 'recordings.jsonl'."
        ),
    ),
    diarize_mode: Optional[str] = typer.Option(
        None,
        "--diarize-mode",
        help=(
            "When to publish transcribe-diarize: per_chunk (after every chunk upload) "
            "or end_of_session (one message when the take stops). Overrides the YAML mode."
        ),
    ),
    plain: bool = typer.Option(
        False,
        "--plain",
        help="Use the Rich level meter instead of the session window.",
    ),
    tray: bool = typer.Option(
        True,
        "--tray/--no-tray",
        help="Show a Linux status-bar icon while this command is running.",
    ),
    screenshot_output: Optional[str] = typer.Option(
        None,
        "--screenshot-output",
        help=(
            "Enable screen capture of this monitor. Use a Wayland output name "
            "(for example DP-1) or a monitor index starting at 0."
        ),
    ),
    screenshot_every: Optional[float] = typer.Option(
        None,
        "--screenshot-every",
        help="Seconds between automatic screenshots. Omit for manual capture only.",
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
    # Initialise optional PawnQueue producer (shared by both recording paths)
    # ------------------------------------------------------------------
    _queue_producer: Optional[SessionQueueProducer] = None
    _queue_cfg = app_config.get_queue_config()
    if _queue_cfg and _queue_cfg.get('enabled', True) and _queue_cfg.get('topic'):
        _s3_cfg_for_queue = app_config.get_s3_config()
        if _s3_cfg_for_queue:
            try:
                _queue_producer = SessionQueueProducer(
                    s3_config=_s3_cfg_for_queue,
                    topic=str(_queue_cfg['topic']),
                )
                console.print(f"[dim]🔔 Queue producer ready: topic={_queue_cfg['topic']!r}[/dim]")
            except Exception as _qe:
                console.print(f"[warning]PawnQueue init failed: {_qe} — publishing disabled[/warning]")
        else:
            console.print('[dim]PawnQueue: no S3 config — publishing disabled[/dim]')

    # Job-level config for structured queue payloads (transcribe-diarize, analyze)
    _queue_job_config = app_config.get_queue_job_config()
    live = None
    tray_icon = None
    try:
        if diarize_mode is not None:
            from pawnai_recorder.core.jobs import resolve_diarize_mode, with_diarize_mode

            try:
                resolve_diarize_mode(_queue_job_config, diarize_mode)
            except ValueError as exc:
                console.print(f"[error]✗ {exc}[/error]")
                raise SystemExit(1) from exc
            _queue_job_config = with_diarize_mode(_queue_job_config, diarize_mode)

        if sink is None and device_id is None:
            device_id = _prompt_input_device(driver, verbose)

        from pawnai_recorder.core.session import RecordingSession

        live = RecordingSession(
            output_dir=output_dir,
            rate=rate,
            chunk_size=chunk_size,
            file_format=format,
            gain=gain,
            device_id=device_id,
            sink=sink,
            conversation_id=conversation_id,
            upload_enabled=upload,
            verbose=verbose,
            timestamp_format=timestamp_format,
            datetime_format=datetime_format,
            session_label=session,
            recording_logger=recording_logger,
            queue_producer=_queue_producer,
            queue_job_config=_queue_job_config,
            screenshot_output=screenshot_output,
            screenshot_every=screenshot_every,
        )

        quit_event = threading.Event()
        live.request_quit = quit_event.set

        import signal

        def _on_term(signum, frame):
            live.quit()

        signal.signal(signal.SIGTERM, _on_term)

        if tray:
            from pawnai_recorder.desktop.tray import start_tray

            tray_icon = start_tray(live)

        if _use_session_window(plain):
            from pawnai_recorder.cli.session_ui import run_session_ui

            run_session_ui(live, duration=float(duration) if duration else None)
        else:
            _run_plain(live, duration, quit_event)
    except KeyboardInterrupt:
        console.print("\n[warning]⏹ Recording interrupted by user[/warning]")
    finally:
        if tray_icon is not None:
            tray_icon.stop()
        if live is not None:
            live.close()
        elif _queue_producer is not None:
            _queue_producer.close()



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
