# Bối cảnh dự án

> Baseline viết lại từ source hiện tại trên nhánh `integration/practice-exam`. Đây là mô tả sản phẩm, không phải xác nhận deployment hoặc nghiệm thu vận hành.

## Mục đích và môi trường

ClassroomSubmissionServerSystem hỗ trợ Giáo viên quản lý câu hỏi, bài luyện tập, Paper, Exam, bài nộp và kết quả. Ứng dụng cung cấp giao diện web tiếng Việt và lưu dữ liệu chủ yếu trong JSON/JSONL cùng các tệp liên quan.

Server mặc định bind `0.0.0.0:8080` (`app/config.py`); `app/main.py::main()` dùng `ThreadingHTTPServer` và in URL LAN. Runner dùng Windows Job Objects (`app/windows_job.py`), vì vậy execution cần môi trường Windows và toolchain Java/Python phù hợp. Đây là khả năng source biểu thị, không phải chứng nhận bảo mật hay production readiness.

## Vai trò

| Vai trò | Trách nhiệm |
|---|---|
| Teacher / Admin | Quản lý Question Bank, Practice eligibility, Paper, Exam, phân phối, Start/End, tài khoản, monitoring, submissions và regrade. |
| Student | Xem Exam được phép, bắt đầu sau Teacher Start, làm/nộp bài; truy cập Practice Library và chạy câu hỏi đủ điều kiện. |

Authentication dựa trên session cookie; route authorization nằm trong `app/security.py` và `app/main.py`.

## Luồng tính năng

### Question Bank
Teacher tạo hoặc nhập JSON vào Question Editor, sửa cấu hình, kiểm tra sample/spec rồi publish. `app/questions.py` xác thực tổ hợp `java/reflection`, `java/stdio`, `python/stdio` và quản lý lifecycle/revisions. Import/export do `static/js/questions.js` thực hiện; backend vẫn là validator cuối cùng. Metadata validation/revision do server quản lý theo contract trong `questions.py`.

### Practice Mode
Practice dùng cùng Question Bank nhưng có eligibility riêng: `status == published`, `practice_enabled == true`, `practice_revision` hợp lệ (`app/practice.py::is_practice_eligible()`). Student xem projection an toàn, sửa code cục bộ và chạy Practice Run. Practice chỉ chấm visible tests/checks và lưu progress theo Student; không tạo Official Exam assignment hoặc dùng Official Submit.

### Paper Management
Paper định nghĩa nội dung, câu hỏi và constraints. Paper schema v2 là entity độc lập có Paper ID, revision, content hiện tại và lifecycle status. Draft được lưu với zero hoặc incomplete question selection; Publish và Published Save Changes yêu cầu selected count bằng chính xác `question_limit`. Paper mới không có nested version collection. Legacy Paper/version pair vẫn được đọc bằng reference tường minh.

### Exam Distribution
Exam là entity riêng chọn một hoặc nhiều Paper, hoặc file Exam. Paper Code item có Common/Random distribution. Release lưu lựa chọn per-Student và dữ liệu snapshot cần cho lịch sử. Source Paper thay đổi sau release không được dùng để diễn giải lại release cũ.

### Official Exam lifecycle
Exam có các trạng thái chính Draft, Published/Distributed, Started, Ended:

1. Draft cho phép Teacher cấu hình.
2. Publish tạo release/hiển thị Exam cho Student đủ điều kiện nhưng chưa cho phép bắt đầu làm.
3. Teacher chủ động Start.
4. Student thực hiện Student Start riêng; backend kiểm tra Teacher state, assignment/release, password nếu cấu hình rồi ghi thời gian bắt đầu/deadline.
5. Published-not-Started có thể sửa nếu release chưa có Student activity làm mất tính toàn vẹn. Started/Ended không được sửa.
6. End đóng quyền làm bài theo release/deadline.

Code Exam có Pretest và Submit chính thức; file Exam có luồng access/submit riêng. Không có automatic scheduling trong source đã kiểm tra.

### Grading
Runner hỗ trợ Java Reflection, Java STDIO, Python STDIO. Practice chỉ chạy visible checks; Official Exam chạy grading đầy đủ theo snapshot, gồm hidden checks nếu cấu hình. `app/grading.py` chuẩn hóa/tổng hợp điểm; execution nằm ở `app/code_exams.py`, `app/code_runner.py`, `app/java_runner.py`, `app/windows_job.py`.

### Teacher Monitoring
Monitoring ghép session presence, assignment/submission summary và telemetry snapshot. Trang Student chính gửi focus, visibility, `tab_count`, browser info; Teacher UI poll backend. Snapshot hiện không gắn Exam/Release và không phải event history. Chi tiết tại [Telemetry Architecture Audit](TELEMETRY_ARCHITECTURE_AUDIT.md).

## Practice và Official Exam

| | Practice | Official Exam |
|---|---|---|
| Nguồn | Question Bank hiện hành, nếu đủ Practice eligibility | Paper/Exam và release snapshot |
| Quyền | `published && practice_enabled && valid practice_revision` | Assignment/release, Teacher Start, Student Start, deadline |
| Run | Visible-only, lưu Practice progress | Pretest tùy cấu hình; Submit chính thức chạy đầy đủ checks |
| Tách biệt | Không cần Paper, release, official assignment/submit | Không phụ thuộc `practice_enabled` |

## Đề xuất đang thảo luận — chưa triển khai

Owner đang xem xét Exam-only behavioral telemetry, giữ heartbeat ngoài Exam, tab precheck/dialog trước Student Start, fullscreen và monitoring events. Đây chưa phải tính năng hiện có hoặc quyết định đã duyệt. Xem [audit telemetry](TELEMETRY_ARCHITECTURE_AUDIT.md).

## Tài liệu liên quan
- [Architecture](ARCHITECTURE.md), [Decisions](DECISIONS.md), [Known Issues](KNOWN_ISSUES.md), [Engineering Lessons](ENGINEERING_LESSONS.md).
- [Exam Code Guide](EXAM_DISTRIBUTION_CODE_GUIDE.md), [Technical Handoff](EXAM_DISTRIBUTION_TECHNICAL_HANDOFF.md), [Merge Contract](EXAM_DISTRIBUTION_MERGE_CONTRACT.md).
- [Practice–Exam Premerge Compatibility](PRACTICE_EXAM_PREMERGE_COMPATIBILITY.md): bối cảnh tích hợp; đối chiếu source trước khi dùng.
