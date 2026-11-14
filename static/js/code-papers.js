(() => {
  "use strict";
  const root = document.getElementById("code-papers-view");
  if (!root) return;

  const { h, errorBox, errorText, setNotice } = window.cssUi;
  const request = window.cssRequest;
  const listHost = document.getElementById("cp-list");
  const editorHost = document.getElementById("cp-editor");
  const notice = document.getElementById("cp-notice");
  const supported = (q) =>
    (q.language === "java" && ["reflection", "stdio"].includes(q.grading_mode)) ||
    (q.language === "python" && q.grading_mode === "stdio");

  let papers = [];
  let questions = [];
  let current = null;
  let selected = [];
  let isNew = false;
  let busy = false;

  async function loadList() {
    listHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải danh sách Paper…"));
    try {
      const data = await request("/api/admin/papers");
      papers = data.papers || [];
      renderList();
    } catch (error) {
      listHost.replaceChildren(errorBox(error, loadList));
    }
  }

  function renderList() {
    const newButton = h("button", { type: "button", class: "btn btn-primary", on: { click: createNew } },
      h("i", { class: "fa fa-plus" }), " Tạo đề thi");
    const rows = papers.map((paper) => {
      const statusLabel = paper.status === "published" ? "Đã xuất bản" : paper.status === "archived" ? "Lưu trữ" : "Nháp";
      const statusClass = paper.status === "published" ? "status-green" : "status-gray";
      const action = (label, fn, cls = "btn-secondary") => h("button", {
        type: "button", class: `btn btn-small ${cls}`, on: { click: (event) => { event.stopPropagation(); fn(); } },
      }, label);
      const actions = [action("Mở", () => openPaper(paper.id))];
      if (paper.status === "archived") actions.push(action("Khôi phục", () => restore(paper)));
      else actions.push(action("Chỉnh sửa", () => openEditor(paper.id)));
      if (paper.status !== "archived") actions.push(action("Lưu trữ", () => archive(paper), "btn-ghost"));
      actions.push(action("Xóa", () => removePaper(paper), "btn-danger"));
      const metadata = Object.entries(paper.metadata || {})
        .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
        .join(" · ") || "—";
      return h("tr", {},
        h("td", {}, h("strong", {}, paper.title), paper.warnings?.length ? h("span", { class: "qb-change-badge", title: `${paper.warnings.length} câu hỏi nguồn cần lưu ý` }, "!") : null),
        h("td", {}, metadata),
        h("td", {}, paper.question_count),
        h("td", {}, paper.version_count),
        h("td", {}, h("span", { class: `status-pill ${statusClass}` }, statusLabel)),
        h("td", {}, h("div", { class: "actions-inline" }, ...actions)));
    });
    listHost.replaceChildren(
      h("div", { class: "panel-heading" },
        h("div", {}, h("h2", {}, "Quản lý đề thi"), h("p", { class: "muted" }, "Tạo Paper có thứ tự từ câu hỏi đã xuất bản. Mỗi lần xuất bản tạo một version bất biến.")), newButton),
      h("div", { class: "table-scroll" }, h("table", { class: "data-table" },
        h("thead", {}, h("tr", {}, ...["Tên Paper", "Metadata", "Số câu", "Versions", "Trạng thái", "Thao tác"].map((label) => h("th", {}, label)))),
        h("tbody", {}, ...(rows.length ? rows : [h("tr", {}, h("td", { colspan: 6, class: "empty-cell" }, "Chưa có Paper nào."))])))));
  }

  async function loadPaper(paperId) {
    const data = await request(`/api/admin/papers/${encodeURIComponent(paperId)}`);
    return data.paper;
  }

  async function openPaper(paperId) {
    editorHost.classList.remove("hidden");
    listHost.classList.add("hidden");
    editorHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải Paper…"));
    try {
      current = await loadPaper(paperId);
      isNew = false;
      await renderDetail();
    } catch (error) {
      editorHost.replaceChildren(errorBox(error, () => openPaper(paperId)));
    }
  }

  async function renderDetail() {
    const versions = Object.values(current.versions || {}).sort((a, b) => a.version - b.version);
    const statusInfo = current.status === "archived" ? "Paper đang lưu trữ." : current.status === "published" ? "Paper đã xuất bản; version đã phát hành không thể sửa." : "Paper đang ở trạng thái Nháp.";
    const versionRows = versions.map((version) => h("section", { class: "qb-preview-item" },
      h("div", { class: "panel-heading" },
        h("div", {}, h("h3", {}, `${version.title} · v${version.version}`), h("p", { class: "fine-print" }, `${version.id} · ${version.questions.length} câu · ${version.published_at || ""}`)),
        h("button", { type: "button", class: "btn btn-small btn-secondary", on: { click: () => preview(current.id, version.id) } }, "Xem version")),
      ...(version.warnings || []).map((warning) => h("p", { class: "alert alert-warning", role: "status" }, `${warning.title || warning.question_id}: ${warning.warning}`))));
    editorHost.replaceChildren(
      h("div", { class: "panel-heading" }, h("div", {}, h("h2", {}, current.title), h("p", { class: "muted" }, statusInfo)),
        h("div", { class: "form-actions" },
          h("button", { type: "button", class: "btn btn-secondary", on: { click: backToList } }, "Quay lại"),
          current.status !== "archived" ? h("button", { type: "button", class: "btn btn-primary", on: { click: () => openEditor(current.id) } }, "Chỉnh sửa bản mới") : null,
          current.status === "archived" ? h("button", { type: "button", class: "btn btn-primary", on: { click: () => restore(current) } }, "Khôi phục") : null)),
      current.draft ? h("section", { class: "exam-form-section" },
        h("h3", {}, "Bản nháp hiện tại"),
        ...(current.draft.warnings || []).map((warning) => h("p", { class: "alert alert-warning", role: "status" }, `${warning.title || warning.question_id}: ${warning.warning}`)),
        h("button", { type: "button", class: "btn btn-small btn-secondary", on: { click: () => openEditor(current.id) } }, "Tiếp tục chỉnh sửa bản nháp")) : null,
      h("p", { class: "muted" }, `Metadata: ${JSON.stringify(current.metadata || {})}`),
      h("div", {}, ...(versionRows.length ? versionRows : [h("p", { class: "empty-cell" }, "Paper chưa có version xuất bản.")])));
    if (current.preview) editorHost.append(renderPreview(current.preview));
  }

  async function preview(paperId, versionId) {
    try {
      const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
      const data = await request(`/api/admin/papers/${encodeURIComponent(paperId)}/preview${query}`);
      current.preview = data.preview;
      await renderDetail();
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  function renderPreview(previewData) {
    const version = previewData.version;
    const draft = previewData.draft;
    const questionsInPreview = version?.questions || draft?.questions || [];
    const sourceWarnings = version?.warnings || previewData.warnings || [];
    return h("section", { class: "qb-preview", role: "region", "aria-label": "Nội dung Paper" },
      h("h3", {}, version ? `${version.title} · ${version.id}` : "Xem trước bản nháp"),
      ...sourceWarnings.map((item) => h("p", { class: "alert alert-warning", role: "status" }, `${item.title || item.question_id}: ${item.warning}`)),
      ...questionsInPreview.map((question, index) => h("article", { class: "qb-preview-item" },
        h("h4", {}, `Câu ${index + 1}: ${question.title || question.question_id}`),
        h("p", { class: "fine-print" }, `${question.language || ""}/${question.grading_mode || ""} · ${Number(question.total_points) || 0} điểm`),
        h("div", { class: "qb-statement" }, question.statement || ""),
        question.starter_code ? h("pre", { class: "qb-code" }, question.starter_code) : null)));
  }

  async function openEditor(paperId) {
    editorHost.classList.remove("hidden");
    listHost.classList.add("hidden");
    editorHost.replaceChildren(h("p", { class: "muted pad" }, "Đang mở trình chỉnh sửa…"));
    try {
      const [paper, bank] = await Promise.all([
        paperId ? loadPaper(paperId) : Promise.resolve(null),
        request("/api/admin/questions"),
      ]);
      current = paper;
      questions = (bank.questions || []).filter((question) => question.status === "published" && supported(question));
      isNew = !paper;
      const activeVersion = paper?.versions?.[paper.current_version_id];
      selected = [...(paper?.draft?.question_ids || activeVersion?.questions?.map((q) => q.question_id) || [])];
      renderEditor();
    } catch (error) {
      editorHost.replaceChildren(errorBox(error, () => openEditor(paperId)));
    }
  }

  function renderEditor() {
    const draft = current?.draft || {};
    const activeVersion = current?.versions?.[current.current_version_id];
    const savedQuestions = new Map((activeVersion?.questions || []).map((q) => [q.question_id, q]));
    const selectedBank = new Map((questions || []).map((q) => [q.id, q]));
    const titleInput = h("input", { type: "text", id: "cp-title", maxlength: 200, value: draft.title || current?.title || "", placeholder: "Tên đề thi" });
    const metadataInput = h("textarea", { id: "cp-metadata", rows: 3, placeholder: "{}" }, JSON.stringify(draft.metadata || current?.metadata || {}, null, 2));
    const search = h("input", { type: "search", placeholder: "Tìm câu hỏi đã xuất bản…" });
    const availableHost = h("div", { class: "qb-picker-list" });
    const selectedHost = h("ol", { class: "qb-selected-list" });
    const previewHost = current?.preview ? renderPreview(current.preview) : h("div", {});
    const canEdit = current?.status !== "archived";

    function renderQuestions() {
      const query = search.value.trim().toLowerCase();
      const available = questions.filter((q) => !selected.includes(q.id) && `${q.title} ${q.category || ""} ${q.id}`.toLowerCase().includes(query));
      availableHost.replaceChildren(...(available.length ? available.map((q) => h("div", { class: "qb-item" },
        h("span", { class: "qb-main" }, h("strong", {}, q.title), h("small", {}, `${q.language}/${q.grading_mode} · ${q.total_points} điểm`)),
        h("button", { type: "button", class: "btn btn-small btn-secondary", disabled: !canEdit, on: { click: () => { selected.push(q.id); renderQuestions(); } } }, "Thêm")))
        : [h("p", { class: "empty-cell" }, questions.length ? "Không có câu hỏi phù hợp." : "Không có câu hỏi Published đủ điều kiện.") ]));

      selectedHost.replaceChildren(...(selected.length ? selected.map((id, index) => {
        const q = selectedBank.get(id) || savedQuestions.get(id);
        const inactive = !selectedBank.has(id);
        const status = inactive ? (q ? "Nguồn không còn Published; giữ snapshot cũ" : "Nguồn đã bị xóa và không có snapshot cũ") : "Published";
        return h("li", { class: `qb-selected${inactive ? " qb-warn" : ""}` },
          h("span", { class: "qb-index" }, `${index + 1}.`),
          h("span", { class: "qb-main" }, h("strong", {}, q?.title || id), h("small", {}, `${q?.total_points ?? "—"} điểm · ${status}`)),
          h("span", { class: "qb-actions" },
            h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit || index === 0, on: { click: () => { [selected[index - 1], selected[index]] = [selected[index], selected[index - 1]]; renderQuestions(); } } }, "↑"),
            h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit || index === selected.length - 1, on: { click: () => { [selected[index + 1], selected[index]] = [selected[index], selected[index + 1]]; renderQuestions(); } } }, "↓"),
            h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit, on: { click: () => { selected = selected.filter((entry) => entry !== id); renderQuestions(); } } }, "Bỏ")));
      }) : [h("li", { class: "muted" }, "Chưa chọn câu hỏi." )]));
    }
    search.addEventListener("input", renderQuestions);
    renderQuestions();

    const saveButton = h("button", { type: "button", class: "btn btn-primary", disabled: !canEdit || busy, on: { click: save } }, "Lưu bản nháp");
    const publishButton = h("button", { type: "button", class: "btn btn-primary", disabled: !canEdit || busy, on: { click: publish } }, "Xuất bản version");
    editorHost.replaceChildren(
      h("div", { class: "panel-heading" }, h("div", {}, h("h2", {}, isNew ? "Tạo Paper" : `Chỉnh sửa Paper: ${current.title}`), h("p", { class: "muted" }, "Danh sách đã chọn giữ nguyên thứ tự. Câu mới chỉ lấy từ câu hỏi Published.")),
        h("div", { class: "form-actions" },
          h("button", { type: "button", class: "btn btn-secondary", on: { click: backToList } }, "Quay lại"),
          !isNew ? h("button", { type: "button", class: "btn btn-ghost", on: { click: async () => { if (await save()) await previewDraft(current.id); } } }, "Xem trước bản nháp") : null,
          saveButton, publishButton)),
      current?.status === "archived" ? h("div", { class: "alert alert-warning" }, "Paper đang lưu trữ. Khôi phục Paper trước khi chỉnh sửa.") : null,
      ...(current?.draft?.warnings || []).map((item) => h("div", { class: "alert alert-warning", role: "status" }, `${item.title || item.question_id}: ${item.warning}`)),
      h("div", { class: "stack-form" }, h("label", { for: "cp-title" }, "Tên Paper"), titleInput, h("label", { for: "cp-metadata" }, "Metadata dạng JSON"), metadataInput),
      h("div", { class: "exam-builder" },
        h("div", { class: "qb-panel" }, h("h3", {}, "Câu hỏi đã xuất bản"), search, availableHost),
        h("div", { class: "qb-panel" }, h("h3", {}, `Thứ tự câu hỏi (${selected.length})`), selectedHost)),
      previewHost,
      h("div", { id: "cp-editor-notice", class: "notice hidden" }));

    async function save() {
      if (busy) return false;
      let metadata;
      try {
        metadata = JSON.parse(metadataInput.value || "{}");
        if (!metadata || Array.isArray(metadata) || typeof metadata !== "object") throw new Error("Metadata phải là JSON object.");
      } catch (error) {
        setNotice(document.getElementById("cp-editor-notice"), `Metadata không hợp lệ: ${error.message}`, true);
        return false;
      }
      if (!titleInput.value.trim() || !selected.length) {
        setNotice(document.getElementById("cp-editor-notice"), "Cần nhập tên Paper và chọn ít nhất một câu hỏi.", true);
        return false;
      }
      busy = true;
      try {
        const payload = { title: titleInput.value.trim(), metadata, question_ids: [...selected] };
        const data = isNew
          ? await request("/api/admin/papers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
          : await request(`/api/admin/papers/${encodeURIComponent(current.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, expected_revision: current.revision }) });
        current = data.paper;
        isNew = false;
        selected = [...(current.draft?.question_ids || selected)];
        setNotice(document.getElementById("cp-editor-notice"), "Đã lưu bản nháp.", false);
        await loadList();
        renderEditor();
        return true;
      } catch (error) {
        setNotice(document.getElementById("cp-editor-notice"), errorText(error), true);
        return false;
      } finally {
        busy = false;
      }
    }

    async function publish() {
      if (!(await save())) return;
      if (!current || isNew || !current.draft) return;
      try {
        const data = await request(`/api/admin/papers/${encodeURIComponent(current.id)}/publish`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision: current.revision }),
        });
        current = data.paper;
        await loadList();
        await renderDetail();
      } catch (error) {
        setNotice(document.getElementById("cp-editor-notice"), errorText(error), true);
      }
    }
  }

  async function previewDraft(paperId) {
    try {
      const data = await request(`/api/admin/papers/${encodeURIComponent(paperId)}/preview`);
      current = await loadPaper(paperId);
      current.preview = data.preview;
      renderEditor();
    } catch (error) {
      setNotice(notice, errorText(error), true);
    }
  }

  async function archive(paper) {
    try {
      await request(`/api/admin/papers/${encodeURIComponent(paper.id)}/archive`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: paper.revision }) });
      await loadList();
    } catch (error) { setNotice(notice, errorText(error), true); }
  }

  async function restore(paper) {
    try {
      await request(`/api/admin/papers/${encodeURIComponent(paper.id)}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: paper.revision }) });
      await loadList();
    } catch (error) { setNotice(notice, errorText(error), true); }
  }

  async function removePaper(paper) {
    if (!window.confirm(`Xóa Paper “${paper.title}”? Paper đang được tham chiếu sẽ không thể xóa.`)) return;
    try {
      await request(`/api/admin/papers/${encodeURIComponent(paper.id)}/delete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: paper.revision }) });
      await loadList();
    } catch (error) { setNotice(notice, errorText(error), true); }
  }

  function createNew() {
    current = null;
    selected = [];
    isNew = true;
    openEditor(null);
  }

  function backToList() {
    editorHost.classList.add("hidden");
    editorHost.replaceChildren();
    listHost.classList.remove("hidden");
    setNotice(notice, "", false);
    loadList();
  }

  loadList();
})();
