(() => {
  "use strict";

  const root = document.getElementById("student-code-root");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const loading = $("student-code-loading");
  const alertBox = $("student-code-alert");
  const content = $("student-code-content");
  const editor = $("student-code-editor");
  const runButton = $("code-run");
  const submitButton = $("code-submit");
  const countdown = $("countdown");
  const reportedErrors = new Set();
  const verdictMessages = {
    AC: "Bài làm đạt các yêu cầu kiểm tra",
    WA: "Bài làm chưa đáp ứng kết quả mong đợi",
    CE: "Code có lỗi biên dịch",
    TLE: "Chương trình vượt quá thời gian cho phép",
    MLE: "Chương trình vượt quá giới hạn bộ nhớ",
    RE: "Chương trình gặp lỗi khi thực thi",
    OLE: "Chương trình tạo ra lượng đầu ra vượt giới hạn",
  };
  let question;
  let exam;
  let starterCode = "";
  let storageKey = "";
  let draftReady = false;
  let latestSubmissionId = null;
  let requestPending = false;
  let submissionUnknown = false;
  let serverRemaining = 0;
  let serverAnchor = 0;
  let storageTimer = 0;

  function reportBackgroundError(scope, error) {
    if (reportedErrors.has(scope)) return;
    reportedErrors.add(scope);
    console.warn(`${scope} request failed`, error);
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function showAlert(message, kind = "warning") {
    alertBox.replaceChildren();
    alertBox.className = `alert alert-${kind}`;
    alertBox.textContent = message;
    alertBox.classList.remove("hidden");
  }

  function clearAlert() {
    alertBox.textContent = "";
    alertBox.className = "hidden";
  }

  function errorMessage(error) {
    if (error.status === 401) return "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.";
    if (error.status === 403) return "Kỳ thi chưa bắt đầu, đã kết thúc hoặc thời gian làm bài đã hết.";
    if (error.status === 409) return "Thao tác không được phép ở trạng thái hiện tại hoặc đã hết lượt nộp.";
    if (error.status === 429) return "Máy chủ đang xử lý nhiều bài. Vui lòng chờ rồi thử lại.";
    if (error.status === 503) return "Dịch vụ chấm đang gặp sự cố. Hãy báo giảng viên; không thể xác nhận kết quả lúc này.";
    if (!error.status) return "Không kết nối được với máy chủ. Hãy kiểm tra trạng thái bài trước khi thử lại.";
    return error.detail || error.message || "Yêu cầu không thành công.";
  }

  function showLoginLink() {
    if (alertBox.querySelector("a")) return;
    const link = node("a", "btn btn-secondary btn-small", "Đăng nhập lại");
    link.href = "/login";
    alertBox.append(document.createTextNode(" "));
    alertBox.append(link);
  }

  function revealContent() {
    loading.classList.add("hidden");
    content.classList.remove("hidden");
  }

  function setPending(value) {
    requestPending = value;
    updateControls();
  }

  function currentRemaining() {
    return Math.max(0, Math.floor(serverRemaining - (performance.now() - serverAnchor) / 1000));
  }

  function updateControls() {
    const expired = currentRemaining() <= 0 || exam?.read_only === true;
    const unavailable = expired || requestPending || submissionUnknown || !draftReady;
    editor.disabled = expired || !draftReady;
    $("code-restore-starter").disabled = expired || requestPending || !draftReady;
    runButton.disabled = unavailable;
    submitButton.disabled = unavailable;
    if (expired) {
      $("code-exam-state").textContent = "Đã khóa";
      $("code-exam-state").className = "status-pill status-gray";
    }
  }

  function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }

  function drawCountdown() {
    if (!countdown) return;
    const remaining = currentRemaining();
    countdown.textContent = remaining > 0 ? formatTime(remaining) : "Hết giờ";
    countdown.classList.toggle("countdown-warning", remaining <= 300);
    updateControls();
  }

  async function syncServerStatus() {
    const status = await window.cssRequest("/api/student/status");
    if (status.remaining_seconds === null || status.remaining_seconds === undefined) {
      serverRemaining = 0;
    } else {
      serverRemaining = Math.max(0, Number(status.remaining_seconds) || 0);
    }
    serverAnchor = performance.now();
    if (status.exam_state && status.exam_state !== "started") exam.read_only = true;
    if (serverRemaining <= 0) exam.read_only = true;
    drawCountdown();
  }

  function resultTable(results) {
    if (!Array.isArray(results) || !results.length) return node("p", "muted", "Máy chủ không trả về check hiển thị nào.");
    const table = node("table", "data-table");
    const head = node("thead");
    const header = node("tr");
    for (const label of ["Check", "Kết quả", "Kỳ vọng", "Thực tế", "Thông tin"]) {
      header.append(node("th", "", label));
    }
    head.append(header);
    const body = node("tbody");
    for (const result of results) {
      const row = node("tr");
      row.append(node("td", "", result.id || ""));
      row.append(node("td", "", result.passed ? "Đạt" : (result.verdict || "Chưa đạt")));
      row.append(node("td", "code-result-value", result.expected ?? ""));
      row.append(node("td", "code-result-value", result.actual ?? ""));
      row.append(node("td", "code-result-value", result.error || ""));
      body.append(row);
    }
    table.append(head, body);
    return table;
  }

  function showRunResult(result) {
    const host = $("code-run-result");
    host.replaceChildren();
    host.classList.remove("hidden");
    host.append(node("h3", "", "Kết quả chạy thử — chưa phải điểm cuối"));
    const verdict = result.verdict;
    host.append(node("p", "code-verdict", verdictMessages[verdict] || (verdict ? `Kết quả: ${verdict}` : "Máy chủ chưa trả verdict.")));
    if (result.error_category && ["JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR", "INVALID_REQUEST"].includes(result.error_category)) {
      host.append(node("div", "alert alert-warning", "Lỗi hạ tầng chấm. Kết quả này không phải lỗi bài làm; hãy báo giảng viên."));
    } else if (result.error_category) {
      host.append(node("p", "fine-print", `Loại lỗi: ${result.error_category}`));
    }
    host.append(resultTable(result.results));
    const compilerText = result.compile_result?.stderr || result.compile_result?.error;
    if (compilerText && verdict === "CE") {
      const details = node("details", "code-diagnostic");
      details.append(node("summary", "", "Chi tiết lỗi biên dịch"));
      details.append(node("pre", "code-block", compilerText));
      host.append(details);
    }
  }

  function showSubmission(record, message) {
    const host = $("code-submission-result");
    host.replaceChildren();
    host.classList.remove("hidden");
    host.append(node("h3", "", "Trạng thái bài nộp"));
    const status = record?.status || "unknown";
    if (record?.verdict) {
      host.append(node("p", "code-verdict", verdictMessages[record.verdict] || `Kết quả: ${record.verdict}`));
    } else if (status === "submitted" || status === "grading") {
      host.append(node("p", "code-verdict", "Đã nộp"));
    } else {
      host.append(node("p", "code-verdict", `Trạng thái: ${status}`));
    }
    if (record?.score !== undefined && record?.total_points !== undefined) {
      host.append(node("p", "", `Điểm: ${record.score}/${record.total_points}`));
    } else if (status === "submitted" || status === "grading") {
      host.append(node("p", "muted", "Điểm sẽ được hiển thị theo cài đặt của kỳ thi."));
    }
    if (record?.submitted_at) host.append(node("p", "fine-print", `Thời gian nộp: ${record.submitted_at}`));
    if (message) host.append(node("p", "alert alert-warning", message));
    if (Array.isArray(record?.results)) host.append(resultTable(record.results));
    if (record?.error && record?.error_category && ["JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"].includes(record.error_category)) {
      host.append(node("p", "alert alert-warning", "Máy chủ chưa thể hoàn tất chấm bài. Hãy báo giảng viên."));
    }
  }

  function starterFilename(q) {
    if (q.target_file) return q.target_file;
    const className = String(q.target_class || "").split(".").pop();
    return className ? `${className}.java` : "Tệp Java";
  }

  function renderQuestionInfo(q) {
    $("code-exam-title").textContent = exam.title || "Bài thi code";
    $("code-filename").textContent = `Tệp: ${starterFilename(q)}`;
    const info = $("code-question-information");
    info.replaceChildren();
    info.append(node("h3", "", q.title || "Câu hỏi"));
    info.append(node("div", "code-statement", q.statement || "Đề bài không có nội dung mô tả."));
    const details = node("dl", "code-question-meta");
    for (const [label, value] of [
      ["Package bắt buộc", q.target_package || "(không khai báo)"],
      ["Class cần cài đặt", q.target_class || "Không có thông tin"],
      ["Tên file", starterFilename(q)],
    ]) {
      details.append(node("dt", "", label), node("dd", "", value));
    }
    info.append(details);
    info.append(node("div", "alert alert-info", "Tên public class phải trùng tên file; package phải đúng theo đề. Bài làm hiện hỗ trợ một file Java và một public class."));
    if (q.starter_code) {
      const block = node("details", "starter-code-details");
      block.append(node("summary", "", "Xem mã khởi tạo"));
      block.append(node("pre", "code-block", q.starter_code));
      info.append(block);
    } else {
      info.append(node("p", "muted", "Đề không cung cấp mã khởi tạo; vùng soạn thảo bắt đầu trống."));
    }
  }

  function storageNotice(message, error = false) {
    const notice = $("code-draft-notice");
    notice.textContent = message;
    notice.classList.remove("hidden", "notice-error");
    if (error) notice.classList.add("notice-error");
  }

  function readDraft() {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      const value = JSON.parse(raw);
      return value && typeof value.source_code === "string" ? value : null;
    } catch (error) {
      storageNotice("Không đọc được bản nháp trong trình duyệt. Mã khởi tạo vẫn được giữ nguyên.", true);
      return null;
    }
  }

  function saveDraft() {
    if (!draftReady || !storageKey) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        source_code: editor.value,
        starter_code: starterCode,
        saved_at: new Date().toISOString(),
      }));
      storageNotice("Bản nháp được lưu trên trình duyệt này.", false);
    } catch (error) {
      storageNotice("Không lưu được bản nháp trong trình duyệt. Hãy giữ nguyên trang để tránh mất mã.", true);
    }
  }

  function selectDraft(cached) {
    editor.value = cached.source_code;
    draftReady = true;
    updateControls();
    saveDraft();
    $("code-draft-notice").classList.remove("hidden");
  }

  function useStarterCode() {
    editor.value = starterCode;
    draftReady = true;
    updateControls();
    saveDraft();
  }

  function initializeDraft(q) {
    starterCode = typeof q.starter_code === "string" ? q.starter_code : "";
    storageKey = [
      "css-code-draft-v1",
      root.dataset.studentId,
      exam.exam_id,
      q.question_id,
    ].map((part) => encodeURIComponent(part || "")).join(":");
    const cached = readDraft();
    if (!cached) {
      editor.value = starterCode;
      draftReady = true;
      return;
    }
    if (cached.starter_code === starterCode) {
      selectDraft(cached);
      storageNotice("Đã khôi phục bản nháp đã lưu trên trình duyệt này.", false);
      return;
    }
    editor.value = starterCode;
    draftReady = false;
    updateControls();
    const notice = $("code-draft-notice");
    notice.replaceChildren(
      document.createTextNode("Mã khởi tạo của đề đã thay đổi nhưng vẫn có một bản nháp đã lưu. Chọn rõ ràng nội dung cần khôi phục: "),
      button("Khôi phục bản nháp", () => selectDraft(cached)),
      button("Dùng mã khởi tạo mới", useStarterCode),
    );
    notice.classList.remove("hidden");
  }

  function button(label, action) {
    const element = node("button", "btn btn-secondary btn-small", label);
    element.type = "button";
    element.addEventListener("click", action);
    return element;
  }

  function installEditor() {
    editor.addEventListener("input", () => {
      window.clearTimeout(storageTimer);
      storageTimer = window.setTimeout(saveDraft, 250);
    });
    editor.addEventListener("blur", saveDraft);
    editor.addEventListener("keydown", (event) => {
      if (event.key !== "Tab" || editor.disabled) return;
      event.preventDefault();
      const start = editor.selectionStart;
      const end = editor.selectionEnd;
      editor.setRangeText("    ", start, end, "end");
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });
    $("code-restore-starter").addEventListener("click", () => {
      if (editor.value && editor.value !== starterCode
          && !window.confirm("Khôi phục mã khởi tạo sẽ thay thế toàn bộ mã đang soạn. Tiếp tục?")) return;
      useStarterCode();
    });
    window.addEventListener("beforeunload", saveDraft);
  }

  async function loadLatestSubmission(q) {
    try {
      const result = await window.cssRequest(`/api/student/code/submission?question_id=${encodeURIComponent(q.question_id)}`);
      const submission = result.submission || result;
      latestSubmissionId = submission.submission_id || submission.id || null;
      showSubmission(submission);
    } catch (error) {
      if (error.status === 404) return;
      if (error.status === 401) showLoginLink();
      showAlert(errorMessage(error));
    }
  }

  async function checkUncertainSubmission(previousId) {
    try {
      const result = await window.cssRequest(`/api/student/code/submission?question_id=${encodeURIComponent(question.question_id)}`);
      const submission = result.submission || result;
      latestSubmissionId = submission.submission_id || submission.id || null;
      if (latestSubmissionId && latestSubmissionId !== previousId) {
        submissionUnknown = false;
        showSubmission(submission, "Máy chủ đã nhận bài; phản hồi ban đầu bị gián đoạn.");
        updateControls();
        return;
      }
    } catch (error) {
      if (error.status === 401) showLoginLink();
    }
    submissionUnknown = true;
    showSubmission(null, "Chưa xác nhận được trạng thái. Để tránh nộp trùng, nút nộp đã khóa. Tải lại trang để kiểm tra bài nộp mới nhất trước khi tiếp tục.");
    updateControls();
  }

  async function runPretest() {
    if (requestPending || currentRemaining() <= 0) return;
    setPending(true);
    clearAlert();
    const host = $("code-run-result");
    host.replaceChildren(node("p", "muted", "Đang chạy các check hiển thị..."));
    host.classList.remove("hidden");
    try {
      const result = await window.cssRequest("/api/student/code/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: question.question_id, source_code: editor.value }),
      });
      showRunResult(result);
    } catch (error) {
      if (error.status === 401) showLoginLink();
      showAlert(errorMessage(error));
      if (error.status === 403) {
        exam.read_only = true;
        syncServerStatus().catch((statusError) => reportBackgroundError("Student code status refresh", statusError));
      }
    } finally {
      setPending(false);
    }
  }

  async function submitAnswer() {
    if (requestPending || submissionUnknown || currentRemaining() <= 0) return;
    if (!editor.value.trim()) {
      showAlert("Hãy nhập mã nguồn trước khi nộp.");
      return;
    }
    if (!window.confirm("Bạn chắc chắn muốn nộp mã nguồn này? Máy chủ sẽ chấm bài theo các quy định của kỳ thi.")) return;
    saveDraft();
    const previousId = latestSubmissionId;
    setPending(true);
    clearAlert();
    try {
      const response = await window.cssRequest("/api/student/code/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: question.question_id, source_code: editor.value }),
      });
      const submission = response.submission || response;
      latestSubmissionId = submission.submission_id || submission.id || latestSubmissionId;
      showSubmission(submission);
    } catch (error) {
      if (error.body?.submission) {
        const submission = error.body.submission;
        latestSubmissionId = submission.submission_id || submission.id || latestSubmissionId;
        showSubmission(submission, errorMessage(error));
      } else if (!error.status || error.status >= 500) {
        showAlert(errorMessage(error));
        await checkUncertainSubmission(previousId);
      } else {
        showAlert(errorMessage(error));
        if (error.status === 401) showLoginLink();
        if (error.status === 403) {
          exam.read_only = true;
          syncServerStatus().catch((statusError) => reportBackgroundError("Student code status refresh", statusError));
        }
      }
    } finally {
      setPending(false);
    }
  }

  async function initialize() {
    installEditor();
    try {
      const assignedId = root.dataset.assignedExamId;
      exam = await window.cssRequest("/api/student/code-exam");
      if (exam.exam_id !== assignedId) {
        throw new Error("Đề code hiện tại không khớp với phân công của tài khoản.");
      }
      const questions = Array.isArray(exam.questions) ? exam.questions : [];
      if (questions.length !== 1) {
        loading.classList.add("hidden");
        showAlert(questions.length
          ? `Đề thi có ${questions.length} câu hỏi. Giao diện hiện chỉ hỗ trợ một câu hỏi Java Reflection; chưa thể hiển thị an toàn toàn bộ đề.`
          : "Đề thi code chưa có câu hỏi.");
        return;
      }
      question = questions[0];
      if (question.language !== "java" || question.grading_mode !== "reflection") {
        loading.classList.add("hidden");
        showAlert("Giao diện này hiện chỉ hỗ trợ một câu hỏi Java Reflection.");
        return;
      }
      renderQuestionInfo(question);
      initializeDraft(question);
      runButton.classList.toggle("hidden", exam.allow_pretest === false || question.allow_pretest === false);
      runButton.addEventListener("click", runPretest);
      submitButton.addEventListener("click", submitAnswer);
      await syncServerStatus();
      revealContent();
      await loadLatestSubmission(question);
      drawCountdown();
      window.setInterval(drawCountdown, 1000);
      window.setInterval(() => syncServerStatus().catch((error) => {
        if (error.status === 401) showLoginLink();
        reportBackgroundError("Student code status polling", error);
      }), 5000);
    } catch (error) {
      loading.classList.add("hidden");
      showAlert(errorMessage(error));
      if (error.status === 401) showLoginLink();
    }
  }

  initialize();
})();
