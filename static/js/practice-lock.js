(function (global) {
  global.createPracticeLock = function ({ request, root, dialog }) {
    let state = "checking";
    let inFlight = null;
    let recovered = false;
    let decisionEpoch = 0;
    const accessStatus = document.getElementById("practice-access-status");
    const message = document.getElementById("practice-lock-message");
    const heading = document.getElementById("practice-lock-title");
    const render = () => {
      const blocked = state !== "allowed";
      root.inert = blocked;
      root.hidden = blocked;
      if (accessStatus) accessStatus.hidden = state !== "checking";
      if (state === "checking") return;
      if (!blocked) { if (dialog.open) dialog.close(); return; }
      heading.textContent = state === "locked" ? "Practice tạm thời bị khóa" : "Đang xác minh quyền luyện tập";
      message.textContent = state === "locked"
        ? "Bạn đang tham gia một kỳ thi chính thức. Chức năng luyện tập sẽ được mở lại sau khi kỳ thi kết thúc. Bài làm của bạn vẫn được giữ nguyên."
        : state === "unauthenticated"
          ? "Phiên đăng nhập không còn hợp lệ. Vui lòng quay về trang thi để đăng nhập lại."
          : state === "error"
            ? "Chưa thể xác minh trạng thái kỳ thi. Bài làm vẫn được giữ nguyên; đang chờ kết nối để kiểm tra lại."
            : "Vui lòng chờ kiểm tra trạng thái kỳ thi.";
      if (!dialog.open) dialog.showModal();
    };
    const check = () => {
      if (inFlight) return inFlight;
      const requestEpoch = decisionEpoch;
      inFlight = (async () => {
        try {
          const response = await request("/api/student/status");
          if (requestEpoch !== decisionEpoch) return state === "allowed";
          if (typeof response?.active_exam_attempt !== "boolean") throw new Error("Invalid Student status");
          if (!response.active_exam_attempt && ["locked", "error", "unauthenticated"].includes(state)) recovered = true;
          state = response.active_exam_attempt ? "locked" : "allowed";
        } catch (error) {
          // A failed request never proves that Practice is available.
          if (state !== "locked") state = error.status === 401 ? "unauthenticated" : "error";
        } finally { render(); inFlight = null; }
        return state === "allowed";
      })();
      return inFlight;
    };
    dialog.addEventListener("cancel", (event) => event.preventDefault());
    dialog.addEventListener("close", () => { if (state !== "allowed") render(); });
    render();
    return {
      check,
      needsRecovery: () => recovered,
      acknowledgeRecovery() { recovered = false; },
      request: async (url, options) => {
        if (state === "checking") await check();
        if (state !== "allowed") {
          const error = new Error("Practice tạm thời chưa khả dụng. Bài làm vẫn được giữ nguyên.");
          error.code = "PRACTICE_LOCKED";
          throw error;
        }
        try { return await request(url, options); }
        catch (error) {
          if (error.code === "PRACTICE_LOCKED") { decisionEpoch++; state = "locked"; render(); }
          else if (error.status === 401) { decisionEpoch++; state = "unauthenticated"; render(); }
          throw error;
        }
      },
    };
  };
})(window);
