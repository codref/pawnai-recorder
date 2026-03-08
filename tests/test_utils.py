"""Utility tests for PawnAI Recorder."""

from pawn_recorder_cli.utils import console


def test_console_available():
    """Test that console is available."""
    assert console is not None
    assert hasattr(console, 'print')
