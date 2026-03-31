"""Entry point: python -m tui [file] [--config path]."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GLM-OCR Terminal UI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tui
  python -m tui document.pdf
  python -m tui document.pdf --config my_config.yaml

Keyboard shortcuts:
  Q  Quit          O  Focus file input
  R  Run pipeline  S  Toggle settings
  L  Toggle logs   Esc Cancel/Close
        """,
    )
    parser.add_argument("file", nargs="?", default="", help="PDF or image file path")
    parser.add_argument(
        "--config", "-c", default=None, help="Path to YAML config file"
    )
    args = parser.parse_args()

    from tui.app import OcrTuiApp

    app = OcrTuiApp(file_path=args.file, config_path=args.config)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
