# Báo cáo bàn giao tiến độ — Exam và Paper

**Ngày lập:** 2026-11-17  
**Repository:** `D:\JSD\ClassroomSubmissionServerSystem`  
**Branch:** `feature/JudgeEngine`  
**Commit nền hiện tại:** `3e756b6 fix lỗi mất hiễn thị ở trang quản lý kỳ thu`

## 1. Project Overview

Dự án quản lý Question Bank, Paper, Exam lập trình, phát hành/assignment, bài nộp và chấm điểm. Phạm vi gần đây tập trung vào Paper Builder và Exam Code/ZIP, gồm tương thích Paper cũ/mới, lựa chọn câu hỏi, vòng đời Draft/Published, phát hành Exam và bảo toàn nội dung lịch sử.

Phạm vi Task 02 hiện tại là hiển thị/đọc Paper tương thích, giữ Published content bất biến và tạo bản Paper độc lập từ Published Paper. Không có migration hoặc ghi lại dữ liệu lịch sử.

## 2. Completed Phases

### Công việc trong checkout hiện tại

| Giai đoạn | Kết quả đã kiểm tra |
|---|---|
| Task 01 — Audit Paper/Exam | Có các tài liệu audit trong `docs/ai copy/`, nhưng chúng ghi snapshot cũ `f00a583`; chưa có bản audit Task 01 được xác nhận theo HEAD `3e756b6`. Không dùng kết luận cũ thay cho source hiện tại. |
| Task 02 — Tương thích Paper legacy/current | Đã sửa và kiểm thử ở checkout hiện tại: list summary có giá trị chung cho schema 2; Published Open dùng Published preview; bỏ Draft Preview UI; Published schema 2 không thể sửa tại chỗ và hành động `Chỉnh sửa bản mới` tạo Paper Draft độc lập; giữ Exam reference tới các Published Version cũ. |
| Handover này | Tạo mới `docs/ai/PROGRESS_HANDOVER.md`; không sửa source trong bước lập báo cáo. |

### Tài liệu tiến độ cũ

`docs/ai copy/PROGRESS_HANDOVER.md` và `docs/ai copy/ACCEPTANCE_REPORT.md` ghi lại Prompt 00–11 của một snapshot cũ tại `f00a5835`. Nội dung này hữu ích làm lịch sử nhưng có thể lỗi thời. Ví dụ, báo cáo cũ ghi Paper API có 13 test và distribution có 6 test; tại checkout hiện tại các con số đã là 23 và 16. `docs/ai copy/` đang là untracked content; phải giữ nguyên.

Các file canonical `docs/ai/PROJECT_CONTEXT.md`, `docs/ai/IMPLEMENTATION_RULES.md`, `docs/ai/EXAM_PAPER_TASK_SPEC.md` không có trong checkout. `AGENTS.md` và `CODEX_PROJECT_CONTEXT_AND_RULES.md` ở root đã được đọc đầy đủ. Các bản `IMPLEMENTATION_RULES.md`, `IMPLEMENTATION_CONTEXT.md`, `ACCEPTANCE_REPORT.md`, `PROGRESS_HANDOVER.md` trong `docs/ai copy/` đã được đọc, nhưng không được xem như tài liệu canonical đã thiếu.

## 3. Current Implementation

### Product code trong diff hiện tại

- `app/papers.py`
  - `list_papers()` trả các trường list summary tương thích schema 2: `has_draft=False`, `current_version_id=None`, `version_count=0`; đây là projection khi đọc, không ghi chuẩn hóa vào storage.
  - `update_paper()` từ chối sửa Published Paper schema 2 bằng `409 PAPER_PUBLISHED_IMMUTABLE`.
- `static/js/code-papers.js`
  - Paper actions dựa trên status và summary; Published Open gọi preview cho cả hai schema.
  - Published detail cho phép `Chỉnh sửa bản mới`; Draft Preview button và handler đã bị gỡ. Published Paper preview vẫn dùng.
- Không sửa `app/general_exams.py`, Exam UI, Paper table layout hoặc Tag/Filter logic trong Task 02.

### Regression tests trong diff hiện tại

- `tests/test_papers.py`: kiểm tra summary legacy/current, field legacy tùy chọn bị thiếu, Published schema 2 bất biến và dữ liệu storage không đổi khi list.
- `tests/test_paper_builder_filters.js`: kiểm tra hành động theo trạng thái, không có Draft Preview UI, Published preview và tạo Paper độc lập.
- `tests/test_paper_distribution.py`: kiểm tra Exam cũ giữ Paper Version cũ và Exam mới dùng version mới; test độc lập Paper schema 2 dùng Paper ID mới thay vì sửa Paper đã phát hành.

### Files thay đổi

Theo Git hiện tại:

- Modified: `app/papers.py`, `static/js/code-papers.js`, `tests/test_papers.py`, `tests/test_paper_builder_filters.js`, `tests/test_paper_distribution.py`.
- Untracked đã có trước bước handover: `docs/ai copy/` (không chỉnh sửa).
- File mới bởi tác vụ handover: `docs/ai/PROGRESS_HANDOVER.md`.
- Không tạo commit hoặc push.

## 4. Architecture & Data Model

- Runtime source xác nhận Python `ThreadingHTTPServer`, Jinja2, HTML/CSS/Vanilla JS, JSON/JSONL filesystem persistence.
- Paper legacy mặc định schema 1 lưu `draft`, `versions`, `current_version_id`; Published versions là snapshot riêng. Một số draft cũ thiếu `question_limit` và `question_filters`.
- Paper schema 2 có `schema_version: 2`, `status`, `question_ids`, snapshot `questions`, `revision`; không lưu `versions` hoặc `current_version_id`. List adapter không bịa version ID.
- Paper detail/list/preview đi qua `/api/admin/papers`; preview Published mặc định và API preview Draft `?draft=1` là các đường riêng. Task 02 bỏ Draft Preview khỏi UI; endpoint backend vẫn tồn tại.
- Paper legacy có thể giữ Published Version và Draft hiện tại cùng Paper ID. `Chỉnh sửa bản mới` từ Published dùng thao tác tạo Paper độc lập; nguồn và các Exam/Release/Assignment hiện tại không bị chuyển sang ID mới.
- Exam được kiểm tra ở backend để giới hạn item theo loại Code hoặc ZIP qua `app/general_exams.py::_normalize_items()`.
- Code Paper release/assignment lưu tham chiếu Paper/version và snapshot. ZIP assignment hiện lưu filename; route student mở file từ thư mục Exam hiện hành.

## 5. Testing Results

### Đã chạy cho Task 02 hiện tại

- `node tests/test_paper_builder_filters.js` — PASS; các regression simulated-DOM đều đạt.
- `node --check static/js/code-papers.js` — PASS.
- `node --check tests/test_paper_builder_filters.js` — PASS.
- `python -m py_compile app/papers.py tests/test_papers.py tests/test_paper_distribution.py` — PASS.
- `python -m unittest tests.test_papers` — 23 tests, OK.
- `python -m unittest tests.test_paper_distribution` — 16 tests, OK.
- `git diff --check` — PASS.
- Search `Preview Draft|previewSavedDraft|draft=1` trong `static/js/code-papers.js` — không còn Draft Preview UI/handler/call.

Python test modules được chạy riêng. Chạy cả hai trong cùng process đã gây xung đột vì test modules gán `storage.DATA_DIR` ở cấp module; lần chạy chung thất bại. Một số lần chạy sandbox ban đầu cũng gặp `PermissionError` khi tạo temp fixture. Các lần chạy cô lập sau đó được thực hiện riêng và đạt. Không có kiểm tra hash runtime JSON trong lượt này; không khẳng định kiểm chứng hash.

Tài liệu acceptance cũ ghi thêm các test Exam selector, ZIP-only và các kết quả Prompt 03–11 ở snapshot trước. Những kết quả đó không được chạy lại trong Task 02 này.

## 6. Known Issues và sai khác

1. **Autosave không khớp quy tắc context:** root context yêu cầu không autosave và yêu cầu Save chủ động; source hiện tại `static/js/code-papers.js::scheduleAutosave()` vẫn gọi `setTimeout` để tự persist một số thay đổi. Task 02 không giải quyết vì ngoài phạm vi. Cần prompt/approval riêng trước khi sửa.
2. **Tài liệu canonical thiếu:** `AGENTS.md` trỏ đến `docs/ai/PROJECT_CONTEXT.md`, `IMPLEMENTATION_RULES.md`, `EXAM_PAPER_TASK_SPEC.md`; hiện không tồn tại. Thư mục `docs/ai copy/` có bản sao/tài liệu tiến độ, nhưng có snapshot khác. Không tự đổi tên, di chuyển hoặc coi bản sao là canonical.
3. **Task 01 chưa được tái xác minh theo HEAD:** audit cũ chỉ gắn với commit `f00a583`; cần audit source hiện tại nếu muốn dựa vào từng finding cũ.
4. **Không chạy full suite:** các fixture Python dùng storage global và từng gây side effect khi chạy chung; chưa có cơ chế cô lập toàn suite.
5. **Chưa xác minh browser/LAN/restart:** UI tests dùng simulated DOM; chưa chạy browser thật, server restart process riêng hoặc LAN.
6. **ZIP lịch sử:** assignment lưu filename và route đọc bytes hiện tại từ file đó. Nếu file bị thay hoặc xóa, nội dung cũ không được bảo toàn bằng byte snapshot. Acceptance report cũ đánh dấu không đạt tiêu chí snapshot ZIP.
7. **Các luồng chưa chạy lại:** Judge Engine/runners, hidden tests, pretest, Practice Mode, auth regression đầy đủ, ZIP assignment/retrieval matrix.
8. **Schema 2 không có version history:** list trả `version_count=0` và không có `current_version_id`; đây là đặc điểm dữ liệu hiện tại, không phải mất version do adapter.

## 7. Pending Tasks (ưu tiên)

1. Khôi phục/nhận đúng các tài liệu canonical bị thiếu, nhất là Task Spec, hoặc project owner xác nhận rõ nguồn thay thế.
2. Xin/nhận prompt cụ thể cho giai đoạn kế tiếp. Source có sai khác autosave quan trọng cần được ưu tiên quyết định; chưa tự ý sửa.
3. Chạy browser-level Paper lifecycle sau khi có prompt phù hợp; kiểm tra Published preview và independent-copy flow trên app thật.
4. Thiết kế cách cô lập storage fixtures rồi chạy test suite rộng hơn; xác minh hash runtime data trước/sau.
5. Quyết định yêu cầu lưu snapshot bytes cho ZIP; sau đó mới lập prompt triển khai và test mode/restart tương ứng.
6. Chạy riêng-process restart/assignment persistence và các regression Judge Engine/student workflows trước khi tuyên bố release acceptance.

## 8. Next Step chính xác

Không tìm thấy thư mục `prompts/` hoặc prompt phase có thể tiếp tục tự động. Vì vậy không thể chỉ định một prompt hiện hữu mà không suy đoán.

**Bước tiếp theo:** project owner cung cấp hoặc xác nhận prompt cho giai đoạn tiếp theo, đồng thời cung cấp/xác nhận các tài liệu canonical đang thiếu. Ưu tiên làm rõ xung đột autosave giữa context và source. Theo yêu cầu recovery mới nhất, Codex tiếp theo phải trình bày những gì đã xác minh, hoàn thành, còn thiếu, phase và kế hoạch, rồi chờ xác nhận trước khi chỉnh sửa source.

## 9. Important Constraints

- Trước mỗi task, đọc `AGENTS.md`, toàn bộ `CODEX_PROJECT_CONTEXT_AND_RULES.md`, kiểm tra Git; đọc các tài liệu phase canonical khi được cung cấp. Không thay thế file thiếu bằng README hoặc trí nhớ.
- Luôn kiểm tra source/branch/commit thực tế; tài liệu trong `docs/ai copy/` là untracked và lịch sử snapshot, không mặc định đúng với HEAD hiện tại.
- Bảo toàn Paper ID/nội dung/version, Exam, Release, Assignment, Submission và snapshot lịch sử. Không migration/reset/seed/cleanup dữ liệu runtime khi chưa được cho phép.
- Không sửa Exam management, Paper table, Tag/Filter hoặc kiến trúc ngoài prompt đã duyệt. Không đưa autosave/explicit Save change vào nếu chưa có prompt riêng.
- Không reset/clean/stash/discard, không checkout branch khác, không commit/push nếu chưa được yêu cầu.
- Không tuyên bố browser, LAN, restart, full-suite hoặc release acceptance nếu chưa chạy và kiểm chứng.
- Prompt Task 02 yêu cầu không commit/push; không được hiểu handover là ủy quyền triển khai thêm.
