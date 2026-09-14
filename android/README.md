# PawnAI Recorder (Android)

Jetpack Compose client that records ambient/call audio, chunks it, uploads to S3-compatible storage, and publishes PawnQueue jobs for diarization — matching the Python CLI contract.

> Note: lives at `pawnai-recorder/android/` (workspace) because creating the planned sibling directory was blocked in this environment. Functionally identical; move/rename to `../pawnai-recorder-android` if desired.

## Features

- Record / stop with foreground service
- VU meter (0–120 dB RMS mapping)
- Timed chunking (default 120 s) + **Force upload chunk**
- Chunk status list (saving / uploading / uploaded / queued / failed)
- Settings via DataStore (recording, S3, queue)
- Kotlin [pawn-queue](../../pawnai-sqs/kotlin) for `transcribe-diarize` / `analyze` / `sync-siyuan`

## Build

```bash
cd android
./gradlew :template:assembleDebug
./gradlew :template:test
```

Requires Android SDK (`local.properties` → `sdk.dir=...`).

## Configure

Open **Settings** in the app and set S3 + queue fields (same as `.pawnai-recorder.yml`).
