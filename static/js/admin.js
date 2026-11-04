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
  async function loadMonitor() {
    const data = await window.cssRequest("/api/admin/monitor");
    monitorRows = data.students || [];
    monitorServerAt = Date.parse(data.occurred_at) || Date.now();
    if ($("stat-total")) $("stat-total").textContent = monitorRows.length;
    if ($("stat-online")) $("stat-online").textContent = data.online_count ?? 0;
    if ($("stat-submitted")) $("stat-submitted").textContent = monitorRows.filter((row) => row.submission_count > 0).length;
    if ($("stat-abnormal")) $("stat-abnormal").textContent = data.abnormal_count ?? 0;
    if ($("monitor-updated")) $("monitor-updated").textContent = "Đồng bộ server " + new Date(monitorServerAt).toLocaleTimeString();
    renderMonitor();
  }
  function renderParticipants() {
    const box = $("participant-list");
    if (!box) return;
    const query = ($("participant-search")?.value || "").toLowerCase();
    const rows = students.filter((row) => [row.student_id, row.full_name].join(" ").toLowerCase().includes(query));
    box.innerHTML = rows.map((row) => `<label class="student-option"><input type="checkbox" name="exam_participant" value="${escape(row.student_id)}" ${row.exam_participant ? "checked" : ""}><span><strong>${escape(row.student_id)}</strong><small>${escape(row.full_name || "")}</small></span></label>`).join("") || '<span class="muted">Không tìm thấy sinh viên.</span>';
    if ($("participant-count")) $("participant-count").textContent = `${document.querySelectorAll('input[name="exam_participant"]:checked').length} sinh viên`;
  }
  function renderMonitor() {
    const body = $("monitor-body");
    if (!body) return;
    const query = ($("monitor-search")?.value || "").toLowerCase();
    const labels = { tab_hidden: "Tab bị ẩn", window_unfocused: "Mất focus", multiple_tabs: "Nhiều tab" };
    const rows = monitorRows.filter((row) => [row.student_id, row.full_name, row.ip].join(" ").toLowerCase().includes(query));
    body.innerHTML = rows.map((row) => {
      const alerts = (row.alerts || []).map((alert) => `<span class="status-pill status-red">${labels[alert] || escape(alert)}</span>`).join("");
      const remaining = row.remaining_seconds == null ? "—" : `${Math.floor(row.remaining_seconds / 60)}:${String(row.remaining_seconds % 60).padStart(2, "0")}`;
      return `<tr class="${alerts ? "row-warning" : ""}"><td><div class="cell-main">${escape(row.student_id)}</div><div class="cell-sub">${escape(row.full_name)}</div></td><td class="code-text">${escape(row.ip || "—")}</td><td>${row.logged_in ? '<span class="status-pill status-green">Đang đăng nhập</span>' : '<span class="status-pill status-gray">Ngoại tuyến / chưa đăng nhập</span>'}<div class="cell-sub">${escape(row.last_seen || "")}</div></td><td>${escape(row.exam_file || "—")}</td><td>${remaining}</td><td>${row.submission_count || 0} lần</td><td><div class="user-agent">${escape(row.user_agent || "—")}</div></td><td>${alerts || '<span class="muted">Bình thường</span>'}</td><td><button class="btn btn-secondary btn-small" data-force="${escape(row.student_id)}">Ép nộp</button> <button class="btn btn-secondary btn-small" data-adjust="${escape(row.student_id)}">Điều chỉnh giờ</button></td></tr>`;
    }).join("") || '<tr><td colspan="9" class="empty-cell">Không có dữ liệu.</td></tr>';
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
    const rows = submissions.filter((row) => [row.student_id, row.full_name, row.filename, row.ip].join(" ").toLowerCase().includes(query));
    if ($("submission-count")) $("submission-count").textContent = `${rows.length} bản ghi`;
    body.innerHTML = rows.map((row) => `<tr><td><div class="cell-main">${escape(row.student_id)}</div><div class="cell-sub">${escape(row.full_name)}</div></td><td>${row.attempt}</td><td>${row.payload_retained === false ? "Payload đã xóa" : `<a href="/admin/submissions/${encodeURIComponent(row.student_id)}/${encodeURIComponent(row.filename)}">${escape(row.filename)}</a>`}</td><td>${escape(row.submitted_at || "")}</td><td>${row.payload_retained === false ? "Đã xóa payload" : "Đang lưu"}</td></tr>`).join("") || '<tr><td colspan="5" class="empty-cell">Chưa có bài nộp.</td></tr>';
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
    try {
      const data = await window.cssRequest("/api/admin/accounts/import", { method: "POST", body: new FormData(event.currentTarget) });
      show("import-result", `Đã tạo ${data.created_count} tài khoản.` + (data.errors?.length ? ` Có ${data.errors.length} dòng lỗi.` : ""));
      if (!data.errors?.length) event.currentTarget.reset();
      await Promise.all([loadAccounts(), loadMonitor()]);
    } catch (error) { show("import-result", error.message, true); toastError(error); }
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
    const force = event.target.closest("[data-force]"); const adjust = event.target.closest("[data-adjust]");
    try {
      if (force && window.confirm(`Ép ${force.dataset.force} nộp bài ngay?`)) await window.cssRequest(`/api/admin/students/${encodeURIComponent(force.dataset.force)}/force-submit`, { method: "POST" });
      if (adjust) { const minutes = window.prompt("Nhập số phút cộng/trừ:", "-5"); if (minutes !== null) { const form = new FormData(); form.set("minutes", minutes); await window.cssRequest(`/api/admin/students/${encodeURIComponent(adjust.dataset.adjust)}/adjust-time`, { method: "POST", body: form }); } }
      if (force || adjust) { await loadMonitor(); window.cssToast("Đã cập nhật.", "success"); }
    } catch (error) { toastError(error); }
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
