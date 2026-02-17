"""Core functionality tests for PawnAI Recorder."""

import pytest
from pawnai_recorder.core import (
    calculate_db_level,
    apply_gain,
    detect_driver_type,
    AppConfig,
)


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
