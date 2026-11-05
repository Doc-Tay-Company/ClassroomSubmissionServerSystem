(() => {
  "use strict";

  const listRoot = document.getElementById("exams-root");
  const detailRoot = document.getElementById("exam-root");
  if (!listRoot && !detailRoot) return;

  const { h, errorBox, errorText, setNotice } = window.cssUi;
  const request = window.cssRequest;
  const API = "/api/admin/exam-records";
  const STATUS = {
    draft: ["Nháp", "status-gray"],
    distributed: ["Đã phát đề", "status-amber"],
    started: ["Đang diễn ra", "status-green"],
    ended: ["Đã kết thúc", "status-gray"],
  };
  const TAGS = { "": "Không nhãn", midterm: "Giữa kỳ", final: "Cuối kỳ" };

  const post = (path, body) => request(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const toast = (message, isError) => {
    if (isError && window.cssToast) window.cssToast(message, "error");
    else if (window.cssToast) window.cssToast(message);
  };
  const pill = (status) => {
    const [label, cls] = STATUS[status] || [status, "status-gray"];
    return h("span", { class: `status-pill ${cls}` }, label);
  };
  const tagPill = (tag) => (tag ? h("span", { class: "section-badge" }, TAGS[tag]) : null);
  const examUrl = (id, edit) => `/admin?section=exam${id ? `&id=${encodeURIComponent(id)}` : ""}${edit ? "&mode=edit" : ""}`;

  function formatRemaining(seconds) {
    const minutes = Math.max(1, Math.ceil(seconds / 60));
    const hours = Math.floor(minutes / 60);
    return hours ? `${hours} giờ ${minutes % 60} phút` : `${minutes} phút`;
  }

  function confirmDialog(message, okLabel, danger) {
    return new Promise((resolve) => {
      const close = (value) => { overlay.remove(); resolve(value); };
      const overlay = h("div", { class: "modal-overlay", role: "dialog", "aria-modal": "true" },
        h("div", { class: "modal-box" },
          h("p", {}, message),
          h("div", { class: "form-actions" },
            h("button", { type: "button", class: "btn btn-ghost", on: { click: () => close(false) } }, "Hủy"),
            h("button", { type: "button", class: `btn ${danger ? "btn-danger" : "btn-primary"}`, on: { click: () => close(true) } }, okLabel || "Xác nhận"))));
      document.body.append(overlay);
      overlay.querySelector(".btn-ghost").focus();
    });
  }

  // Lifecycle actions shared by the list cards and the detail page.
  const ACTIONS = {
    revoke: { label: "Thu hồi", icon: "fa-undo", confirm: () => "Thu hồi kỳ thi về trạng thái Nháp? Sinh viên sẽ không còn thấy kỳ thi này.", ok: "Thu hồi", done: "Đã thu hồi kỳ thi." },
    start: { label: "Bắt đầu kỳ thi", icon: "fa-play", cls: "btn-primary", confirm: () => "Bắt đầu kỳ thi ngay bây giờ?", ok: "Bắt đầu", done: "Kỳ thi đã bắt đầu." },
    end: {
      label: "Kết thúc kỳ thi", icon: "fa-stop", cls: "btn-danger", danger: true, ok: "Dừng kỳ thi", done: "Kỳ thi đã kết thúc.",
      confirm: (exam) => `Kỳ thi còn ${formatRemaining(exam.remaining_seconds ?? exam.config.duration_minutes * 60)}, bạn có muốn dừng kỳ thi lại không?`,
    },
    delete: {
      label: "Xóa", icon: "fa-trash", cls: "btn-danger", danger: true, ok: "Xóa", done: "Đã xóa kỳ thi.",
      confirm: (exam) => (exam.status === "ended"
        ? "Xóa kỳ thi này khỏi danh sách? Bài nộp và điểm chấm đã có vẫn được giữ lại trên server."
        : "Xóa kỳ thi này? Thao tác không thể hoàn tác."),
    },
    copy: { label: "Sao chép", icon: "fa-copy", confirm: null, done: "Đã tạo bản sao ở trạng thái Nháp." },
  };

  async function runAction(name, exam) {
    const spec = ACTIONS[name];
    if (spec.confirm && !(await confirmDialog(spec.confirm(exam), spec.ok, spec.danger))) return null;
    try {
      const data = await post(`/${encodeURIComponent(exam.id)}/${name}`);
      toast(spec.done);
      return data;
    } catch (error) {
      toast(errorText(error), true);
      return null;
    }
  }

  const actionButton = (name, exam, onDone, disabled) => {
    const spec = ACTIONS[name];
    return h("button", {
      type: "button",
      class: `btn btn-small ${spec.cls || "btn-secondary"}`,
      disabled: disabled || false,
      on: { click: async (event) => { event.stopPropagation(); const data = await runAction(name, exam); if (data) onDone(data, name); } },
    }, h("i", { class: `fa ${spec.icon}` }), ` ${spec.label}`);
  };

  const link = (href, icon, label, cls) => h("a", { class: `btn btn-small ${cls || "btn-secondary"}`, href }, h("i", { class: `fa ${icon}` }), ` ${label}`);

  // ------------------------------------------------------------------ list page
  function initList() {
    const filters = { q: "", tag: "", status: "" };
    let exams = [];
    const grid = h("div", { class: "exam-card-grid" });
    const status = h("div", { class: "notice hidden" });

    const search = h("input", { type: "search", placeholder: "Tìm theo tên kỳ thi...", "aria-label": "Tìm kỳ thi", on: { input: (e) => { filters.q = e.target.value; render(); } } });
    const tagSelect = h("select", { "aria-label": "Lọc theo nhãn", on: { change: (e) => { filters.tag = e.target.value; render(); } } },
      h("option", { value: "" }, "Tất cả nhãn"), h("option", { value: "midterm" }, "Giữa kỳ"), h("option", { value: "final" }, "Cuối kỳ"));
    const statusSelect = h("select", { "aria-label": "Lọc theo trạng thái", on: { change: (e) => { filters.status = e.target.value; render(); } } },
      h("option", { value: "" }, "Tất cả trạng thái"), ...Object.entries(STATUS).map(([value, [label]]) => h("option", { value }, label)));

    listRoot.append(
      h("div", { class: "panel-heading" },
        h("div", {}, h("h2", {}, h("i", { class: "fa fa-calendar" }), " Danh sách kỳ thi"),
          h("p", { class: "muted" }, "Tạo kỳ thi, phát đề, bắt đầu và kết thúc kỳ thi. Chỉ một kỳ thi được diễn ra tại một thời điểm.")),
        link(examUrl(), "fa-plus", "Tạo kỳ thi mới", "btn-primary")),
      h("div", { class: "exam-filters" }, search, tagSelect, statusSelect),
      status, grid);

    function card(exam) {
      const running = exams.some((item) => item.status === "started");
      const code = exam.items.find((item) => item.type === "code");
      const zip = exam.items.find((item) => item.type === "zip");
      const parts = [];
      if (code) parts.push(`${code.question_ids.length} câu code`);
      if (zip) parts.push("Nộp file");
      const refresh = () => load();
      const buttons = [];
      if (exam.status === "draft") buttons.push(actionButton("copy", exam, refresh), actionButton("delete", exam, refresh));
      if (exam.status === "distributed") {
        buttons.push(link(examUrl(exam.id, true), "fa-pencil", "Chỉnh sửa"), actionButton("copy", exam, refresh), actionButton("revoke", exam, refresh),
          actionButton("start", exam, refresh, running), actionButton("delete", exam, refresh));
      }
      if (exam.status === "started") buttons.push(link("/admin?section=monitor", "fa-eye", "Giám sát"), actionButton("end", exam, refresh));
      if (exam.status === "ended") buttons.push(actionButton("copy", exam, refresh), actionButton("delete", exam, refresh));
      const article = h("article", { class: `exam-card exam-card-${exam.status}`, on: { click: (event) => { if (!event.target.closest("a, button")) location.href = examUrl(exam.id); } } },
        h("div", { class: "exam-card-main" },
          h("div", { class: "exam-card-head" },
            h("a", { class: "exam-card-title", href: examUrl(exam.id) }, exam.title),
            h("div", { class: "exam-card-meta" }, pill(exam.status), tagPill(exam.tag))),
          h("p", { class: "muted" }, `${exam.config.duration_minutes} phút · ${exam.config.participants.length || "Tất cả"} sinh viên · ${parts.join(" + ") || "Chưa có bài"}`)),
        h("div", { class: "exam-card-actions" }, buttons));
      return article;
    }

    function render() {
      const q = filters.q.trim().toLowerCase();
      const rows = exams.filter((exam) => (!q || exam.title.toLowerCase().includes(q)) && (!filters.tag || exam.tag === filters.tag) && (!filters.status || exam.status === filters.status));
      grid.replaceChildren(...(rows.length ? rows.map(card) : [h("p", { class: "muted" }, exams.length ? "Không có kỳ thi nào khớp bộ lọc." : "Chưa có kỳ thi nào. Hãy bấm “Tạo kỳ thi mới”.")]));
    }

    async function load() {
      try {
        exams = (await request(API)).exams;
        setNotice(status, "");
        render();
      } catch (error) {
        grid.replaceChildren(errorBox(error, load));
      }
    }
    load();
  }

  // ---------------------------------------------------------------- detail page
  function initDetail() {
    const params = new URLSearchParams(location.search);
    let exam = null;
    let examId = detailRoot.dataset.examId || "";
    let editing = false;
    let ref = { accounts: [], files: [], questions: [] };
    let form = null;
    let saveTimer = null;
    let saving = false;
    let dirty = false;
    let showErrors = false;
    const blank = () => ({
      title: "", tag: "", duration: 90, policy: "configurable", maxSub: 1, overwrite: true, ext: ".zip", pwEnabled: false, pw: "", hasPw: false,
      participants: new Set(), code: null, zip: null, accountQuery: "", questionQuery: "",
    });

    function fromExam(source) {
      const f = blank();
      const c = source.config;
      Object.assign(f, {
        title: source.title, tag: source.tag || "", duration: c.duration_minutes, policy: c.submission_policy, maxSub: c.max_submissions,
        overwrite: c.overwrite_previous, ext: c.accepted_submission_extensions.join(" "), pwEnabled: c.password_enabled, hasPw: c.has_password,
        participants: new Set(c.participants),
      });
      for (const item of source.items) {
        if (item.type === "code") {
          f.code = { item_id: item.item_id, ids: new Set(item.question_ids), final: item.show_final_score_immediately, pretest: item.allow_pretest, maxRuns: item.max_pretest_runs, cooldown: item.pretest_cooldown_seconds };
        } else {
          const cfg = item.distribution_config || {};
          const modulus = (cfg.exam_files || []).length;
          const map = {};
          for (const [digit, file] of Object.entries(cfg.last_digit_map || {})) if (modulus) map[Number(digit) % modulus] = file;
          f.zip = { item_id: item.item_id, mode: item.distribution_mode, files: new Set(cfg.exam_files || []), even: cfg.even_exam || "", odd: cfg.odd_exam || "", map };
        }
      }
      return f;
    }

    const clampPretest = (value) => {
      const n = Number(value);
      return Number.isFinite(n) ? Math.min(20, Math.max(1, n)) : 1;
    };

    function toPayload() {
      const items = [];
      if (form.code) {
        items.push({
          item_id: form.code.item_id, type: "code", question_ids: [...form.code.ids], show_final_score_immediately: form.code.final,
          allow_pretest: form.code.pretest, max_pretest_runs: Math.round(clampPretest(form.code.maxRuns)), pretest_cooldown_seconds: clampPretest(form.code.cooldown),
        });
      }
      if (form.zip) {
        const files = [...form.zip.files];
        let distribution = { exam_files: files };
        if (form.zip.mode === "parity") distribution = { even_exam: form.zip.even, odd_exam: form.zip.odd };
        if (form.zip.mode === "custom") {
          const map = {};
          for (let digit = 0; digit < 10; digit += 1) map[String(digit)] = form.zip.map[digit % Math.max(files.length, 1)] || "";
          distribution = { exam_files: files, custom_modulus: files.length, last_digit_map: map };
        }
        items.push({ item_id: form.zip.item_id, type: "zip", distribution_mode: form.zip.mode, distribution_config: distribution });
      }
      const config = {
        duration_minutes: Number(form.duration), submission_policy: form.policy, max_submissions: Number(form.maxSub), overwrite_previous: form.overwrite,
        accepted_submission_extensions: form.ext, password_enabled: form.pwEnabled, participants: [...form.participants],
      };
      if (form.pw) config.password = form.pw;
      return { title: form.title, tag: form.tag, config, items };
    }

    const notice = h("div", { class: "notice hidden", role: "status" });
    const autosave = h("span", { class: "muted fine-print" });
    const body = h("div", {});
    detailRoot.append(body);

    const mode = () => {
      if (!exam) return "edit";
      if (exam.status === "draft") return "edit";
      if (exam.status === "distributed" && editing) return "edit";
      return "view";
    };

    async function persist(quiet) {
      if (saving) return exam;
      saving = true;
      clearTimeout(saveTimer);
      try {
        const data = exam ? await post(`/${encodeURIComponent(examId)}/update`, toPayload()) : await post("", toPayload());
        exam = data.exam;
        examId = exam.id;
        form.pw = "";
        form.hasPw = exam.config.has_password;
        dirty = false;
        if (!params.get("id")) history.replaceState(null, "", examUrl(examId));
        if (quiet) autosave.textContent = `Đã lưu nháp lúc ${new Date().toLocaleTimeString("vi-VN")}`;
        return exam;
      } finally {
        saving = false;
      }
    }

    const mark = (key, el) => { el.dataset.field = key; return el; };

    function scheduleAutosave() {
      dirty = true;
      if (showErrors) applyErrors(publishProblems());
      if (!exam || exam.status !== "draft") return;
      clearTimeout(saveTimer);
      autosave.textContent = "Đang chờ lưu…";
      saveTimer = setTimeout(async () => {
        try { await persist(true); } catch (error) { autosave.textContent = `Không thể tự lưu: ${errorText(error)}`; }
      }, 1500);
    }

    // Mirrors the backend publish rules; keys match the `fields` returned by the API.
    function publishProblems() {
      const problems = [];
      const inRange = (value, min, max) => Number.isInteger(Number(value)) && String(value).trim() !== "" && Number(value) >= min && Number(value) <= max;
      if (!form.title.trim()) problems.push(["title", "tên kỳ thi"]);
      if (!inRange(form.duration, 1, 1440)) problems.push(["duration", "thời lượng (1–1440 phút)"]);
      if (!inRange(form.maxSub, 1, 20)) problems.push(["maxSub", "số lần nộp tối đa (1–20)"]);
      if (!form.ext.replace(/[,\s]/g, "")) problems.push(["ext", "loại file được chấp nhận"]);
      if (form.pwEnabled && !form.pw && !form.hasPw) problems.push(["password", "mật khẩu đề thi (đang bật yêu cầu mật khẩu)"]);
      if (!form.participants.size) problems.push(["participants", "danh sách sinh viên dự thi"]);
      if (!form.code && !form.zip) problems.push(["items", "bài code hoặc bài nộp file (cần ít nhất một)"]);
      else if (form.code && !form.code.ids.size) problems.push(["code", "câu hỏi cho bài code"]);
      return problems;
    }

    function applyErrors(problems) {
      body.querySelectorAll(".field-invalid").forEach((el) => el.classList.remove("field-invalid"));
      problems.forEach(([key]) => body.querySelectorAll(`[data-field="${key}"]`).forEach((el) => el.classList.add("field-invalid")));
    }

    function showProblems(problems) {
      showErrors = true;
      applyErrors(problems);
      toast(`Chưa thể phát đề. Còn thiếu: ${problems.map(([, label]) => label).join("; ")}.`, true);
      const first = body.querySelector(".field-invalid");
      if (first) {
        first.scrollIntoView({ behavior: "smooth", block: "center" });
        if (/^(INPUT|SELECT|TEXTAREA)$/.test(first.tagName)) first.focus({ preventScroll: true });
      }
    }

    const field = (label, control, hint) => h("div", {}, h("label", {}, label), control, hint ? h("p", { class: "fine-print" }, hint) : null);
    const rowField = (label, control) => h("div", { class: "exam-row" }, h("label", {}, label), control);
    const stackField = (label, control) => h("div", { class: "exam-row exam-row-stack" }, h("label", {}, label), control);
    const bind = (key, type) => (event) => {
      const t = event.target;
      form[key] = type === "bool" ? t.checked : type === "yesno" ? t.value === "true" : t.value;
      scheduleAutosave();
    };

    function configSection() {
      return h("section", { class: "exam-form-section" },
        h("h3", {}, h("i", { class: "fa fa-sliders" }), " Thông tin và cấu hình"),
        h("div", { class: "exam-row exam-row-title" }, h("label", {}, "Tên kỳ thi"), mark("title", h("input", { value: form.title, maxlength: 200, placeholder: "Ví dụ: Thi giữa kỳ JSD", on: { input: bind("title") } }))),
        h("div", { class: "exam-grid" },
          stackField("Nhãn", h("select", { value: form.tag, on: { change: bind("tag") } },
            ...Object.entries(TAGS).map(([value, label]) => h("option", { value, selected: form.tag === value }, label)))),
          stackField("Thời lượng (phút)", mark("duration", h("input", { type: "number", min: 1, max: 1440, value: form.duration, on: { input: bind("duration") } }))),
          stackField("Chính sách nộp bài", h("select", { on: { change: bind("policy") } },
            h("option", { value: "once", selected: form.policy === "once" }, "Một lần duy nhất"),
            h("option", { value: "configurable", selected: form.policy === "configurable" }, "Theo số lần Admin cấu hình"))),
          stackField("Số lần nộp tối đa", mark("maxSub", h("input", { type: "number", min: 1, max: 20, value: form.maxSub, on: { input: bind("maxSub") } }))),
          stackField("Khi nộp lại", h("select", { on: { change: bind("overwrite", "yesno") } },
            h("option", { value: "true", selected: form.overwrite }, "Ghi đè file trước"),
            h("option", { value: "false", selected: !form.overwrite }, "Giữ các file trước"))),
          stackField("Loại file được chấp nhận", mark("ext", h("input", { value: form.ext, placeholder: ".zip .pdf .docx", on: { input: bind("ext") } })))),
        h("label", { class: "checkbox-row" }, h("input", { type: "checkbox", checked: form.pwEnabled, on: { change: (e) => { form.pwEnabled = e.target.checked; scheduleAutosave(); render(); } } }), " Yêu cầu mật khẩu đề thi"),
        form.pwEnabled
          ? stackField("Mật khẩu đề thi", mark("password", h("input", { type: "password", autocomplete: "new-password", value: form.pw, placeholder: form.hasPw ? "Đã có mật khẩu — chỉ nhập khi muốn đổi" : "Nhập mật khẩu", on: { input: bind("pw") } })))
          : null);
    }

    function participantsSection() {
      const count = h("span", { class: "section-badge" });
      const list = h("div", { class: "participant-list" });
      const paste = h("textarea", { rows: 6, class: "paste-input", placeholder: "Nhập mỗi dòng một MSSV hoặc phân cách bằng dấu phẩy" });
      paste.addEventListener("input", () => { paste.style.height = "auto"; paste.style.height = `${paste.scrollHeight + 2}px`; });
      const refreshList = () => {
        const query = form.accountQuery.trim().toLowerCase();
        const known = new Set(ref.accounts.map((row) => row.student_id));
        const rows = [...ref.accounts, ...[...form.participants].filter((sid) => !known.has(sid)).map((sid) => ({ student_id: sid, full_name: "(chưa có tài khoản — sẽ tự tạo khi phát đề)" }))]
          .filter((row) => !query || `${row.student_id} ${row.full_name || ""}`.toLowerCase().includes(query));
        list.replaceChildren(...(rows.length ? rows.map((row) => h("label", { class: "student-option" },
          h("input", { type: "checkbox", checked: form.participants.has(row.student_id), on: { change: (e) => { e.target.checked ? form.participants.add(row.student_id) : form.participants.delete(row.student_id); refreshCount(); scheduleAutosave(); } } }),
          h("span", {}, h("strong", {}, row.student_id), h("small", {}, row.full_name || "")))) : [h("span", { class: "muted" }, "Không tìm thấy sinh viên.")]));
        refreshCount();
      };
      const refreshCount = () => { count.textContent = `${form.participants.size} sinh viên`; };
      const setVisible = (value) => {
        const query = form.accountQuery.trim().toLowerCase();
        list.querySelectorAll(".student-option").forEach((row) => {
          if (!query || row.textContent.toLowerCase().includes(query)) row.querySelector("input").checked = value;
        });
        list.querySelectorAll("input").forEach((input) => {
          const sid = input.closest("label").querySelector("strong").textContent;
          if (input.checked) form.participants.add(sid); else if (!value) form.participants.delete(sid);
        });
        refreshCount();
        scheduleAutosave();
      };
      refreshList();
      return h("section", { class: "exam-form-section" },
        h("h3", {}, h("i", { class: "fa fa-user-check" }), " Đối tượng được vào thi ", count),
        h("p", { class: "muted" }, "Cần chọn ít nhất một sinh viên để phát đề. MSSV chưa có tài khoản sẽ được tạo tự động (mật khẩu ban đầu là MSSV) khi phát đề."),
        mark("participants", h("div", { class: "participant-block" },
          h("div", {},
            h("input", { type: "search", value: form.accountQuery, placeholder: "Tìm MSSV hoặc họ tên...", on: { input: (e) => { form.accountQuery = e.target.value; refreshList(); } } }),
            list,
            h("div", { class: "form-actions" },
              h("button", { type: "button", class: "btn btn-ghost btn-small", on: { click: () => setVisible(true) } }, "Chọn tất cả kết quả"),
              h("button", { type: "button", class: "btn btn-ghost btn-small", on: { click: () => setVisible(false) } }, "Bỏ chọn kết quả"))),
          h("div", { class: "paste-block" }, paste,
            h("button", {
              type: "button", class: "btn btn-secondary btn-small",
              on: { click: () => {
                const ids = paste.value.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
                ids.forEach((sid) => form.participants.add(sid));
                paste.value = "";
                paste.style.height = "";
                refreshList();
                scheduleAutosave();
              } },
            }, "Thêm vào danh sách")))));
    }

    function codeSection() {
      const toggle = h("label", { class: "checkbox-row" }, h("input", {
        type: "checkbox", checked: Boolean(form.code),
        on: { change: (e) => { form.code = e.target.checked ? { item_id: undefined, ids: new Set(), final: false, pretest: true, maxRuns: 20, cooldown: 2 } : null; scheduleAutosave(); render(); } },
      }), " Có bài code (chấm tự động)");
      if (!form.code) return mark("items", h("section", { class: "exam-form-section" }, h("h3", {}, h("i", { class: "fa fa-code" }), " Bài code"), toggle));
      const code = form.code;
      const published = ref.questions.filter((question) => question.status === "published");
      const list = h("div", { class: "participant-list" });
      const count = h("span", { class: "section-badge" });
      const refreshList = () => {
        const query = form.questionQuery.trim().toLowerCase();
        const rows = published.filter((question) => !query || `${question.title} ${question.id}`.toLowerCase().includes(query));
        list.replaceChildren(...(rows.length ? rows.map((question) => h("label", { class: "student-option" },
          h("input", { type: "checkbox", checked: code.ids.has(question.id), on: { change: (e) => { e.target.checked ? code.ids.add(question.id) : code.ids.delete(question.id); count.textContent = `${code.ids.size} câu`; scheduleAutosave(); } } }),
          h("span", {}, h("strong", {}, question.title), h("small", {}, question.language ? String(question.language) : "")))) : [h("span", { class: "muted" }, published.length ? "Không có câu hỏi khớp." : "Chưa có câu hỏi đã xuất bản trong Ngân hàng câu hỏi.")]));
        count.textContent = `${code.ids.size} câu`;
      };
      refreshList();
      const clampInput = (input, assign, integer) => {
        const raw = input.value.trim();
        if (raw === "" || Number.isNaN(Number(raw))) return;
        let value = Number(raw);
        if (integer) value = Math.round(value);
        const fixed = clampPretest(value);
        if (fixed !== Number(raw)) input.value = String(fixed);
        assign(fixed);
        scheduleAutosave();
      };
      const settle = (input, assign, integer) => {
        if (input.value.trim() === "") input.value = "1";
        clampInput(input, assign, integer);
      };
      const runsInput = h("input", { type: "number", min: 1, max: 20, step: 1, value: clampPretest(code.maxRuns), disabled: !code.pretest });
      const cooldownInput = h("input", { type: "number", min: 1, max: 20, step: "0.5", value: clampPretest(code.cooldown), disabled: !code.pretest });
      code.maxRuns = runsInput.value;
      code.cooldown = cooldownInput.value;
      const setRuns = (value) => { code.maxRuns = value; };
      const setCooldown = (value) => { code.cooldown = value; };
      runsInput.addEventListener("input", () => clampInput(runsInput, setRuns, true));
      runsInput.addEventListener("change", () => settle(runsInput, setRuns, true));
      cooldownInput.addEventListener("input", () => clampInput(cooldownInput, setCooldown, false));
      cooldownInput.addEventListener("change", () => settle(cooldownInput, setCooldown, false));
      return h("section", { class: "exam-form-section" },
        h("h3", {}, h("i", { class: "fa fa-code" }), " Bài code ", count), toggle,
        h("input", { type: "search", value: form.questionQuery, placeholder: "Tìm câu hỏi đã xuất bản...", on: { input: (e) => { form.questionQuery = e.target.value; refreshList(); } } }),
        mark("code", list),
        h("div", { class: "exam-rows" },
          h("label", { class: "checkbox-row" }, h("input", { type: "checkbox", checked: code.pretest, on: { change: (e) => { code.pretest = e.target.checked; runsInput.disabled = cooldownInput.disabled = !code.pretest; scheduleAutosave(); } } }), " Cho phép chạy thử (pretest)"),
          h("label", { class: "checkbox-row" }, h("input", { type: "checkbox", checked: code.final, on: { change: (e) => { code.final = e.target.checked; scheduleAutosave(); } } }), " Hiện điểm cuối cho sinh viên ngay sau khi nộp"),
          rowField("Số lần chạy thử tối đa", runsInput),
          rowField("Thời gian chờ giữa các lần chạy thử (giây)", cooldownInput)));
    }

    function zipSection() {
      const toggle = h("label", { class: "checkbox-row" }, h("input", {
        type: "checkbox", checked: Boolean(form.zip),
        on: { change: (e) => { form.zip = e.target.checked ? { item_id: undefined, mode: "random", files: new Set(), even: "", odd: "", map: {} } : null; scheduleAutosave(); render(); } },
      }), " Có bài nộp file (đề ZIP/PDF)");
      const heading = h("h3", {}, h("i", { class: "fa fa-file-archive-o" }), " Bài nộp file");
      if (!form.zip) return mark("items", h("section", { class: "exam-form-section" }, heading, toggle));
      const zip = form.zip;
      const names = ref.files.map((file) => file.name);
      const fileOptions = (selected, onChange) => h("select", { on: { change: onChange } }, h("option", { value: "" }, "— Chọn đề —"), ...names.map((name) => h("option", { value: name, selected: name === selected }, name)));
      const extra = [];
      if (zip.mode === "parity") {
        extra.push(h("div", { class: "two-cols" },
          field("Đề cho MSSV chẵn", fileOptions(zip.even, (e) => { zip.even = e.target.value; scheduleAutosave(); })),
          field("Đề cho MSSV lẻ", fileOptions(zip.odd, (e) => { zip.odd = e.target.value; scheduleAutosave(); }))));
      } else {
        extra.push(h("fieldset", {}, h("legend", {}, "Đề dùng để phân phối"),
          names.length ? h("div", { class: "two-cols" }, names.map((name) => h("label", { class: "checkbox-row" }, h("input", {
            type: "checkbox", checked: zip.files.has(name),
            on: { change: (e) => { e.target.checked ? zip.files.add(name) : zip.files.delete(name); scheduleAutosave(); if (zip.mode === "custom") render(); } },
          }), ` ${name}`))) : h("div", { class: "alert alert-warning" }, "Chưa có file đề hợp lệ trong thư mục de-thi/.")));
      }
      if (zip.mode === "custom") {
        const selected = [...zip.files];
        extra.push(h("fieldset", {}, h("legend", {}, `Chữ số cuối MSSV chia ${selected.length || 0} dư…`),
          selected.length < 2 ? h("p", { class: "fine-print" }, "Chọn từ 2 đến 10 đề để gán theo số dư.") : null,
          ...(selected.length >= 2 ? selected.map((_, remainder) => h("label", { class: "remainder-row" }, h("span", {}, `Dư ${remainder}`),
            h("select", { on: { change: (e) => { zip.map[remainder] = e.target.value; scheduleAutosave(); } } },
              h("option", { value: "" }, "— Chọn đề —"), ...selected.map((name) => h("option", { value: name, selected: zip.map[remainder] === name }, name))))) : [])));
      }
      return mark("items", h("section", { class: "exam-form-section" }, heading, toggle,
        rowField("Chế độ phân phối", h("select", { class: "exam-select-wide", on: { change: (e) => { zip.mode = e.target.value; scheduleAutosave(); render(); } } },
          h("option", { value: "random", selected: zip.mode === "random" }, "Ngẫu nhiên (xa nhau theo IP) trong các đề được chọn"),
          h("option", { value: "selected", selected: zip.mode === "selected" }, "Luân phiên trong các đề được chọn"),
          h("option", { value: "parity", selected: zip.mode === "parity" }, "Chẵn/lẻ theo chữ số cuối MSSV"),
          h("option", { value: "custom", selected: zip.mode === "custom" }, "Quy tắc tùy chỉnh theo chữ số cuối MSSV"))),
        ...extra));
    }

    let busy = false;
    const syncBusy = () => body.querySelectorAll("[data-guard]").forEach((b) => { b.disabled = busy; });
    const guard = (fn) => async () => {
      if (busy) return;
      busy = true;
      syncBusy();
      try { await fn(); } finally { busy = false; syncBusy(); }
    };
    const needSave = async () => {
      if (!form.title.trim()) { toast("Hãy nhập tên kỳ thi.", true); return false; }
      try { await persist(false); return true; } catch (error) { toast(errorText(error), true); return false; }
    };
    const handlers = {
      saveDraft: guard(async () => { if (await needSave()) { toast("Đã lưu nháp."); render(); } }),
      publish: guard(async () => {
        const problems = publishProblems();
        if (problems.length) { showProblems(problems); return; }
        showErrors = false;
        applyErrors([]);
        if (!(await confirmDialog("Phát đề cho kỳ thi này? Sinh viên được chọn sẽ thấy kỳ thi trong danh sách đã phát đề.", "Phát đề"))) return;
        if (!(await needSave())) return;
        try {
          const data = await post(`/${encodeURIComponent(examId)}/publish`);
          exam = data.exam; toast("Đã phát đề."); history.replaceState(null, "", examUrl(examId)); render();
        } catch (error) {
          toast(errorText(error), true);
          const keys = error && error.body && Array.isArray(error.body.fields) ? error.body.fields : [];
          if (keys.length) applyErrors(keys.map((key) => [key, ""]));
        }
      }),
      saveChanges: guard(async () => {
        if (!form.title.trim()) { toast("Hãy nhập tên kỳ thi.", true); return; }
        try { await persist(false); toast("Đã lưu thay đổi và phát đề lại."); editing = false; history.replaceState(null, "", examUrl(examId)); render(); } catch (error) { toast(errorText(error), true); }
      }),
      cancel: guard(async () => { form = fromExam(exam); editing = false; dirty = false; history.replaceState(null, "", examUrl(examId)); render(); }),
    };
    const guarded = (label, icon, cls, onClick) => {
      const button = h("button", { type: "button", class: `btn ${cls}`, disabled: busy, on: { click: onClick } }, h("i", { class: `fa ${icon}` }), ` ${label}`);
      button.dataset.guard = "1";
      return button;
    };

    // Only the editing actions are repeated at the bottom; destructive actions stay in the top bar.
    function editButtons() {
      const status = exam ? exam.status : "new";
      if (mode() === "edit" && status === "distributed") {
        return [guarded("Hủy bỏ", "fa-times", "btn-ghost", handlers.cancel), guarded("Lưu thay đổi", "fa-save", "btn-primary", handlers.saveChanges)];
      }
      if (mode() === "edit" && (status === "new" || status === "draft")) {
        return [guarded("Lưu nháp", "fa-save", "btn-secondary", handlers.saveDraft), guarded("Phát đề", "fa-paper-plane", "btn-primary", handlers.publish)];
      }
      return [];
    }

    function bottomBar() {
      const buttons = editButtons();
      return buttons.length ? h("div", { class: "exam-action-bar exam-action-bottom" }, ...(exam && exam.status === "draft" || !exam ? [...buttons].reverse() : buttons)) : null;
    }

    function actionBar() {
      const bar = h("div", { class: "exam-action-bar" });
      const reload = () => { location.href = examUrl(examId); };
      const running = ref.running;
      const btn = (label, icon, cls, onClick, disabled) => h("button", { type: "button", class: `btn ${cls}`, disabled: disabled || false, on: { click: onClick } }, h("i", { class: `fa ${icon}` }), ` ${label}`);
      const status = exam ? exam.status : "new";

      const editing_ = editButtons();
      if (editing_.length) {
        bar.append(...editing_);
        if (exam && status === "draft") bar.append(actionButton("delete", exam, () => { location.href = "/admin?section=exams"; }));
        return bar;
      }
      if (status === "distributed") {
        bar.append(
          btn("Chỉnh sửa", "fa-pencil", "btn-secondary", () => { editing = true; history.replaceState(null, "", examUrl(examId, true)); render(); }),
          actionButton("copy", exam, (data) => { location.href = examUrl(data.exam.id); }),
          actionButton("revoke", exam, () => reload()),
          actionButton("start", exam, () => reload(), running),
          actionButton("delete", exam, () => { location.href = "/admin?section=exams"; }));
        if (running) bar.append(h("span", { class: "muted fine-print" }, "Đang có kỳ thi khác diễn ra."));
        return bar;
      }
      if (status === "started") {
        bar.append(link("/admin?section=monitor", "fa-eye", "Giám sát", "btn-secondary"), actionButton("end", exam, () => reload()));
        return bar;
      }
      bar.append(actionButton("delete", exam, () => { location.href = "/admin?section=exams"; }));
      return bar;
    }

    function render() {
      const readOnly = mode() === "view";
      const warningText = !readOnly || !exam ? "" : exam.status === "distributed"
        ? "Kỳ thi đã phát đề. Bấm “Chỉnh sửa” để thay đổi (đề sẽ được phát lại)."
        : "Kỳ thi ở chế độ chỉ xem.";
      body.replaceChildren(
        h("div", { class: "exam-detail-head" },
          h("div", { class: "exam-detail-status" }, pill(exam ? exam.status : "draft"), actionBar()),
          link("/admin?section=exams", "fa-arrow-left", "Danh sách kỳ thi", "btn-ghost")),
        warningText.trim() ? h("div", { class: "alert alert-warning" }, warningText) : null,
        h("fieldset", { class: "exam-form", disabled: readOnly }, configSection(), participantsSection(), codeSection(), zipSection()),
        mode() === "edit" && (!exam || exam.status === "draft") ? autosave : null,
        bottomBar(), notice);
      if (showErrors && mode() === "edit") applyErrors(publishProblems());
    }

    async function init() {
      body.replaceChildren(h("p", { class: "muted" }, h("i", { class: "fa fa-spinner fa-spin" }), " Đang tải…"));
      try {
        const [accounts, files, questions, list] = await Promise.all([
          request("/api/admin/accounts"), request("/api/admin/exams"), request("/api/admin/questions"), request(API),
        ]);
        ref = { accounts: accounts.students || [], files: files.exams || [], questions: questions.questions || [], running: list.exams.some((item) => item.status === "started") };
        if (examId) exam = (await request(`${API}/${encodeURIComponent(examId)}`)).exam;
        editing = params.get("mode") === "edit";
        form = exam ? fromExam(exam) : blank();
        render();
      } catch (error) {
        body.replaceChildren(errorBox(error, init));
      }
    }
    window.addEventListener("beforeunload", (event) => { if (dirty && mode() === "edit") event.preventDefault(); });
    init();
  }

  if (listRoot) initList();
  if (detailRoot) initDetail();
})();
