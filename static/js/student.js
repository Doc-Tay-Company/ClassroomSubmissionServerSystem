(async function () {
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
  const sendTelemetry = async () => {
    const form = new URLSearchParams({
      visibility: document.visibilityState,
      focused: String(document.hasFocus()),
      tab_count: String(updateTabs()),
      browser: navigator.userAgent,
    });
    try {
      await window.cssRequest("/api/student/telemetry", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form,
      });
    } catch (error) { reportBackgroundError("Student telemetry", error); }
  };
  const heartbeat = async () => {
    try {
      await sendTelemetry();
      const status = await window.cssRequest("/api/student/status");
      const box = document.getElementById("student-notifications");
      if (box && status.notifications?.length) {
        box.className = "alert alert-info";
        box.innerHTML = status.notifications.map((item) =>
          `<div><strong>Thông báo</strong>: ${window.cssEscape(item.message)}</div>`).join("");
      }
      const panel = document.getElementById("student-panel");
      const waiting = panel && ["idle", "ended", "distributed"].includes(panel.dataset.examState);
      const published = (status.published_exams || []).map((item) => item.id).sort().join(",");
      if (waiting && (status.exam_state === "started" || (panel.dataset.published ?? published) !== published)) window.location.reload();
    } catch (error) { reportBackgroundError("Student heartbeat", error); }
  };
  document.addEventListener("visibilitychange", sendTelemetry);
  window.addEventListener("focus", sendTelemetry);
  window.addEventListener("blur", sendTelemetry);
  window.addEventListener("storage", sendTelemetry);
  heartbeat();
  setInterval(heartbeat, 15000);

  const start = document.getElementById("start-exam");
  if (start) {
    start.addEventListener("click", async () => {
      start.disabled = true;
      const password = document.getElementById("exam-password")?.value || "";
      const form = new FormData();
      form.append("exam_password", password);
      try {
        await window.cssRequest("/api/student/start", { method: "POST", body: form });
        window.location.reload();
      } catch (error) {
        window.cssToast(error.message, "error");
        start.disabled = false;
      }
    });
  }

  const countdown = document.getElementById("countdown");
  if (countdown && !document.getElementById("student-code-root")) {
    let remaining = Number(countdown.dataset.remaining || 0);
    const draw = () => {
      const minutes = Math.floor(remaining / 60);
      const seconds = remaining % 60;
      countdown.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
      countdown.classList.toggle("countdown-warning", remaining <= 300);
      if (remaining <= 0) countdown.textContent = "Hết giờ";
    };
    draw();
    setInterval(() => { if (remaining > 0) remaining--; draw(); }, 1000);
    setInterval(async () => {
      try {
        const status = await window.cssRequest("/api/student/status");
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
        box.textContent = `Đã nhận bài: ${result.submission.filename} (${result.submission.size_bytes} bytes).`;
        window.cssToast("Nộp bài thành công.", "success");
      } catch (error) {
        window.cssToast(error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  }
})();
