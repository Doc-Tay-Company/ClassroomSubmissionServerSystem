# Exam Monitoring: scope, implementation status, and acceptance plan

> **Reconciled against source on 2026-11-22.** All four functional scopes described below are present in the current source. This document remains the approved behavior/acceptance reference; it is not an instruction to restart implementation or evidence of completed browser acceptance, production deployment, or passing tests in this checkout.

## 1. Mục đích, phạm vi và thẩm quyền

Đây là tài liệu tham chiếu cho scope và acceptance của Exam Monitoring. Implementation status ở đầu tài liệu được đối chiếu từ source; mỗi phase chỉ được coi là nghiệm thu khi acceptance và regression phù hợp đã được thực hiện, ghi nhận.

Tài liệu không cho phép tự thay đổi runtime data, tạo commit, hay mở rộng phạm vi. Test chưa chạy/block phải được báo; không thể coi là pass. Browser signal là technical observation, không phải kết luận misconduct.

## Current source status

| Phase | Source evidence | Status in this checkout |
|---|---|---|
| 1 — Exam-aware telemetry | `app/exams.py::is_active_exam_attempt()`, `app/main.py` status/snapshot routes, `static/js/student.js` | Implemented: status polling remains available; snapshots are sent for active attempts. |
| 2 — Persistent event history and Teacher Monitoring | `app/exam_monitoring.py`, monitoring/event routes in `app/main.py`, `static/js/admin.js` | Implemented: per-Student/release events, counters, sequence paging, and incremental admin history. |
| 3 — Student Start precheck and fullscreen gate | `static/js/exam-entry.js`, `static/js/exam-telemetry.js`, Student Start/status backend | Implemented: multi-page precheck, fullscreen gate, and attempt-scoped events. |
| 4 — Practice lock and final integration | `app/practice.py`, Practice routes in `app/main.py`, `static/js/practice-lock.js` | Implemented: active-attempt Practice operations are blocked per Student. |

Relevant checked-in test suites include `tests/test_exam_monitoring.py`, `tests/test_exam_start_monitoring.py`, `tests/test_practice_lock.py`, `tests/test_exam_entry.js`, and `tests/test_practice_lock.js`. They were not run as part of this documentation update.

## 2. Tài liệu và cơ sở source

### Tài liệu tham chiếu

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — miền nghiệp vụ và ranh giới Practice / Official Exam.
- [ARCHITECTURE.md](ARCHITECTURE.md) — module, persistence và data flow.
- [DECISIONS.md](DECISIONS.md) — Owner decisions tách khỏi source observations.
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md) — telemetry, JSON concurrency và deployment limits.
- [ENGINEERING_LESSONS.md](ENGINEERING_LESSONS.md) — nested data, API compatibility, concurrency, presence/telemetry.
- [TELEMETRY_ARCHITECTURE_AUDIT.md](TELEMETRY_ARCHITECTURE_AUDIT.md) — historical pre-implementation investigation; do not use its old behavior claims as current.
- [README.md](README.md) — documentation index, project footprint, and current/historical document ownership.

### Source navigation đã xác nhận

| Trách nhiệm | Source reference | Ý nghĩa |
|---|---|---|
| HTTP routes/auth | app/main.py: Handler.do_GET(), do_POST(), do_DELETE(), _auth() | Student status/Start, telemetry, Monitor và Practice endpoints. |
| Presence/session | app/security.py: new_session(), get_session(), require_user(), logout_session() | Session và last_seen. |
| Student browser | static/js/student.js: updateTabs(), sendTelemetry(), heartbeat(), Start handler | Heartbeat, snapshot và Student Start hiện hành. |
| Student workspace shell | templates/student.html | Nút Start và scripts của Student shell. |
| Practice UI | static/js/student-practice.js; templates/practice.html | Catalog polling/visibility; Practice không nạp student.js. |
| Active code attempt | app/code_exams.py: _active_context(), get_student_code_exam() | Kiểm tra release/assignment/start/status/deadline/forced submit; không phải status API dùng chung cho mọi UI. |
| Teacher Monitoring | app/main.py: monitoring_snapshot(); static/js/admin.js: loadMonitor(), renderMonitor() | Snapshot và HTTP polling hiện hữu. |
| JSON storage | app/storage.py: atomic_write(), read_json(), write_json(), transaction(), update_json() | Atomic replace từng file và process-local lock. |
| Server | app/main.py: main() | ThreadingHTTPServer; cần bảo vệ concurrent read-modify-write. |
| Practice service | app/practice.py: is_practice_eligible(), run_practice(), active-run registry | Eligibility, Run/progress; Run đã accepted không được hủy bởi lock. |
| Exam lifecycle | app/exams.py: start_exam(), start_exam_session(), end_exam_session(); app/general_exams.py | Teacher Start và Student Start là các bước riêng; assignment/release là nguồn trạng thái. |

### Current behavior verified against source

- `POST /api/student/start` retains backend authorization for Teacher Start, assignment/release and optional password; the route records the tab precheck result for replay into monitoring history.
- `GET /api/student/status` returns `active_exam_attempt` based on the current assignment/release/deadline state, not `started_at` alone.
- `static/js/student.js` polls status every 10 seconds. It sends telemetry snapshots only while status reports an active attempt; authenticated requests continue to refresh session presence independently.
- `POST /api/student/telemetry` stores the current active-attempt snapshot in the session. `POST /api/student/telemetry/event` validates active attempt/release and appends deduplicated events to `exam_monitoring.json`.
- `monitoring_snapshot()` filters snapshots to the active assignment/release and exposes counters plus `latest_event_seq`; the admin UI polls every 5 seconds and pages event history incrementally.
- `exam-entry.js` implements the multi-page Start precheck and fullscreen gate. `practice-lock.js` and backend Practice checks block Practice operations for the Student with an active Official Exam attempt.
- `tab_count` estimates recent same-origin page instances from localStorage; it does not count every browser tab/window.
- Storage locking is process-local and JSON replacement is per-file; there is no cross-process lock or multi-file transaction.

The older detailed audit below is historical; current behavior should be checked against source. File/line coordinates in this plan are navigation hints and may drift.

## 3. Kiến trúc được duyệt và các feature deferred

### 3.1 Heartbeat và Behavioral Telemetry

- Session presence/heartbeat tiếp tục suốt authenticated Student session.
- Behavioral Telemetry chỉ bật sau Student Start thành công khi backend xác nhận active Official Exam attempt.
- Login, Teacher Start, chờ thi hoặc Practice không bật behavioral monitoring.
- Reload, reconnect, logout/reauth lấy lại monitoring state từ backend, không lấy localStorage làm nguồn sự thật.
- Attempt hết active thì dừng behavioral telemetry, không dừng presence.

### 3.2 Event History, counters và Teacher Monitoring

- Giữ current telemetry snapshot.
- Thêm persistent Event History theo Student Official Exam attempt, counters tích lũy và event sequence tăng đơn điệu.
- Window blur và document hidden là hai event độc lập, kể cả cùng xảy ra do một thao tác.
- Không tăng counter theo heartbeat, polling hay initialization; retry không ghi trùng.
- Teacher tiếp tục HTTP poll khoảng 5 giây. Monitor response có attempt identity, snapshot, counters và latest_event_seq.
- Lấy history mới khi sequence tăng; phục hồi missed poll, failed request và dashboard reload. Counter lịch sử không bị xóa khi trạng thái browser trở lại bình thường.
- Technical observation dùng cho Teacher review, không tự động kết luận misconduct.
- Không tự động retention/archive/xóa history trong initial implementation.

### 3.3 Student Start, precheck và Fullscreen

- Giữ backend Student Start authorization hiện tại.
- Chạy tab precheck hiện có trước Start; không đổi thuật toán.
- Nhiều tab: cảnh báo có Cancel/Continue. Cancel không gọi Start và không ghi event.
- Continue cho phép Start request. Initial multiple-tab event chỉ ghi sau successful Start; ưu tiên metadata trong Start request nếu compatibility/consistency được chứng minh.
- Sau Start và reload, active Exam không fullscreen hiển thị modal nổi bật và overlay khóa workspace.
- Agree request Fullscreen từ direct user interaction; chỉ mở khóa sau khi browser xác nhận.
- Refuse ghi fullscreen_refused; request failure ghi fullscreen_request_failed; giữ khóa và có nút quay lại request modal.
- Fullscreen exit khi attempt active ghi fullscreen_lost và khôi phục gate.
- F5 phục hồi từ backend, không reset progress/history và không tự tính fullscreen_lost.
- Không giả định có thể chặn Esc hoặc tự bật Fullscreen.

### 3.4 Practice Lock

- Chỉ Student có active Official Exam attempt sau Student Start bị khóa.
- Teacher Start đơn lẻ không khóa.
- Practice tabs mở trước/sau Start đều phải phát hiện trạng thái; hiện overlay directing Student về Exam Workspace; Practice Fullscreen không bypass lock.
- Backend chặn page và Practice operations mới; không ảnh hưởng Students khác.
- Practice Run đã accepted trước khi lock kích hoạt hoàn tất tự nhiên; không terminate process hoặc redesign execution. Student không được tiếp tục dùng Practice interface.
- Mở Practice khi attempt không còn active.

### 3.5 Deferred / out of scope

Không thực hiện trong bốn phase: redesign tab detection; Teacher add/dismiss/waive/reason management; WebSocket; browser extensions/kiosk; screen recording; grading/Practice engine redesign; tự động retention/archive; destructive data migration; compatibility architecture chỉ để hỗ trợ obsolete legacy assignments. Raw technical observations nên tách khỏi Teacher-reviewed assessment nếu review feature được duyệt về sau.

## 4. Roadmap bốn phase

> The phase-by-phase sections below preserve the original objectives, contracts, and acceptance criteria. Any phrase such as “not yet included” describes that phase's planned boundary at the time, not the current source status shown above.

| Phase | Kết quả chức năng độc lập | Dependency | Source status |
|---|---|---|---|
| 1 — Exam-Aware Telemetry | Presence vẫn chạy; snapshot chỉ thu trong active Student attempt và phục hồi qua reload. Event History chưa cần có. | Backend active-attempt determination. | Implemented; acceptance not verified here. |
| 2 — Persistent Event History and Teacher Monitoring | Focus/visibility transitions lưu bền; counters và history xem được, incremental sync qua monitor. | Phase 1 và attempt identity; không phụ thuộc Fullscreen/Practice Lock. | Implemented; acceptance not verified here. |
| 3 — Student Start Precheck and Fullscreen Gate | Student precheck/start và vào Exam bằng Fullscreen gate; event hiện ở Teacher Monitoring. | Phase 2; không phụ thuộc Practice Lock. | Implemented; browser acceptance not verified here. |
| 4 — Practice Lock and Final Integration | Active examinee không mở/khởi tạo Practice operation mới; accepted Run được hoàn tất; đúng lúc thì unlock. | Shared active-attempt contract và Phase 1–3. | Implemented; end-to-end acceptance not verified here. |

Phase N không hoàn tất nếu chỉ hoàn thành các phần frontend/backend riêng lẻ. Cần usable end-to-end result, acceptance riêng, regression cộng dồn và Owner review.

## 5. Phase 1 — Exam-Aware Telemetry

### Objective, scope and deferred work

Tách session presence khỏi behavioral monitoring. Reuse auth/session/status, assignment/release, telemetry snapshot và Monitor hiện có. Thay đổi dự kiến ở app/main.py, app/security.py chỉ nếu cần, app/exams.py/general_exams.py nếu active resolver cần service context, static/js/student.js, tests liên quan.

In scope: shared backend active-attempt determination; giữ Student Start validation; heartbeat/status tiếp tục; chỉ gửi/ghi telemetry khi active; frontend khôi phục từ status sau success/reload/reconnect/reauth; stop telemetry khi End/expiration/deadline/forced submission; bảo toàn snapshot/monitor contract tương thích. Chưa có event history, modal, precheck hay Practice Lock.

### API/data contract

- GET /api/student/status bổ sung active-attempt projection additive; giữ field cũ.
- POST /api/student/telemetry tiếp tục nhận snapshot hiện tại nhưng server đối chiếu session và active assignment/release, không tin ID do client khai báo.
- sessions.json giữ current snapshot schema; không tạo events/counters ở phase này.
- Attempt identity tối thiểu xem xét student_id + release_id từ assignment. Trước code phải xác nhận pair này xác định duy nhất attempt trong model được hỗ trợ hiện tại; nếu không, dừng xin Owner quyết định thay vì bịa ID.

### Acceptance criteria

- Login, Teacher Start only, Exam waiting và Practice: online/last_seen vẫn hoạt động; không có behavioral telemetry mới.
- Student Start success bật telemetry sau khi state backend xác nhận active; failed Start không bật.
- Reload/new tab/reauth khôi phục state từ backend.
- Teacher End, deadline, expiration, forced submit tắt telemetry.
- Existing Exam/Practice routes và snapshot fields vẫn tương thích.
- Stale snapshot không bị hiển thị như trạng thái active ngoài attempt.

### Regression and manual verification

Automated: active resolver not-assigned/teacher-started/active/ended/expired/forced/deadline/release mismatch; telemetry POST outside/inside attempt; status không dựa started_at đơn độc; last_seen khi telemetry off; Monitor response compatibility; Practice/Paper/Exam/Student API/Runner regressions.

Manual: login không Exam, Teacher Start chưa Student Start, Start success/fail, reload/re-auth, logout, End/deadline/forced submit, online/offline Monitor, Practice ngoài Exam.

### Risks, rollback and DoD

Rủi ro: status hiện không cung cấp active boolean đủ; assignment flows có thể có termination details khác; snapshot cũ tồn tại. Dùng additive response và không xóa sessions.json. Rollback code không xóa data. DoD: active resolver được test, presence liên tục, telemetry đúng lifecycle, reload restore, Phase 1 + existing regressions pass, Owner được báo test chưa chạy/rủi ro và review trước Phase 2.

## 6. Phase 2 — Persistent Event History and Teacher Monitoring

### Objective, scope and deferred work

Lưu focus/visibility transitions theo attempt, Teacher xem counters/history kể cả khi Student trở lại trạng thái bình thường. Reuse telemetry listeners, snapshot, monitor polling, JSON utilities. Dự kiến sửa app/main.py, app/storage.py hoặc service nhỏ phù hợp, static/js/student.js, static/js/admin.js, tests và additive test fixtures.

In scope: event store additive; event identity/sequence/counters/timestamps; distinct blur/hidden; transition/idempotency; thread-safe read-modify-write; Monitor response nhẹ có identity/snapshot/counter/latest_event_seq; history incremental sync và UI history. Chưa có Fullscreen, precheck, Practice Lock, teacher review tools hay retention.

### API/data contract

- Event gồm server sequence, unique event_id, event_type, server received timestamp, attempt identity, provenance tối thiểu. Client time chỉ là hint.
- Counters tăng đúng một lần khi event được append. sequence tăng theo accepted event trong attempt. Retry cùng event_id không duplicate; hai loại event khác nhau không gộp.
- Giữ event/counter/sequence trong cùng record/mutation để nhất quán; file riêng additive (ví dụ exam_monitoring.json) thích hợp hơn sessions.json vì session lifecycle không phải Exam history lifecycle.
- Monitor polling không tải event đầy đủ. latest_event_seq đổi mới yêu cầu history query theo attempt + after_seq; route mới hoặc extension được chọn khi triển khai, giữ API compatibility.
- Authentication: Student chỉ append attempt của chính mình; Teacher phải admin-authenticated để đọc.
- Storage lock bao trọn read-check-write; không suy diễn transaction đa file hoặc multi-process.

### Acceptance criteria

- Blur và hidden được ghi riêng, kể cả cùng thao tác.
- Heartbeat/poll/init/repeated snapshot không tăng counters.
- Retry và concurrent submissions không mất/tăng trùng record; history/counters/sequence khớp.
- Teacher thấy historical warning sau khi snapshot bình thường.
- History fetch chỉ khi seq tăng; dashboard reload, missed poll, failed fetch phục hồi đầy đủ mà không tiến cursor sai.
- Phase 2 dùng được không cần Phase 3/4.

### Regression and manual verification

Automated: event type/transition, dedupe, counter/sequence, threaded temp-data mutation, auth/attempt ownership, after_seq/pagination, failure/retry, Monitor backward compatibility, unchanged sequence avoids history request, reload/reconnect; toàn bộ Phase 1 + Exam/Practice suites.

Manual: focus/blur, hidden/visible, đồng thời hai event; reload/reauth; Teacher polling, missed polls, dashboard reload; xác nhận alert persistence và không gán misconduct.

### Risks, rollback and DoD

Event JSON tăng dần, không có retention trong scope. Threaded server tạo races nếu mutation không khóa toàn chuỗi; lock chỉ process-local. Rollback code/UI không xóa event data. DoD: persistent history/counter/sequence nhất quán, Teacher incremental sync hoạt động, cumulative regression pass, Owner review trước Phase 3.

## 7. Phase 3 — Student Start Precheck and Fullscreen Gate

### Objective, scope and deferred work

Controlled entry vào Official Exam và Fullscreen recovery. Reuse Start route/auth, Phase 2 event store/counters/monitor, active-state query. Dự kiến sửa templates/student.html, static/js/student.js hoặc module Exam workspace phù hợp, CSS hiện hành, app/main.py/app/exams.py nếu Start metadata cần thiết, tests.

In scope: tab precheck; Cancel/Continue; successful Start ghi multiple-tab event; modal/overlay fullscreen; Agree/Refuse/request failure/exit; F5 and End recovery; Monitor history. Chưa có Practice Lock hay redesign tab algorithm.

### API/data contract

- Giữ backend Student Start authorization/response behavior; request field metadata optional để callers cũ tương thích.
- Cancel không gửi POST Start và không ghi event.
- Initial tab event chỉ ghi sau successful Start; không gửi cho failed Start. Dùng idempotency để retry không ghi trùng.
- Event types đúng: fullscreen_refused, fullscreen_request_failed, fullscreen_lost.
- Fullscreen request từ user click; unlock chỉ khi browser báo đã vào fullscreen.
- Browser signal không xác nhận nguyên nhân. Reload không tự tạo fullscreen_lost.

### Acceptance criteria

- Một tab đi thẳng; nhiều tab hiển thị cảnh báo.
- Cancel không Start/no event; Continue + success Start và tối đa một event; Start fail không event.
- Active Exam sau reload hiện modal khi không fullscreen.
- Agree success unlock; Refuse/failure giữ khóa; recovery button hoạt động.
- Exit fullscreen khi active khóa lại và ghi một event cho transition.
- F5 không restart/reset; Exam End trong modal gỡ gate.
- Teacher Monitor Phase 2 thể hiện events/counters.
- Phase 3 không phụ thuộc Practice Lock.

### Regression and manual verification

Automated: no POST on cancel; continue success/fail; double click/retry/idempotency; backend Start auth unchanged; fullscreen state accept/refuse/reject/exit/reload/end; counters/history/Monitor; browser automation nơi khả thi; Phase 1–2 và existing Exam/Practice suites.

Manual: browser tab signal, Fullscreen permission/rejection, Refuse/retry, Esc/browser exit, F5, network loss, Teacher End; kiểm tra thông báo không khẳng định detect mọi tab hay nguyên nhân exit.

### Risks, rollback and DoD

Fullscreen cần user activation và browser support; không đảm bảo ngăn Esc/tự bật lại. Event có thể mất nếu Start thành công nhưng follow-up request lỗi; ưu tiên metadata cùng Start hoặc reliable idempotent retry. Rollback UI không xóa event history hay thay Student Start. DoD: controlled Start/fullscreen, correct events, Monitor visibility, cumulative regressions pass, Owner review trước Phase 4.

## 8. Phase 4 — Practice Lock and Final Integration

### Objective, scope and deferred work

Chặn Practice cho Student đang thi mà không phá Run đã accepted. Reuse active-attempt helper Phase 1, Practice route/API auth, student-practice.js polling/visibility, Phase 3 Exam navigation. Dự kiến sửa app/main.py, app/practice.py chỉ tại operation boundary cần thiết, static/js/student-practice.js, templates/practice.html, tests.

In scope: page + API guards; open Practice before/after Start; blocking overlay; backend per-Student enforcement; polling/visibility recovery; Run in-flight semantics; unlock khi attempt ended/expired; end-to-end integration. Không sửa Practice engine, cancel Run, grading, eligibility/revision/progress hoặc Exam lifecycle.

### API/data contract

- Server guard là authoritative. Không dùng global exam_state started để khóa tất cả Students.
- Guard GET /practice và mọi Practice operation đang có: progress, catalog, run-status, detail, update, Run, progress deletion; kiểm kê route mới trước khi triển khai.
- API denial có error contract rõ để UI khóa mà không xóa progress.
- Recheck lock ngay trước chấp nhận operation mới.
- Run đã accepted trước Start hoàn tất tự nhiên. Không terminate process; không cho Student tá继续 dùng interface/result route trong lock nếu điều đó mở khóa content. Implementation phải phân biệt operation in-flight với operation mới.

### Acceptance criteria

- Practice full functionality trước Student Start; Teacher Start riêng không lock.
- Practice mở sau Start bị chặn; tab mở trước Start tự phát hiện qua status polling/lifecycle events.
- Direct API requests bị server từ chối.
- Run đang execute trước khi lock được hoàn tất; Run mới bị chặn.
- Student khác không bị ảnh hưởng.
- End/expiration unlock đúng Student; Exam Monitoring Phases 1–3 vẫn hoạt động.
- Eligibility, revision/CAS, visible-only, progress và active-run safeguards giữ nguyên.

### Regression and manual verification

Automated: state matrix (not started/active/ended/expired/deadline/forced), all routes, direct API, old tab status polling, Run-in-flight then Start, new Run denial, unlock, Student isolation; Practice eligibility/progress/CAS/visible-only; toàn bộ Phase 1–3, Paper/Exam/Student API/Runner/grading/regrading suites.

Manual: Practice tab trước/sau Start, reload/direct URL, API attempt, existing Run, Teacher Start alone, multi-Student, End/expiry unlock, Practice Fullscreen không bypass.

### Risks, rollback and DoD

Browser đã nhận content không thể bị thu hồi; overlay/API guard ngăn thao tác bình thường và operation mới, không xóa cache/devtools. Polling có độ trễ UI, backend guard mới là tức thời. Không cancel Run đã accepted. DoD: page/API khóa, Run completion tự nhiên, unlock đúng, isolation và prior contracts pass; Owner review cuối.

## 9. Cross-phase dependencies và contract matrix

| Contract | Owner/module | Phase giới thiệu | Consumer | Compatibility / regression protection |
|---|---|---:|---|---|
| Canonical active attempt | Backend helper từ assignment/release | 1 | 2–4 | Không dùng started_at đơn độc; kiểm tra status, Teacher End, forced submit, deadline và release. Test state matrix. |
| Attempt identity | Authenticated student_id + persisted release identity; xác nhận uniqueness từ current records | 1 | 2–4 | Không tin client ID; không bịa assignment ID. Nếu pair không đủ unique thì dừng xin Owner. Test mismatch/reauth/multi-Student. |
| Presence vs telemetry | security.get_session + student.js schedulers | 1 | Tất cả | Presence tiếp tục khi telemetry off; test last_seen/online. |
| Snapshot schema | telemetry route + sessions.json + monitor projection | 1 | 2–3 | Giữ field/shape cũ; stale snapshot không đồng nghĩa active event. Test old consumers. |
| Event semantics | Event service + browser transition listeners | 2 | 3, Monitor | Blur/hidden độc lập; Fullscreen type đúng đã duyệt; test simultaneous types. |
| Counters | Event mutation service | 2 | 3, Monitor | Chỉ event append mới tăng; historical counter không reset; test counter/history consistency. |
| Event ID/sequence | Event persistence + incremental API | 2 | 3, Teacher UI | Idempotent event_id; monotonic sequence per attempt; cursor không collision. |
| JSON concurrency | app/storage.py + service transaction boundary | 2 | 3–4 | Lock entire read-check-write; event/counter/seq cùng mutation. Không tuyên bố multi-process/đa file atomic. Test threaded temp storage. |
| Monitor polling/API | monitoring_snapshot + admin.js | Snapshot Phase 1; counters/history Phase 2 | 3 | Response nhẹ/fields cũ giữ; lịch sử chỉ fetch khi seq đổi. Test poll/reload/missed request. |
| Student Start | main.py/exams.py + student.js | Giữ ở 1; metadata optional ở 3 | 3 | Giữ auth/password/assignment rules; Cancel không gọi API. Test API compatibility và retry. |
| Fullscreen state | Student workspace | 3 | Monitor | Request từ gesture; unlock chỉ sau confirmation; reload không tạo exit event. Browser tests. |
| Practice Lock | main.py routes + student-practice.js | 4 | Future | Per authenticated Student; server authoritative; accepted Run finishes naturally. Test every route/in-flight Run/isolation. |

## 10. Regression, Git checkpoints, risks và unresolved questions

### Cumulative regression policy

| Điểm kết thúc | Bắt buộc |
|---|---|
| Phase 1 | Phase 1 acceptance + existing Exam/Practice regression. |
| Phase 2 | Phase 1 + Phase 2 + existing Exam/Practice regression. |
| Phase 3 | Phase 1–3 + existing Exam/Practice regression. |
| Phase 4 | Phase 1–4 + complete Paper/Exam/Student API/Question Bank/Runner/submission/grading/regrading/Practice regression. |

Report mỗi phase phải ghi command, số lượng pass/fail/skip/block, môi trường, browser test và test không chạy. Chỉ dùng temporary data; không test trên live JSON.

### Git checkpoint và Owner approval

1. Trước mỗi phase xác nhận branch/worktree và lưu nhận thức về tất cả existing changes; không reset, restore, clean, stash hoặc overwrite unrelated work.
2. Đọc lại source và xác nhận request của Owner chỉ định phase.
3. Chỉ sửa scope phase đó; không tự động thực hiện phase sau.
4. Test với isolated data và cumulative suites.
5. Báo file đổi, test results, manual verification, untested items và risks.
6. Dừng chờ Owner review. Automated pass không thay Owner acceptance.
7. Commit checkpoint chỉ sau explicit Owner authorization; không commit/push/merge tự động.

### Rủi ro

- Browser focus/visibility/tab/fullscreen là client-reported signal; không chứng minh misconduct.
- tab_count không đếm mọi tab/window.
- ThreadingHTTPServer cần đồng bộ read-modify-write; RLock chỉ process-local.
- JSON Event History tăng dung lượng vì không có retention trong scope.
- Snapshot stale có thể tồn tại trong sessions.json sau khi Exam kết thúc.
- Poll và event mutation có race với End/expiration; backend phải recheck tại write boundary.
- Fullscreen khác nhau theo browser và user activation; không cam kết chặn Esc/tự restore.
- Practice overlay không thu hồi nội dung đã tải; backend guard chặn operation mới.
- Test/browser environment không hỗ trợ Fullscreen phải được ghi là limitation, không PASS giả.

### Câu hỏi chưa được source/decision giải đáp

1. **Attempt key:** xác nhận student_id + release_id duy nhất cho mọi record hiện được hỗ trợ trước khi định schema history. Nếu không, cần Owner chọn identity dựa trên field đã tồn tại.
2. **Initial state baseline:** khi monitoring bật mà document đã hidden/unfocused, khuyến nghị snapshot baseline, chỉ ghi transition quan sát được sau activation.
3. **Multiple-tab event handoff:** ở Phase 3 chốt optional request metadata/idempotency sau khi kiểm tra Start transaction semantics. Khuyến nghị append chỉ sau successful Start và retry idempotently.
4. **Retention:** Owner đã yêu cầu không auto-delete/archive ban đầu. Chính sách retention chỉ cần quyết định trước khi mở rộng phạm vi sau này.

## 11. Hướng dẫn handoff cho phiên triển khai tương lai

- Đọc kế hoạch này, DECISIONS.md, ARCHITECTURE.md, KNOWN_ISSUES.md và TELEMETRY_ARCHITECTURE_AUDIT.md.
- Yêu cầu triển khai phải chỉ rõ phase và phạm vi; tài liệu này không tự cấp authorization.
- Kiểm tra source/line numbers, branch và Git status mới nhất trước khi sửa.
- Tách rõ Owner-approved requirement, verified current behavior, inference và proposal.
- Dùng isolated temporary data, không migrate hay sửa live JSON.
- Truy vết UI event → HTTP method/path/payload → auth → service → validation → storage → response/render.
- Giữ compatibility các Exam, Practice, snapshot, assignment, grading và Runner contracts.
- Chạy regression cộng dồn, báo trung thực test không chạy/failure/blocker.
- Dừng sau phase và chờ Owner review; không tạo commit nếu chưa được yêu cầu.