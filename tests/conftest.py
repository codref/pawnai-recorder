"""Shared test fixtures for PawnAI Recorder tests."""

import pytest
from pathlib import Path


@pytest.fixture
def temp_audio_dir(tmp_path):
    """Provide temporary audio directory for tests."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


@pytest.fixture
def sample_config():
    """Provide sample configuration for tests."""
    return {
        "rate": 16000,
        "chunk": 16000,
        "channel": 1,
        "chunk_size": 120,
        "file_extension": "flac",
    }
