# Testing pawn_recorder_droid

The Android app is built with **Flet** + **flet-audio-recorder**.  
`flet build apk` replaces Buildozer — no Cython, no SDL, no JDK manual setup.

---

## 1. Desktop testing (no device needed)

Run the Flet app directly on Linux/macOS/Windows:

```bash
# Install Python deps
make install                # uv pip install -e ".[dev,android]"

# Launch the UI
make run
# or:
.venv/bin/flet run pawn_recorder_droid/main.py
```

`AudioRecorder` works on Linux if **fmedia** is installed:

```bash
# Arch Linux
yay -S fmedia                        # AUR

# Debian/Ubuntu
# fmedia binary: https://stsaz.github.io/fmedia/
```

All core logic (S3 upload, queue publish, JSONL logger) can be exercised on
the desktop — real microphone access included.

---

## 2. Unit tests

```bash
.venv/bin/pytest tests/ -v
```

`tests/test_droid.py` (to be created) can test the recording screen logic by
mocking `flet_audio_recorder.AudioRecorder`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio, flet as ft
from pawn_recorder_droid.screens.recorder_screen import build_recorder_view

def test_build_recorder_view_attaches_to_page():
    page = MagicMock(spec=ft.Page)
    page.services = []
    page.add = MagicMock()
    with patch("flet_audio_recorder.AudioRecorder"):
        build_recorder_view(page)
    assert page.add.called           # UI was added to page
    assert len(page.services) == 1   # AudioRecorder added as service
```

---

## 3. Prerequisites for APK build

### Python deps (already done by `make install`)

```bash
make install    # installs flet + flet-audio-recorder from pyproject.toml [android]
```

### Flutter SDK

`flet build apk` is a thin wrapper around `flutter build apk`.  
Flutter must be installed once on the build machine:

```bash
# Arch Linux
yay -S flutter                       # AUR  (or: sudo snap install flutter --classic)
flutter doctor                       # verify setup

# Debian/Ubuntu
sudo snap install flutter --classic
flutter doctor
```

`make install-flutter` prints the same instructions.

---

## 4. Build debug APK

```bash
make android-debug
# equivalent to:
cd pawn_recorder_droid && .venv/bin/flet build apk --verbose
```

The APK lands in `pawn_recorder_droid/build/apk/app-release.apk`.

### Required permissions

Flet reads `flet.toml` (or CLI flags) for Android manifest customisation.
Add a `flet.toml` to `pawn_recorder_droid/` if you need custom permissions:

```toml
[android]
permissions = [
    "android.permission.RECORD_AUDIO",
    "android.permission.INTERNET",
    "android.permission.WRITE_EXTERNAL_STORAGE",
]
```

`flet-audio-recorder` automatically requests `RECORD_AUDIO` at runtime via
`await recorder.has_permission()` (called at the start of every recording
session).

---

## 5. Deploy to a real device

```bash
make android-deploy         # build APK + adb install
make android-run            # build + install + launch
```

### Config file on device

Push `.pawn-recorder.yml` to the app's data directory:

```bash
adb push .pawn-recorder.yml \
    /sdcard/Android/data/com.pawnai.pawnrecorder/files/
```

---

## 6. Emulator (Android Studio AVD)

1. Create an AVD (API 31+) in Android Studio.
2. Start the emulator.
3. Run `make android-deploy` — adb detects the emulator automatically.

The emulator mic is routed from the host machine's default input device,
which is enough to verify the timed-chunk loop and S3 upload.

---

## 7. Checking logs

```bash
# Live logcat — Flutter + Python messages
make android-logcat
# or:
adb logcat -s flutter:V python:V
```

`RecordingLogger` writes to `recordings.jsonl` in the app's data directory:

```bash
adb shell cat \
    /sdcard/Android/data/com.pawnai.pawnrecorder/files/recordings.jsonl
```

---

## 8. Build release APK (optional)

```bash
KEYSTORE=/path/to/key.jks \
KEY_ALIAS=mykey \
KEY_PASS=secret \
  make android-release
