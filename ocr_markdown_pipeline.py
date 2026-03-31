#!/usr/bin/env python3
"""
GLM-OCR Markdown Pipeline Script

A comprehensive document OCR solution that:
1. Takes PDF or image files as input
2. Runs OCR with GLM-OCR preserving document layout
3. Supports Traditional Chinese (繁體中文) + English (English)
4. Outputs well-formatted markdown with preserved structure
5. Saves results (markdown, JSON, cropped images)

Usage:
    python ocr_markdown_pipeline.py <input_file> [--output-dir OUTPUT_DIR]
    python ocr_markdown_pipeline.py documents/paper.pdf --output-dir ./results
    python ocr_markdown_pipeline.py --batch-dir ./documents --output-dir ./results

Requirements:
    - ZHIPU_API_KEY environment variable or --api-key parameter
    - Python 3.10+
    - pip install glmocr

Configuration:
    Set ZHIPU_API_KEY environment variable or create .env file:
        ZHIPU_API_KEY=sk-xxx
        GLMOCR_MODE=maas  # or selfhosted
        GLMOCR_LOG_LEVEL=INFO
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import traceback


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure logging with colored output."""
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(__name__)


logger = setup_logging()


def import_glmocr():
    """Import GLM-OCR SDK with helpful error messages."""
    try:
        import glmocr
        return glmocr
    except ImportError:
        logger.error(
            "GLM-OCR SDK not found. Install with: pip install glmocr"
        )
        sys.exit(1)


class OCRMarkdownPipeline:
    """
    Production-grade OCR pipeline for document processing.

    Features:
    - Supports multiple input formats (PDF, PNG, JPG, etc.)
    - Preserves document layout (headings, tables, paragraphs, lists)
    - Language support: Traditional Chinese, English
    - Outputs: Markdown (formatted), JSON (structured), images (cropped regions)
    - Progress tracking and error recovery
    - Configurable API endpoints and models
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        mode: str = "maas",
        api_url: Optional[str] = None,
        log_level: str = "INFO",
        layout_device: Optional[str] = None,
    ):
        """
        Initialize the OCR pipeline.

        Args:
            api_key: Zhipu API key (defaults to ZHIPU_API_KEY env var)
            mode: "maas" (cloud, recommended) or "selfhosted" (local vLLM/SGLang)
            api_url: Custom API endpoint (optional)
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
            layout_device: GPU device for layout detection ("cpu", "cuda", "cuda:0", etc.)
        """
        self.logger = setup_logging(log_level)
        self.mode = mode
        self.api_key = api_key or os.getenv("ZHIPU_API_KEY")
        self.api_url = api_url
        self.layout_device = layout_device

        if not self.api_key and self.mode == "maas":
            self.logger.error(
                "ZHIPU_API_KEY not found. Please set it via:\n"
                "  export ZHIPU_API_KEY=sk-xxx\n"
                "  or pass --api-key parameter\n"
                "  or create .env file with ZHIPU_API_KEY=sk-xxx"
            )
            sys.exit(1)

        self._init_glmocr()

    def _init_glmocr(self):
        """Initialize GLM-OCR client."""
        try:
            glmocr = import_glmocr()

            init_kwargs = {
                "mode": self.mode,
            }

            if self.api_key:
                init_kwargs["api_key"] = self.api_key
            if self.api_url:
                init_kwargs["api_url"] = self.api_url
            if self.layout_device:
                init_kwargs["layout_device"] = self.layout_device

            self.ocr = glmocr.GlmOcr(**init_kwargs)
            self.logger.info(
                f"✓ GLM-OCR initialized (mode={self.mode}, "
                f"version={glmocr.__version__})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize GLM-OCR: {e}")
            traceback.print_exc()
            sys.exit(1)

    def _validate_input_file(self, file_path: str) -> Path:
        """Validate that input file exists and is supported."""
        path = Path(file_path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")

        supported = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
        if path.suffix.lower() not in supported:
            raise ValueError(
                f"Unsupported file type: {path.suffix}\n"
                f"Supported types: {', '.join(supported)}"
            )

        return path

    def _prepare_output_dir(self, output_dir: Optional[str]) -> Path:
        """Create and return output directory path."""
        if output_dir:
            out_path = Path(output_dir).resolve()
        else:
            # Default: create output with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = Path(f"ocr_output_{timestamp}").resolve()

        out_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Output directory: {out_path}")
        return out_path

    def _format_markdown_output(
        self, json_result: List[List[Dict[str, Any]]]
    ) -> str:
        """
        Format OCR results into well-structured markdown.

        Converts JSON layout with content into hierarchical markdown
        with proper formatting for:
        - Headings (title, heading)
        - Body text (text, paragraph)
        - Tables (markdown format)
        - Formulas (LaTeX)
        - Figures and captions
        - Lists (bullet/numbered)

        Args:
            json_result: List of pages, each page is list of regions

        Returns:
            Formatted markdown string
        """
        markdown_parts = []

        # Document header
        markdown_parts.append("# Document OCR Result\n")
        markdown_parts.append(
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"
        )
        markdown_parts.append("---\n\n")

        # Process each page
        for page_idx, page_content in enumerate(json_result, 1):
            if page_idx > 1:
                markdown_parts.append("\n---\n\n")  # Page separator

            markdown_parts.append(f"## Page {page_idx}\n\n")

            # Sort regions by position (top-to-bottom, left-to-right)
            sorted_regions = sorted(
                page_content,
                key=lambda r: (
                    r.get("bbox_2d", [0, 0, 0, 0])[1],  # y-coordinate
                    r.get("bbox_2d", [0, 0, 0, 0])[0],  # x-coordinate
                ),
            )

            # Render each region
            for region in sorted_regions:
                label = region.get("label", "text")
                content = region.get("content", "")

                if not content:
                    continue

                # Format based on element type
                if label == "title":
                    markdown_parts.append(f"# {content}\n\n")
                elif label in ("heading", "header"):
                    markdown_parts.append(f"### {content}\n\n")
                elif label == "text":
                    markdown_parts.append(f"{content}\n\n")
                elif label == "table":
                    # Tables are typically in markdown format already
                    markdown_parts.append(f"{content}\n\n")
                elif label == "formula":
                    # LaTeX formulas
                    markdown_parts.append(f"$$\n{content}\n$$\n\n")
                elif label == "figure":
                    markdown_parts.append(f"![Figure]({content})\n\n")
                elif label == "figure_caption":
                    markdown_parts.append(f"*{content}*\n\n")
                elif label == "page_number":
                    # Skip page numbers
                    pass
                elif label == "reference":
                    markdown_parts.append(f"> {content}\n\n")
                else:
                    # Default: treat as paragraph
                    markdown_parts.append(f"{content}\n\n")

        return "".join(markdown_parts)

    def process_file(
        self,
        input_file: str,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a single document file through OCR pipeline.

        Args:
            input_file: Path to PDF or image file
            output_dir: Output directory for results (default: auto-generated)

        Returns:
            Dictionary with processing results:
            {
                "success": bool,
                "input_file": str,
                "output_dir": str,
                "markdown_file": str,
                "json_file": str,
                "pages_processed": int,
                "regions_detected": int,
                "execution_time": float,
                "error": str (if failed)
            }
        """
        import time

        start_time = time.time()
        result = {
            "success": False,
            "input_file": input_file,
            "output_dir": None,
            "markdown_file": None,
            "json_file": None,
            "pages_processed": 0,
            "regions_detected": 0,
            "execution_time": 0,
        }

        try:
            # Validate and prepare
            input_path = self._validate_input_file(input_file)
            output_path = self._prepare_output_dir(output_dir)
            result["output_dir"] = str(output_path)

            self.logger.info(f"Processing: {input_path}")

            # Run OCR pipeline
            ocr_result = self.ocr.parse(str(input_path))

            if not ocr_result:
                raise RuntimeError("OCR returned empty result")

            # Extract data
            json_data = ocr_result.json_result
            if not json_data:
                raise RuntimeError("No JSON result from OCR")

            # Count pages and regions
            num_pages = len(json_data)
            total_regions = sum(len(page) for page in json_data)
            result["pages_processed"] = num_pages
            result["regions_detected"] = total_regions

            self.logger.info(
                f"✓ OCR complete: {num_pages} pages, {total_regions} regions"
            )

            # Format markdown output
            markdown_content = self._format_markdown_output(json_data)

            # Save results
            base_name = input_path.stem
            markdown_file = output_path / f"{base_name}.md"
            json_file = output_path / f"{base_name}.json"

            markdown_file.write_text(markdown_content, encoding="utf-8")
            self.logger.info(f"✓ Saved markdown: {markdown_file}")
            result["markdown_file"] = str(markdown_file)

            json_file.write_text(
                json.dumps(json_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.logger.info(f"✓ Saved JSON: {json_file}")
            result["json_file"] = str(json_file)

            # Save cropped images if available
            try:
                ocr_result.save(output_dir=str(output_path / "images"))
                self.logger.info(
                    f"✓ Saved region images: {output_path / 'images'}"
                )
            except Exception as e:
                self.logger.warning(f"Could not save region images: {e}")

            # Save original JSON result with metadata
            metadata = {
                "source_file": str(input_path),
                "timestamp": datetime.now().isoformat(),
                "pages": num_pages,
                "regions": total_regions,
                "mode": self.mode,
            }

            full_result = {
                "metadata": metadata,
                "data": json_data,
            }

            metadata_file = output_path / f"{base_name}_metadata.json"
            metadata_file.write_text(
                json.dumps(full_result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result["success"] = True
            result["execution_time"] = time.time() - start_time

            self.logger.info(
                f"✓ Processing complete ({result['execution_time']:.2f}s)"
            )

            return result

        except Exception as e:
            result["error"] = str(e)
            result["execution_time"] = time.time() - start_time
            self.logger.error(f"✗ Processing failed: {e}")
            traceback.print_exc()
            return result

    def process_batch(
        self,
        batch_dir: str,
        output_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process multiple files from a directory.

        Args:
            batch_dir: Directory containing PDF/image files
            output_dir: Output directory (default: auto-generated)

        Returns:
            List of results for each file
        """
        batch_path = Path(batch_dir).resolve()

        if not batch_path.is_dir():
            raise ValueError(f"Not a directory: {batch_dir}")

        # Find all supported files
        supported = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
        files = [
            p for p in batch_path.rglob("*") if p.suffix.lower() in supported
        ]

        if not files:
            self.logger.warning(f"No supported files found in {batch_dir}")
            return []

        self.logger.info(f"Found {len(files)} file(s) to process")

        results = []
        for file_path in files:
            result = self.process_file(str(file_path), output_dir)
            results.append(result)

        return results

    def close(self):
        """Clean up resources."""
        if hasattr(self, "ocr"):
            self.ocr.close()
            self.logger.info("✓ OCR client closed")


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="GLM-OCR Markdown Pipeline - Convert documents to structured markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single PDF
  python ocr_markdown_pipeline.py document.pdf

  # Process with custom output directory
  python ocr_markdown_pipeline.py document.pdf --output-dir ./results

  # Process batch directory
  python ocr_markdown_pipeline.py --batch-dir ./documents --output-dir ./results

  # Use custom API settings
  python ocr_markdown_pipeline.py document.pdf --api-key sk-xxx --mode maas

  # Self-hosted mode with local vLLM
  python ocr_markdown_pipeline.py document.pdf --mode selfhosted

  # Specify GPU device
  python ocr_markdown_pipeline.py document.pdf --layout-device cuda:0

Environment Variables:
  ZHIPU_API_KEY    - API key for cloud service (required for MaaS mode)
  GLMOCR_MODE      - "maas" or "selfhosted"
  GLMOCR_LOG_LEVEL - DEBUG, INFO, WARNING, ERROR
        """,
    )

    parser.add_argument(
        "input_file",
        nargs="?",
        help="Input PDF or image file to process",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for results",
    )
    parser.add_argument(
        "--batch-dir",
        help="Process all files in directory",
    )
    parser.add_argument(
        "--api-key",
        help="Zhipu API key (overrides ZHIPU_API_KEY env var)",
    )
    parser.add_argument(
        "--mode",
        choices=["maas", "selfhosted"],
        default="maas",
        help="Operation mode (default: maas)",
    )
    parser.add_argument(
        "--api-url",
        help="Custom API endpoint URL",
    )
    parser.add_argument(
        "--layout-device",
        help="GPU device for layout detection (cpu, cuda, cuda:0, etc.)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.input_file and not args.batch_dir:
        parser.print_help()
        sys.exit(1)

    if args.input_file and args.batch_dir:
        logger.error("Specify either input_file or --batch-dir, not both")
        sys.exit(1)

    # Run pipeline
    try:
        pipeline = OCRMarkdownPipeline(
            api_key=args.api_key,
            mode=args.mode,
            api_url=args.api_url,
            log_level=args.log_level,
            layout_device=args.layout_device,
        )

        if args.batch_dir:
            results = pipeline.process_batch(
                args.batch_dir, args.output_dir
            )

            # Summary
            logger.info("\n" + "=" * 60)
            logger.info("BATCH PROCESSING SUMMARY")
            logger.info("=" * 60)
            successful = sum(1 for r in results if r["success"])
            logger.info(f"Total files: {len(results)}")
            logger.info(f"Successful: {successful}")
            logger.info(f"Failed: {len(results) - successful}")

            for r in results:
                status = "✓" if r["success"] else "✗"
                logger.info(
                    f"{status} {Path(r['input_file']).name}: "
                    f"{r.get('pages_processed', 0)} pages, "
                    f"{r.get('regions_detected', 0)} regions"
                )
        else:
            result = pipeline.process_file(
                args.input_file, args.output_dir
            )

            # Summary
            logger.info("\n" + "=" * 60)
            logger.info("PROCESSING RESULT")
            logger.info("=" * 60)
            if result["success"]:
                logger.info(f"✓ Status: SUCCESS")
                logger.info(f"  Pages: {result['pages_processed']}")
                logger.info(f"  Regions: {result['regions_detected']}")
                logger.info(f"  Time: {result['execution_time']:.2f}s")
                logger.info(f"  Output: {result['output_dir']}")
                logger.info(f"  Markdown: {result['markdown_file']}")
                logger.info(f"  JSON: {result['json_file']}")
            else:
                logger.error(f"✗ Status: FAILED")
                logger.error(f"  Error: {result.get('error', 'Unknown error')}")
                sys.exit(1)

        pipeline.close()

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
