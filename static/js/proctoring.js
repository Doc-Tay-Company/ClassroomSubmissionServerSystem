(() => {
  "use strict";

  const root = document.getElementById("proctoring-root");
  const panel = document.getElementById("student-panel");
  if (!root || !panel) return;

  let state = {};
  try {
    state = JSON.parse(root.dataset.state || "{}") || {};
  } catch (error) {
    state = {};
  }

  const homeView = panel.dataset.homeView === "true";
  const maxWarnings = Number(state.max_warnings || 3);
  const graceSeconds = Number(state.grace_seconds || 120);
  let active = Boolean(state.active) && !homeView;
  let terminated = Boolean(state.terminated);
  let violationCount = Number(state.violation_count || 0);
  let leaveRequest = null;
  let leaveRecorded = false;
  let lastLeaveAt = 0;
  let suppressUntil = 0;
  let deadline = 0;
  let modalKind = "";
  let pollTimer = 0;
  let tickTimer = 0;
  let retryTimer = 0;
  let timeoutTriggered = false;

  const reasonText = {
    violation_limit: "bạn đã vượt quá số lần cảnh cáo cho phép",
    return_timeout: "bạn không quay lại màn hình kiểm tra trong vòng 2 phút",
    disconnect_timeout: "hệ thống không nhận được tín hiệu từ máy của bạn trong vòng 2 phút",
  };

  let overlay;
  let title;
  let message;
  let countdown;
  let errorBox;
  let acceptButton;
  let homeButton;

  function buildOverlay() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "proctoring-overlay hidden";
    overlay.id = "proctoring-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "proctoring-title");
    overlay.innerHTML = `
      <div class="proctoring-card">
        <div class="proctoring-icon"><i class="fa fa-exclamation-triangle"></i></div>
        <h2 id="proctoring-title"></h2>
        <p id="proctoring-message" class="proctoring-message"></p>
        <div id="proctoring-countdown" class="proctoring-countdown hidden"></div>
        <div id="proctoring-error" class="alert alert-error hidden" role="alert"></div>
        <button id="proctoring-accept" class="btn btn-primary btn-wide" type="button">Quay lại làm bài</button>
        <a id="proctoring-home" class="btn btn-secondary btn-wide hidden" href="/?view=home">Về trang chủ</a>
      </div>`;
    document.body.append(overlay);
    title = document.getElementById("proctoring-title");
    message = document.getElementById("proctoring-message");
    countdown = document.getElementById("proctoring-countdown");
    errorBox = document.getElementById("proctoring-error");
    acceptButton = document.getElementById("proctoring-accept");
    homeButton = document.getElementById("proctoring-home");
    acceptButton.addEventListener("click", acknowledge);
  }

  function formatTime(seconds) {
    const safe = Math.max(0, Math.ceil(seconds));
    return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
  }

  function showError(text) {
    if (!errorBox) return;
    errorBox.textContent = text;
    errorBox.classList.remove("hidden");
  }

  function clearError() {
    if (!errorBox) return;
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function lockExam() {
    terminated = true;
    active = false;
    panel.setAttribute("inert", "");
    panel.querySelectorAll("input, textarea, button, select").forEach((element) => {
      element.disabled = true;
    });
    document.body.classList.add("proctoring-terminated");
    if (pollTimer) window.clearInterval(pollTimer);
    if (tickTimer) window.clearInterval(tickTimer);
    if (retryTimer) window.clearTimeout(retryTimer);
    pollTimer = tickTimer = retryTimer = 0;
  }

  function showTerminated(serverState = {}) {
    buildOverlay();
    lockExam();
    modalKind = "terminated";
    const reason = serverState.termination_reason || state.termination_reason;
    title.textContent = "Bài thi đã kết thúc";
    message.textContent = `Bài thi của bạn đã bị kết thúc vì vi phạm quy chế giám sát`;
    countdown.classList.add("hidden");
    clearError();
    acceptButton.classList.add("hidden");
    homeButton.classList.remove("hidden");
    overlay.classList.remove("hidden");
    document.title = "Bài thi đã kết thúc";
  }

  function updateWarning(serverState = {}) {
    const count = Number(serverState.violation_count ?? violationCount);
    violationCount = count;
    if (serverState.grace_remaining !== null && serverState.grace_remaining !== undefined) {
      deadline = Date.now() + Math.max(0, Number(serverState.grace_remaining)) * 1000;
      if (Number(serverState.grace_remaining) > 0) timeoutTriggered = false;
    }
    title.textContent = "Cảnh cáo vi phạm";
    const remainingText = count >= maxWarnings
      ? " Đây là cảnh cáo cuối cùng; lần vi phạm tiếp theo sẽ kết thúc bài thi ngay lập tức."
      : "";
    message.textContent = `Bạn đã rời khỏi màn hình kiểm tra. Vi phạm thứ ${count}/${maxWarnings}. Bài thi đang bị tạm khóa. ${remainingText}`;
    countdown.classList.remove("hidden");
    countdown.textContent = deadline
      ? `Thời gian còn lại để quay lại: ${formatTime((deadline - Date.now()) / 1000)}`
      : "Đang ghi nhận vi phạm...";
    syncAcceptButton();
  }

  function syncAcceptButton() {
    if (!acceptButton) return;
    acceptButton.classList.remove("hidden");
    homeButton.classList.add("hidden");
    if (leaveRequest) {
      acceptButton.disabled = true;
      acceptButton.textContent = "Đang ghi nhận vi phạm...";
    } else if (leaveRecorded) {
      acceptButton.disabled = false;
      acceptButton.textContent = "Quay lại làm bài";
    } else {
      acceptButton.disabled = true;
      acceptButton.textContent = "Đang chờ kết nối lại...";
    }
  }

  function showWarning(serverState = {}) {
    if (terminated) return;
    buildOverlay();
    if (!modalKind) {
      document.body.classList.add("proctoring-locked");
      panel.setAttribute("inert", "");
    }
    modalKind = "warning";
    clearError();
    overlay.classList.remove("hidden");
    updateWarning(serverState);
    window.setTimeout(() => acceptButton?.focus(), 0);
  }

  function hideModal() {
    if (!overlay) return;
    modalKind = "";
    overlay.classList.add("hidden");
    panel.removeAttribute("inert");
    document.body.classList.remove("proctoring-locked");
    clearError();
    if (pollTimer) window.clearInterval(pollTimer);
    if (tickTimer) window.clearInterval(tickTimer);
    if (retryTimer) window.clearTimeout(retryTimer);
    pollTimer = tickTimer = retryTimer = 0;
    if (active) {
      startTimers();
      pollState();
    }
  }

  function applyState(serverState) {
    if (!serverState) return;
    active = Boolean(serverState.active) && !homeView;
    violationCount = Number(serverState.violation_count ?? violationCount) || 0;
    if (serverState.terminated) {
      showTerminated(serverState);
      return;
    }
    terminated = false;
    if (serverState.warning_pending && active) {
      leaveRecorded = true;
      if (modalKind !== "warning") {
        showWarning(serverState);
      } else {
        updateWarning(serverState);
      }
      return;
    }
    if (modalKind === "warning") {
      hideModal();
    }
    if (!active) {
      if (pollTimer) window.clearInterval(pollTimer);
      if (tickTimer) window.clearInterval(tickTimer);
      pollTimer = tickTimer = 0;
    }
  }

  async function pollState() {
    if (!active || terminated) return;
    try {
      const status = await window.cssRequest("/api/student/status");
      if (status.proctoring) applyState(status.proctoring);
      if (status.status && status.status !== "in_progress") {
        active = false;
      }
    } catch (error) {
      if (error.status === 401) {
        active = false;
      }
    }
  }

  function scheduleRetry(eventName) {
    if (retryTimer || !active || terminated) return;
    retryTimer = window.setTimeout(() => {
      retryTimer = 0;
      sendViolation(eventName);
    }, 5000);
  }

  async function sendViolation(eventName) {
    if (!active || terminated || leaveRequest) return;
    leaveRequest = (async () => {
      try {
        const body = new URLSearchParams({ event: eventName });
        const data = await window.cssRequest("/api/student/proctoring/violation", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body,
        });
        leaveRecorded = true;
        clearError();
        if (retryTimer) window.clearTimeout(retryTimer);
        retryTimer = 0;
        applyState(data.proctoring);
      } catch (error) {
        leaveRecorded = false;
        if (error.status === 401) {
          showError("Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại để tiếp tục.");
          return;
        }
        showError("Không thể ghi nhận vi phạm lúc này. Hệ thống sẽ tự động kết thúc bài thi nếu bạn không quay lại trong 2 phút. Đang thử kết nối lại...");
        scheduleRetry(eventName);
      } finally {
        leaveRequest = null;
        syncAcceptButton();
      }
    })();
    syncAcceptButton();
  }

  function recordViolation(eventName) {
    if (!active || terminated || modalKind === "warning") return;
    if (Date.now() < suppressUntil) return;
    if (document.visibilityState === "visible" && document.hasFocus()) return;
    if (Date.now() - lastLeaveAt < 1500) return;
    lastLeaveAt = Date.now();
    const optimistic = {
      active: true,
      terminated: false,
      violation_count: violationCount + 1,
      max_warnings: maxWarnings,
      warning_pending: true,
      grace_seconds: graceSeconds,
      grace_remaining: graceSeconds,
    };
    leaveRecorded = false;
    deadline = Date.now() + graceSeconds * 1000;
    showWarning(optimistic);
    sendViolation(eventName);
  }

  async function acknowledge() {
    if (modalKind !== "warning" || leaveRequest) return;
    acceptButton.disabled = true;
    acceptButton.textContent = "Đang xác nhận...";
    try {
      const data = await window.cssRequest("/api/student/proctoring/ack", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(),
      });
      applyState(data.proctoring);
      if (!data.proctoring?.terminated) {
        window.cssToast("Đã xác nhận cảnh cáo. Tiếp tục làm bài.", "success");
        document.getElementById("student-code-editor")?.focus();
      }
    } catch (error) {
      showError(error.message || "Không thể xác nhận cảnh cáo. Vui lòng thử lại.");
      acceptButton.disabled = false;
      acceptButton.textContent = "Quay lại làm bài";
    }
  }

  async function handleTimeout() {
    if (modalKind !== "warning" || terminated) return;
    countdown.textContent = "Đã hết thời gian quay lại. Đang kết thúc bài thi...";
    acceptButton.disabled = true;
    try {
      const status = await window.cssRequest("/api/student/status");
      if (status.proctoring) {
        applyState(status.proctoring);
        if (status.proctoring.terminated) return;
      }
    } catch (error) {
      // The server watchdog also handles this case; show the terminal state locally.
    }
    showTerminated({ termination_reason: "return_timeout" });
  }

  function tick() {
    if (modalKind !== "warning" || !deadline) return;
    const remaining = (deadline - Date.now()) / 1000;
    countdown.textContent = `Thời gian còn lại để quay lại: ${formatTime(remaining)}`;
    countdown.classList.toggle("proctoring-countdown-urgent", remaining <= 30);
    if (remaining <= 0 && !timeoutTriggered) {
      timeoutTriggered = true;
      handleTimeout();
    }
  }

  function startTimers() {
    if (!active || terminated) return;
    if (!pollTimer) pollTimer = window.setInterval(pollState, 5000);
    if (!tickTimer) tickTimer = window.setInterval(tick, 1000);
  }

  if (!active && !terminated && !state.warning_pending) return;
  if (homeView) {
    // The home view is not the exam screen; the template banner is enough.
    // Reloading it must not trap a terminated student in the modal again.
    return;
  }

  buildOverlay();
  if (terminated) {
    showTerminated(state);
    return;
  }
  if (state.warning_pending) {
    leaveRecorded = true;
    if (state.grace_remaining !== null && state.grace_remaining !== undefined) {
      deadline = Date.now() + Math.max(0, Number(state.grace_remaining)) * 1000;
    }
    showWarning(state);
  }
  startTimers();
  pollState();

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest('input[type="file"]')) {
      // Opening the OS file picker is part of submitting the ZIP, not a violation.
      suppressUntil = Date.now() + 15000;
    }
    if (target.closest("[data-proctoring-exempt]")) {
      // Reading the exam paper in a new tab is part of the exam.
      suppressUntil = Date.now() + 5000;
    }
  }, true);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      recordViolation("tab_hidden");
    } else {
      window.setTimeout(() => {
        if (document.visibilityState === "visible") suppressUntil = 0;
      }, 800);
      pollState();
    }
  });

  window.addEventListener("blur", () => recordViolation("window_blur"));
  window.addEventListener("focus", () => {
    window.setTimeout(() => {
      if (document.hasFocus()) suppressUntil = 0;
    }, 800);
    pollState();
  });

  window.addEventListener("pagehide", () => {
    if (!active || terminated) return;
    if (Date.now() < suppressUntil) return;
    try {
      navigator.sendBeacon(
        "/api/student/proctoring/violation",
        new URLSearchParams({ event: "pagehide" }),
      );
    } catch (error) {
      // The server heartbeat timeout is the fallback.
    }
  });

  window.addEventListener("pageshow", (event) => {
    if (event.persisted) pollState();
  });
})();
