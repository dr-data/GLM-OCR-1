/* GLM-OCR Settings — reads OCR settings panel and wires presets/tooltips */
var OcrSettings = (function () {
    "use strict";

    function read() {
        var s = {};
        var dpi = document.getElementById("ocr-dpi");
        var threshold = document.getElementById("ocr-threshold");
        var format = document.getElementById("ocr-format");
        var maxTokens = document.getElementById("ocr-max-tokens");
        var polygon = document.getElementById("ocr-polygon");
        var unclip = document.getElementById("ocr-unclip");
        var repPenalty = document.getElementById("ocr-rep-penalty");
        if (dpi) s["pipeline.page_loader.pdf_dpi"] = parseInt(dpi.value, 10);
        if (threshold) s["pipeline.layout.threshold"] = parseFloat(threshold.value);
        if (format) s["pipeline.page_loader.image_format"] = format.value;
        if (maxTokens) s["pipeline.page_loader.max_tokens"] = parseInt(maxTokens.value, 10);
        if (polygon) s["pipeline.layout.use_polygon"] = polygon.value === "true";
        if (unclip) s["pipeline.layout.layout_unclip_ratio"] = [parseFloat(unclip.value), parseFloat(unclip.value)];
        if (repPenalty) s["pipeline.page_loader.repetition_penalty"] = parseFloat(repPenalty.value);
        return s;
    }

    function wirePresets() {
        document.querySelectorAll(".ocr-presets").forEach(function (row) {
            var targetId = row.getAttribute("data-target");
            var input = document.getElementById(targetId);
            if (!input) return;
            row.querySelectorAll(".ocr-preset").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    row.querySelectorAll(".ocr-preset").forEach(function (b) { b.classList.remove("active"); });
                    btn.classList.add("active");
                    input.value = btn.getAttribute("data-val");
                    if (input.tagName === "SELECT") {
                        input.dispatchEvent(new Event("change"));
                    }
                });
            });
            input.addEventListener("input", function () {
                var val = input.value;
                row.querySelectorAll(".ocr-preset").forEach(function (b) {
                    b.classList.toggle("active", b.getAttribute("data-val") === val);
                });
            });
        });
    }

    function wireTooltips() {
        document.querySelectorAll(".ocr-help").forEach(function (el) {
            var tip = null;
            el.addEventListener("mouseenter", function () {
                if (tip) return;
                tip = document.createElement("div");
                tip.className = "ocr-tooltip";
                tip.textContent = (el.getAttribute("data-tip") || "").replace(/\\n/g, "\n");
                el.style.position = "relative";
                el.appendChild(tip);
            });
            el.addEventListener("mouseleave", function () {
                if (tip) { tip.remove(); tip = null; }
            });
        });
    }

    return { read: read, wirePresets: wirePresets, wireTooltips: wireTooltips };
})();
