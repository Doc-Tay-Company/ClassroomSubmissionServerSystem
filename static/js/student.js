(async function () {
  document.querySelectorAll("[data-local-clock]").forEach((element) => { element.textContent = window.formatExamClock(element.dataset.localClock); });
  const reportedErrors = new Set();
  const reportBackgroundError = (scope, error) => {
    if (reportedErrors.has(scope)) return;
    reportedErrors.add(scope);
    console.warn(`${scope} request failed`, error);
  };
  const tabId = Math.random().toString(36).slice(2);
  const tabKey = "css-exam-tabs";
  const updateTabs = () => {
    let tabs = {};
    try { tabs = JSON.parse(localStorage.getItem(tabKey) || "{}"); }
    catch (error) { reportBackgroundError("Student tab storage read", error); }
    const now = Date.now();
    tabs[tabId] = now;
    Object.keys(tabs).forEach((id) => { if (now - tabs[id] > 20000) delete tabs[id]; });
    try { localStorage.setItem(tabKey, JSON.stringify(tabs)); }
    catch (error) { reportBackgroundError("Student tab storage write", error); }
    return Object.keys(tabs).length;
  };
  let heartbeatInFlight = false;
  const examTelemetry = window.createExamTelemetry({
    sendSnapshot: async () => {
    const form = new URLSearchParams({
      visibility: document.visibilityState,
      focused: String(document.hasFocus()),
      tab_count: String(updateTabs()),
      browser: navigator.userAgent,
    });
      await window.cssRequest("/api/student/telemetry", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form,
      });
    },
    submitEvent: (event) => window.cssRequest("/api/student/telemetry/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    }),
    reportError: (error) => reportBackgroundError("Exam monitoring event", error),
  });
  const examEntry = window.createExamEntry({
    getTabCount: updateTabs,
    startRequest: (confirmedMultipleTabs) => {
      const form = new FormData();
      form.append("exam_password", document.getElementById("exam-password")?.value || "");
      if (confirmedMultipleTabs) form.append("confirmed_multiple_tabs", "true");
      return window.cssRequest("/api/student/start", { method: "POST", body: form });
    },
    recordEvent: (type) => examTelemetry.recordEvent(type),
    reload: () => window.location.reload(),
    reportError: (error) => window.cssToast(error.message, "error"),
  });
  let completionNavigation = null;
  window.completeOfficialExam = () => {
    if (completionNavigation) return completionNavigation;
    examTelemetry.setActive(false, null);
    examEntry.setStatus({ active_exam_attempt: false });
    completionNavigation = (async () => {
      try { if (document.fullscreenElement && document.exitFullscreen) await document.exitFullscreen(); } catch (_) {}
      window.location.assign("/?view=home");
    })();
    return completionNavigation;
  };
  const heartbeat = async () => {
    if (heartbeatInFlight) return;
    heartbeatInFlight = true;
    updateTabs(); // Keep the existing page registry usable for the pre-Start check; no telemetry is sent here.
    try {
      const status = await window.cssRequest("/api/student/status");
      window.refreshExamDeadlineClock(status.ends_at);
      const activeAttempt = status.active_exam_attempt === true;
      const behaviorMonitoring = activeAttempt && !status.exam_file;
      examTelemetry.setActive(behaviorMonitoring, behaviorMonitoring ? status.release_id : null);
      examEntry.setStatus(status);
      if (status.completion?.finalized && document.getElementById("student-panel")?.dataset.homeView !== "true") {
        await window.completeOfficialExam();
        return;
      }
      if (behaviorMonitoring) {
        await examTelemetry.sendSnapshot();
      }
      const box = document.getElementById("student-notifications");
      if (box && status.notifications?.length) {
        box.className = "alert alert-info";
        box.innerHTML = status.notifications.map((item) =>
          `<div><strong>Thông báo</strong>: ${window.cssEscape(item.message)}</div>`).join("");
      }
      const panel = document.getElementById("student-panel");
      const published = (status.published_exams || []).map((item) => item.id).sort().join(",");
      if (panel && panel.dataset.homeView === "true") {
        const previous = [
          panel.dataset.assigned || "",
          panel.dataset.assignmentRelease || "",
          panel.dataset.assignmentStatus || "",
          panel.dataset.assignmentStartedAt || "",
          panel.dataset.examState || "idle",
          (panel.dataset.published || "").split(",").filter(Boolean).sort().join(","),
        ].join("|");
        const current = [
          status.assigned ? "1" : "0",
          status.release_id || "",
          status.assigned ? (status.status || "") : "",
          status.started_at || "",
          status.exam_state || "idle",
          published,
        ].join("|");
        if (current !== previous) {
          window.location.reload();
          return;
        }
      }
      const waiting = panel && ["idle", "ended", "distributed"].includes(panel.dataset.examState);
      const publishedBefore = (panel?.dataset.published || "").split(",").filter(Boolean).sort().join(",");
      if (waiting && (status.exam_state === "started" || publishedBefore !== published)) window.location.reload();
    } catch (error) {
      examTelemetry.pause();
      reportBackgroundError("Student heartbeat", error);
    } finally {
      heartbeatInFlight = false;
    }
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") heartbeat();
    else examTelemetry.onVisibilityChange();
  });
  window.addEventListener("focus", heartbeat);
  window.addEventListener("focus", () => examTelemetry.onFocus());
  window.addEventListener("blur", () => examTelemetry.onBlur());
  window.addEventListener("storage", () => examTelemetry.sendSnapshot());
  heartbeat();
  setInterval(heartbeat, 10000);

  const countdown = document.getElementById("countdown");
  if (countdown && !document.getElementById("student-code-root")) {
    let remaining = Number(countdown.dataset.remaining || 0);
    let closing = false;
    let retryAfter = 0;
    const closeExpiredFileExam = async () => {
      const panel = document.getElementById("student-panel");
      if (remaining > 0 || !panel?.dataset.assignmentStartedAt || closing || Date.now() < retryAfter) return;
      closing = true;
      retryAfter = Date.now() + 5000;
      document.getElementById("submission-form")?.querySelectorAll("input,button").forEach((element) => { element.disabled = true; });
      try {
        const result = await window.cssRequest("/api/student/finalize", {method:"POST"});
        if (result.finalized) await window.completeOfficialExam();
      } catch (error) { reportBackgroundError("Deadline finalization", error); }
      finally { closing = false; }
    };
    const draw = () => {
      const minutes = Math.floor(remaining / 60);
      const seconds = remaining % 60;
      countdown.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
      countdown.classList.toggle("countdown-warning", remaining <= 300);
      if (remaining <= 0) countdown.textContent = "Hết giờ";
      if (remaining <= 0) void closeExpiredFileExam();
    };
    draw();
    setInterval(() => { if (remaining > 0) remaining--; draw(); }, 1000);
    setInterval(async () => {
      try {
        const status = await window.cssRequest("/api/student/status");
        window.refreshExamDeadlineClock(status.ends_at);
        if (status.remaining_seconds !== null) {
          remaining = status.remaining_seconds;
          draw();
        }
      } catch (error) { reportBackgroundError("Student status", error); }
    }, 5000);
  }

  const form = document.getElementById("submission-form");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const file = document.getElementById("submission-file").files[0];
      if (!file) return;
      const button = form.querySelector("button");
      button.disabled = true;
      const data = new FormData();
      data.append("file", file);
      try {
        const result = await window.cssRequest("/api/student/submit", { method: "POST", body: data });
        const box = document.getElementById("submission-result");
        box.classList.remove("hidden");
        const zipState = result.zip_submission;
        if (zipState?.eligible) {
          const remaining = Math.max(0, Number(zipState.limit) - Number(zipState.count));
          box.textContent = `Đã nhận bài ${zipState.count}/${zipState.limit}. Bạn còn ${remaining} lượt nộp trước thời hạn.`;
          const allowance = document.getElementById("zip-submission-allowance");
          if (allowance) allowance.textContent = `Đã nộp ${zipState.count}/${zipState.limit} lượt; còn ${remaining} lượt.`;
          window.cssToast("Đã nhận bài. Bạn vẫn có thể tiếp tục làm bài.", "success");
          form.reset();
        } else {
          box.textContent = `Đã nhận bài: ${result.submission.filename} (${result.submission.size_bytes} bytes).`;
          window.cssToast("Nộp bài thành công.", "success");
          await window.completeOfficialExam();
        }
      } catch (error) {
        window.cssToast(error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  }
})();
