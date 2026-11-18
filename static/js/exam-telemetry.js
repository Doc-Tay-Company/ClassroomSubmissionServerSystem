(function (global) {
  global.createExamTelemetry = function ({ sendSnapshot, submitEvent, reportError }) {
    let enabled = false;
    let releaseId = null;
    let focused = document.hasFocus();
    let visible = document.visibilityState === "visible";
    let pending = [];
    let flushing = false;

    const makeEventId = () => {
      if (global.crypto?.randomUUID) return global.crypto.randomUUID();
      return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
    };
    const flush = async () => {
      if (!enabled || flushing) return;
      flushing = true;
      try {
        while (enabled && pending.length) {
          const item = pending[0];
          if (item.releaseId !== releaseId) { pending.shift(); continue; }
          try {
            const result = await submitEvent({
              event_id: item.eventId,
              event_type: item.type,
              client_occurred_at: item.occurredAt,
              release_id: item.releaseId,
            });
            // A server-side inactive decision is final for this attempted delivery.
            if (pending[0] === item) pending.shift();
            if (result?.reason === "inactive_attempt") break;
          } catch (error) {
            reportError?.(error);
            break; // Keep the same event_id for the next retry.
          }
        }
      } finally { flushing = false; }
    };
    const record = (type) => {
      pending.push({ releaseId, type, eventId: makeEventId(), occurredAt: new Date().toISOString() });
      void flush();
    };
    const sendCurrentSnapshot = async () => {
      if (!enabled) return;
      try { await sendSnapshot(); }
      catch (error) { reportError?.(error); }
    };

    return {
      setActive(active, nextReleaseId) {
        if (!active || !nextReleaseId) {
          enabled = false;
          releaseId = null;
          pending = [];
          return;
        }
        if (releaseId !== nextReleaseId) {
          // Establish a baseline. Initial hidden/unfocused state is not an event.
          focused = document.hasFocus();
          visible = document.visibilityState === "visible";
          pending = [];
        } else if (!enabled) {
          // Reconnection establishes a fresh browser-state baseline but retains
          // queued events and their event IDs for idempotent delivery retries.
          focused = document.hasFocus();
          visible = document.visibilityState === "visible";
        }
        releaseId = nextReleaseId;
        enabled = true;
        void flush();
      },
      pause() { enabled = false; },
      recordEvent(type) { if (enabled) record(type); },
      sendSnapshot: sendCurrentSnapshot,
      onBlur() {
        const wasFocused = focused;
        focused = false;
        if (!enabled) return;
        if (wasFocused) record("window_blur");
        void sendCurrentSnapshot();
      },
      onFocus() {
        focused = true;
        if (enabled) void flush();
      },
      onVisibilityChange() {
        const isVisible = document.visibilityState === "visible";
        const wasVisible = visible;
        visible = isVisible;
        if (!enabled) return;
        if (wasVisible && !isVisible) record("document_hidden");
        if (isVisible) void flush();
        void sendCurrentSnapshot();
      },
      pendingCount: () => pending.length,
    };
  };
})(window);
