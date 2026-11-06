(() => {
  "use strict";
  const ui = window.cssUi;
  if (!ui) return;
  const { h, errorText, errorBox, setNotice, statusPill } = ui;
  const request = window.cssRequest;

  const root = document.getElementById("code-papers-view");
  if (!root) return;

  const listHost = document.getElementById("cp-list");
  const editorHost = document.getElementById("cp-editor");
  const notice = document.getElementById("cp-notice");
  const newButton = document.getElementById("cp-new");

  const SUPPORTED = (q) =>
    (q.language === "java" && ["reflection", "stdio"].includes(q.grading_mode)) ||
    (q.language === "python" && q.grading_mode === "stdio");

  const PAPER_STATUS = {
    draft: ["Nháp", "status-gray"],
    published: ["Đã Xuất Bản", "status-green"],
  };
  const paperPill = (status) => {
    const [label, cls] = PAPER_STATUS[status] || [status || "?", "status-gray"];
    return h("span", { class: `status-pill ${cls}` }, label);
  };

  let papers = [];
  let bank = [];
  let current = null; // paper being edited (public shape)
  let selected = []; // ordered question ids in the editor
  let highlightChanges = false; // set when entering editor via "Cập nhật ngay"

  const changeBadge = (count, title) => h("span", {
    class: "cp-change-badge",
    title: title || `${count} câu hỏi nguồn đã thay đổi`,
    "aria-label": title || `${count} câu hỏi nguồn đã thay đổi`,
  }, "!");

  const changeReasonText = (change) => {
    const parts = [change.reason || ""];
    if (change.previous_version != null && change.current_version != null && change.previous_version !== change.current_version) {
      parts.push(`(phiên bản ${change.previous_version} → ${change.current_version})`);
    }
    if (change.differences && change.differences.length) {
      parts.push(change.differences.map((d) => {
        if (d.changed) return `${d.label} đã thay đổi`;
        return `${d.label}: ${String(d.old ?? "—")} → ${String(d.new ?? "—")}`;
      }).join("; "));
    }
    return parts.join(" ");
  };

  // ---------- list ----------
  async function loadList() {
    listHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải danh sách đề thi code..."));
    try {
      const data = await request("/api/admin/code-papers");
      papers = data.code_papers || [];
      renderList();
    } catch (error) {
      listHost.replaceChildren(errorBox(error, loadList));
    }
  }

  function renderList() {
    if (!papers.length) {
      listHost.replaceChildren(h("p", { class: "empty-cell" }, "Chưa có đề thi code nào. Nhấn “Tạo đề thi code” để bắt đầu."));
      return;
    }
    const rows = papers.map((paper) => {
      const latest = paper.versions && paper.versions.length ? paper.versions[paper.versions.length - 1] : null;
      const draft = paper.draft || {};
      const isPublished = paper.status === "published";
      const count = isPublished ? (latest ? latest.question_ids.length : 0) : (draft.question_ids || []).length;
      const points = isPublished
        ? (latest ? latest.total_points : 0)
        : (draft.question_ids || []).reduce((sum, id) => sum + (Number((bank.find((q) => q.id === id) || {}).total_points) || 0), 0);
      const open = () => (isPublished ? openDetail(paper.id) : openEditor(paper.id));
      const changes = paper.changes || [];
      const draftChanges = paper.draft_changes || [];
      const changeCount = isPublished ? changes.length : draftChanges.length;
      const action = (label, cls, fn) => h("button", {
        type: "button", class: `btn btn-small ${cls}`,
        on: { click: (e) => { e.stopPropagation(); e.preventDefault(); fn(); } },
      }, label);
      const actions = isPublished
        ? [
          action("Thu hồi", "btn-secondary", () => withdrawPaper(paper)),
          action("Nhân bản", "btn-secondary", () => duplicatePaper(paper)),
          action("Chỉnh sửa", "btn-primary", () => startEdit(paper.id)),
        ]
        : [
          action("Xóa", "btn-danger", () => deletePaper(paper)),
          action("Nhân bản", "btn-secondary", () => duplicatePaper(paper)),
        ];
      return h("tr", { class: "clickable", on: { click: open } },
        h("td", {}, h("strong", {}, paper.name), changeCount ? changeBadge(changeCount) : null),
        h("td", {}, count),
        h("td", {}, points),
        h("td", {}, paper.versions ? paper.versions.length : 0),
        h("td", {}, paperPill(paper.status)),
        h("td", {}, h("div", { class: "actions-inline" }, ...actions)));
    });
    listHost.replaceChildren(
      h("table", { class: "data-table" },
        h("thead", {}, h("tr", {}, ...["Tên đề", "Số câu", "Tổng điểm", "Phiên bản", "Trạng thái", "Thao tác"].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows)));
  }

  // ---------- detail (published read-only) ----------
  async function openDetail(paperId) {
    editorHost.classList.remove("hidden");
    listHost.classList.add("hidden");
    newButton.classList.add("hidden");
    editorHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải..."));
    try {
      const data = await request(`/api/admin/code-papers/${encodeURIComponent(paperId)}`);
      const paper = data.code_paper;
      const latest = paper.versions && paper.versions.length ? paper.versions[paper.versions.length - 1] : null;
      const version = latest ? await request(`/api/admin/code-paper-versions/${encodeURIComponent(latest.id)}`) : null;
      const questions = version ? version.code_paper_version.questions : [];
      const changes = version ? version.code_paper_version.changes || [] : [];
      const changePanel = changes.length
        ? h("div", { class: "alert alert-warning cp-change-panel", role: "alert" },
          h("strong", {}, `Có ${changes.length} câu hỏi nguồn đã thay đổi. Phiên bản đã xuất bản vẫn được giữ nguyên.`),
          h("ul", {}, changes.map((change) => h("li", {},
            h("strong", {}, `${change.position}. ${change.title || change.question_id}`),
            " — ", changeReasonText(change),
            change.code === "missing" ? null : h("a", { href: `/admin?section=exam-management&tab=questions&question=${encodeURIComponent(change.question_id)}`, target: "_blank", rel: "noopener" }, " Mở câu hỏi")))),
          h("div", { class: "form-actions" },
            h("button", { type: "button", class: "btn btn-primary", on: { click: () => updateNow(paper.id) } }, "Cập nhật ngay")))
        : null;
      editorHost.replaceChildren(
        h("div", { class: "panel-heading" },
          h("div", {}, h("h2", {}, paper.name), h("p", { class: "muted" }, `Phiên bản ${latest ? latest.version : "—"} · ${questions.length} câu · ${latest ? latest.total_points : 0} điểm`)),
          h("div", { class: "form-actions" },
            h("button", { type: "button", class: "btn btn-secondary", on: { click: backToList } }, "Quay lại"),
            h("button", { type: "button", class: "btn btn-primary", on: { click: () => startEdit(paper.id) } }, "Chỉnh sửa"))),
        changePanel,
        h("div", { class: "table-scroll" },
          h("table", { class: "data-table" },
            h("thead", {}, h("tr", {}, ...["#", "Tiêu đề", "Danh mục", "Ngôn ngữ / kiểu chấm", "Điểm"].map((t) => h("th", {}, t)))),
            h("tbody", {}, questions.map((q, i) => h("tr", {},
              h("td", {}, i + 1),
              h("td", {}, h("strong", {}, q.title)),
              h("td", {}, q.category || "—"),
              h("td", {}, `${q.language} / ${q.grading_mode}`),
              h("td", {}, q.total_points)))))));
    } catch (error) {
      editorHost.replaceChildren(errorBox(error, () => openDetail(paperId)));
    }
  }

  async function updateNow(paperId) {
    highlightChanges = true;
    await startEdit(paperId);
  }

  async function deletePaper(paper) {
    if (!window.confirm(`Xóa đề thi code “${paper.name}”? Thao tác này không thể hoàn tác.`)) return;
    try {
      await request(`/api/admin/code-papers/${encodeURIComponent(paper.id)}/delete`, { method: "POST" });
      setNotice(notice, "Đã xóa đề thi code.", false);
      await loadList();
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  async function duplicatePaper(paper) {
    try {
      const data = await request(`/api/admin/code-papers/${encodeURIComponent(paper.id)}/duplicate`, { method: "POST" });
      setNotice(notice, "Đã nhân bản đề thi code thành một bản Nháp mới.", false);
      await loadList();
      if (data.code_paper) await openEditor(data.code_paper.id);
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  async function withdrawPaper(paper) {
    if (!window.confirm(`Thu hồi đề thi code “${paper.name}”? Đề sẽ không còn được chọn cho kỳ thi mới. Các phiên bản đã xuất bản và kỳ thi cũ vẫn được giữ nguyên.`)) return;
    try {
      const data = await request(`/api/admin/code-papers/${encodeURIComponent(paper.id)}/withdraw`, { method: "POST" });
      setNotice(notice, "Đã thu hồi đề thi code. Một bản Nháp đã được tạo để chỉnh sửa.", false);
      await loadList();
      if (data.code_paper) await openEditor(data.code_paper.id);
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  async function startEdit(paperId) {
    try {
      const before = await request(`/api/admin/code-papers/${encodeURIComponent(paperId)}`);
      const hadDraft = Boolean(before.code_paper && before.code_paper.has_draft);
      await request(`/api/admin/code-papers/${encodeURIComponent(paperId)}/edit`, { method: "POST" });
      setNotice(notice, hadDraft ? "Đang mở bản nháp hiện có của đề thi code." : "Đã tạo bản nháp mới từ phiên bản đã xuất bản.", false);
      await loadList();
      await openEditor(paperId);
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  // ---------- editor (two-panel) ----------
  async function openEditor(paperId) {
    editorHost.classList.remove("hidden");
    listHost.classList.add("hidden");
    newButton.classList.add("hidden");
    editorHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải..."));
    try {
      const [paperData, questionData] = await Promise.all([
        request(`/api/admin/code-papers/${encodeURIComponent(paperId)}`),
        request("/api/admin/questions"),
      ]);
      current = paperData.code_paper;
      bank = (questionData.questions || []).filter((q) => q.status === "published" && SUPPORTED(q));
      selected = (current.draft && current.draft.question_ids) || [];
      renderEditor();
    } catch (error) {
      editorHost.replaceChildren(errorBox(error, () => openEditor(paperId)));
    }
  }

  function renderEditor() {
    const draft = current.draft || {};
    const nameInput = h("input", { type: "text", id: "cp-name", value: current.name, placeholder: "Tên đề thi code" });
    const countInput = h("input", { type: "number", id: "cp-count", value: draft.question_count, min: 1, max: Math.max(1, bank.length) });
    const countInfo = h("span", { class: "muted", id: "cp-count-info" }, `Tối đa ${bank.length} câu hỏi đã xuất bản.`);

    const leftSearch = h("input", { type: "search", id: "cp-left-search", placeholder: "Tìm câu hỏi..." });
    const leftType = h("select", { id: "cp-left-type" },
      h("option", { value: "" }, "Mọi loại"),
      h("option", { value: "java-reflection" }, "Java Reflection"),
      h("option", { value: "java-stdio" }, "Java STDIO"),
      h("option", { value: "python-stdio" }, "Python STDIO"));
    const rightSearch = h("input", { type: "search", id: "cp-right-search", placeholder: "Tìm trong danh sách đã chọn..." });

    const leftHost = h("div", { id: "cp-left-list", class: "cp-picker-list" });
    const rightHost = h("div", { id: "cp-right-list", class: "cp-picker-list" });

    const addAllButton = h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: addAll } }, "Thêm tất cả câu hỏi");
    const randomButton = h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: randomFill } }, "Chọn ngẫu nhiên");
    const totalInfo = h("span", { class: "muted", id: "cp-total" });

    const saveButton = h("button", { type: "button", class: "btn btn-primary", on: { click: save } }, "Lưu thay đổi");
    const publishButton = h("button", { type: "button", class: "btn btn-primary", on: { click: publish } }, "Xuất bản");
    const cancelButton = h("button", { type: "button", class: "btn btn-secondary", on: { click: cancelEdit } }, "Hủy bỏ");
    const backButton = h("button", { type: "button", class: "btn btn-secondary", on: { click: backToList } }, "Quay lại");

    const draftChanges = current.draft_changes || [];
    const changePanel = draftChanges.length
      ? h("div", { class: "alert alert-warning cp-change-panel", role: "alert" },
        h("strong", {}, `Có ${draftChanges.length} câu hỏi nguồn đã thay đổi. Hãy xử lý trước khi xuất bản.`),
        h("ul", {}, draftChanges.map((change) => h("li", {},
          h("strong", {}, `${change.position}. ${change.title || change.question_id}`),
          " — ", changeReasonText(change),
          change.code === "missing" ? null : h("a", { href: `/admin?section=exam-management&tab=questions&question=${encodeURIComponent(change.question_id)}`, target: "_blank", rel: "noopener" }, " Mở câu hỏi")))))
      : null;

    editorHost.replaceChildren(
      h("div", { class: "panel-heading" },
        h("div", {}, h("h2", {}, "Chỉnh sửa đề thi code"), h("p", { class: "muted" }, "Chọn câu hỏi đã xuất bản để tạo đề. Xuất bản sẽ tạo phiên bản bất biến.")),
        h("div", { class: "form-actions" }, backButton, cancelButton, saveButton, publishButton)),
      h("div", { class: "stack-form" },
        h("label", { for: "cp-name" }, "Tên đề thi code"), nameInput,
        h("label", { for: "cp-count" }, "Số lượng câu hỏi mong muốn"), countInput, countInfo),
      changePanel,
      h("div", { class: "cp-layout" },
        h("div", { class: "cp-panel" },
          h("h3", {}, "Ngân hàng câu hỏi"),
          h("div", { class: "filter-row" }, leftSearch, leftType, addAllButton, randomButton),
          leftHost),
        h("div", { class: "cp-panel" },
          h("h3", {}, "Câu hỏi đã chọn"),
          h("div", { class: "filter-row" }, rightSearch, totalInfo),
          rightHost)),
      h("div", { id: "cp-editor-notice", class: "notice hidden" }));

    nameInput.addEventListener("input", () => { current.name = nameInput.value; });
    countInput.addEventListener("input", () => { current.draft.question_count = Math.max(1, parseInt(countInput.value, 10) || 1); renderPickers(); });
    leftSearch.addEventListener("input", renderPickers);
    leftType.addEventListener("change", renderPickers);
    rightSearch.addEventListener("input", renderPickers);
    renderPickers();
    if (highlightChanges) {
      highlightChanges = false;
      const panel = editorHost.querySelector(".cp-change-panel");
      if (panel) panel.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function typeOf(q) {
    return `${q.language}-${q.grading_mode}`;
  }

  function renderPickers() {
    const leftHost = document.getElementById("cp-left-list");
    const rightHost = document.getElementById("cp-right-list");
    const totalInfo = document.getElementById("cp-total");
    const countInfo = document.getElementById("cp-count-info");
    if (!leftHost || !rightHost) return;

    const leftSearch = (document.getElementById("cp-left-search")?.value || "").toLowerCase();
    const leftType = document.getElementById("cp-left-type")?.value || "";
    const rightSearch = (document.getElementById("cp-right-search")?.value || "").toLowerCase();

    const selectedSet = new Set(selected);
    const changedIds = new Set((current.draft_changes || []).map((c) => c.question_id));
    const available = bank.filter((q) => !selectedSet.has(q.id));
    const filteredAvailable = available.filter((q) => {
      if (leftType && typeOf(q) !== leftType) return false;
      if (leftSearch) {
        const hay = `${q.title || ""} ${q.category || ""} ${q.id}`.toLowerCase();
        if (!hay.includes(leftSearch)) return false;
      }
      return true;
    });
    const filteredSelected = selected.map((id) => bank.find((q) => q.id === id)).filter(Boolean)
      .filter((q) => {
        if (!rightSearch) return true;
        const hay = `${q.title || ""} ${q.category || ""} ${q.id}`.toLowerCase();
        return hay.includes(rightSearch);
      });

    const total = selected.reduce((sum, id) => sum + (Number((bank.find((q) => q.id === id) || {}).total_points) || 0), 0);
    totalInfo.textContent = `Tổng điểm: ${total}`;
    countInfo.textContent = `Đã chọn ${selected.length} câu · Tối đa ${bank.length} câu hỏi đã xuất bản.`;

    const leftChildren = filteredAvailable.length
      ? filteredAvailable.map((q) => h("div", { class: "cp-picker-item" },
        h("div", {}, h("strong", {}, q.title), h("small", { class: "muted" }, `${q.category || "—"} · ${q.language}/${q.grading_mode} · ${q.total_points} điểm`)),
        h("button", { type: "button", class: "btn btn-small btn-secondary", on: { click: () => addQuestion(q.id) } }, "Thêm")))
      : [h("p", { class: "empty-cell" }, "Không có câu hỏi khớp.")];
    leftHost.replaceChildren(...leftChildren);

    const rightChildren = filteredSelected.length
      ? filteredSelected.map((q, i) => h("div", { class: `cp-picker-item${changedIds.has(q.id) ? " cp-changed" : ""}` },
        h("div", {}, h("strong", {}, `${i + 1}. ${q.title}`), changedIds.has(q.id) ? changeBadge(1, "Câu hỏi nguồn đã thay đổi") : null, h("small", { class: "muted" }, `${q.total_points} điểm`)),
        h("div", { class: "actions-inline" },
          h("button", { type: "button", class: "btn btn-small btn-ghost", on: { click: () => moveQuestion(q.id, -1) } }, "↑"),
          h("button", { type: "button", class: "btn btn-small btn-ghost", on: { click: () => moveQuestion(q.id, 1) } }, "↓"),
          h("button", { type: "button", class: "btn btn-small btn-secondary", on: { click: () => removeQuestion(q.id) } }, "Bỏ"))))
      : [h("p", { class: "empty-cell" }, "Chưa chọn câu hỏi nào.")];
    rightHost.replaceChildren(...rightChildren);
  }

  function addQuestion(id) {
    if (selected.includes(id)) return;
    selected.push(id);
    renderPickers();
  }

  function removeQuestion(id) {
    selected = selected.filter((x) => x !== id);
    renderPickers();
  }

  function moveQuestion(id, delta) {
    const index = selected.indexOf(id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= selected.length) return;
    [selected[index], selected[target]] = [selected[target], selected[index]];
    renderPickers();
  }

  function addAll() {
    const selectedSet = new Set(selected);
    for (const q of bank) if (!selectedSet.has(q.id)) selected.push(q.id);
    current.draft.question_count = selected.length;
    const countInput = document.getElementById("cp-count");
    if (countInput) countInput.value = selected.length;
    renderPickers();
  }

  function randomFill() {
    const leftType = document.getElementById("cp-left-type")?.value || "";
    const pool = bank.filter((q) => !selected.includes(q.id) && (!leftType || typeOf(q) === leftType));
    const count = current.draft.question_count || 0;
    const needed = count - selected.length;
    if (needed <= 0) {
      setNotice(document.getElementById("cp-editor-notice"), "Đã đủ số lượng câu hỏi mong muốn.", false);
      return;
    }
    if (pool.length < needed) {
      setNotice(document.getElementById("cp-editor-notice"), `Không đủ câu hỏi: cần thêm ${needed} câu nhưng chỉ còn ${pool.length} câu đủ điều kiện.`, true);
      return;
    }
    const shuffled = [...pool].sort(() => Math.random() - 0.5);
    for (const q of shuffled.slice(0, needed)) selected.push(q.id);
    renderPickers();
  }

  async function save() {
    const name = document.getElementById("cp-name")?.value || "";
    const count = parseInt(document.getElementById("cp-count")?.value, 10) || 1;
    try {
      const data = await request(`/api/admin/code-papers/${encodeURIComponent(current.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, question_count: count, question_ids: selected }),
      });
      current = data.code_paper;
      selected = (current.draft && current.draft.question_ids) || [];
      highlightChanges = false;
      setNotice(document.getElementById("cp-editor-notice"), "Đã lưu bản nháp.", false);
      renderEditor();
    } catch (error) {
      setNotice(document.getElementById("cp-editor-notice"), errorText(error), true);
    }
  }

  async function publish() {
    const name = document.getElementById("cp-name")?.value || "";
    const count = parseInt(document.getElementById("cp-count")?.value, 10) || 1;
    try {
      await request(`/api/admin/code-papers/${encodeURIComponent(current.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, question_count: count, question_ids: selected }),
      });
      const data = await request(`/api/admin/code-papers/${encodeURIComponent(current.id)}/publish`, { method: "POST" });
      setNotice(document.getElementById("cp-editor-notice"), "Đã xuất bản đề thi code.", false);
      current = data.code_paper;
      await loadList();
      await openDetail(current.id);
    } catch (error) {
      const body = error.body && typeof error.body === "object" ? error.body : {};
      const invalid = body.invalid_questions || [];
      const lines = [errorText(error)];
      for (const item of invalid) lines.push(`• ${item.reason || "Câu hỏi không hợp lệ."}`);
      setNotice(document.getElementById("cp-editor-notice"), lines.join(" "), true);
    }
  }

  function backToList() {
    editorHost.classList.add("hidden");
    editorHost.replaceChildren();
    listHost.classList.remove("hidden");
    newButton.classList.remove("hidden");
    setNotice(notice, "", false);
    loadList();
  }

  async function cancelEdit() {
    highlightChanges = false;
    // Discard unsaved editor changes and return to the read-only preview.
    if (current && current.versions && current.versions.length) {
      await openDetail(current.id);
    } else {
      backToList();
    }
  }

  async function createNew() {
    try {
      const data = await request("/api/admin/code-papers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Đề thi code mới", question_count: 1, question_ids: [] }),
      });
      setNotice(notice, "Đã tạo đề thi code mới.", false);
      await loadList();
      await openEditor(data.code_paper.id);
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  newButton.addEventListener("click", createNew);
  loadList();
})();