"""CLI utilities for PawnAI Recorder.

This module provides common CLI utilities like Rich console output and
progress indicators.
"""

import os
import sys
from contextlib import contextmanager
from rich.console import Console
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


__all__ = ["console", "suppress_stderr"]
