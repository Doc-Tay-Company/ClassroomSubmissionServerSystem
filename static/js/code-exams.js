(() => {
  "use strict";
  const ui = window.cssUi;
  if (!ui) return;
  const { h, errorBox, errorText, setNotice, statusPill } = ui;
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

  // ---------- selector inside the distribution form (exam section) ----------
  const select = document.getElementById("code-exam-select");
  if (select) {
    fetchCodeExams().then((exams) => {
      for (const exam of exams) {
        if (exam.status === "ended") continue;
        select.append(h("option", { value: exam.id }, `${exam.title} (${(exam.questions || []).length} câu)`));
      }
    }).catch(() => {
      select.append(h("option", { value: "", disabled: true }, "Không tải được danh sách đề code"));
    });
  }

  // ---------- code exam tab ----------
  const root = document.getElementById("code-exams-view");
  if (!root) return;
  const listHost = document.getElementById("ce-list");
  const formHost = document.getElementById("ce-form-host");
  const notice = document.getElementById("ce-notice");

  async function loadList() {
    listHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải danh sách đề thi code..."));
    try {
      const exams = await fetchCodeExams();
      if (!exams.length) {
        listHost.replaceChildren(h("p", { class: "empty-cell" }, "Chưa có đề thi code nào. Nhấn “Tạo đề thi”."));
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

  async function openForm() {
    formHost.classList.remove("hidden");
    formHost.replaceChildren(h("p", { class: "muted pad" }, "Đang tải câu hỏi đã xuất bản..."));
    let published;
    try {
      const data = await request("/api/admin/questions");
      published = (data.questions || []).filter((q) => q.status === "published");
    } catch (error) {
      formHost.replaceChildren(errorBox(error, openForm));
      return;
    }
    if (!published.length) {
      formHost.replaceChildren(
        h("div", { class: "alert alert-warning" }, "Chưa có câu hỏi nào đã xuất bản. Hãy tạo, chạy đáp án mẫu và xuất bản câu hỏi trong “Ngân hàng câu hỏi” trước."),
        h("a", { class: "btn btn-secondary btn-small", href: "/admin?section=exam-management&tab=questions" }, "Đến Ngân hàng câu hỏi"),
        h("button", { type: "button", class: "btn btn-ghost btn-small", on: { click: () => formHost.classList.add("hidden") } }, "Đóng"));
      return;
    }

    const title = h("input", { type: "text", maxlength: 200 });
    const policy = h("select", {}, h("option", { value: "once" }, "Chỉ nộp 1 lần"), h("option", { value: "configurable" }, "Cho nộp nhiều lần"));
    policy.value = "configurable";
    const maxSubmissions = h("input", { type: "number", min: 1, max: 20, step: 1, value: 1 });
    const showScore = h("input", { type: "checkbox" });
    const allowPretest = h("input", { type: "checkbox", checked: true });
    const cooldown = h("input", { type: "number", min: 0, max: 3600, step: "any", value: 2 });
    const maxPretest = h("input", { type: "number", min: 1, max: 1000, step: 1, value: 20 });
    const boxes = published.map((q) => ({ q, input: h("input", { type: "checkbox", value: q.id }) }));
    const msg = h("div", { class: "notice hidden" });

    const syncPolicy = () => { maxSubmissions.disabled = policy.value === "once"; };
    policy.addEventListener("change", syncPolicy);
    syncPolicy();

    const submit = h("button", { type: "submit", class: "btn btn-primary" }, h("i", { class: "fa fa-save" }), " Tạo đề thi");
    const form = h("form", {
      class: "stack-form",
      novalidate: true,
      on: {
        submit: async (event) => {
          event.preventDefault();
          const ids = boxes.filter((b) => b.input.checked).map((b) => b.q.id);
          if (!title.value.trim()) return setNotice(msg, "Hãy nhập tiêu đề đề thi.", true);
          if (!ids.length) return setNotice(msg, "Hãy chọn ít nhất một câu hỏi.", true);
          const body = {
            title: title.value.trim(),
            question_ids: ids,
            submission_policy: policy.value,
            show_final_score_immediately: showScore.checked,
            allow_pretest: allowPretest.checked,
            pretest_cooldown_seconds: Number(cooldown.value),
            max_pretest_runs: Number(maxPretest.value),
          };
          if (policy.value === "configurable") body.max_submissions = Number(maxSubmissions.value);
          submit.disabled = true;
          try {
            await request("/api/admin/code-exams", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
            formHost.classList.add("hidden");
            formHost.replaceChildren();
            setNotice(notice, "Đã tạo đề thi code. Dùng mục “Cấu hình kỳ thi” để phát đề cho sinh viên.", false);
            loadList();
          } catch (error) {
            setNotice(msg, errorText(error), true);
            submit.disabled = false;
          }
        },
      },
    },
    h("h3", {}, "Tạo đề thi code"),
    h("label", { class: "field" }, h("span", {}, "Tiêu đề *"), title),
    h("fieldset", {}, h("legend", {}, "Chọn câu hỏi đã xuất bản"),
      ...boxes.map(({ q, input }) => h("label", { class: "checkbox-row" }, input, ` ${q.title} · ${q.language}/${q.grading_mode} · ${q.total_points} điểm`))),
    h("div", { class: "two-cols" },
      h("label", { class: "field" }, h("span", {}, "Chính sách nộp bài"), policy),
      h("label", { class: "field" }, h("span", {}, "Số lần nộp tối đa (1–20)"), maxSubmissions),
      h("label", { class: "field" }, h("span", {}, "Cooldown chạy thử (giây)"), cooldown),
      h("label", { class: "field" }, h("span", {}, "Số lần chạy thử tối đa"), maxPretest)),
    h("label", { class: "checkbox-row" }, allowPretest, " Cho phép chạy thử (pretest)"),
    h("label", { class: "checkbox-row" }, showScore, " Hiện điểm cuối ngay sau khi nộp"),
    msg,
    h("div", { class: "form-actions" }, submit,
      h("button", { type: "button", class: "btn btn-ghost", on: { click: () => { formHost.classList.add("hidden"); formHost.replaceChildren(); } } }, "Hủy")));
    formHost.replaceChildren(form);
  }

  document.getElementById("ce-new").addEventListener("click", openForm);
  loadList();
})();
