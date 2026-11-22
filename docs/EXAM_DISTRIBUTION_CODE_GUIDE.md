# Hướng dẫn đọc mã Exam Distribution

Tài liệu này mô tả luồng trong source tree được rà soát ngày 2026-11-22; các tên hàm, endpoint và cấu trúc lưu trữ được giữ nguyên bằng tiếng Anh để tìm trong VS Code. Exam distribution ở đây là luồng Exam record trong `general_exams.py`; các endpoint distribution cũ trong `app/exams.py` vẫn được giữ để tương thích. For current API contracts, see [Code Exam API](CODE_EXAM_API.md).

## A. Tổng quan kiến trúc

| Thành phần | Vai trò trong mã hiện tại | Dữ liệu chính |
|---|---|---|
| Question Bank | Nguồn câu hỏi, trạng thái phát hành, grading specification và metadata. | `questions.json`, key là Question ID. |
| Paper | Danh sách có thứ tự các câu hỏi code, kèm `question_limit` và filters. Schema v2 là entity độc lập, không có nested version history; legacy schema v1 giữ `draft` và `versions`. | `papers.json`. |
| Exam | Cấu hình vận hành: tiêu đề, participants, thời lượng, chính sách nộp bài và một item loại code hoặc ZIP. | `exams.json`. |
| Release | Bản Exam được publish. Ghi `release_id`, Paper pool, snapshot code exam và lựa chọn Paper cho từng Student. Publish chưa bắt đầu giờ làm bài. | `exams.json` (`release`). |
| Assignment | Bản ghi cho Student được gán vào release, gồm file và/hoặc `paper_id`, legacy `paper_version_id`, `code_exam_id`, trạng thái và thời gian. | `assignments.json`, key Student ID. |
| Snapshot | Bản sao câu hỏi có thứ tự dùng trong một code exam release. Nguồn Paper được chụp vào `paper_snapshot`; release có snapshot code exam riêng cho từng Paper trong pool. | `code_exams.json`. |
| Submission | Mã nguồn, câu hỏi, release, lượt nộp và kết quả grading. | `code_submissions.json`; ZIP/file submission nằm trong `submissions.json`. |
| Grading / Regrading | So sánh output/checks với grading specification; regrade Paper release dùng câu hỏi snapshot của release. | `app/code_exams.py`, kết quả lưu trong `code_submissions.json`. |

Paper chọn nội dung; Exam cấu hình và phát nội dung; Release cố định lựa chọn cho một lần phát; Assignment nối Student với release; Snapshot giữ specification được dùng khi làm bài và chấm. Random Paper trong Exam khác với thao tác chọn ngẫu nhiên câu hỏi trong Paper Builder.

## B. Các luồng thực thi

### 1. Teacher tạo Exam và chọn Paper

1. Trang Exam gọi `initList()` / `initDetail()` trong `static/js/exams.js`. Màn hình tải Exam records, accounts, Questions, Papers và files qua các GET request.
2. `fromExam()` khôi phục cấu hình đang lưu vào form; `toPayload()` biến form thành `items` và `config`.
3. Item code có `distribution: { mode, paper_versions }`. Paper độc lập được gửi dưới dạng `{paper_id}`; Paper legacy phải gửi `{paper_id, paper_version_id}`.
4. Tạo mới gửi `POST /api/admin/exam-records`; `main.Handler.do_POST()` gọi `general_exams.create_exam()`, rồi `_normalize()` và `_normalize_items()` xác thực dữ liệu trước khi ghi `exams.json`.
5. Paper Builder riêng tải `GET /api/admin/questions` và `GET /api/admin/papers`; tạo Paper schema-v2 dùng `POST /api/admin/papers/independent` (POST `/api/admin/papers` remains the legacy schema-v1 creation route), sửa dùng `PUT /api/admin/papers/{paper_id}`. `app/papers.py` lưu danh sách câu hỏi theo ID trong current Paper; publishing validates exact `question_limit`. The Exam release stores its immutable question snapshots in release-scoped Code Exam records, not in a nested Paper version list.

Nguồn: `static/js/exams.js:98, 165, 186, 236, 752`; `app/main.py:348-380, 515-549, 631-642`; `app/general_exams.py:166, 217, 249, 716`; `app/papers.py:172, 257, 280, 362, 462, 495, 635`.

### 2. Common và Random Paper Distribution

`_normalize_code_item()` chấp nhận `common` hoặc `random`, yêu cầu Paper references không rỗng và không trùng; `common` yêu cầu chính xác một reference. `_check_code_papers()` resolve từng ref và yêu cầu Paper Published.

Khi publish Exam, `_build_release()` tạo một code-exam snapshot cho mỗi Paper trong pool. Với `common`, tất cả Student được ghi cùng một ref. Với `random`, `_choose_random_paper()` chọn một ref độc lập cho mỗi Student bằng `random.SystemRandom().choice`. Quyết định được lưu lại trong `release.paper_assignments`, cùng `paper_pool` và `paper_distribution_summary`; việc truy cập sau đó dùng lựa chọn đã lưu, không bốc lại.

ZIP distribution là luồng khác: `app/exams.py:71` `compute_assignments()` hỗ trợ `selected`, `parity`, `custom`, và random theo IP subnet; không dùng Paper pool. Không diễn giải `random` ZIP như Random Paper.

Nguồn: `app/general_exams.py:166-215, 812-832, 834-970`; `app/exams.py:36-40, 71-147`.

### 3. Teacher publish, sửa Paper Selection, và Start

- `POST /api/admin/exam-records/{id}/publish` gọi `publish_exam()`. Chỉ Draft được publish. `_build_release()` validate và tạo snapshots; Exam status chuyển thành `distributed`. Student View có thể liệt kê Exam Card nhưng việc này không kích hoạt bài làm.
- `POST /api/admin/exam-records/{id}/update` gọi `update_exam()`. `expected_revision` là bắt buộc; stale revision trả 409. Status `draft` và `distributed` được sửa. Với Exam distributed, hàm dựng release mới và đồng bộ các assignment chuẩn bị trước Start. Student activity chặn thay đổi; `started` và `ended` không được sửa.
- Nút Start của Teacher gọi `POST /api/admin/exam-records/{id}/start`; `start_exam()` áp dụng release map vào assignments và chuyển Exam sang `started`. Đây là sự kiện bắt đầu do Teacher chủ động, không có lịch tự chạy.
- `revoke_exam()` đưa một Exam distributed chưa bắt đầu về Draft; release/applied state liên quan được dọn theo helper hiện tại.

Nguồn: `static/js/exams.js:118, 320, 342, 358, 520, 665-680`; `app/main.py:631-642`; `app/general_exams.py:307, 342, 999, 1036, 1063, 1081, 1160`.

### 4. Student nhìn thấy Exam và bắt đầu làm

`GET /api/student/status` gọi `published_for_students()` và trả `published_exams` với `id`, `title`, `tag` cho Exam status `distributed`, lọc participants nếu được cấu hình. `static/js/student.js` tải status và refresh giao diện khi danh sách publish hoặc Exam state đổi. Card hiển thị thông tin này không phải quyền bắt đầu làm.

Teacher Start gọi `_apply_release()` và ghi `settings.exam_state="started"`, `exam_released=true`, `exam_release_id`; đồng thời materialize assignments có `release_id`, `exam_file` và/hoặc Paper/code-exam refs. Sau đó Student gọi `POST /api/student/start`. `app/exams.py:start_exam()` chỉ chấp nhận khi trạng thái toàn cục đã `started`, Student có assignment cùng release, và mật khẩu (nếu bật) đúng; hàm này ghi `started_at`, `ends_at`, `in_progress` cho assignment đó.

ZIP access dùng `GET /api/student/exam`, kiểm tra release, Student `started_at`, deadline và đường dẫn file. Code access dùng `GET /api/student/code-exam`, kiểm tra assignment và code exam khớp `release_id`, trạng thái và Paper reference. Trước khi có Student start, hai đường truy cập nội dung này bị từ chối.

Nguồn: `app/main.py:300, 403-420, 820-825`; `static/js/student.js:40, 86-104`; `app/general_exams.py:682, 1081-1158`; `app/exams.py:172-197`; `app/code_exams.py:393-432, 471-558`.

### 5. Student pretest, submit và backend grading

`static/js/student-code.js` tải code exam, gửi pretest bằng `POST /api/student/code/run` và submit bằng `POST /api/student/code/submit` hoặc bulk `POST /api/student/code/submit-exam`.

`run_pretest()` và `submit_code()` lấy Student context qua `_active_context()`, rồi lấy câu hỏi qua `_question_snapshot(exam, question_id)`. Với Paper release, `get_code_exam()` trả câu hỏi từ `paper_snapshot`; code execution không lấy bản Question mới từ Question Bank. `_reserve_submission()` lưu `exam_id`, `release_id`, `question_id`, `snapshot_version`, source code/hash và attempt. `execute_question()` chạy runner; `_complete_submission()` kiểm tra runner verdict/points với grader server-side (`grade_stdio` / `grade_reflection`) rồi ghi kết quả. Bulk submit gọi cùng snapshot cho từng câu.

Nguồn: `app/main.py:826-846`; `static/js/student-code.js:394, 595, 654, 691, 725`; `app/code_exams.py:309, 393, 433, 678, 832, 875, 925, 1166, 1199`.

### 6. Teacher results và regrade

Teacher xem main Exam results qua `GET /api/admin/exam-results` and detail at `/api/admin/exam-results/{exam_id}`. Single and per-Student regrade use the matching `/regrade` routes. Legacy standalone code results remain at `/api/admin/code-results`. Paper-release regrade uses its frozen release snapshot; `use_latest_spec=true` is rejected for Paper releases. ZIP uploads do not pass through the code grader.

Các ZIP upload được xử lý qua `POST /api/student/submit` và `accept_submission()`; chúng không đi qua code grader này. Admin list general submissions dùng `/api/admin/submissions`. Không mô tả ZIP như có auto-grading.

Nguồn: `app/main.py:334-346, 394-402, 608-624, 841-849`; `static/js/code-results.js:145-245`; `app/code_exams.py:1369, 1443, 1503`.

## C. Bản đồ điều hướng code

| File và vị trí | Hàm/điểm vào | Trách nhiệm / liên kết |
|---|---|---|
| `app/main.py:284` | `Handler.do_GET()` | GET cho Paper, Exam, Student status, ZIP exam và code exam. |
| `app/main.py:474` | `Handler.do_POST()` | POST cho CRUD/lifecycle Exam, publish Paper, Student Start/submit và regrade. |
| `app/general_exams.py:166` | `_normalize_code_item()` | Chuẩn hóa legacy question IDs hoặc Paper distribution config. |
| `app/general_exams.py:716` | `create_exam()` | Tạo Draft Exam record. |
| `app/general_exams.py:743` | `_validate_publishable()` | Kiểm tra Exam configuration trước phát. |
| `app/general_exams.py:812` | `_check_code_papers()` | Resolve refs và kiểm tra Published eligibility. |
| `app/general_exams.py:834` | `_build_release()` | Tạo release plan, snapshot Paper và lựa chọn Student. |
| `app/general_exams.py:999` | `update_exam()` | Revision guard và sửa Draft/Published-not-started. |
| `app/general_exams.py:1081` | `_apply_release()` | Ghi assignments/settings khi Teacher Start. |
| `app/papers.py:362` | `resolve_paper_reference()` | Tách explicit legacy pair khỏi Paper độc lập. |
| `app/code_exams.py:179` | `create_paper_code_exam()` | Tạo code-exam release snapshot từ ref. |
| `app/code_exams.py:309` | `get_code_exam()` | Load question snapshots, legacy fallback theo version pair. |
| `app/code_exams.py:471` | `get_student_code_exam()` | Student-facing projection và checks. |
| `app/code_exams.py:925` | `_complete_submission()` | Validate kết quả grading và lưu submission. |
| `app/code_exams.py:1503` | `regrade_submission()` | Regrade submission từ snapshot đã chọn. |
| `app/storage.py:83-121` | `atomic_write()`, `read_json()`, `transaction()`, `update_json()` | JSON I/O, atomic file replacement, process-local RLock và audit append. |
| `static/js/exams.js:186-243` | `fromExam()`, `toPayload()` | Map Exam record ↔ editor form/payload. |
| `static/js/exams.js:320-378` | `persist()`, autosave, publish validation | Save/revision and client validation. |
| `static/js/exams.js:520-558` | `codeSection()` | Mode selector, Paper pool and selection UI. |
| `static/js/code-papers.js:230-255, 384-439, 664-790` | `openEditor()`, validation/autosave, save/publish | Paper editor to Paper APIs. |

### Navigation map

| User Action | Frontend | API | Backend | Storage |
|---|---|---|---|---|
| Create Exam | `exams.js` `persist()` | `POST /api/admin/exam-records` | `create_exam()` | `exams.json` |
| Choose Paper(s) | `exams.js` `codeSection()` | Included in Exam create/update payload | `_normalize_code_item()` | `exams.json` |
| Publish Exam | `runAction()` / detail action | `POST .../{id}/publish` | `publish_exam()` → `_build_release()` | `exams.json`, `code_exams.json` |
| Edit selection pre-Start | `fromExam()` / `codeSection()` | `POST .../{id}/update` | `update_exam()` and sync helpers | Exam/release/assignments/code snapshots |
| Teacher Start | Exam card action | `POST .../{id}/start` | `start_exam()` → `_apply_release()` | `settings.json`, `assignments.json`, `exams.json`, `code_exams.json` |
| Student open code exam | `student-code.js` | `GET /api/student/code-exam` | `get_student_code_exam()` | assignment + release code snapshot |
| Submit / Regrade | `student-code.js` / `code-results.js` | student submit APIs / admin regrade APIs | `submit_code*()` / `regrade_submission()` | `code_submissions.json` |
