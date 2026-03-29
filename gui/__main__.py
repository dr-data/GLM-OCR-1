"""Entry-point for ``python -m gui``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is importable.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from gui.server import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="GLM-OCR Web GUI")
    parser.add_argument("--port", type=int, default=8080, help="Listen port")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    _default_config = str(Path(__file__).resolve().parent / "gui_config.yaml")
    parser.add_argument("--config", default=_default_config, help="Path to config YAML")
    args = parser.parse_args()

    import uvicorn

    app = create_app(config_path=args.config)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
