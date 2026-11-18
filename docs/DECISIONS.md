# Sổ quyết định và contract

> Source behavior không tự chứng minh Owner đã duyệt thiết kế hoặc rationale. Bảng 1 ghi các yêu cầu Owner đã xác nhận; bảng 2 ghi contract hiện thấy trong source nhưng không gán approval.

## 1. Owner-approved decisions / requirements

| ID | Quyết định | Evidence / ranh giới | Rationale đã xác minh | Status |
|---|---|---|---|---|
| D-01 | Paper mới là entity độc lập, có Paper ID/content/status/revision; không tạo nested version history hoặc `current_version_id`. | Owner-approved Phase 1 architecture, được lặp lại trong Phase 2 integration instructions. | Paper content tách khỏi Exam distribution theo chủ trương Owner. | Baseline được duyệt |
| D-02 | Published Save Changes sửa Paper được chọn tại chỗ; Save Draft từ Published tạo Paper Draft mới. Draft được lưu zero/incomplete questions; Publish và Published Save Changes yêu cầu selected count bằng chính xác `question_limit`. | Paper architecture và focused bug-fix requests. | Giữ identity; phân biệt draft work-in-progress với publication validation. | Contract được duyệt |
| D-03 | Giữ đọc legacy Paper/version references; không suy ra version ID và không migrate/rewrite lịch sử nếu không có approval riêng. | Paper/Exam compatibility instructions. | Bảo toàn Exam/release/submission history như yêu cầu Owner. | Constraint được duyệt |
| D-04 | Exam chọn Paper và giữ Common/Random semantics, persisted per-Student assignment, release snapshot và grading/history. Không redesign Exam Distribution khi chỉ sửa Paper. | Phase 2 integration/snapshot instructions. | Bảo toàn allocation và historical records được yêu cầu trực tiếp. | Contract được duyệt |
| D-05 | Exam Publish khác Teacher Start; Student Start là bước server-authorized riêng. Draft và Published-not-Started được sửa trước activity; Started/Ended bị khóa. | Owner lifecycle clarification và Issue 04 correction. | Student chỉ bắt đầu sau Teacher action; không sửa history khi đã có activity. | Lifecycle được duyệt |
| D-06 | Practice và Official Exam là hai execution context. Practice eligibility dùng published + `practice_enabled` + `practice_revision`; Practice Run visible-only, không phụ thuộc Paper/Official Assignment/Submit. Official eligibility không dựa vào `practice_enabled`. | Owner-approved integration invariants. | Ranh giới Practice/official được yêu cầu tường minh. | Boundary được duyệt |
| D-07 | Không destructive migrate hoặc overwrite runtime data/historical references nếu chưa có authorization cụ thể. | Controlled merge and migration restrictions from Owner. | Dữ liệu có liên kết assignments, submissions và scores. | Safety constraint được duyệt |

## 2. Source contracts — approval status unknown

| Quan sát | Evidence | Constraint kỹ thuật |
|---|---|---|
| JSON/JSONL là persistence chính; atomic replacement và process-local RLock. | `app/storage.py` | Không suy ra multi-file atomicity hoặc multi-process safety. |
| Question modes là Java Reflection, Java STDIO, Python STDIO; backend validates config. | `app/questions.py::_validate_question()` | Giữ execution schema và import compatibility. |
| Runner interface hỗ trợ `visible_only`, `workspace_parent`. | `app/code_runner.py::run_stdio()`, `app/code_exams.py::execute_question()` | Caller Practice/Official Exam phải cùng tương thích. |
| Student heartbeat hiện gọi telemetry; Monitor trả session snapshot. | `static/js/student.js`, `app/main.py::monitoring_snapshot()` | Presence khác behavioral monitoring; snapshot khác event history. |
| Server bind default `0.0.0.0:8080`, dùng ThreadingHTTPServer; Runner dùng Windows Job Objects. | `app/config.py`, `app/main.py`, `app/windows_job.py` | Implementation profile, không tự chứng minh dài hạn là architecture đã được duyệt. |

## 3. Đề xuất chưa được duyệt

Exam-only monitoring, multiple-tab precheck/dialog, fullscreen khi vào Exam và persistent monitoring events đang được xem xét. Chúng không phải quyết định được duyệt và chưa triển khai. Xem [Telemetry Audit](TELEMETRY_ARCHITECTURE_AUDIT.md).

Không coi public hosting, nhiều server process, Docker, SQLite migration hoặc lifecycle mới là scope được duyệt chỉ vì có thể xuất hiện trong tài liệu cũ/roadmap.

## 4. Khi có xung đột

Nếu implementation khác D-01—D-07, ghi discrepancy và xin Owner xác nhận trước khi đổi semantics. Nếu một behavior chỉ thấy trong source, giữ ở bảng 2 cho tới khi có approval evidence.
