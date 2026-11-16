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
  function paperErrorText(error) {
    const body = error?.body || {};
    if (error?.code === "QUESTION_LIMIT_MISMATCH") {
      const expected = body.expected_count;
      const actual = body.actual_count;
      return `Selected question count must exactly match Question Limit${Number.isInteger(expected) ? ` (${expected} expected, ${actual} selected)` : ""}.`;
    }
    if (error?.code === "INVALID_QUESTION_LIMIT" && Number.isInteger(body.question_bank_max)) {
      return `Question Limit must be between 1 and ${body.question_bank_max} (the current Question Bank size).`;
    }
    return errorText(error);
  }

  let papers = [];
  let questions = [];
  let questionBankMax = 0;
  let current = null;
  let selected = [];
  let isNew = false;
  let busy = false;
  let editorOperation = "";
  let editorFeedback = "";
  let editorFeedbackError = false;
  let stalePaperId = null;
  let activeDraftCacheKey = null;
  let editorStorageHandler = null;
  const editorTabId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  let viewGeneration = 0;
  let listGeneration = 0;

  function beginView() {
    viewGeneration += 1;
    busy = false;
    editorOperation = "";
    editorFeedback = "";
    editorFeedbackError = false;
    stalePaperId = null;
    return viewGeneration;
  }

  function isCurrentView(generation, paperId) {
    return generation === viewGeneration && (paperId === undefined || current?.id === paperId);
  }

  async function loadList() {
    const generation = ++listGeneration;
    listHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải danh sách Paper…"));
    try {
      const data = await request("/api/admin/papers");
      if (generation !== listGeneration) return;
      papers = data.papers || [];
      renderList();
    } catch (error) {
      if (generation !== listGeneration) return;
      listHost.replaceChildren(errorBox(error, loadList));
    }
  }

  function renderList() {
    const newButton = h("button", { type: "button", class: "btn btn-primary", on: { click: createNew } },
      h("i", { class: "fa fa-plus" }), " Tạo đề thi");
    if (papers.some((paper) => paper.schema_version >= 2)) {
      const cards = papers.map((paper) => {
        const actions = [];
        const action = (label, handler, cls = "btn-secondary") => h("button", {
          type: "button", class: `btn btn-small ${cls}`, on: { click: handler },
        }, label);
        if (paper.status === "archived") actions.push(action("Restore", () => restore(paper)));
        else {
          actions.push(action(paper.status === "draft" ? "Edit Draft" : "Preview", () =>
            paper.schema_version >= 2 && paper.status === "draft" ? openEditor(paper.id) : openPaper(paper.id)));
          if (paper.status === "published") actions.push(action("Edit", () => openEditor(paper.id)));
          actions.push(action("Archive", () => archive(paper), "btn-ghost"));
        }
        actions.push(action("Delete", () => removePaper(paper), "btn-danger"));
        const identity = paper.schema_version >= 2 ? `Paper ID ${paper.id}` : `Legacy versions: ${paper.version_count}`;
        const unavailableCount = (paper.warnings || []).length;
        return h("article", { class: "panel qb-preview-item" },
          h("div", { class: "panel-heading" }, h("div", {}, h("h3", {}, paper.title),
            h("span", { class: `status-pill ${paper.status === "published" ? "status-green" : "status-gray"}` }, paper.status)),
            h("div", { class: "actions-inline" }, ...actions)),
          h("p", { class: "muted" }, `${paper.question_count} questions · ${identity}`),
          unavailableCount ? h("p", { class: "alert alert-warning", role: "status" },
            `⚠ ${unavailableCount} question${unavailableCount === 1 ? " is" : "s are"} unavailable`) : null,
          h("p", { class: "fine-print" }, `Revision ${paper.revision}`));
      });
      listHost.replaceChildren(
        h("div", { class: "panel-heading" }, h("div", {}, h("h2", {}, "Exam Papers"),
          h("p", { class: "muted" }, "Each Paper is managed as an independent card.")), newButton),
        h("div", { class: "qb-picker-list" }, ...cards));
      return;
    }
    const rows = papers.map((paper) => {
      const statusLabel = paper.status === "published" ? "Đã xuất bản" : paper.status === "archived" ? "Lưu trữ" : "Nháp";
      const statusClass = paper.status === "published" ? "status-green" : "status-gray";
      const action = (label, fn, cls = "btn-secondary") => h("button", {
        type: "button", class: `btn btn-small ${cls}`, on: { click: (event) => { event.stopPropagation(); fn(); } },
      }, label);
      const actions = [action(paper.schema_version >= 2 && paper.status === "draft" ? "Edit" : "Preview", () => {
        if (paper.schema_version >= 2 && paper.status === "draft") openEditor(paper.id); else openPaper(paper.id);
      })];
      if (paper.status === "archived") actions.push(action("Khôi phục", () => restore(paper)));
      else if (!(paper.schema_version >= 2 && paper.status === "draft")) actions.push(action("Edit", () => openEditor(paper.id)));
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
    const generation = beginView();
    editorHost.classList.remove("hidden");
    listHost.classList.add("hidden");
    editorHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải Paper…"));
    try {
      const paper = await loadPaper(paperId);
      if (!isCurrentView(generation) || paper?.id !== paperId) return;
      current = paper;
      isNew = false;
      if (paper.schema_version >= 2 && paper.status === "published") {
        await preview(paperId);
        return;
      }
      await renderDetail();
    } catch (error) {
      if (!isCurrentView(generation)) return;
      editorHost.replaceChildren(errorBox(error, () => openPaper(paperId)));
    }
  }

  async function renderDetail() {
    if (current?.schema_version >= 2) {
      editorHost.replaceChildren(
        h("div", { class: "panel-heading" }, h("div", {}, h("h2", {}, current.title), h("p", { class: "muted" }, `${current.status} · Paper ${current.id} · revision ${current.revision}`)),
          h("div", { class: "form-actions" },
            h("button", { type: "button", class: "btn btn-secondary", on: { click: backToList } }, "Back to Papers"),
            current.status !== "archived" ? h("button", { type: "button", class: "btn btn-primary", on: { click: () => openEditor(current.id) } }, "Edit Paper") : null)),
        current.preview ? renderPreview(current.preview) : h("p", { class: "muted" }, "No preview available."));
      return;
    }
    const versions = Object.values(current.versions || {}).sort((a, b) => a.version - b.version);
    const latestVersion = versions[versions.length - 1];
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
      h("p", { class: "fine-print", role: "status", "data-role": "paper-version-status" },
        `Paper ${current.id} · revision ${current.revision} · bản xuất bản mới nhất ${latestVersion ? `v${latestVersion.version} (${latestVersion.id})` : "chưa có"}`),
      editorFeedback ? h("p", { class: editorFeedbackError ? "alert alert-error" : "alert", role: "status" }, editorFeedback) : null,
      current.draft ? h("section", { class: "exam-form-section" },
        h("h3", {}, "Bản nháp hiện tại"),
        ...(current.draft.warnings || []).map((warning) => h("p", { class: "alert alert-warning", role: "status" }, `${warning.title || warning.question_id}: ${warning.warning}`)),
        h("button", { type: "button", class: "btn btn-small btn-secondary", on: { click: () => openEditor(current.id) } }, "Tiếp tục chỉnh sửa bản nháp")) : null,
      h("p", { class: "muted" }, `Metadata: ${JSON.stringify(current.metadata || {})}`),
      h("div", {}, ...(versionRows.length ? versionRows : [h("p", { class: "empty-cell" }, "Paper chưa có version xuất bản.")])));
    if (current.preview) editorHost.append(renderPreview(current.preview));
  }

  async function preview(paperId, versionId) {
    const generation = viewGeneration;
    if (!isCurrentView(generation, paperId)) return;
    try {
      const query = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
      const data = await request(`/api/admin/papers/${encodeURIComponent(paperId)}/preview${query}`);
      if (!isCurrentView(generation, paperId)) return;
      current = { ...current, preview: data.preview };
      await renderDetail();
    } catch (error) {
      if (!isCurrentView(generation, paperId)) return;
      setNotice(notice, errorText(error), true);
    }
  }

  function renderPreview(previewData) {
    const version = previewData.paper || previewData.version;
    const draft = previewData.draft;
    const questionsInPreview = version?.questions || draft?.questions || [];
    const sourceWarnings = version?.warnings || previewData.warnings || [];
    return h("section", { class: "qb-preview", role: "region", "aria-label": "Nội dung Paper" },
      h("h3", {}, version ? `${version.title} · ${version.id}` : "Draft Preview · Xem trước bản nháp"),
      ...sourceWarnings.map((item) => h("p", { class: "alert alert-warning", role: "status" }, `${item.title || item.question_id}: ${item.warning}`)),
      ...questionsInPreview.map((question, index) => h("article", { class: "qb-preview-item" },
        h("h4", {}, `Câu ${index + 1}: ${question.title || question.question_id}`),
        h("p", { class: "fine-print" }, `${question.language || ""}/${question.grading_mode || ""} · ${Number(question.total_points) || 0} điểm`),
        h("div", { class: "qb-statement" }, question.statement || ""),
        question.starter_code ? h("pre", { class: "qb-code" }, question.starter_code) : null)));
  }

  async function openEditor(paperId) {
    const generation = beginView();
    editorHost.classList.remove("hidden");
    listHost.classList.add("hidden");
    editorHost.replaceChildren(h("p", { class: "muted pad" }, "Đang mở trình chỉnh sửa…"));
    try {
      const [paper, bank] = await Promise.all([
        paperId ? loadPaper(paperId) : Promise.resolve(null),
        request("/api/admin/questions"),
      ]);
      if (!isCurrentView(generation) || (paperId && paper?.id !== paperId)) return;
      current = paper;
      const allBankQuestions = bank.questions || [];
      questionBankMax = allBankQuestions.length;
      questions = allBankQuestions.filter((question) => question.status === "published" && supported(question));
      isNew = !paper;
      const activeVersion = paper?.versions?.[paper.current_version_id];
      selected = [...(paper?.schema_version >= 2 ? (paper.question_ids || paper.questions?.map((q) => q.question_id) || []) : paper?.draft?.question_ids || activeVersion?.questions?.map((q) => q.question_id) || [])];
      renderEditor();
    } catch (error) {
      if (!isCurrentView(generation)) return;
      editorHost.replaceChildren(errorBox(error, () => openEditor(paperId)));
    }
  }

  function renderEditor() {
    const editorGeneration = viewGeneration;
    const independent = current?.schema_version >= 2;
    const ownerKey = document.querySelector?.(".sidebar strong")?.textContent.trim() || "unknown";
    const editorContext = current?.id || "new-paper";
    const cacheKey = `css-paper-editor:${encodeURIComponent(ownerKey)}:${encodeURIComponent(editorContext)}`;
    activeDraftCacheKey = cacheKey;
    const draft = independent ? current : current?.draft || {};
    const activeVersion = current?.versions?.[current.current_version_id];
    const savedQuestions = new Map((activeVersion?.questions || []).map((q) => [q.question_id, q]));
    const selectedBank = new Map((questions || []).map((q) => [q.id, q]));
    const normalize = (value) => (typeof value === "string" ? value.trim().toLowerCase() : "");
    const questionTags = (question) => {
      const raw = question?.tags;
      const values = Array.isArray(raw) ? raw : typeof raw === "string" ? raw.split(",") : [];
      return values.filter((tag) => typeof tag === "string" && tag.trim()).map(normalize);
    };
    const savedFilters = draft.question_filters && typeof draft.question_filters === "object" && !Array.isArray(draft.question_filters)
      ? draft.question_filters : {};
    const filters = {
      search: typeof savedFilters.search === "string" ? savedFilters.search : "",
      category: normalize(savedFilters.category),
      language: normalize(savedFilters.language),
      grading_mode: normalize(savedFilters.grading_mode),
      difficulty: normalize(savedFilters.difficulty),
      tags: new Set(Array.isArray(savedFilters.tags) ? savedFilters.tags.map(normalize).filter(Boolean) : []),
    };
    const initialQuantity = questionBankMax === 0 || draft.question_limit === null ? ""
      : Number.isInteger(draft.question_limit) && draft.question_limit >= 1 && draft.question_limit <= questionBankMax
        ? String(draft.question_limit) : draft.question_limit === undefined ? "1" : "";
    const titleInput = h("input", { type: "text", id: "cp-title", maxlength: 200, value: draft.title || current?.title || "", placeholder: "Tên đề thi" });
    const metadataInput = h("textarea", { id: "cp-metadata", rows: 3, placeholder: "{}" }, JSON.stringify(draft.metadata || current?.metadata || {}, null, 2));
    const serverEditorState = { title: titleInput.value, metadata: metadataInput.value, selected: [...selected] };
    const search = h("input", { type: "search", value: filters.search, "data-filter": "search", placeholder: "Tìm theo tiêu đề, ID hoặc tag…" });
    const categories = [...new Set([...questions.map((q) => normalize(q.category)).filter(Boolean), filters.category].filter(Boolean))].sort();
    const difficulties = [...new Set([...questions.map((q) => normalize(q.difficulty)).filter(Boolean), filters.difficulty].filter(Boolean))].sort();
    const availableTags = [...new Set([...questions.flatMap(questionTags), ...filters.tags])].sort();
    const optionList = (values, selectedValue, allLabel) => [
      h("option", { value: "", selected: !selectedValue }, allLabel),
      ...values.map((value) => h("option", { value, selected: value === selectedValue }, value)),
    ];
    const categoryFilter = h("select", { value: filters.category, "data-filter": "category" }, ...optionList(categories, filters.category, "Tất cả danh mục"));
    const languageFilter = h("select", { value: filters.language, "data-filter": "language" },
      ...optionList(["java", "python"], filters.language, "Tất cả ngôn ngữ"));
    const typeFilter = h("select", { value: filters.grading_mode, "data-filter": "grading_mode" },
      ...optionList(["reflection", "stdio"], filters.grading_mode, "Tất cả kiểu chấm"));
    const difficultyFilter = h("select", { value: filters.difficulty, "data-filter": "difficulty" },
      ...optionList(difficulties, filters.difficulty, "Mọi độ khó"));
    const tagFilters = new Map();
    const tagFilterHost = h("div", { class: "qb-filter-tags", "aria-label": "Lọc theo tags" }, ...availableTags.map((tag) => {
      const checkbox = h("input", { type: "checkbox", checked: filters.tags.has(tag), "data-filter-tag": tag });
      tagFilters.set(tag, checkbox);
      checkbox.addEventListener("change", (event) => {
        if (event.target.checked) filters.tags.add(tag); else filters.tags.delete(tag);
        refreshFilterResults();
      });
      return h("label", { class: "checkbox-row" }, checkbox, ` ${tag}`);
    }));
    const quantityInput = h("input", {
      type: "number", min: 1, max: questionBankMax || undefined, step: "any", value: initialQuantity, "data-field": "question-limit",
      "aria-label": "Số lượng câu hỏi",
    });
    serverEditorState.quantity = quantityInput.value;
    serverEditorState.filters = { ...filters, tags: [...filters.tags].sort() };
    let staleLocalDraft = false;
    let recoveredLocalDraft = false;
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
      if (cached && cached.base_revision === (current?.revision ?? null)) {
        recoveredLocalDraft = true;
        titleInput.value = cached.title ?? titleInput.value;
        metadataInput.value = cached.metadata ?? metadataInput.value;
        if (Array.isArray(cached.selected)) selected = cached.selected.filter((id) => typeof id === "string");
        quantityInput.value = cached.quantity ?? quantityInput.value;
        for (const key of ["search", "category", "language", "grading_mode", "difficulty"]) {
          if (typeof cached.filters?.[key] === "string") filters[key] = cached.filters[key];
        }
        if (Array.isArray(cached.filters?.tags)) filters.tags = new Set(cached.filters.tags);
      } else if (cached) staleLocalDraft = true;
    } catch { /* Ignore malformed or unavailable local editor storage. */ }
    search.value = filters.search;
    categoryFilter.value = filters.category;
    languageFilter.value = filters.language;
    typeFilter.value = filters.grading_mode;
    difficultyFilter.value = filters.difficulty;
    tagFilters.forEach((checkbox, tag) => { checkbox.checked = filters.tags.has(tag); });
    const counts = h("p", { class: "fine-print", "data-role": "question-counts" });
    const quantityNotice = h("p", { class: "fine-print", role: "status", "data-role": "question-limit-status" });
    const lifecycleStatus = h("div", { class: "alert", role: "status", "data-role": "paper-lifecycle" });
    const operationStatus = h("p", { class: "fine-print", role: "status", "data-role": "paper-operation" });
    const resetFilters = h("button", { type: "button", class: "btn btn-small btn-ghost", on: { click: () => {
      filters.search = ""; filters.category = ""; filters.language = ""; filters.grading_mode = ""; filters.difficulty = ""; filters.tags.clear();
      search.value = ""; categoryFilter.value = ""; languageFilter.value = ""; typeFilter.value = ""; difficultyFilter.value = "";
      tagFilters.forEach((checkbox) => { checkbox.checked = false; });
      refreshFilterResults();
    } } }, "Xóa bộ lọc");
    const availableHost = h("div", { class: "qb-picker-list" });
    const selectedHost = h("ol", { class: "qb-selected-list" });
    const canEdit = current?.status !== "archived";
    let selectionBusy = false;
    const filteredSelection = h("input", { type: "checkbox", "data-role": "filtered-selection", disabled: !canEdit });
    const randomButton = h("button", { type: "button", class: "btn btn-small btn-secondary", disabled: !canEdit,
      on: { click: randomizeSelection } }, "Chọn ngẫu nhiên đúng N câu (thay danh sách)");
    const selectAllButton = h("button", { type: "button", class: "btn btn-small btn-secondary", disabled: !canEdit,
      on: { click: selectAllFiltered } }, "Chọn tất cả câu phù hợp (thay danh sách)");
    const deselectAllButton = h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit,
      on: { click: clearSelection } }, "Bỏ chọn tất cả");
    const selectionNotice = h("p", { class: "fine-print", role: "status", "data-role": "selection-status" });
    const previewHost = current?.preview ? renderPreview(current.preview) : h("div", {});
    const saveButton = h("button", { type: "button", class: "btn btn-primary", disabled: !canEdit || busy, on: { click: save } }, independent && current?.status === "published" ? "Save Changes" : "Save Draft");
    const previewButton = h("button", { type: "button", class: "btn btn-secondary", disabled: !canEdit || busy || isNew,
      on: { click: previewSavedDraft } }, "Preview Draft · Xem trước bản nháp");
    const publishButton = h("button", { type: "button", class: "btn btn-primary", disabled: !canEdit || busy, on: { click: publish } }, independent ? "Publish Paper" : "Publish Version · Xuất bản version");
    const saveDraftCopyButton = h("button", { type: "button", class: "btn btn-secondary", disabled: !canEdit || busy || !independent || current?.status !== "published", on: { click: saveDraftCopy } }, "Save Draft Copy");

    function filteredQuestions() {
      const query = normalize(filters.search);
      return questions.filter((q) => {
        if (filters.category && normalize(q.category) !== filters.category) return false;
        if (filters.language && normalize(q.language) !== filters.language) return false;
        if (filters.grading_mode && normalize(q.grading_mode) !== filters.grading_mode) return false;
        if (filters.difficulty && normalize(q.difficulty) !== filters.difficulty) return false;
        const tags = questionTags(q);
        if (filters.tags.size && ![...filters.tags].some((tag) => tags.includes(tag))) return false;
        if (query && !`${q.title || ""} ${q.id || ""} ${tags.join(" ")}`.toLowerCase().includes(query)) return false;
        return true;
      });
    }

    function quantityIsValid(pool) {
      const quantity = Number(quantityInput.value);
      return questionBankMax > 0 && Number.isInteger(quantity) && quantity >= 1
        && quantity <= questionBankMax && selected.length === quantity;
    }

    function draftSelectionIsValid(pool) {
      if (new Set(selected).size !== selected.length) return false;
      const rawQuantity = quantityInput.value.trim();
      if (!rawQuantity) return true;
      const quantity = Number(rawQuantity);
      return Number.isInteger(quantity) && quantity >= 1 && questionBankMax > 0 && quantity <= questionBankMax;
    }

    function editorFingerprint() {
      return JSON.stringify({
        title: titleInput.value,
        metadata: metadataInput.value,
        question_ids: selected,
        question_limit: quantityInput.value,
        question_filters: { ...filters, tags: [...filters.tags].sort() },
      });
    }

    let savedFingerprint = isNew ? null : JSON.stringify({
      title: serverEditorState.title, metadata: serverEditorState.metadata,
      question_ids: serverEditorState.selected, question_limit: serverEditorState.quantity,
      question_filters: serverEditorState.filters,
    });
    function persistLocalDraft() {
      if (staleLocalDraft) return;
      try {
        localStorage.setItem(cacheKey, JSON.stringify({ base_revision: current?.revision ?? null,
          title: titleInput.value, metadata: metadataInput.value, selected, quantity: quantityInput.value,
          filters: { ...filters, tags: [...filters.tags] }, tab_id: editorTabId, saved_at: Date.now() }));
      } catch { /* Storage can be disabled or full; editing remains available in memory. */ }
    }
    if (staleLocalDraft) {
      editorFeedback = "A local editing session exists for an older Paper revision. It was not restored; copy or discard it explicitly before continuing.";
      editorFeedbackError = true;
    }
    if (recoveredLocalDraft) editorFeedback = "Recovered local unsaved input for this Paper revision.";
    if (editorStorageHandler) window.removeEventListener?.("storage", editorStorageHandler);
    editorStorageHandler = (event) => {
      if (event.key !== cacheKey || !event.newValue) return;
      try {
        const other = JSON.parse(event.newValue);
        if (other.tab_id && other.tab_id !== editorTabId) {
          staleLocalDraft = true;
          editorFeedback = "Another tab updated this local editing session. This tab will not overwrite that cache.";
          editorFeedbackError = true;
          updateLifecycleStatus();
        }
      } catch { /* Ignore malformed cross-tab state. */ }
    };
    window.addEventListener?.("storage", editorStorageHandler);
    function updateLifecycleStatus() {
      const latest = Object.values(current?.versions || {}).sort((a, b) => b.version - a.version)[0];
      const dirty = savedFingerprint === null || editorFingerprint() !== savedFingerprint;
      if (dirty && editorFeedback && !editorFeedbackError && !busy) editorFeedback = "";
      const state = isNew ? "Chưa lưu · Unsaved Changes" : dirty ? "Có thay đổi chưa lưu · Unsaved Changes" : "Đã lưu · Saved";
      lifecycleStatus.className = `alert${editorFeedbackError ? " alert-error" : ""}`;
      lifecycleStatus.replaceChildren(
        h("span", {}, `${state} · Paper ${current?.id || "chưa có ID"} · draft revision ${current?.revision ?? "chưa có"} · bản xuất bản mới nhất ${latest ? `v${latest.version} (${latest.id})` : "chưa có"}`),
        editorFeedback ? h("p", { class: editorFeedbackError ? "alert alert-error" : "fine-print" }, editorFeedback) : null,
        stalePaperId ? h("button", { type: "button", class: "btn btn-small btn-secondary", "data-role": "reload-stale-paper", on: { click: () => {
          if (window.confirm("Tải lại bản mới nhất sẽ bỏ các thay đổi chưa lưu trên màn hình. Tiếp tục?")) openEditor(stalePaperId);
        } } }, "Tải lại bản mới nhất") : null,
      );
      operationStatus.textContent = editorOperation === "save" ? "Đang lưu bản nháp…"
        : editorOperation === "preview" ? "Đang tạo Draft Preview…"
          : editorOperation === "publish" ? "Đang xuất bản version…" : "";
      const hasDraftChanges = dirty || isNew;
      const unchangedPublished = independent && current?.status === "published" && !dirty;
      saveButton.disabled = !canEdit || busy || unchangedPublished || !titleInput.value.trim() || !draftSelectionIsValid(filteredQuestions());
      saveDraftCopyButton.disabled = !canEdit || busy || !independent || current?.status !== "published"
        || !titleInput.value.trim() || !draftSelectionIsValid(filteredQuestions());
      previewButton.disabled = !canEdit || busy || isNew;
      publishButton.disabled = !canEdit || busy || !hasDraftChanges && current?.status === "published"
        || !titleInput.value.trim() || !quantityIsValid(filteredQuestions());
    }

    function renderQuestions() {
      persistLocalDraft();
      const pool = filteredQuestions();
      quantityInput.max = String(questionBankMax);
      quantityInput.disabled = !canEdit || questionBankMax === 0;
      const quantity = Number(quantityInput.value);
      const selectedMatchingPool = new Set(pool.map((question) => question.id));
      const selectedMatchingCount = pool.filter((question) => selected.includes(question.id)).length;
      filteredSelection.checked = pool.length > 0 && selectedMatchingCount === pool.length;
      filteredSelection.indeterminate = selectedMatchingCount > 0 && selectedMatchingCount < pool.length;
      filteredSelection.disabled = !canEdit || busy || selectionBusy || pool.length === 0;
      const withinPool = true;
      const canSelectMore = Number.isInteger(quantity) && quantity >= 1 && quantity <= pool.length && selected.length < quantity;
      counts.textContent = `Đã chọn ${selected.length}/${quantityInput.value || 0} câu · Có ${pool.length} câu phù hợp bộ lọc.`;
      if (!pool.length) quantityNotice.textContent = "Không có câu Published phù hợp. Hãy xóa hoặc nới bộ lọc.";
      else if (!withinPool) quantityNotice.textContent = "Số lượng phải là số nguyên trong giới hạn số câu phù hợp bộ lọc.";
      else if (quantity > pool.length) quantityNotice.textContent = "Paper cũ có câu được giữ lại ngoài bộ lọc hiện tại; hãy giữ nguyên hoặc bỏ câu rõ ràng trước khi thêm câu mới.";
      else if (selected.length > quantity) quantityNotice.textContent = "Số câu đã chọn vượt số lượng. Hãy bỏ câu rõ ràng hoặc tăng số lượng; lựa chọn không bị xóa tự động.";
      else if (selected.length < quantity) quantityNotice.textContent = `Hãy chọn thêm ${quantity - selected.length} câu để đủ số lượng.`;
      else quantityNotice.textContent = "";
      if (questionBankMax === 0) quantityNotice.textContent = "Question Bank is empty. A valid Question Limit cannot be set, and publishing is unavailable.";
      else if (!quantityInput.value.trim()) quantityNotice.textContent = "Enter a whole-number Question Limit before publishing. Drafts can be saved incomplete.";
      else if (!Number.isInteger(quantity) || quantity < 1 || quantity > questionBankMax) quantityNotice.textContent = `Question Limit must be a whole number from 1 to ${questionBankMax}.`;
      else if (!pool.length) quantityNotice.textContent = "No eligible Published questions match the current filters.";
      else if (selected.length > quantity) quantityNotice.textContent = "Selected question count exceeds Question Limit. Selection was retained.";
      else if (selected.length < quantity) quantityNotice.textContent = `Select ${quantity - selected.length} more question(s) to match Question Limit.`;
      else quantityNotice.textContent = "";
      const randomCanRun = Number.isInteger(quantity) && quantity >= 1 && quantity <= pool.length;
      randomButton.disabled = !canEdit || busy || selectionBusy || !randomCanRun;
      selectAllButton.disabled = !canEdit || busy || selectionBusy || pool.length === 0;
      deselectAllButton.disabled = !canEdit || busy || selectionBusy || selected.length === 0;
      selectionNotice.textContent = pool.length
        ? `${selectedMatchingCount}/${pool.length} câu phù hợp đang được chọn` + (selected.length > selectedMatchingCount ? ` · ${selected.length - selectedMatchingCount} câu nằm ngoài bộ lọc` : "") + ". Random và Chọn tất cả thay toàn bộ danh sách; nhóm checkbox giữ lại câu ngoài bộ lọc."
        : "Không có câu phù hợp; các câu đã chọn ngoài bộ lọc vẫn được giữ.";
      updateLifecycleStatus();
      const selectedMatching = new Set(pool.map((q) => q.id));
      const available = pool.filter((q) => !selected.includes(q.id));
      availableHost.replaceChildren(...(available.length ? available.map((q) => h("div", { class: "qb-item" },
        h("span", { class: "qb-main" }, h("strong", {}, q.title), h("small", {}, `${q.language}/${q.grading_mode} · ${q.total_points} điểm`)),
            h("button", { type: "button", class: "btn btn-small btn-secondary", disabled: !canEdit || busy || selectionBusy || !canSelectMore, on: { click: () => { selected.push(q.id); renderQuestions(); } } }, "Thêm")))
        : [h("p", { class: "empty-cell" }, questions.length ? "Không có câu hỏi phù hợp bộ lọc." : "Không có câu hỏi Published đủ điều kiện.") ]));

      selectedHost.replaceChildren(...(selected.length ? selected.map((id, index) => {
        const q = selectedBank.get(id) || savedQuestions.get(id);
        const inactive = !selectedBank.has(id);
        const outsideFilter = !inactive && !selectedMatching.has(id);
        const status = inactive ? (q ? "Nguồn không còn Published; giữ snapshot cũ" : "Nguồn đã bị xóa và không có snapshot cũ")
          : outsideFilter ? "Ngoài bộ lọc hiện tại; vẫn được giữ" : "Published";
        return h("li", { class: `qb-selected${inactive ? " qb-warn" : ""}` },
          h("span", { class: "qb-index" }, `${index + 1}.`),
          h("span", { class: "qb-main" }, h("strong", {}, q?.title || id), h("small", {}, `${q?.total_points ?? "—"} điểm · ${status}`)),
          h("span", { class: "qb-actions" },
            h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit || index === 0, on: { click: () => { [selected[index - 1], selected[index]] = [selected[index], selected[index - 1]]; renderQuestions(); } } }, "↑"),
            h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit || index === selected.length - 1, on: { click: () => { [selected[index + 1], selected[index]] = [selected[index], selected[index + 1]]; renderQuestions(); } } }, "↓"),
            h("button", { type: "button", class: "btn btn-small btn-ghost", disabled: !canEdit, on: { click: () => {
              selected = selected.filter((entry) => entry !== id);
              renderQuestions();
            } } }, "Bỏ")));
      }) : [h("li", { class: "muted" }, "Chưa chọn câu hỏi." )]));
    }
    function refreshFilterResults() {
      renderQuestions();
    }
    let lastValidQuantity = Number.isInteger(Number(quantityInput.value))
      && Number(quantityInput.value) >= 1 && Number(quantityInput.value) <= questionBankMax
      ? String(Number(quantityInput.value)) : "";
    function commitQuestionLimit() {
      if (questionBankMax === 0) {
        quantityInput.value = "";
        quantityNotice.textContent = "Question Bank is empty. A valid Question Limit cannot be set, and publishing is unavailable.";
        renderQuestions();
        return;
      }
      const raw = quantityInput.value.trim();
      if (!raw) { quantityNotice.textContent = "Enter a whole-number Question Limit before publishing. Drafts can be saved incomplete."; renderQuestions(); return; }
      const value = Number(raw);
      if (!Number.isFinite(value) || !Number.isInteger(value)) {
        quantityInput.value = lastValidQuantity;
        quantityNotice.textContent = "Question Limit must be a whole number.";
      } else {
        quantityInput.value = String(Math.min(questionBankMax, Math.max(1, value)));
        lastValidQuantity = quantityInput.value;
      }
      renderQuestions();
    }
    function confirmReplacement(actionName, nextIds) {
      if (!selected.length || (selected.length === nextIds.length && selected.every((id, index) => id === nextIds[index]))) return true;
      return window.confirm(`${actionName} sẽ thay ${selected.length} câu đang chọn bằng ${nextIds.length} câu mới. Tiếp tục?`);
    }
    function randomizeSelection() {
      if (selectionBusy || busy) return;
      const pool = filteredQuestions();
      const quantity = Number(quantityInput.value);
      const uniquePool = [...new Map(pool.filter((question) => typeof question.id === "string" && question.id).map((question) => [question.id, question])).values()];
      if (!Number.isInteger(quantity) || quantity < 1 || uniquePool.length < quantity) {
        selectionNotice.textContent = `Không đủ câu phù hợp để chọn ${quantityInput.value || "N"}; hiện có ${uniquePool.length}.`;
        return;
      }
      const candidates = [...uniquePool];
      for (let index = candidates.length - 1; index > 0; index -= 1) {
        const swapIndex = Math.floor(Math.random() * (index + 1));
        [candidates[index], candidates[swapIndex]] = [candidates[swapIndex], candidates[index]];
      }
      const nextIds = candidates.slice(0, quantity).map((question) => question.id);
      if (!confirmReplacement("Chọn ngẫu nhiên", nextIds)) return;
      selectionBusy = true;
      try { selected = nextIds; } finally { selectionBusy = false; }
      renderQuestions();
    }
    function selectAllFiltered() {
      if (selectionBusy || busy) return;
      const pool = filteredQuestions();
      const nextIds = [...new Set(pool.map((question) => question.id).filter((id) => typeof id === "string" && id))];
      if (!nextIds.length) {
        selectionNotice.textContent = "Không có câu Published phù hợp để chọn.";
        return;
      }
      if (!confirmReplacement("Chọn tất cả câu phù hợp", nextIds)) return;
      selectionBusy = true;
      try {
        selected = nextIds;
      } finally {
        selectionBusy = false;
      }
      renderQuestions();
    }
    function clearSelection() {
      if (selectionBusy || busy || !selected.length) return;
      if (!window.confirm(`Bỏ chọn toàn bộ ${selected.length} câu hỏi?`)) return;
      selectionBusy = true;
      try {
        selected = [];
      } finally {
        selectionBusy = false;
      }
      renderQuestions();
    }
    filteredSelection.addEventListener("change", () => {
      if (selectionBusy || busy) return;
      const pool = filteredQuestions();
      const matchingIds = new Set(pool.map((question) => question.id));
      selectionBusy = true;
      try {
        if (filteredSelection.checked) {
          const matching = pool.map((question) => question.id).filter((id) => typeof id === "string" && id);
          selected = [...selected.filter((id) => !matchingIds.has(id)), ...new Set(matching)];
        } else {
          selected = selected.filter((id) => !matchingIds.has(id));
        }
      } finally {
        selectionBusy = false;
      }
      renderQuestions();
    });
    for (const control of [categoryFilter, languageFilter, typeFilter, difficultyFilter]) {
      control.addEventListener("change", () => {
        filters[control.dataset.filter] = normalize(control.value);
        refreshFilterResults();
      });
    }
    search.addEventListener("input", () => { filters.search = search.value; refreshFilterResults(); });
    quantityInput.addEventListener("input", renderQuestions);
    quantityInput.addEventListener("blur", commitQuestionLimit);
    titleInput.addEventListener("input", renderQuestions);
    metadataInput.addEventListener("input", renderQuestions);
    savedFingerprint = isNew ? null : editorFingerprint();
    renderQuestions();

    editorHost.replaceChildren(
      h("div", { class: "panel-heading" }, h("div", {}, h("h2", {}, isNew ? "Tạo Paper" : `Chỉnh sửa Paper: ${current.title}`), h("p", { class: "muted" }, "Danh sách đã chọn giữ nguyên thứ tự. Câu mới chỉ lấy từ câu hỏi Published.")),
        h("div", { class: "form-actions" },
          h("button", { type: "button", class: "btn btn-secondary", on: { click: backToList } }, "Cancel"),
          saveButton, independent && current?.status === "published" ? saveDraftCopyButton : null,
          !independent && previewButton, (!independent || current?.status === "draft") ? publishButton : null)),
      lifecycleStatus, operationStatus,
      isNew ? h("p", { class: "fine-print", role: "status" }, "Lưu bản nháp để có Paper ID và mở Draft Preview.") : null,
      current?.status === "archived" ? h("div", { class: "alert alert-warning" }, "Paper đang lưu trữ. Khôi phục Paper trước khi chỉnh sửa.") : null,
      ...(current?.draft?.warnings || []).map((item) => h("div", { class: "alert alert-warning", role: "status" }, `${item.title || item.question_id}: ${item.warning}`)),
      h("div", { class: "stack-form" }, h("label", { for: "cp-title" }, "Tên Paper"), titleInput, h("label", { for: "cp-metadata" }, "Metadata dạng JSON"), metadataInput),
      h("div", { class: "qb-question-tools" },
        h("div", { class: "exam-rows" },
          h("label", {}, "Từ khóa", search),
          h("label", {}, "Danh mục", categoryFilter),
          h("label", {}, "Ngôn ngữ", languageFilter),
          h("label", {}, "Kiểu câu hỏi / chấm", typeFilter),
          h("label", {}, "Độ khó", difficultyFilter),
          h("div", {}, h("span", {}, "Tags (khớp bất kỳ)"), tagFilterHost)),
        resetFilters),
      quantityInput, counts, quantityNotice,
      h("div", { class: "qb-selection-tools" },
        h("label", { class: "checkbox-row" }, filteredSelection, " Chọn/bỏ chọn nhóm câu phù hợp (giữ câu ngoài bộ lọc)"),
        randomButton, selectAllButton, deselectAllButton, selectionNotice),
      h("div", { class: "exam-builder" },
        h("div", { class: "qb-panel" }, h("h3", {}, "Câu hỏi đã xuất bản"), availableHost),
        h("div", { class: "qb-panel" }, h("h3", {}, `Thứ tự câu hỏi (${selected.length})`), selectedHost)),
      previewHost,
      h("div", { id: "cp-editor-notice", class: "notice hidden" }));

    async function save({ deferRender = false } = {}) {
      if (busy) return false;
      const targetPaperId = current?.id || null;
      const expectedRevision = current?.revision;
      const creating = isNew;
      let sessionPaperId = targetPaperId;
      const ownsEditor = () => isCurrentView(editorGeneration, sessionPaperId || undefined)
        && (sessionPaperId !== null || (creating && isNew));
      const dirty = savedFingerprint === null || editorFingerprint() !== savedFingerprint;
      if (!dirty) return true;
      let metadata;
      try {
        metadata = JSON.parse(metadataInput.value || "{}");
        if (!metadata || Array.isArray(metadata) || typeof metadata !== "object") throw new Error("Metadata phải là JSON object.");
      } catch (error) {
        setNotice(document.getElementById("cp-editor-notice"), `Metadata không hợp lệ: ${error.message}`, true);
        return false;
      }
      const filteredPool = filteredQuestions();
      const quantity = quantityInput.value.trim() ? Number(quantityInput.value) : null;
      if (!titleInput.value.trim() || !draftSelectionIsValid(filteredPool)) {
        editorFeedback = "Bản nháp cần tên Paper hợp lệ; số lượng phải nguyên, không nhỏ hơn số câu đã chọn và nằm trong pool hiện tại. Có thể lưu khi chưa chọn đủ N câu.";
        editorFeedbackError = true;
        updateLifecycleStatus();
        return false;
      }
      busy = true;
      editorOperation = "save";
      editorFeedback = "";
      editorFeedbackError = false;
      updateLifecycleStatus();
      let saved = false;
      try {
        const payload = {
          title: titleInput.value.trim(), metadata, question_ids: [...selected],
          question_limit: quantity, question_filters: {
            ...filters, tags: [...filters.tags],
          },
        };
        const data = creating
          ? await request("/api/admin/papers/independent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
          : await request(`/api/admin/papers/${encodeURIComponent(targetPaperId)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, expected_revision: expectedRevision }) });
        if (!ownsEditor()) {
          void loadList();
          return false;
        }
        if (!data.paper?.id || (targetPaperId && data.paper.id !== targetPaperId)) {
          throw new Error("Save response Paper ID does not match the active Paper.");
        }
        sessionPaperId = data.paper.id;
        current = data.paper;
        isNew = false;
        selected = [...(current.draft?.question_ids || selected)];
        savedFingerprint = editorFingerprint();
        try { localStorage.removeItem(cacheKey); } catch { /* Ignore unavailable storage. */ }
        editorFeedback = `Đã lưu bản nháp tại revision ${current.revision}.`;
        editorFeedbackError = false;
        stalePaperId = null;
        await loadList();
        if (!ownsEditor()) return false;
        saved = true;
      } catch (error) {
        if (!ownsEditor()) return false;
        const stale = error.status === 409 && error.code === "PAPER_CHANGED";
        stalePaperId = stale ? targetPaperId : null;
        if (["QUESTION_LIMIT_MISMATCH", "INVALID_QUESTION_LIMIT"].includes(error.code)) editorFeedback = paperErrorText(error);
        editorFeedback = stale
          ? `Không lưu được vì Paper đã thay đổi ở nơi khác. Các chỉnh sửa hiện tại vẫn được giữ. ${errorText(error)}`
          : `Lưu bản nháp thất bại: ${errorText(error)}`;
        editorFeedbackError = true;
        if (["QUESTION_LIMIT_MISMATCH", "INVALID_QUESTION_LIMIT"].includes(error.code)) editorFeedback = paperErrorText(error);
      } finally {
        if (editorGeneration === viewGeneration) {
          busy = false;
          editorOperation = "";
        }
      }
      if (saved) {
        if (deferRender) updateLifecycleStatus();
        else renderEditor();
        return true;
      }
      renderQuestions();
      return false;
    }

    async function saveDraftCopy() {
      if (busy || !independent || current?.status !== "published") return;
      let metadata;
      try {
        metadata = JSON.parse(metadataInput.value || "{}");
        if (!metadata || Array.isArray(metadata) || typeof metadata !== "object") throw new Error("Metadata must be a JSON object.");
      } catch (error) {
        setNotice(document.getElementById("cp-editor-notice"), error.message, true);
        return;
      }
      if (!titleInput.value.trim() || !draftSelectionIsValid(filteredQuestions())) return;
      const payload = { expected_revision: current.revision, title: titleInput.value.trim(), metadata,
        question_ids: [...selected], question_limit: quantityInput.value.trim() ? Number(quantityInput.value) : null,
        question_filters: { ...filters, tags: [...filters.tags] } };
      try {
        await request(`/api/admin/papers/${encodeURIComponent(current.id)}/draft-copy`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        backToList();
      } catch (error) {
        setNotice(document.getElementById("cp-editor-notice"), errorText(error), true);
      }
    }

    async function publish() {
      if (busy) return;
      const generation = editorGeneration;
      const hadUnsavedChanges = savedFingerprint === null || editorFingerprint() !== savedFingerprint;
      if (hadUnsavedChanges && !(await save({ deferRender: true }))) return;
      if (!isCurrentView(generation)) return;
      if (!current || isNew || (!current.draft && current.schema_version < 2)) return;
      const paperId = current.id;
      const expectedRevision = current.revision;
      busy = true;
      editorOperation = "publish";
      editorFeedback = "";
      editorFeedbackError = false;
      updateLifecycleStatus();
      let published = false;
      try {
        const data = await request(`/api/admin/papers/${encodeURIComponent(paperId)}/publish`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision: expectedRevision }),
        });
        if (!isCurrentView(generation, paperId) || data.paper?.id !== paperId) {
          void loadList();
          return;
        }
        current = data.paper;
        try { localStorage.removeItem(cacheKey); } catch { /* Ignore unavailable storage. */ }
        const version = current.versions?.[current.current_version_id];
        editorFeedback = version
          ? `Đã xuất bản version ${version.id} (v${version.version}).`
          : "Đã xuất bản version mới.";
        editorFeedbackError = false;
        stalePaperId = null;
        await loadList();
        await renderDetail();
        published = true;
      } catch (error) {
        if (!isCurrentView(generation, paperId)) return;
        const stale = error.status === 409 && error.code === "PAPER_CHANGED";
        stalePaperId = stale ? paperId : null;
        const savedRevision = current?.revision;
        editorFeedback = `Draft saved${savedRevision ? ` · revision ${savedRevision}` : ""}; publishing failed: ${errorText(error)}`
          + (stale ? " Các chỉnh sửa đã lưu vẫn được giữ; hãy tải lại để xem trạng thái mới nhất." : "");
        editorFeedbackError = true;
      } finally {
        if (generation === viewGeneration) {
          busy = false;
          editorOperation = "";
        }
      }
      if (!published) renderEditor();
    }

    async function previewSavedDraft() {
      if (busy) return;
      const generation = editorGeneration;
      if (isNew || !current?.id) {
        editorFeedback = "Lưu bản nháp để có Paper ID và mở Draft Preview.";
        editorFeedbackError = false;
        updateLifecycleStatus();
        return;
      }
      const paperId = current.id;
      if (savedFingerprint === null || editorFingerprint() !== savedFingerprint) {
        if (!(await save({ deferRender: true }))) return;
      }
      if (!isCurrentView(generation, paperId) || isNew) return;
      const expectedRevision = current.revision;
      busy = true;
      editorOperation = "preview";
      editorFeedback = "";
      editorFeedbackError = false;
      updateLifecycleStatus();
      try {
        const latest = await loadPaper(paperId);
        if (!isCurrentView(generation, paperId)) return;
        if (latest.revision !== expectedRevision || current.revision !== expectedRevision) {
          const conflict = new Error("Paper đã thay đổi ở nơi khác; tải lại trước khi preview.");
          conflict.status = 409;
          conflict.code = "PAPER_CHANGED";
          throw conflict;
        }
        const data = await request(`/api/admin/papers/${encodeURIComponent(paperId)}/preview?draft=1`);
        if (!isCurrentView(generation, paperId)) return;
        current = { ...current, preview: data.preview };
        editorFeedback = `Draft Preview được tạo từ revision ${current.revision}; không xuất bản version.`;
        editorFeedbackError = false;
      } catch (error) {
        if (!isCurrentView(generation, paperId)) return;
        const stale = error.status === 409 && error.code === "PAPER_CHANGED";
        stalePaperId = stale ? paperId : null;
        editorFeedback = `Draft Preview thất bại: ${errorText(error)}`;
        editorFeedbackError = true;
      } finally {
        if (generation === viewGeneration) {
          busy = false;
          editorOperation = "";
        }
      }
      if (isCurrentView(generation, paperId)) renderEditor();
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
    openEditor(null);
  }

  function backToList() {
    beginView();
    if (editorStorageHandler) window.removeEventListener?.("storage", editorStorageHandler);
    editorStorageHandler = null;
    if (activeDraftCacheKey) {
      try { localStorage.removeItem(activeDraftCacheKey); } catch { /* Ignore unavailable storage. */ }
    }
    activeDraftCacheKey = null;
    editorHost.classList.add("hidden");
    editorHost.replaceChildren();
    listHost.classList.remove("hidden");
    setNotice(notice, "", false);
    loadList();
  }

  document.addEventListener?.("visibilitychange", () => {
    if (!document.hidden) void loadList();
  });
  loadList();
})();
