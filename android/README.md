# PawnAI Recorder (Android)

Jetpack Compose client that records ambient/call audio, chunks it, uploads to S3-compatible storage, and publishes PawnQueue jobs for diarization — matching the Python CLI contract.

> Note: lives at `pawnai-recorder/android/` (workspace) because creating the planned sibling directory was blocked in this environment. Functionally identical; move/rename to `../pawnai-recorder-android` if desired.

## Features

- Record / stop with foreground service
- VU meter (0–120 dB RMS mapping)
- Timed chunking (default 120 s) + **Force upload chunk**
- Chunk status list (saving / uploading / uploaded / queued / failed)
- Audio formats: **FLAC** (default, libFLAC via NDK) or WAV
- Settings via DataStore (recording, S3, queue)
- Kotlin [pawn-queue](../../pawnai-sqs/kotlin) for `transcribe-diarize` / `analyze` / `sync-siyuan`

## Audio encoding (bundled native)

FLAC is encoded with **libFLAC 1.4.3**, statically linked into `libpawnai_flac.so` and packaged inside the APK (`lib/<abi>/`). No separate FFmpeg binary is required.

Build needs the Android NDK + CMake (AGP downloads libFLAC source on first native build):

```bash
sdkmanager "ndk;27.0.12077973" "cmake;3.22.1"
```

Point `ndk.dir` / `cmake.dir` in `local.properties` if they are not under `sdk.dir`.

## Build

```bash
cd android
./gradlew :template:assembleDebug
./gradlew :template:test
```

Requires Android SDK (`local.properties` → `sdk.dir=...`).

## Configure

Open **Settings** in the app and set S3 + queue fields (same as `.pawnai-recorder.yml`).
File format chips: `flac` (lossless, compressed) or `wav` (uncompressed PCM).
