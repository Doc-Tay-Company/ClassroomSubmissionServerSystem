(function () {
  const $ = (id) => document.getElementById(id);
  const shell = document.querySelector(".admin-shell");
  const escape = (value) => window.cssEscape(String(value ?? ""));
  const show = (id, message, error) => {
    const node = $(id);
    if (!node) return;
    node.textContent = message;
    node.classList.remove("hidden");
    node.style.background = error ? "#fff0f0" : "";
  };
  const toastError = (error) => window.cssToast(error.message || "Không thể xử lý yêu cầu.", "error");

  document.querySelector(".sidebar-toggle")?.addEventListener("click", () => shell?.classList.toggle("sidebar-open"));
  document.querySelectorAll(".sidebar-nav a").forEach((link) => link.addEventListener("click", () => shell?.classList.remove("sidebar-open")));

  let monitorRows = [];
  let monitorServerAt = Date.now();
  let monitorLoadInFlight = false;
  const monitorHistory = new Map();
  let openHistoryKey = "";
  let openHistoryRow = null;
  let monitorExamRecords = null;
  let monitorExamRecordsPromise = null;
  let monitorExamRecordsFetchedAt = 0;
  const attemptKey = (row) => row.monitoring_attempt ? JSON.stringify([row.monitoring_attempt.student_id, row.monitoring_attempt.release_id]) : "";
  async function updateMonitorExamLink() {
    const link = $("monitor-return-exam");
    if (!link) return;
    const releaseIds = new Set(monitorRows.map((row) => row.monitoring_attempt?.release_id).filter(Boolean));
    if (!releaseIds.size) { link.classList.add("hidden"); link.removeAttribute("href"); return; }
    try {
      if (!monitorExamRecords || Date.now() - monitorExamRecordsFetchedAt > 60000) {
        if (!monitorExamRecordsPromise) {
          monitorExamRecordsPromise = window.cssRequest("/api/admin/exam-records")
            .then((response) => { monitorExamRecords = Array.isArray(response.exams) ? response.exams : []; monitorExamRecordsFetchedAt = Date.now(); return monitorExamRecords; })
            .finally(() => { monitorExamRecordsPromise = null; });
        }
        await monitorExamRecordsPromise;
      }
      const matches = (monitorExamRecords || []).filter((exam) => releaseIds.has(exam.release?.release_id));
      const started = matches.filter((exam) => exam.status === "started");
      const selected = started.length === 1 ? started[0] : (!started.length && matches.length === 1 ? matches[0] : null);
      if (!selected?.id) { link.classList.add("hidden"); link.removeAttribute("href"); return; }
      link.href = `/admin?section=exam&id=${encodeURIComponent(selected.id)}`;
      link.classList.remove("hidden");
    } catch (_) {
      link.classList.add("hidden");
      link.removeAttribute("href");
    }
  }
  async function syncMonitorHistory(rows) {
    await Promise.all((rows || []).map(async (row) => {
      const key = attemptKey(row);
      if (!key || !row.latest_event_seq) return;
      let state = monitorHistory.get(key);
      if (!state) { state = { cursor: 0, events: [], fetching: false }; monitorHistory.set(key, state); }
      if (state.fetching || state.cursor >= Number(row.latest_event_seq)) return;
      state.fetching = true;
      try {
        while (state.cursor < Number(row.latest_event_seq)) {
          const params = new URLSearchParams({
            student_id: row.monitoring_attempt.student_id,
            release_id: row.monitoring_attempt.release_id,
            after_seq: String(state.cursor),
            limit: "100",
          });
          const page = await window.cssRequest(`/api/admin/monitor/events?${params}`);
          if (!Array.isArray(page.events) || !page.events.length) break;
          const expectedFirst = state.cursor + 1;
          const firstSeq = Number(page.events[0].seq);
          const lastSeq = Number(page.events[page.events.length - 1].seq);
          if (firstSeq !== expectedFirst || !Number.isInteger(lastSeq) || lastSeq < firstSeq) break;
          state.events.push(...page.events);
          state.cursor = lastSeq;
          if (!page.has_more && state.cursor < Number(row.latest_event_seq)) break;
        }
      } catch (_) {
        // Keep the cursor unchanged on a failed page so the next Monitor poll retries it.
      } finally { state.fetching = false; }
    }));
  }
  async function loadMonitor() { // data to display in mornitor screen
    if (monitorLoadInFlight) return;
    monitorLoadInFlight = true;
    try {
      const data = await window.cssRequest("/api/admin/monitor");
      monitorRows = data.students || [];
      monitorServerAt = Date.parse(data.occurred_at) || Date.now();
      await updateMonitorExamLink();
      await syncMonitorHistory(monitorRows);
      if ($("stat-total")) $("stat-total").textContent = monitorRows.length;
      if ($("stat-online")) $("stat-online").textContent = data.online_count ?? 0;
      if ($("stat-submitted")) $("stat-submitted").textContent = monitorRows.filter((row) => row.submission_count > 0).length;
      if ($("stat-abnormal")) $("stat-abnormal").textContent = data.abnormal_count ?? 0;
      if ($("monitor-updated")) $("monitor-updated").textContent = "Đồng bộ server " + new Date(monitorServerAt).toLocaleTimeString();
      renderMonitor();
    } finally { monitorLoadInFlight = false; }
  }
  function renderParticipants() { // data to display in select participant in exam
    const box = $("participant-list");
    if (!box) return;
    const query = ($("participant-search")?.value || "").toLowerCase();
    const rows = students.filter((row) => [row.student_id, row.full_name].join(" ").toLowerCase().includes(query));
    box.innerHTML = rows.map((row) => `<label class="student-option"><input type="checkbox" name="exam_participant" value="${escape(row.student_id)}" ${row.exam_participant ? "checked" : ""}><span><strong>${escape(row.student_id)}</strong><small>${escape(row.full_name || "")}</small></span></label>`).join("") || '<span class="muted">Không tìm thấy sinh viên.</span>';
    if ($("participant-count")) $("participant-count").textContent = `${document.querySelectorAll('input[name="exam_participant"]:checked').length} sinh viên`;
  }
  function renderMonitor() { // data to display in student card in monitor
    const body = $("monitor-body");
    if (!body) return;
    const query = ($("monitor-search")?.value || "").toLowerCase();
    const labels = { tab_hidden: "Tab bị ẩn", window_unfocused: "Mất focus", multiple_tabs: "Nhiều tab", recorded_window_blur: "Đã ghi nhận mất focus", recorded_document_hidden: "Đã ghi nhận ẩn trang" };
    const rows = monitorRows.filter((row) => [row.student_id, row.full_name, row.ip].join(" ").toLowerCase().includes(query));
    body.innerHTML = rows.map((row) => {
      const alerts = (row.alerts || []).map((alert) => `<span class="status-pill status-red">${labels[alert] || escape(alert)}</span>`).join("");
      const historyPanel = row.latest_event_seq && attemptKey(row)
        ? `<details class="monitor-event-history" data-monitor-history="${escape(attemptKey(row))}"><summary>Xem chi tiết</summary></details>`
        : "";
      const remaining = row.attempt_state === "active"
        ? `${Math.floor(row.remaining_seconds / 60)}:${String(row.remaining_seconds % 60).padStart(2, "0")}`
        : ({ not_started: "Ch\u01b0a b\u1eaft \u0111\u1ea7u", no_show: "Kh\u00f4ng d\u1ef1 thi", awaiting_completion: "00:00", completed: "\u0110\u00e3 ho\u00e0n th\u00e0nh", unassigned: "\u2014" }[row.attempt_state] || "\u2014");
      return `<tr class="${alerts ? "row-warning" : ""}"><td><div class="cell-main">${escape(row.student_id)}</div><div class="cell-sub">${escape(row.full_name)}</div></td><td class="code-text">${escape(row.ip || "—")}</td><td>${row.logged_in ? '<span class="status-pill status-green">Đang đăng nhập</span>' : '<span class="status-pill status-gray">Ngoại tuyến / chưa đăng nhập</span>'}<div class="cell-sub">${escape(row.last_seen || "")}</div></td><td>${escape(row.exam_file || "—")}</td><td>${remaining}</td><td>${row.submission_count || 0} lần</td><td><div class="user-agent">${escape(row.user_agent || "—")}</div></td><td>${alerts || '<span class="muted">Bình thường</span>'}<div>${historyPanel}</div></td><td><button class="btn btn-secondary btn-small" data-force="${escape(row.student_id)}">Ép nộp</button> <button class="btn btn-secondary btn-small" data-adjust="${escape(row.student_id)}">Điều chỉnh giờ</button></td></tr>`;
    }).join("") || '<tr><td colspan="9" class="empty-cell">Không có dữ liệu.</td></tr>';
    renderHistoryDialog();
  }

  const eventTypeLabels = { window_blur: "Mất focus cửa sổ", document_hidden: "Trang chuyển sang ẩn", multiple_tabs_detected: "Phát hiện nhiều trang ứng dụng", fullscreen_refused: "Từ chối toàn màn hình", fullscreen_request_failed: "Yêu cầu toàn màn hình thất bại (kỹ thuật)", fullscreen_lost: "Rời chế độ toàn màn hình" };
  function formatEventTimestamp(value) {
    const parsed = value ? new Date(value) : null;
    return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toLocaleString("vi-VN") : String(value || "Không có thời gian");
  }
  function renderHistoryDialog() {
    const dialog = $("monitor-history-modal");
    const content = $("monitor-history-content");
    if (!dialog || !content || !dialog.open || !openHistoryKey || !openHistoryRow) return;
    const refreshedRow = monitorRows.find((item) => attemptKey(item) === openHistoryKey);
    if (refreshedRow) openHistoryRow = refreshedRow;
    const row = openHistoryRow;
    const state = monitorHistory.get(openHistoryKey);
    const counters = row.event_counters || {};
    const expectedSeq = Number(row.latest_event_seq || 0);
    const events = (state?.events || []).map((item) => {
      const details = [
        item.source ? `Nguồn: ${escape(item.source)}` : "",
        item.client_occurred_at ? `Thời điểm từ trình duyệt: ${escape(formatEventTimestamp(item.client_occurred_at))}` : "",
      ].filter(Boolean).join(" · ");
      const receivedAt = formatEventTimestamp(item.received_at);
      return `<li class="monitor-history-event"><div class="monitor-history-event-heading"><strong>#${Number(item.seq)} · ${escape(eventTypeLabels[item.event_type] || item.event_type || "Sự kiện kỹ thuật")}</strong><time datetime="${escape(item.received_at || "")}">${escape(receivedAt)}</time></div>${details ? `<div class="cell-sub">${details}</div>` : ""}</li>`;
    }).join("");
    const loading = !state || state.cursor < expectedSeq;
    const attempt = row.monitoring_attempt || {};
    const additionalCounters = ["multiple_tabs_detected", "fullscreen_refused", "fullscreen_request_failed", "fullscreen_lost"]
      .filter((type) => Number(counters[type] || 0) > 0)
      .map((type) => `<span>${escape(eventTypeLabels[type])}: <strong>${Number(counters[type])}</strong></span>`).join("");
    content.innerHTML = `<div class="monitor-history-identity"><div><strong>${escape(row.full_name || row.student_id || "Sinh viên")}</strong><div class="cell-sub">MSSV: ${escape(row.student_id || attempt.student_id || "—")}</div></div><div><strong>Đề / lượt thi</strong><div class="cell-sub">${escape(row.exam_file || "—")} · Release: ${escape(attempt.release_id || "—")}</div></div></div><div class="monitor-history-counters"><span>Focus: <strong>${Number(counters.window_blur || 0)}</strong></span><span>Ẩn trang: <strong>${Number(counters.document_hidden || 0)}</strong></span>${additionalCounters}</div>${loading ? '<p class="muted" role="status">Đang tải lịch sử sự kiện…</p>' : ""}<ol class="monitor-history-list">${events || (loading ? "" : '<li class="muted">Chưa có sự kiện được ghi nhận.</li>')}</ol>`;
  }

  let students = [];
  async function loadAccounts() {
    const data = await window.cssRequest("/api/admin/accounts");
    students = data.students || [];
    renderStudents();
    renderNotificationStudents();
    renderParticipants();
  }
  function renderStudents() {
    const body = $("accounts-body");
    if (!body) return;
    const query = ($("account-search")?.value || "").toLowerCase();
    const rows = students.filter((row) => [row.student_id, row.full_name, row.last_ip].join(" ").toLowerCase().includes(query));
    body.innerHTML = rows.map((row) => `<tr><td class="cell-main">${escape(row.student_id)}</td><td>${escape(row.full_name)}</td><td>${row.active ? '<span class="status-pill status-green">Hoạt động</span>' : '<span class="status-pill status-red">Đã khóa</span>'}</td><td class="code-text">${escape(row.last_ip || "—")}</td><td><div class="actions-inline"><button class="btn btn-secondary btn-small" data-toggle-account="${escape(row.student_id)}">${row.active ? "Khóa" : "Mở khóa"}</button><button class="btn btn-secondary btn-small" data-reset-account="${escape(row.student_id)}">Đặt lại mật khẩu</button><button class="btn btn-secondary btn-small" data-unlock-account="${escape(row.student_id)}">Gỡ khóa login</button></div></td></tr>`).join("") || '<tr><td colspan="5" class="empty-cell">Chưa có tài khoản.</td></tr>';
  }
  function renderNotificationStudents() {
    const box = $("notification-students");
    if (!box) return;
    const query = ($("notification-search")?.value || "").toLowerCase();
    const rows = students.filter((row) => [row.student_id, row.full_name].join(" ").toLowerCase().includes(query));
    box.innerHTML = rows.map((row) => `<label class="student-option"><input type="checkbox" name="notification_student" value="${escape(row.student_id)}"><span><strong>${escape(row.student_id)}</strong><small>${escape(row.full_name)}</small></span></label>`).join("") || '<span class="muted">Không tìm thấy sinh viên.</span>';
    updateSelectedCount();
  }
  function updateSelectedCount() {
    if ($("selected-students-count")) $("selected-students-count").textContent = `${document.querySelectorAll('input[name="notification_student"]:checked').length} sinh viên được chọn`;
  }

  let submissions = [];
  async function loadSubmissions() {
    const data = await window.cssRequest("/api/admin/submissions");
    submissions = data.submissions || [];
    const body = $("submissions-body");
    if (!body) return;
    const query = ($("submission-search")?.value || "").toLowerCase();
    const rows = submissions.filter((row) => [row.student_id, row.full_name, row.exam_name, row.exam_file, row.filename, row.ip].join(" ").toLowerCase().includes(query));
    if ($("submission-count")) $("submission-count").textContent = `${rows.length} bản ghi`;
    body.innerHTML = rows.map((row) => `<tr><td><div class="cell-main">${escape(row.student_id)}</div><div class="cell-sub">${escape(row.full_name)}</div></td><td>${escape(row.exam_name || "Không xác định")}</td><td>${escape(row.exam_file || "Không xác định")}</td><td>${row.attempt ?? "—"}</td><td>${row.payload_retained === false ? "Payload đã xóa" : `<a href="/admin/submissions/${encodeURIComponent(row.student_id)}/${encodeURIComponent(row.filename)}">${escape(row.filename)}</a>`}</td><td>${escape(row.submitted_at || "")}</td><td>${row.payload_retained === false ? "Đã xóa payload" : "Đang lưu"}</td></tr>`).join("") || '<tr><td colspan="7" class="empty-cell">Chưa có bài nộp.</td></tr>';
  }

  async function loadAdmins() {
    const data = await window.cssRequest("/api/admin/admins");
    const body = $("admins-body");
    if (!body) return;
    body.innerHTML = (data.admins || []).map((row) => `<tr><td>${escape(row.username)}</td><td>${escape(row.created_at || "")}</td><td>${escape(row.created_by || "—")}</td><td>${row.active ? "Hoạt động" : "Đã khóa"}</td></tr>`).join("") || '<tr><td colspan="4" class="empty-cell">Chưa có Admin.</td></tr>';
  }
  async function loadServerInfo() {
    const data = await window.cssRequest("/api/admin/server-info");
    const box = $("server-addresses");
    if (!box) return;
    const addresses = [...new Set([...(data.addresses || []), data.current_url].filter(Boolean))];
    box.innerHTML = addresses.map((address) => `<div class="address-item"><strong>${escape(address)}</strong><button class="btn btn-secondary" data-copy="${escape(address)}">Copy</button></div>`).join("") || '<span class="muted">Không xác định được địa chỉ LAN.</span>';
  }

  $("monitor-search")?.addEventListener("input", renderMonitor);
  $("refresh-monitor")?.addEventListener("click", () => loadMonitor().catch(toastError));
  $("account-search")?.addEventListener("input", renderStudents);
  $("participant-search")?.addEventListener("input", renderParticipants);
  $("participant-list")?.addEventListener("change", () => { if ($("participant-count")) $("participant-count").textContent = `${document.querySelectorAll('input[name="exam_participant"]:checked').length} sinh viên`; });
  $("select-all-participants")?.addEventListener("click", () => { document.querySelectorAll("#participant-list .student-option").forEach((row) => { row.querySelector("input").checked = true; }); if ($("participant-count")) $("participant-count").textContent = `${document.querySelectorAll('input[name="exam_participant"]:checked').length} sinh viên`; });
  $("clear-all-participants")?.addEventListener("click", () => { document.querySelectorAll("#participant-list input").forEach((input) => { input.checked = false; }); if ($("participant-count")) $("participant-count").textContent = "0 sinh viên"; });
  $("save-participants")?.addEventListener("click", async () => {
    const selected = [...document.querySelectorAll('input[name="exam_participant"]:checked')].map((input) => input.value);
    const pasted = $("participant-paste")?.value.trim() || "";
    const ids = [...new Set([...selected, ...pasted.replace(/,/g, "\n").split(/\r?\n/).map((item) => item.trim()).filter(Boolean)])];
    if (!ids.length) return window.cssToast("Hãy chọn hoặc nhập ít nhất một MSSV.", "error");
    const form = new FormData(); form.set("student_ids", ids.join("\n"));
    try { const data = await window.cssRequest("/api/admin/exam-participants", { method: "POST", body: form }); $("participant-paste").value = ""; show("participant-result", `Đã lưu ${data.count} sinh viên dự thi. Tạo mới ${data.created.length} tài khoản.`); await loadAccounts(); } catch (error) { show("participant-result", error.message, true); toastError(error); }
  });
  $("accounts-body")?.addEventListener("click", async (event) => {
    const toggle = event.target.closest("[data-toggle-account]");
    const reset = event.target.closest("[data-reset-account]");
    const unlock = event.target.closest("[data-unlock-account]");
    try {
      if (toggle) {
        await window.cssRequest(`/api/admin/accounts/${encodeURIComponent(toggle.dataset.toggleAccount)}/toggle`, { method: "POST" });
        window.cssToast("Đã cập nhật trạng thái tài khoản.", "success");
      } else if (unlock) {
        await window.cssRequest(`/api/admin/accounts/${encodeURIComponent(unlock.dataset.unlockAccount)}/unlock-login`, { method: "POST" });
        window.cssToast("Đã gỡ giới hạn đăng nhập.", "success");
      } else if (reset) {
        const password = window.prompt("Nhập mật khẩu mới (tối thiểu 8 ký tự):", "");
        if (password === null) return;
        if (password.length < 8) throw new Error("Mật khẩu phải có ít nhất 8 ký tự.");
        const form = new FormData();
        form.set("new_password", password);
        await window.cssRequest(`/api/admin/accounts/${encodeURIComponent(reset.dataset.resetAccount)}/reset-password`, { method: "POST", body: form });
        window.cssToast("Đã đặt lại mật khẩu.", "success");
      }
      if (toggle || reset || unlock) await loadAccounts();
    } catch (error) { toastError(error); }
  });
  $("submission-search")?.addEventListener("input", () => loadSubmissions().catch(toastError));
  $("refresh-server-info")?.addEventListener("click", () => loadServerInfo().catch(toastError));
  $("distribution-mode")?.addEventListener("change", (event) => {
    $("parity-fields")?.classList.toggle("hidden", event.target.value !== "parity");
    $("custom-fields")?.classList.toggle("hidden", event.target.value !== "custom");
    if (event.target.value === "custom") renderRemainderRules();
  });
  $("select-all-exams")?.addEventListener("click", () => document.querySelectorAll('input[name="exam-choice"]').forEach((input) => { input.checked = true; }));
  $("clear-all-exams")?.addEventListener("click", () => document.querySelectorAll('input[name="exam-choice"]').forEach((input) => { input.checked = false; }));
  function selectedExamNames() {
    return [...document.querySelectorAll('input[name="exam-choice"]:checked')].map((input) => input.value);
  }
  function renderRemainderRules() {
    const box = $("remainder-rules");
    if (!box) return;
    const exams = selectedExamNames();
    const count = exams.length;
    if ($("custom-modulus")) $("custom-modulus").value = String(count);
    if ($("custom-modulus-label")) $("custom-modulus-label").textContent = String(count);
    if (count < 2) {
      box.innerHTML = '<p class="muted">Hãy chọn ít nhất 2 đề ở mục phía trên để tạo quy tắc theo số dư.</p>';
      updateRemainderMap();
      return;
    }
    box.innerHTML = Array.from({ length: count }, (_, remainder) => `<label class="remainder-row"><span>Chữ số cuối chia ${count} dư <strong>${remainder}</strong></span><select class="remainder-exam" data-remainder="${remainder}">${exams.map((exam) => `<option value="${escape(exam)}">${escape(exam)}</option>`).join("") || '<option value="">Chưa chọn đề</option>'}</select></label>`).join("");
    updateRemainderMap();
  }
  function updateRemainderMap() {
    const map = {};
    const modulus = Number($("custom-modulus")?.value || selectedExamNames().length);
    document.querySelectorAll(".remainder-exam").forEach((select) => {
      const exam = select.value;
      if (exam && modulus > 0) for (let digit = Number(select.dataset.remainder); digit < 10; digit += modulus) map[String(digit)] = exam;
    });
    if ($("last-digit-map")) $("last-digit-map").value = JSON.stringify(map);
  }
  $("remainder-rules")?.addEventListener("change", updateRemainderMap);
  document.querySelectorAll('input[name="exam-choice"]').forEach((input) => input.addEventListener("change", () => { if ($("distribution-mode")?.value === "custom") renderRemainderRules(); }));
  document.querySelectorAll('input[name="notification_scope"]').forEach((radio) => radio.addEventListener("change", () => $("notification-picker")?.classList.toggle("hidden", radio.value !== "selected" || !radio.checked)));
  $("notification-search")?.addEventListener("input", renderNotificationStudents);
  $("notification-students")?.addEventListener("change", updateSelectedCount);
  $("select-visible-students")?.addEventListener("click", () => { document.querySelectorAll(".student-option input").forEach((input) => { input.checked = true; }); updateSelectedCount(); });
  $("clear-selected-students")?.addEventListener("click", () => { document.querySelectorAll('input[name="notification_student"]').forEach((input) => { input.checked = false; }); updateSelectedCount(); });

  $("import-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    let data;
    try {
      data = await window.cssRequest("/api/admin/accounts/import", { method: "POST", body: new FormData(form) });
    } catch (error) {
      show("import-result", error.message, true);
      toastError(error);
      return;
    }
    const duplicates = data.duplicates?.length ? ` Bỏ qua ${data.duplicates.length} MSSV đã tồn tại.` : "";
    const errors = data.errors?.length ? ` Có ${data.errors.length} dòng lỗi.` : "";
    show("import-result", `Đã tạo ${data.created_count} tài khoản.${duplicates}${errors}`);
    if (!data.errors?.length) form.reset();
    try {
      await Promise.all([loadAccounts(), loadMonitor()]);
    } catch (error) {
      show("import-result", `Yêu cầu đã tạo ${data.created_count} tài khoản, nhưng không thể làm mới danh sách: ${error.message}`, true);
      toastError(error);
    }
  });
  $("notification-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = [...document.querySelectorAll('input[name="notification_student"]:checked')].map((input) => input.value);
    const scope = event.currentTarget.querySelector('input[name="notification_scope"]:checked')?.value;
    if (scope === "selected" && !selected.length) return window.cssToast("Hãy chọn ít nhất một sinh viên.", "error");
    const form = new FormData(event.currentTarget); form.delete("notification_scope"); form.set("student_ids", selected.join(","));
    try { await window.cssRequest("/api/admin/notifications", { method: "POST", body: form }); event.currentTarget.reset(); show("notification-result", "Đã gửi thông báo thành công."); } catch (error) { show("notification-result", error.message, true); toastError(error); }
  });
  $("create-admin-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { const data = await window.cssRequest("/api/admin/admins", { method: "POST", body: new FormData(event.currentTarget) }); event.currentTarget.reset(); show("admin-create-result", `Đã tạo Admin ${data.username}.`); await loadAdmins(); } catch (error) { show("admin-create-result", error.message, true); toastError(error); }
  });
  $("monitor-body")?.addEventListener("click", async (event) => {
    const historyDisclosure = event.target.closest("details[data-monitor-history]");
    if (historyDisclosure) {
      event.preventDefault();
      const key = historyDisclosure.dataset.monitorHistory;
      const row = monitorRows.find((item) => attemptKey(item) === key);
      const dialog = $("monitor-history-modal");
      if (row && dialog && !dialog.open) {
        openHistoryKey = key;
        openHistoryRow = row;
        dialog.showModal();
        renderHistoryDialog();
      }
      return;
    }
    const force = event.target.closest("[data-force]"); const adjust = event.target.closest("[data-adjust]");
    try {
      if (force && window.confirm(`Ép ${force.dataset.force} nộp bài ngay?`)) await window.cssRequest(`/api/admin/students/${encodeURIComponent(force.dataset.force)}/force-submit`, { method: "POST" });
      if (adjust) { const minutes = window.prompt("Nhập số phút cộng/trừ:", "-5"); if (minutes !== null) { const form = new FormData(); form.set("minutes", minutes); await window.cssRequest(`/api/admin/students/${encodeURIComponent(adjust.dataset.adjust)}/adjust-time`, { method: "POST", body: form }); } }
      if (force || adjust) { await loadMonitor(); window.cssToast("Đã cập nhật.", "success"); }
    } catch (error) { toastError(error); }
  });
  const historyDialog = $("monitor-history-modal");
  historyDialog?.addEventListener("close", () => {
    openHistoryKey = "";
    openHistoryRow = null;
  });
  historyDialog?.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-monitor-history-close]")) {
      historyDialog.close();
      return;
    }
    if (event.target === historyDialog) historyDialog.close();
  });
  $("distribution-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    form.set("exam_files", [...document.querySelectorAll('input[name="exam-choice"]:checked')].map((input) => input.value).join(","));
    const codeExamId = $("code-exam-select")?.value || "";
    const codeOnly = Boolean(codeExamId) && Boolean($("code-only")?.checked);
    if (codeExamId) form.set("code_exam_id", codeExamId);
    if (codeOnly) { form.set("code_only", "true"); form.set("mode", "selected"); form.set("exam_files", ""); }
    else if (!form.get("exam_files")) return window.cssToast("Hãy chọn ít nhất một đề.", "error");
    if (!codeOnly && form.get("mode") === "custom") { updateRemainderMap(); form.set("last_digit_map", $("last-digit-map").value); form.set("custom_modulus", $("custom-modulus").value); }
    try { const data = await window.cssRequest("/api/admin/distribute", { method: "POST", body: form }); show("distribution-result", `Đã phát đề cho ${data.assigned_count} tài khoản.`); if ($("start-exam-admin")) $("start-exam-admin").disabled = false; } catch (error) { show("distribution-result", error.message, true); toastError(error); }
  });
  $("settings-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = new FormData(event.currentTarget); form.set("overwrite_previous", $("overwrite").value); form.set("exam_password_enabled", $("password-enabled").checked ? "true" : "false");
    try { await window.cssRequest("/api/admin/settings", { method: "POST", body: form }); show("settings-result", "Đã lưu cấu hình kỳ thi."); } catch (error) { show("settings-result", error.message, true); toastError(error); }
  });
  $("start-exam-admin")?.addEventListener("click", async () => { try { await window.cssRequest("/api/admin/start-exam", { method: "POST" }); location.reload(); } catch (error) { toastError(error); } });
  $("end-exam")?.addEventListener("click", async () => { try { await window.cssRequest("/api/admin/end-exam", { method: "POST" }); location.reload(); } catch (error) { toastError(error); } });
  document.body.addEventListener("click", (event) => { const button = event.target.closest("[data-copy]"); if (button) navigator.clipboard?.writeText(button.dataset.copy); });

  const pageLoads = [];
  if ($("monitor-body") || $("stat-total")) pageLoads.push(loadMonitor());
  if ($("accounts-body") || $("notification-students") || $("participant-list")) pageLoads.push(loadAccounts());
  if ($("submissions-body")) pageLoads.push(loadSubmissions());
  if ($("admins-body")) pageLoads.push(loadAdmins());
  if ($("server-addresses")) pageLoads.push(loadServerInfo());
  if ($("distribution-mode")?.value === "custom") renderRemainderRules();
  Promise.all(pageLoads).catch(toastError);
  window.setInterval(() => { if ($("monitor-body")) loadMonitor().catch(() => {}); }, 5000);
})();
