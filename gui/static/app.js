/* GLM-OCR Web GUI — Vanilla JS */

(function () {
    "use strict";

    var STAGE_NAMES = ["PDF", "Layout", "OCR", "MD"];
    var STAGE_KEYS = ["pdf_input", "layout", "ocr", "markdown"];

    // ── DOM refs ──────────────────────────────────────
    var logContent = document.getElementById("log-content");
    var zone = document.getElementById("upload-zone");
    var fileInput = document.getElementById("file-input");
    var uploadStatus = document.getElementById("upload-status");
    var serverIndicator = document.getElementById("server-indicator");
    var serverStatusText = document.getElementById("server-status-text");
    var pipelineSection = document.getElementById("pipeline-section");
    var logSection = document.getElementById("log-section");
    var outputSection = document.getElementById("output-section");
    var outputPreview = document.getElementById("output-preview");
    var mdPreview = document.getElementById("md-preview");
    var currentTaskId = null;
    var currentFileStem = "";
    var currentMarkdown = "";

    // ── Logging ────────────────────────────────────────
    var _logUserClosed = false;
    (function () {
        var details = document.getElementById("log-details");
        if (details) {
            details.addEventListener("toggle", function () {
                if (!details.open) _logUserClosed = true;
            });
        }
    })();

    function log(msg, level) {
        if (!logContent) return;
        level = level || "info";
        // Auto-open on first entry, but never reopen after user closes
        if (!_logUserClosed) {
            var details = document.getElementById("log-details");
            if (details && !details.open) details.open = true;
        }
        var ts = new Date().toLocaleTimeString();
        var el = document.createElement("div");
        el.className = "log-entry " + level;
        el.textContent = ts + "  " + msg;
        logContent.appendChild(el);
        logContent.scrollTop = logContent.scrollHeight;
    }

    // ── Server Status Bar ─────────────────────────────
    function setServerBar(state, text) {
        if (serverIndicator) {
            serverIndicator.className = "indicator " + state;
        }
        if (serverStatusText) {
            serverStatusText.textContent = text;
        }
    }

    var btnServerStart = document.getElementById("btn-server-start");

    function updateStartButton(running, available) {
        if (!btnServerStart) return;
        if (running) {
            btnServerStart.classList.remove("hidden");
            btnServerStart.disabled = false;
            btnServerStart.textContent = "Stop";
            btnServerStart.setAttribute("data-action", "stop");
        } else if (available) {
            btnServerStart.classList.remove("hidden");
            btnServerStart.disabled = false;
            btnServerStart.textContent = "Start";
            btnServerStart.setAttribute("data-action", "start");
        } else {
            btnServerStart.classList.add("hidden");
        }
    }

    function checkHealth() {
        setServerBar("checking", "Checking server...");
        fetch("/api/health")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var label = data.server_type === "vllm" ? "vLLM" : "MLX-VLM";
                if (data.running) {
                    setServerBar("running", label + " \u25cf Running (port " + data.port + ")");
                    updateStartButton(true, true);
                } else if (data.available) {
                    setServerBar("stopped", label + " \u25cf Installed (stopped)");
                    updateStartButton(false, true);
                } else {
                    setServerBar("not-installed", "Not installed \u2014 will auto-install on first upload");
                    updateStartButton(false, false);
                }
            })
            .catch(function () {
                setServerBar("not-installed", "Server unavailable");
                updateStartButton(false, false);
            });
    }

    if (btnServerStart) {
        btnServerStart.addEventListener("click", function () {
            var action = btnServerStart.getAttribute("data-action") || "start";
            btnServerStart.disabled = true;
            if (action === "stop") {
                btnServerStart.textContent = "Stopping\u2026";
                fetch("/api/server/stop", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ type: "mlx" }),
                })
                .then(function () { setTimeout(checkHealth, 1000); })
                .catch(function () { setTimeout(checkHealth, 1000); });
            } else {
                btnServerStart.textContent = "Starting\u2026";
                setServerBar("starting", "Starting server\u2026");
                fetch("/api/auto-start", { method: "POST" })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (data.status === "running") {
                            checkHealth();
                        } else {
                            pollHealthUntilRunning(function () { checkHealth(); });
                        }
                    })
                    .catch(function () {
                        setServerBar("stopped", "Failed to start");
                        updateStartButton(false, true);
                    });
            }
        });
    }

    // Check health on page load
    if (serverIndicator) checkHealth();

    // ── Main-page server log streaming ───────────────
    var _mainLogPoll = null;
    var _mainLogSeen = 0;

    function startMainServerLogPoll() {
        if (logSection) logSection.classList.remove("hidden");
        _mainLogSeen = 0;
        _pollMainServerLogs();
    }

    function _pollMainServerLogs() {
        _mainLogPoll = setTimeout(function () {
            fetch("/api/server/status")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var type = null;
                if (data.mlx && data.mlx.running) type = "mlx";
                else if (data.vllm && data.vllm.running) type = "vllm";
                if (!type) { _pollMainServerLogs(); return; }

                return fetch("/api/server/logs/" + type)
                .then(function (r) { return r.json(); })
                .then(function (logData) {
                    if (logData.lines && logData.lines.length > _mainLogSeen) {
                        for (var i = _mainLogSeen; i < logData.lines.length; i++) {
                            log("[server] " + logData.lines[i], "info");
                        }
                        _mainLogSeen = logData.lines.length;
                    }
                    _pollMainServerLogs();
                });
            })
            .catch(function () { _pollMainServerLogs(); });
        }, 3000);
    }

    function stopMainServerLogPoll() {
        if (_mainLogPoll) { clearTimeout(_mainLogPoll); _mainLogPoll = null; }
    }

    // ── Upload Handling ─────────────────────────────
    if (zone && fileInput) {
        zone.addEventListener("click", function () { fileInput.click(); });

        fileInput.addEventListener("change", function () {
            if (fileInput.files.length) handleFiles(fileInput.files);
        });

        zone.addEventListener("dragover", function (e) {
            e.preventDefault();
            zone.classList.add("dragover");
        });

        zone.addEventListener("dragleave", function () {
            zone.classList.remove("dragover");
        });

        zone.addEventListener("drop", function (e) {
            e.preventDefault();
            zone.classList.remove("dragover");
            if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
        });
    }

    var ALLOWED_EXTENSIONS = [
        ".pdf", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ];

    function isAllowedFile(file) {
        var name = (file.name || "").toLowerCase();
        return ALLOWED_EXTENSIONS.some(function (ext) { return name.endsWith(ext); });
    }

    function handleFiles(files) {
        var accepted = [];
        var rejected = [];
        for (var i = 0; i < files.length; i++) {
            if (isAllowedFile(files[i])) {
                accepted.push(files[i]);
            } else {
                rejected.push(files[i].name);
            }
        }
        if (rejected.length > 0) {
            var msg = "Unsupported file(s): " + rejected.join(", ")
                + "\nAccepted: PDF, Word (.doc/.docx), images (.png/.jpg/.tiff/.bmp/.webp)";
            if (uploadStatus) uploadStatus.textContent = msg;
            log(msg, "error");
        }
        if (accepted.length === 0) return;

        if (accepted.length === 1) {
            document.getElementById("batch-section").classList.add("hidden");
            uploadSingleFile(accepted[0]);
        } else {
            if (pipelineSection) pipelineSection.classList.remove("hidden");
            if (logSection) logSection.classList.remove("hidden");
            document.getElementById("batch-section").classList.remove("hidden");
            uploadBatch(accepted);
        }
    }

    // ── Retry support ───────────────────────────────
    var _lastFile = null;
    var retryBtn = document.getElementById("btn-retry");
    if (retryBtn) {
        retryBtn.addEventListener("click", function () {
            retryBtn.classList.add("hidden");
            if (_lastFile) {
                uploadSingleFile(_lastFile);
            }
        });
    }

    function showRetryButton() {
        if (retryBtn) retryBtn.classList.remove("hidden");
    }

    // ── Auto-Start + Single File Upload ────────────────
    function uploadSingleFile(file) {
        _lastFile = file;
        if (uploadStatus) uploadStatus.textContent = "Uploading " + file.name + "...";

        // Show pipeline + log sections
        if (pipelineSection) pipelineSection.classList.remove("hidden");
        if (logSection) logSection.classList.remove("hidden");

        // Reset pipeline stages
        for (var i = 0; i < 4; i++) {
            var box = document.getElementById("stage-" + i);
            if (box) {
                box.className = "stage-box idle";
                var statusEl = box.querySelector(".status");
                if (statusEl) statusEl.textContent = "IDLE";
            }
        }
        // Reset progress bars
        var pageFill = document.getElementById("progress-fill");
        var pageLabel = document.getElementById("progress-text");
        var regionFill = document.getElementById("region-progress-fill");
        var regionLabel = document.getElementById("region-progress-text");
        var regionStats = document.getElementById("region-progress-stats");
        if (pageFill) pageFill.style.width = "0%";
        if (pageLabel) pageLabel.textContent = "waiting";
        if (regionFill) regionFill.style.width = "0%";
        if (regionLabel) regionLabel.textContent = "";
        if (regionStats) regionStats.textContent = "";

        // Allow log auto-open for this new task
        _logUserClosed = false;

        // Hide output from previous run
        if (outputSection) outputSection.classList.add("hidden");
        if (outputPreview) outputPreview.textContent = "";

        log("Uploading: " + file.name);

        // Show PDF/image preview immediately from local file
        if (outputSection) outputSection.classList.remove("hidden");
        var ext = file.name.split(".").pop().toLowerCase();
        if (ext === "pdf" && typeof pdfjsLib !== "undefined") {
            loadPdf(URL.createObjectURL(file));
            var panel = document.getElementById("pdf-panel");
            if (panel) panel.style.display = "";
        } else if (["png","jpg","jpeg","tif","tiff","bmp","webp"].indexOf(ext) >= 0) {
            var panel = document.getElementById("pdf-panel");
            if (panel) panel.style.display = "";
            var img = new Image();
            img.onload = function () {
                if (pdfCanvas) {
                    var maxW = pdfCanvasWrap ? pdfCanvasWrap.clientWidth - 20 : 500;
                    var scale = Math.min(maxW / img.width, 1);
                    pdfCanvas.width = img.width * scale;
                    pdfCanvas.height = img.height * scale;
                    pdfCanvas.getContext("2d").drawImage(img, 0, 0, pdfCanvas.width, pdfCanvas.height);
                }
            };
            img.src = URL.createObjectURL(file);
        }

        // Step 1: Auto-start server
        setServerBar("starting", "Preparing server...");
        log("Auto-starting server...");

        fetch("/api/auto-start", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === "running") {
                    setServerBar("running", "MLX-VLM \u25cf Ready");
                    log("Server ready");
                    doUpload(file);
                } else if (data.status === "starting") {
                    setServerBar("starting", "Starting server...");
                    log("Starting server, please wait...");
                    pollHealthUntilRunning(function () { doUpload(file); });
                } else if (data.status === "installing") {
                    setServerBar("installing", "Installing MLX-VLM...");
                    log("Installing MLX-VLM, this may take a few minutes...");
                    pollInstallThenStart(function () { doUpload(file); });
                } else {
                    setServerBar("not-installed", "Auto-start failed");
                    log("Auto-start error: " + (data.error || "unknown"), "error");
                    if (uploadStatus) uploadStatus.textContent = "Error: server not available";
                    showRetryButton();
                }
            })
            .catch(function (err) {
                setServerBar("not-installed", "Server unavailable");
                log("Auto-start failed: " + err.message, "error");
                if (uploadStatus) uploadStatus.textContent = "Error: " + err.message;
            });
    }

    function pollHealthUntilRunning(callback) {
        setTimeout(function () {
            fetch("/api/health")
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.server_running) {
                        setServerBar("running", "MLX-VLM \u25cf Ready");
                        log("Server is ready");
                        callback();
                    } else {
                        pollHealthUntilRunning(callback);
                    }
                })
                .catch(function () {
                    pollHealthUntilRunning(callback);
                });
        }, 2000);
    }

    function pollInstallThenStart(callback) {
        setTimeout(function () {
            fetch("/api/server/install/status/mlx")
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    // Stream install log lines
                    if (data.lines) {
                        for (var i = 0; i < data.lines.length; i++) {
                            log("[install] " + data.lines[i], "info");
                        }
                    }
                    if (data.done) {
                        if (data.success) {
                            log("Installation complete, starting server...");
                            setServerBar("starting", "Starting server...");
                            // Now auto-start again
                            fetch("/api/auto-start", { method: "POST" })
                                .then(function (r) { return r.json(); })
                                .then(function (startData) {
                                    if (startData.status === "running") {
                                        setServerBar("running", "MLX-VLM \u25cf Ready");
                                        callback();
                                    } else {
                                        pollHealthUntilRunning(callback);
                                    }
                                })
                                .catch(function () {
                                    pollHealthUntilRunning(callback);
                                });
                        } else {
                            setServerBar("not-installed", "Installation failed");
                            log("Installation failed: " + (data.error || "unknown"), "error");
                        }
                    } else {
                        pollInstallThenStart(callback);
                    }
                })
                .catch(function () {
                    pollInstallThenStart(callback);
                });
        }, 2000);
    }

    // ── PDF.js Viewer ──────────────────────────
    var pdfDoc = null;
    var pdfCurrentPage = 1;
    var pdfTotalPages = 0;
    var pdfScale = 1.0;
    var pdfZoomLevel = 1.0;
    var pdfCanvas = document.getElementById("pdf-canvas");
    var pdfOverlay = document.getElementById("pdf-overlay");
    var pdfCanvasWrap = document.getElementById("pdf-canvas-wrap");
    var pdfPageInfo = document.getElementById("pdf-page-info");
    var pdfZoomInfo = document.getElementById("pdf-zoom-info");
    var pdfPrev = document.getElementById("pdf-prev");
    var pdfNext = document.getElementById("pdf-next");
    var pdfZoomIn = document.getElementById("pdf-zoom-in");
    var pdfZoomOut = document.getElementById("pdf-zoom-out");

    function loadPdf(url) {
        if (typeof pdfjsLib === "undefined") {
            console.error("PDF.js not loaded");
            return;
        }
        pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

        pdfjsLib.getDocument(url).promise.then(function (doc) {
            pdfDoc = doc;
            pdfTotalPages = doc.numPages;
            pdfCurrentPage = 1;
            updatePageInfo();
            renderPdfPage(pdfCurrentPage);
        }).catch(function (err) {
            console.error("PDF.js load error:", err);
        });
    }

    function renderPdfPage(pageNum) {
        if (!pdfDoc || !pdfCanvas) return;
        pdfDoc.getPage(pageNum).then(function (page) {
            var containerWidth = pdfCanvasWrap ? pdfCanvasWrap.clientWidth - 20 : 500;
            var containerHeight = pdfCanvasWrap ? pdfCanvasWrap.clientHeight - 20 : 700;
            var unscaledViewport = page.getViewport({ scale: 1 });
            var scaleByWidth = containerWidth / unscaledViewport.width;
            var scaleByHeight = containerHeight / unscaledViewport.height;
            var baseScale = Math.min(scaleByWidth, scaleByHeight);
            pdfScale = baseScale * pdfZoomLevel;
            var viewport = page.getViewport({ scale: pdfScale });

            pdfCanvas.width = viewport.width;
            pdfCanvas.height = viewport.height;

            var ctx = pdfCanvas.getContext("2d");
            page.render({ canvasContext: ctx, viewport: viewport }).promise.then(function () {
                // Position overlay exactly on top of the canvas
                // (canvas may be centered by flex, so read its actual offset)
                if (pdfOverlay && pdfCanvasWrap) {
                    var canvasRect = pdfCanvas.getBoundingClientRect();
                    var wrapRect = pdfCanvasWrap.getBoundingClientRect();
                    pdfOverlay.style.left = (canvasRect.left - wrapRect.left + pdfCanvasWrap.scrollLeft) + "px";
                    pdfOverlay.style.top = (canvasRect.top - wrapRect.top + pdfCanvasWrap.scrollTop) + "px";
                    pdfOverlay.style.width = pdfCanvas.width + "px";
                    pdfOverlay.style.height = pdfCanvas.height + "px";
                }
                drawPageRegions(pageNum - 1);
            });
        });
    }

    function updatePageInfo() {
        if (pdfPageInfo) {
            pdfPageInfo.textContent = pdfCurrentPage + " / " + pdfTotalPages;
        }
    }

    function goToPdfPage(n) {
        if (!pdfDoc) return;
        if (n < 1) n = 1;
        if (n > pdfTotalPages) n = pdfTotalPages;
        pdfCurrentPage = n;
        updatePageInfo();
        renderPdfPage(n);
    }

    if (pdfPrev) pdfPrev.addEventListener("click", function () { goToPdfPage(pdfCurrentPage - 1); });
    if (pdfNext) pdfNext.addEventListener("click", function () { goToPdfPage(pdfCurrentPage + 1); });

    function updateZoomInfo() {
        if (pdfZoomInfo) pdfZoomInfo.textContent = Math.round(pdfZoomLevel * 100) + "%";
    }
    if (pdfZoomIn) pdfZoomIn.addEventListener("click", function () {
        pdfZoomLevel = Math.min(pdfZoomLevel + 0.25, 3.0);
        updateZoomInfo();
        renderPdfPage(pdfCurrentPage);
    });
    if (pdfZoomOut) pdfZoomOut.addEventListener("click", function () {
        pdfZoomLevel = Math.max(pdfZoomLevel - 0.25, 0.5);
        updateZoomInfo();
        renderPdfPage(pdfCurrentPage);
    });

    // Region overlay drawing (called by highlight sync system)
    var currentPageRegions = {};

    function setRegionData(data) {
        currentPageRegions = {};
        if (!data) return;
        for (var p = 0; p < data.length; p++) {
            currentPageRegions[p] = (data[p] || []).map(function (r, i) {
                return {
                    bbox_2d: r.bbox_2d,
                    label: r.label || r.task_type,
                    content: r.content,
                    regionIdx: r.index != null ? r.index : i,
                };
            });
        }
        if (pdfDoc) drawPageRegions(pdfCurrentPage - 1);
    }

    function drawPageRegions(pageIdx) {
        if (!pdfOverlay) return;
        pdfOverlay.innerHTML = "";
        var regions = currentPageRegions[pageIdx];
        if (!regions || !pdfCanvas) return;

        var cw = pdfCanvas.width;
        var ch = pdfCanvas.height;

        regions.forEach(function (r) {
            if (!r.bbox_2d || r.bbox_2d.length < 4) return;
            var x1 = (r.bbox_2d[0] / 1000) * cw;
            var y1 = (r.bbox_2d[1] / 1000) * ch;
            var x2 = (r.bbox_2d[2] / 1000) * cw;
            var y2 = (r.bbox_2d[3] / 1000) * ch;

            var rect = document.createElement("div");
            rect.className = "region-rect";
            rect.style.left = x1 + "px";
            rect.style.top = y1 + "px";
            rect.style.width = (x2 - x1) + "px";
            rect.style.height = (y2 - y1) + "px";
            rect.setAttribute("data-page", pageIdx);
            rect.setAttribute("data-region", r.regionIdx);
            rect.title = (r.label || "region") + " — click to copy";

            // Click to copy region content
            (function (content) {
                rect.addEventListener("click", function () {
                    if (!content) return;
                    navigator.clipboard.writeText(content.trim()).then(function () {
                        rect.classList.add("copied");
                        setTimeout(function () { rect.classList.remove("copied"); }, 800);
                    });
                });
            })(r.content);

            pdfOverlay.appendChild(rect);
        });
    }

    function highlightPdfRegion(pageIdx, regionIdx) {
        if (pdfCurrentPage !== pageIdx + 1) {
            goToPdfPage(pageIdx + 1);
            setTimeout(function () { _activatePdfRect(regionIdx); }, 300);
        } else {
            _activatePdfRect(regionIdx);
        }
    }

    function _activatePdfRect(regionIdx) {
        if (!pdfOverlay) return;
        pdfOverlay.querySelectorAll(".region-rect.active").forEach(function (el) {
            el.classList.remove("active");
        });
        var target = pdfOverlay.querySelector('.region-rect[data-region="' + regionIdx + '"]');
        if (target) target.classList.add("active");
    }

    function clearPdfHighlight() {
        if (!pdfOverlay) return;
        pdfOverlay.querySelectorAll(".region-rect.active").forEach(function (el) {
            el.classList.remove("active");
        });
    }

    function showPdfPreview(filename) {
        var panel = document.getElementById("pdf-panel");
        if (filename) {
            loadPdf("/api/uploaded/" + encodeURIComponent(filename));
            if (panel) panel.style.display = "";
        }
    }

    function getOcrSettings() {
        var s = {};
        var dpi = document.getElementById("ocr-dpi");
        var threshold = document.getElementById("ocr-threshold");
        var format = document.getElementById("ocr-format");
        var maxTokens = document.getElementById("ocr-max-tokens");
        var polygon = document.getElementById("ocr-polygon");
        var unclip = document.getElementById("ocr-unclip");
        if (dpi) s["pipeline.page_loader.pdf_dpi"] = parseInt(dpi.value, 10);
        if (threshold) s["pipeline.layout.threshold"] = parseFloat(threshold.value);
        if (format) s["pipeline.page_loader.image_format"] = format.value;
        if (maxTokens) s["pipeline.page_loader.max_tokens"] = parseInt(maxTokens.value, 10);
        if (polygon) s["pipeline.layout.use_polygon"] = polygon.checked;
        if (unclip) s["pipeline.layout.layout_unclip_ratio"] = [parseFloat(unclip.value), parseFloat(unclip.value)];
        return s;
    }

    function doUpload(file) {
        var fd = new FormData();
        fd.append("file", file);
        fd.append("ocr_settings", JSON.stringify(getOcrSettings()));
        fetch("/api/upload", { method: "POST", body: fd })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.task_id) {
                    if (uploadStatus) uploadStatus.textContent = "Processing " + file.name + "...";
                    log("Task started: " + data.task_id);
                    startMainServerLogPoll();
                    // Show PDF preview and output section immediately
                    if (outputSection) outputSection.classList.remove("hidden");
                    showPdfPreview(data.filename || file.name);
                    connectSSE(data.task_id, null);
                } else {
                    if (uploadStatus) uploadStatus.textContent = "Error: " + (data.error || "upload failed");
                    log("Upload error: " + (data.error || "failed"), "error");
                    showRetryButton();
                }
            })
            .catch(function (err) {
                if (uploadStatus) uploadStatus.textContent = "Error: " + err.message;
                log("Upload error: " + err.message, "error");
            });
    }

    // ── Batch Upload ────────────────────────────────
    var batchResults = {};
    var batchProgress = {};
    var batchTasks = {};   // idx → {taskId, filename}
    var batchActive = -1;  // which batch item is shown in the main output panel
    var batchTotal = 0;
    var batchDone = 0;

    function uploadBatch(files) {
        var list = document.getElementById("batch-list");
        list.innerHTML = "";
        batchResults = {};
        batchProgress = {};
        batchTasks = {};
        batchActive = -1;
        batchTotal = files.length;
        batchDone = 0;

        // Reset global progress bars
        var pf = document.getElementById("progress-fill");
        var pl = document.getElementById("progress-text");
        var rf = document.getElementById("region-progress-fill");
        var rl = document.getElementById("region-progress-text");
        var rs = document.getElementById("region-progress-stats");
        if (pf) pf.style.width = "0%";
        if (pl) pl.textContent = "0/" + files.length + " files";
        if (rf) rf.style.width = "0%";
        if (rl) rl.textContent = "";
        if (rs) rs.textContent = "";
        if (uploadStatus) uploadStatus.textContent = "Uploading " + files.length + " files...";
        if (logSection) logSection.classList.remove("hidden");
        log("Batch upload: " + files.length + " files");

        // Auto-start server first, then upload all
        setServerBar("starting", "Preparing server...");
        fetch("/api/auto-start", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === "running") {
                    setServerBar("running", "MLX-VLM \u25cf Ready");
                    doBatchUpload(files, list);
                } else if (data.status === "starting") {
                    setServerBar("starting", "Starting server...");
                    pollHealthUntilRunning(function () { doBatchUpload(files, list); });
                } else if (data.status === "installing") {
                    setServerBar("installing", "Installing MLX-VLM...");
                    pollInstallThenStart(function () { doBatchUpload(files, list); });
                } else {
                    setServerBar("not-installed", "Auto-start failed");
                    if (uploadStatus) uploadStatus.textContent = "Error: server not available";
                }
            })
            .catch(function () {
                setServerBar("not-installed", "Server unavailable");
                if (uploadStatus) uploadStatus.textContent = "Error: server not available";
            });
    }

    // Per-batch-file state: {pdfDoc, currentPage, totalPages, zoomLevel, markdown}
    var batchFileState = {};

    function initBatchFileUI(idx) {
        var s = batchFileState[idx] = { pdfDoc: null, page: 1, total: 0, zoom: 1.0, markdown: "" };
        var canvas = document.getElementById("bp-canvas-" + idx);
        var wrap = document.getElementById("bp-wrap-" + idx);
        var overlay = document.getElementById("bp-overlay-" + idx);

        function render() {
            if (!s.pdfDoc || !canvas) return;
            s.pdfDoc.getPage(s.page).then(function (page) {
                var cw = (wrap && wrap.clientWidth > 40) ? wrap.clientWidth - 20 : 500;
                var ch = (wrap && wrap.clientHeight > 40) ? wrap.clientHeight - 20 : 500;
                var vp0 = page.getViewport({ scale: 1 });
                var base = Math.min(cw / vp0.width, ch / vp0.height);
                var sc = base * s.zoom;
                var vp = page.getViewport({ scale: sc });
                canvas.width = vp.width;
                canvas.height = vp.height;
                page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise.then(function () {
                    if (overlay && wrap) {
                        var cr = canvas.getBoundingClientRect();
                        var wr = wrap.getBoundingClientRect();
                        overlay.style.left = (cr.left - wr.left + wrap.scrollLeft) + "px";
                        overlay.style.top = (cr.top - wr.top + wrap.scrollTop) + "px";
                        overlay.style.width = canvas.width + "px";
                        overlay.style.height = canvas.height + "px";
                    }
                    drawBatchRegions(idx);
                });
            });
            var pi = document.getElementById("bp-page-" + idx);
            if (pi) pi.textContent = s.page + " / " + s.total;
            var zi = document.getElementById("bp-zoom-" + idx);
            if (zi) zi.textContent = Math.round(s.zoom * 100) + "%";
        }

        // Page nav
        var item = document.getElementById("batch-item-" + idx);
        if (item) {
            item.addEventListener("click", function (e) {
                var btn = e.target;
                if (btn.classList.contains("bp-prev")) { if (s.page > 1) { s.page--; render(); } }
                else if (btn.classList.contains("bp-next")) { if (s.page < s.total) { s.page++; render(); } }
                else if (btn.classList.contains("bp-zin")) { s.zoom = Math.min(s.zoom + 0.25, 3.0); render(); }
                else if (btn.classList.contains("bp-zout")) { s.zoom = Math.max(s.zoom - 0.25, 0.5); render(); }
                // Tabs
                else if (btn.classList.contains("bp-tab")) {
                    var tab = btn.getAttribute("data-tab");
                    item.querySelectorAll(".bp-tab").forEach(function (t) { t.classList.toggle("active", t.getAttribute("data-tab") === tab); });
                    ["preview", "raw", "fullmd"].forEach(function (t) {
                        var p = document.getElementById("bp-" + t + "-" + idx) || item.querySelector(".bp-panel-" + t);
                        if (p) p.classList.toggle("hidden", t !== tab);
                    });
                    if (tab === "fullmd") {
                        var el = document.getElementById("bp-fullpre-" + idx);
                        if (el && s.markdown) el.textContent = s.markdown;
                    }
                }
                // Copy
                else if (btn.classList.contains("bp-copy")) {
                    if (s.markdown) navigator.clipboard.writeText(s.markdown);
                }
            });
        }

        batchFileState[idx]._render = render;
    }

    function loadBatchPdf(idx, filename, blobUrl) {
        var url = blobUrl || "/api/uploaded/" + encodeURIComponent(filename);
        var s = batchFileState[idx];
        if (!s) return;
        if (typeof pdfjsLib === "undefined") return;
        pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
        pdfjsLib.getDocument(url).promise.then(function (doc) {
            s.pdfDoc = doc;
            s.total = doc.numPages;
            s.page = 1;
            // Render immediately; if canvas has no layout yet, retry shortly
            s._render();
            setTimeout(function () { s._render(); }, 300);
        }).catch(function (err) {
            console.error("Batch PDF load error for idx " + idx + ":", err);
        });
    }

    function drawBatchRegions(idx) {
        var overlay = document.getElementById("bp-overlay-" + idx);
        var canvas = document.getElementById("bp-canvas-" + idx);
        if (!overlay || !canvas) return;
        overlay.innerHTML = "";
        var s = batchFileState[idx];
        if (!s) return;
        var pageIdx = s.page - 1;
        var regions = (currentPageRegions._batch || {})[idx];
        if (!regions || !regions[pageIdx]) return;
        var cw = canvas.width, ch = canvas.height;
        regions[pageIdx].forEach(function (r, ri) {
            if (!r.bbox_2d || r.bbox_2d.length < 4) return;
            var rect = document.createElement("div");
            rect.className = "region-rect";
            rect.setAttribute("data-page", pageIdx);
            rect.setAttribute("data-region", ri);
            rect.style.left = (r.bbox_2d[0] / 1000 * cw) + "px";
            rect.style.top = (r.bbox_2d[1] / 1000 * ch) + "px";
            rect.style.width = ((r.bbox_2d[2] - r.bbox_2d[0]) / 1000 * cw) + "px";
            rect.style.height = ((r.bbox_2d[3] - r.bbox_2d[1]) / 1000 * ch) + "px";
            rect.title = (r.label || "region") + " — click to copy";
            (function (content) {
                rect.addEventListener("click", function () {
                    if (!content) return;
                    navigator.clipboard.writeText(content.trim()).then(function () {
                        rect.classList.add("copied");
                        setTimeout(function () { rect.classList.remove("copied"); }, 800);
                    });
                });
            })(r.content);
            overlay.appendChild(rect);
        });
    }

    function _renderMdHtml(md, fileStem) {
        if (typeof marked === "undefined") return md;
        var html = marked.parse(md);
        // Rewrite image paths: imgs/... → /api/output-image/{stem}/imgs/...
        var stem = fileStem || currentFileStem;
        if (stem) {
            html = html.replace(
                /src="(imgs\/[^"]+)"/g,
                'src="/api/output-image/' + encodeURIComponent(stem) + '/$1"'
            );
        }
        html = html.replace(/\$\$([\s\S]*?)\$\$/g, function (_, tex) {
            try { return typeof katex !== "undefined" ? katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false }) : "$$" + tex + "$$"; }
            catch (e) { return "$$" + tex + "$$"; }
        });
        html = html.replace(/\$([^\$\n]+?)\$/g, function (_, tex) {
            try { return typeof katex !== "undefined" ? katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false }) : "$" + tex + "$"; }
            catch (e) { return "$" + tex + "$"; }
        });
        return html;
    }

    function setBatchMarkdown(idx, md, taskId, filename) {
        var s = batchFileState[idx];
        if (!s) return;
        s.markdown = md;
        s.fileStem = filename ? filename.replace(/\.[^.]+$/, "") : "";
        // Preview tab — simple render (region-annotated rebuild happens in wireBatchRegionSync)
        var mdEl = document.getElementById("bp-md-" + idx);
        if (mdEl) mdEl.innerHTML = _renderMdHtml(md, s.fileStem);
        // Raw tab
        var rawEl = document.getElementById("bp-rawpre-" + idx);
        if (rawEl) rawEl.textContent = md;
        // Download
        var dl = document.getElementById("bp-dl-" + idx);
        if (dl) {
            var blob = new Blob([md], { type: "text/markdown" });
            dl.href = URL.createObjectURL(blob);
            if (filename) dl.download = filename.replace(/\.[^.]+$/, "") + ".md";
        }
    }

    // Rebuild per-file markdown from JSON regions (1:1 mapping) + wire hover sync
    function wireBatchRegionSync(idx) {
        var regions = (currentPageRegions._batch || {})[idx];
        if (!regions) return;
        var mdEl = document.getElementById("bp-md-" + idx);
        var overlay = document.getElementById("bp-overlay-" + idx);
        if (!mdEl) return;

        // Rebuild markdown preview: one div per region with data-page/data-region
        var container = document.createDocumentFragment();
        var pageKeys = Object.keys(regions).sort(function (a, b) { return a - b; });
        for (var pi = 0; pi < pageKeys.length; pi++) {
            var pageIdx = parseInt(pageKeys[pi], 10);
            var pageRegions = regions[pageIdx] || [];
            var section = document.createElement("div");
            section.className = "page-section";
            if (pageKeys.length > 1) {
                var label = document.createElement("div");
                label.className = "page-label";
                label.textContent = "Page " + (pageIdx + 1);
                section.appendChild(label);
            }
            for (var ri = 0; ri < pageRegions.length; ri++) {
                var r = pageRegions[ri];
                var content = r.content;
                if (!content || (typeof content === "string" && !content.trim())) continue;
                var block = document.createElement("div");
                block.className = "region-block";
                block.setAttribute("data-page", pageIdx);
                block.setAttribute("data-region", ri);
                var stem = batchFileState[idx] ? batchFileState[idx].fileStem : "";
                block.innerHTML = _renderMdHtml(content, stem);

                // Markdown → PDF hover
                (function (el, pg, region) {
                    el.addEventListener("mouseenter", function () {
                        el.classList.add("region-hover");
                        // Highlight PDF box: navigate to page if needed, then activate
                        var s = batchFileState[idx];
                        if (s && s.page !== pg + 1) {
                            s.page = pg + 1;
                            s._render();
                            setTimeout(function () { _activateBatchRect(idx, region); }, 300);
                        } else {
                            _activateBatchRect(idx, region);
                        }
                    });
                    el.addEventListener("mouseleave", function () {
                        el.classList.remove("region-hover");
                        _clearBatchRectHighlight(idx);
                    });
                    el.addEventListener("click", function () {
                        if (content) navigator.clipboard.writeText(content.trim()).then(function () {
                            el.classList.add("region-copied");
                            setTimeout(function () { el.classList.remove("region-copied"); }, 800);
                        });
                    });
                })(block, pageIdx, ri);

                section.appendChild(block);
            }
            container.appendChild(section);
        }
        mdEl.innerHTML = "";
        mdEl.appendChild(container);

        // PDF → markdown hover (event delegation on overlay)
        if (overlay && !overlay._batchSyncWired) {
            overlay._batchSyncWired = true;
            overlay.addEventListener("mouseenter", function (e) {
                var rect = e.target.closest(".region-rect");
                if (!rect) return;
                rect.classList.add("active");
                var pg = rect.getAttribute("data-page");
                var ri = rect.getAttribute("data-region");
                var mdBlock = mdEl.querySelector('.region-block[data-page="' + pg + '"][data-region="' + ri + '"]');
                if (mdBlock) {
                    mdBlock.classList.add("region-hover");
                    mdBlock.scrollIntoView({ behavior: "smooth", block: "center" });
                }
            }, true);
            overlay.addEventListener("mouseleave", function (e) {
                var rect = e.target.closest(".region-rect");
                if (!rect) return;
                rect.classList.remove("active");
                mdEl.querySelectorAll(".region-hover").forEach(function (el) {
                    el.classList.remove("region-hover");
                });
            }, true);
        }
    }

    function _activateBatchRect(idx, regionIdx) {
        var overlay = document.getElementById("bp-overlay-" + idx);
        if (!overlay) return;
        overlay.querySelectorAll(".region-rect.active").forEach(function (el) { el.classList.remove("active"); });
        var target = overlay.querySelector('.region-rect[data-region="' + regionIdx + '"]');
        if (target) target.classList.add("active");
    }

    function _clearBatchRectHighlight(idx) {
        var overlay = document.getElementById("bp-overlay-" + idx);
        if (!overlay) return;
        overlay.querySelectorAll(".region-rect.active").forEach(function (el) { el.classList.remove("active"); });
    }

    function doBatchUpload(files, list) {
        startMainServerLogPoll();
        for (var i = 0; i < files.length; i++) {
            (function (file, idx) {
                var details = document.createElement("details");
                details.className = "batch-item";
                details.id = "batch-item-" + idx;

                var summary = document.createElement("summary");
                summary.innerHTML =
                    '<span class="batch-filename">' + escapeHtml(file.name) + '</span>' +
                    '<span class="batch-stages">' +
                        STAGE_NAMES.map(function (n, j) {
                            return '<span class="batch-stage" id="bs-' + idx + '-' + j + '">' + n + '</span>';
                        }).join("") +
                    '</span>' +
                    '<span class="batch-status" id="bstat-' + idx + '">uploading</span>';
                details.appendChild(summary);

                // Per-file progress bar
                var barWrap = document.createElement("div");
                barWrap.className = "batch-progress-bar";
                barWrap.innerHTML =
                    '<div class="progress-bar-track"><div class="batch-fill" id="bfill-' + idx + '"></div></div>' +
                    '<span class="batch-progress-label" id="blabel-' + idx + '"></span>';
                details.appendChild(barWrap);

                // Full comparison view matching single-file UI
                var cv = document.createElement("div");
                cv.className = "batch-comparison comparison-view";
                cv.innerHTML =
                    // Left: PDF with controls
                    '<div class="compare-panel">' +
                        '<details class="compare-detail" open><summary>Input</summary>' +
                        '<div class="pdf-preview-container">' +
                            '<div class="pdf-controls">' +
                                '<button class="bp-prev" data-idx="' + idx + '" title="Previous">&laquo;</button>' +
                                '<span class="bp-page-info" id="bp-page-' + idx + '">- / -</span>' +
                                '<button class="bp-next" data-idx="' + idx + '" title="Next">&raquo;</button>' +
                                '<span class="pdf-controls-sep">|</span>' +
                                '<button class="bp-zout" data-idx="' + idx + '">-</button>' +
                                '<span class="bp-zoom-info" id="bp-zoom-' + idx + '">100%</span>' +
                                '<button class="bp-zin" data-idx="' + idx + '">+</button>' +
                            '</div>' +
                            '<div class="pdf-canvas-wrap" id="bp-wrap-' + idx + '">' +
                                '<canvas id="bp-canvas-' + idx + '"></canvas>' +
                                '<div class="pdf-overlay" id="bp-overlay-' + idx + '"></div>' +
                            '</div>' +
                        '</div>' +
                        '</details>' +
                    '</div>' +
                    // Right: Output with tabs
                    '<div class="compare-panel">' +
                        '<details class="compare-detail" open><summary>' +
                            '<span>Output</span>' +
                            '<span class="output-tabs-inline">' +
                                '<button class="tab active bp-tab" data-idx="' + idx + '" data-tab="preview">Preview</button>' +
                                '<button class="tab bp-tab" data-idx="' + idx + '" data-tab="raw">Raw</button>' +
                                '<button class="tab bp-tab" data-idx="' + idx + '" data-tab="fullmd">Full MD</button>' +
                            '</span>' +
                        '</summary>' +
                        '<div class="output-panel bp-panel-preview" id="bp-preview-' + idx + '">' +
                            '<div class="md-preview" id="bp-md-' + idx + '"></div>' +
                        '</div>' +
                        '<div class="output-panel hidden bp-panel-raw" id="bp-raw-' + idx + '">' +
                            '<pre class="output-preview" id="bp-rawpre-' + idx + '"></pre>' +
                        '</div>' +
                        '<div class="output-panel hidden bp-panel-fullmd" id="bp-fullmd-' + idx + '">' +
                            '<pre class="output-preview" id="bp-fullpre-' + idx + '"></pre>' +
                        '</div>' +
                        '<div class="output-actions">' +
                            '<button class="bp-copy" data-idx="' + idx + '">Copy</button>' +
                            '<a class="bp-dl" id="bp-dl-' + idx + '" href="#" download="output.md"><button type="button">Download .md</button></a>' +
                        '</div>' +
                        '</details>' +
                    '</div>';
                details.appendChild(cv);

                // Append to DOM and open FIRST so elements have layout
                list.appendChild(details);
                details.open = true;

                // Wire per-file PDF.js + controls + tabs (after DOM insert)
                initBatchFileUI(idx);

                // Load PDF/image preview immediately from local file
                (function (f, i) {
                    var ext = f.name.split(".").pop().toLowerCase();
                    if (ext === "pdf" && typeof pdfjsLib !== "undefined") {
                        var localUrl = URL.createObjectURL(f);
                        loadBatchPdf(i, null, localUrl);
                    } else if (["png","jpg","jpeg","tif","tiff","bmp","webp"].indexOf(ext) >= 0) {
                        var canvas = document.getElementById("bp-canvas-" + i);
                        if (canvas) {
                            var img = new Image();
                            img.onload = function () {
                                var wrap = document.getElementById("bp-wrap-" + i);
                                var maxW = wrap ? wrap.clientWidth - 20 : 500;
                                var scale = Math.min(maxW / img.width, 1);
                                canvas.width = img.width * scale;
                                canvas.height = img.height * scale;
                                canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
                            };
                            img.src = URL.createObjectURL(f);
                        }
                    }
                })(file, idx);

                var fd = new FormData();
                fd.append("file", file);

                fetch("/api/upload", { method: "POST", body: fd })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (data.task_id) {
                            batchTasks[idx] = { taskId: data.task_id, filename: data.filename || file.name };
                            log("Started: " + file.name + " (task " + data.task_id + ")");
                            setBatchStatus(idx, "processing", "running");

                            connectSSE(data.task_id, idx);
                        } else {
                            setBatchStatus(idx, data.error || "failed", "error");
                            log("Failed: " + file.name + " - " + (data.error || "upload failed"), "error");
                            batchCheckDone();
                        }
                    })
                    .catch(function (err) {
                        setBatchStatus(idx, "error", "error");
                        log("Failed: " + file.name + " - " + err.message, "error");
                        batchCheckDone();
                    });
            })(files[i], i);
        }
    }

    function setBatchStatus(idx, text, cls) {
        var el = document.getElementById("bstat-" + idx);
        if (el) {
            el.textContent = text;
            el.className = "batch-status " + (cls || "");
        }
    }

    function setBatchStage(idx, stageIdx, cls) {
        var el = document.getElementById("bs-" + idx + "-" + stageIdx);
        if (el) {
            el.className = "batch-stage " + (cls || "");
        }
    }

    function batchCheckDone() {
        batchDone++;
        if (uploadStatus) uploadStatus.textContent = batchDone + "/" + batchTotal + " files complete";
        if (batchDone >= batchTotal) {
            stopMainServerLogPoll();
            if (uploadStatus) uploadStatus.textContent = "Batch complete (" + batchTotal + " files)";
            log("Batch complete: " + batchTotal + " files processed");
            checkHealth();
        }
    }

    // ── SSE Progress ────────────────────────────────
    function connectSSE(taskId, batchIdx) {
        var source = new EventSource("/api/progress/" + taskId);
        var _lastLoggedStage = "";
        var _finished = false;

        function handleProgress(data) {
            if (batchIdx !== null && batchIdx !== undefined) {
                updateBatchPipeline(batchIdx, data);

                // Track per-file progress
                batchProgress[batchIdx] = {
                    pages_done: data.pages_done || 0,
                    pages_total: data.pages_total || 0,
                    regions_done: data.regions_done || 0,
                    regions_total: data.regions_total || 0,
                    regions_breakdown: data.regions_breakdown || "",
                };

                // Per-file progress bar
                var fileFill = document.getElementById("bfill-" + batchIdx);
                var fileLabel = document.getElementById("blabel-" + batchIdx);
                var pDone = data.pages_done || 0;
                var pTotal = data.pages_total || 0;
                if (fileFill) fileFill.style.width = (pTotal > 0 ? Math.round(pDone / pTotal * 100) : 0) + "%";
                if (fileLabel) fileLabel.textContent = pTotal > 0 ? pDone + "/" + pTotal + " pages" : (data.stage_detail || "");

                // Per-file markdown output (all tabs)
                if (data.markdown) {
                    setBatchMarkdown(batchIdx, data.markdown, data.task_id, data.filename);
                }

                // Streaming region boxes + sync
                if (data.partial_regions) {
                    try {
                        var pr = typeof data.partial_regions === "string"
                            ? JSON.parse(data.partial_regions) : data.partial_regions;
                        if (pr && pr.length) {
                            if (!currentPageRegions._batch) currentPageRegions._batch = {};
                            currentPageRegions._batch[batchIdx] = {};
                            for (var p = 0; p < pr.length; p++) {
                                currentPageRegions._batch[batchIdx][p] = (pr[p] || []).map(function (r) {
                                    return { bbox_2d: r.bbox_2d, label: r.label || r.task_type, content: r.content };
                                });
                            }
                            drawBatchRegions(batchIdx);
                            wireBatchRegionSync(batchIdx);
                        }
                    } catch (e) {}
                }

                // Aggregate global progress bars
                updateBatchTotalProgress();
            } else {
                updatePipeline(data);
                updateProgress(data);

                // Live markdown preview
                if (data.markdown) {
                    if (outputSection) outputSection.classList.remove("hidden");
                    if (outputPreview) outputPreview.textContent = data.markdown;
                    renderMarkdown(data.markdown, data.task_id, data.filename);
                }

                // Streaming region boxes on PDF overlay
                if (data.partial_regions) {
                    try {
                        var pr = typeof data.partial_regions === "string"
                            ? JSON.parse(data.partial_regions) : data.partial_regions;
                        if (pr && pr.length) {
                            // Update region data and redraw
                            for (var p = 0; p < pr.length; p++) {
                                currentPageRegions[p] = (pr[p] || []).map(function (r, i) {
                                    return {
                                        bbox_2d: r.bbox_2d,
                                        label: r.label || r.task_type,
                                        content: r.content,
                                        regionIdx: r.index != null ? r.index : i,
                                    };
                                });
                            }
                            drawPageRegions(pdfCurrentPage - 1);
                        }
                    } catch (e) {}
                }
            }
            var detail = data.stage_detail || data.stage || "processing";
            var stats = "";
            if (data.pages_total > 0) {
                stats += " | pages: " + data.pages_done + "/" + data.pages_total;
            }
            if (data.regions_total > 0) {
                stats += " | regions: " + data.regions_done + "/" + data.regions_total;
            }
            if (data.regions_breakdown) {
                stats += " [" + data.regions_breakdown + "]";
            }
            // Update Layout stage box with region breakdown
            if (data.regions_breakdown) {
                var layoutStatus = document.querySelector("#stage-1 .status");
                if (layoutStatus) layoutStatus.textContent = data.regions_breakdown;
            }
            var stageKey = data.stage + ":" + data.status;
            if (stageKey !== _lastLoggedStage || stats) {
                _lastLoggedStage = stageKey;
                var fileTag = data.filename ? "[" + data.filename + "] " : "";
                log(fileTag + "[" + data.stage + "] " + detail + stats);
            }
        }

        function handleDone(data) {
            _finished = true;
            source.close();
            if (batchIdx !== null && batchIdx !== undefined) {
                if (data.status === "done") {
                    updateBatchPipeline(batchIdx, data);
                    setBatchStatus(batchIdx, "done", "done");
                    log("[" + taskId + "] Complete");
                    // Fill per-file bar to 100%
                    var fileFill = document.getElementById("bfill-" + batchIdx);
                    if (fileFill) fileFill.style.width = "100%";
                    // Fetch full result + region data for boxes
                    (function (bi, tid) {
                        var fn = batchTasks[bi] ? batchTasks[bi].filename : "";
                        fetch("/api/result/" + tid)
                            .then(function (r) { return r.json(); })
                            .then(function (result) {
                                if (result.markdown) setBatchMarkdown(bi, result.markdown, tid, fn);
                            }).catch(function () {});
                        // Load region data for bbox overlay
                        fetch("/api/regions/" + tid)
                            .then(function (r) { return r.json(); })
                            .then(function (data) {
                                if (data.regions && data.regions.length) {
                                    if (!currentPageRegions._batch) currentPageRegions._batch = {};
                                    currentPageRegions._batch[bi] = {};
                                    for (var p = 0; p < data.regions.length; p++) {
                                        currentPageRegions._batch[bi][p] = (data.regions[p] || []).map(function (r, i) {
                                            return { bbox_2d: r.bbox_2d, label: r.label || r.task_type, content: r.content };
                                        });
                                    }
                                    drawBatchRegions(bi);
                                    wireBatchRegionSync(bi);
                                }
                            }).catch(function () {});
                    })(batchIdx, taskId);
                } else {
                    setBatchStatus(batchIdx, data.error || "error", "error");
                    log("[" + taskId + "] Error: " + (data.error || "unknown"), "error");
                }
                batchResults[batchIdx] = { taskId: taskId, status: data.status };
                updateBatchTotalProgress();
                batchCheckDone();
            } else {
                stopMainServerLogPoll();
                if (data.status === "done") {
                    fetchResult(taskId);
                    log("[" + taskId + "] Complete");
                } else if (data.error) {
                    if (uploadStatus) uploadStatus.textContent = "Error: " + data.error;
                    log("[" + taskId + "] Error: " + data.error, "error");
                    showRetryButton();
                }
                checkHealth();
            }
        }

        source.addEventListener("progress", function (e) {
            handleProgress(JSON.parse(e.data));
        });

        source.addEventListener("done", function (e) {
            handleDone(JSON.parse(e.data));
        });

        source.onerror = function () {
            source.close();
            if (_finished) return;
            log("[" + taskId + "] SSE disconnected, checking status\u2026", "warning");
            fetch("/api/result/" + taskId)
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.markdown) {
                        handleDone({ status: "done" });
                    } else {
                        log("[" + taskId + "] Reconnecting\u2026", "warning");
                        connectSSE(taskId, batchIdx);
                    }
                })
                .catch(function () {
                    if (batchIdx !== null && batchIdx !== undefined) {
                        setBatchStatus(batchIdx, "disconnected", "error");
                        batchCheckDone();
                    } else {
                        stopMainServerLogPoll();
                        if (uploadStatus) uploadStatus.textContent = "Connection lost";
                    }
                    log("[" + taskId + "] Connection lost", "warning");
                });
        };
    }

    function updateBatchPipeline(idx, data) {
        var stageMap = { pdf_input: 0, layout: 1, ocr: 2, markdown: 3 };
        var current = stageMap[data.stage] !== undefined ? stageMap[data.stage] : -1;
        var errored = data.status === "error";

        for (var i = 0; i < 4; i++) {
            if (errored && i === current) {
                setBatchStage(idx, i, "error");
            } else if (i < current || (data.status === "done" && i <= current)) {
                setBatchStage(idx, i, "done");
            } else if (i === current) {
                setBatchStage(idx, i, "running");
            } else {
                setBatchStage(idx, i, "");
            }
        }
    }

    function updatePipeline(data) {
        var stageMap = { pdf_input: 0, layout: 1, ocr: 2, markdown: 3 };
        var current = stageMap[data.stage] !== undefined ? stageMap[data.stage] : -1;
        var errored = data.status === "error";
        for (var i = 0; i < 4; i++) {
            var box = document.getElementById("stage-" + i);
            if (!box) continue;
            var statusEl = box.querySelector(".status");
            box.className = "stage-box";
            if (errored && i === current) {
                box.classList.add("error");
                if (statusEl) statusEl.textContent = "ERROR";
            } else if (i < current || (data.status === "done" && i <= current)) {
                box.classList.add("done");
                if (statusEl) statusEl.textContent = "DONE";
            } else if (i === current) {
                box.classList.add("running");
                if (statusEl) statusEl.textContent = data.stage_detail || "RUNNING";
            } else {
                box.classList.add("idle");
                if (statusEl) statusEl.textContent = "IDLE";
            }
        }
    }

    function updateProgress(data) {
        // ── Bar 1: Pages ──
        var pageLabelEl = document.getElementById("progress-text");
        var pageFillEl = document.getElementById("progress-fill");

        var pagesDone = data.pages_done || 0;
        var pagesTotal = data.pages_total || 0;
        var pagePct = pagesTotal > 0 ? Math.round((pagesDone / pagesTotal) * 100) : 0;

        if (pageFillEl) pageFillEl.style.width = pagePct + "%";
        if (pageLabelEl) {
            pageLabelEl.textContent = pagesTotal > 0
                ? pagesDone + "/" + pagesTotal + " pages"
                : (data.stage_detail || "processing");
        }

        // ── Bar 2: Regions (OCR → Markdown) ──
        var regionLabelEl = document.getElementById("region-progress-text");
        var regionFillEl = document.getElementById("region-progress-fill");
        var regionStatsEl = document.getElementById("region-progress-stats");

        var regionsDone = data.regions_done || 0;
        var regionsTotal = data.regions_total || 0;
        var regionPct = regionsTotal > 0 ? Math.round((regionsDone / regionsTotal) * 100) : 0;

        if (regionFillEl) regionFillEl.style.width = regionPct + "%";
        if (regionLabelEl) {
            regionLabelEl.textContent = regionsTotal > 0
                ? regionsDone + "/" + regionsTotal + " regions"
                : "";
        }
        if (regionStatsEl) {
            regionStatsEl.textContent = data.regions_breakdown || "";
        }
    }

    function updateBatchTotalProgress() {
        var totalPages = 0, donePages = 0;
        var totalRegions = 0, doneRegions = 0;
        var breakdownParts = {};
        var filesDone = 0;

        for (var k in batchProgress) {
            var p = batchProgress[k];
            totalPages += p.pages_total;
            donePages += p.pages_done;
            totalRegions += p.regions_total;
            doneRegions += p.regions_done;
            if (p.regions_breakdown) {
                p.regions_breakdown.split(" ").forEach(function (part) {
                    var kv = part.split(":");
                    if (kv.length === 2) {
                        breakdownParts[kv[0]] = (breakdownParts[kv[0]] || 0) + parseInt(kv[1], 10);
                    }
                });
            }
        }
        for (var k in batchResults) {
            if (batchResults[k].status === "done") filesDone++;
        }

        // Pages bar — show files done / total + pages
        var pageFill = document.getElementById("progress-fill");
        var pageLabel = document.getElementById("progress-text");
        var pagePct = totalPages > 0 ? Math.round(donePages / totalPages * 100) : 0;
        if (pageFill) pageFill.style.width = pagePct + "%";
        if (pageLabel) {
            pageLabel.textContent = filesDone + "/" + batchTotal + " files"
                + (totalPages > 0 ? "  (" + donePages + "/" + totalPages + " pages)" : "");
        }

        // Regions bar
        var regionFill = document.getElementById("region-progress-fill");
        var regionLabel = document.getElementById("region-progress-text");
        var regionStats = document.getElementById("region-progress-stats");
        var regionPct = totalRegions > 0 ? Math.round(doneRegions / totalRegions * 100) : 0;
        if (regionFill) regionFill.style.width = regionPct + "%";
        if (regionLabel) regionLabel.textContent = totalRegions > 0 ? doneRegions + "/" + totalRegions + " regions" : "";
        if (regionStats) {
            var parts = [];
            ["text", "table", "formula", "skip"].forEach(function (lbl) {
                if (breakdownParts[lbl]) parts.push(lbl + ":" + breakdownParts[lbl]);
            });
            regionStats.textContent = parts.join(" ");
        }
    }

    // ── Markdown Rendering ───────────────────────────
    function renderMarkdown(md, taskId, filename) {
        if (!mdPreview || typeof marked === "undefined") return;
        currentMarkdown = md;
        currentTaskId = taskId || currentTaskId;
        if (filename) currentFileStem = filename.replace(/\.[^.]+$/, "");

        // Configure marked with highlight.js
        marked.setOptions({
            highlight: function (code, lang) {
                if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
                    return hljs.highlight(code, { language: lang }).value;
                }
                return code;
            },
            breaks: false,
            gfm: true,
        });

        // Render markdown to HTML
        var html = marked.parse(md);

        // Rewrite image paths: imgs/... → /api/output-image/{stem}/imgs/...
        if (currentFileStem) {
            html = html.replace(
                /src="(imgs\/[^"]+)"/g,
                'src="/api/output-image/' + encodeURIComponent(currentFileStem) + '/$1"'
            );
        }

        // Render LaTeX math blocks: $$ ... $$ and inline $ ... $
        html = html.replace(/\$\$([\s\S]*?)\$\$/g, function (_, tex) {
            try {
                return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false });
            } catch (e) { return "$$" + tex + "$$"; }
        });
        html = html.replace(/\$([^\$\n]+?)\$/g, function (_, tex) {
            try {
                return katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false });
            } catch (e) { return "$" + tex + "$"; }
        });

        // Wrap block elements with region markers for hover highlight
        mdPreview.innerHTML = html;
        annotateRegions(mdPreview);
    }

    // ── Region Annotation & Hover Highlight ─────────
    function annotateRegions(container) {
        // Split content by <hr> (page separators from "---" in markdown)
        var children = Array.from(container.childNodes);
        var pageIdx = 0;
        var regionIdx = 0;
        var currentPage = document.createElement("div");
        currentPage.className = "page-section";
        currentPage.setAttribute("data-page", pageIdx);

        var fragment = document.createDocumentFragment();

        children.forEach(function (node) {
            if (node.nodeType === 1 && node.tagName === "HR") {
                // Page break — finish current page, start new one
                if (currentPage.childNodes.length > 0) {
                    fragment.appendChild(currentPage);
                }
                pageIdx++;
                regionIdx = 0;
                currentPage = document.createElement("div");
                currentPage.className = "page-section";
                currentPage.setAttribute("data-page", pageIdx);
                return;
            }

            // Wrap block-level elements as hoverable regions
            if (node.nodeType === 1) {
                node.classList.add("region-block");
                node.setAttribute("data-page", pageIdx);
                node.setAttribute("data-region", regionIdx);
                regionIdx++;
            }
            currentPage.appendChild(node);
        });

        if (currentPage.childNodes.length > 0) {
            fragment.appendChild(currentPage);
        }

        container.innerHTML = "";
        container.appendChild(fragment);

        // Add page labels
        container.querySelectorAll(".page-section").forEach(function (section) {
            var pg = parseInt(section.getAttribute("data-page"), 10);
            var label = document.createElement("div");
            label.className = "page-label";
            label.textContent = "Page " + (pg + 1);
            section.insertBefore(label, section.firstChild);
        });

        // Hover handlers (markdown → PDF)
        container.querySelectorAll(".region-block").forEach(function (el) {
            el.addEventListener("mouseenter", function () {
                el.classList.add("region-hover");
                var pg = parseInt(el.getAttribute("data-page"), 10);
                var ri = parseInt(el.getAttribute("data-region"), 10);
                highlightPdfRegion(pg, ri);
            });
            el.addEventListener("mouseleave", function () {
                el.classList.remove("region-hover");
                clearPdfHighlight();
            });
            el.addEventListener("click", function () {
                var text = el.innerText || el.textContent;
                navigator.clipboard.writeText(text.trim()).then(function () {
                    el.classList.add("region-copied");
                    setTimeout(function () { el.classList.remove("region-copied"); }, 800);
                });
            });
        });
    }

    // Wire PDF overlay → markdown highlight (called after region data is loaded)
    function wireRegionSync() {
        if (!pdfOverlay || !mdPreview) return;

        // Use event delegation on the overlay
        pdfOverlay.addEventListener("mouseenter", function (e) {
            var rect = e.target.closest(".region-rect");
            if (!rect) return;
            rect.classList.add("active");
            var pg = rect.getAttribute("data-page");
            var ri = rect.getAttribute("data-region");
            // Find and highlight matching markdown block
            var mdBlock = mdPreview.querySelector(
                '.region-block[data-page="' + pg + '"][data-region="' + ri + '"]'
            );
            if (mdBlock) {
                mdBlock.classList.add("region-hover");
                mdBlock.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        }, true);

        pdfOverlay.addEventListener("mouseleave", function (e) {
            var rect = e.target.closest(".region-rect");
            if (!rect) return;
            rect.classList.remove("active");
            // Clear all markdown highlights
            mdPreview.querySelectorAll(".region-hover").forEach(function (el) {
                el.classList.remove("region-hover");
            });
        }, true);
    }

    // Rebuild markdown preview from JSON region data so each region is
    // a single hoverable block with an exact data-region index matching
    // the PDF overlay.  Called once region data arrives from the backend.
    function renderRegionAnnotatedMarkdown(regionData) {
        if (!mdPreview || typeof marked === "undefined") return;
        if (!regionData || regionData.length === 0) return;

        marked.setOptions({
            highlight: function (code, lang) {
                if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
                    return hljs.highlight(code, { language: lang }).value;
                }
                return code;
            },
            breaks: false,
            gfm: true,
        });

        var container = document.createDocumentFragment();

        for (var p = 0; p < regionData.length; p++) {
            var section = document.createElement("div");
            section.className = "page-section";
            section.setAttribute("data-page", p);

            var label = document.createElement("div");
            label.className = "page-label";
            label.textContent = "Page " + (p + 1);
            section.appendChild(label);

            var regions = regionData[p] || [];
            for (var r = 0; r < regions.length; r++) {
                var content = regions[r].content;
                if (content == null || (typeof content === "string" && content.trim() === "")) continue;

                var regionContent = typeof content === "string" ? content : String(content);

                // Render region content as markdown HTML
                var html = marked.parse(regionContent);

                // Rewrite image paths
                if (currentFileStem) {
                    html = html.replace(
                        /src="(imgs\/[^"]+)"/g,
                        'src="/api/output-image/' + encodeURIComponent(currentFileStem) + '/$1"'
                    );
                }

                // Render LaTeX
                html = html.replace(/\$\$([\s\S]*?)\$\$/g, function (_, tex) {
                    try {
                        return typeof katex !== "undefined"
                            ? katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false })
                            : "$$" + tex + "$$";
                    } catch (e) { return "$$" + tex + "$$"; }
                });
                html = html.replace(/\$([^\$\n]+?)\$/g, function (_, tex) {
                    try {
                        return typeof katex !== "undefined"
                            ? katex.renderToString(tex.trim(), { displayMode: false, throwOnError: false })
                            : "$" + tex + "$";
                    } catch (e) { return "$" + tex + "$"; }
                });

                var block = document.createElement("div");
                block.className = "region-block";
                block.setAttribute("data-page", p);
                block.setAttribute("data-region", regions[r].index != null ? regions[r].index : r);
                block.innerHTML = html;

                // Hover handlers
                (function (el) {
                    el.addEventListener("mouseenter", function () {
                        el.classList.add("region-hover");
                        var pg = parseInt(el.getAttribute("data-page"), 10);
                        var ri = parseInt(el.getAttribute("data-region"), 10);
                        highlightPdfRegion(pg, ri);
                    });
                    el.addEventListener("mouseleave", function () {
                        el.classList.remove("region-hover");
                        clearPdfHighlight();
                    });
                    el.addEventListener("click", function () {
                        var text = el.innerText || el.textContent;
                        navigator.clipboard.writeText(text.trim()).then(function () {
                            el.classList.add("region-copied");
                            setTimeout(function () { el.classList.remove("region-copied"); }, 800);
                        });
                    });
                })(block);

                section.appendChild(block);
            }
            container.appendChild(section);
        }

        mdPreview.innerHTML = "";
        mdPreview.appendChild(container);
    }

    function scrollPdfToPage(pageNum) {
        goToPdfPage(pageNum);
    }

    // ── Output Tab Switching (3 tabs) ──────────────
    var tabPreview = document.getElementById("tab-preview");
    var tabRaw = document.getElementById("tab-raw");
    var tabFullmd = document.getElementById("tab-fullmd");
    var panelPreview = document.getElementById("panel-preview");
    var panelRaw = document.getElementById("panel-raw");
    var panelFullmd = document.getElementById("panel-fullmd");
    var outputFullmd = document.getElementById("output-fullmd");
    var activeTab = "preview";

    var allTabs = [tabPreview, tabRaw, tabFullmd];
    var allPanels = [panelPreview, panelRaw, panelFullmd];

    function switchTab(tab) {
        activeTab = tab;
        var tabMap = { preview: 0, raw: 1, fullmd: 2 };
        var idx = tabMap[tab] !== undefined ? tabMap[tab] : 0;
        for (var i = 0; i < allTabs.length; i++) {
            if (allTabs[i]) allTabs[i].classList.toggle("active", i === idx);
            if (allPanels[i]) allPanels[i].classList.toggle("hidden", i !== idx);
        }
        // Generate Full MD content on demand
        if (tab === "fullmd" && outputFullmd && currentMarkdown) {
            outputFullmd.textContent = generateFullMarkdown(currentMarkdown);
        }
    }

    function generateFullMarkdown(md) {
        // Replace image references with ASCII art boxes
        return md.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, function (_, alt, src) {
            var fname = src.split("/").pop();
            var label = alt || fname;
            var innerW = Math.max(label.length, fname.length) + 6;
            var border = "+" + "-".repeat(innerW) + "+";
            var padLabel = "  " + label + " ".repeat(innerW - label.length - 4) + "  ";
            var padFile = "  " + fname + " ".repeat(innerW - fname.length - 4) + "  ";
            return border + "\n|" + padLabel + "|\n|" + padFile + "|\n" + border;
        });
    }

    // Stop tab clicks from toggling the <details> parent
    [tabPreview, tabRaw, tabFullmd].forEach(function (btn) {
        if (btn) {
            btn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                switchTab(btn.getAttribute("data-tab"));
            });
        }
    });

    // ── Result Fetching ─────────────────────────────
    function fetchResult(taskId) {
        fetch("/api/result/" + taskId)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (outputSection && data.markdown) {
                    if (outputPreview) outputPreview.textContent = data.markdown;
                    renderMarkdown(data.markdown, taskId, data.filename);
                    outputSection.classList.remove("hidden");
                    setupDownload(data.markdown, data.filename);
                }
                if (uploadStatus) uploadStatus.textContent = "Done \u2014 " + (data.output_path || "");
                // Fetch region data for highlight overlay
                fetchRegionData(taskId);
            })
            .catch(function () {
                if (uploadStatus) uploadStatus.textContent = "Error fetching result";
            });
    }

    function fetchRegionData(taskId) {
        fetch("/api/regions/" + taskId)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.regions && data.regions.length > 0) {
                    setRegionData(data.regions);
                    // Rebuild markdown preview from JSON so each region
                    // is a single block with exact data-region index
                    renderRegionAnnotatedMarkdown(data.regions);
                    wireRegionSync();
                }
            })
            .catch(function () {});
    }

    function setupDownload(markdown, filename) {
        var link = document.getElementById("btn-download");
        if (!link) return;
        var blob = new Blob([markdown], { type: "text/markdown" });
        link.href = URL.createObjectURL(blob);
        if (filename) link.download = filename.replace(/\.[^.]+$/, "") + ".md";
    }

    var copyBtn = document.getElementById("btn-copy");
    if (copyBtn) {
        copyBtn.addEventListener("click", function () {
            var text = "";
            if (activeTab === "fullmd" && outputFullmd) {
                text = outputFullmd.textContent;
            } else if (activeTab === "raw" && outputPreview) {
                text = outputPreview.textContent;
            } else {
                text = currentMarkdown;
            }
            if (text) {
                navigator.clipboard.writeText(text).then(function () {
                    copyBtn.textContent = "Copied!";
                    setTimeout(function () { copyBtn.textContent = "Copy"; }, 1500);
                });
            }
        });
    }

    // ── Utility ─────────────────────────────────────
    function escapeHtml(str) {
        var div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Server Control (settings page) ────────────────
    var serverAvailability = {};
    var logOutput = document.getElementById("server-log-output");

    var btnClearLog = document.getElementById("btn-clear-server-log");

    function showLog(text) {
        if (!logOutput) return;
        logOutput.classList.remove("hidden");
        if (btnClearLog) btnClearLog.classList.remove("hidden");
        logOutput.textContent += text + "\n";
        logOutput.scrollTop = logOutput.scrollHeight;
    }

    function clearServerLog() {
        if (logOutput) logOutput.textContent = "";
    }

    if (btnClearLog) {
        btnClearLog.addEventListener("click", clearServerLog);
    }

    function setServerUI(type, state) {
        var statusEl = document.getElementById("status-" + type);
        var startBtn = document.getElementById("btn-start-" + type);
        var stopBtn = document.getElementById("btn-stop-" + type);
        var installBtn = document.getElementById("btn-install-" + type);
        var dockerBtn = document.getElementById("btn-docker-" + type);
        var noteEl = document.getElementById("note-" + type);
        var info = serverAvailability[type] || {};

        if (statusEl) {
            statusEl.className = "server-status " + state;
            var labels = {
                "not-installed": "not installed",
                "stopped": "stopped",
                "starting": "starting\u2026",
                "running": "running" + (info.pid ? " (PID " + info.pid + ")" : ""),
                "installing": "installing\u2026",
                "error": "error",
            };
            statusEl.textContent = labels[state] || state;
        }

        if (installBtn) {
            if (state === "not-installed") {
                installBtn.classList.remove("hidden");
                installBtn.disabled = false;
                installBtn.textContent = "Install";
            } else if (state === "installing") {
                installBtn.classList.remove("hidden");
                installBtn.disabled = true;
                installBtn.textContent = "Installing\u2026";
            } else {
                installBtn.classList.add("hidden");
            }
        }

        if (dockerBtn) {
            if (state === "not-installed" && info.docker_available) {
                dockerBtn.classList.remove("hidden");
                dockerBtn.disabled = false;
            } else if (state === "installing") {
                dockerBtn.classList.remove("hidden");
                dockerBtn.disabled = true;
            } else {
                dockerBtn.classList.add("hidden");
            }
        }

        if (noteEl) {
            if (state === "not-installed" && info.note) {
                noteEl.textContent = info.note;
                noteEl.classList.remove("hidden");
            } else {
                noteEl.classList.add("hidden");
            }
        }

        if (startBtn) {
            startBtn.disabled = (state !== "stopped");
        }

        if (stopBtn) {
            stopBtn.disabled = (state !== "running");
        }
    }

    function installServer(type, method) {
        method = method || "sandbox";
        setServerUI(type, "installing");
        var label = (serverAvailability[type] && serverAvailability[type].label) || type;
        var via = method === "docker" ? " via Docker" : " (sandbox venv)";
        showLog("Installing " + label + via + "\u2026");

        fetch("/api/server/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: type, method: method }),
        })
        .then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) {
                    showLog("Error: " + (data.error || data.detail || "install failed"));
                    setServerUI(type, "not-installed");
                    return;
                }
                pollInstallStatus(type, 0);
            });
        })
        .catch(function (err) {
            showLog("Error: " + err.message);
            setServerUI(type, "not-installed");
        });
    }

    var _installPolls = {};

    function pollInstallStatus(type, linesSeen) {
        _installPolls[type] = setTimeout(function () {
            fetch("/api/server/install/status/" + type)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.lines && data.lines.length > linesSeen) {
                    for (var i = linesSeen; i < data.lines.length; i++) {
                        showLog(data.lines[i]);
                    }
                    linesSeen = data.lines.length;
                }

                if (data.done) {
                    delete _installPolls[type];
                    if (data.success && data.available) {
                        showLog("\n\u2713 Installation complete. You can now click Start.");
                        serverAvailability[type] = serverAvailability[type] || {};
                        serverAvailability[type].available = true;
                        setServerUI(type, "stopped");
                    } else {
                        var errMsg = data.error || ("exit code " + (data.return_code || "?"));
                        showLog("\n\u2717 Installation failed (" + errMsg + ")");
                        setServerUI(type, "not-installed");
                    }
                } else {
                    pollInstallStatus(type, linesSeen);
                }
            })
            .catch(function () {
                delete _installPolls[type];
                showLog("Error: lost connection during install");
                setServerUI(type, "not-installed");
            });
        }, 1000);
    }

    function _pollUntilRunning(type, n) {
        setTimeout(function () {
            var el = document.getElementById("status-" + type);
            if (!el || el.className.indexOf("starting") === -1) return;
            if (n >= 30) {
                setServerUI(type, "error");
                showLog("Timeout: " + type + " server did not start within 60 s.");
                return;
            }
            fetch("/api/server/status")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var info = data[type];
                if (info && info.running) {
                    serverAvailability[type] = info;
                    setServerUI(type, "running");
                } else {
                    _pollUntilRunning(type, n + 1);
                }
            })
            .catch(function () { _pollUntilRunning(type, n + 1); });
        }, 2000);
    }

    var _serverLogPolls = {};

    function pollServerLogs(type, linesSeen) {
        _serverLogPolls[type] = setTimeout(function () {
            fetch("/api/server/logs/" + type)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.lines && data.lines.length > linesSeen) {
                    for (var i = linesSeen; i < data.lines.length; i++) {
                        showLog(data.lines[i]);
                    }
                    linesSeen = data.lines.length;
                }
                var statusEl = document.getElementById("status-" + type);
                var isRunning = statusEl && statusEl.className.indexOf("running") !== -1;
                var isStarting = statusEl && statusEl.className.indexOf("starting") !== -1;
                if (isRunning || isStarting) {
                    pollServerLogs(type, linesSeen);
                }
            })
            .catch(function () {});
        }, 2000);
    }

    function stopServerLogPoll(type) {
        if (_serverLogPolls[type]) {
            clearTimeout(_serverLogPolls[type]);
            delete _serverLogPolls[type];
        }
    }

    function startServer(type) {
        var portEl = document.getElementById("f-port");
        var port = portEl ? parseInt(portEl.value, 10) || 8090 : 8090;
        setServerUI(type, "starting");
        showLog("Starting " + type + " on port " + port + "\u2026\nModel will download on first use (~1.8 GB for GLM-OCR).");

        fetch("/api/server/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: type, port: port }),
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.ok) {
                serverAvailability[type] = serverAvailability[type] || {};
                serverAvailability[type].pid = data.pid;
                setServerUI(type, "running");
                showLog("\u2713 Server process started (PID " + data.pid + ")");
                showLog("Streaming server logs below (model download, requests):");
                pollServerLogs(type, 0);
                setTimeout(refreshServerStatus, 3000);
            } else {
                setServerUI(type, data.install ? "not-installed" : "error");
                showLog("Failed to start: " + (data.error || data.detail || "unknown error"));
            }
        })
        .catch(function (err) {
            setServerUI(type, "error");
            showLog("Error: " + (err.message || "failed to start"));
        });

        _pollUntilRunning(type, 0);
    }

    function stopServer(type) {
        stopServerLogPoll(type);
        var statusEl = document.getElementById("status-" + type);
        if (statusEl) { statusEl.textContent = "stopping\u2026"; statusEl.className = "server-status"; }

        fetch("/api/server/stop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ type: type }),
        })
        .then(function (r) { return r.json(); })
        .then(function () {
            setServerUI(type, "stopped");
            showLog("Server stopped.");
        })
        .catch(function () {
            setServerUI(type, "error");
        });
    }

    function fetchServerLogs(type) {
        showLog("Loading " + type + " logs\u2026");

        fetch("/api/server/logs/" + type)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.lines && data.lines.length) {
                showLog(data.lines.join("\n"));
            } else {
                showLog("(no output captured)");
            }
        })
        .catch(function () {
            showLog("(failed to fetch logs)");
        });
    }

    function refreshServerStatus() {
        fetch("/api/server/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            ["vllm", "mlx"].forEach(function (type) {
                if (!data[type]) return;
                serverAvailability[type] = data[type];

                if (data[type].running) {
                    setServerUI(type, "running");
                } else if (!data[type].available) {
                    setServerUI(type, "not-installed");
                } else {
                    setServerUI(type, "stopped");
                }
            });
        })
        .catch(function () {});
    }

    // Bind server control buttons (settings page)
    var btnStartVllm = document.getElementById("btn-start-vllm");
    var btnStopVllm = document.getElementById("btn-stop-vllm");
    var btnStartMlx = document.getElementById("btn-start-mlx");
    var btnStopMlx = document.getElementById("btn-stop-mlx");
    var btnLogsVllm = document.getElementById("btn-logs-vllm");
    var btnLogsMlx = document.getElementById("btn-logs-mlx");
    var btnInstallVllm = document.getElementById("btn-install-vllm");
    var btnInstallMlx = document.getElementById("btn-install-mlx");
    var btnDockerVllm = document.getElementById("btn-docker-vllm");
    if (btnStartVllm) btnStartVllm.addEventListener("click", function () { startServer("vllm"); });
    if (btnStopVllm) btnStopVllm.addEventListener("click", function () { stopServer("vllm"); });
    if (btnStartMlx) btnStartMlx.addEventListener("click", function () { startServer("mlx"); });
    if (btnStopMlx) btnStopMlx.addEventListener("click", function () { stopServer("mlx"); });
    if (btnLogsVllm) btnLogsVllm.addEventListener("click", function () { fetchServerLogs("vllm"); });
    if (btnLogsMlx) btnLogsMlx.addEventListener("click", function () { fetchServerLogs("mlx"); });
    if (btnInstallVllm) btnInstallVllm.addEventListener("click", function () { installServer("vllm", "sandbox"); });
    if (btnInstallMlx) btnInstallMlx.addEventListener("click", function () { installServer("mlx", "sandbox"); });
    if (btnDockerVllm) btnDockerVllm.addEventListener("click", function () { installServer("vllm", "docker"); });

    if (document.getElementById("status-vllm")) refreshServerStatus();

    // ── Settings: Mode Toggle ──────────────────────────
    var modeSelect = document.getElementById("mode-select");
    if (modeSelect) {
        function toggleModeGroups() {
            var isMaas = modeSelect.value === "true";
            document.querySelectorAll("[data-group='maas']").forEach(function (el) {
                el.classList.toggle("group-hidden", !isMaas);
            });
            document.querySelectorAll("[data-group='selfhosted']").forEach(function (el) {
                el.classList.toggle("group-hidden", isMaas);
            });
        }
        modeSelect.addEventListener("change", toggleModeGroups);
        toggleModeGroups();
    }

    // ── Settings Form ───────────────────────────────
    var form = document.getElementById("settings-form");
    if (form) {
        form.addEventListener("submit", function (e) {
            e.preventDefault();
            var payload = {};
            var fields = form.querySelectorAll("[data-path]");
            fields.forEach(function (el) {
                var path = el.getAttribute("data-path");
                var type = el.getAttribute("data-type");
                var val;
                if (type === "bool") {
                    val = el.checked;
                } else if (type === "int") {
                    val = parseInt(el.value, 10);
                } else if (type === "float") {
                    val = parseFloat(el.value);
                } else if (type === "mode_select") {
                    val = el.value === "true";
                } else {
                    val = el.value;
                }
                payload[path] = val;
            });

            var status = document.getElementById("save-status");
            fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (status) {
                        status.textContent = data.ok ? "Saved \u2713" : "Error!";
                        status.style.color = data.ok ? "#00ff88" : "#ff4444";
                        setTimeout(function () { status.textContent = ""; }, 2000);
                    }
                })
                .catch(function () {
                    if (status) {
                        status.textContent = "Error!";
                        status.style.color = "#ff4444";
                    }
                });
        });
    }
    // ── Box Overlay Color Settings ──────────────────
    function hexToRgb(hex) {
        hex = hex.replace("#", "");
        return {
            r: parseInt(hex.substring(0, 2), 16),
            g: parseInt(hex.substring(2, 4), 16),
            b: parseInt(hex.substring(4, 6), 16),
        };
    }

    function applyBoxColors(color, outlineOp, fillOp, activeOutlineOp, activeFillOp, borderW) {
        var rgb = hexToRgb(color || "#00cccc");
        var r = rgb.r, g = rgb.g, b = rgb.b;
        var root = document.documentElement;
        root.style.setProperty("--box-outline", "rgba(" + r + "," + g + "," + b + "," + (outlineOp / 100) + ")");
        root.style.setProperty("--box-fill", "rgba(" + r + "," + g + "," + b + "," + (fillOp / 100) + ")");
        root.style.setProperty("--box-outline-active", "rgba(" + r + "," + g + "," + b + "," + (activeOutlineOp / 100) + ")");
        root.style.setProperty("--box-fill-active", "rgba(" + r + "," + g + "," + b + "," + (activeFillOp / 100) + ")");
        root.style.setProperty("--box-border-width", borderW + "px");
    }

    var BOX_DEFAULTS = {
        color: "#00cccc", outlineOp: 30, fillOp: 5,
        activeOutlineOp: 80, activeFillOp: 15, borderW: 2,
    };

    function loadBoxSettings() {
        try {
            var saved = JSON.parse(localStorage.getItem("boxOverlay") || "{}");
            return {
                color: saved.color || BOX_DEFAULTS.color,
                outlineOp: saved.outlineOp != null ? saved.outlineOp : BOX_DEFAULTS.outlineOp,
                fillOp: saved.fillOp != null ? saved.fillOp : BOX_DEFAULTS.fillOp,
                activeOutlineOp: saved.activeOutlineOp != null ? saved.activeOutlineOp : BOX_DEFAULTS.activeOutlineOp,
                activeFillOp: saved.activeFillOp != null ? saved.activeFillOp : BOX_DEFAULTS.activeFillOp,
                borderW: saved.borderW != null ? saved.borderW : BOX_DEFAULTS.borderW,
            };
        } catch (e) { return BOX_DEFAULTS; }
    }

    function saveBoxSettings(s) {
        localStorage.setItem("boxOverlay", JSON.stringify(s));
    }

    // Apply on every page load
    (function () {
        var s = loadBoxSettings();
        applyBoxColors(s.color, s.outlineOp, s.fillOp, s.activeOutlineOp, s.activeFillOp, s.borderW);
    })();

    // Settings page: live preview, slider labels, and localStorage sync
    var boxColorEl = document.getElementById("f-box-color");
    var boxSliders = {
        outlineOp: document.getElementById("f-box-outline-opacity"),
        fillOp: document.getElementById("f-box-fill-opacity"),
        activeOutlineOp: document.getElementById("f-box-active-outline-opacity"),
        activeFillOp: document.getElementById("f-box-active-fill-opacity"),
    };
    var boxBorderEl = document.getElementById("f-box-border-width");

    // Initialize settings fields from localStorage on settings page
    if (boxColorEl) {
        var s = loadBoxSettings();
        boxColorEl.value = s.color;
        if (boxSliders.outlineOp) boxSliders.outlineOp.value = s.outlineOp;
        if (boxSliders.fillOp) boxSliders.fillOp.value = s.fillOp;
        if (boxSliders.activeOutlineOp) boxSliders.activeOutlineOp.value = s.activeOutlineOp;
        if (boxSliders.activeFillOp) boxSliders.activeFillOp.value = s.activeFillOp;
        if (boxBorderEl) boxBorderEl.value = s.borderW;

        // Update labels
        ["box-outline-opacity", "box-fill-opacity", "box-active-outline-opacity", "box-active-fill-opacity"].forEach(function (id) {
            var slider = document.getElementById("f-" + id);
            var label = document.getElementById(id + "-val");
            if (slider && label) label.textContent = slider.value + "%";
        });
    }

    function readBoxSettingsFromForm() {
        return {
            color: boxColorEl ? boxColorEl.value : BOX_DEFAULTS.color,
            outlineOp: boxSliders.outlineOp ? parseInt(boxSliders.outlineOp.value, 10) : BOX_DEFAULTS.outlineOp,
            fillOp: boxSliders.fillOp ? parseInt(boxSliders.fillOp.value, 10) : BOX_DEFAULTS.fillOp,
            activeOutlineOp: boxSliders.activeOutlineOp ? parseInt(boxSliders.activeOutlineOp.value, 10) : BOX_DEFAULTS.activeOutlineOp,
            activeFillOp: boxSliders.activeFillOp ? parseInt(boxSliders.activeFillOp.value, 10) : BOX_DEFAULTS.activeFillOp,
            borderW: boxBorderEl ? parseInt(boxBorderEl.value, 10) : BOX_DEFAULTS.borderW,
        };
    }

    // Live preview + save on change
    function onBoxSettingChange() {
        var s = readBoxSettingsFromForm();
        applyBoxColors(s.color, s.outlineOp, s.fillOp, s.activeOutlineOp, s.activeFillOp, s.borderW);
        saveBoxSettings(s);
    }

    if (boxColorEl) boxColorEl.addEventListener("input", onBoxSettingChange);
    if (boxBorderEl) boxBorderEl.addEventListener("input", onBoxSettingChange);
    ["outlineOp", "fillOp", "activeOutlineOp", "activeFillOp"].forEach(function (key) {
        var slider = boxSliders[key];
        if (slider) {
            slider.addEventListener("input", function () {
                var labelMap = {
                    outlineOp: "box-outline-opacity-val",
                    fillOp: "box-fill-opacity-val",
                    activeOutlineOp: "box-active-outline-opacity-val",
                    activeFillOp: "box-active-fill-opacity-val",
                };
                var label = document.getElementById(labelMap[key]);
                if (label) label.textContent = slider.value + "%";
                onBoxSettingChange();
            });
        }
    });

    // ── Layout Toggle (horizontal / vertical) ─────
    var layoutToggle = document.getElementById("layout-toggle");
    var comparisonView = document.querySelector(".comparison-view");
    var layoutMode = localStorage.getItem("layoutMode") || "horizontal";

    function applyLayout(mode) {
        layoutMode = mode;
        if (comparisonView) {
            comparisonView.classList.toggle("vertical", mode === "vertical");
        }
        if (layoutToggle) {
            layoutToggle.innerHTML = mode === "horizontal"
                ? "&#x2B0C; Side-by-side"
                : "&#x2B0D; Stacked";
        }
        localStorage.setItem("layoutMode", mode);
        // Re-render PDF to fit new container width
        if (pdfDoc) setTimeout(function () { renderPdfPage(pdfCurrentPage); }, 100);
    }

    if (layoutToggle) {
        layoutToggle.addEventListener("click", function () {
            applyLayout(layoutMode === "horizontal" ? "vertical" : "horizontal");
        });
    }
    applyLayout(layoutMode);

    // ── Reconnect to active tasks on page load ─────────
    // When navigating back from Settings, restore running pipelines.
    (function reconnectActiveTasks() {
        if (!document.getElementById("pipeline-section")) return; // not pipeline page
        fetch("/api/tasks")
            .then(function (r) { return r.json(); })
            .then(function (taskList) {
                if (!taskList || !taskList.length) return;

                // Filter to non-idle tasks
                var active = taskList.filter(function (t) {
                    return t.status !== "pending" || t.stage !== "idle";
                });
                if (!active.length) return;

                // Single task: reconnect directly
                if (active.length === 1) {
                    var t = active[0];
                    if (pipelineSection) pipelineSection.classList.remove("hidden");
                    if (logSection) logSection.classList.remove("hidden");
                    if (uploadStatus) uploadStatus.textContent = "Resuming: " + t.filename;

                    // Show PDF preview from server
                    if (outputSection) outputSection.classList.remove("hidden");
                    showPdfPreview(t.filename);

                    if (t.status === "done") {
                        // Already done — fetch result directly
                        fetchResult(t.task_id);
                    } else if (t.status === "error") {
                        if (uploadStatus) uploadStatus.textContent = "Error on " + t.filename;
                    } else {
                        // Still running — reconnect SSE
                        connectSSE(t.task_id, null);
                    }
                    return;
                }

                // Multiple tasks: reconnect as batch
                if (pipelineSection) pipelineSection.classList.remove("hidden");
                if (logSection) logSection.classList.remove("hidden");
                var batchSection = document.getElementById("batch-section");
                if (batchSection) batchSection.classList.remove("hidden");

                batchTotal = active.length;
                batchDone = 0;
                if (uploadStatus) uploadStatus.textContent = "Resuming " + active.length + " files...";

                var list = document.getElementById("batch-list");
                if (list) list.innerHTML = "";

                active.forEach(function (t, idx) {
                    batchTasks[idx] = { taskId: t.task_id, filename: t.filename };

                    // Build minimal batch item
                    var details = document.createElement("details");
                    details.className = "batch-item";
                    details.id = "batch-item-" + idx;
                    details.open = true;

                    var summary = document.createElement("summary");
                    summary.innerHTML =
                        '<span class="batch-filename">' + escapeHtml(t.filename) + '</span>' +
                        '<span class="batch-stages">' +
                            STAGE_NAMES.map(function (n, j) {
                                return '<span class="batch-stage" id="bs-' + idx + '-' + j + '">' + n + '</span>';
                            }).join("") +
                        '</span>' +
                        '<span class="batch-status" id="bstat-' + idx + '">' + t.status + '</span>';
                    details.appendChild(summary);

                    var barWrap = document.createElement("div");
                    barWrap.className = "batch-progress-bar";
                    barWrap.innerHTML =
                        '<div class="progress-bar-track"><div class="batch-fill" id="bfill-' + idx + '"></div></div>' +
                        '<span class="batch-progress-label" id="blabel-' + idx + '"></span>';
                    details.appendChild(barWrap);

                    if (list) list.appendChild(details);

                    if (t.status === "done") {
                        setBatchStatus(idx, "done", "done");
                        var ff = document.getElementById("bfill-" + idx);
                        if (ff) ff.style.width = "100%";
                        batchDone++;
                    } else if (t.status === "error") {
                        setBatchStatus(idx, "error", "error");
                        batchDone++;
                    } else {
                        setBatchStatus(idx, "processing", "running");
                        connectSSE(t.task_id, idx);
                    }
                });

                if (batchDone >= batchTotal) {
                    if (uploadStatus) uploadStatus.textContent = "Batch complete (" + batchTotal + " files)";
                }
            })
            .catch(function () {});
    })();

})();
