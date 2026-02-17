"""CLI integration tests for PawnAI Recorder."""

import pytest
from typer.testing import CliRunner
from pawnai_recorder.cli import app

runner = CliRunner()


def test_list_devices_command():
    """Test list-devices command."""
    result = runner.invoke(app, ["list-devices"])
    assert result.exit_code == 0


def test_status_command():
    """Test status command."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0


def test_help_command():
    """Test help command."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Recording" in result.stdout or "recording" in result.stdout
