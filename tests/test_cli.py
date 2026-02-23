"""CLI integration tests for PawnAI Recorder."""

import pytest
from typer.testing import CliRunner
from pawnai_recorder.cli import app

runner = CliRunner()


def test_list_devices_command():
    """Test list-devices command."""
    result = runner.invoke(app, ["list-devices"])
    assert result.exit_code == 0


def test_status_command(tmp_path, monkeypatch):
    """Test status command without S3 configuration."""
    # run in temporary directory so that existing workspace config is ignored
    monkeypatch.chdir(tmp_path)
    # recreate app_config so it reads from the new cwd
    from pawnai_recorder.cli import commands
    commands.app_config = commands.AppConfig()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "S3 storage not configured" in result.stdout


def test_status_with_s3_available(tmp_path, monkeypatch):
    """Status should report available when uploader.check_bucket returns True."""
    # create minimal config file inside clean dir
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / ".pawnai-recorder.yml"
    config_file.write_text(
        """
        s3:
          bucket: my-bucket
          endpoint_url: https://s3.example.test
          access_key: a
          secret_key: b
        """,
        encoding="utf-8",
    )
    # refresh config after creating file
    from pawnai_recorder.cli import commands
    commands.app_config = commands.AppConfig()

    # patch S3Uploader.check_bucket
    from pawnai_recorder.core.s3_upload import S3Uploader

    monkeypatch.setattr(S3Uploader, "check_bucket", lambda self: True)
    monkeypatch.setattr(S3Uploader, "bucket", property(lambda self: "my-bucket"))

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "S3 storage available" in result.stdout
    assert "my-bucket" in result.stdout


def test_status_with_s3_unreachable(tmp_path, monkeypatch):
    """Status should warn when uploader.check_bucket returns False."""
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / ".pawnai-recorder.yml"
    config_file.write_text(
        """
        s3:
          bucket: other
          endpoint_url: https://s3.example.test
          access_key: a
          secret_key: b
        """,
        encoding="utf-8",
    )
    from pawnai_recorder.cli import commands
    commands.app_config = commands.AppConfig()

    from pawnai_recorder.core.s3_upload import S3Uploader

    monkeypatch.setattr(S3Uploader, "check_bucket", lambda self: False)
    monkeypatch.setattr(S3Uploader, "bucket", property(lambda self: "other"))

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "S3 storage not reachable" in result.stdout


def test_help_command():
    """Test help command."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Recording" in result.stdout or "recording" in result.stdout


def test_record_help_shows_conversation_id_option():
    """Test record command exposes conversation-id option."""
    result = runner.invoke(app, ["record", "--help"])
    assert result.exit_code == 0
    assert "--conversation-id" in result.stdout
    assert "--no-upload" in result.stdout
