(function (global) {
  // Entry UI consumes authoritative status; it does not change tab detection or Exam authorization.
  global.createExamEntry = function ({ getTabCount, startRequest, recordEvent, reload, reportError }) {
    const byId = (id) => document.getElementById(id);
    const start = byId("start-exam");
    const precheck = byId("exam-tab-warning");
    const gate = byId("exam-fullscreen-gate");
    const workspace = byId("student-panel");
    const zipExam = workspace?.dataset?.zipExam === "true";
    const target = document.documentElement;
    let active = false;
    let release = null;
    let wasFullscreen = false;
    let starting = false;
    let requesting = false;
    let leaving = false;
    let expiresAt = null;
    let expiryTimer = null;
    const fullscreen = () => document.fullscreenElement === target;
    const updateHeader = () => byId("student-header-actions")?.classList.toggle("hidden", active && fullscreen() && workspace?.dataset?.homeView !== "true");
    const setBlocked = (blocked) => { if (workspace) workspace.inert = blocked; };
    const showGate = (message, recovery = false) => {
      if (!active || !gate) return;
      setBlocked(true);
      byId("exam-fullscreen-message").textContent = message;
      byId("exam-fullscreen-choices").hidden = recovery;
      byId("exam-fullscreen-return").hidden = !recovery;
      if (!gate.open) gate.showModal();
    };
    const requireFullscreen = () => showGate("Bạn cần bật toàn màn hình để tiếp tục làm bài thi chính thức.");
    const unlock = () => {
      updateHeader();
      setBlocked(false);
      if (gate?.open) gate.close();
    };
    const submitStart = async (confirmedMultipleTabs) => {
      try {
        await startRequest(confirmedMultipleTabs);
        reload();
      } catch (error) {
        reportError(error);
        starting = false;
        if (start) start.disabled = false;
      }
    };
    start?.addEventListener("click", () => {
      if (starting) return;
      starting = true;
      start.disabled = true;
      if (getTabCount() > 1 && !zipExam) precheck.showModal();
      else void submitStart(false);
    });
    const cancelPrecheck = () => {
      if (precheck?.open) precheck.close();
      starting = false;
      if (start) start.disabled = false;
    };
    byId("exam-tab-cancel")?.addEventListener("click", cancelPrecheck);
    precheck?.addEventListener("cancel", (event) => { event.preventDefault(); cancelPrecheck(); });
    byId("exam-tab-continue")?.addEventListener("click", () => {
      if (!starting || !precheck.open) return;
      precheck.close();
      void submitStart(true);
    });
    gate?.addEventListener("cancel", (event) => event.preventDefault());
    gate?.addEventListener("close", () => {
      if (active && !fullscreen()) requireFullscreen();
    });
    byId("exam-fullscreen-agree")?.addEventListener("click", async () => {
      if (!active || requesting) return;
      requesting = true;
      const requestedRelease = release;
      try {
        if (!target.requestFullscreen) throw new Error("Trình duyệt không hỗ trợ Fullscreen API.");
        // Must be invoked before any await, directly in the click's user activation.
        await target.requestFullscreen();
        if (!active || release !== requestedRelease) return;
        if (!fullscreen()) throw new Error("Trình duyệt chưa kích hoạt toàn màn hình.");
        wasFullscreen = true;
        unlock();
      } catch (_) {
        if (active && release === requestedRelease) {
          recordEvent("fullscreen_request_failed");
          showGate("Không thể bật toàn màn hình. Hãy kiểm tra quyền hoặc hỗ trợ của trình duyệt rồi thử lại. Đây là lỗi kỹ thuật.", true);
        }
      } finally { requesting = false; }
    });
    byId("exam-fullscreen-refuse")?.addEventListener("click", () => {
      if (!active || requesting || byId("exam-fullscreen-choices").hidden) return;
      recordEvent("fullscreen_refused");
      showGate("Toàn màn hình là bắt buộc. Bạn chưa thể tiếp tục làm bài. Chọn Quay lại làm bài để yêu cầu lại.", true);
    });
    byId("exam-fullscreen-return")?.addEventListener("click", requireFullscreen);
    document.addEventListener("fullscreenchange", () => {
      if (!active || leaving) return;
      const current = fullscreen();
      const lost = wasFullscreen && !current;
      wasFullscreen = current;
      if (current) unlock();
      else {
        updateHeader();
        requireFullscreen();
        const lostRelease = release;
        if (lost) global.setTimeout(() => {
          if (active && release === lostRelease && !leaving) recordEvent("fullscreen_lost");
        }, 0);
      }
    });
    global.addEventListener("pagehide", () => { leaving = true; });
    global.addEventListener("beforeunload", () => { leaving = true; });
    global.addEventListener("pageshow", () => {
      leaving = false;
      wasFullscreen = fullscreen();
      if (active && !wasFullscreen) requireFullscreen();
    });
    return {
      setStatus(status) {
        const next = status.active_exam_attempt === true && !status.exam_file;
        if (next && (!active || release !== status.release_id)) wasFullscreen = fullscreen(); // restore baseline, never an exit event
        active = next;
        release = next ? status.release_id : null;
        expiresAt = next ? Date.parse(status.ends_at) : null;
        global.clearTimeout(expiryTimer);
        if (next && Number.isFinite(expiresAt)) {
          const remaining = expiresAt - (Date.parse(status.server_time) || Date.now());
          expiryTimer = global.setTimeout(() => { active = false; unlock(); }, Math.max(0, remaining));
        }
        if (!next || fullscreen()) unlock();
        else if (!gate?.open) requireFullscreen();
      },
    };
  };
})(window);
