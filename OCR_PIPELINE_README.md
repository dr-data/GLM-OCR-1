# GLM-OCR Markdown Pipeline

A production-grade Python script for converting PDF documents and images into well-structured markdown with preserved layout, supporting Traditional Chinese and English text recognition.

## Quick Start

```bash
# 1. Install GLM-OCR SDK
pip install glmocr

# 2. Set API key
export ZHIPU_API_KEY=sk-your-key

# 3. Process a document
python ocr_markdown_pipeline.py document.pdf --output-dir ./results
```

## Features

✨ **Document Processing**
- PDF, PNG, JPG, BMP, GIF, WebP support
- Preserves structure: headings, tables, formulas, figures
- Traditional Chinese (繁體中文) + English support
- Outputs: Markdown + JSON + Cropped images

🚀 **Two Deployment Modes**
- **MaaS** (Cloud): Zero-GPU, Zhipu API recommended
- **Self-hosted**: Local vLLM/SGLang with GPU

⚙️ **Enterprise Ready**
- Single-file or batch processing
- Progress tracking & error recovery
- Debug logging & execution metrics
- GPU device configuration

## Installation

```bash
# Minimal (cloud only)
pip install glmocr

# Self-hosted (with layout detection)
pip install "glmocr[selfhosted]"

# From source
git clone https://github.com/zai-org/GLM-OCR.git
cd GLM-OCR
pip install -e .
```

## API Key Setup

Get your API key: https://www.bigmodel.cn/usercenter/proj-mgmt/apikeys

```bash
# Option 1: Environment variable
export ZHIPU_API_KEY=sk-xxx

# Option 2: .env file
echo "ZHIPU_API_KEY=sk-xxx" > .env

# Option 3: CLI argument
python ocr_markdown_pipeline.py document.pdf --api-key sk-xxx
```

## Usage

### Single File
```bash
python ocr_markdown_pipeline.py document.pdf
python ocr_markdown_pipeline.py image.png --output-dir ./results
```

### Batch Processing
```bash
python ocr_markdown_pipeline.py --batch-dir ./documents --output-dir ./results
```

### Self-Hosted Mode

Start vLLM server:
```bash
vllm serve zai-org/GLM-OCR --port 8080
```

Run pipeline:
```bash
python ocr_markdown_pipeline.py document.pdf --mode selfhosted
```

### Advanced Options
```bash
# Specify GPU device
python ocr_markdown_pipeline.py document.pdf --layout-device cuda:0

# Use CPU for layout
python ocr_markdown_pipeline.py document.pdf --layout-device cpu

# Debug logging
python ocr_markdown_pipeline.py document.pdf --log-level DEBUG

# Custom API endpoint
python ocr_markdown_pipeline.py document.pdf \
  --api-url https://custom.endpoint/v1/chat/completions
```

## Output Files

After processing, you get:

| File | Content |
|------|---------|
| `.md` | Formatted markdown with structure |
| `.json` | Structured OCR results |
| `_metadata.json` | Processing metadata |
| `images/` | Cropped region images |

### Markdown Example
```markdown
# Document OCR Result

## Page 1

# Title

Body text paragraph...

## Section

| Table | Column |
|-------|--------|
| Data  | Value  |

$$\LaTeX formula$$

[Figure](image.png)
```

## Language Support

- Traditional Chinese (繁體中文) ✅
- English (English) ✅
- Mixed documents with auto-detection ✅

## Element Types

| Element | Format |
|---------|--------|
| Title | `# Title` |
| Heading | `### Heading` |
| Text | Regular paragraph |
| Table | Markdown table |
| Formula | `$$LaTeX$$` |
| Figure | `![](image.png)` |
| Quote | `> Reference` |

## Common Issues

**API Key Not Found**
```bash
export ZHIPU_API_KEY=sk-your-key
```

**File Not Found**
```bash
# Use absolute paths
python ocr_markdown_pipeline.py /absolute/path/to/file.pdf
```

**Connection Error**
```bash
# Check internet connection
# Verify API key is valid
# Check firewall/VPN settings
```

## Architecture

```
PDF/Image → PageLoader → LayoutDetector → OCRClient → ResultFormatter → Output
                         (PP-DocLayout)   (GLM-OCR)   (MD + JSON)      Files
```

## Performance Tips

1. Process multiple files at once for better throughput
2. Use `--layout-device cuda:0` for faster layout detection
3. Set `--log-level WARNING` for production
4. Monitor GPU memory with `nvidia-smi`

## Example Workflows

### Research Paper Processing
```bash
python ocr_markdown_pipeline.py paper.pdf \
  --output-dir ./papers \
  --log-level INFO
```

### Document Archive Conversion
```bash
python ocr_markdown_pipeline.py \
  --batch-dir ./scanned_docs \
  --output-dir ./converted \
  --log-level DEBUG
```

### Python Integration
```python
from ocr_markdown_pipeline import OCRMarkdownPipeline

pipeline = OCRMarkdownPipeline(api_key="sk-xxx")
result = pipeline.process_file("doc.pdf", output_dir="./out")

if result["success"]:
    print(f"Pages: {result['pages_processed']}")
    print(f"Regions: {result['regions_detected']}")
    print(f"Output: {result['markdown_file']}")

pipeline.close()
```

## Supported Formats

| Format | Support |
|--------|---------|
| PDF | ✅ Full |
| PNG | ✅ Full |
| JPG/JPEG | ✅ Full |
| BMP | ✅ Full |
| GIF | ✅ Full |
| WebP | ✅ Full |

## Requirements

- Python 3.10+
- 100 MB disk space per document (approx)
- glmocr>=0.1.4
- Internet (MaaS) or GPU (self-hosted)

## Resources

- **GitHub**: https://github.com/zai-org/GLM-OCR
- **API Key**: https://www.bigmodel.cn/usercenter/proj-mgmt/apikeys
- **Documentation**: https://docs.z.ai/guides/vlm/glm-ocr
- **Discord**: https://discord.gg/QR7SARHRxK

## License

- Script: Apache License 2.0
- GLM-OCR Model: MIT License
