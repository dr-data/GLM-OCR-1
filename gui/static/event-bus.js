/* GLM-OCR Event Bus — simple pub/sub for decoupled communication */
var EventBus = (function () {
    "use strict";
    var listeners = {};
    return {
        on: function (event, callback) {
            if (!listeners[event]) listeners[event] = [];
            listeners[event].push(callback);
        },
        off: function (event, callback) {
            if (!listeners[event]) return;
            listeners[event] = listeners[event].filter(function (cb) { return cb !== callback; });
        },
        emit: function (event, data) {
            (listeners[event] || []).forEach(function (cb) {
                try { cb(data); } catch (e) { console.error("EventBus error on " + event + ":", e); }
            });
        },
    };
})();
