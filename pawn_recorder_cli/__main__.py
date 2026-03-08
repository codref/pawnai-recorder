"""Entry point for PawnAI Recorder when invoked as a module or command."""

import sys

from pawnai_recorder.cli import app
from pawnai_recorder.cli.utils import console


def main() -> None:
    """Main entry point function for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[warning]Recording cancelled by user[/warning]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[error]Error: {str(e)}[/error]")
        sys.exit(1)


if __name__ == "__main__":
    main()
