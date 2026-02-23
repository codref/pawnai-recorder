# PawnAI Recorder

A Python audio recording and management CLI with real-time dB level metering.

## Features

- Real-time audio level monitoring with visual dB meter
- Support for multiple audio devices and drivers (PulseAudio, ALSA, JACK, USB)
- Configurable audio gain/amplification
- Automatic audio segmentation into chunks
- Input gain control
- Interactive device selection
- **Local JSONL recording log** – per-session and per-chunk metadata (device, duration, S3 status) persisted alongside audio files

## Installation

### From source

```bash
pip install -e .
```

After installation, you can run the `pawnai-recorder` command from anywhere:

```bash
pawnai-recorder --help
```

### Development installation

For development with optional tools (testing, linting, type checking):

```bash
pip install -e ".[dev]"
```

## Usage

### List available audio devices

```bash
pawnai-recorder list-devices
```

Filter by driver type:

```bash
pawnai-recorder list-devices --driver pulse
```

Show debug output from audio libraries (ALSA, JACK warnings):

```bash
pawnai-recorder list-devices --verbose
```

The `status` command prints system and device information. When an S3
configuration is present it also verifies that the configured bucket is
reachable and reports the result.

```bash
pawnai-recorder status
```

Show debug output from audio libraries (ALSA, JACK warnings):

```bash
pawnai-recorder status --verbose
```

Filter by driver type:

```bash
pawnai-recorder list-devices --driver pulse
```

### Record audio

Start recording with interactive device selection:

```bash
pawnai-recorder record
```

Show debug output (useful for troubleshooting audio issues):

```bash
pawnai-recorder record --verbose
```

Record for a specific duration (in seconds):

```bash
pawnai-recorder record --duration 60
```

Specify device ID directly:

```bash
pawnai-recorder record --device-id 0
```

Apply input gain:

```bash
pawnai-recorder record --gain 2.0  # 2x amplification (+6dB)
```

Specify custom output directory:

```bash
pawnai-recorder record --output ./my-recordings/
```

### Timestamp / filename formatting

Every session and chunk filename is derived from a configurable timestamp template.
Two options control the output:

| Option | Default | Description |
|---|---|---|
| `--timestamp-format` | `{ts}` | Format string; supports `{ts}` and `{device_id}` placeholders |
| `--datetime-format` | `%y%m%d%H%M%S` | strftime pattern applied to `{ts}` |

**Placeholders**

| Placeholder | Example value | Notes |
|---|---|---|
| `{ts}` | `231015143022` | Shaped by `--datetime-format` |
| `{device_id}` | `3` | Numeric device ID; `default` when not set |

**Examples**

Embed the device ID in every filename:

```bash
pawnai-recorder record --timestamp-format '{ts}_dev{device_id}'
# → audio/231015143022_dev3_01.flac
```

Human-readable date with device tag:

```bash
pawnai-recorder record \
  --datetime-format '%Y-%m-%dT%H%M%S' \
  --timestamp-format '{ts}_dev{device_id}'
# → audio/2023-10-15T143022_dev3_01.flac
```

Date-only prefix (group by day):

```bash
pawnai-recorder record \
  --datetime-format '%Y%m%d' \
  --timestamp-format '{ts}_{device_id}'
# → audio/20231015_3_01.flac
```

Both options can also be set permanently in `.pawnai-recorder.yml`
(see [Configuration](#configuration) below).

### Combined example

```bash
pawnai-recorder record --device-id 0 --duration 30 --output ./recordings/ --gain 1.5
```

### S3-compatible upload organization

> The status command now checks for S3 availability when configuration is
> provided and will surface an error or warning if the bucket cannot be
> contacted.


Saved files are uploaded automatically when `s3` is configured in `.pawnai-recorder.yml`.
Use `--no-upload` to bypass upload for a specific recording run.

Default key layout:

- Without conversation ID: `timestamp/filename`
- With conversation ID: `conversation_id/timestamp/filename`

Example with conversation ID:

```bash
pawnai-recorder record --device-id 0 --duration 60 --conversation-id conv-123
```

Bypass upload for one run:

```bash
pawnai-recorder record --duration 60 --no-upload
```

Copy the example config and edit credentials:

```bash
cp .pawnai-recorder.yml.example .pawnai-recorder.yml
```

Then configure `.pawnai-recorder.yml` in project root:

```yaml
recording:
  rate: 16000
  chunk: 16000
  channel: 1
  chunk_size: 120
  file_extension: "flac"
  output_dir: "audio/"
  sample_width: 2
  # Timestamp / filename formatting
  # Placeholders: {ts} (datetime string), {device_id} (numeric device ID)
  timestamp_format: "{ts}"            # e.g. "{ts}_dev{device_id}" to embed device
  datetime_format: "%y%m%d%H%M%S"    # strftime pattern for {ts}

s3:
  bucket: "your-bucket-name"
  endpoint_url: "https://your-s3-compatible-endpoint"
  access_key: "your-access-key"
  secret_key: "your-secret-key"
  region: "us-east-1"      # optional
  prefix: "conversations"  # optional
  verify_ssl: true          # optional
  path_style: true          # optional

log:
  file: "recordings.jsonl"  # filename relative to output_dir (optional)
```

If upload fails, recording continues and local files are kept.

### Local recording log

Every `record` run appends structured entries to a [JSON Lines](https://jsonlines.org/)
file (`recordings.jsonl`) inside the output directory. Three record types are
written per session:

| `type` | `event` | When written | Key fields |
|--------|---------|--------------|------------|
| `session` | `start` | Immediately after the stream opens | `session_id`, `conversation_id`, `device_id`, `device_name`, `sample_rate`, `channels`, `format`, `started_at` |
| `chunk` | — | After each chunk file is saved | `chunk_index`, `file_path`, `duration_sec`, `s3_object_key`, `s3_uploaded`, `started_at` |
| `session` | `end` | After all chunks have been saved | `total_duration_sec`, `chunk_count`, `ended_at` |

**Example entries**

```json
{"type":"session","event":"start","session_id":"260223143022","conversation_id":"mtg-01","device_id":3,"device_name":"USB PnP Audio Device","sample_rate":16000,"channels":1,"format":"flac","started_at":"2026-02-23T14:30:22"}
{"type":"chunk","session_id":"260223143022","chunk_index":1,"file_path":"audio/260223143022_01.flac","started_at":"2026-02-23T14:30:22","duration_sec":600.0,"s3_object_key":"conversations/mtg-01/260223143022/260223143022_01.flac","s3_uploaded":true}
{"type":"session","event":"end","session_id":"260223143022","ended_at":"2026-02-23T14:40:22","total_duration_sec":600.0,"chunk_count":1}
```

The log file is created automatically; no configuration is required.

**Override the log filename for a single run:**

```bash
pawnai-recorder record --log-file custom_log.jsonl
```

**Inspect the log with standard tools:**

```bash
# Pretty-print all entries
python -c "import json,sys; [print(json.dumps(json.loads(l), indent=2)) for l in open('audio/recordings.jsonl')]"

# List only session-start records (one per run)
grep '"event":"start"' audio/recordings.jsonl | python -m json.tool

# Show all chunks that failed S3 upload
grep '"type":"chunk"' audio/recordings.jsonl | python -c "
import json,sys
for line in sys.stdin:
    r = json.loads(line)
    if not r.get('s3_uploaded'):
        print(r['file_path'], r['started_at'])
"
```

**Configure the log filename permanently** in `.pawnai-recorder.yml`
(see [Configuration](#configuration)).


## Running as a module

You can also run the application as a Python module:

```bash
python -m pawnai_recorder record
```

## Project Structure

```text
pawnai-recorder/
├── pawnai_recorder/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli/
│   │   ├── commands.py
│   │   └── utils.py
│   ├── core/
│   │   ├── config.py
│   │   ├── log.py            # JSONL recording log
│   │   ├── recording.py
│   │   ├── s3_upload.py
│   │   ├── storage.py
│   │   └── processing.py
│   └── utils/
├── audio/                    # Default output directory for recordings
│   └── recordings.jsonl      # Auto-created recording log
├── docs/
├── tests/
├── pyproject.toml
├── setup.py
├── requirements.txt
└── README.md                 # This file
```

## Configuration

All project metadata and dependencies are configured in `pyproject.toml` using the modern Python packaging standard (PEP 621). The `setup.py` file is minimal and only needed for backward compatibility.

### Development tools configuration

The `pyproject.toml` includes configurations for:

- **black**: Code formatting
- **ruff**: Fast Python linter
- **mypy**: Static type checking
- **pytest**: Testing framework with coverage reporting

## Requirements

- Python 3.8+
- PyAudio 0.2.14+
- Loguru 0.7.2+
- Typer 0.16.1+
- Blessed 1.20.0+
- NumPy 1.26.0+

## Development Dependencies (optional)

- pytest 7.0+
- black 23.0+
- ruff 0.1.0+
- mypy 1.0+

## License

MIT
