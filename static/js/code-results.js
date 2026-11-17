(() => {
  "use strict";
  const root = document.getElementById("code-results-view");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const examSelect = $("cr-exam");
  const studentSelect = $("cr-student");
  const questionSelect = $("cr-question");
  const list = $("cr-list");
  const detail = $("cr-detail");
  const notice = $("cr-notice");
  let exams = [];
  let students = new Map();
  let submissions = [];
  let matrix = [];
  let selectedExam = null;
  let selectedSubmission = null;

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  const text = (value) => value === undefined || value === null || value === "" ? "—" : String(value);

  function setNotice(message, error = false) {
    notice.textContent = message || "";
    notice.classList.toggle("hidden", !message);
    notice.classList.toggle("notice-error", error);
  }

  function requestError(error, retry) {
    const box = el("div", error.message || "Yêu cầu không thành công.", "alert alert-warning");
    const button = el("button", "Thử lại", "btn btn-secondary btn-small");
    button.type = "button";
    button.addEventListener("click", retry);
    box.append(document.createTextNode(" "), button);
    return box;
  }

  function table(headers, rows) {
    const result = el("table");
    const thead = el("thead");
    const headRow = el("tr");
    headers.forEach((value) => headRow.append(el("th", value)));
    thead.append(headRow);
    const tbody = el("tbody");
    rows.forEach((row) => tbody.append(row));
    result.append(thead, tbody);
    return result;
  }

  function verdictLabel(verdict) {
    const messages = {
      AC: "Đạt yêu cầu",
      WA: "Chưa đạt",
      CE: "Lỗi biên dịch",
      TLE: "Quá thời gian",
      MLE: "Quá bộ nhớ",
      RE: "Lỗi thực thi",
      OLE: "Quá giới hạn output",
      JUDGE_INFRA_ERROR: "Lỗi hạ tầng chấm",
      PROTOCOL_ERROR: "Lỗi giao thức chấm",
    };
    return messages[verdict] || text(verdict);
  }

  function renderCheckResults(results) {
    if (!Array.isArray(results) || !results.length) return el("p", "Máy chủ không trả chi tiết check cho bài nộp này.", "muted");
    return table(
      ["Check", "Hiển thị", "Kết quả", "Điểm", "Kỳ vọng", "Thực tế", "Lỗi"],
      results.map((item) => {
        const row = el("tr");
        [
          item.id,
          item.is_visible ? "Công khai" : "Ẩn",
          item.passed ? "Đạt" : verdictLabel(item.verdict || "WA"),
          item.points_earned,
          item.expected,
          item.actual,
          item.error,
        ].forEach((value, index) => row.append(el("td", text(value), index >= 4 ? "code-result-value" : "")));
        return row;
      }),
    );
  }

  function renderHistory(record) {
    if (!Array.isArray(record.grading_history) || !record.grading_history.length) return null;
    const container = el("details", undefined, "grading-history");
    container.append(el("summary", `Lịch sử chấm (${record.grading_history.length})`));
    record.grading_history.forEach((entry, index) => {
      const section = el("section", undefined, "history-entry");
      section.append(el("h4", `Kết quả cũ ${index + 1}`));
      section.append(el("p", `Thời gian: ${text(entry.graded_at)} · Spec: ${text(entry.grading_spec_version)} · ${verdictLabel(entry.verdict)} · Điểm ${text(entry.score)}/${text(entry.total_points)}`));
      section.append(renderCheckResults(entry.results));
      container.append(section);
    });
    return container;
  }

  function renderDetail(record) {
    selectedSubmission = record;
    detail.replaceChildren();
    detail.classList.remove("hidden");
    const heading = el("div", undefined, "submission-detail-heading");
    heading.append(
      el("h3", `Bài nộp ${record.id || ""}`),
      el("button", "Đóng", "btn btn-ghost btn-small"),
    );
    heading.querySelector("button").type = "button";
    heading.querySelector("button").addEventListener("click", () => detail.classList.add("hidden"));
    detail.append(heading);
    detail.append(el("p", `${students.get(record.student_id) || "Sinh viên"} · MSSV ${record.student_id || "—"} · Lần nộp ${text(record.attempt)} · ${text(record.submitted_at)}`));
    detail.append(el("p", `Trạng thái: ${text(record.status)} · ${verdictLabel(record.verdict)} · Điểm ${text(record.score)}/${text(record.total_points)} · Spec: ${text(record.grading_spec_version)}`));
    if (record.error) detail.append(el("div", `${record.error_category ? record.error_category + ": " : ""}${record.error}`, "alert alert-warning"));
    const source = el("pre", record.source_code || "Bản ghi không có mã nguồn.");
    source.className = "code-block submission-source";
    detail.append(el("h4", "Mã nguồn đã nộp"), source);
    detail.append(el("h4", "Kết quả từng check (bao gồm check ẩn)"));
    detail.append(renderCheckResults(record.results));
    if (record.compile_result) {
      const diagnostics = record.compile_result.stderr || record.compile_result.error;
      if (diagnostics) detail.append(el("pre", diagnostics, "code-block"));
    }

    const history = renderHistory(record);
    if (history) detail.append(history);

    const regradeForm = el("div", undefined, "regrade-controls");
    const mode = el("select");
    const snapshotOption = el("option", "Dùng snapshot của đề đã phát");
    snapshotOption.value = "false";
    const latestOption = el("option", "Dùng phiên bản câu hỏi mới nhất đã xuất bản");
    latestOption.value = "true";
    mode.append(snapshotOption, latestOption);
    const regradeButton = el("button", "Chấm lại", "btn btn-secondary btn-small");
    regradeButton.type = "button";
    const examEnded = selectedExam?.status === "ended";
    regradeButton.disabled = !examEnded || !record.id || !["graded", "error"].includes(record.status);
    regradeButton.addEventListener("click", () => regrade(record, mode.value, regradeButton));
    regradeForm.append(
      el("p", "Chấm lại chỉ khả dụng sau khi kỳ thi kết thúc. Kết quả mới sẽ thay kết quả hiện tại; máy chủ lưu lịch sử chấm."),
      mode,
      regradeButton,
    );
    if (!examEnded) regradeForm.append(el("p", "Đề thi chưa kết thúc nên máy chủ chưa cho phép chấm lại.", "fine-print"));
    detail.append(regradeForm);
  }

  async function regrade(record, latestValue, button) {
    const latest = latestValue === "true";
    const specChoice = latest ? "phiên bản mới nhất đã xuất bản" : "snapshot đã phát";
    if (!window.confirm(`Chấm lại bài ${record.id} của sinh viên ${record.student_id} bằng ${specChoice}?`)) return;
    button.disabled = true;
    setNotice("Đang yêu cầu máy chủ chấm lại...", false);
    try {
      const response = await window.cssRequest(`/api/admin/code-results/${encodeURIComponent(selectedExam.id)}/regrade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ submission_id: record.id, use_latest_spec: latest }),
      });
      const updated = response.submission;
      setNotice("Máy chủ đã xác nhận chấm lại. Đang tải danh sách cập nhật.");
      await loadResults();
      if (updated) renderDetail(updated);
    } catch (error) {
      setNotice(error.message || "Không thể chấm lại bài.", true);
      button.disabled = false;
    }
  }

  function renderList() {
    detail.classList.add("hidden");
    const exam = selectedExam;
    const questionTitles = new Map((exam?.questions || []).map((q) => [q.question_id, q.title]));
    if (!submissions.length) {
      list.replaceChildren(el("p", "Chưa có bài nộp nào trong đề thi này.", "empty-cell"));
      return;
    }
    const rows = submissions.map((record) => {
      const row = el("tr");
      const studentCell = el("td");
      studentCell.append(el("strong", students.get(record.student_id) || record.student_id || "—"));
      studentCell.append(el("div", `MSSV: ${record.student_id || "—"}`, "fine-print"));
      row.append(studentCell);
      row.append(el("td", questionTitles.get(record.question_id) || record.question_id));
      row.append(el("td", text(record.submitted_at)));
      row.append(el("td", `${text(record.status)} · ${verdictLabel(record.verdict)}`));
      row.append(el("td", record.score === undefined ? "—" : `${record.score}/${text(record.total_points)}`));
      row.append(el("td", text(record.attempt)));
      const actions = el("td");
      const open = el("button", "Chi tiết", "btn btn-secondary btn-small");
      open.type = "button";
      open.addEventListener("click", () => renderDetail(record));
      actions.append(open);
      row.append(actions);
      return row;
    });
    list.replaceChildren(table(["Sinh viên", "Câu hỏi", "Thời gian nộp", "Trạng thái / verdict", "Điểm", "Lần", ""], rows));
  }

  function cellLabel(cell) {
    if (cell.status === "none") return "Chưa nộp";
    if (cell.status === "error") return "Lỗi chấm";
    if (cell.status !== "graded") return "Đang chấm";
    return `${cell.score}/${cell.total_points}`;
  }

  const specMode = el("select");
  specMode.setAttribute("aria-label", "Phiên bản đề dùng khi chấm lại");
  for (const [value, label] of [["false", "Chấm lại bằng snapshot đã phát"], ["true", "Chấm lại bằng phiên bản câu hỏi mới nhất"]]) {
    const option = el("option", label);
    option.value = value;
    specMode.append(option);
  }

  async function bulkRegrade(studentId, questionId, buttons) {
    const latest = specMode.value === "true";
    const scope = questionId ? "câu hỏi này" : "toàn bộ đề";
    if (!window.confirm(`Chấm lại ${scope} của sinh viên ${studentId} bằng ${latest ? "phiên bản mới nhất đã xuất bản" : "snapshot đã phát"}? Kết quả cũ được lưu vào lịch sử chấm.`)) return;
    buttons.forEach((button) => { button.disabled = true; });
    setNotice("Đang yêu cầu máy chủ chấm lại...", false);
    try {
      const response = await window.cssRequest(`/api/admin/code-results/${encodeURIComponent(selectedExam.id)}/regrade-student`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ student_id: studentId, ...(questionId ? { question_id: questionId } : {}), use_latest_spec: latest }),
      });
      const result = response.result;
      const titles = new Map((selectedExam.questions || []).map((q) => [q.question_id, q.title || q.question_id]));
      const parts = [`Đã chấm lại ${result.regraded.length} câu.`];
      if (result.skipped.length) parts.push(`Bỏ qua ${result.skipped.length} câu chưa có bài nộp đã chấm.`);
      if (result.failed.length) parts.push(`Thất bại ${result.failed.length} câu (kết quả cũ được giữ): ${result.failed.map((item) => `${titles.get(item.question_id)} — ${item.error}`).join("; ")}`);
      await loadResults();
      setNotice(parts.join(" "), result.failed.length > 0);
    } catch (error) {
      setNotice(error.message || "Không thể chấm lại.", true);
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function renderMatrix() {
    const host = $("cr-matrix");
    if (!host) return;
    host.replaceChildren();
    if (!selectedExam || !matrix.length) return;
    const ended = selectedExam.status === "ended";
    host.append(el("h3", "Bảng điểm theo sinh viên (theo thứ tự câu trong đề)"));
    const controls = el("div", undefined, "regrade-controls");
    controls.append(specMode);
    if (!ended) controls.append(el("p", "Đề thi chưa kết thúc nên chưa thể chấm lại.", "fine-print"));
    host.append(controls);
    const questions = selectedExam.questions || [];
    const rows = matrix.map((entry) => {
      const row = el("tr");
      const who = el("td");
      who.append(el("strong", entry.full_name || students.get(entry.student_id) || entry.student_id), el("div", `MSSV: ${entry.student_id}`, "fine-print"));
      row.append(who);
      const buttons = [];
      entry.cells.forEach((cell) => {
        const td = el("td");
        td.append(el("div", cellLabel(cell)), el("div", `${verdictLabel(cell.verdict)}${cell.attempts ? ` · ${cell.attempts} lần` : ""}${cell.regraded ? " · đã chấm lại" : ""}`, "fine-print"));
        const detailRecord = submissions.find((record) => record.id === cell.submission_id);
        if (detailRecord) {
          const open = el("button", "Chi tiết", "btn btn-ghost btn-small");
          open.type = "button";
          open.addEventListener("click", () => renderDetail(detailRecord));
          td.append(open);
        }
        if (cell.submission_id) {
          const one = el("button", "Chấm lại câu", "btn btn-ghost btn-small");
          one.type = "button";
          one.disabled = !ended;
          one.addEventListener("click", () => bulkRegrade(entry.student_id, cell.question_id, buttons));
          buttons.push(one);
          td.append(one);
        }
        row.append(td);
      });
      row.append(el("td", entry.total_score === null ? "—" : `${entry.total_score}/${entry.total_points}`));
      const actions = el("td");
      const all = el("button", "Chấm lại cả đề", "btn btn-secondary btn-small");
      all.type = "button";
      all.disabled = !ended;
      buttons.push(all);
      all.addEventListener("click", () => bulkRegrade(entry.student_id, null, buttons));
      actions.append(all);
      row.append(actions);
      return row;
    });
    host.append(el("div", undefined, "table-scroll"));
    host.lastChild.append(table(["Sinh viên", ...questions.map((q) => `${q.title || q.question_id} (${q.total_points} điểm)`), "Tổng", ""], rows));
  }

  async function loadResults() {
    if (!examSelect.value) {
      detail.classList.add("hidden");
      submissions = [];
      matrix = [];
      renderMatrix();
      list.replaceChildren(el("p", "Chọn một đề thi code để xem kết quả.", "empty-cell"));
      setNotice("", false);
      return;
    }
    selectedExam = exams.find((exam) => exam.id === examSelect.value);
    if (!selectedExam) return;
    detail.classList.add("hidden");
    const params = new URLSearchParams({ exam_id: selectedExam.id });
    if (studentSelect.value) params.set("student_id", studentSelect.value);
    if (questionSelect.value) params.set("question_id", questionSelect.value);
    list.replaceChildren(el("p", "Đang tải bài nộp..."));
    try {
      const response = await window.cssRequest(`/api/admin/code-results?${params.toString()}`);
      submissions = response.submissions || [];
      matrix = response.matrix || [];
      selectedExam = { ...selectedExam, status: response.status || selectedExam.status };
      renderMatrix();
      renderList();
      if (studentSelect.value || questionSelect.value) {
        setNotice(submissions.length ? "" : "Không có bài nộp nào khớp với bộ lọc.", false);
      } else {
        setNotice("", false);
      }
    } catch (error) {
      list.replaceChildren(requestError(error, loadResults));
      setNotice(error.status === 403 ? "Bạn không có quyền xem kết quả code." : "", error.status === 403);
    }
  }

  function updateQuestionFilter() {
    const current = questionSelect.value;
    questionSelect.replaceChildren(el("option", "Tất cả câu hỏi"));
    questionSelect.options[0].value = "";
    for (const question of selectedExam?.questions || []) {
      const option = el("option", `${question.title || question.question_id} (${question.question_id})`);
      option.value = question.question_id;
      questionSelect.append(option);
    }
    questionSelect.value = [...questionSelect.options].some((option) => option.value === current) ? current : "";
  }

  async function initialize() {
    list.replaceChildren(el("p", "Đang tải đề thi và danh sách sinh viên..."));
    try {
      const [examData, accountData] = await Promise.all([
        window.cssRequest("/api/admin/code-exams"),
        window.cssRequest("/api/admin/accounts"),
      ]);
      exams = examData.code_exams || [];
      students = new Map((accountData.students || []).map((student) => [student.student_id, student.full_name || student.student_id]));
      examSelect.replaceChildren(el("option", "Chọn đề thi"));
      examSelect.options[0].value = "";
      for (const exam of exams) {
        const option = el("option", `${exam.title} · ${exam.status}`);
        option.value = exam.id;
        examSelect.append(option);
      }
      studentSelect.replaceChildren(el("option", "Tất cả sinh viên"));
      studentSelect.options[0].value = "";
      for (const [id, name] of students) {
        const option = el("option", `${name} (${id})`);
        option.value = id;
        studentSelect.append(option);
      }
      if (!exams.length) {
        setNotice("Chưa có đề thi code để tra cứu.", false);
        list.replaceChildren(el("p", "Chưa có đề thi code.", "empty-cell"));
        return;
      }
      list.replaceChildren(el("p", "Chọn đề thi, sinh viên hoặc câu hỏi rồi tải kết quả.", "empty-cell"));
    } catch (error) {
      list.replaceChildren(requestError(error, initialize));
      setNotice(error.status === 403 ? "Bạn không có quyền xem kết quả code." : error.message, true);
    }
  }

  examSelect.addEventListener("change", () => {
    selectedExam = exams.find((exam) => exam.id === examSelect.value);
    updateQuestionFilter();
    loadResults();
  });
  studentSelect.addEventListener("change", loadResults);
  questionSelect.addEventListener("change", loadResults);
  $("cr-refresh").addEventListener("click", loadResults);
  initialize();
})();
