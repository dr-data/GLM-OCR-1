"""FastAPI application for the GLM-OCR web GUI."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import jinja2
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from starlette.responses import StreamingResponse

# Ensure project root is importable.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tui.config_manager import ConfigManager, GUI_SETTINGS  # noqa: E402

from gui.pipeline_worker import PipelineWorker, TaskState  # noqa: E402

_GUI_DIR = Path(__file__).resolve().parent


def create_app(config_path: Optional[str] = None) -> FastAPI:
    """Application factory."""

    app = FastAPI(title="GLM-OCR Web GUI")

    # --- Shared state -----------------------------------------------------------
    config = ConfigManager(config_path)
    worker = PipelineWorker(config)
    tasks: dict[str, TaskState] = {}
    server_procs: dict[str, subprocess.Popen] = {}

    # Sandbox directory for isolated server installs.
    _SANDBOX_DIR = Path(_PROJECT_ROOT) / ".server_venvs"

    def _sandbox_python(srv_type: str) -> Path:
        """Return the Python binary inside a server's sandbox venv."""
        return _SANDBOX_DIR / srv_type / "bin" / "python"

    # Server launch commands and metadata.
    # Each server uses a sandboxed virtualenv so packages don't pollute the
    # project environment.  vLLM also supports Docker for Linux/CUDA hosts.
    _SERVER_META = {
        "vllm": {
            "cmd": [
                str(_sandbox_python("vllm")), "-m", "vllm.entrypoints.openai.api_server",
                "--model", "zai-org/GLM-OCR",
                "--allowed-local-media-path", "/",
                "--port", "{port}",
                "--speculative-config", '{"method": "mtp", "num_speculative_tokens": 1}',
                "--served-model-name", "glm-ocr",
            ],
            "docker_cmd": [
                "docker", "run", "--rm", "--gpus", "all",
                "-p", "{port}:{port}",
                "--name", "glmocr-vllm",
                "vllm/vllm-openai:latest",
                "--model", "zai-org/GLM-OCR",
                "--port", "{port}",
                "--served-model-name", "glm-ocr",
            ],
            "check": "sandbox",
            "module": "vllm",
            "install_pip": "vllm",
            "install_docker": "docker pull vllm/vllm-openai:latest",
            "install": "pip install vllm",
            "label": "vLLM",
            "note_macos": "vLLM requires CUDA (Linux + NVIDIA GPU). On macOS, use Docker with a remote GPU host or use MLX-VLM instead.",
        },
        "mlx": {
            "cmd": [
                str(_sandbox_python("mlx")), "-m", "mlx_vlm.server",
                "--trust-remote-code",
                "--port", "{port}",
            ],
            "check": "sandbox",
            "module": "mlx_vlm",
            "install_pip": "git+https://github.com/Blaizzy/mlx-vlm.git",
            "install": "pip install git+https://github.com/Blaizzy/mlx-vlm.git",
            "label": "MLX-VLM (Apple Silicon)",
        },
    }

    def _check_server_available(srv_type: str) -> dict:
        """Check whether a server backend is installed in its sandbox."""
        meta = _SERVER_META.get(srv_type)
        if meta is None:
            return {"available": False, "reason": f"unknown server type: {srv_type}"}

        # Check sandbox venv.
        sandbox_py = _sandbox_python(srv_type)
        if sandbox_py.exists():
            # Verify the target module is importable inside the sandbox.
            module = meta.get("module", "")
            if module:
                try:
                    result = subprocess.run(
                        [str(sandbox_py), "-c", f"import {module}"],
                        capture_output=True, timeout=10,
                    )
                    if result.returncode == 0:
                        return {"available": True, "path": str(sandbox_py)}
                except (subprocess.TimeoutExpired, OSError):
                    pass

        # Check Docker as fallback for vLLM.
        if srv_type == "vllm" and shutil.which("docker"):
            try:
                result = subprocess.run(
                    ["docker", "images", "-q", "vllm/vllm-openai"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return {"available": True, "method": "docker"}
            except (subprocess.TimeoutExpired, OSError):
                pass

        return {
            "available": False,
            "reason": f"'{meta['label']}' not installed",
            "install": meta.get("install", ""),
        }

    # --- Static / templates -----------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(_GUI_DIR / "static")), name="static")
    _jinja_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_GUI_DIR / "templates")),
        autoescape=True,
    )

    import time as _time
    _cache_bust = str(int(_time.time()))

    def _render(template_name: str, **ctx) -> HTMLResponse:
        tmpl = _jinja_env.get_template(template_name)
        ctx.setdefault("cache_bust", _cache_bust)
        return HTMLResponse(tmpl.render(**ctx))

    # --- Page routes ------------------------------------------------------------
    @app.get("/")
    async def index():
        return _render("index.html")

    @app.get("/settings")
    async def settings_page():
        return _render(
            "settings.html",
            values=config.get_gui_values(),
            settings=GUI_SETTINGS,
            config_path=str(config.config_path),
        )

    @app.get("/files")
    async def files_page():
        return _render("files.html", config_path=str(config.config_path))

    # --- OCR output image serving -----------------------------------------------
    @app.get("/api/uploaded/{filename:path}")
    async def serve_uploaded(filename: str):
        """Serve uploaded files (PDFs/images) for preview."""
        output_dir = config.get_tui_setting("output_dir", "./output")
        upload_root = (Path(output_dir) / "uploads").resolve()
        file_path = (upload_root / filename).resolve()
        if not str(file_path).startswith(str(upload_root)):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if not file_path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(file_path))

    @app.get("/api/output-image/{stem}/{path:path}")
    async def output_image(stem: str, path: str):
        """Serve images from OCR output directories by filename stem."""
        output_dir = config.get_tui_setting("output_dir", "./output")
        output_root = Path(output_dir).resolve()
        img_path = (output_root / stem / path).resolve()
        # Security: ensure path is under the output directory
        if not str(img_path).startswith(str(output_root)):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if not img_path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(img_path))

    # --- API routes -------------------------------------------------------------
    @app.get("/api/regions/{task_id}")
    async def get_regions(task_id: str):
        """Return region bbox data for highlight overlay."""
        state = tasks.get(task_id)
        if state is None:
            return JSONResponse({"error": "unknown task"}, status_code=404)
        if not state.json_data:
            return JSONResponse({"regions": [], "pages": 0})
        import json as _json
        data = _json.loads(state.json_data)
        return JSONResponse({
            "regions": data,
            "pages": len(data),
        })

    _ALLOWED_EXTENSIONS = {
        ".pdf", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    }

    @app.post("/api/upload")
    async def upload(file: UploadFile):
        ext = Path(file.filename or "").suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            return JSONResponse(
                {"error": f"Unsupported file type '{ext}'. "
                          "Accepted: PDF, Word, images (png/jpg/tiff/bmp/webp)."},
                status_code=400,
            )

        output_dir = config.get_tui_setting("output_dir", "./output")
        upload_dir = Path(output_dir) / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)

        dest = upload_dir / file.filename
        content = await file.read()
        dest.write_bytes(content)

        task_id = uuid.uuid4().hex[:12]
        state = TaskState(
            task_id=task_id,
            filename=file.filename,
            file_path=str(dest.resolve()),
        )
        tasks[task_id] = state

        asyncio.create_task(worker.run(state))

        return JSONResponse({"task_id": task_id, "filename": file.filename})

    @app.get("/api/tasks")
    async def list_tasks():
        """Return all known tasks (active + recent) for reconnection."""
        result = []
        for tid, state in tasks.items():
            result.append({
                "task_id": tid,
                "filename": state.filename,
                "status": state.status,
                "stage": state.stage,
            })
        return JSONResponse(result)

    @app.get("/api/progress/{task_id}")
    async def progress(task_id: str):
        state = tasks.get(task_id)
        if state is None:
            return JSONResponse({"error": "unknown task"}, status_code=404)

        async def _stream():
            last_version = -1
            heartbeat_counter = 0
            while True:
                heartbeat_counter += 1
                if state.version != last_version:
                    last_version = state.version
                    yield {"event": "progress", "data": state.to_json()}
                    heartbeat_counter = 0
                elif heartbeat_counter >= 33:  # ~10s (33 * 0.3s)
                    yield {"event": "progress", "data": state.to_json()}
                    heartbeat_counter = 0
                if state.status in ("done", "error"):
                    yield {"event": "done", "data": state.to_json()}
                    break
                await asyncio.sleep(0.3)

        return EventSourceResponse(_stream())

    @app.get("/api/result/{task_id}")
    async def result(task_id: str):
        state = tasks.get(task_id)
        if state is None:
            return JSONResponse({"error": "unknown task"}, status_code=404)
        return JSONResponse(
            {
                "markdown": state.markdown,
                "output_path": state.output_path,
                "filename": state.filename,
            }
        )

    @app.post("/api/settings")
    async def update_settings(request: Request):
        body = await request.json()
        for key, value in body.items():
            config.update_setting(key, value)
        return JSONResponse({"ok": True})

    # --- Server control routes --------------------------------------------------

    # Store recent server output lines for debugging.
    server_logs: dict[str, list[str]] = {}
    _MAX_LOG_LINES = 100

    def _is_proc_alive(proc: subprocess.Popen) -> bool:
        return proc.poll() is None

    def _tail_server_output(srv_type: str, proc: subprocess.Popen) -> None:
        """Background reader that captures server stdout/stderr."""
        server_logs.setdefault(srv_type, [])
        try:
            for raw_line in iter(proc.stdout.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                buf = server_logs[srv_type]
                buf.append(line)
                if len(buf) > _MAX_LOG_LINES:
                    del buf[: len(buf) - _MAX_LOG_LINES]
        except (ValueError, OSError):
            pass  # pipe closed

    @app.get("/api/server/available")
    async def server_available():
        """Pre-flight check: report which server backends are installed."""
        result = {}
        for srv_type in _SERVER_META:
            result[srv_type] = await asyncio.to_thread(_check_server_available, srv_type)
        return JSONResponse(result)

    @app.post("/api/server/start")
    async def start_server(request: Request):
        body = await request.json()
        srv_type = body.get("type", "")
        port = body.get("port", 8090)

        meta = _SERVER_META.get(srv_type)
        if meta is None:
            return JSONResponse(
                {"error": f"Unknown server type: {srv_type}"},
                status_code=400,
            )

        # Pre-flight: check if the backend is actually installed.
        avail = await asyncio.to_thread(_check_server_available, srv_type)
        if not avail["available"]:
            hint = avail.get("install", "")
            msg = avail["reason"]
            if hint:
                msg += f"\n\nInstall with:\n  {hint}"
            return JSONResponse({"error": msg, "install": hint}, status_code=400)

        # Stop existing process of same type if running.
        if srv_type in server_procs and _is_proc_alive(server_procs[srv_type]):
            old_proc = server_procs[srv_type]
            old_proc.terminate()
            try:
                await asyncio.to_thread(old_proc.wait, timeout=5)
            except subprocess.TimeoutExpired:
                old_proc.kill()

        # Choose Docker or sandbox command depending on how it was installed.
        use_docker = avail.get("method") == "docker" and "docker_cmd" in meta
        base_cmd = meta["docker_cmd"] if use_docker else meta["cmd"]
        cmd = [c.replace("{port}", str(port)) for c in base_cmd]
        server_logs[srv_type] = []

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            server_procs[srv_type] = proc

            # Capture output in background for diagnostics.
            t = threading.Thread(
                target=_tail_server_output,
                args=(srv_type, proc),
                daemon=True,
            )
            t.start()

            # Auto-configure the SDK to use the local server.
            if srv_type == "mlx":
                config.update_setting("pipeline.maas.enabled", False)
                config.update_setting("pipeline.ocr_api.api_host", "localhost")
                config.update_setting("pipeline.ocr_api.api_port", port)
                config.update_setting("pipeline.ocr_api.model", "mlx-community/GLM-OCR-bf16")
                config.update_setting("pipeline.ocr_api.api_path", "/chat/completions")
            elif srv_type == "vllm":
                config.update_setting("pipeline.maas.enabled", False)
                config.update_setting("pipeline.ocr_api.api_host", "localhost")
                config.update_setting("pipeline.ocr_api.api_port", port)

            return JSONResponse(
                {"ok": True, "pid": proc.pid, "cmd": " ".join(cmd)}
            )
        except FileNotFoundError:
            hint = meta.get("install", "")
            return JSONResponse(
                {
                    "error": (
                        f"'{cmd[0]}' not found on PATH.\n\n"
                        f"Install with:\n  {hint}"
                    ),
                    "install": hint,
                },
                status_code=400,
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/server/stop")
    async def stop_server(request: Request):
        body = await request.json()
        srv_type = body.get("type", "")

        proc = server_procs.get(srv_type)
        if proc is None or not _is_proc_alive(proc):
            return JSONResponse({"ok": True, "status": "already stopped"})

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return JSONResponse({"ok": True, "status": "stopped"})

    @app.get("/api/server/status")
    async def server_status():
        """Return running state and availability for each server type."""
        import platform

        is_macos = platform.system() == "Darwin"
        result = {}
        for srv_type, meta in _SERVER_META.items():
            proc = server_procs.get(srv_type)
            running = proc is not None and _is_proc_alive(proc)
            if running:
                avail = {"available": True}
            else:
                avail = await asyncio.to_thread(_check_server_available, srv_type)
            has_docker = shutil.which("docker") is not None
            entry = {
                "running": running,
                "pid": proc.pid if running else None,
                "available": avail["available"],
                "install": meta.get("install", ""),
                "label": meta.get("label", srv_type),
                "docker_available": has_docker and "docker_cmd" in meta,
            }
            # Add platform note for servers that can't run locally.
            if is_macos and meta.get("note_macos"):
                entry["note"] = meta["note_macos"]
            result[srv_type] = entry
        return JSONResponse(result)

    @app.get("/api/server/logs/{srv_type}")
    async def server_log(srv_type: str):
        """Return recent stdout/stderr lines from a managed server."""
        lines = server_logs.get(srv_type, [])
        return JSONResponse({"type": srv_type, "lines": lines})

    # --- Server install routes ----------------------------------------------------

    _install_state: dict[str, dict] = {}

    def _run_cmd_with_log(cmd: list[str], state: dict) -> int:
        """Run a command, appending stdout lines to state['lines']. Returns exit code."""
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        for raw_line in iter(proc.stdout.readline, b""):
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            state["lines"].append(line)
        proc.wait()
        return proc.returncode

    def _run_sandbox_install(srv_type: str, meta: dict, state: dict, method: str) -> None:
        """Create a sandbox venv and install the server package into it."""
        try:
            if method == "docker":
                # Docker pull for vLLM.
                state["lines"].append(f"Pulling Docker image for {meta['label']}...")
                docker_cmd = meta.get("install_docker", "").split()
                if not docker_cmd:
                    raise RuntimeError("No docker install command configured")
                rc = _run_cmd_with_log(docker_cmd, state)
                avail = _check_server_available(srv_type)
                state["success"] = rc == 0
                state["return_code"] = rc
                state["available"] = avail.get("available", False)
                return

            # --- Sandbox venv install ---
            venv_dir = _SANDBOX_DIR / srv_type
            sandbox_py = _sandbox_python(srv_type)

            # Step 1: Create virtualenv if it doesn't exist.
            if not sandbox_py.exists():
                state["lines"].append(f"Creating sandbox virtualenv at {venv_dir}...")
                import venv
                venv.create(str(venv_dir), with_pip=True, clear=True)
                state["lines"].append("Sandbox virtualenv created.")

            if not sandbox_py.exists():
                raise RuntimeError(f"Failed to create virtualenv — {sandbox_py} not found")

            # Step 2: Upgrade pip in the sandbox.
            state["lines"].append("Upgrading pip in sandbox...")
            _run_cmd_with_log(
                [str(sandbox_py), "-m", "pip", "install", "--upgrade", "pip"],
                state,
            )

            # Step 3: Install the package.
            pkg = meta.get("install_pip", "")
            if not pkg:
                raise RuntimeError("No install_pip configured")

            state["lines"].append(f"Installing {pkg} into sandbox...")
            rc = _run_cmd_with_log(
                [str(sandbox_py), "-m", "pip", "install", pkg],
                state,
            )

            avail = _check_server_available(srv_type)
            state["success"] = rc == 0
            state["return_code"] = rc
            state["available"] = avail.get("available", False)

        except Exception as exc:
            state["success"] = False
            state["error"] = str(exc)
            state["available"] = False
        finally:
            state["installing"] = False
            state["done"] = True

    @app.post("/api/server/install")
    async def install_server(request: Request):
        """Start installing a server backend in a sandbox. Returns immediately."""
        body = await request.json()
        srv_type = body.get("type", "")
        method = body.get("method", "sandbox")  # "sandbox" or "docker"

        meta = _SERVER_META.get(srv_type)
        if meta is None:
            return JSONResponse(
                {"error": f"Unknown server type: {srv_type}"},
                status_code=400,
            )

        existing = _install_state.get(srv_type)
        if existing and existing.get("installing"):
            return JSONResponse(
                {"error": f"{meta['label']} installation already in progress"},
                status_code=409,
            )

        # Docker method: check Docker is available.
        if method == "docker":
            if not shutil.which("docker"):
                return JSONResponse(
                    {"error": "Docker not found on PATH. Install Docker first."},
                    status_code=400,
                )

        state: dict = {
            "installing": True,
            "done": False,
            "success": None,
            "available": None,
            "return_code": None,
            "error": None,
            "lines": [],
            "method": method,
        }
        _install_state[srv_type] = state

        t = threading.Thread(
            target=_run_sandbox_install,
            args=(srv_type, meta, state, method),
            daemon=True,
        )
        t.start()

        return JSONResponse({"ok": True, "method": method})

    @app.get("/api/server/install/status/{srv_type}")
    async def install_status(srv_type: str):
        """Return current install progress for polling."""
        state = _install_state.get(srv_type)
        if state is None:
            return JSONResponse(
                {"installing": False, "done": False, "lines": []}
            )
        return JSONResponse({
            "installing": state["installing"],
            "done": state["done"],
            "success": state["success"],
            "available": state["available"],
            "return_code": state["return_code"],
            "error": state["error"],
            "lines": state["lines"],
        })

    # --- Platform detection helper -----------------------------------------------

    def _detect_best_server() -> str | None:
        """Return the preferred server type for this platform, or None."""
        if platform.system() == "Darwin":
            return "mlx"
        if platform.system() == "Linux":
            # Prefer vLLM on Linux with NVIDIA GPU.
            if shutil.which("nvidia-smi"):
                return "vllm"
        return None

    def _model_loaded(srv_type: str) -> bool:
        """Check server logs for startup-complete markers."""
        lines = server_logs.get(srv_type, [])
        for line in reversed(lines):
            if "Application startup complete" in line:
                return True
        return False

    # --- Health & auto-start routes ---------------------------------------------

    @app.get("/api/health")
    async def health():
        """Quick status check for the frontend."""
        srv_type = _detect_best_server()

        # Find a running server (check preferred type first, then all).
        running_type = None
        running_proc = None
        check_order = ([srv_type] if srv_type else []) + [
            t for t in _SERVER_META if t != srv_type
        ]
        for t in check_order:
            proc = server_procs.get(t)
            if proc is not None and _is_proc_alive(proc):
                running_type = t
                running_proc = proc
                break

        if running_type:
            port = 8090  # default port
            return JSONResponse({
                "server_type": running_type,
                "running": True,
                "port": port,
                "available": True,
                "installing": bool(
                    _install_state.get(running_type, {}).get("installing")
                ),
                "model_loaded": _model_loaded(running_type),
            })

        # Check if port is already responding (server started externally).
        try:
            import urllib.request as _ur
            with _ur.urlopen(_ur.Request(
                "http://localhost:8090/v1/models", method="GET"
            ), timeout=2) as resp:
                if resp.status == 200:
                    t = srv_type or "mlx"
                    return JSONResponse({
                        "server_type": t,
                        "running": True,
                        "port": 8090,
                        "available": True,
                        "installing": False,
                        "model_loaded": True,
                    })
        except Exception:
            pass

        # Nothing running — report availability of the preferred type.
        effective_type = srv_type
        avail_info = {}
        if effective_type:
            avail_info = await asyncio.to_thread(
                _check_server_available, effective_type
            )

        installing = bool(
            _install_state.get(effective_type or "", {}).get("installing")
        )

        return JSONResponse({
            "server_type": effective_type,
            "running": False,
            "port": 8090,
            "available": avail_info.get("available", False),
            "installing": installing,
            "model_loaded": False,
        })

    @app.post("/api/auto-start")
    async def auto_start():
        """Idempotent endpoint: ensure a server is running (install/start as needed)."""
        default_port = 8090

        # 1. Check if any server is already running (tracked process OR port responding).
        for t in _SERVER_META:
            proc = server_procs.get(t)
            if proc is not None and _is_proc_alive(proc):
                return JSONResponse({
                    "status": "running",
                    "server_type": t,
                    "port": default_port,
                    "message": f"{_SERVER_META[t]['label']} server is running on port {default_port}",
                })

        # 1b. Check if port is already responding (e.g. server started externally).
        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://localhost:{default_port}/v1/models", method="GET"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    srv_type = _detect_best_server() or "mlx"
                    return JSONResponse({
                        "status": "running",
                        "server_type": srv_type,
                        "port": default_port,
                        "message": f"Server already responding on port {default_port}",
                    })
        except Exception:
            pass

        # 2. Detect best server type for this platform.
        srv_type = _detect_best_server()
        if not srv_type:
            return JSONResponse({
                "status": "unavailable",
                "server_type": None,
                "port": default_port,
                "message": "No compatible server backend detected for this platform",
            })

        meta = _SERVER_META[srv_type]

        # 3. If an install is already in progress, report that.
        existing_install = _install_state.get(srv_type)
        if existing_install and existing_install.get("installing"):
            return JSONResponse({
                "status": "installing",
                "server_type": srv_type,
                "port": default_port,
                "message": f"{meta['label']} installation in progress",
            })

        # 4. Check if backend is installed.
        avail = await asyncio.to_thread(_check_server_available, srv_type)

        if not avail["available"]:
            # Trigger sandbox install (same logic as /api/server/install).
            method = "sandbox"
            state: dict = {
                "installing": True,
                "done": False,
                "success": None,
                "available": None,
                "return_code": None,
                "error": None,
                "lines": [],
                "method": method,
            }
            _install_state[srv_type] = state

            t = threading.Thread(
                target=_run_sandbox_install,
                args=(srv_type, meta, state, method),
                daemon=True,
            )
            t.start()

            return JSONResponse({
                "status": "installing",
                "server_type": srv_type,
                "port": default_port,
                "message": f"Installing {meta['label']} into sandbox",
            })

        # 5. Installed but not running → start the server.
        use_docker = avail.get("method") == "docker" and "docker_cmd" in meta
        base_cmd = meta["docker_cmd"] if use_docker else meta["cmd"]
        cmd = [c.replace("{port}", str(default_port)) for c in base_cmd]
        server_logs[srv_type] = []

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            server_procs[srv_type] = proc

            log_thread = threading.Thread(
                target=_tail_server_output,
                args=(srv_type, proc),
                daemon=True,
            )
            log_thread.start()

            # Auto-configure SDK settings (same as start_server).
            if srv_type == "mlx":
                config.update_setting("pipeline.maas.enabled", False)
                config.update_setting("pipeline.ocr_api.api_host", "localhost")
                config.update_setting("pipeline.ocr_api.api_port", default_port)
                config.update_setting("pipeline.ocr_api.model", "mlx-community/GLM-OCR-bf16")
                config.update_setting("pipeline.ocr_api.api_path", "/chat/completions")
            elif srv_type == "vllm":
                config.update_setting("pipeline.maas.enabled", False)
                config.update_setting("pipeline.ocr_api.api_host", "localhost")
                config.update_setting("pipeline.ocr_api.api_port", default_port)

            return JSONResponse({
                "status": "starting",
                "server_type": srv_type,
                "port": default_port,
                "message": f"Starting {meta['label']} on port {default_port}",
            })
        except Exception as e:
            return JSONResponse({
                "status": "unavailable",
                "server_type": srv_type,
                "port": default_port,
                "message": f"Failed to start {meta['label']}: {e}",
            })

    # ── File Explorer API ────────────────────────────

    @app.get("/api/files")
    async def list_files():
        output_dir = Path(config.get_tui_setting("output_dir", "./output"))
        uploads_dir = output_dir / "uploads"
        result = []
        if not output_dir.exists():
            return JSONResponse(result)
        for d in sorted(output_dir.iterdir()):
            if not d.is_dir() or d.name == "uploads":
                continue
            entry: dict = {"name": d.name, "files": [], "has_images": False}
            for ext in (".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx",
                        ".tif", ".tiff", ".bmp", ".webp"):
                candidate = uploads_dir / (d.name + ext)
                if candidate.exists():
                    entry["input_file"] = candidate.name
                    break
            for f in sorted(d.iterdir()):
                if f.is_file() and not f.name.endswith("_model.json"):
                    entry["files"].append({"name": f.name, "size": f.stat().st_size})
                elif f.is_dir() and f.name == "imgs":
                    entry["has_images"] = True
                    entry["images"] = [
                        img.name for img in sorted(f.iterdir()) if img.is_file()
                    ]
            result.append(entry)
        return JSONResponse(result)

    @app.get("/api/files/{stem}/zip")
    async def download_zip(stem: str):
        output_dir = Path(config.get_tui_setting("output_dir", "./output"))
        folder = output_dir / stem
        if not folder.exists() or not folder.is_dir():
            return JSONResponse({"error": "Not found"}, status_code=404)
        uploads_dir = output_dir / "uploads"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in folder.rglob("*"):
                if f.is_file() and not f.name.endswith("_model.json"):
                    zf.write(f, f"{stem}/{f.relative_to(folder)}")
            for ext in (".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx"):
                candidate = uploads_dir / (stem + ext)
                if candidate.exists():
                    zf.write(candidate, f"{stem}/input/{candidate.name}")
                    break
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{stem}.zip"'},
        )

    @app.get("/api/files/{stem}/{path:path}")
    async def get_explorer_file(stem: str, path: str):
        output_dir = Path(config.get_tui_setting("output_dir", "./output"))
        file_path = output_dir / stem / path
        if not file_path.exists() or not file_path.is_file():
            return JSONResponse({"error": "Not found"}, status_code=404)
        try:
            file_path.resolve().relative_to(output_dir.resolve())
        except ValueError:
            return JSONResponse({"error": "Invalid path"}, status_code=403)
        return FileResponse(file_path)

    return app
