# PawnAI Recorder

A Python audio recording and management CLI with real-time dB level metering.

## Features

- Real-time audio level monitoring with visual dB meter
- Support for multiple audio devices and drivers (PulseAudio, ALSA, JACK, USB)
- Configurable audio gain/amplification
- Automatic audio segmentation into chunks
- Input gain control
- Interactive device selection

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

### Record audio

Start recording with interactive device selection:

```bash
pawnai-recorder record
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

### Combined example

```bash
pawnai-recorder record --device-id 0 --duration 30 --output ./recordings/ --gain 1.5
```

## Running as a module

You can also run the application as a Python module:

```bash
python -m pawnai_recorder record
```

## Project Structure

```
pawnai-recorder/
├── pawnai_recorder/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli/
│   │   ├── commands.py
│   │   └── utils.py
│   ├── core/
│   │   ├── config.py
│   │   ├── recording.py
│   │   ├── storage.py
│   │   └── processing.py
│   └── utils/
├── audio/                    # Default output directory for recordings
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
