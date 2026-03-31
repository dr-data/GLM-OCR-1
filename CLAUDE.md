# GLM-OCR Project

## Overview
GLM-OCR is a document OCR system (0.9B parameters, #1 on OmniDocBench V1.5) with a Python SDK, CLI, Web GUI, and TUI. It processes PDFs/images into structured markdown preserving layout, tables, formulas, and supports Traditional Chinese + English natively.

## Architecture

```
SDK (glmocr/)          GUI (gui/)           TUI (tui/)
   │                      │                    │
   ├─ api.py (GlmOcr)    ├─ server.py (FastAPI)├─ app.py (Textual)
   ├─ cli.py              ├─ pipeline_worker.py ├─ config_manager.py
   ├─ pipeline/           ├─ static/app.js     │
   ├─ layout/             ├─ templates/        │
   ├─ postprocess/        ├─ gui_config.yaml   │
   └─ config.yaml         └─ __main__.py       │
                                                │
Scripts (root)            Sandbox               │
   ├─ ocr_to_markdown.py  .server_venvs/       │
   └─ ocr_markdown_pipeline.py  ├─ mlx/        │
                                └─ vllm/       │
```

## Two Operating Modes

### MaaS (Cloud)
- Uses Zhipu cloud API, no GPU needed
- Set `ZHIPU_API_KEY` env var
- Endpoint: `https://open.bigmodel.cn/api/paas/v4/layout_parsing`

### Self-Hosted (Local — Apple Silicon)
- MLX-VLM server runs GLM-OCR model locally on Metal GPU
- Model: `mlx-community/GLM-OCR-bf16` (~1.8GB, auto-downloads on first use)
- Server installed in sandbox venv: `.server_venvs/mlx/`
- SDK communicates via HTTP on port 8090

## GUI System

### Start
```bash
.venv/bin/python -m gui --port 8080
```

### Key Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Main pipeline page (one-click upload + process) |
| `/settings` | GET | Advanced configuration |
| `/api/health` | GET | Server status for status bar |
| `/api/auto-start` | POST | Auto-detect, install, and start best server |
| `/api/upload` | POST | Upload file and start processing |
| `/api/progress/{id}` | GET | SSE stream of pipeline progress |
| `/api/result/{id}` | GET | Final markdown result |
| `/api/server/start` | POST | Start a specific server type |
| `/api/server/stop` | POST | Stop a server |
| `/api/server/status` | GET | All server types status |
| `/api/server/install` | POST | Install server in sandbox venv |
| `/api/server/install/status/{type}` | GET | Poll install progress |
| `/api/server/logs/{type}` | GET | Server stdout/stderr logs |

### One-Click Flow
1. Page load → `GET /api/health` → shows server status bar (green/yellow/red)
2. User drops PDF → `POST /api/auto-start` → installs/starts server if needed
3. File uploaded → `POST /api/upload` → starts pipeline worker
4. SSE progress → live pipeline stages + server logs + markdown preview
5. Result displayed with Copy/Download buttons

### Sandbox Install System
Server backends install into isolated virtualenvs under `.server_venvs/`:
- MLX-VLM: `.server_venvs/mlx/bin/python -m mlx_vlm.server`
- vLLM: `.server_venvs/vllm/bin/python` (Linux only, requires CUDA)
- Install source: `git+https://github.com/Blaizzy/mlx-vlm.git` (includes GLM-OCR model arch)

## Pipeline (3-Stage Async)

```
PageLoader (Thread 1)     LayoutDetector (Thread 2)     OCRClient (Thread 3)
PDF → PIL Images    →     PP-DocLayoutV3 regions   →    VLM inference (parallel)
     page_queue              region_queue                    ↓
                                                      ResultFormatter → MD + JSON
```

- Layout model: `PaddlePaddle/PP-DocLayoutV3_safetensors` (auto-downloads from HuggingFace)
- OCR model: `mlx-community/GLM-OCR-bf16` (for MLX) or `zai-org/GLM-OCR` (for vLLM)
- Output: Markdown with title hierarchy, LaTeX formulas, HTML→MD tables, image refs

## Key Configuration

### gui/gui_config.yaml (GUI defaults)
```yaml
pipeline:
  maas:
    enabled: false          # false = self-hosted mode
  ocr_api:
    api_host: localhost
    api_port: 8090          # NOT 8080 (that's the GUI)
    model: mlx-community/GLM-OCR-bf16
    api_path: /chat/completions   # no /v1 prefix for MLX
  layout:
    threshold: 0.3
```

### Config Bridge (tui/config_manager.py)
`get_pipeline_overrides()` maps GUI config → SDK dotted overrides. Must include:
- `pipeline.ocr_api.model`
- `pipeline.ocr_api.api_path`
- `pipeline.ocr_api.verify_ssl`

Without these, the SDK uses wrong defaults (model: `glm-ocr`, path: `/v1/chat/completions`).

## Critical Files

| File | Purpose |
|------|---------|
| `gui/server.py` | FastAPI app factory — all API routes, server control, sandbox install |
| `gui/static/app.js` | All frontend logic — upload, SSE, auto-start, live preview, server logs |
| `gui/static/style.css` | Dark terminal theme, server bar, pipeline stages, log panels |
| `gui/templates/index.html` | Main page layout (server bar + upload + pipeline + logs + output) |
| `gui/templates/settings.html` | Advanced settings (mode, port, thresholds, server install/start) |
| `gui/pipeline_worker.py` | Background thread running GlmOcr pipeline with progress tracking |
| `gui/gui_config.yaml` | GUI-specific defaults (port 8090, MLX model, etc.) |
| `tui/config_manager.py` | Config bridge: YAML → SDK kwargs + dotted overrides |
| `glmocr/config.yaml` | SDK defaults (layout model path, thresholds, prompts) |
| `ocr_to_markdown.py` | CLI script: PDF → markdown with HTML table conversion |
| `ocr_markdown_pipeline.py` | CLI script: batch PDF processing with custom formatting |

## Platform Notes

### macOS (Apple Silicon M-series)
- Use MLX-VLM (not vLLM — requires CUDA/Linux)
- Install: `pip install git+https://github.com/Blaizzy/mlx-vlm.git`
- Model runs on Metal GPU, ~1.8GB VRAM
- First request downloads model + compiles Metal shaders (slow)
- Subsequent requests are fast

### Linux (NVIDIA GPU)
- Use vLLM with Docker: `docker pull vllm/vllm-openai:latest`
- Or sandbox install: `.server_venvs/vllm/`

### Port Convention
- GUI: port 8080
- OCR server (MLX/vLLM): port 8090
- Never use same port for both

## Common Operations

```bash
# Start GUI
.venv/bin/python -m gui --port 8080

# CLI: OCR a PDF (MaaS mode)
export ZHIPU_API_KEY=sk-xxx
python ocr_to_markdown.py document.pdf

# CLI: OCR with local MLX server
python ocr_to_markdown.py document.pdf --mode selfhosted --host localhost --port 8090

# Batch processing
python ocr_markdown_pipeline.py --batch-dir ./documents --output-dir ./results

# Check server health
curl http://localhost:8080/api/health

# Auto-start server
curl -X POST http://localhost:8080/api/auto-start
```

## SSE Progress Events
The `/api/progress/{task_id}` endpoint sends named SSE events:
- `event: progress` — pipeline state updates (stage, pages, regions, partial markdown)
- `event: done` — task completed or errored
- Heartbeat every ~10s to prevent browser timeout
- Frontend auto-reconnects on disconnect and checks if task completed while disconnected

## Dependencies
- Python 3.10+ with venv
- `pip install glmocr` (or `pip install -e .` from source)
- `pip install 'glmocr[selfhosted]'` for layout detection (torch, torchvision, opencv-python, transformers)
- GUI: `pip install fastapi uvicorn jinja2 sse-starlette` (included in project deps)
