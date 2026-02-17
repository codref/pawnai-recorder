"""Utility tests for PawnAI Recorder."""

from pawnai_recorder.cli.utils import console


def test_console_available():
    """Test that console is available."""
    assert console is not None
    assert hasattr(console, 'print')
