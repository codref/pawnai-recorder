"""
aaudio_source.py — ctypes wrapper around libpawn_recorder_native.so (AAudio NDK).

On Android the .so lives at :
    /data/app/<pkg>/lib/arm64/libpawn_recorder_native.so

On non-Android environments (desktop dev / CI) a no-op stub is returned so the
rest of the code can be imported without an Android device.
"""

from __future__ import annotations

import ctypes
import os
import platform
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger


# ─── locate native library ────────────────────────────────────────────────────

def _find_so() -> Optional[Path]:
    """Return path to libpawn_recorder_native.so, or None on non-Android."""
    # Android: placed next to .dex by the package installer
    candidates = [
        Path("/data/app")  / "libpawn_recorder_native.so",   # rough fallback
    ]
    # More reliable: look relative to this file (the .so is extracted to lib/)
    here = Path(__file__).resolve().parent
    for up in range(6):
        candidate = here.joinpath(*[".."] * up) / "lib" / "libpawn_recorder_native.so"
        candidates.append(candidate.resolve())

    for c in candidates:
        if c.exists():
            return c

    return None


# ─── ctypes bindings ─────────────────────────────────────────────────────────

class _NativeLib:
    """Thin ctypes wrapper — all methods raise RuntimeError on desktop."""

    def __init__(self) -> None:
        path = _find_so()
        if path is None:
            logger.warning(
                "libpawn_recorder_native.so not found — using silent stub "
                "(expected on desktop / CI; will produce zeros instead of audio)"
            )
            self._lib = None
            return

        logger.info(f"Loading native recorder from {path}")
        lib = ctypes.CDLL(str(path))

        lib.recorder_open.restype  = ctypes.c_int
        lib.recorder_open.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]

        lib.recorder_start.restype  = ctypes.c_int
        lib.recorder_start.argtypes = []

        lib.recorder_read.restype  = ctypes.c_int
        lib.recorder_read.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_int32]

        lib.recorder_stop.restype  = None
        lib.recorder_stop.argtypes = []

        lib.recorder_close.restype  = None
        lib.recorder_close.argtypes = []

        self._lib = lib

    # ── public API consistent with RecordingEngine interface ─────────────────

    def open(self, sample_rate: int = 16000, channels: int = 1,
             frames_per_burst: int = 256) -> int:
        if self._lib is None:
            return 0
        return self._lib.recorder_open(sample_rate, channels, frames_per_burst)

    def start(self) -> int:
        if self._lib is None:
            return 0
        return self._lib.recorder_start()

    def read(self, num_frames: int) -> np.ndarray:
        """Read num_frames PCM int16 samples. Returns zeros on stub/error."""
        if self._lib is None:
            return np.zeros(num_frames, dtype=np.int16)
        buf = (ctypes.c_int16 * num_frames)()
        n = self._lib.recorder_read(buf, num_frames)
        if n <= 0:
            return np.zeros(num_frames, dtype=np.int16)
        return np.frombuffer(buf, dtype=np.int16)[:n].copy()

    def stop(self) -> None:
        if self._lib:
            self._lib.recorder_stop()

    def close(self) -> None:
        if self._lib:
            self._lib.recorder_close()


# module-level singleton — callers do:  from pawn_recorder_droid.audio.aaudio_source import native_recorder
native_recorder = _NativeLib()
