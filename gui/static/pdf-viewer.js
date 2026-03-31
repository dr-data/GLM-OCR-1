/* PdfViewer — Reusable PDF.js viewer with region overlay
 *
 * Usage:
 *   var viewer = new PdfViewer({
 *       canvas: canvasEl,
 *       overlay: overlayEl,
 *       wrap: wrapEl,
 *       onRegionHover: function (pageIdx, regionIdx) {},
 *       onRegionLeave: function () {},
 *   });
 *   viewer.loadUrl("/path/to.pdf");
 *   viewer.setRegions(regionsPerPage);
 */

(function (global) {
    "use strict";

    var PDFJS_WORKER_SRC = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

    /**
     * @param {Object} options
     * @param {HTMLCanvasElement} options.canvas
     * @param {HTMLElement}       options.overlay
     * @param {HTMLElement}       options.wrap
     * @param {Function}          [options.onRegionHover]  — (pageIdx, regionIdx)
     * @param {Function}          [options.onRegionLeave]
     * @param {Function}          [options.onPageChange]   — ({current, total})
     * @param {Function}          [options.onZoomChange]   — (zoomPercentString)
     */
    function PdfViewer(options) {
        this._canvas = options.canvas || null;
        this._overlay = options.overlay || null;
        this._wrap = options.wrap || null;
        this._onRegionHover = options.onRegionHover || null;
        this._onRegionLeave = options.onRegionLeave || null;
        this._onPageChange = options.onPageChange || null;
        this._onZoomChange = options.onZoomChange || null;

        this._doc = null;
        this._currentPage = 1;
        this._totalPages = 0;
        this._baseScale = 1.0;   // computed fit-to-container scale
        this._zoomLevel = 1.0;   // user zoom multiplier

        // Per-page region data: { pageIdx: [{bbox_2d, label, content, regionIdx}] }
        this._regions = {};

        this._destroyed = false;
    }

    // ── Loading ──────────────────────────────────────

    PdfViewer.prototype.loadUrl = function (url) {
        var self = this;
        if (typeof pdfjsLib === "undefined") {
            console.error("PdfViewer: PDF.js not loaded");
            return;
        }
        pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_SRC;

        pdfjsLib.getDocument(url).promise.then(function (doc) {
            if (self._destroyed) return;
            self._doc = doc;
            self._totalPages = doc.numPages;
            self._currentPage = 1;
            self._notifyPageChange();
            self.render();
        }).catch(function (err) {
            console.error("PdfViewer: load error", err);
        });
    };

    PdfViewer.prototype.loadBlob = function (blob) {
        this.loadUrl(URL.createObjectURL(blob));
    };

    // ── Page Navigation ──────────────────────────────

    PdfViewer.prototype.setPage = function (n) {
        if (!this._doc) return;
        if (n < 1) n = 1;
        if (n > this._totalPages) n = this._totalPages;
        this._currentPage = n;
        this._notifyPageChange();
        this.render();
    };

    PdfViewer.prototype.nextPage = function () {
        this.setPage(this._currentPage + 1);
    };

    PdfViewer.prototype.prevPage = function () {
        this.setPage(this._currentPage - 1);
    };

    // ── Zoom ─────────────────────────────────────────

    PdfViewer.prototype.setZoom = function (level) {
        this._zoomLevel = Math.max(0.5, Math.min(3.0, level));
        this._notifyZoomChange();
        this.render();
    };

    PdfViewer.prototype.zoomIn = function () {
        this.setZoom(this._zoomLevel + 0.25);
    };

    PdfViewer.prototype.zoomOut = function () {
        this.setZoom(this._zoomLevel - 0.25);
    };

    // ── Rendering ────────────────────────────────────

    PdfViewer.prototype.render = function () {
        var self = this;
        if (!this._doc || !this._canvas) return;

        this._doc.getPage(this._currentPage).then(function (page) {
            if (self._destroyed) return;

            var containerWidth = (self._wrap && self._wrap.clientWidth > 40)
                ? self._wrap.clientWidth - 20 : 500;
            var containerHeight = (self._wrap && self._wrap.clientHeight > 40)
                ? self._wrap.clientHeight - 20 : 700;

            var unscaledViewport = page.getViewport({ scale: 1 });
            var scaleByWidth = containerWidth / unscaledViewport.width;
            var scaleByHeight = containerHeight / unscaledViewport.height;
            self._baseScale = Math.min(scaleByWidth, scaleByHeight);

            var finalScale = self._baseScale * self._zoomLevel;
            var viewport = page.getViewport({ scale: finalScale });

            self._canvas.width = viewport.width;
            self._canvas.height = viewport.height;

            var ctx = self._canvas.getContext("2d");
            page.render({ canvasContext: ctx, viewport: viewport }).promise.then(function () {
                if (self._destroyed) return;
                self._positionOverlay();
                self._drawRegions(self._currentPage - 1);
            });
        });
    };

    /**
     * Render a static image (non-PDF) onto the canvas, fitting to wrap width.
     * @param {HTMLImageElement} img — an already-loaded Image object
     */
    PdfViewer.prototype.renderImage = function (img) {
        if (!this._canvas) return;
        var maxW = this._wrap ? this._wrap.clientWidth - 20 : 500;
        var scale = Math.min(maxW / img.width, 1);
        this._canvas.width = img.width * scale;
        this._canvas.height = img.height * scale;
        this._canvas.getContext("2d").drawImage(img, 0, 0, this._canvas.width, this._canvas.height);
    };

    // ── Region Data ──────────────────────────────────

    /**
     * Set region data for all pages.
     * @param {Array|Object} regionsPerPage — either an Array (index = pageIdx) or
     *   an Object { pageIdx: [{bbox_2d, label, content, regionIdx?}] }
     */
    PdfViewer.prototype.setRegions = function (regionsPerPage) {
        this._regions = {};
        if (!regionsPerPage) return;

        if (Array.isArray(regionsPerPage)) {
            for (var p = 0; p < regionsPerPage.length; p++) {
                this._regions[p] = this._normalizeRegions(regionsPerPage[p], p);
            }
        } else {
            for (var key in regionsPerPage) {
                if (regionsPerPage.hasOwnProperty(key)) {
                    var idx = parseInt(key, 10);
                    this._regions[idx] = this._normalizeRegions(regionsPerPage[key], idx);
                }
            }
        }

        if (this._doc) {
            this._drawRegions(this._currentPage - 1);
        }
    };

    PdfViewer.prototype._normalizeRegions = function (regionList) {
        if (!regionList) return [];
        return regionList.map(function (r, i) {
            return {
                bbox_2d: r.bbox_2d,
                label: r.label || r.task_type || "region",
                content: r.content,
                regionIdx: r.index != null ? r.index : (r.regionIdx != null ? r.regionIdx : i),
            };
        });
    };

    // ── Region Highlight ─────────────────────────────

    PdfViewer.prototype.highlightRegion = function (regionIdx, pageIdx) {
        var self = this;
        if (pageIdx !== undefined && this._currentPage !== pageIdx + 1) {
            this.setPage(pageIdx + 1);
            setTimeout(function () { self._activateRect(regionIdx); }, 300);
        } else {
            this._activateRect(regionIdx);
        }
    };

    PdfViewer.prototype.clearHighlight = function () {
        if (!this._overlay) return;
        var active = this._overlay.querySelectorAll(".region-rect.active");
        for (var i = 0; i < active.length; i++) {
            active[i].classList.remove("active");
        }
    };

    // ── Info Getters ─────────────────────────────────

    PdfViewer.prototype.getPageInfo = function () {
        return { current: this._currentPage, total: this._totalPages };
    };

    PdfViewer.prototype.getZoomInfo = function () {
        return Math.round(this._zoomLevel * 100) + "%";
    };

    PdfViewer.prototype.getDoc = function () {
        return this._doc;
    };

    PdfViewer.prototype.getRegions = function (pageIdx) {
        if (pageIdx !== undefined) return this._regions[pageIdx] || [];
        return this._regions;
    };

    // ── Cleanup ──────────────────────────────────────

    PdfViewer.prototype.destroy = function () {
        this._destroyed = true;
        if (this._doc) {
            this._doc.destroy();
            this._doc = null;
        }
        if (this._overlay) {
            this._overlay.innerHTML = "";
        }
        this._regions = {};
    };

    // ── Private Helpers ──────────────────────────────

    PdfViewer.prototype._positionOverlay = function () {
        if (!this._overlay || !this._wrap || !this._canvas) return;
        var canvasRect = this._canvas.getBoundingClientRect();
        var wrapRect = this._wrap.getBoundingClientRect();
        this._overlay.style.left = (canvasRect.left - wrapRect.left + this._wrap.scrollLeft) + "px";
        this._overlay.style.top = (canvasRect.top - wrapRect.top + this._wrap.scrollTop) + "px";
        this._overlay.style.width = this._canvas.width + "px";
        this._overlay.style.height = this._canvas.height + "px";
    };

    PdfViewer.prototype._drawRegions = function (pageIdx) {
        if (!this._overlay || !this._canvas) return;
        this._overlay.innerHTML = "";
        var regions = this._regions[pageIdx];
        if (!regions) return;

        var cw = this._canvas.width;
        var ch = this._canvas.height;
        var self = this;

        for (var i = 0; i < regions.length; i++) {
            (function (r) {
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
                rect.title = r.label + " \u2014 click to copy";

                // Click to copy region content
                rect.addEventListener("click", function () {
                    if (!r.content) return;
                    navigator.clipboard.writeText(r.content.trim()).then(function () {
                        rect.classList.add("copied");
                        setTimeout(function () { rect.classList.remove("copied"); }, 800);
                    });
                });

                // Hover callbacks
                rect.addEventListener("mouseenter", function () {
                    rect.classList.add("active");
                    if (self._onRegionHover) {
                        self._onRegionHover(pageIdx, r.regionIdx);
                    }
                });
                rect.addEventListener("mouseleave", function () {
                    rect.classList.remove("active");
                    if (self._onRegionLeave) {
                        self._onRegionLeave();
                    }
                });

                self._overlay.appendChild(rect);
            })(regions[i]);
        }
    };

    PdfViewer.prototype._activateRect = function (regionIdx) {
        if (!this._overlay) return;
        var active = this._overlay.querySelectorAll(".region-rect.active");
        for (var i = 0; i < active.length; i++) {
            active[i].classList.remove("active");
        }
        var target = this._overlay.querySelector('.region-rect[data-region="' + regionIdx + '"]');
        if (target) target.classList.add("active");
    };

    PdfViewer.prototype._notifyPageChange = function () {
        if (this._onPageChange) {
            this._onPageChange({ current: this._currentPage, total: this._totalPages });
        }
    };

    PdfViewer.prototype._notifyZoomChange = function () {
        if (this._onZoomChange) {
            this._onZoomChange(this.getZoomInfo());
        }
    };

    // ── Export ────────────────────────────────────────
    global.PdfViewer = PdfViewer;

})(window);
