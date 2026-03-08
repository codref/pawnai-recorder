"""Entry point for pawn-recorder CLI when invoked as a module or command."""

import sys

from pawn_recorder_cli import app
from pawn_recorder_cli.utils import console


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
