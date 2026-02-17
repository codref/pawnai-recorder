# GitHub Copilot Instructions - PawnAI Recorder Project

## Project Overview

**PawnAI Recorder** is a professional Python CLI application for audio recording, management, and processing. This document provides project-specific guidelines and architecture for development.

## Project Structure

```
/home/operatore/git-codref/r-n-d/tapmein/
├── pawnai_recorder/                 # Main package
│   ├── __init__.py                     # Package metadata & public API
│   ├── __main__.py                     # 🎯 SINGLE CLI ENTRYPOINT
│   ├── core/                           # Core business logic
│   │   ├── __init__.py
│   │   ├── config.py                   # Configuration management
│   │   ├── recording.py                # Recording engine
│   │   ├── storage.py                  # Audio file storage management
│   │   └── processing.py               # Audio processing pipeline
│   ├── cli/                            # CLI layer
│   │   ├── __init__.py
│   │   ├── commands.py                 # All CLI commands (Typer-based)
│   │   └── utils.py                    # CLI utilities (Rich console, progress)
│   └── utils/                          # General utilities
│       └── __init__.py                 # Helper functions
├── tests/                              # Test suite
│   ├── __init__.py
│   ├── conftest.py                     # Shared test fixtures
│   ├── test_cli.py                     # CLI integration tests
│   ├── test_core.py                    # Core functionality tests
│   └── test_utils.py                   # Utility tests
├── docs/                               # Documentation
│   ├── README.md                       # User guide and command reference
│   ├── ARCHITECTURE.md                 # System architecture & design
│   ├── DEVELOPMENT.md                  # Development workflow
│   ├── PROJECT_ORGANIZATION.md         # Organization summary
│   └── SETUP_COMPLETE.md               # Setup checklist
├── pyproject.toml                      # Modern Python project config
├── setup.py                            # Setup script (backward compatibility)
├── MANIFEST.in                         # Package manifest
├── .gitignore                          # Git ignore rules
├── audio/                              # Audio recordings directory
├── old/                                # Legacy code (ignored by git)
└── README.md                           # Top-level README
```

## Key Architectural Principles

### 1. Single Entry Point
All CLI commands route through `pawnai_recorder/__main__.py:main()`:
```python
def main() -> None:
    """Main entry point function for the CLI."""
    try:
        app()  # Typer app from cli/commands.py
    except KeyboardInterrupt:
        console.print("\n[yellow]Recording cancelled by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        sys.exit(1)
```

### 2. Separation of Concerns
- **Core Layer** (`pawnai_recorder/core/`): Pure business logic, no CLI dependencies
- **CLI Layer** (`pawnai_recorder/cli/`): Command definitions, argument parsing, formatting
- **Utils Layer** (`pawnai_recorder/utils/`): Reusable helper functions

### 3. CLI Framework: Typer
Commands are defined using Typer decorators in `pawnai_recorder/cli/commands.py`:
```python
@app.command()
def record(
    duration: int = typer.Option(10, help="Recording duration in seconds"),
    output: str = typer.Option("audio/recording.wav", help="Output file path"),
    device: str = typer.Option("default", help="Audio device to use"),
) -> None:
    """Start a new audio recording."""
    pass
```

### 4. Rich Output
Use Rich library for formatted terminal output:
```python
from pawnai_recorder.cli.utils import console

console.print("[green]✓ Recording started[/green]")
console.print("[red]✗ Error: Device not found[/red]")
with console.status("[bold green]Recording..."):
    # recording operation
    pass
```

## CLI Commands

### Available Commands
- **record**: Start a new audio recording
- **list**: List all stored recordings
- **play**: Playback a recording
- **info**: Get metadata and information about a recording
- **process**: Apply audio processing (normalization, trimming, etc.)
- **export**: Export recordings in different formats
- **status**: System and device information

### Adding New Commands

1. Add command function to `pawnai_recorder/cli/commands.py`:
```python
@app.command()
def new_command(
    required_arg: str = typer.Argument(...),
    optional_opt: str = typer.Option("default"),
) -> None:
    """Short description of the command."""
    # Implementation here
    pass
```

2. Add corresponding core logic to appropriate module in `pawnai_recorder/core/`

3. Add tests in `tests/test_cli.py` and `tests/test_core.py`

## Core Module Guidelines

### config.py
- Configuration management and constants
- Audio settings (sample rate, bit depth, channels)
- Device configuration
- Storage paths and defaults
- Environment variable handling

### recording.py
- `RecordingEngine` class for audio capture
- Device enumeration and management
- Real-time recording with buffer management
- Audio format handling
- Duration and level monitoring

### storage.py
- `StorageManager` class for file management
- Recording metadata (timestamps, duration, device)
- File organization and indexing
- Cleanup and archival functions
- Database integration for recording catalog

### processing.py
- `AudioProcessor` class for audio manipulation
- Normalization and level adjustment
- Trimming and cutting
- Format conversion
- Filtering and effects

## Development Workflow

### Installation
```bash
cd /home/operatore/git-codref/r-n-d/tapmein
pip install -e ".[dev]"
```

### Running Commands
```bash
# CLI entry point
pawnai-recorder --help
pawnai-recorder status
pawnai-recorder record --duration 30 --output audio/meeting.wav

# Python module
python -m pawnai_recorder --help
python -m pawnai_recorder list
python -m pawnai_recorder play audio/meeting.wav
```

### Code Quality
```bash
# Format code
black pawnai_recorder tests
isort pawnai_recorder tests

# Lint
flake8 pawnai_recorder tests

# Type check
mypy pawnai_recorder

# Run tests
pytest
pytest --cov=pawnai_recorder
```

## Type Hints & IDE Support

All functions should have complete type hints:
```python
from typing import Optional, List, Dict, Any
from pathlib import Path

def record_audio(
    duration: int,
    output_path: Path,
    device: Optional[str] = None,
    sample_rate: int = 44100,
) -> Dict[str, Any]:
    """Record audio to file.
    
    Args:
        duration: Recording duration in seconds
        output_path: Path to save recording
        device: Audio device name, defaults to system default
        sample_rate: Sample rate in Hz
    
    Returns:
        Dictionary with recording metadata (duration, file size, format)
    
    Raises:
        FileNotFoundError: If output directory doesn't exist
        ValueError: If duration is invalid
        RuntimeError: If recording device not available
    """
    pass
```

## Documentation Standards

### Module Docstrings
```python
"""Module for audio recording functionality.

This module provides real-time audio capture capabilities
with support for multiple audio devices and formats.
"""
```

### Function Docstrings
```python
def record(
    duration: int,
    device: Optional[str] = None,
) -> Path:
    """Record audio from device.
    
    Args:
        duration: Recording duration in seconds
        device: Audio device name or ID
    
    Returns:
        Path to recorded file
    
    Example:
        >>> output = record(30, device="Microphone")
        >>> print(f"Saved to {output}")
    """
    pass
```

## Testing Guidelines

### Test Structure
- Unit tests in `tests/test_core.py`
- CLI integration tests in `tests/test_cli.py`
- Shared fixtures in `tests/conftest.py`

### Test Example
```python
import pytest
from pathlib import Path
from pawnai_recorder.core import recording

@pytest.fixture
def temp_output(tmp_path):
    """Provide temporary output directory for tests."""
    return tmp_path / "recordings"

def test_list_devices():
    """Test audio device enumeration."""
    engine = recording.RecordingEngine()
    devices = engine.list_devices()
    assert len(devices) > 0
    assert all("name" in d for d in devices)

def test_record_creates_file(temp_output):
    """Test recording creates output file."""
    temp_output.mkdir(parents=True, exist_ok=True)
    output_path = temp_output / "test.wav"
    
    engine = recording.RecordingEngine()
    result = engine.record(duration=2, output_path=output_path)
    
    assert output_path.exists()
    assert output_path.stat().st_size > 0
```

## Dependencies Management

### pyproject.toml Structure
```toml
[project]
name = "pawnai-recorder"
version = "1.0.0"  # Or dynamic from __init__.py
description = "Professional audio recording and management CLI"
dependencies = [
    "typer[all]>=0.9.0",
    "rich>=13.0.0",
    "sounddevice>=0.4.5",
    "soundfile>=0.12.0",
    "numpy>=1.21.0",
    "scipy>=1.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "black>=23.0",
    "isort>=5.0",
    "mypy>=1.0",
    "flake8>=4.0",
]

[project.scripts]
pawnai-recorder = "pawnai_recorder.__main__:main"
```

## Common Patterns

### Device Management
```python
class RecordingEngine:
    def __init__(self):
        self._devices = None
    
    @property
    def devices(self) -> List[Dict[str, Any]]:
        if self._devices is None:
            self._devices = self._enumerate_devices()
        return self._devices
    
    def _enumerate_devices(self) -> List[Dict[str, Any]]:
        """Enumerate available audio devices."""
        pass
```

### Error Handling in CLI
```python
try:
    result = core.recording.record(duration, output_path, device)
    console.print(f"[green]✓ Recording saved to {result}[/green]")
except FileNotFoundError:
    console.print("[red]Error: Output directory not found[/red]")
    sys.exit(1)
except RuntimeError as e:
    console.print(f"[red]Recording failed: {e}[/red]")
    sys.exit(2)
except KeyboardInterrupt:
    console.print("[yellow]Recording interrupted by user[/yellow]")
    sys.exit(0)
```

### Configuration Management
```python
from pathlib import Path
from pawnai_recorder.core.config import AppConfig

config = AppConfig()
audio_dir = Path(config.get("audio_dir", "audio"))
audio_dir.mkdir(parents=True, exist_ok=True)

sample_rate = config.get("sample_rate", 44100)
channels = config.get("channels", 1)
```

## Import Organization

### Good Imports
```python
# Standard library first
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# Third-party second
import typer
from rich.console import Console
import sounddevice as sd

# Local imports last
from pawnai_recorder.core import recording
from pawnai_recorder.cli.utils import console
```

### Avoid Circular Imports
- Don't import from parent `__init__.py` in child modules
- Import specific classes/functions, not entire modules when possible
- Use `TYPE_CHECKING` for forward references

## Performance Considerations

### Audio Stream Management
- Use buffering for real-time recording
- Monitor CPU usage during recording
- Clean up resources properly after recording

### File Operations
- Use efficient I/O for large audio files
- Index recording catalog for quick lookup
- Consider compression for long-term storage

### Memory Management
- Release audio buffers after use
- Monitor memory during continuous operations
- Implement optional caching for frequently accessed recordings

## Debugging Tips

### Check Device Status
```bash
pawnai-recorder status
```

### Enable Verbose Logging
```python
from pawnai_recorder.cli.utils import console

console.print("[debug][yellow]Device enumeration started[/yellow][/debug]")
```

### Inspect Recording Metadata
```python
from pawnai_recorder.core.storage import StorageManager

manager = StorageManager()
recordings = manager.list_recordings()
for rec in recordings:
    print(f"{rec['name']}: {rec['duration']}s @ {rec['sample_rate']}Hz")
```

## Documentation Files

- [docs/README.md](docs/README.md): User guide, installation, command reference
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): System design, data flow
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): Development workflow
- [docs/PROJECT_ORGANIZATION.md](docs/PROJECT_ORGANIZATION.md): Organization summary
- [docs/SETUP_COMPLETE.md](docs/SETUP_COMPLETE.md): Setup checklist

## Next Steps for Development

1. **Extend Core Functionality**
   - Implement full recording engine with device management
   - Add audio processing and effects
   - Implement metadata and cataloging system

2. **Improve Testing**
   - Add unit tests for all core modules
   - Create integration tests for CLI
   - Add performance benchmarks

3. **Documentation**
   - Write comprehensive user guide
   - Document all configuration options
   - Create usage examples and recipes

4. **Distribution**
   - Build package: `python -m build`
   - Upload to PyPI when ready
   - Create GitHub releases

---

**Last Updated**: February 2026
**Project**: PawnAI Recorder
**Status**: Development
