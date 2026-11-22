(function () {
  "use strict";

  let practiceAccess = null;
  function getRequest() {
    return practiceAccess ? practiceAccess.request : getBaseRequest();
  }
  function getBaseRequest() {
    return window.cssRequest || (async (url, options) => {
      const res = await fetch(url, options);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const err = new Error(data.detail || `HTTP ${res.status}`);
        err.status = res.status;
        err.code = data.code;
        throw err;
      }
      return data;
    });
  }

  function getEscape() {
    return window.cssEscape || ((str) => {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    });
  }

  function generateHex32() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID().replace(/-/g, "");
    }
    const bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    }
    return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  // --- State ---
  let catalog = [];
  let catalogToken = null;
  let catalogPollTimer = null;
  let catalogPollInFlight = false;
  let catalogPollPending = false;
  let catalogPollingStopped = false;
  let catalogRequestGeneration = 0;
  let openPreviewQuestionId = null;
  let workspaceUnavailable = false;
  let currentFilter = {
    search: "",
    language: "",
    difficulty: "",
  };

  let currentView = "library"; // "library" | "workspace"
  let currentQuestion = null;
  let currentAttemptId = null;
  let needsRetest = false;
  let questionDetailsVerified = true;
  let updateCommittedUnloaded = false;
  let tabDraftId = null;
  let runBusy = false;
  let activeRun = false;
  let runStatusChecked = false;
  let runStatusTimer = null;
  let workspaceGeneration = 0;
  let attemptConflict = false;
  let hasApplicableResult = false;

  // --- DOM Elements ---
  let root = null;
  let libraryView = null;
  let workspaceView = null;
  let listHost = null;
  let noticeHost = null;
  let modalHost = null;
  let searchInput = null;
  let langFilter = null;
  let diffFilter = null;
  let refreshBtn = null;

  // Workspace DOM
  let wsTitle = null;
  let wsLangBadge = null;
  let wsDiffBadge = null;
  let wsCatBadge = null;
  let wsPoints = null;
  let wsRetestBadge = null;
  let wsUpdateBtn = null;
  let wsBackBtn = null;
  let wsStatement = null;
  let wsTargetSection = null;
  let wsTargetInfo = null;
  let wsStarterSection = null;
  let wsStarterCode = null;
  let wsTestsTableHost = null;
  let wsEditorLangLabel = null;
  let wsEditorFilename = null;
  let wsEditor = null;
  let wsRestoreStarterBtn = null;
  let wsRunBtn = null;
  let wsEditorAlert = null;
  let wsRunResult = null;
  let wsStorageWarning = null;
  let wsRevisionNotice = null;
  let wsRevisionNoticeText = null;
  let wsRetryDetailsBtn = null;

  function getStudentId() {
    return (root && root.dataset && root.dataset.studentId) || "anonymous";
  }

  // --- Local Storage Helpers ---
  function getTabDraftId() {
    if (tabDraftId) return tabDraftId;
    try {
      const key = "css_practice_tab_draft_id";
      tabDraftId = window.sessionStorage.getItem(key);
      if (!tabDraftId) {
        tabDraftId = generateHex32();
        window.sessionStorage.setItem(key, tabDraftId);
      }
    } catch (e) {
      // If sessionStorage is blocked, this page instance still gets isolated in-memory state.
      tabDraftId = generateHex32();
    }
    return tabDraftId;
  }

  function tabDraftKey(studentId, qid) {
    return `css_practice_draft:${studentId}:${qid}:tab:${getTabDraftId()}`;
  }

  function saveDraftToStorage(qid, attemptId, draft) {
    try {
      const studentId = getStudentId();
      localStorage.setItem(tabDraftKey(studentId, qid), JSON.stringify(draft));
      hideStorageWarning();
      return true;
    } catch (e) {
      showStorageWarning("Trình duyệt không cho phép lưu trữ cục bộ (localStorage). Code của bạn vẫn hiển thị nhưng sẽ mất nếu tải lại trang.");
      return false;
    }
  }

  function loadDraftFromStorage(qid, attemptId) {
    try {
      const studentId = getStudentId();
      let raw = localStorage.getItem(tabDraftKey(studentId, qid));
      if (!raw) {
        // One-time compatibility for drafts written before tab-local keys were introduced.
        const oldAttempt = localStorage.getItem(`css_practice_active_attempt:${studentId}:${qid}`);
        if (oldAttempt) {
          raw = localStorage.getItem(`css_practice_draft:${studentId}:${qid}:${oldAttempt}`);
          if (raw) localStorage.setItem(tabDraftKey(studentId, qid), raw);
        }
      }
      if (!raw) return null;
      const draft = JSON.parse(raw);
      return !attemptId || draft.attempt_id === attemptId ? draft : null;
    } catch (e) {
      return null;
    }
  }

  function getStoredActiveAttemptId(qid) {
    try {
      const draft = loadDraftFromStorage(qid, null);
      return draft && draft.attempt_id ? draft.attempt_id : null;
    } catch (e) {
      return null;
    }
  }

  function clearStoredAttempt(qid, attemptId) {
    try {
      const studentId = getStudentId();
      const draft = loadDraftFromStorage(qid, null);
      if (!draft || draft.attempt_id === attemptId) localStorage.removeItem(tabDraftKey(studentId, qid));
    } catch (e) {}
  }

  function clearAllStoredForQuestion(qid) {
    try {
      const studentId = getStudentId();
      localStorage.removeItem(`css_practice_active_attempt:${studentId}:${qid}`);
      const prefix = `css_practice_draft:${studentId}:${qid}:`;
      const keysToRemove = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(prefix)) keysToRemove.push(k);
      }
      keysToRemove.forEach((k) => localStorage.removeItem(k));
    } catch (e) {}
  }

  function showStorageWarning(msg) {
    if (!wsStorageWarning) return;
    wsStorageWarning.textContent = msg || "Cảnh báo: Không thể truy cập lưu trữ cục bộ.";
    wsStorageWarning.classList.remove("hidden");
  }

  function hideStorageWarning() {
    if (!wsStorageWarning) return;
    wsStorageWarning.classList.add("hidden");
  }

  function setNotice(message, isError) {
    if (!noticeHost) return;
    if (!message) {
      noticeHost.className = "hidden";
      noticeHost.textContent = "";
      return;
    }
    noticeHost.className = isError ? "alert alert-warning mb-4" : "alert alert-info mb-4";
    noticeHost.textContent = message;
  }

  // --- Percentage Color Helper (Owner-approved) ---
  function getScoreColorClass(percentage) {
    if (percentage === null || percentage === undefined) return "practice-pill-neutral";
    if (percentage >= 100) return "practice-pill-green";
    if (percentage >= 50) return "practice-pill-orange"; // Exactly 50% is light orange
    return "practice-pill-red";
  }

  function getProgressBarColorClass(percentage) {
    if (percentage === null || percentage === undefined) return "fill-neutral";
    if (percentage >= 100) return "fill-green";
    if (percentage >= 50) return "fill-orange"; // Exactly 50% is light orange
    return "fill-red";
  }

  function getValidScore(progress) {
    if (!progress || progress.score_available === false) return null;
    const value = progress.practice_percentage;
    return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
  }

  function updateRunButton() {
    if (!wsRunBtn) return;
    const canRun = Boolean(currentQuestion && !workspaceUnavailable && questionDetailsVerified && currentAttemptId &&
      (hasApplicableResult || needsRetest) && !attemptConflict && !runBusy && !activeRun && runStatusChecked);
    wsRunBtn.disabled = !canRun;
    wsRunBtn.setAttribute("aria-disabled", String(!canRun));
    if (!currentAttemptId) wsRunBtn.title = "Edit the starter code before the first Practice Run.";
    else if (!hasApplicableResult && !needsRetest) wsRunBtn.title = "Edit the code before the first Run Test for this attempt.";
    else if (!questionDetailsVerified) wsRunBtn.title = "Verify the latest question content before running.";
    else wsRunBtn.title = "";
    wsRunBtn.innerHTML = runBusy || activeRun
      ? '<i class="fa fa-spinner fa-spin"></i> Processing…'
      : '<i class="fa fa-play"></i> Chạy thử (Run Test)';
  }

  function renderRunResult(progress) {
    if (!wsRunResult) return;
    if (!progress || progress.has_result !== true) {
      wsRunResult.classList.add("hidden");
      wsRunResult.innerHTML = "";
      return;
    }
    wsRunResult.innerHTML = renderPracticeResult(progress, "Kết quả chạy thử", needsRetest);
    wsRunResult.classList.remove("hidden");
  }

  function feedbackPassed(row) {
    return row.passed ?? (row.verdict === "AC");
  }

  function renderPracticeResult(progress, title, stale = false) {
    const escape = getEscape();
    const pct = getValidScore(progress);
    const rows = Array.isArray(progress.result_summary)
      ? progress.result_summary.filter((row) => row && typeof row === "object")
      : [];
    const allPassed = pct === 100 && rows.every(feedbackPassed);
    const statusClass = pct === null ? "status-gray" : allPassed ? "status-green" : "status-red";
    const statusLabel = pct === null ? "Chưa tính điểm" : allPassed ? "Đạt toàn bộ" : "Chưa đạt";
    const points = pct === null ? "" : `Điểm ${escape(progress.earned_visible_points ?? "—")} / ${escape(progress.maximum_visible_points ?? "—")} (${pct}%)`;
    const diagnostic = progress.run_diagnostic;
    const runDiagnostic = typeof diagnostic === "string" && diagnostic && !rows.some((row) => row.diagnostic === diagnostic)
      ? `<div class="alert alert-warning"><strong>Chi tiết lỗi chạy thử</strong>${renderFeedbackValue(diagnostic, escape)}</div>`
      : "";
    return `
      <h3 class="practice-result-title">${escape(title)}</h3>
      <p class="practice-result-summary"><span class="status-pill ${statusClass}">${statusLabel}</span>${points}</p>
      ${stale ? '<p class="alert alert-warning">Mã đã thay đổi từ lần chấm này. Hãy chạy thử lại.</p>' : ""}
      ${runDiagnostic}
      ${renderFeedbackTable(rows, escape)}
    `;
  }

  function renderFeedbackValue(value, escape) {
    if (typeof value !== "string") return "—";
    return `<pre class="practice-feedback-output">${value === "" ? "(trống)" : escape(value)}</pre>`;
  }

  function renderFeedbackTable(rows, escape) {
    if (!rows.length) return "";
    const body = rows.map((row) => {
      const passed = feedbackPassed(row);
      const verdict = row.verdict || (passed ? "AC" : "WA");
      const points = row.points_earned == null && row.points == null
        ? "—"
        : `${escape(row.points_earned ?? "—")} / ${escape(row.points ?? "—")}`;
      return `
        <tr>
          <td><strong>${escape(row.id || "")}</strong></td>
          <td><span class="status-pill ${passed ? "status-green" : "status-red"}">${passed ? "Đạt" : "Sai"}</span>
            <small class="muted practice-feedback-verdict">${escape(verdict)}</small></td>
          <td>${points}</td>
          <td>${renderFeedbackValue(row.expected_output ?? row.expected, escape)}</td>
          <td>${renderFeedbackValue(row.actual_output ?? row.actual, escape)}</td>
          <td>${renderFeedbackValue(row.diagnostic, escape)}</td>
        </tr>
      `;
    }).join("");
    const headers = ["Test case", "Kết quả", "Điểm", "Kỳ vọng", "Thực tế", "Lỗi"];
    return `
      <div class="table-scroll practice-feedback-scroll" tabindex="0" role="region" aria-label="Chi tiết từng test case">
        <table class="data-table practice-feedback-table">
          <thead><tr>${headers.map((label) => `<th scope="col">${label}</th>`).join("")}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  function setRunMessage(message, isError = false) {
    if (!wsEditorAlert) return;
    wsEditorAlert.textContent = message || "";
    wsEditorAlert.className = message ? (isError ? "notice notice-error" : "notice") : "notice hidden";
  }

  async function refreshRunStatus(questionId, generation = workspaceGeneration) {
    if (runStatusTimer) {
      window.clearTimeout(runStatusTimer);
      runStatusTimer = null;
    }
    if (!questionId || generation !== workspaceGeneration) return;
    try {
      const request = getRequest();
      const status = await request(`/api/student/practice/questions/${encodeURIComponent(questionId)}/run-status`);
      if (generation !== workspaceGeneration || !currentQuestion || currentQuestion.question_id !== questionId) return;
      const wasActive = activeRun;
      activeRun = status.active === true;
      runStatusChecked = true;
      const serverAttempt = status.attempt_id;
      if (activeRun && currentAttemptId && serverAttempt && currentAttemptId !== serverAttempt) {
        try {
          await refreshProgressCatalog();
          if (generation !== workspaceGeneration) return;
          const item = catalog.find((entry) => entry.question_id === questionId);
          if (item && item.progress) syncAttemptFromProgress(item.progress);
        } catch (error) {
          attemptConflict = true;
          setRunMessage(`Could not synchronize the current attempt: ${error.message}. Your local code is preserved.`, true);
        }
      }
      updateRunButton();
      if (activeRun) {
        runStatusTimer = window.setTimeout(() => refreshRunStatus(questionId, generation), 1000);
      } else if (wasActive) {
        try {
          await refreshProgressCatalog();
          renderCatalog();
        } catch (error) {
          setRunMessage(`Could not refresh Practice progress: ${error.message}. Your local code is preserved.`, true);
        }
        if (generation !== workspaceGeneration || !currentQuestion || currentQuestion.question_id !== questionId) return;
        const item = catalog.find((entry) => entry.question_id === questionId);
        const progress = item && item.progress;
        if (progress) syncAttemptFromProgress(progress);
        updateRunButton();
      }
    } catch (error) {
      if (generation !== workspaceGeneration) return;
      runStatusChecked = false;
      updateRunButton();
      setRunMessage(`Could not confirm Practice Run status: ${error.message}. Retry shortly.`, true);
      runStatusTimer = window.setTimeout(() => refreshRunStatus(questionId, generation), 3000);
    }
  }

  async function runPractice() {
    if (!currentQuestion || !questionDetailsVerified || !currentAttemptId || attemptConflict || runBusy || activeRun || !runStatusChecked) {
      if (currentQuestion && !currentAttemptId) setRunMessage("Edit the starter code before the first Run Test.", true);
      return;
    }
    if (!hasApplicableResult && !needsRetest) {
      setRunMessage("Edit the code before the first Run Test for this attempt.", true);
      return;
    }
    const request = getRequest();
    const questionId = currentQuestion.question_id;
    const revision = currentQuestion.practice_revision;
    const attemptId = currentAttemptId;
    const submittedSource = wsEditor.value;
    const generation = workspaceGeneration;
    runBusy = true;
    updateRunButton();
    setRunMessage("Practice Run is processing. Your code remains editable and is saved locally.");
    try {
      const response = await request("/api/student/practice/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: questionId, expected_practice_revision: revision, attempt_id: attemptId, source_code: submittedSource }),
      });
      if (generation !== workspaceGeneration || !currentQuestion || currentQuestion.question_id !== questionId || currentAttemptId !== attemptId || currentQuestion.practice_revision !== revision) return;
      if (!response || response.completed !== true || response.attempt_id !== attemptId || response.practice_revision !== revision) {
        throw new Error("The server response did not match this question attempt.");
      }
      needsRetest = wsEditor.value !== submittedSource;
      persistCurrentDraft();
      updateRetestBadge();
      renderRunResult({
        has_result: true,
        score_available: response.score_available,
        practice_percentage: response.practice_percentage,
        earned_visible_points: response.earned_visible_points,
        maximum_visible_points: response.maximum_visible_points,
        result_summary: response.results,
        run_diagnostic: response.run_diagnostic,
      });
      hasApplicableResult = true;
      hasApplicableResult = true;
      setRunMessage(needsRetest ? "Run completed for the submitted code. The current edited code still needs testing." : "Run completed.");
      await loadCatalog();
    } catch (error) {
      if (error && error.status === 409 && generation === workspaceGeneration && currentQuestion && currentQuestion.question_id === questionId) {
        try {
          await refreshProgressCatalog();
          if (generation === workspaceGeneration && currentQuestion && currentQuestion.question_id === questionId) {
            const item = catalog.find((entry) => entry.question_id === questionId);
            if (item && item.progress) {
              const recovered = syncAttemptFromProgress(item.progress);
              if (recovered) setRunMessage("This tab is using the current attempt now. Your local code was preserved; run again when ready.");
            }
          }
        } catch (refreshError) {
          // Keep the request error and local draft; a later Workspace open can retry recovery.
        }
      }
      if (generation === workspaceGeneration && currentQuestion && currentQuestion.question_id === questionId && currentAttemptId === attemptId) {
        setRunMessage(error.message || "Practice Run failed. Your previous valid result was retained.", true);
      }
    } finally {
      if (generation === workspaceGeneration) {
        runBusy = false;
        activeRun = false;
        updateRunButton();
        if (currentQuestion && currentQuestion.question_id === questionId) await refreshRunStatus(questionId, generation);
      }
    }
  }

  // --- Catalog & Progress Loading ---
  async function loadCatalog() {
    const request = getRequest();
    const escape = getEscape();
    setNotice("", false);
    if (listHost) {
      listHost.innerHTML = '<p class="muted pad"><i class="fa fa-spinner fa-spin"></i> Đang tải danh sách câu hỏi...</p>';
    }
    try {
      await refreshProgressCatalog();
      renderCatalog();
      reconcileWorkspaceCatalog();
      refreshOpenPreview();
    } catch (error) {
      if (listHost) {
        listHost.innerHTML = `<div class="alert alert-warning"><i class="fa fa-exclamation-triangle"></i> Không thể tải danh sách luyện tập: ${escape(error.message)}</div>`;
      }
    }
  }

  async function refreshProgressCatalog() {
    const request = getRequest();
    const generation = ++catalogRequestGeneration;
    const data = await request("/api/student/practice/progress");
    if (generation !== catalogRequestGeneration) return false;
    catalog = Array.isArray(data.progress) ? data.progress : [];
    if (typeof data.catalog_token === "string") catalogToken = data.catalog_token;
    return true;
  }

  const CATALOG_POLL_INTERVAL_MS = 15000;

  function clearCatalogPollTimer() {
    if (catalogPollTimer !== null) {
      window.clearTimeout(catalogPollTimer);
      catalogPollTimer = null;
    }
  }

  function canPollCatalog() {
    return !catalogPollingStopped && document.visibilityState !== "hidden";
  }

  function scheduleCatalogPoll(delay = CATALOG_POLL_INTERVAL_MS) {
    clearCatalogPollTimer();
    if (!canPollCatalog()) return;
    catalogPollTimer = window.setTimeout(() => {
      catalogPollTimer = null;
      pollCatalogChanges();
    }, delay);
    if (catalogPollTimer && typeof catalogPollTimer.unref === "function") catalogPollTimer.unref();
  }

  async function pollCatalogChanges() {
    if (!canPollCatalog()) return false;
    if (catalogPollInFlight) {
      catalogPollPending = true;
      return false;
    }
    catalogPollInFlight = true;
    const request = getRequest();
    try {
      if (practiceAccess && !await practiceAccess.check()) return false;
      const accessRecovered = practiceAccess?.needsRecovery();
      const response = await request("/api/student/practice/questions");
      if (!canPollCatalog()) return false;
      const observedToken = response && response.catalog_token;
      if (typeof observedToken !== "string") throw new Error("The Practice catalog response has no change token.");
      if (observedToken === catalogToken && !accessRecovered) {
        if (noticeHost && noticeHost.textContent.includes("synchronization is temporarily unavailable")) setNotice("", false);
        return true;
      }

      // Progress carries the token computed from the same Question Bank snapshot.
      const generation = ++catalogRequestGeneration;
      const progressResponse = await request("/api/student/practice/progress");
      if (!canPollCatalog() || generation !== catalogRequestGeneration) return false;
      if (!progressResponse || !Array.isArray(progressResponse.progress) || typeof progressResponse.catalog_token !== "string") {
        throw new Error("The updated Practice catalog could not be verified.");
      }

      catalog = progressResponse.progress;
      catalogToken = progressResponse.catalog_token;
      practiceAccess?.acknowledgeRecovery();
      renderCatalog();
      reconcileWorkspaceCatalog();
      refreshOpenPreview();
      setNotice("", false);
      return true;
    } catch (error) {
      if (canPollCatalog()) setNotice("Practice synchronization is temporarily unavailable. Your current work is preserved; retrying automatically.", true);
      return false;
    } finally {
      catalogPollInFlight = false;
      const refreshWasRequested = catalogPollPending;
      catalogPollPending = false;
      scheduleCatalogPoll(refreshWasRequested ? 0 : CATALOG_POLL_INTERVAL_MS);
    }
  }

  function renderWorkspaceQuestionGrid(questionId) {
    const grid = document.getElementById("practice-question-grid");
    if (!grid) return;
    const escape = getEscape();
    grid.innerHTML = catalog.map((item, index) => `
      <button type="button" class="btn btn-secondary" data-question-id="${escape(item.question_id)}"
        ${item.question_id === questionId ? 'aria-current="true"' : ""}
        ${!item.available ? "disabled" : ""}>
        <strong>Câu ${index + 1}: ${escape(item.title || item.question_id)}</strong>
        ${!item.available ? "<small>Không khả dụng</small>" : ""}
      </button>`).join("");
    grid.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.questionId !== questionId) openWorkspace(button.dataset.questionId);
      });
    });
  }

  function reconcileWorkspaceCatalog() {
    if (currentView !== "workspace" || !currentQuestion) return;
    renderWorkspaceQuestionGrid(currentQuestion.question_id);
    const item = catalog.find((entry) => entry.question_id === currentQuestion.question_id);
    const unavailable = !item || item.available !== true;
    if (unavailable) {
      workspaceUnavailable = true;
      attemptConflict = true;
      wsUpdateBtn?.classList.add("hidden");
      if (wsRevisionNotice && wsRevisionNoticeText) {
        wsRevisionNoticeText.textContent = "Question unavailable. Your current question view and local code are preserved; new Runs are disabled.";
        wsRevisionNotice.classList.remove("hidden");
      }
      updateRunButton();
      return;
    }

    const changed = item.practice_revision !== currentQuestion.practice_revision;
    const wasUnavailable = workspaceUnavailable;
    workspaceUnavailable = false;
    if (changed) {
      attemptConflict = true;
      wsUpdateBtn?.classList.remove("hidden");
      if (wsRevisionNotice && wsRevisionNoticeText) {
        wsRevisionNoticeText.textContent = "Question content has changed. Choose Update when you are ready; your local code and current result are preserved.";
        wsRevisionNotice.classList.remove("hidden");
      }
    } else if (wasUnavailable) {
      // Availability was restored without replacing the open snapshot or source.
      if (wsRevisionNotice && wsRevisionNoticeText && wsRevisionNoticeText.textContent.startsWith("Question unavailable.")) {
        wsRevisionNotice.classList.add("hidden");
      }
      attemptConflict = false;
      wsUpdateBtn?.classList.add("hidden");
    }
    updateRunButton();
  }

  function refreshOpenPreview() {
    if (!openPreviewQuestionId || !modalHost || modalHost.classList.contains("hidden")) return;
    const item = catalog.find((entry) => entry.question_id === openPreviewQuestionId);
    if (item) openPreviewModal(item);
    else closeModal();
  }

  function stopCatalogPolling() {
    catalogPollingStopped = true;
    clearCatalogPollTimer();
  }

  function syncAttemptFromProgress(progress) {
    if (!progress || !currentQuestion || !progress.attempt_id) return false;
    const questionId = currentQuestion.question_id;
    const localDraft = loadDraftFromStorage(questionId, null);
    const sameRevision = progress.practice_revision === currentQuestion.practice_revision;
    const localDraftNeedsUpdate = Boolean(localDraft && localDraft.practice_revision &&
      localDraft.practice_revision !== currentQuestion.practice_revision);
    const attemptChanged = currentAttemptId !== progress.attempt_id;

    if (attemptChanged) {
      currentAttemptId = progress.attempt_id;
      if (localDraft) {
        localDraft.attempt_id = progress.attempt_id;
        saveDraftToStorage(questionId, progress.attempt_id, localDraft);
      }
    }

    attemptConflict = !sameRevision || localDraftNeedsUpdate;
    if (attemptConflict) {
      hasApplicableResult = false;
      wsUpdateBtn?.classList.remove("hidden");
      if (wsRevisionNotice && wsRevisionNoticeText) {
        wsRevisionNoticeText.textContent = "Question content has changed. Update it before running; your local code is preserved.";
        wsRevisionNotice.classList.remove("hidden");
      }
      setRunMessage("This question revision needs an Update before it can be run. Your local code and current attempt are preserved.", true);
    } else {
      hasApplicableResult = progress.has_result === true;
      renderRunResult(progress);
    }
    updateRunButton();
    return !attemptConflict;
  }

  function filteredCatalog() {
    const q = (currentFilter.search || "").trim().toLowerCase();
    const lang = currentFilter.language;
    const diff = currentFilter.difficulty;

    return catalog.filter((item) => {
      if (lang && item.language !== lang) return false;
      if (diff && item.difficulty !== diff) return false;
      if (q) {
        const text = `${item.title || ""} ${item.category || ""}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }

  function renderCatalog() {
    if (!listHost) return;
    const escape = getEscape();
    const items = filteredCatalog();

    if (!catalog.length) {
      listHost.innerHTML = `
        <div class="empty-state">
          <i class="fa fa-book"></i>
          <h3>Chưa có câu hỏi luyện tập nào</h3>
          <p class="muted">Giảng viên chưa mở câu hỏi nào cho chế độ luyện tập. Vui lòng quay lại sau.</p>
        </div>`;
      return;
    }

    if (!items.length) {
      listHost.innerHTML = `
        <div class="empty-state">
          <i class="fa fa-search"></i>
          <h3>Không tìm thấy câu hỏi phù hợp</h3>
          <p class="muted">Hãy thử thay đổi từ khóa tìm kiếm hoặc bỏ bớt các bộ lọc.</p>
        </div>`;
      return;
    }

    listHost.innerHTML = items
      .map((item) => {
        const langBadge = item.language === "java" ? "badge-java" : "badge-python";
        const hasResult = item.progress && item.progress.has_result;
        const isUnavailable = !item.available;
        const isStaleRevision = item.available && hasResult && item.practice_revision !== item.progress.practice_revision;

        let scoreBadgeHtml = "";
        if (hasResult) {
          const pct = getValidScore(item.progress);
          if (pct === null) {
            scoreBadgeHtml = `<span class="practice-badge practice-pill-neutral">Not scored</span>`;
          } else {
            const colorCls = getScoreColorClass(pct);
            scoreBadgeHtml = `<span class="practice-badge ${colorCls}"><i class="fa fa-check-circle"></i> ${pct}%</span>`;
          }
        }

        let actionButtonsHtml = "";
        if (isUnavailable) {
          actionButtonsHtml = `
            <button type="button" class="btn btn-secondary btn-small open-preview-btn" data-qid="${escape(item.question_id)}">
              <i class="fa fa-info-circle"></i> Chi tiết
            </button>`;
        } else if (hasResult) {
          actionButtonsHtml = `
            <button type="button" class="btn btn-ghost btn-small open-preview-btn" data-qid="${escape(item.question_id)}">
              <i class="fa fa-eye"></i> Xem kết quả
            </button>
            <button type="button" class="btn btn-primary btn-small open-workspace-btn" data-qid="${escape(item.question_id)}">
              <i class="fa fa-code"></i> Vào bài làm
            </button>`;
        } else {
          actionButtonsHtml = `
            <button type="button" class="btn btn-primary btn-small open-workspace-btn" data-qid="${escape(item.question_id)}">
              <i class="fa fa-code"></i> Làm bài
            </button>`;
        }

        return `
          <div class="practice-card" data-qid="${escape(item.question_id)}">
            <div class="practice-card-title">
              <div>
                <span>${escape(item.title || item.question_id || "Câu hỏi không tên")}</span>
                ${isUnavailable ? `<span class="practice-badge badge-unavailable ml-2"><i class="fa fa-ban"></i> Câu hỏi không khả dụng</span>` : ""}
                ${isStaleRevision ? `<span class="practice-badge badge-updated ml-2"><i class="fa fa-exclamation-circle"></i> Đề đã cập nhật</span>` : ""}
              </div>
              <div class="practice-card-actions">
                ${scoreBadgeHtml}
                ${actionButtonsHtml}
              </div>
            </div>
            <div class="practice-meta">
              <span class="practice-badge ${langBadge}">${escape(item.language || "code").toUpperCase()}</span>
              ${item.difficulty ? `<span class="practice-badge badge-diff">${escape(item.difficulty)}</span>` : ""}
              ${item.category ? `<span class="practice-badge badge-diff"><i class="fa fa-folder-o"></i> ${escape(item.category)}</span>` : ""}
              <small class="muted">Phiên bản: ${escape(item.version || 1)}</small>
            </div>
          </div>
        `;
      })
      .join("");

    listHost.querySelectorAll(".open-workspace-btn").forEach((btn) => {
      btn.addEventListener("click", () => openWorkspace(btn.dataset.qid));
    });

    listHost.querySelectorAll(".open-preview-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = catalog.find((c) => c.question_id === btn.dataset.qid);
        if (item) openPreviewModal(item);
      });
    });
  }

  // --- Modal Previews ---
  function openPreviewModal(item) {
    if (!modalHost) return;
    openPreviewQuestionId = item.question_id;
    const escape = getEscape();
    const hasResult = item.progress && item.progress.has_result;
    const isUnavailable = !item.available;
    const isStaleRevision = item.available && hasResult && item.practice_revision !== item.progress.practice_revision;

    modalHost.className = "practice-modal-backdrop";

    if (isUnavailable) {
      // WP2.1: Exactly Delete and Cancel for unavailable question
      let resultDetailsHtml = "";
      if (hasResult) {
        const pct = getValidScore(item.progress);
        const colorCls = getScoreColorClass(pct);
        const barCls = getProgressBarColorClass(pct);
        resultDetailsHtml = pct === null ? `<div class="practice-section"><span class="practice-badge practice-pill-neutral">Not scored</span></div>` : `
          <div class="practice-section">
            <h3 class="practice-section-title">Kết quả lần làm trước</h3>
            <div class="flex items-center gap-2 mb-2">
              <span class="practice-badge ${colorCls} text-sm">${pct}%</span>
              <small class="muted">${escape(item.progress.earned_visible_points || 0)} / ${escape(item.progress.maximum_visible_points || 0)} điểm</small>
            </div>
            <div class="practice-progress-bar">
              <div class="practice-progress-fill ${barCls}" data-pct="${Math.min(100, Math.max(0, pct))}"></div>
            </div>
          </div>
        `;
      }

      modalHost.innerHTML = `
        <div class="practice-modal">
          <div class="panel-heading practice-modal-panel-heading">
            <div>
              <h2 class="practice-modal-title">${escape(item.title || item.question_id)}</h2>
              <div class="practice-meta practice-modal-meta">
                <span class="practice-badge badge-unavailable"><i class="fa fa-ban"></i> Câu hỏi không khả dụng</span>
              </div>
            </div>
            <button type="button" class="btn btn-ghost modal-close-btn"><i class="fa fa-times"></i></button>
          </div>
          <div class="alert alert-warning mb-4">
            <i class="fa fa-exclamation-triangle"></i> Câu hỏi này hiện không còn khả dụng cho luyện tập (đã bị giảng viên tắt luyện tập hoặc thu hồi).
          </div>
          ${resultDetailsHtml}
          <div class="form-actions practice-modal-actions">
            <button type="button" class="btn btn-danger modal-delete-btn"><i class="fa fa-trash"></i> Xóa (Delete)</button>
            <button type="button" class="btn btn-secondary modal-close-btn">Hủy (Cancel)</button>
          </div>
        </div>
      `;

      modalHost.querySelector(".modal-delete-btn")?.addEventListener("click", () => {
        handleDeleteProgress(item.question_id);
      });
      modalHost.querySelectorAll(".modal-close-btn").forEach((b) => b.addEventListener("click", closeModal));
      return;
    }

    const resultSectionHtml = hasResult
      ? `<div class="practice-section">${renderPracticeResult(item.progress, "Kết quả hiện tại")}</div>`
      : "";

    let revisionAlertHtml = "";
    let actionButtonsHtml = "";

    if (isStaleRevision) {
      revisionAlertHtml = `
        <div class="alert alert-info mb-4">
          <i class="fa fa-info-circle"></i> Đề bài đã có phiên bản mới trong Question Bank. Điểm số cũ không còn hiệu lực. Bạn có thể cập nhật đề để tiếp tục làm (code của bạn sẽ được giữ nguyên).
        </div>
      `;
      actionButtonsHtml = `
        <button type="button" class="btn btn-warning modal-update-btn"><i class="fa fa-refresh"></i> Cập nhật đề (Update)</button>
        <button type="button" class="btn btn-primary modal-open-ws-btn"><i class="fa fa-code"></i> Vào bài làm</button>
        <button type="button" class="btn btn-ghost modal-close-btn">Đóng</button>
      `;
    } else {
      actionButtonsHtml = `
        <button type="button" class="btn btn-primary modal-open-ws-btn"><i class="fa fa-code"></i> Vào bài làm</button>
        <button type="button" class="btn btn-ghost modal-close-btn">Đóng</button>
      `;
    }

    modalHost.innerHTML = `
      <div class="practice-modal">
        <div class="panel-heading practice-modal-panel-heading">
          <div>
            <h2 class="practice-modal-title">${escape(item.title)}</h2>
            <div class="practice-meta practice-modal-meta">
              <span class="practice-badge ${item.language === "java" ? "badge-java" : "badge-python"}">${escape(item.language).toUpperCase()}</span>
              ${item.difficulty ? `<span class="practice-badge badge-diff">${escape(item.difficulty)}</span>` : ""}
              ${item.category ? `<span class="practice-badge badge-diff"><i class="fa fa-folder-o"></i> ${escape(item.category)}</span>` : ""}
              <small class="muted">Phiên bản: ${escape(item.version || 1)}</small>
            </div>
          </div>
          <button type="button" class="btn btn-ghost modal-close-btn"><i class="fa fa-times"></i></button>
        </div>
        ${revisionAlertHtml}
        ${resultSectionHtml}
        <div class="form-actions practice-modal-actions">
          ${actionButtonsHtml}
        </div>
      </div>
    `;

    modalHost.querySelector(".modal-update-btn")?.addEventListener("click", async () => {
      closeModal();
      await handleUpdate(item.question_id);
    });

    modalHost.querySelector(".modal-open-ws-btn")?.addEventListener("click", () => {
      closeModal();
      openWorkspace(item.question_id);
    });

    modalHost.querySelectorAll(".modal-close-btn").forEach((b) => b.addEventListener("click", closeModal));
  }

  function closeModal() {
    if (!modalHost) return;
    openPreviewQuestionId = null;
    modalHost.className = "hidden";
    modalHost.innerHTML = "";
  }

  // --- Deletion (Unavailable Question) ---
  async function handleDeleteProgress(questionId) {
    if (!window.confirm("Xóa bài làm này khỏi danh sách luyện tập của bạn? Bạn sẽ không thể khôi phục lại điểm số này.")) {
      return;
    }
    const request = getRequest();
    try {
      await request(`/api/student/practice/progress/${encodeURIComponent(questionId)}`, {
        method: "DELETE",
      });
      clearAllStoredForQuestion(questionId);
      closeModal();
      await loadCatalog();
    } catch (err) {
      alert(`Không thể xóa bài làm: ${err.message}`);
    }
  }

  // --- Update Action ---
  async function handleUpdate(questionId) {
    const request = getRequest();
    const localDraft = loadDraftFromStorage(questionId, null);
    const source = currentQuestion && currentQuestion.question_id === questionId
      ? wsEditor.value
      : (localDraft ? localDraft.source_code : null);

    try {
      const [questionData, progressData] = await Promise.all([
        request(`/api/student/practice/questions/${encodeURIComponent(questionId)}`),
        request("/api/student/practice/progress"),
      ]);
      const latestQuestion = questionData && questionData.question;
      const item = Array.isArray(progressData.progress)
        ? progressData.progress.find((entry) => entry.question_id === questionId)
        : null;
      const progress = item && item.progress;
      if (!latestQuestion || !item || item.available !== true || !progress || !progress.attempt_id) {
        throw new Error("Current question progress is unavailable. Refresh the Practice Library and try again.");
      }
      const oldRev = progress.practice_revision;
      const newRev = latestQuestion.practice_revision;
      if (!oldRev || !newRev || oldRev === newRev) {
        throw new Error("The question has no newer revision to apply. Refresh the Practice Library.");
      }

      await request(`/api/student/practice/questions/${encodeURIComponent(questionId)}/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_attempt_id: progress.attempt_id,
          old_practice_revision: oldRev,
          new_practice_revision: newRev,
        }),
      });
      updateCommittedUnloaded = true;
      workspaceUnavailable = false;

      await openWorkspace(questionId, {
        attempt_id: progress.attempt_id,
        practice_revision: newRev,
        source_code: source,
        needs_retest: true,
      });

      await loadCatalog();
    } catch (err) {
      if (err && err.status === 409) {
        await loadCatalog();
        alert(`Câu hỏi đã thay đổi trong lúc cập nhật. Mã nguồn của bạn được giữ nguyên. Hãy tải lại danh sách và thử lại. ${err.message}`);
      } else {
        alert(`Không thể cập nhật đề: ${err.message}`);
      }
    }
  }

  // --- Workspace View Logic ---
  async function openWorkspace(questionId, draftOverride) {
    // Dirty check if leaving another workspace
    if (currentView === "workspace" && currentQuestion && currentQuestion.question_id !== questionId) {
      if (!confirmLeaveWorkspace()) return;
    }

    const request = getRequest();
    const escape = getEscape();

    workspaceGeneration += 1;
    const generation = workspaceGeneration;
    if (runStatusTimer) window.clearTimeout(runStatusTimer);
    runStatusTimer = null;
    runBusy = false;
    activeRun = false;
    runStatusChecked = false;
    attemptConflict = false;
    hasApplicableResult = false;
    workspaceUnavailable = false;

    currentView = "workspace";
    questionDetailsVerified = false;
    libraryView.classList.add("hidden");
    workspaceView.classList.remove("hidden");
    window.location.hash = `q=${encodeURIComponent(questionId)}`;

    renderWorkspaceQuestionGrid(questionId);

    // Reset UI
    wsTitle.textContent = "Đang tải đề bài...";
    wsStatement.textContent = "";
    wsTestsTableHost.innerHTML = "";
    wsEditorAlert.classList.add("hidden");
    wsRunResult.classList.add("hidden");
    hideStorageWarning();
    wsRevisionNotice.classList.add("hidden");
    if (wsRetryDetailsBtn) wsRetryDetailsBtn.classList.add("hidden");
    wsUpdateBtn.classList.add("hidden");

    try {
      const data = await request(`/api/student/practice/questions/${encodeURIComponent(questionId)}`);
      currentQuestion = data.question;
      renderWorkspaceDetails(currentQuestion);
      questionDetailsVerified = true;
      updateCommittedUnloaded = false;
      if (draftOverride) {
        currentAttemptId = draftOverride.attempt_id;
        needsRetest = Boolean(draftOverride.needs_retest);
        wsEditor.value = draftOverride.source_code === null ? (currentQuestion.starter_code || "") : draftOverride.source_code;
        persistCurrentDraft(draftOverride.practice_revision || currentQuestion.practice_revision);
        updateRetestBadge();
      } else {
        restoreOrInitDraft(currentQuestion);
      }
      // Restore this tab's source first, then reconcile attempt metadata with
      // the current server record. Never copy source from another tab.
      await refreshProgressCatalog();
      if (generation !== workspaceGeneration) return;
      renderCatalog();
      const item = catalog.find((entry) => entry.question_id === questionId);
      const progress = item && item.progress;
      if (progress) syncAttemptFromProgress(progress);
      reconcileWorkspaceCatalog();
      if (!currentAttemptId) setRunMessage("Edit the starter code to begin an attempt and enable Run Test.");
      else if (!hasApplicableResult && !needsRetest) setRunMessage("Edit the code before the first Run Test for this attempt.");
      updateRunButton();
      await refreshRunStatus(questionId, generation);
    } catch (err) {
      wsTitle.textContent = "Không tìm thấy câu hỏi";
      wsStatement.textContent = `Lỗi: ${err.message}. Câu hỏi có thể không khả dụng hoặc đã bị thu hồi.`;
      if (draftOverride) {
        currentQuestion = { question_id: questionId, practice_revision: draftOverride.practice_revision, version: draftOverride.version, language: draftOverride.language, starter_code: "" };
        currentAttemptId = draftOverride.attempt_id;
        needsRetest = Boolean(draftOverride.needs_retest);
        wsEditor.value = draftOverride.source_code || "";
        persistCurrentDraft(draftOverride.practice_revision);
      }
      wsEditor.disabled = false;
      runStatusChecked = false;
      updateRunButton();
      showQuestionReloadFailure();
    }
  }

  async function reloadQuestionDetails(questionId, expectedRevision) {
    const request = getRequest();
    const source = currentQuestion && currentQuestion.question_id === questionId ? wsEditor.value : "";
    const attemptId = currentAttemptId;
    try {
      const data = await request(`/api/student/practice/questions/${encodeURIComponent(questionId)}`);
      if (expectedRevision && data.question.practice_revision !== expectedRevision) throw new Error("Question revision changed again; retry the update.");
      currentQuestion = data.question;
      renderWorkspaceDetails(currentQuestion);
      wsEditor.value = source;
      currentAttemptId = attemptId;
      needsRetest = true;
      questionDetailsVerified = true;
      persistCurrentDraft(currentQuestion.practice_revision);
      updateRetestBadge();
      if (wsRevisionNotice) {
        wsRevisionNoticeText.textContent = updateCommittedUnloaded
          ? "Question details are current. Your code was preserved; run it again after Practice execution becomes available."
          : "Question details were reloaded.";
        wsRevisionNotice.classList.remove("hidden");
      }
      updateCommittedUnloaded = false;
      if (wsRetryDetailsBtn) wsRetryDetailsBtn.classList.add("hidden");
      return true;
    } catch (e) {
      showQuestionReloadFailure(updateCommittedUnloaded);
      return false;
    }
  }

  function showQuestionReloadFailure(updateSucceeded = updateCommittedUnloaded) {
    questionDetailsVerified = false;
    if (wsRevisionNotice) {
      wsRevisionNoticeText.textContent = updateSucceeded
        ? "The progress update succeeded, but the latest question content could not be loaded. Your code is preserved; the displayed question is unverified and cannot be run. Retry loading the latest content."
        : "The latest question content could not be loaded. Your code is preserved; the displayed question is unverified. Retry loading the content.";
      wsRevisionNotice.classList.remove("hidden");
    }
    if (wsRetryDetailsBtn) wsRetryDetailsBtn.classList.remove("hidden");
  }

  async function retryQuestionDetails() {
    if (currentQuestion) await reloadQuestionDetails(currentQuestion.question_id, currentQuestion.practice_revision);
  }

  function renderWorkspaceDetails(q) {
    const escape = getEscape();
    wsTitle.textContent = q.title || q.question_id;
    wsLangBadge.textContent = (q.language || "").toUpperCase();
    wsLangBadge.className = `practice-badge ${q.language === "java" ? "badge-java" : "badge-python"}`;
    wsDiffBadge.textContent = q.difficulty || "Mặc định";
    wsCatBadge.textContent = q.category || "Chung";
    wsPoints.textContent = String(q.visible_points || 0);

    wsEditorLangLabel.textContent = q.language === "python" ? "Mã nguồn Python" : "Mã nguồn Java";
    wsEditorFilename.textContent = q.target_file || (q.language === "python" ? "solution.py" : (q.target_class ? `${q.target_class.split(".").pop()}.java` : "Solution.java"));

    wsStatement.textContent = q.statement || "(Trống)";

    // Reflection targets
    if (q.grading_mode === "reflection" && (q.target_class || q.target_package || q.target_file)) {
      wsTargetSection.classList.remove("hidden");
      wsTargetInfo.innerHTML = `
        ${q.target_package ? `<div><span class="practice-target-label">Package</span><code>${escape(q.target_package)}</code></div>` : ""}
        ${q.target_class ? `<div><span class="practice-target-label">Class</span><code>${escape(q.target_class)}</code></div>` : ""}
        ${q.target_file ? `<div><span class="practice-target-label">File</span><code>${escape(q.target_file)}</code></div>` : ""}
      `;
    } else {
      wsTargetSection.classList.add("hidden");
      wsTargetInfo.innerHTML = "";
    }

    // Starter code
    if (q.starter_code) {
      wsStarterSection.classList.remove("hidden");
      wsStarterCode.textContent = q.starter_code;
    } else {
      wsStarterSection.classList.add("hidden");
    }

    // Visible tests / checks
    const isReflection = q.grading_mode === "reflection";
    const items = isReflection ? q.checks || [] : q.tests || [];
    if (items.length) {
      wsTestsTableHost.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Tên</th>
              ${isReflection ? "<th>Mô tả</th>" : "<th>Input</th><th>Output mong đợi</th>"}
              <th>Điểm</th>
            </tr>
          </thead>
          <tbody>
            ${items
              .map((item) => `
              <tr>
                <td><strong>${escape(item.name || item.id || "")}</strong></td>
                ${
                  isReflection
                    ? `<td>${escape(item.description || "")}</td>`
                    : `<td><code>${escape(item.stdin ?? item.input ?? "(trống)")}</code></td><td><code>${escape(item.expected_stdout ?? item.expected_output ?? "(trống)")}</code></td>`
                }
                <td>${escape(item.points ?? 0)}</td>
              </tr>
            `)
              .join("")}
          </tbody>
        </table>
      `;
    } else {
      wsTestsTableHost.innerHTML = '<p class="muted">Không có test case công khai.</p>';
    }

    wsEditor.disabled = false;
    updateRunButton();
  }

  function restoreOrInitDraft(q) {
    const qid = q.question_id;
    const activeAttempt = getStoredActiveAttemptId(qid);
    let draft = null;

    if (activeAttempt) {
      draft = loadDraftFromStorage(qid, activeAttempt);
    }

    if (draft && draft.attempt_id) {
      currentAttemptId = draft.attempt_id;
      wsEditor.value = draft.source_code !== undefined ? draft.source_code : (q.starter_code || "");
      needsRetest = Boolean(draft.needs_retest);

      // Check revision mismatch between draft and Question Bank
      if (draft.practice_revision && draft.practice_revision !== q.practice_revision) {
        wsRevisionNoticeText.textContent = "Đề bài đã có phiên bản mới trong Question Bank. Hãy nhấn Cập nhật đề để làm bài trên đề mới.";
        wsRevisionNotice.classList.remove("hidden");
        wsUpdateBtn.classList.remove("hidden");
      }
    } else {
      // Reuse an already established Student–Question attempt without creating a new one.
      const item = catalog.find((entry) => entry.question_id === qid);
      currentAttemptId = item && item.progress && item.progress.attempt_id ? item.progress.attempt_id : null;
      wsEditor.value = q.starter_code || "";
      needsRetest = false;
    }

    updateRetestBadge();
  }

  function persistCurrentDraft(customRevision) {
    if (!currentQuestion || !currentAttemptId) return;
    const q = currentQuestion;
    const draft = {
      question_id: q.question_id,
      practice_revision: customRevision || q.practice_revision,
      version: q.version,
      language: q.language,
      source_code: wsEditor.value,
      needs_retest: needsRetest,
      attempt_id: currentAttemptId,
    };
    saveDraftToStorage(q.question_id, currentAttemptId, draft);
  }

  function updateRetestBadge() {
    if (!wsRetestBadge) return;
    if (needsRetest) {
      wsRetestBadge.textContent = "Chưa chạy thử lại";
      wsRetestBadge.className = "practice-badge badge-retest-warning";
    } else {
      wsRetestBadge.textContent = "Đã đồng bộ";
      wsRetestBadge.className = "practice-badge badge-retest-clean";
    }
  }

  // Practice Run requests are handled by the authenticated visible-only endpoint.

  // --- Reset to starter code ---
  function onRestoreStarterClick() {
    if (!currentQuestion) return;
    if (!window.confirm("Khôi phục mã khởi tạo sẽ thay thế toàn bộ code hiện tại bằng mã ban đầu. Bạn có chắc không?")) {
      return;
    }
    const starter = currentQuestion.starter_code || "";
    if (wsEditor.value === starter) return;
    wsEditor.value = starter;
    if (!currentAttemptId) currentAttemptId = generateHex32();
    needsRetest = true;
    updateRetestBadge();
    persistCurrentDraft();
  }

  // --- Navigation & Dirty Checks ---
  function confirmLeaveWorkspace() {
    if (needsRetest && currentQuestion && wsEditor.value !== (currentQuestion.starter_code || "")) {
      return window.confirm("Bạn có thay đổi chưa chạy thử. Bạn có chắc muốn quay lại thư viện không? (Bản nháp được lưu trên trình duyệt này).");
    }
    return true;
  }

  function showLibraryView() {
    if (currentView === "workspace") {
      if (!confirmLeaveWorkspace()) return;
    }
    currentView = "library";
    workspaceGeneration += 1;
    if (runStatusTimer) window.clearTimeout(runStatusTimer);
    runStatusTimer = null;
    workspaceView.classList.add("hidden");
    libraryView.classList.remove("hidden");
    window.location.hash = "";
    loadCatalog();
  }

  // Each tab has its own draft key. Only an explicit progress deletion clears all tab drafts.
  window.addEventListener("storage", (e) => {
    if (!e.key || e.newValue !== null || !currentQuestion) return;
    const prefix = `css_practice_draft:${getStudentId()}:${currentQuestion.question_id}:`;
    if (e.key.startsWith(prefix) && currentView === "workspace") {
      wsEditor.value = "";
      currentAttemptId = null;
      needsRetest = false;
      hasApplicableResult = false;
      updateRetestBadge();
    }
  });

  // --- Initialization ---
  function init() {
    root = document.getElementById("practice-root");
    practiceAccess = window.createPracticeLock({ request: (url, options) => getBaseRequest()(url, options), root, dialog: document.getElementById("practice-lock-dialog") });
    libraryView = document.getElementById("practice-library-view");
    workspaceView = document.getElementById("practice-workspace-view");
    listHost = document.getElementById("practice-catalog-list");
    noticeHost = document.getElementById("practice-notice");
    modalHost = document.getElementById("practice-modal-host");
    searchInput = document.getElementById("practice-search");
    langFilter = document.getElementById("practice-lang-filter");
    diffFilter = document.getElementById("practice-diff-filter");
    refreshBtn = document.getElementById("practice-refresh-btn");

    // Workspace elements
    wsTitle = document.getElementById("practice-ws-title");
    wsLangBadge = document.getElementById("practice-ws-lang-badge");
    wsDiffBadge = document.getElementById("practice-ws-diff-badge");
    wsCatBadge = document.getElementById("practice-ws-cat-badge");
    wsPoints = document.getElementById("practice-ws-points");
    wsRetestBadge = document.getElementById("practice-retest-badge");
    wsUpdateBtn = document.getElementById("practice-ws-update-btn");
    wsBackBtn = document.getElementById("practice-back-to-library-btn");
    wsStatement = document.getElementById("practice-ws-statement");
    wsTargetSection = document.getElementById("practice-ws-target-section");
    wsTargetInfo = document.getElementById("practice-ws-target-info");
    wsStarterSection = document.getElementById("practice-ws-starter-section");
    wsStarterCode = document.getElementById("practice-ws-starter-code");
    wsTestsTableHost = document.getElementById("practice-ws-tests-table-host");
    wsEditorLangLabel = document.getElementById("practice-editor-lang-label");
    wsEditorFilename = document.getElementById("practice-editor-filename");
    wsEditor = document.getElementById("practice-code-editor");
    wsRestoreStarterBtn = document.getElementById("practice-restore-starter-btn");
    wsRunBtn = document.getElementById("practice-run-btn");
    wsEditorAlert = document.getElementById("practice-editor-alert");
    wsRunResult = document.getElementById("practice-run-result");
    wsStorageWarning = document.getElementById("practice-storage-warning");
    wsRevisionNotice = document.getElementById("practice-revision-notice");
    wsRevisionNoticeText = document.getElementById("practice-revision-notice-text");
    wsRetryDetailsBtn = document.getElementById("practice-retry-details-btn");

    // Library listeners
    modalHost?.addEventListener("click", (e) => {
      if (e.target === modalHost) closeModal();
    });

    searchInput?.addEventListener("input", (e) => {
      currentFilter.search = e.target.value;
      renderCatalog();
    });

    langFilter?.addEventListener("change", (e) => {
      currentFilter.language = e.target.value;
      renderCatalog();
    });

    diffFilter?.addEventListener("change", (e) => {
      currentFilter.difficulty = e.target.value;
      renderCatalog();
    });

    refreshBtn?.addEventListener("click", loadCatalog);

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        clearCatalogPollTimer();
      } else {
        pollCatalogChanges();
      }
    });
    window.addEventListener("online", () => pollCatalogChanges());
    window.addEventListener("focus", () => pollCatalogChanges());
    window.addEventListener("pagehide", stopCatalogPolling);
    window.addEventListener("pageshow", () => {
      catalogPollingStopped = false;
      pollCatalogChanges();
    });

    // Workspace listeners
    wsBackBtn?.addEventListener("click", showLibraryView);

    wsEditor?.addEventListener("input", () => {
      const wasAttemptless = !currentAttemptId;
      if (!currentAttemptId) {
        currentAttemptId = generateHex32();
      }
      needsRetest = true;
      updateRetestBadge();
      persistCurrentDraft();
      if (wasAttemptless) setRunMessage("");
      updateRunButton();
    });

    wsEditor?.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const start = wsEditor.selectionStart;
        const end = wsEditor.selectionEnd;
        wsEditor.setRangeText("    ", start, end, "end");
        wsEditor.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    wsRestoreStarterBtn?.addEventListener("click", onRestoreStarterClick);
    if (wsRunBtn) {
      wsRunBtn.disabled = true;
      wsRunBtn.addEventListener("click", runPractice);
    }
    wsRetryDetailsBtn?.addEventListener("click", retryQuestionDetails);

    wsUpdateBtn?.addEventListener("click", () => {
      if (currentQuestion) handleUpdate(currentQuestion.question_id);
    });

    const navExam = document.getElementById("practice-nav-exam");
    navExam?.addEventListener("click", (e) => {
      if (currentView === "workspace" && !confirmLeaveWorkspace()) {
        e.preventDefault();
      }
    });

    // Check hash for direct question open (F5 reload / direct link)
    const hash = window.location.hash;
    const match = hash.match(/^#q=([^&]+)/);
    if (match && match[1]) {
      const qid = decodeURIComponent(match[1]);
      loadCatalog().then(() => {
        openWorkspace(qid);
        scheduleCatalogPoll();
      });
    } else {
      loadCatalog().then(() => scheduleCatalogPoll());
    }
  }

  // Expose test interface
  window.PracticeWorkspace = {
    openWorkspace,
    showLibraryView,
    setCatalog: (c) => { catalog = c; renderCatalog(); },
    setCatalogToken: (token) => { catalogToken = token; },
    getNeedsRetest: () => needsRetest,
    setNeedsRetest: (v) => { needsRetest = v; updateRetestBadge(); },
    getCurrentAttemptId: () => currentAttemptId,
    setCurrentAttemptId: (id) => { currentAttemptId = id; },
    getCurrentQuestion: () => currentQuestion,
    handleUpdate,
    retryQuestionDetails,
    openPreviewModal,
    handleDeleteProgress,
    loadDraftFromStorage,
    saveDraftToStorage,
    clearStoredAttempt,
    clearAllStoredForQuestion,
    generateHex32,
    pollCatalogChanges,
    stopCatalogPolling,
    getCatalogToken: () => catalogToken,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
