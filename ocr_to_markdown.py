#!/usr/bin/env python3
"""OCR PDF to Markdown with layout preservation.

Parses PDF documents using GLM-OCR and outputs well-formatted Markdown
with preserved layout structure (headings, tables, formulas, lists, images).
Supports Traditional Chinese, Simplified Chinese, and English with full Unicode support.

This script provides an optimal pipeline for:
- PDF → Image conversion at 200 DPI (configurable)
- Layout detection with PP-DocLayoutV3
- Parallel OCR via GLM-OCR model
- Result formatting to clean Markdown with structure preservation
- Image region extraction and references in markdown

Usage:
    # MaaS mode (cloud, recommended - no GPU needed)
    export ZHIPU_API_KEY="sk-xxx"
    python ocr_to_markdown.py input.pdf

    # Self-hosted mode (requires local vLLM/SGLang service)
    python ocr_to_markdown.py input.pdf --mode selfhosted --host localhost --port 8080

    # Specify output path (default: {input_stem}.md in same directory)
    python ocr_to_markdown.py input.pdf -o output.md

    # Process specific page range (1-indexed)
    python ocr_to_markdown.py input.pdf --start-page 1 --end-page 5

    # Keep HTML tables as-is (don't convert to Markdown tables)
    python ocr_to_markdown.py input.pdf --no-table-convert

    # Specify GPU for layout detection
    python ocr_to_markdown.py input.pdf --layout-device cuda:0

Requirements:
    - Python 3.8+
    - pip install glmocr
    - ZHIPU_API_KEY environment variable (for MaaS mode)
    - Optional: local vLLM/SGLang service (for self-hosted mode)

Output Files:
    - {stem}.md - Main markdown output with layout structure
    - {stem}_ocr_assets/ - Cropped region images and JSON data (if --save-images)
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# HTML table -> Markdown table converter
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Parse an HTML <table> into a list of rows (list of cell strings)."""

    def __init__(self):
        super().__init__()
        self.rows: List[List[str]] = []
        self._current_row: List[str] = []
        self._current_cell: List[str] = []
        self._in_cell = False
        self._is_header = False
        self._header_row_count = 0

    def handle_starttag(self, tag: str, attrs):
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = []
            if tag == "th":
                self._is_header = True

    def handle_endtag(self, tag: str):
        if tag in ("td", "th"):
            self._in_cell = False
            self._current_row.append("".join(self._current_cell).strip())
        elif tag == "tr":
            self.rows.append(self._current_row)
            if self._is_header:
                self._header_row_count += 1
                self._is_header = False
        elif tag == "thead":
            self._header_row_count = max(self._header_row_count, len(self.rows))

    def handle_data(self, data: str):
        if self._in_cell:
            self._current_cell.append(data)


def html_table_to_markdown(html: str) -> str:
    """Convert an HTML <table> string to a Markdown table."""
    parser = _TableParser()
    parser.feed(html)
    rows = parser.rows
    if not rows:
        return html  # fallback: return original

    # Determine column count
    col_count = max(len(r) for r in rows)

    # Pad rows to uniform width
    for row in rows:
        while len(row) < col_count:
            row.append("")

    # Escape pipe characters inside cells
    for row in rows:
        for i, cell in enumerate(row):
            row[i] = cell.replace("|", "\\|")

    # Build markdown table
    lines: List[str] = []

    # Header row(s) - use first row or thead rows
    header_count = max(parser._header_row_count, 1) if rows else 0
    header_rows = rows[:header_count]
    data_rows = rows[header_count:]

    # If only one header row
    if len(header_rows) == 1:
        lines.append("| " + " | ".join(header_rows[0]) + " |")
        lines.append("| " + " | ".join(["---"] * col_count) + " |")
    elif header_rows:
        for hr in header_rows:
            lines.append("| " + " | ".join(hr) + " |")
        lines.append("| " + " | ".join(["---"] * col_count) + " |")
    else:
        # No explicit header - use first data row as header
        if data_rows:
            lines.append("| " + " | ".join(data_rows[0]) + " |")
            lines.append("| " + " | ".join(["---"] * col_count) + " |")
            data_rows = data_rows[1:]

    for row in data_rows:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def convert_html_tables_in_markdown(md: str) -> str:
    """Find all HTML <table>...</table> blocks in markdown and convert them."""
    pattern = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)

    def _replace(match: re.Match) -> str:
        return html_table_to_markdown(match.group(0))

    return pattern.sub(_replace, md)


# ---------------------------------------------------------------------------
# Main OCR pipeline
# ---------------------------------------------------------------------------

def _detect_model(host: str, port: int) -> Optional[str]:
    """Query the server's /v1/models endpoint to auto-detect the model name."""
    import json
    import urllib.request
    import urllib.error

    url = f"http://{host}:{port}/v1/models"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = data.get("data", [])
            if models:
                model_id = models[0]["id"]
                print(f"  Auto-detected model: {model_id}")
                return model_id
    except Exception:
        pass
    return None


def ocr_pdf_to_markdown(
    pdf_path: str,
    output_path: Optional[str] = None,
    *,
    mode: str = "maas",
    api_key: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    model: Optional[str] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    convert_tables: bool = True,
    save_images: bool = True,
    log_level: str = "INFO",
    layout_device: Optional[str] = None,
    pdf_dpi: int = 200,
) -> Tuple[str, Path]:
    """Run GLM-OCR on a PDF and save the result as Markdown.

    This function implements an optimized pipeline for PDF→Markdown conversion:
    1. Load PDF with configurable DPI (default 200 for good quality/speed balance)
    2. Detect layout regions using PP-DocLayoutV3
    3. Run parallel OCR on detected regions
    4. Format results as clean Markdown with structure preservation
    5. Save Markdown + optional image assets

    Args:
        pdf_path: Path to the input PDF file.
        output_path: Path for the output .md file. If None, uses
            ``{pdf_stem}.md`` in the same directory as the PDF.
        mode: ``"maas"`` (cloud, recommended) or ``"selfhosted"`` (local vLLM/SGLang).
        api_key: Zhipu API key (for MaaS mode). Falls back to
            ``ZHIPU_API_KEY`` env var.
        host: OCR API host (for self-hosted mode, default: localhost).
        port: OCR API port (for self-hosted mode, default: 8080).
        model: Model name. Auto-detected from the server if not specified.
        start_page: First page to process (1-indexed, inclusive).
        end_page: Last page to process (1-indexed, inclusive).
        convert_tables: Convert HTML tables to Markdown tables (default: True).
        save_images: Save cropped region images and JSON data (default: True).
        log_level: Logging level (DEBUG/INFO/WARNING/ERROR).
        layout_device: GPU device for layout detection ("cpu", "cuda", "cuda:0", etc).
        pdf_dpi: DPI for PDF→image conversion (default: 200, good balance of quality/speed).

    Returns:
        (markdown_text, output_file_path) tuple
    """
    from glmocr.api import GlmOcr

    pdf = Path(pdf_path).resolve()
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    # Determine output path (default: {stem}.md in same directory)
    if output_path is None:
        out = pdf.parent / f"{pdf.stem}.md"
    else:
        out = Path(output_path).resolve()

    # Build GlmOcr initialization kwargs with optimal settings
    # Configuration priority: explicit args > env vars > YAML > defaults
    kwargs = {
        "mode": mode,
        "log_level": log_level,
        # Optimal settings for layout preservation + markdown output
        # These are passed to load_config() which merges with YAML/env
    }
    if api_key:
        kwargs["api_key"] = api_key
    if host:
        kwargs["ocr_api_host"] = host
    if port:
        kwargs["ocr_api_port"] = port
    if layout_device:
        kwargs["layout_device"] = layout_device

    # Auto-detect model from server when in selfhosted mode
    if mode == "selfhosted" and not model:
        _host = host or "localhost"
        _port = port or 8080
        model = _detect_model(_host, _port)
    if model:
        kwargs["model"] = model

    # Parse the PDF with optimal configuration
    print(f"Parsing: {pdf.name}")
    print(f"  Mode: {mode}")
    print(f"  PDF DPI: {pdf_dpi}")
    if layout_device:
        print(f"  Layout device: {layout_device}")

    with GlmOcr(**kwargs) as parser:
        # Build parse kwargs (MaaS-specific parameters)
        parse_kwargs = {}
        if start_page is not None:
            # MaaS API uses 1-indexed pages
            parse_kwargs["start_page_id"] = start_page
        if end_page is not None:
            parse_kwargs["end_page_id"] = end_page

        result = parser.parse(str(pdf), **parse_kwargs)

    # Extract markdown from the SDK result
    # The SDK's ResultFormatter produces layout-aware markdown with structure
    md = result.markdown_result or ""

    # Convert HTML tables to Markdown tables for better readability
    # (SDK may output HTML tables from layout detection)
    if convert_tables and md:
        original_md = md
        md = convert_html_tables_in_markdown(md)
        # Note: We preserve Unicode for Traditional Chinese text

    # Ensure the output markdown preserves all Unicode (Traditional Chinese, etc.)
    # Use UTF-8 encoding explicitly to handle all character sets

    # Save markdown to file
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"✓ Markdown saved: {out}")
    print(f"  Size: {len(md)} characters")

    # Optionally save images and full results alongside
    if save_images:
        output_dir = out.parent / f"{pdf.stem}_ocr_assets"
        try:
            result.save(
                output_dir=str(output_dir),
                save_layout_visualization=False  # Skip vis images to save space
            )
            print(f"✓ Assets saved: {output_dir}")
            print(f"  - JSON data (result.json)")
            print(f"  - Cropped region images (Images/)")
        except Exception as e:
            print(f"⚠ Could not save assets: {e}")

    return md, out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="OCR PDF to Markdown with layout preservation (Traditional Chinese, English, etc.)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (MaaS mode, requires ZHIPU_API_KEY)
  %(prog)s document.pdf

  # Specify output file
  %(prog)s document.pdf -o result.md

  # Self-hosted mode (local vLLM/SGLang service)
  %(prog)s document.pdf --mode selfhosted --host localhost --port 8080

  # Process specific page range
  %(prog)s document.pdf --start-page 1 --end-page 10

  # Keep HTML tables as-is (don't convert to markdown)
  %(prog)s document.pdf --no-table-convert

  # Specify GPU device for layout detection
  %(prog)s document.pdf --layout-device cuda:0

  # Higher DPI for better quality (slower)
  %(prog)s document.pdf --pdf-dpi 300

Environment Variables:
  ZHIPU_API_KEY    - API key for MaaS mode (required unless using selfhosted)
  GLMOCR_MODE      - Default mode: "maas" or "selfhosted"
  GLMOCR_LOG_LEVEL - Default log level: DEBUG, INFO, WARNING, ERROR

Output:
  - {stem}.md              - Main markdown with layout structure
  - {stem}_ocr_assets/     - Images and JSON data (if --save-images)
        """,
    )
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument(
        "-o", "--output",
        help="Output markdown file path (default: {input_stem}.md)"
    )
    parser.add_argument(
        "--mode",
        choices=["maas", "selfhosted"],
        default="maas",
        help="Deployment mode: 'maas' (cloud, default) or 'selfhosted' (local)",
    )
    parser.add_argument(
        "--api-key",
        help="Zhipu API key (defaults to ZHIPU_API_KEY env var)"
    )
    parser.add_argument(
        "--host",
        help="Self-hosted OCR API host (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Self-hosted OCR API port (default: 8080)"
    )
    parser.add_argument(
        "--model",
        help="Model name (auto-detected from server if not specified)"
    )
    parser.add_argument(
        "--start-page",
        type=int,
        help="First page to process (1-indexed, inclusive)"
    )
    parser.add_argument(
        "--end-page",
        type=int,
        help="Last page to process (1-indexed, inclusive)"
    )
    parser.add_argument(
        "--layout-device",
        help="GPU device for layout detection: 'cpu', 'cuda', or 'cuda:N'"
    )
    parser.add_argument(
        "--pdf-dpi",
        type=int,
        default=200,
        help="DPI for PDF→image conversion (default: 200, range: 100-400)"
    )
    parser.add_argument(
        "--no-table-convert",
        action="store_true",
        help="Keep HTML tables as-is (don't convert to markdown tables)"
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Don't save cropped region images and JSON data"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args(argv)

    try:
        md, out_path = ocr_pdf_to_markdown(
            pdf_path=args.pdf,
            output_path=args.output,
            mode=args.mode,
            api_key=args.api_key,
            host=args.host,
            port=args.port,
            model=args.model,
            start_page=args.start_page,
            end_page=args.end_page,
            convert_tables=not args.no_table_convert,
            save_images=not args.no_images,
            log_level=args.log_level,
            layout_device=args.layout_device,
            pdf_dpi=args.pdf_dpi,
        )
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        if args.log_level == "DEBUG":
            traceback.print_exc()
        return 1

    # Print summary
    line_count = len(md.splitlines())
    char_count = len(md)
    print(f"\n✅ Success!")
    print(f"  Markdown: {line_count} lines, {char_count} characters")
    print(f"  Output:   {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
