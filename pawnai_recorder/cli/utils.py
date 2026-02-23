"""CLI utilities for PawnAI Recorder.

This module provides common CLI utilities like Rich console output and
progress indicators.
"""

import os
import sys
from contextlib import contextmanager
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.theme import Theme

# Create themed console for consistent output
_theme = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "bold red",
        "debug": "dim white",
    }
)

console = Console(theme=_theme)


def make_device_table(devices: List[dict]) -> Table:
    """Build a Rich Table from the device list returned by RecordingEngine.list_devices().

    Args:
        devices: List of dicts with keys: id, name, driver, channels, rate, is_default

    Returns:
        Configured Rich Table ready to print.
    """
    table = Table(show_header=True, header_style="bold", show_lines=False, expand=False)
    table.add_column("ID", style="cyan", width=4, justify="right")
    table.add_column("Name", min_width=30)
    table.add_column("Driver", style="dim", width=8)
    table.add_column("Ch", justify="right", style="dim", width=4)
    table.add_column("Rate", justify="right", style="dim", width=12)
    table.add_column("", width=9)

    for d in devices:
        default_mark = "[bold green]DEFAULT[/bold green]" if d.get("is_default") else ""
        table.add_row(
            str(d["id"]),
            d["name"],
            d.get("driver", "").upper(),
            str(d.get("channels", "")),
            f"{d.get('rate', '')} Hz",
            default_mark,
        )
    return table


def make_level_progress() -> Progress:
    """Create a Rich Progress instance repurposed as a real-time dB level meter.

    Usage::

        with make_level_progress() as progress:
            task = progress.add_task("level", total=120, db_text="-- dB")
            while recording:
                progress.update(task, completed=db_level, db_text=f"{db_level:.1f} dB")
                time.sleep(0.1)

    Returns:
        Configured Rich Progress instance (0–120 dB scale).
    """
    return Progress(
        TextColumn("📈 Audio Level"),
        BarColumn(
            bar_width=50,
            complete_style="green",
            finished_style="green",
            pulse_style="yellow",
        ),
        TextColumn("[bold]{task.fields[db_text]}[/bold]"),
        console=console,
        transient=False,
        expand=False,
    )


def make_monitor_progress() -> Progress:
    """Create a Rich Progress instance for the multi-device monitor.

    Each audio device is added as a separate task using
    ``progress.add_task(description, total=120, db_text="-- dB", status="")``.
    Update each task with ``progress.update(task_id, completed=db_level,
    db_text=f"{db_level:.1f} dB", status=...)``.

    Returns:
        Configured Rich Progress instance (0–120 dB scale, one row per device).
    """
    return Progress(
        TextColumn("{task.description:<42}"),
        BarColumn(
            bar_width=50,
            complete_style="green",
            finished_style="green",
            pulse_style="yellow",
        ),
        TextColumn("[bold]{task.fields[db_text]}[/bold]"),
        TextColumn("{task.fields[status]}"),
        console=console,
        transient=False,
        expand=False,
    )


@contextmanager
def suppress_stderr():
    """Context manager to suppress stderr output from libraries like ALSA, JACK.

    Used to hide debug/warning messages from audio subsystems that pollute
    terminal output.
    """
    # Save original stderr file descriptor
    original_stderr_fd = os.dup(2)
    try:
        # Open /dev/null and redirect stderr to it
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, 2)
        yield
    finally:
        # Restore original stderr
        os.dup2(original_stderr_fd, 2)
        os.close(original_stderr_fd)


__all__ = ["console", "suppress_stderr", "make_device_table", "make_level_progress", "make_monitor_progress"]
