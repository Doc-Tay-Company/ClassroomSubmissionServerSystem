(() => {
  "use strict";

  // ---------- shared DOM helpers (also used by code-exams.js) ----------
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "on") for (const [name, fn] of Object.entries(value)) node.addEventListener(name, fn);
      else if (key === "value" || key === "checked" || key === "disabled") node[key] = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat()) {
      if (child === undefined || child === null || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function errorText(error) {
    if (error && error.status === 401) return "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.";
    if (error && error.status === 403) return "Bạn không có quyền thực hiện thao tác này.";
    return (error && error.message) || "Đã có lỗi xảy ra.";
  }

  function errorBox(error, retry) {
    const box = h("div", { class: "alert alert-warning" }, errorText(error), " ");
    if (error && error.status === 401) box.append(h("a", { href: "/login", class: "btn btn-small btn-secondary" }, "Đăng nhập lại"));
    else if (retry) box.append(h("button", { type: "button", class: "btn btn-small btn-secondary", on: { click: retry } }, "Thử lại"));
    return box;
  }

  function setNotice(node, message, isError) {
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("hidden", !message);
    node.classList.toggle("notice-error", Boolean(isError));
  }

  const STATUS = {
    draft: ["Nháp", "status-gray"],
    published: ["Đã xuất bản", "status-green"],
    archived: ["Lưu trữ", "status-amber"],
  };
  function statusPill(status) {
    const [label, cls] = STATUS[status] || [status || "?", "status-gray"];
    return h("span", { class: `status-pill ${cls}` }, label);
  }

  window.cssUi = { h, errorText, errorBox, setNotice, statusPill };

  const root = document.getElementById("questions-view");
  if (!root) return;

  const request = window.cssRequest;
  const listView = document.getElementById("q-list-view");
  const detailView = document.getElementById("q-detail-view");
  const editorView = document.getElementById("q-editor-view");
  const listHost = document.getElementById("q-list");
  const listNotice = document.getElementById("q-notice");
  let questions = [];

  const SERVER_OWNED = ["id", "status", "source", "usage_count", "version", "validation", "reference_source"];
  const CHECK_KINDS = {
    field: "Thuộc tính (field)",
    constructor: "Constructor",
    method: "Phương thức (method)",
    implements: "Interface",
    behavior: "Hành vi (behavior)",
    toString: "toString()",
    comparable: "Comparable",
  };
  const VALIDATION_MESSAGES = {
    VALIDATION_REQUIRED: "Câu hỏi chưa được chạy đáp án mẫu. Hãy chạy đáp án mẫu trước khi xuất bản.",
    VALIDATION_OUTDATED: "Câu hỏi đã thay đổi sau lần chạy mẫu gần nhất. Hãy chạy lại đáp án mẫu.",
    VALIDATION_FAILED: "Đáp án mẫu chưa đạt toàn bộ test. Hãy sửa câu hỏi hoặc đáp án mẫu rồi chạy lại.",
    ALREADY_PUBLISHED: "Câu hỏi đã được xuất bản.",
    QUESTION_NOT_DRAFT: "Chỉ câu hỏi ở trạng thái nháp mới được chạy mẫu hoặc xuất bản.",
    SAMPLE_REQUIRED: "Cần nhập mã nguồn đáp án mẫu để xác thực trước khi lưu thay đổi.",
    QUESTION_NOT_PUBLISHED: "Chỉ câu hỏi đã xuất bản mới thực hiện được thao tác này.",
    QUESTION_NOT_ARCHIVED: "Chỉ câu hỏi đã lưu trữ mới có thể khôi phục.",
    QUESTION_CHANGED: "Câu hỏi đã bị thay đổi trong lúc xác thực; hãy tải lại và thử lại.",
    JUDGE_INFRA_ERROR: "Hệ thống chấm gặp lỗi hạ tầng (không phải lỗi câu hỏi); thay đổi chưa được lưu.",
  };
  function friendly(error) {
    return (error && VALIDATION_MESSAGES[error.code]) || errorText(error);
  }

  function show(view) {
    for (const node of [listView, detailView, editorView]) node.classList.toggle("hidden", node !== view);
    if (creation) { creation.open = view === editorView && Boolean(editing) && !editing.id; schedulePersist(); }
    window.scrollTo({ top: 0 });
  }

  // ---------- temporary draft of the "new code question" form ----------
  const DRAFT_KEY = "css:question-creation-draft:v1";
  const QUESTION_TYPES = [["code", "Câu hỏi code"], ["choice", "Câu hỏi trắc nghiệm"], ["short", "Câu hỏi ngắn"]];
  let creation = null; // { draft, type, open } kept in memory so a storage failure never loses data
  let persistTimer = null;
  let storageFailed = false;

  function loadStoredCreation() {
    try {
      const data = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
      if (!data || data.v !== 1 || !data.draft || typeof data.draft !== "object" || Array.isArray(data.draft)) return null;
      const draft = { ...newDraft(), ...data.draft };
      draft.checks = Array.isArray(draft.checks) ? draft.checks : [];
      draft.tests = Array.isArray(draft.tests) ? draft.tests : [];
      draft.tags = Array.isArray(draft.tags) ? draft.tags : [];
      return { draft, type: QUESTION_TYPES.some(([k]) => k === data.type) ? data.type : "code", open: data.open === true };
    } catch (error) {
      return null;
    }
  }

  function persistCreationNow() {
    clearTimeout(persistTimer);
    persistTimer = null;
    if (!creation) return;
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ v: 1, type: creation.type, open: creation.open, draft: creation.draft }));
      storageFailed = false;
    } catch (error) {
      storageFailed = true;
    }
    const note = document.getElementById("q-storage-note");
    if (note) note.classList.toggle("hidden", !storageFailed);
  }

  function schedulePersist() {
    if (!creation) return;
    clearTimeout(persistTimer);
    persistTimer = setTimeout(persistCreationNow, 250);
  }

  function clearCreation() {
    clearTimeout(persistTimer);
    persistTimer = null;
    creation = null;
    try { sessionStorage.removeItem(DRAFT_KEY); } catch (error) { /* nothing stored */ }
  }

  window.addEventListener("pagehide", persistCreationNow);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") persistCreationNow(); });
  // Bound inputs update the draft first; these bubbled events then snapshot it (covers dynamic add/remove/copy/reorder clicks).
  for (const type of ["input", "change", "click"]) {
    editorView.addEventListener(type, () => { if (editing && !editing.id) schedulePersist(); });
  }

  // ---------- list ----------
  async function loadList() {
    listHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải danh sách câu hỏi..."));
    try {
      const data = await request("/api/admin/questions");
      questions = data.questions || [];
      renderList();
    } catch (error) {
      listHost.replaceChildren(errorBox(error, loadList));
    }
  }

  function filteredQuestions() {
    const value = (id) => document.getElementById(id).value.trim();
    const search = value("q-filter-search").toLowerCase();
    const language = value("q-filter-language");
    const mode = value("q-filter-mode");
    const status = value("q-filter-status");
    const category = value("q-filter-category").toLowerCase();
    const usage = value("q-filter-usage");
    return questions.filter((q) => {
      const used = Number(q.usage_count) || 0;
      if (usage === "0" && used !== 0) return false;
      if (usage === "used" && used < 1) return false;
      if (usage === "1-2" && (used < 1 || used > 2)) return false;
      if (usage === "3+" && used < 3) return false;
      if (language && q.language !== language) return false;
      if (mode && q.grading_mode !== mode) return false;
      if (status && q.status !== status) return false;
      if (category && !String(q.category || "").toLowerCase().includes(category)) return false;
      if (search) {
        const hay = `${q.title || ""} ${(q.tags || []).join(" ")} ${q.id}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });
  }

  function renderList() {
    const rows = filteredQuestions();
    document.getElementById("q-count").textContent = questions.length ? `Hiển thị ${rows.length}/${questions.length} câu hỏi` : "";
    document.getElementById("q-filter-usage-clear").classList.toggle("hidden", !document.getElementById("q-filter-usage").value);
    if (!questions.length) {
      listHost.replaceChildren(h("p", { class: "empty-cell" }, "Chưa có câu hỏi nào. Nhấn “Tạo câu hỏi” hoặc “Nhập JSON” để bắt đầu."));
      return;
    }
    if (!rows.length) {
      listHost.replaceChildren(h("p", { class: "empty-cell" }, "Không có câu hỏi khớp bộ lọc."));
      return;
    }
    const head = h("tr", {}, ...["Tiêu đề", "Ngôn ngữ / kiểu chấm", "Điểm", "Trạng thái", "Phiên bản", "Đã dùng", ""].map((t) => h("th", {}, t)));
    const body = rows.map((q) => {
      const act = (label, cls, fn) => h("button", { type: "button", class: `btn btn-small ${cls}`, on: { click: (e) => { e.stopPropagation(); fn(); } } }, label);
      const open = () => (q.status === "draft" ? openEditor(q.id) : openDetail(q.id));
      const actions = [];
      if (q.status === "published") actions.push(act("Chỉnh sửa", "btn-secondary", () => openEditor(q.id)), act("Thu hồi", "btn-ghost", () => revoke(q)));
      if (q.status === "archived") actions.push(act("Khôi phục", "btn-secondary", () => restore(q)));
      actions.push(act("Sao chép", "btn-ghost", () => duplicate(q)));
      if (q.status !== "archived") actions.push(act("Lưu trữ", "btn-ghost", () => archive(q)));
      actions.push(act("Xóa", "btn-danger", () => remove(q)));
      return h("tr", {
        class: "q-row-clickable", tabindex: "0", title: q.status === "draft" ? "Mở để chỉnh sửa" : "Mở để xem",
        on: {
          click: open,
          keydown: (e) => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(); } },
        },
      },
        h("td", {}, h("strong", {}, q.title), q.category ? h("div", { class: "fine-print" }, q.category) : null),
        h("td", {}, `${q.language} / ${q.grading_mode}`),
        h("td", {}, q.total_points),
        h("td", {}, statusPill(q.status)),
        h("td", {}, q.version ?? 1),
        h("td", {}, q.usage_count ?? 0),
        h("td", { class: "row-actions" }, ...actions));
    });
    listHost.replaceChildren(h("table", { class: "data-table" }, h("thead", {}, head), h("tbody", {}, body)));
  }

  async function mutate(promiseFactory, okMessage) {
    try {
      await promiseFactory();
      setNotice(listNotice, okMessage, false);
    } catch (error) {
      setNotice(listNotice, friendly(error), true);
    }
    await loadList();
  }

  const post = (url, body) => request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });

  function duplicate(q) {
    return mutate(() => post(`/api/admin/questions/${encodeURIComponent(q.id)}/duplicate`), "Đã nhân bản câu hỏi (bản sao ở trạng thái nháp).");
  }
  function revoke(q) {
    if (!window.confirm(`Thu hồi câu hỏi “${q.title}” về trạng thái Nháp? Các đề đã tạo vẫn giữ phiên bản cũ.`)) return;
    return mutate(() => post(`/api/admin/questions/${encodeURIComponent(q.id)}/revoke`), "Đã thu hồi câu hỏi về trạng thái Nháp.");
  }
  function restore(q) {
    return mutate(() => post(`/api/admin/questions/${encodeURIComponent(q.id)}/restore`), "Đã khôi phục câu hỏi về trạng thái Nháp (chưa xuất bản).");
  }
  function archive(q) {
    if (!window.confirm(`Lưu trữ câu hỏi “${q.title}”? Câu hỏi sẽ không thể chọn cho đề mới.`)) return;
    return mutate(() => post(`/api/admin/questions/${encodeURIComponent(q.id)}/archive`), "Đã lưu trữ câu hỏi.");
  }
  function remove(q) {
    if (!window.confirm(`Xóa vĩnh viễn câu hỏi “${q.title}”?`)) return;
    return mutate(async () => {
      try {
        await post(`/api/admin/questions/${encodeURIComponent(q.id)}/delete`);
      } catch (error) {
        if (error.status === 409) throw new Error(`Không thể xóa: câu hỏi đang được đề thi, bài nộp hoặc lượt chạy sử dụng. Hãy dùng “Lưu trữ”. (${error.message})`);
        throw error;
      }
    }, "Đã xóa câu hỏi.");
  }

  // ---------- detail + validation/publish ----------
  async function openDetail(id) {
    show(detailView);
    detailView.replaceChildren(h("p", { class: "muted pad" }, "Đang tải câu hỏi..."));
    try {
      const data = await request(`/api/admin/questions/${encodeURIComponent(id)}`);
      renderDetail(data.question);
    } catch (error) {
      detailView.replaceChildren(backButton(), errorBox(error, () => openDetail(id)));
    }
  }

  function backButton() {
    return h("button", { type: "button", class: "btn btn-ghost btn-small", on: { click: () => { show(listView); loadList(); } } }, h("i", { class: "fa fa-arrow-left" }), " Danh sách");
  }

  function kv(label, value) {
    return h("div", { class: "kv" }, h("span", { class: "muted" }, label), h("strong", {}, value === undefined || value === "" ? "—" : value));
  }

  function itemSummary(item) {
    const parts = [];
    for (const [key, value] of Object.entries(item)) {
      if (["id", "kind", "points", "is_visible"].includes(key)) continue;
      parts.push(`${key}=${typeof value === "string" ? value : JSON.stringify(value)}`);
    }
    return parts.join(", ");
  }

  const VERDICT_TEXT = { CE: "lỗi biên dịch", WA: "sai kết quả", RE: "lỗi khi chạy", TLE: "quá thời gian", MLE: "quá bộ nhớ", OLE: "quá giới hạn output" };
  function renderDetail(q) {
    const items = q.grading_mode === "reflection" ? q.checks || [] : q.tests || [];
    const sampleBox = h("textarea", { id: "q-sample-source", class: "code-area", rows: 14, spellcheck: "false", placeholder: "Dán mã nguồn đáp án mẫu (Java) tại đây" });
    const resultHost = h("div", { id: "q-validation-result" });
    const publishButton = h("button", { type: "button", class: "btn btn-primary", id: "q-publish" }, h("i", { class: "fa fa-upload" }), " Xuất bản câu hỏi");
    const runButton = h("button", { type: "button", class: "btn btn-secondary", id: "q-validate" }, h("i", { class: "fa fa-play" }), " Chạy đáp án mẫu");
    const hint = h("p", { class: "fine-print" });
    let current = q;

    function refreshPublish() {
      const validation = current.validation;
      const canPublish = current.status === "draft" && validation && validation.passed === true && validation.current !== false;
      publishButton.disabled = !canPublish;
      if (current.status === "published") hint.textContent = "Câu hỏi đã xuất bản.";
      else if (current.status === "archived") hint.textContent = "Câu hỏi đã lưu trữ.";
      else if (!validation) hint.textContent = "Chưa chạy đáp án mẫu: chưa thể xuất bản.";
      else if (!validation.passed) hint.textContent = `Lần chạy mẫu gần nhất chưa đạt (${VERDICT_TEXT[validation.verdict] || validation.verdict || "không rõ"}, ${validation.score ?? 0}/${validation.total_points ?? "?"} điểm): chưa thể xuất bản. Hãy dán đáp án mẫu đúng rồi bấm “Chạy đáp án mẫu”.`;
      else if (validation.current === false) hint.textContent = "Kết quả xác thực không còn khớp đặc tả hiện tại: hãy chạy lại đáp án mẫu.";
      else hint.textContent = `Đáp án mẫu đạt (${validation.validated_at || ""}). Có thể xuất bản.`;
      runButton.disabled = current.status !== "draft";
      sampleBox.disabled = current.status !== "draft";
    }

    runButton.addEventListener("click", async () => {
      const source = sampleBox.value;
      if (!source.trim()) { resultHost.replaceChildren(h("div", { class: "alert alert-warning" }, "Hãy nhập mã nguồn đáp án mẫu.")); return; }
      runButton.disabled = true; publishButton.disabled = true;
      resultHost.replaceChildren(h("p", { class: "muted" }, h("i", { class: "fa fa-spinner fa-spin" }), " Đang biên dịch và chạy đáp án mẫu..."));
      try {
        const result = await post(`/api/admin/questions/${encodeURIComponent(q.id)}/validate`, { sample_source: source });
        current = { ...current, validation: result.previous_pass || result.validation };
        const view = renderValidation(result);
        if (result.previous_pass) view.prepend(h("div", { class: "alert alert-warning" }, "Lần chạy này chưa đạt, nhưng đáp án mẫu đạt trước đó cho đúng đặc tả hiện tại vẫn được giữ: có thể xuất bản."));
        resultHost.replaceChildren(view);
      } catch (error) {
        const body = error.body && typeof error.body === "object" ? error.body : {};
        const lines = [friendly(error)];
        if (error.error_category || body.error_category) lines.push(`Loại lỗi: ${error.error_category || body.error_category}`);
        if (error.status === 503) lines.unshift("Hệ thống chấm gặp lỗi hạ tầng (không phải lỗi câu hỏi). Kết quả này KHÔNG được ghi nhận.");
        resultHost.replaceChildren(h("div", { class: "alert alert-warning" }, ...lines.map((l) => h("div", {}, l))));
      }
      refreshPublish();
    });

    publishButton.addEventListener("click", async () => {
      if (!window.confirm(`Xuất bản câu hỏi “${q.title}”? Sau đó có thể chọn vào đề thi code.`)) return;
      publishButton.disabled = true;
      try {
        const data = await post(`/api/admin/questions/${encodeURIComponent(q.id)}/publish`);
        current = data.question;
        setNotice(listNotice, "Đã xuất bản câu hỏi.", false);
        loadList();
        renderDetail(current);
      } catch (error) {
        resultHost.replaceChildren(h("div", { class: "alert alert-warning" }, friendly(error)));
        refreshPublish();
      }
    });

    const panel = h("div", { class: "stack-form" },
      h("div", { class: "panel-heading" },
        h("div", {}, backButton(), " ", h("strong", {}, q.title), " ", statusPill(q.status)),
        h("div", { class: "form-actions" },
          q.status === "published" ? h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: () => openEditor(q.id) } }, "Chỉnh sửa") : null,
          q.status === "published" ? h("button", { type: "button", class: "btn btn-ghost btn-small", on: { click: async () => { await revoke(q); openDetail(q.id); } } }, "Thu hồi") : null,
          q.status === "draft" ? h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: () => openEditor(q.id) } }, "Chỉnh sửa") : null,
          q.status === "archived" ? h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: async () => { await restore(q); openDetail(q.id); } } }, "Khôi phục") : null)),
      h("div", { class: "kv-grid" },
        kv("Ngôn ngữ", q.language), kv("Kiểu chấm", q.grading_mode), kv("Tổng điểm", q.total_points),
        kv("Phiên bản", q.version), kv("Đã dùng", q.usage_count), kv("Danh mục", q.category),
        kv("Độ khó", q.difficulty), kv("Tags", (q.tags || []).join(", ")),
        kv("Time limit (s)", q.time_limit_seconds), kv("Memory (MB)", q.memory_limit_mb),
        kv("Target class", q.target_class), kv("Package", q.target_package)),
      h("h3", {}, "Đề bài"),
      h("pre", { class: "code-block" }, q.statement || "(trống)"),
      q.starter_code ? [h("h3", {}, "Mã khởi tạo"), h("pre", { class: "code-block" }, q.starter_code)] : null,
      h("h3", {}, q.grading_mode === "reflection" ? `Checks (${items.length})` : `Tests (${items.length})`),
      h("div", { class: "table-scroll" }, h("table", { class: "data-table" },
        h("thead", {}, h("tr", {}, ...["ID", "Loại", "Điểm", "Hiển thị", "Chi tiết"].map((t) => h("th", {}, t)))),
        h("tbody", {}, items.map((c) => h("tr", {},
          h("td", {}, c.id), h("td", {}, c.kind || "stdio"), h("td", {}, c.points),
          h("td", {}, c.is_visible ? "Công khai" : "Ẩn"), h("td", { class: "fine-print" }, itemSummary(c))))))),
      q.status === "draft"
        ? [
            h("h3", {}, "Chạy đáp án mẫu & xuất bản"),
            h("label", { for: "q-sample-source" }, "Mã nguồn đáp án mẫu"), sampleBox,
            h("div", { class: "form-actions" }, runButton, publishButton), hint, resultHost,
          ]
        : h("p", { class: "fine-print" }, q.status === "published" ? "Câu hỏi đã xuất bản (chỉ đọc). Bấm “Chỉnh sửa” để sửa; thay đổi chỉ được lưu sau khi đáp án mẫu đạt, hoặc “Thu hồi” để đưa về Nháp." : "Câu hỏi đã lưu trữ (chỉ đọc). Bấm “Khôi phục” để đưa về Nháp."));
    detailView.replaceChildren(panel);
    refreshPublish();
  }

  function renderValidation(result) {
    const validation = result.validation || {};
    const box = h("div", { class: "validation-result" });
    if (result.reused) box.append(h("div", { class: "alert alert-success" }, "Đặc tả chấm và mã nguồn đáp án mẫu không thay đổi: kết quả xác thực trước đó được tái sử dụng, không cần chạy lại."));
    const verdictClass = validation.passed ? "status-green" : "status-red";
    box.append(h("p", {},
      h("span", { class: `status-pill ${verdictClass}` }, validation.passed ? "Đạt toàn bộ" : "Chưa đạt"), " ",
      `Verdict: ${result.verdict || "?"} · Điểm: ${result.score ?? "?"}/${result.total_points ?? "?"} · ${result.duration_ms ?? "?"} ms`));
    if (validation.stale) box.append(h("div", { class: "alert alert-warning" }, "Câu hỏi đã thay đổi trong lúc chạy; kết quả không được lưu. Hãy chạy lại."));
    if (result.error) box.append(h("div", { class: "alert alert-warning" }, `${result.error_category ? result.error_category + ": " : ""}${result.error}`));
    if (result.compile_result && (result.compile_result.stderr || result.compile_result.error)) {
      box.append(h("h4", {}, "Biên dịch"), h("pre", { class: "code-block" }, result.compile_result.stderr || result.compile_result.error));
    }
    const rows = result.results || [];
    if (rows.length) {
      box.append(h("div", { class: "table-scroll" }, h("table", { class: "data-table" },
        h("thead", {}, h("tr", {}, ...["Check", "Hiển thị", "Kết quả", "Điểm", "Kỳ vọng", "Thực tế", "Lỗi"].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows.map((r) => h("tr", {},
          h("td", {}, r.id), h("td", {}, r.is_visible ? "Công khai" : "Ẩn"),
          h("td", {}, h("span", { class: `status-pill ${r.passed ? "status-green" : "status-red"}` }, r.passed ? "Đạt" : "Sai")),
          h("td", {}, r.points_earned), h("td", { class: "fine-print" }, fmt(r.expected)),
          h("td", { class: "fine-print" }, fmt(r.actual)), h("td", { class: "fine-print" }, r.error || "")))))));
    }
    return box;
  }

  function fmt(value) {
    if (value === undefined || value === null) return "";
    return typeof value === "string" ? value : JSON.stringify(value);
  }

  // ---------- editor ----------
  const splitList = (text) => text.split(",").map((s) => s.trim()).filter(Boolean);
  const splitWords = (text) => text.split(/\s+/).filter(Boolean);
  const listToText = (value) => (Array.isArray(value) ? value.join(", ") : "");
  const argsToText = (value) => (Array.isArray(value) ? JSON.stringify(value).slice(1, -1) : "");
  const textToArgs = (text) => JSON.parse(`[${text}]`);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const modifierText = (value) => Array.isArray(value) ? value.join(" ") : (value || "");

  function toEditorCheck(check) {
    const item = clone(check);
    if (item.kind === "field") {
      item.field_name ??= item.name;
      item.expected_type ??= item.type;
      item.expected_modifiers = splitWords(modifierText(item.modifier ?? item.expected_modifiers));
      delete item.name;
      delete item.type;
      delete item.modifier;
    } else if (item.kind === "constructor") {
      item.param_types ??= item.parameter_types;
      item.expected_modifiers = splitWords(modifierText(item.modifier ?? item.expected_modifiers));
      delete item.parameter_types;
      delete item.modifier;
    } else if (item.kind === "method") {
      item.method_name ??= item.name;
      item.expected_return_type ??= item.return_type;
      item.param_types ??= item.parameter_types;
      item.expected_modifiers = splitWords(modifierText(item.modifier ?? item.expected_modifiers));
      delete item.name;
      delete item.return_type;
      delete item.parameter_types;
      delete item.modifier;
    } else if (item.kind === "implements") {
      item.expected_interface ??= item.interface;
      delete item.interface;
    } else if (item.kind === "behavior") {
      const oldSetup = item.setup;
      if (oldSetup && !Array.isArray(oldSetup)) {
        item.setup = {
          constructor_param_types: oldSetup.constructor_param_types || oldSetup.constructor_parameter_types || [],
          constructor_args: oldSetup.constructor_args || [],
        };
        item.setup_actions = [];
      } else {
        item.setup_actions = Array.isArray(oldSetup) ? oldSetup : [];
        item.setup = {
          constructor_param_types: item.constructor_parameter_types || [],
          constructor_args: item.constructor_args || [],
        };
      }
      item.invoke ??= {
        method: item.method || "",
        param_types: item.parameter_types || [],
        args: item.args || [],
      };
      if (item.expect_state && typeof item.expect_state === "object"
          && !("getter" in item.expect_state) && !("field" in item.expect_state)) {
        const [getter, value] = Object.entries(item.expect_state)[0] || ["", null];
        item.expect_state = { getter, value };
      }
      delete item.constructor_parameter_types;
      delete item.constructor_args;
      delete item.method;
      delete item.parameter_types;
      delete item.args;
    } else if (item.kind === "toString") {
      item.expected_template ??= item.template;
      delete item.template;
      const oldSetup = item.setup;
      if (oldSetup && !Array.isArray(oldSetup)) {
        item.setup = {
          constructor_param_types: oldSetup.constructor_param_types || oldSetup.constructor_parameter_types || [],
          constructor_args: oldSetup.constructor_args || [],
        };
      } else {
        item.setup = {
          constructor_param_types: item.constructor_parameter_types || [],
          constructor_args: item.constructor_args || [],
        };
      }
      item.setup_actions = Array.isArray(oldSetup) ? oldSetup : [];
      delete item.constructor_parameter_types;
      delete item.constructor_args;
    } else if (item.kind === "comparable") {
      const oldCases = item.cases;
      if (Array.isArray(oldCases)) {
        item.cases = oldCases;
      } else {
        const instances = item.instances || [];
        item.cases = (item.comparisons || []).map((comparison) => ({
          a: instances[comparison.left]?.constructor_args || [],
          b: instances[comparison.right]?.constructor_args || [],
          expected_sign: comparison.expected_sign,
        }));
        item.constructor_param_types ??= instances[0]?.constructor_parameter_types || [];
      }
      delete item.instances;
      delete item.comparisons;
    }
    return item;
  }

  function toJudgeCheck(check) {
    const item = clone(check);
    if (item.kind === "field") {
      item.name = item.field_name;
      item.type = item.expected_type;
      item.modifier = modifierText(item.expected_modifiers);
      delete item.field_name;
      delete item.expected_type;
      delete item.expected_modifiers;
    } else if (item.kind === "constructor") {
      item.parameter_types = item.param_types || [];
      item.modifier = modifierText(item.expected_modifiers);
      delete item.param_types;
      delete item.expected_modifiers;
    } else if (item.kind === "method") {
      item.name = item.method_name;
      item.return_type = item.expected_return_type;
      item.parameter_types = item.param_types || [];
      item.modifier = modifierText(item.expected_modifiers);
      delete item.method_name;
      delete item.expected_return_type;
      delete item.param_types;
      delete item.expected_modifiers;
    } else if (item.kind === "implements") {
      item.interface = item.expected_interface;
      delete item.expected_interface;
    } else if (item.kind === "behavior") {
      const setup = item.setup || {};
      item.constructor_parameter_types = setup.constructor_param_types || [];
      item.constructor_args = setup.constructor_args || [];
      item.setup = item.setup_actions || [];
      item.method = item.invoke?.method || "";
      item.parameter_types = item.invoke?.param_types || [];
      item.args = item.invoke?.args || [];
      if (item.expect_state && typeof item.expect_state === "object") {
        const state = item.expect_state;
        if (state.getter || state.field) {
          item.expect_state = { ...state, value: state.value };
        }
      }
      delete item.setup_actions;
      delete item.invoke;
    } else if (item.kind === "toString") {
      const setup = item.setup || {};
      item.constructor_parameter_types = setup.constructor_param_types || [];
      item.constructor_args = setup.constructor_args || [];
      item.setup = item.setup_actions || [];
      item.template = item.expected_template || "";
      delete item.expected_template;
      delete item.setup_actions;
    } else if (item.kind === "comparable") {
      const parameterTypes = item.constructor_param_types || [];
      item.instances = [];
      item.comparisons = [];
      for (const testCase of item.cases || []) {
        const left = item.instances.length;
        item.instances.push({ constructor_parameter_types: parameterTypes, constructor_args: testCase.a || [] });
        const right = item.instances.length;
        item.instances.push({ constructor_parameter_types: parameterTypes, constructor_args: testCase.b || [] });
        item.comparisons.push({ left, right, expected_sign: Number(testCase.expected_sign) });
      }
      delete item.cases;
      delete item.constructor_param_types;
    }
    return item;
  }

  function toEditorQuestion(question) {
    const draft = clone(question);
    if (Array.isArray(draft.checks)) draft.checks = draft.checks.map(toEditorCheck);
    return draft;
  }

  let editing = null; // { id, draft, isNew }

  function newDraft() {
    return {
      title: "", statement: "", language: "java", grading_mode: "reflection",
      target_class: "", target_package: "", target_file: "", starter_code: "",
      time_limit_seconds: 5, memory_limit_mb: 256, max_output_bytes: 65536,
      allow_pretest: true, max_pretest_runs: 20, category: "", tags: [], difficulty: "",
      checks: [], tests: [], total_points: 0,
    };
  }

  async function openEditor(id, imported) {
    if (!id) {
      if (imported) creation = { draft: imported, type: "code", open: true };
      else if (!creation) creation = { draft: newDraft(), type: "code", open: true };
      editing = { id: null, draft: creation.draft, original: null };
      show(editorView);
      renderEditor();
      persistCreationNow();
      return;
    }
    editing = null;
    show(editorView);
    editorView.replaceChildren(h("p", { class: "muted pad" }, "Đang tải câu hỏi..."));
    try {
      const data = await request(`/api/admin/questions/${encodeURIComponent(id)}`);
      editing = { id, draft: toEditorQuestion(data.question), original: data.question, sample: data.question.reference_source || "" };
      renderEditor();
    } catch (error) {
      editorView.replaceChildren(backButton(), errorBox(error, () => openEditor(id)));
    }
  }

  // bind helper: input -> draft[key] with conversion; bad input is flagged so save can block
  function bindInput(input, target, key, parse, format) {
    const initial = target[key];
    input.value = format ? format(initial) : initial ?? "";
    input.addEventListener("input", () => {
      try {
        const parsed = parse ? parse(input.value) : input.value;
        target[key] = parsed;
        input.removeAttribute("data-bad");
        input.classList.remove("invalid");
      } catch (error) {
        input.setAttribute("data-bad", "1");
        input.classList.add("invalid");
      }
      if (key === "points") refreshTotal();
      markValidationDirty();
    });
    return input;
  }

  function field(label, input, hint) {
    return h("label", { class: "field" }, h("span", {}, label), input, hint ? h("small", { class: "fine-print" }, hint) : null);
  }

  const num = (text) => {
    const value = Number(text);
    if (text.trim() === "" || !Number.isFinite(value)) throw new Error("number");
    return value;
  };
  const jsonValue = (text) => JSON.parse(text);

  let totalNode = null;
  function refreshTotal() {
    if (!editing || !totalNode) return;
    const items = editing.draft.grading_mode === "reflection" ? editing.draft.checks : editing.draft.tests;
    const total = items.reduce((sum, c) => sum + (Number(c.points) || 0), 0);
    editing.draft.total_points = Math.round(total * 1e6) / 1e6;
    totalNode.textContent = editing.draft.total_points;
  }

  function renderEditor() {
    const d = editing.draft;
    const isReflection = d.grading_mode === "reflection";
    const isNew = !editing.id;
    totalNode = h("strong", {}, d.total_points);

    const language = h("select", {}, h("option", { value: "java" }, "Java"), h("option", { value: "python" }, "Python"));
    language.value = d.language;
    language.addEventListener("change", () => {
      d.language = language.value;
      if (d.language === "python") d.grading_mode = "stdio";
      markValidationDirty();
      collectAndRender();
    });
    const mode = h("select", {}, h("option", { value: "reflection" }, "reflection (kiểm tra cấu trúc class)"), h("option", { value: "stdio" }, "stdio (so sánh đầu ra)"));
    mode.value = d.grading_mode;
    mode.disabled = d.language === "python";
    mode.addEventListener("change", () => { d.grading_mode = mode.value; markValidationDirty(); collectAndRender(); });

    const statement = bindInput(h("textarea", { rows: 6 }), d, "statement");
    const starter = bindInput(h("textarea", { rows: 8, class: "code-area", spellcheck: "false" }), d, "starter_code");
    const memory = bindInput(h("input", { type: "number", min: d.language === "java" ? 256 : 16, max: 2048, step: 1 }), d, "memory_limit_mb", (t) => { const n = num(t); if (!Number.isInteger(n)) throw new Error("int"); return n; });

    const heading = h("div", { class: "panel-heading" },
      h("div", {}, backButton(), isNew ? null : " ", isNew ? null : h("strong", {}, `Sửa: ${d.title || editing.id}`)),
      h("div", { class: "form-actions" }, h("button", { type: "button", class: "btn btn-ghost btn-small", on: { click: exportSpec } }, h("i", { class: "fa fa-download" }), " Xuất JSON")));

    const form = h("form", { class: "stack-form", novalidate: true, on: { submit: (e) => { e.preventDefault(); if (editing.original?.status === "published") save(); else saveDraft(); } } },
      isNew ? null : heading,
      !isNew && editing.original?.status === "published"
        ? h("div", { class: "alert alert-warning" }, "Câu hỏi đang ở trạng thái Đã xuất bản. Thay đổi chỉ được áp dụng khi đáp án mẫu mới chạy đạt; nếu không đạt, phiên bản đã xuất bản hiện tại được giữ nguyên. Các đề đã tạo giữ nguyên phiên bản cũ.")
        : null,
      h("div", { class: "two-cols" },
        field("Tiêu đề *", bindInput(h("input", { type: "text", maxlength: 200 }), d, "title")),
        field("Danh mục", bindInput(h("input", { type: "text" }), d, "category"))),
      h("div", { class: "two-cols" },
        field("Ngôn ngữ", language), field("Kiểu chấm", mode)),
      field("Đề bài", statement),
      h("div", { class: "two-cols" },
        field("Độ khó", bindInput(h("input", { type: "text" }), d, "difficulty")),
        field("Tags (cách nhau bởi dấu phẩy)", bindInput(h("input", { type: "text" }), d, "tags", splitList, listToText))),
      isReflection || d.language === "java"
        ? h("div", { class: "two-cols" },
            field(isReflection ? "Target class * (ví dụ model.Student)" : "Target class * (ví dụ Main)", bindInput(h("input", { type: "text" }), d, "target_class")),
            isReflection ? field("Target package * (ví dụ model)", bindInput(h("input", { type: "text" }), d, "target_package")) : null)
        : null,
      d.language === "python" ? field("Target file", bindInput(h("input", { type: "text", placeholder: "solution.py" }), d, "target_file")) : null,
      field("Mã khởi tạo cho sinh viên", starter),
      h("div", { class: "two-cols" },
        field("Time limit (giây, 0.1–60)", bindInput(h("input", { type: "number", min: 0.1, max: 60, step: "any" }), d, "time_limit_seconds", num)),
        field(`Memory limit (MB${d.language === "java" ? ", Java tối thiểu 256" : ""})`, memory)),
      h("div", { class: "two-cols" },
        field("Giới hạn output (bytes)", bindInput(h("input", { type: "number", min: 1024, max: 1048576, step: 1 }), d, "max_output_bytes", num)),
        field("Số lần chạy thử tối đa", bindInput(h("input", { type: "number", min: 1, max: 1000, step: 1 }), d, "max_pretest_runs", num))),
      h("label", { class: "checkbox-row" }, h("input", { type: "checkbox", checked: d.allow_pretest !== false, on: { change: (e) => { d.allow_pretest = e.target.checked; markValidationDirty(); } } }), " Cho phép chạy thử (pretest)"),
      h("h3", {}, isReflection ? "Checks" : "Tests"),
      h("div", { id: "q-items" }),
      h("div", { class: "form-actions" }, addMenu(isReflection)),
      h("p", {}, "Tổng điểm (tự cộng): ", totalNode),
      editing.original?.status === "published"
        ? h("div", {}, h("label", { for: "q-edit-sample" }, "Mã nguồn đáp án mẫu (đã lưu; chỉ cần sửa khi thay đổi đặc tả chấm)"),
            h("textarea", { id: "q-edit-sample", rows: 10, class: "code-area", spellcheck: "false", on: { input: (e) => { editing.sample = e.target.value; markValidationDirty(); } } }, editing.sample || ""))
        : h("div", {}, h("label", { for: "q-edit-sample" }, "Mã nguồn đáp án mẫu (dùng để chạy thử và xuất bản)"),
            h("textarea", { id: "q-edit-sample", rows: 10, class: "code-area", spellcheck: "false", on: { input: (e) => { editing.sample = e.target.value; markValidationDirty(); } } }, editing.sample || "")),
      h("div", { id: "q-editor-notice", class: "notice hidden" }),
      h("div", { id: "q-editor-result" }),
      h("div", { class: "form-actions" },
        editing.original?.status === "published"
          ? h("button", { type: "submit", class: "btn btn-primary" }, h("i", { class: "fa fa-save" }), " Lưu thay đổi")
          : h("button", { type: "button", class: "btn btn-primary", on: { click: saveDraft } }, h("i", { class: "fa fa-save" }), " Lưu Nháp"),
        h("button", { type: "button", class: "btn btn-secondary", on: { click: runCandidate } }, h("i", { class: "fa fa-play" }), " Chạy thử mã nguồn mẫu"),
        editing.original?.status === "published"
          ? null
          : h("button", { type: "button", class: "btn btn-success", on: { click: publishCandidate } }, h("i", { class: "fa fa-upload" }), " Xuất bản"),
        h("button", { type: "button", class: "btn btn-ghost", on: { click: discardCreation } }, isNew ? "Hủy và xóa bản nháp" : "Hủy bỏ")));
    if (!isNew) {
      editorView.replaceChildren(form);
      renderItems();
      refreshTotal();
      return;
    }
    const typeSelect = h("select", { id: "q-type-select", "aria-label": "Loại câu hỏi" }, ...QUESTION_TYPES.map(([value, label]) => h("option", { value }, label)));
    typeSelect.value = creation.type;
    const placeholder = (text) => h("div", { class: "q-type-placeholder" }, h("p", { class: "muted" }, "Chức năng đang được phát triển"), h("small", { class: "fine-print" }, text));
    const choicePane = placeholder("Câu hỏi trắc nghiệm");
    const shortPane = placeholder("Câu hỏi ngắn");
    const exportBtn = heading.querySelector(".form-actions");
    const applyType = () => {
      const type = typeSelect.value;
      creation.type = type;
      form.classList.toggle("hidden", type !== "code");
      exportBtn.classList.toggle("hidden", type !== "code");
      choicePane.classList.toggle("hidden", type !== "choice");
      shortPane.classList.toggle("hidden", type !== "short");
    };
    typeSelect.addEventListener("change", () => { applyType(); persistCreationNow(); });
    editorView.replaceChildren(heading,
      h("div", { class: "q-create-head" },
        h("h2", {}, "Tạo câu hỏi mới"),
        typeSelect,
        h("small", { id: "q-storage-note", class: `fine-print ${storageFailed ? "" : "hidden"}` }, "Không thể lưu bản nháp tạm vào trình duyệt; dữ liệu chỉ được giữ cho đến khi tải lại trang.")),
      form, choicePane, shortPane);
    applyType();
    renderItems();
    refreshTotal();
  }

  function discardCreation() {
    if (editing && !editing.id) {
      if (!window.confirm("Hủy tạo câu hỏi và xóa bản nháp đang nhập?")) return;
      clearCreation();
      editing = null;
    }
    if (editing && editing.id) {
      const id = editing.id;
      const published = editing.original?.status === "published";
      if (published && hasUnsavedChanges()) {
        if (!window.confirm("Bạn có thay đổi chưa lưu. Hủy bỏ và quay lại bản đã xuất bản hiện tại?")) return;
      }
      editing = null;
      if (published) { openDetail(id); return; }
    }
    show(listView);
    loadList();
  }

  // inputs are bound live, so a re-render after structural change keeps the draft
  function collectAndRender() { renderEditor(); }

  // Whether the current form differs from the original question (used for the Hủy bỏ confirmation).
  function hasUnsavedChanges() {
    if (!editing || !editing.original) return false;
    const original = toEditorQuestion(editing.original);
    const current = editing.draft;
    const sampleChanged = (editing.sample || "") !== (editing.original.reference_source || "");
    return sampleChanged || JSON.stringify(current) !== JSON.stringify(original);
  }

  function addMenu(isReflection) {
    if (!isReflection) {
      return h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: () => { editing.draft.tests = editing.draft.tests || []; editing.draft.tests.push({ id: uniqueId("test"), stdin: "", expected_stdout: "", points: 10, is_visible: true }); renderItems(); refreshTotal(); } } }, h("i", { class: "fa fa-plus" }), " Thêm test");
    }
    const select = h("select", {}, ...Object.entries(CHECK_KINDS).map(([k, label]) => h("option", { value: k }, label)));
    return h("span", { class: "inline-group" }, select,
      h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: () => { editing.draft.checks.push(newCheck(select.value)); renderItems(); refreshTotal(); } } }, h("i", { class: "fa fa-plus" }), " Thêm check"));
  }

  function uniqueId(prefix) {
    const used = new Set([...(editing.draft.checks || []), ...(editing.draft.tests || [])].map((c) => c.id));
    let n = used.size + 1;
    while (used.has(`${prefix}-${n}`)) n += 1;
    return `${prefix}-${n}`;
  }

  function newCheck(kind) {
    const base = { id: uniqueId(kind.toLowerCase()), kind, points: 10, is_visible: true };
    const setup = () => ({ constructor_param_types: [], constructor_args: [] });
    switch (kind) {
      case "field": return { ...base, field_name: "", expected_type: "", expected_modifiers: ["private"] };
      case "constructor": return { ...base, param_types: [], expected_modifiers: ["public"] };
      case "method": return { ...base, method_name: "", param_types: [], expected_return_type: "void", expected_modifiers: ["public"] };
      case "implements": return { ...base, expected_interface: "" };
      case "behavior": return { ...base, setup: setup(), invoke: { method: "", param_types: [], args: [] }, expect_return: null };
      case "toString": return { ...base, expected_template: "", setup: setup() };
      case "comparable": return { ...base, constructor_param_types: [], cases: [] };
      default: return base;
    }
  }

  function renderItems() {
    const host = document.getElementById("q-items");
    const d = editing.draft;
    const isReflection = d.grading_mode === "reflection";
    const items = isReflection ? d.checks : d.tests;
    if (!items.length) { host.replaceChildren(h("p", { class: "empty-cell" }, isReflection ? "Chưa có check nào." : "Chưa có test nào.")); return; }
    host.replaceChildren(...items.map((item, index) => itemCard(items, item, index, isReflection)));
  }

  function itemCard(items, item, index, isReflection) {
    const move = (delta) => { const to = index + delta; if (to < 0 || to >= items.length) return; [items[index], items[to]] = [items[to], items[index]]; renderItems(); };
    const title = isReflection ? `${CHECK_KINDS[item.kind] || item.kind}` : "Test stdio";
    return h("fieldset", { class: "check-card" },
      h("legend", {}, `#${index + 1} · ${title}`),
      h("div", { class: "check-head" },
        field("ID", bindInput(h("input", { type: "text" }), item, "id")),
        field("Điểm", bindInput(h("input", { type: "number", min: 0, step: "any" }), item, "points", num))),
      h("div", { class: "check-body" }, isReflection ? checkFields(item) : testFields(item)),
      h("div", { class: "check-footer" },
        h("label", { class: "checkbox-row" }, h("input", { type: "checkbox", checked: item.is_visible === true, on: { change: (e) => { item.is_visible = e.target.checked; } } }), " Hiển thị cho sinh viên"),
        h("span", { class: "row-actions" },
          h("button", { type: "button", class: "btn btn-ghost btn-small", title: "Lên", on: { click: () => move(-1) } }, h("i", { class: "fa fa-arrow-up" })),
          h("button", { type: "button", class: "btn btn-ghost btn-small", title: "Xuống", on: { click: () => move(1) } }, h("i", { class: "fa fa-arrow-down" })),
          h("button", { type: "button", class: "btn btn-danger btn-small", title: "Xóa", on: { click: () => { items.splice(index, 1); renderItems(); refreshTotal(); } } }, h("i", { class: "fa fa-trash" })))));
  }

  const typesInput = (obj, key) => bindInput(h("input", { type: "text", placeholder: "java.lang.String, double" }), obj, key, splitList, listToText);
  const modsInput = (obj, key) => bindInput(h("input", { type: "text", placeholder: "public static final" }), obj, key, splitWords, (v) => (Array.isArray(v) ? v.join(" ") : ""));
  const argsInput = (obj, key) => bindInput(h("input", { type: "text", placeholder: '"An", 8.5' }), obj, key, textToArgs, argsToText);
  const TYPE_HINT = "Phân cách bằng dấu phẩy; để trống nếu không có tham số.";
  const ARGS_HINT = "Giá trị theo kiểu JSON, phân cách bằng dấu phẩy: chuỗi trong dấu nháy kép.";

  function setupFields(item) {
    item.setup = item.setup || { constructor_param_types: [], constructor_args: [] };
    return h("div", { class: "two-cols" },
      field("Kiểu tham số constructor (setup)", typesInput(item.setup, "constructor_param_types"), TYPE_HINT),
      field("Giá trị tham số constructor (setup)", argsInput(item.setup, "constructor_args"), ARGS_HINT));
  }

  function checkFields(item) {
    switch (item.kind) {
      case "field":
        return h("div", { class: "two-cols" },
          field("Tên field", bindInput(h("input", { type: "text" }), item, "field_name")),
          field("Kiểu dữ liệu", bindInput(h("input", { type: "text", placeholder: "java.lang.String" }), item, "expected_type")),
          field("Modifier", modsInput(item, "expected_modifiers"), "Cách nhau bởi khoảng trắng."));
      case "constructor":
        return h("div", { class: "two-cols" },
          field("Kiểu tham số", typesInput(item, "param_types"), TYPE_HINT),
          field("Modifier", modsInput(item, "expected_modifiers"), "Cách nhau bởi khoảng trắng."));
      case "method":
        return h("div", { class: "two-cols" },
          field("Tên method", bindInput(h("input", { type: "text" }), item, "method_name")),
          field("Kiểu trả về", bindInput(h("input", { type: "text" }), item, "expected_return_type")),
          field("Kiểu tham số", typesInput(item, "param_types"), TYPE_HINT),
          field("Modifier", modsInput(item, "expected_modifiers"), "Cách nhau bởi khoảng trắng."));
      case "implements":
        return field("Interface cần triển khai", bindInput(h("input", { type: "text", placeholder: "java.lang.Comparable" }), item, "expected_interface"));
      case "behavior": return behaviorFields(item);
      case "toString":
        return h("div", {},
          field("Mẫu kết quả toString()", bindInput(h("input", { type: "text" }), item, "expected_template"), "Dùng {tenField} để chèn giá trị field."),
          setupFields(item));
      case "comparable": return comparableFields(item);
      default:
        return h("p", { class: "fine-print" }, `Loại check “${item.kind}” chưa có giao diện chỉnh sửa; dữ liệu được giữ nguyên: ${itemSummary(item)}`);
    }
  }

  function expectKind(item) {
    if ("expect_exception" in item) return "exception";
    if ("expect_state" in item) return "state";
    return "return";
  }

  function behaviorFields(item) {
    item.invoke = item.invoke || { method: "", param_types: [], args: [] };
    const host = h("div", { class: "two-cols" });
    const kindSelect = h("select", {},
      h("option", { value: "return" }, "Giá trị trả về"),
      h("option", { value: "state" }, "Trạng thái sau khi gọi (getter)"),
      h("option", { value: "exception" }, "Ném exception"));
    kindSelect.value = expectKind(item);
    function draw() {
      const kind = kindSelect.value;
      host.replaceChildren();
      if (kind === "return") {
        delete item.expect_state; delete item.expect_exception;
        if (!("expect_return" in item)) item.expect_return = null;
        host.append(field("Giá trị trả về mong đợi (JSON)", bindInput(h("input", { type: "text", placeholder: "true" }), item, "expect_return", jsonValue, (v) => JSON.stringify(v))));
      } else if (kind === "state") {
        delete item.expect_return; delete item.expect_exception;
        if (!item.expect_state || typeof item.expect_state !== "object") item.expect_state = {};
        const state = item.expect_state;
        const getterInput = h("input", { type: "text", placeholder: "getGpa" });
        getterInput.value = state.getter || "";
        getterInput.addEventListener("input", () => { state.getter = getterInput.value.trim(); });
        const valueInput = h("input", { type: "text", placeholder: "9.0" });
        valueInput.value = state.value === undefined ? "" : JSON.stringify(state.value);
        valueInput.addEventListener("input", () => {
          try { state.value = JSON.parse(valueInput.value); valueInput.removeAttribute("data-bad"); valueInput.classList.remove("invalid"); }
          catch (error) { valueInput.setAttribute("data-bad", "1"); valueInput.classList.add("invalid"); }
        });
        item.expect_state = state;
        host.append(field("Tên getter", getterInput), field("Giá trị mong đợi (JSON)", valueInput));
      } else {
        delete item.expect_return; delete item.expect_state;
        if (typeof item.expect_exception !== "string") item.expect_exception = "java.lang.IllegalArgumentException";
        host.append(field("Exception mong đợi", bindInput(h("input", { type: "text" }), item, "expect_exception")));
      }
    }
    kindSelect.addEventListener("change", () => {
      delete item.expect_return; delete item.expect_state; delete item.expect_exception;
      draw();
    });
    draw();
    return h("div", {},
      setupFields(item),
      h("div", { class: "two-cols" },
        field("Method được gọi", bindInput(h("input", { type: "text" }), item.invoke, "method")),
        field("Kiểu tham số của method", typesInput(item.invoke, "param_types"), TYPE_HINT),
        field("Giá trị tham số khi gọi", argsInput(item.invoke, "args"), ARGS_HINT),
        field("Kiểu kỳ vọng", kindSelect)),
      host);
  }

  function comparableFields(item) {
    item.cases = item.cases || [];
    const host = h("div", {});
    function draw() {
      host.replaceChildren(...item.cases.map((c, i) => {
        const sign = h("select", {}, h("option", { value: "-1" }, "a < b (-1)"), h("option", { value: "0" }, "a = b (0)"), h("option", { value: "1" }, "a > b (1)"));
        sign.value = String(c.expected_sign ?? 0);
        sign.addEventListener("change", () => { c.expected_sign = Number(sign.value); });
        return h("div", { class: "two-cols case-row" },
          h("span", { class: "case-title" }, `Case ${i + 1}`),
          h("div", { class: "case-fields" }, field("a", argsInput(c, "a")), field("b", argsInput(c, "b")), field("Kết quả so sánh", sign)),
          h("div", { class: "case-hints" }, h("small", { class: "fine-print" }, ARGS_HINT)),
          h("div", { class: "case-actions" },
            h("button", { type: "button", class: "btn btn-danger btn-xs", title: "Xóa case", on: { click: () => { item.cases.splice(i, 1); draw(); } } }, h("i", { class: "fa fa-trash" }), " Xóa"),
            h("button", { type: "button", class: "btn btn-ghost btn-xs", title: "Sao chép case", on: { click: () => { item.cases.splice(i + 1, 0, clone(c)); draw(); } } }, h("i", { class: "fa fa-clone" }), " Sao chép")));
      }));
      if (!item.cases.length) host.append(h("p", { class: "fine-print" }, "Chưa có case so sánh."));
    }
    draw();
    return h("div", {},
      field("Kiểu tham số constructor", typesInput(item, "constructor_param_types"), TYPE_HINT),
      host,
      h("button", { type: "button", class: "btn btn-secondary btn-small", on: { click: () => { item.cases.push({ a: [], b: [], expected_sign: 0 }); draw(); } } }, h("i", { class: "fa fa-plus" }), " Thêm case"));
  }

  function testFields(item) {
    return h("div", { class: "two-cols" },
      field("Stdin", bindInput(h("textarea", { rows: 3, class: "code-area" }), item, "stdin")),
      field("Stdout mong đợi", bindInput(h("textarea", { rows: 3, class: "code-area" }), item, "expected_stdout")));
  }

  // ---------- save / import / export ----------
  function buildPayload() {
    const d = clone(editing.draft);
    for (const key of SERVER_OWNED) delete d[key];
    refreshTotalOn(d);
    if (d.grading_mode === "reflection") {
      delete d.tests;
      d.problem_kind = d.problem_kind || "java_reflection";
      d.checks = d.checks.map(toJudgeCheck);
      if (!d.target_file && d.target_class) d.target_file = `${d.target_class.split(".").pop()}.java`;
    } else {
      delete d.checks;
    }
    if (!d.difficulty) delete d.difficulty;
    return d;
  }

  function refreshTotalOn(d) {
    const items = d.grading_mode === "reflection" ? d.checks : d.tests;
    d.total_points = Math.round(items.reduce((s, c) => s + (Number(c.points) || 0), 0) * 1e6) / 1e6;
  }

  function validateLocal() {
    const d = editing.draft;
    const notice = [];
    if (editorView.querySelector("[data-bad='1']")) notice.push("Có ô nhập sai định dạng (viền đỏ). Hãy sửa trước khi lưu.");
    if (!String(d.title || "").trim()) notice.push("Tiêu đề không được để trống.");
    if (d.grading_mode === "reflection") {
      if (!String(d.target_class || "").trim()) notice.push("Target class là bắt buộc.");
      if (!String(d.target_package || "").trim()) notice.push("Target package là bắt buộc.");
    } else if (d.language === "java" && !String(d.target_class || "").trim()) notice.push("Java stdio cần target class.");
    const items = d.grading_mode === "reflection" ? d.checks : d.tests;
    if (!items.length) notice.push("Cần ít nhất một check/test.");
    const ids = new Set();
    for (const item of items) {
      if (!String(item.id || "").trim()) notice.push("Mỗi check/test cần ID.");
      else if (ids.has(item.id)) notice.push(`ID bị trùng: ${item.id}`);
      ids.add(item.id);
      if (d.grading_mode !== "reflection") continue;
      if (item.kind === "field") {
        if (!String(item.field_name || "").trim() || !String(item.expected_type || "").trim()) notice.push(`Check ${item.id}: cần tên field và kiểu dữ liệu.`);
      } else if (item.kind === "constructor") {
        if (!Array.isArray(item.param_types)) notice.push(`Check ${item.id}: kiểu tham số constructor không hợp lệ.`);
      } else if (item.kind === "method") {
        if (!String(item.method_name || "").trim() || !String(item.expected_return_type || "").trim()) notice.push(`Check ${item.id}: cần tên method và kiểu trả về.`);
        if (!Array.isArray(item.param_types)) notice.push(`Check ${item.id}: kiểu tham số method không hợp lệ.`);
      } else if (item.kind === "implements") {
        if (!String(item.expected_interface || "").trim()) notice.push(`Check ${item.id}: cần tên interface.`);
      } else if (item.kind === "behavior") {
        if (!String(item.invoke?.method || "").trim()) notice.push(`Check ${item.id}: cần tên method được gọi.`);
        const hasExpectation = "expect_return" in item || "expect_state" in item || "expect_exception" in item;
        if (!hasExpectation) notice.push(`Check ${item.id}: cần một kết quả kỳ vọng.`);
        if (item.expect_state && (!String(item.expect_state.getter || item.expect_state.field || "").trim()
            || !("value" in item.expect_state))) notice.push(`Check ${item.id}: trạng thái cần getter/field và giá trị kỳ vọng.`);
      } else if (item.kind === "toString") {
        if (!String(item.expected_template || "").trim()) notice.push(`Check ${item.id}: cần mẫu toString().`);
      } else if (item.kind === "comparable" && !item.cases?.length) {
        notice.push(`Check ${item.id}: cần ít nhất một case so sánh.`);
      }
    }
    if (d.language === "java" && Number(d.memory_limit_mb) < 256) notice.push("Java cần memory tối thiểu 256 MB.");
    return notice;
  }

  async function save() {
    const notice = document.getElementById("q-editor-notice");
    const problems = validateLocal();
    if (problems.length) { setNotice(notice, problems.join(" "), true); return; }
    setNotice(notice, "Đang lưu...", false);
    try {
      const payload = buildPayload();
      const isUpdate = Boolean(editing.id);
      const published = isUpdate && editing.original?.status === "published";
      if (published) {
        // Published editing is handled separately (unchanged in this task).
        payload.sample_source = editing.sample || "";
        setNotice(notice, "Đang xác thực đáp án mẫu với thay đổi...", false);
      }
      const url = isUpdate ? `/api/admin/questions/${encodeURIComponent(editing.id)}/update` : "/api/admin/questions";
      const data = await post(url, payload);
      const resultHost = document.getElementById("q-editor-result");
      if (published && data.saved === false) {
        setNotice(notice, "Đáp án mẫu không đạt với thay đổi. Phiên bản đã xuất bản hiện tại được giữ nguyên, thay đổi chưa được lưu.", true);
        if (resultHost) resultHost.replaceChildren(renderValidation(data));
        return;
      }
      if (!isUpdate) { clearCreation(); editing = null; }
      setNotice(listNotice, published ? "Đã lưu thay đổi. Câu hỏi vẫn ở trạng thái Đã xuất bản." : isUpdate ? "Đã lưu. Câu hỏi ở trạng thái nháp, cần chạy đáp án mẫu trước khi xuất bản." : "Đã tạo câu hỏi (nháp).", false);
      openDetail(data.question.id);
    } catch (error) {
      setNotice(notice, friendly(error), true);
    }
  }

  // Save a new or Draft question and stay in the editor (Nháp lifecycle).
  async function saveDraft() {
    const notice = document.getElementById("q-editor-notice");
    const problems = validateLocal();
    if (problems.length) { setNotice(notice, problems.join(" "), true); return; }
    setNotice(notice, "Đang lưu nháp...", false);
    try {
      const payload = buildPayload();
      payload.reference_source = editing.sample || "";
      const isUpdate = Boolean(editing.id);
      const url = isUpdate ? `/api/admin/questions/${encodeURIComponent(editing.id)}/update` : "/api/admin/questions";
      const data = await post(url, payload);
      if (!isUpdate) { clearCreation(); }
      editing = { id: data.question.id, draft: toEditorQuestion(data.question), original: data.question, sample: data.question.reference_source || "" };
      setNotice(notice, "Đã lưu nháp. Câu hỏi vẫn ở trạng thái Nháp.", false);
      renderEditor();
    } catch (error) {
      setNotice(notice, friendly(error), true);
    }
  }

  // Run the reference source against the current (possibly unsaved) candidate, in memory.
  async function runCandidate() {
    const notice = document.getElementById("q-editor-notice");
    const resultHost = document.getElementById("q-editor-result");
    const problems = validateLocal();
    if (problems.length) { setNotice(notice, problems.join(" "), true); return; }
    if (!(editing.sample || "").trim()) { setNotice(notice, "Hãy nhập mã nguồn đáp án mẫu trước khi chạy thử.", true); return; }
    setNotice(notice, "Đang biên dịch và chạy đáp án mẫu...", false);
    if (resultHost) resultHost.replaceChildren(h("p", { class: "muted" }, h("i", { class: "fa fa-spinner fa-spin" }), " Đang chạy..."));
    try {
      const payload = buildPayload();
      payload.sample_source = editing.sample;
      const result = await post("/api/admin/questions/validate-candidate", payload);
      editing.lastValidation = { spec_hash: result.spec_hash, sample_sha256: result.sample_sha256, passed: result.validation?.passed === true };
      editing.validationDirty = false;
      if (resultHost) resultHost.replaceChildren(renderValidation(result));
      setNotice(notice, result.validation?.passed ? "Đáp án mẫu đạt toàn bộ." : "Đáp án mẫu chưa đạt. Bạn có thể sửa và chạy lại.", result.validation?.passed ? false : true);
    } catch (error) {
      const body = error.body && typeof error.body === "object" ? error.body : {};
      const lines = [friendly(error)];
      if (error.error_category || body.error_category) lines.push(`Loại lỗi: ${error.error_category || body.error_category}`);
      if (error.status === 503) lines.unshift("Hệ thống chấm gặp lỗi hạ tầng (không phải lỗi câu hỏi). Kết quả này KHÔNG được ghi nhận.");
      if (resultHost) resultHost.replaceChildren(h("div", { class: "alert alert-warning" }, ...lines.map((l) => h("div", {}, l))));
      setNotice(notice, "Chạy thử thất bại.", true);
    }
  }

  // Mark the last displayed validation result as outdated when the candidate or source changes.
  function markValidationDirty() {
    if (!editing || !editing.lastValidation) return;
    editing.validationDirty = true;
    const resultHost = document.getElementById("q-editor-result");
    if (resultHost && resultHost.firstChild) {
      const existing = resultHost.firstChild;
      if (!existing.querySelector?.(".validation-outdated")) {
        existing.prepend(h("div", { class: "alert alert-warning validation-outdated" }, "Đã có thay đổi sau lần chạy gần nhất: kết quả xác thực không còn khớp. Hãy chạy lại đáp án mẫu."));
      }
    }
  }

  // Publish: always revalidate server-side with the exact current candidate + reference source.
  async function publishCandidate() {
    const notice = document.getElementById("q-editor-notice");
    const resultHost = document.getElementById("q-editor-result");
    const problems = validateLocal();
    if (problems.length) { setNotice(notice, problems.join(" "), true); return; }
    if (!(editing.sample || "").trim()) { setNotice(notice, "Hãy nhập mã nguồn đáp án mẫu trước khi xuất bản.", true); return; }
    if (!window.confirm(`Xuất bản câu hỏi “${editing.draft.title || "chưa có tiêu đề"}”? Hệ thống sẽ chạy lại đáp án mẫu để xác thực.`)) return;
    setNotice(notice, "Đang xác thực và xuất bản...", false);
    if (resultHost) resultHost.replaceChildren(h("p", { class: "muted" }, h("i", { class: "fa fa-spinner fa-spin" }), " Đang chạy..."));
    try {
      const payload = buildPayload();
      if (editing.id) payload.id = editing.id;
      payload.sample_source = editing.sample;
      const data = await post("/api/admin/questions/publish-candidate", payload);
      if (data.published) {
        setNotice(listNotice, "Đã xuất bản câu hỏi.", false);
        openDetail(data.question.id);
      } else {
        // Validation failed or infra error: candidate retained as Nháp.
        editing = { id: data.question.id, draft: toEditorQuestion(data.question), original: data.question, sample: data.question.reference_source || "" };
        const infra = data.error_category && ["INVALID_REQUEST", "JDK_NOT_FOUND", "JUDGE_INFRA_ERROR", "PROTOCOL_ERROR"].includes(data.error_category);
        setNotice(notice, infra ? "Hệ thống chấm gặp lỗi hạ tầng. Câu hỏi được giữ ở trạng thái Nháp, chưa xuất bản." : "Đáp án mẫu chưa đạt. Câu hỏi được giữ ở trạng thái Nháp, chưa xuất bản. Hãy sửa và thử lại.", true);
        renderEditor();
        const freshResult = document.getElementById("q-editor-result");
        if (freshResult) freshResult.replaceChildren(renderValidation(data));
      }
    } catch (error) {
      const body = error.body && typeof error.body === "object" ? error.body : {};
      const lines = [friendly(error)];
      if (error.error_category || body.error_category) lines.push(`Loại lỗi: ${error.error_category || body.error_category}`);
      if (error.status === 503) lines.unshift("Hệ thống chấm gặp lỗi hạ tầng (không phải lỗi câu hỏi). Câu hỏi chưa được xuất bản.");
      // If the backend persisted the candidate as Nháp, adopt its ID so a retry updates the
      // existing Draft instead of creating a duplicate. Keep the current form data and source.
      const savedQuestion = body.question;
      if (savedQuestion && savedQuestion.id) {
        editing.id = savedQuestion.id;
        editing.original = savedQuestion;
        renderEditor();
        const freshResult = document.getElementById("q-editor-result");
        if (freshResult) freshResult.replaceChildren(renderValidation(body));
      } else if (resultHost) {
        resultHost.replaceChildren(h("div", { class: "alert alert-warning" }, ...lines.map((l) => h("div", {}, l))));
      }
      setNotice(notice, "Xuất bản thất bại. Câu hỏi chưa được xuất bản.", true);
    }
  }

  function exportSpec() {
    const payload = buildPayload();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = h("a", { href: URL.createObjectURL(blob), download: `${editing.id || "question"}.json` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function importSpec(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(String(reader.result));
        if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("File JSON phải là một object câu hỏi.");
        for (const key of SERVER_OWNED) delete data[key];
        data.checks = Array.isArray(data.checks) ? data.checks : [];
        data.tests = Array.isArray(data.tests) ? data.tests : [];
        data.tags = Array.isArray(data.tags) ? data.tags : [];
        if (creation && !window.confirm("Nhập JSON sẽ thay thế bản nháp câu hỏi đang nhập. Tiếp tục?")) return;
        openEditor(null, toEditorQuestion({ ...newDraft(), ...data }));
      } catch (error) {
        setNotice(listNotice, `Không nhập được: ${error.message}`, true);
      }
    };
    reader.onerror = () => setNotice(listNotice, "Không đọc được file.", true);
    reader.readAsText(file);
  }

  document.getElementById("q-new").addEventListener("click", () => openEditor(null));
  document.getElementById("q-import").addEventListener("click", () => document.getElementById("q-import-file").click());
  document.getElementById("q-import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) importSpec(file);
  });
  for (const id of ["q-filter-search", "q-filter-language", "q-filter-mode",   "q-filter-status", "q-filter-category", "q-filter-usage"]) {
    document.getElementById(id).addEventListener("input", renderList);
  }
    document.getElementById("q-filter-usage-clear").addEventListener("click", () => {
      document.getElementById("q-filter-usage").value = "";
      renderList();
    });

  const storedCreation = loadStoredCreation();
  if (storedCreation) creation = storedCreation;
  loadList();
  const linkedQuestion = new URLSearchParams(location.search).get("question");
  if (linkedQuestion) {
    request(`/api/admin/questions/${encodeURIComponent(linkedQuestion)}`)
      .then((data) => (data.question.status === "draft" ? openEditor(linkedQuestion) : openDetail(linkedQuestion)))
      .catch((error) => { listHost.prepend(errorBox(error, () => location.reload())); });
  } else if (creation && creation.open) openEditor(null);
})();
