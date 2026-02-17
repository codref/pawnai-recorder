"""Audio processing utilities for PawnAI Recorder.

This module provides audio processing functions including level calculation,
gain adjustment, and driver detection.
"""

from typing import Optional

import numpy as np
from loguru import logger


def calculate_db_level(audio_data: bytes, sample_width: int = 2) -> float:
    """Calculate dB level from audio data.

    Args:
        audio_data: Raw audio bytes
        sample_width: Number of bytes per sample (2 for int16)

    Returns:
        dB level (0-120 range)
    """
    try:
        # Convert bytes to numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16)

        # Calculate RMS (Root Mean Square)
        rms = np.sqrt(np.mean(audio_array.astype(float) ** 2))

        # Convert to dB (reference is max int16 value)
        max_int16 = 32768
        if rms > 0:
            db = 20 * np.log10(rms / max_int16)
            # Normalize to 0-120 range
            db = max(0, min(120, db + 120))
        else:
            db = 0

        return db
    except Exception as e:
        logger.debug(f"Error calculating dB level: {e}")
        return 0


def draw_db_bar(db_level: float, width: int = 50) -> str:
    """Create a visual bar representation of dB level.

    Args:
        db_level: dB level (0-120)
        width: Width of the bar in characters

    Returns:
        A string representation of the dB bar
    """
    filled = int((db_level / 120) * width)
    bar = '█' * filled + '░' * (width - filled)
    return f"[{bar}] {db_level:.1f} dB"


def apply_gain(audio_data: bytes, gain_factor: float = 1.0) -> bytes:
    """Apply gain/amplification to audio data.

    Args:
        audio_data: Raw audio bytes (int16)
        gain_factor: Gain multiplier (1.0 = no change, 2.0 = +6dB, 0.5 = -6dB)

    Returns:
        Amplified audio data as bytes
    """
    if gain_factor == 1.0:
        return audio_data

    try:
        # Convert bytes to numpy array (int16)
        audio_array = np.frombuffer(audio_data, dtype=np.int16).copy()

        # Apply gain
        audio_array = (audio_array.astype(np.float32) * gain_factor).astype(np.int16)

        # Clip to prevent distortion
        max_int16 = 32767
        audio_array = np.clip(audio_array, -max_int16, max_int16)

        return audio_array.tobytes()
    except Exception as e:
        logger.debug(f"Error applying gain: {e}")
        return audio_data


def detect_driver_type(device_name: str) -> str:
    """Detect the audio driver type from device name.

    Args:
        device_name: The name of the audio device

    Returns:
        Driver type: 'pulse', 'alsa', 'jack', 'default', etc.
    """
    name_lower = device_name.lower()

    if 'pulse' in name_lower or 'pipewire' in name_lower:
        return 'pulse'
    elif 'alsa' in name_lower or 'hw:' in name_lower or 'plughw' in name_lower:
        return 'alsa'
    elif 'jack' in name_lower:
        return 'jack'
    elif 'usb' in name_lower:
        return 'usb'
    else:
        return 'default'
