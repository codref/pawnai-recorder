"""CLI commands for PawnAI Recorder.

This module provides all command-line interface commands using Typer.
"""

import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import typer
from blessed import Terminal
from loguru import logger

from pawnai_recorder.core import (
    MicrophoneStream,
    RecordingEngine,
    draw_db_bar,
)
from pawnai_recorder.core.s3_upload import S3Uploader
from pawnai_recorder.core.config import (
    AppConfig, RATE, RECORDING_CHUNK_SIZE, FILE_EXTENSION, CHUNK_DIR,
    TIMESTAMP_FORMAT, DATETIME_FORMAT,
)
from pawnai_recorder.core.log import RecordingLogger
from pawnai_recorder.cli.utils import console, suppress_stderr

app = typer.Typer(help="Professional audio recording and management CLI")

app_config = AppConfig()
default_output_dir = str(app_config.get("output_dir", CHUNK_DIR))
default_rate = int(app_config.get("rate", RATE))
default_chunk_size = int(app_config.get("chunk_size", RECORDING_CHUNK_SIZE))
default_file_extension = str(app_config.get("file_extension", FILE_EXTENSION))
default_timestamp_format = str(app_config.get("timestamp_format", TIMESTAMP_FORMAT))
default_datetime_format = str(app_config.get("datetime_format", DATETIME_FORMAT))

# Terminal UI
term = Terminal()


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
        RecordingEngine.list_devices(driver_filter=driver)
    else:
        with suppress_stderr():
            RecordingEngine.list_devices(driver_filter=driver)


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

    # List devices and get user selection if not specified
    if device_id is None:
        if verbose:
            input_devices = RecordingEngine.list_devices(driver_filter=driver)
        else:
            with suppress_stderr():
                input_devices = RecordingEngine.list_devices(driver_filter=driver)
        if not input_devices:
            console.print(
                f"[error]✗ No input devices found"
                + (f" for driver: {driver}" if driver else "")
                + "[/error]"
            )
            sys.exit(1)
        try:
            import pyaudio

            if verbose:
                audio = pyaudio.PyAudio()
            else:
                with suppress_stderr():
                    audio = pyaudio.PyAudio()
            default_device = audio.get_default_input_device_info()
            # Try to find default device in filtered list
            default_device_id = int(default_device['index']) if default_device else -1
            if default_device_id not in input_devices:
                default_device_id = input_devices[0] if input_devices else 0
            audio.terminate()
            device_id = int(
                input("📍 Select device ID (or press Enter for default): ") or default_device_id
            )
            if device_id not in input_devices:
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
            stream.start_recording()
        else:
            with suppress_stderr():
                stream.start_recording()

        if upload:
            console.print("[info]☁️ Upload mode: enabled (use --no-upload to bypass)[/info]")
        else:
            console.print("[warning]☁️ Upload mode: bypassed for this run[/warning]")

        if gain != 1.0:
            db_gain = 20 * np.log10(gain) if gain > 0 else 0
            console.print(f"[info]📊 Input gain: {gain:.2f}x ({db_gain:+.1f} dB)[/info]")

        console.print(f"[info]🎵 Audio format: {format.upper()}[/info]")

        if duration:
            console.print(f"[info]⏱ Recording for {duration} seconds...[/info]")
            start_time = time.time()
            while time.time() - start_time < duration:
                db_level = stream.get_current_db_level()
                bar = draw_db_bar(db_level, width=50)
                sys.stdout.write(f"\r📈 Audio Level: {bar}")
                sys.stdout.flush()
                time.sleep(0.1)
            print()  # New line after progress
            stream.stop_recording()
            # Wait for background threads to finish saving
            time.sleep(1.5)
            console.print("[success]✓ Recording completed[/success]")
        else:
            console.print("[success]✓ Recording continuously... Press Ctrl+C to stop[/success]")
            print(term.bold_underline("\n📊 Real-time dB Level Meter (Press Ctrl+C to stop)\n"))
            while True:
                db_level = stream.get_current_db_level()
                bar = draw_db_bar(db_level, width=50)
                sys.stdout.write(f"\r📈 Audio Level: {bar}")
                sys.stdout.flush()
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
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show debug output from audio libraries"
    ),
):
    """Monitor all audio devices in real-time to identify which has audio.
    
    Shows live audio levels for all connected input devices.
    Press Ctrl+C to stop monitoring.
    """
    # Configure loguru log level based on verbose flag
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="WARNING")

    import pyaudio
    
    # Get list of all input devices
    if verbose:
        all_input_devices = RecordingEngine.list_devices()
    else:
        with suppress_stderr():
            all_input_devices = RecordingEngine.list_devices()
    if not all_input_devices:
        console.print("[error]✗ No input devices found[/error]")
        sys.exit(1)
    
    # Test each device and filter out unavailable ones
    if verbose:
        audio = pyaudio.PyAudio()
    else:
        with suppress_stderr():
            audio = pyaudio.PyAudio()
    device_names = {}
    streams = {}
    available_devices = []
    
    try:
        for device_id in all_input_devices:
            try:
                device_info = audio.get_device_info_by_index(device_id)
                device_names[device_id] = device_info.get('name', f'Device {device_id}')
                
                # Test if we can open stream for this device
                test_stream = audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    input=True,
                    input_device_index=device_id,
                    frames_per_buffer=chunk_size,
                    stream_callback=None,
                )
                test_stream.close()
                available_devices.append(device_id)
            except Exception:
                # Device is unavailable, skip it silently
                pass
        
        if not available_devices:
            console.print("[error]✗ No available audio devices found[/error]")
            sys.exit(1)
        
        console.print(f"\n[success]✓ Monitoring {len(available_devices)} device(s)[/success]")
        console.print("[info]Press Ctrl+C to stop monitoring[/info]\n")
        
        # Now open streams for available devices
        for device_id in available_devices:
            try:
                stream = audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=rate,
                    input=True,
                    input_device_index=device_id,
                    frames_per_buffer=chunk_size,
                    stream_callback=None,
                )
                streams[device_id] = stream
            except Exception:
                # Skip if stream opening fails
                pass
        
        # Dictionary to store current dB levels
        device_levels = {device_id: 0.0 for device_id in available_devices}
        start_time = time.time()
        
        # Monitoring loop
        while True:
            # Check duration
            if duration and (time.time() - start_time) > duration:
                break
            
            # Update levels from available streams
            for device_id, stream in streams.items():
                try:
                    if stream.is_active():
                        data = stream.read(chunk_size, exception_on_overflow=False)
                        import numpy as np
                        audio_array = np.frombuffer(data, dtype=np.int16)
                        rms = np.sqrt(np.mean(audio_array.astype(float) ** 2))
                        max_int16 = 32768
                        if rms > 0:
                            db = 20 * np.log10(rms / max_int16)
                            db = max(0, min(120, db + 120))
                        else:
                            db = 0
                        device_levels[device_id] = db
                except Exception:
                    # Silently skip read errors
                    pass
            
            # Display levels for all devices
            print("\033[H\033[J", end="", flush=True)  # Clear screen
            console.print("[bold cyan]📊 Audio Device Monitor[/bold cyan]")
            console.print("-" * 80)
            
            # Find device with highest activity
            max_device = max(device_levels, key=device_levels.get)
            max_level = max(device_levels.values())
            
            for device_id in sorted(available_devices):
                db_level = device_levels[device_id]
                bar = draw_db_bar(db_level, width=40)
                is_active = " 🎤 [bold green]ACTIVE[/bold green]" if device_id == max_device and max_level > 10 else ""
                console.print(f"[{device_id}] {device_names[device_id]:<35} {bar}{is_active}")
            
            console.print("-" * 80)
            console.print("[dim]Ctrl+C to stop | Highest activity device marked ACTIVE[/dim]")
            time.sleep(interval)
    
    except KeyboardInterrupt:
        console.print("\n[warning]⏹ Monitoring stopped by user[/warning]")
    finally:
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

    console.print("[bold]📋 PawnAI Recorder Status[/bold]")
    console.print()
    console.print("[info]Available Input Devices:[/info]")
    try:
        if verbose:
            RecordingEngine.list_devices()
        else:
            with suppress_stderr():
                RecordingEngine.list_devices()
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
