(() => {
  "use strict";
  const ui = window.cssUi;
  if (!ui) return;
  const { h, errorBox, statusPill } = ui;
  const request = window.cssRequest;

  const examStatus = {
    draft: ["Nháp", "status-gray"],
    active: ["Đang thi", "status-green"],
    running: ["Đang thi", "status-green"],
    ended: ["Đã kết thúc", "status-amber"],
  };
  const pill = (status) => {
    const entry = examStatus[status];
    return entry ? h("span", { class: `status-pill ${entry[1]}` }, entry[0]) : statusPill(status);
  };

  async function fetchCodeExams() {
    const data = await request("/api/admin/code-exams");
    return data.code_exams || [];
  }

  // ---------- code exam tab ----------
  const root = document.getElementById("code-exams-view");
  if (!root) return;
  const listHost = document.getElementById("ce-list");

  async function loadList() {
    listHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải danh sách đề thi code..."));
    try {
      const exams = await fetchCodeExams();
      if (!exams.length) {
        listHost.replaceChildren(h("p", { class: "empty-cell" }, "Chưa có đề thi code nào. Hãy tạo trong mục Kỳ thi."));
        return;
      }
      listHost.replaceChildren(h("table", { class: "data-table" },
        h("thead", {}, h("tr", {}, ...["Tiêu đề", "Số câu", "Tổng điểm", "Chính sách nộp", "Trạng thái", "Tạo lúc"].map((t) => h("th", {}, t)))),
        h("tbody", {}, exams.map((exam) => h("tr", {},
          h("td", {}, h("strong", {}, exam.title)),
          h("td", {}, (exam.questions || []).length),
          h("td", {}, (exam.questions || []).reduce((sum, q) => sum + (Number(q.total_points) || 0), 0)),
          h("td", {}, exam.submission_policy === "once" ? "Nộp 1 lần" : `Tối đa ${exam.max_submissions} lần`),
          h("td", {}, pill(exam.status)),
          h("td", { class: "fine-print" }, exam.created_at || ""))))));
    } catch (error) {
      listHost.replaceChildren(errorBox(error, loadList));
    }
  }

  loadList();
})();
