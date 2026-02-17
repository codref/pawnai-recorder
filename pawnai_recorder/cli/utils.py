"""CLI utilities for PawnAI Recorder.

This module provides common CLI utilities like Rich console output and
progress indicators.
"""

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

__all__ = ["console"]
