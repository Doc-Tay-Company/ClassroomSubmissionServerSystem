# Bài học kỹ thuật

Các mục này gắn với sự cố hoặc contract đã xác minh; chúng là hướng dẫn review, không phải requirement mới.

## EL-01 — Giữ nguyên nested grading JSON

**Ví dụ:** R03 Comparable có 3 `instances`, hai `comparisons` và `expected_order: [1,2,0]`. Nếu editor biến nested spec thành default cases rồi tái tạo, instance identity/index có thể đổi và Reflection validator báo lỗi cấu hình dù sample solution đúng.

**Thực hành:** Giữ canonical source hoặc transformation đảo ngược được; so sánh nested arrays/order qua import → editor → payload → Runner. Đừng flatten JSON chỉ vì UI dùng representation khác.

**Evidence:** `static/js/questions.js::toEditorQuestion()` giữ `__editor_comparable_source`; payload conversion khôi phục arrays khi cases chưa bị sửa. Regression guards ở `tests/test_question_import_comparable.js`, `tests/test_question_concurrency.py`. Owner báo đã xác nhận browser; test không chạy lại trong task tài liệu.

## EL-02 — Phân biệt lỗi cấu hình grader với kết quả Student

Validate Question/Runner specification trước execution. INVALID_REQUEST, invalid check shape hoặc protocol/infrastructure failure không phải WA/0 điểm của Student. Giữ loại lỗi riêng trong response và grading. Tham khảo `app/questions.py::_validate_question()`, `app/java_runner.py::_validate_reflection_request()`, `app/code_exams.py::execute_question()`.

## EL-03 — Backend là ranh giới validation

Editor clamp/normalize chỉ hỗ trợ UX. API payload vẫn phải được backend validate về type, language/mode, filename, grading config, Paper/Exam refs và revision. Test gọi service/route với malformed payload và xác nhận không có partial write.

## EL-04 — Giữ metadata ownership rõ ràng

Request-only expected revisions được tiêu thụ ở mutation boundary, không trở thành domain fields. Import không được tự xác lập server validation/lifecycle metadata nếu contract không cho phép. Server khởi tạo ID/revision/status/validation theo service ownership.

## EL-05 — Không trộn Practice với Official Exam

Cả hai có thể dùng chung Runner nhưng khác eligibility, authorization, snapshot, persistence và scoring. Practice visible-only/progress; official access cần release assignment và Student Start, Submit/regrade dùng official contracts. Regression test từng flow riêng.

## EL-06 — Runtime JSON là vận hành, không phải source code

Khi merge branch, giữ riêng code/schema và data records. Inventory IDs/counts, so sánh cấu trúc và preserve submissions/assignments/progress/scores. Không chọn nguyên data “ours”/“theirs”, không migrate nếu chưa có phê duyệt.

## EL-07 — Trace full API contract trước thay đổi

Đi từ frontend event → method/path/payload → route/auth → service/validation → storage → response/render. Khi error, giữ input/local recovery; khi stale revision/invalid input, assert stored data không đổi. Đừng chỉ kiểm tra UI state.

## EL-08 — Presence không phải behavioral monitoring

Authenticated status/API requests refresh session presence independently of telemetry. Current telemetry snapshots and persistent events are accepted only for an active Student/release attempt; event history is stored and paged separately from the current snapshot. Client-reported focus, visibility, tab count, and fullscreen transitions remain technical signals, not independently verified evidence. Preserve the presence/attempt boundary and avoid interpreting event history as an automatic misconduct finding.

## EL-09 — Storage helper không thay thế analysis concurrency

Atomic replace là per-file; process-local RLock không phải multi-process lock hoặc multi-file transaction. Xác minh mutation có bao trọn read/check/write trong transaction thực hay không, rồi test interleaving trên isolated data.

## EL-10 — Tài liệu cũ phải được đối chiếu source

Sau integration, kiểm tra lại routes, module, lifecycle và test inventory. Ví dụ tài liệu trước từng nói Practice Run chưa có, trong khi source hiện có `run_practice()` và `POST /api/student/practice/run`. Tách Owner-approved decisions khỏi source observations; ghi trạng thái test “đã chạy/chưa chạy”.

## Checklist review

- Có fixture canary cho nested arrays, hidden checks và server-owned metadata.
- Test import → editor → serialize → validate, không chỉ JSON.parse.
- Tách visible-only Practice khỏi full official grading.
- Kiểm tra historical release/snapshot trước đổi Paper hoặc Exam selection.
- Ghi rõ runtime/browser verification gaps; không quảng bá proposal thành tính năng.
