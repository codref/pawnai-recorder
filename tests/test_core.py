"""Core functionality tests for PawnAI Recorder."""

import pytest
import yaml
from pawnai_recorder.core import (
    calculate_db_level,
    apply_gain,
    detect_driver_type,
    AppConfig,
    build_object_key,
)
from pawnai_recorder.core.s3_upload import S3Uploader


def test_calculate_db_level():
    """Test dB level calculation."""
    import numpy as np

    # Create a simple audio signal
    audio_array = np.zeros(16000, dtype=np.int16)
    audio_data = audio_array.tobytes()

    db_level = calculate_db_level(audio_data)
    assert 0 <= db_level <= 120


def test_apply_gain():
    """Test audio gain application."""
    import numpy as np

    # Create a simple audio signal
    audio_array = np.ones(16000, dtype=np.int16) * 1000
    audio_data = audio_array.tobytes()

    # Apply no gain
    result = apply_gain(audio_data, 1.0)
    assert result == audio_data

    # Apply gain
    result = apply_gain(audio_data, 2.0)
    assert len(result) == len(audio_data)


def test_detect_driver_type():
    """Test audio driver type detection."""
    assert detect_driver_type("PulseAudio") == "pulse"
    assert detect_driver_type("ALSA") == "alsa"
    assert detect_driver_type("JACK") == "jack"
    assert detect_driver_type("USB Device") == "usb"
    assert detect_driver_type("Unknown") == "default"


def test_app_config():
    """Test application configuration."""
    config = AppConfig()

    # Test get with default
    assert config.get("rate", 16000) == 16000

    # Test set and get
    config.set("rate", 44100)
    assert config.get("rate") == 44100

    # Test output directory
    output_dir = config.get_output_dir()
    assert output_dir.exists()


def test_app_config_loads_yaml(tmp_path, monkeypatch):
    """Test YAML config loading from project root."""
    config_file = tmp_path / ".pawnai-recorder.yml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "recording": {
                    "rate": 22050,
                    "chunk_size": 240,
                    "output_dir": "custom-audio/",
                    "file_extension": "wav",
                },
                "s3": {
                    "bucket": "test-bucket",
                    "endpoint_url": "https://s3.example.test",
                    "access_key": "abc",
                    "secret_key": "def",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = AppConfig()
    s3_config = config.get_s3_config()

    assert s3_config is not None
    assert s3_config["bucket"] == "test-bucket"
    assert config.get("rate") == 22050
    assert config.get("chunk_size") == 240
    assert config.get("output_dir") == "custom-audio/"
    assert config.get("file_extension") == "wav"


def test_build_object_key_without_conversation_id():
    """Test default key layout timestamp/filename."""
    key = build_object_key(
        filename="audio/240221101500_01.flac",
        session_id="240221101500",
    )
    assert key == "240221101500/240221101500_01.flac"


def test_build_object_key_with_conversation_id_and_prefix():
    """Test key layout conversation_id/timestamp/filename with prefix."""
    key = build_object_key(
        filename="audio/240221101500_02.flac",
        session_id="240221101500",
        conversation_id="conversation-42",
        prefix="conversations",
    )
    assert key == "conversations/conversation-42/240221101500/240221101500_02.flac"


# ---------------------------------------------------------------------------
# RecordingLogger tests
# ---------------------------------------------------------------------------

def test_log_creates_file(tmp_path):
    """RecordingLogger creates the log file on first write."""
    from pawnai_recorder.core.log import RecordingLogger

    log_path = tmp_path / "subdir" / "recordings.jsonl"
    logger = RecordingLogger(log_path)
    logger.write_session_start(
        session_id="s1",
        conversation_id=None,
        device_id=0,
        device_name="Test Device",
        sample_rate=16000,
        channels=1,
        format="flac",
    )
    assert log_path.exists()


def test_log_session_roundtrip(tmp_path):
    """session-start and session-end records contain all expected fields."""
    import json
    from pawnai_recorder.core.log import RecordingLogger

    log_path = tmp_path / "recordings.jsonl"
    rl = RecordingLogger(log_path)
    rl.write_session_start(
        session_id="260223143022",
        conversation_id="mtg-01",
        device_id=3,
        device_name="USB Mic",
        sample_rate=16000,
        channels=1,
        format="flac",
    )
    rl.write_session_end(
        session_id="260223143022",
        total_duration_sec=120.0,
        chunk_count=1,
    )

    lines = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2

    start = lines[0]
    assert start["type"] == "session"
    assert start["event"] == "start"
    assert start["session_id"] == "260223143022"
    assert start["conversation_id"] == "mtg-01"
    assert start["device_id"] == 3
    assert start["device_name"] == "USB Mic"
    assert start["sample_rate"] == 16000
    assert start["channels"] == 1
    assert start["format"] == "flac"
    assert "started_at" in start

    end = lines[1]
    assert end["type"] == "session"
    assert end["event"] == "end"
    assert end["session_id"] == "260223143022"
    assert end["total_duration_sec"] == 120.0
    assert end["chunk_count"] == 1
    assert "ended_at" in end


def test_log_chunk_entry(tmp_path):
    """Chunk records capture file path, duration, and S3 upload status."""
    import json
    from pawnai_recorder.core.log import RecordingLogger

    log_path = tmp_path / "recordings.jsonl"
    rl = RecordingLogger(log_path)
    rl.write_chunk(
        session_id="s1",
        chunk_index=1,
        file_path="audio/s1_01.flac",
        started_at=None,
        duration_sec=120.0,
        s3_object_key=None,
        s3_uploaded=False,
    )

    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["type"] == "chunk"
    assert record["session_id"] == "s1"
    assert record["chunk_index"] == 1
    assert record["file_path"] == "audio/s1_01.flac"
    assert record["duration_sec"] == 120.0
    assert record["s3_object_key"] is None
    assert record["s3_uploaded"] is False
    assert "started_at" in record


def test_log_chunk_with_s3(tmp_path):
    """Chunk records reflect successful S3 upload."""
    import json
    from pawnai_recorder.core.log import RecordingLogger

    log_path = tmp_path / "recordings.jsonl"
    rl = RecordingLogger(log_path)
    rl.write_chunk(
        session_id="s1",
        chunk_index=2,
        file_path="audio/s1_02.flac",
        started_at=None,
        duration_sec=60.5,
        s3_object_key="conversations/mtg-01/s1/s1_02.flac",
        s3_uploaded=True,
    )

    record = json.loads(log_path.read_text().splitlines()[0])
    assert record["s3_uploaded"] is True
    assert record["s3_object_key"] == "conversations/mtg-01/s1/s1_02.flac"
    assert record["duration_sec"] == 60.5


def test_log_get_log_path_default(tmp_path, monkeypatch):
    """AppConfig.get_log_path() defaults to output_dir/recordings.jsonl."""
    from pawnai_recorder.core.config import AppConfig, LOG_FILE

    monkeypatch.chdir(tmp_path)
    config = AppConfig()
    log_path = config.get_log_path(tmp_path / "audio")
    assert log_path.name == LOG_FILE
    assert log_path.parent == tmp_path / "audio"


def test_log_get_log_path_from_yaml(tmp_path, monkeypatch):
    """AppConfig.get_log_path() respects the log.file YAML key."""
    import yaml
    from pawnai_recorder.core.config import AppConfig

    config_file = tmp_path / ".pawnai-recorder.yml"
    config_file.write_text(
        yaml.safe_dump({"log": {"file": "my_log.jsonl"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = AppConfig()
    log_path = config.get_log_path(tmp_path / "audio")
    assert log_path.name == "my_log.jsonl"


def test_s3_uploader_check_bucket(monkeypatch):
    """Check bucket method returns True when head_bucket succeeds and False on failure."""
    calls = {}

    class DummyClient:
        def __init__(self, succeed: bool):
            self._succeed = succeed

        def head_bucket(self, Bucket):
            calls['bucket'] = Bucket
            if not self._succeed:
                # simulate botocore exception
                import botocore

                raise botocore.exceptions.ClientError(
                    {'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadBucket'
                )
            return {}

    # construct config dict for uploader
    cfg = {
        'bucket': 'test-bucket',
        'endpoint_url': 'https://s3.example.test',
        'access_key': 'abc',
        'secret_key': 'def',
    }

    uploader = S3Uploader.from_dict(cfg)

    # monkeypatch the internal client
    uploader._client = DummyClient(succeed=True)
    assert uploader.check_bucket() is True
    assert calls['bucket'] == 'test-bucket'

    uploader._client = DummyClient(succeed=False)
    assert uploader.check_bucket() is False
