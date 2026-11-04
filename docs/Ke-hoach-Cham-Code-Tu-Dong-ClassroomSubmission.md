# Kế hoạch: Làm bài code + chấm code tự động cho ClassroomSubmissionServerSystem

> **Phiên bản:** v3 — bản tạo lại, đã gộp toàn bộ quyết định mới nhất
> **Cập nhật:** 02/11/2026
> **Những gì đã gộp vào v3 so với v2:**
> - Hệ thống chuyên cho **Windows** (máy trường đều chạy Windows), kèm các mục Windows trước đây nằm ở file bổ sung riêng — nay đã gộp vào kế hoạch và checklist chính, không cần tick file bổ sung riêng nữa.
> - **Stdio dùng cho cả Java và Python**, không còn là riêng của Python. Chấm class chỉ có ở Java.
> - **Mục “Quản lý đề thi”**: ngân hàng câu hỏi + đề thi dùng lại câu hỏi, thay cho việc mỗi kỳ thi chỉ có một đề code lẻ.
> - Đã xóa các phần brainstorm, hỏi đáp, nhật ký quyết định cũ. Các quyết định đã chốt chỉ còn ở bảng ràng buộc ngắn ở mục 2.
> **Tài liệu chi tiết đi kèm (không viết lại ở đây):**
> - Đặc tả Phase 1 Java: `Dac-ta-Phase1-Java-Reflection.md`
> - Code khung Phase 1 Java: `java-phase1-skeleton/` (ReflectionJudge.java, run_java.py, student-oop-spec.json, samples/)
> - Checklist chia task nhóm 3 người (bản tạo lại cùng đợt này): `Checklist-Nhom-3-Nguoi-Code-Grading.md`
> - Phân tích repo gốc: `README-ClassroomSubmissionServerSystem-Analysis.md`

---

## 1. Phạm vi và nền tảng — chỉ Windows

- **Máy giảng viên (server):** Windows 10/11, chạy server bằng Python, chia sẻ URL LAN cho sinh viên trong phòng học.
- **Máy sinh viên:** Windows, mở trình duyệt (Edge/Chrome) và truy cập URL LAN của máy giảng viên. Không cần cài thêm phần mềm gì trên máy sinh viên.
- **Chạy server:** bằng `.venv` + `setup_windows.bat` / `start_windows.bat` sẵn có của repo. Không dùng `start_unix.sh`, không hướng dẫn Linux/macOS trong tính năng này.
- **Stack giữ nguyên của repo:** Python standard library + Jinja2 là dependency runtime duy nhất. Không thêm FastAPI, Pydantic, Uvicorn, database server. Lý do vẫn đúng trên Windows: một số máy trường bật Device Guard / Application Control chặn DLL native như `_pydantic_core`, nên càng ít dependency native càng tốt.
- **Mô hình triển khai:** 1 process Python duy nhất, dữ liệu JSON/JSONL, chạy trên LAN tin cậy trong phòng học. **Không làm bản public internet trong đợt này.**

## 2. Ràng buộc phải tuân theo khi triển khai

| # | Ràng buộc |
|---|---|
| 1 | Phân loại câu hỏi bằng 2 chiều riêng: `language` (`java` / `python`) và `grading_mode` (`stdio` / `reflection`). Tổ hợp hợp lệ duy nhất: Java + reflection, Java + stdio, Python + stdio. |
| 2 | Bài Java Reflection: **package bắt buộc theo yêu cầu từng đề bài** (ví dụ `model.Student`). Khai báo sai hoặc không khai báo package là fail check class. Server phải đặt file nguồn đúng cấu trúc thư mục package trước khi gọi `javac`. |
| 3 | Bài Java stdio: 1 file / 1 public class có hàm `main`. Package theo spec của đề: spec ghi package thì phải đúng package đó, spec để trống thì cho phép default package. |
| 4 | Bài Java hiện tại (cả reflection và stdio): **1 file / 1 public class**. Tên file trùng tên public class. Chưa làm đa file. |
| 5 | Bài Java Reflection `toString`: admin cung cấp **template có sẵn**, sinh viên phải trả về **exact sau khi điền template** (chỉ chuẩn hóa CRLF → LF, không dùng `contains`). |
| 6 | Bài Java Reflection validator: giá trị không hợp lệ phải ném **`IllegalArgumentException`** (áp cho setter/constructor/method kiểm tra đầu vào). Predicate kiểu `isValid()` / `isPassing()` vẫn trả boolean. |
| 7 | Bài Java Reflection `Comparable`/`Comparator`: mặc định **không test `null`** trừ khi spec của check đó ghi rõ. |
| 8 | Pretest: admin bật/tắt được theo từng câu hỏi hoặc theo đề (`allow_pretest`). Bật thì sinh viên chỉ được chạy test/check **visible**. Tắt thì nút chạy thử biến mất hoàn toàn. |
| 9 | Chấm cuối: chạy toàn bộ test/check (visible + hidden). Test/check hidden **không bao giờ** được trả về frontend, HTML, JS hay log phía sinh viên. Server lọc trước khi trả. |
| 10 | Mọi deadline, thời gian bắt đầu/kết thúc đều theo **đồng hồ server (UTC)**, không theo đồng hồ máy sinh viên. Chỉ chấm khi đúng `release_id`, đã bắt đầu, còn trong giờ, đúng `exam_state`. |
| 11 | Đề thi gồm **nhiều câu hỏi** lấy từ ngân hàng, không còn giới hạn 1 đề code cho cả kỳ thi. Điểm đề bằng tổng điểm các câu hỏi trong đề. |
| 12 | Dùng lại câu hỏi bằng **snapshot, không phải link sống**: khi thêm câu hỏi vào đề, server copy nguyên bản câu hỏi lúc đó vào đề, kèm `source_question_id` và phiên bản. Sửa ngân hàng sau đó không làm thay đổi đề đã phát. Đề còn ở trạng thái nháp thì admin bấm “cập nhật từ ngân hàng” mới lấy bản mới nhất. |
| 13 | Giới hạn mặc định (admin sửa được theo từng câu hỏi/đề): pretest tối đa 20 lần/câu hỏi/kỳ thi, timeout judge theo spec, output cắt ngắn. Số lần nộp code dùng lại chính sách nộp sẵn có của kỳ thi (`submission_policy`, `max_submissions`). |

`target_class` và package được server kiểm tra theo classroom identifier subset: Unicode start/continuation categories của Python, cho phép `$`, nhưng loại các ký tự identifier-ignorable mà Java cho phép. Đây không phải parser đầy đủ của Java Language Specification; javac vẫn xác thực tên khai báo trong source.

## 3. Mục tiêu

1. Sinh viên làm bài code ngay trên web, không cần nộp ZIP rồi chờ.
2. Sinh viên được chạy thử với test/check visible nếu đề cho phép, hoặc không được chạy thử gì nếu đề thi kín.
3. Khi nộp bài, server tự chấm theo toàn bộ test/check có sẵn và lưu điểm + chi tiết từng test/check, theo từng câu hỏi.
4. Admin quản lý ngân hàng câu hỏi, lắp đề thi từ ngân hàng, xem kết quả trên dashboard hiện có, và chấm lại được khi sửa spec.
5. Code sinh viên không làm hại server, không đọc được đáp án/test ẩn, không đọc được dữ liệu của người khác trong phạm vi đã ghi ở mục 10.

### Ngoài phạm vi đợt này

- Chấm bằng AI, chấm phong cách code, chống đạo văn.
- Chạy code trên máy sinh viên rồi gửi kết quả về.
- Đa file Java, Comparator dạng class riêng, bài Python dạng viết hàm import trực tiếp.
- Judge server riêng, hàng đợi phân tán, auto-scale.
- Public internet, Docker bắt buộc, Windows Sandbox bắt buộc (chỉ là hướng hardening sau này, xem mục 10).
- Gộp đề PDF cũ vào ngân hàng câu hỏi code (ngân hàng ở đợt này chỉ cho đề code).

## 4. Kiến trúc tích hợp — không đập đi xây lại

```text
Trình duyệt Windows (sinh viên / admin)
  │  HTTP, mặc định http://<IP-LAN-may-giang-vien>:8080
  ▼
ThreadingHTTPServer (1 process Python, chạy trên máy giảng viên Windows)
  │  app/main.py — route cũ + route code mới, session + role check cũ
  ├── app/questions.py     (MỚI) Ngân hàng câu hỏi: CRUD, validate spec, lọc
  ├── app/code_exams.py    (MỚI) Đề thi code: tạo đề, thêm/xóa câu hỏi, snapshot
  ├── app/grading.py       (MỚI) Tính điểm theo từng câu hỏi và tổng điểm đề
  ├── app/java_runner.py   (MỚI) javac + java ReflectionJudge, subprocess Windows
  ├── app/code_runner.py   (MỚI) Runner stdio chung cho cả Java và Python
  ├── app/exams.py         (SỬA ÍT) Gắn đề thi code vào lượt thi, dùng lại release_id
  ├── app/submissions.py   (SỬA ÍT) Thêm loại submission "code", theo từng question_id
  └── app/storage.py       (DÙNG LẠI) JSON/JSONL + audit
        │
        ▼
Ổ đĩa máy giảng viên (Windows)
  data/questions.json        Ngân hàng câu hỏi
  data/code_exams.json       Đề thi code + snapshot câu hỏi trong đề
  data/code_submissions.json Bài code + kết quả chấm, theo exam_id + question_id
  data/code_runs.json        Lịch sử chạy thử, theo question_id (giới hạn số bản ghi)
  logs/audit.jsonl           question.create/update, exam.create/distribute,
                             code.run, code.submit, code.graded, code.regraded
  de-thi/                    File đề PDF hiện có (không đổi)
  submissions/               File ZIP hiện có (không đổi)
```

Nguyên tắc: code chấm không bao giờ chạy trong process của server web. Nó luôn chạy trong process con riêng và bị kill khi hết timeout.

## 5. Dữ liệu

### Câu hỏi trong ngân hàng (`data/questions.json`)

Mỗi câu hỏi có: `id`, `title`, `statement`, `language`, `grading_mode`, `category` (chủ đề để lọc, ví dụ OOP, mảng, vòng lặp — khác với `grading_mode`), `tags`, `difficulty` (tùy chọn), `starter_code`, `time_limit_seconds`, `memory_limit_mb`, `max_output_bytes`, `allow_pretest`, `max_pretest_runs`, `total_points` (phải bằng tổng điểm các check/test), `status` (`draft` / `published`), `source` (người tạo, thời gian tạo/sửa), `usage_count`.

`memory_limit_mb` là giới hạn **tổng committed memory của một Job Object cho một execution phase**, tính theo MiB (1 MiB = 1024 × 1024 bytes) và áp dụng cho toàn process tree trong Job. Job Object `JOB_MEMORY` đo commit, không đo resident working set. `PROCESS_MEMORY` cũng là commit limit nhưng áp dụng riêng cho từng process; runner đặt nó bằng cùng budget để một process đơn không vượt question limit. Với Python, interpreter và student code đều nằm trong budget. Với Java Reflection, JVM dùng chung cho ReflectionJudge và student class; heap và native JVM memory đều chịu tổng Job limit. Với Java STDIO, mỗi lần chạy test có Job riêng. Java question cần ít nhất 256 MiB để JVM có đủ native startup headroom; giá trị thấp hơn bị từ chối như cấu hình không hợp lệ.

Java `-Xmx` được suy ra từ budget hiệu dụng: tối đa một nửa tổng Job/process limit, làm tròn xuống MiB. Phần còn lại là headroom cho native JVM memory, class metadata, thread stacks, code cache và harness. `-Xmx` chỉ giới hạn Java heap, không phải tổng memory. Student compile và runtime chạy trong các Job riêng, mỗi Job chịu cùng `memory_limit_mb` của question. JDK version probes là thao tác hạ tầng và dùng budget riêng 512 MiB. `MLE` chỉ được trả khi Windows Job Object phát thông báo vượt process/job commit limit; Java `OutOfMemoryError`, exit code bất thường hoặc working set cao tự thân không đủ bằng chứng để gọi `MLE`.

Trường riêng theo dạng chấm:

- **Java reflection:** `target_class`, `target_package` (bắt buộc), `target_file`, danh sách `checks[]`.
- **Java stdio:** `target_class` (ví dụ `Main` hoặc tên do đề quy định), `target_package` (có thể để trống cho default package), `target_file`, danh sách `tests[]`.
- **Python stdio:** `target_file` (ví dụ `solution.py`), danh sách `tests[]`.

### Test/check

- **Java reflection:** mỗi check có `id`, `kind`, `points`, `is_visible`, cộng trường riêng theo kind (xem mục 8).
- **Stdio (cả Java và Python):** mỗi test có `id`, `stdin`, `expected_stdout`, `is_visible`, `points`, `compare_mode` (xem mục 9).
- `total_points` phải bằng tổng điểm. Bản tích hợp web phải tự kiểm tra và báo lỗi nếu lệch, không tự sửa điểm.

### Đề thi code (`data/code_exams.json`)

Mỗi đề có: `id`, `title`, `starts_at`, `ends_at`, `duration_minutes` (nếu có), `show_final_score_immediately`, `submission_policy` / `max_submissions` (dùng lại chính sách sẵn có), `status` (`draft` / `distributed` / `started` / `ended`), `release_id`, và `questions[]` — mỗi phần tử là snapshot của một câu hỏi lúc được thêm vào đề, gồm `question_id` (nguồn), `snapshot_version`, `snapshot_at`, toàn bộ nội dung câu hỏi lúc snapshot, và thứ tự trong đề. Điểm đề bằng tổng điểm các snapshot trong đề.

### Bài nộp code (`data/code_submissions.json`)

Mỗi bản ghi, theo MSSV, theo từng câu hỏi: `exam_id`, `release_id`, `question_id`, `language`, `grading_mode`, code snapshot, `submitted_at`, `score`, `total_points`, `status` (`graded`), `results[]` — mỗi kết quả có `test_id`/`check_id`, `verdict`, `points_earned`, `time_ms`, và với test/check visible thì có thêm `stdout`/`expected`/`actual` để sinh viên đối chiếu. Với test/check hidden, chỉ admin thấy chi tiết.

## 6. Ngân hàng câu hỏi — mục “Quản lý đề thi”, tab Ngân hàng

- Tạo, sửa, xóa, nhân bản, xem trước câu hỏi.
- Lọc theo `language`, `grading_mode`, `category`, từ khóa, trạng thái nháp/đã duyệt. Danh sách hiện tiêu đề, ngôn ngữ, dạng chấm, chủ đề, tổng điểm, số lần đã dùng trong các đề thi.
- Form tạo câu hỏi đổi theo lựa chọn: chọn ngôn ngữ trước, rồi chọn dạng chấm. Chọn Java thì hiện đủ 2 lựa chọn stdio và chấm class, chọn Python thì chỉ hiện stdio.
  - Form stdio: đề bài, starter code, bảng test (stdin, expected, visible/hidden, điểm, compare_mode), import/export test từ JSON.
  - Form reflection: đề bài, target_class, target_package bắt buộc, tên file, template `toString`, bảng check theo từng loại bằng dropdown (field, constructor, method, behavior, toString, comparable), không bắt admin gõ JSON tay.
- Trước khi một câu hỏi được chuyển sang `published` để dùng chung, bắt buộc phải chạy đáp án mẫu qua toàn bộ test/check và đạt 100/100. Đáp án mẫu trượt check nào là spec sai, phải sửa trước, không được phát đề rồi mới phát hiện.
- Xóa câu hỏi: chỉ xóa hẳn khi chưa dùng trong đề nào đã phát. Câu hỏi đã dùng trong đề đã phát thì chỉ được lưu trữ (archive), không xóa hẳn, để còn chấm lại và xem lịch sử. Snapshot trong đề cũ vẫn giữ nguyên dù câu hỏi gốc bị lưu trữ hay sửa sau đó.
- Câu hỏi mẫu đầu tiên để kiểm chứng: `model.Student` trong `student-oop-spec.json` (Java reflection, 11 check, 100 điểm: 70 visible, 30 hidden là validator và comparable). Đưa câu này vào ngân hàng với `category` là OOP để nhóm test luồng dùng lại ngay.

## 7. Đề thi — mục “Quản lý đề thi”, tab Đề thi

- Tạo đề thi gồm tên, thời gian bắt đầu/kết thúc, cài đặt hiển thị điểm và chính sách nộp, rồi chọn câu hỏi từ ngân hàng.
- Trình lắp đề: bên trái là ngân hàng có lọc theo ngôn ngữ, dạng chấm, chủ đề và tìm kiếm; bên phải là danh sách câu hỏi đã chọn, kéo thứ tự lên xuống, xóa khỏi đề, xem tổng điểm tự cộng theo các câu hỏi đã chọn. Không cho thêm trùng một câu hỏi hai lần vào cùng một đề.
- Khi thêm câu hỏi vào đề, server tạo snapshot như ràng buộc 12. Đề còn ở trạng thái nháp thì admin có nút “cập nhật từ ngân hàng” để lấy bản mới nhất của một câu hỏi, hoặc xóa rồi thêm lại. Đề đã phát thì không được sửa nội dung câu hỏi trong đề nữa, chỉ được chấm lại kết quả nếu cần.
- Đề thi đi theo vòng đời sẵn có: nháp → phát đề → bắt đầu → kết thúc, dùng `release_id` và đồng hồ server. Hết giờ thì khóa chạy thử và nộp bài cho toàn bộ câu hỏi trong đề.
- Trang kết quả của admin theo đề: lọc theo sinh viên, xem điểm từng câu hỏi, tổng điểm đề, xem code đã nộp từng câu, xem pass/fail từng check/test (admin thấy cả hidden), nút chấm lại theo đề hoặc theo từng câu hỏi.

## 8. Phase 1 — Java bằng Reflection (làm trước)

Chi tiết đầy đủ nằm trong `Dac-ta-Phase1-Java-Reflection.md` và code khung trong `java-phase1-skeleton/`. Bản kế hoạch này chỉ ghi lại những điểm bắt buộc để nhóm không phải mở lại toàn bộ đặc tả khi code.

### Các loại check phải làm

| Kind | Kiểm tra |
|---|---|
| `field` | Tên field, kiểu dữ liệu, modifier (dùng `getDeclaredField`) |
| `constructor` | Đúng danh sách tham số, modifier (dùng `getDeclaredConstructor`) |
| `method` | Tên, kiểu trả về, tham số, modifier (dùng `getDeclaredMethod`, match theo tên + tham số, không match theo tên riêng) |
| `implements` | Class có implements interface yêu cầu không |
| `behavior` | Hành vi chung: setup object → gọi method → so `expect_return`, hoặc `expect_state` (đọc lại bằng getter/field), hoặc `expect_exception` |
| `toString` | Điền template bằng giá trị field thật, so exact với `toString()` của sinh viên (chỉ chuẩn hóa CRLF → LF) |
| `comparable` | `compareTo` đúng dấu và đúng thứ tự sort theo spec |

Getter/setter và validator được chấm bằng `behavior`, không chỉ chấm tên method: getter/setter thì set rồi get lại phải đúng; validator thì giá trị sai phải ném `IllegalArgumentException` (ràng buộc 6), predicate `isPassing()`/`isValid()` thì so return boolean.

### Luồng chấm Java Reflection trên Windows

```text
Sinh viên nộp Student.java (1 file, 1 public class, đúng package)
  → Server lưu code vào thư mục tạm riêng, đúng cấu trúc package:
      <temp>\src\model\Student.java
  → javac -encoding UTF-8 -d <temp>\out <temp>\src\model\Student.java
      Lỗi biên dịch → verdict CE, 0 điểm, kèm output javac cắt ngắn, dừng
  → java -Xmx<derived-from-memory_limit_mb> -cp <judge_build_cache>/<key>/classes ReflectionJudge <temp>\out
      Spec đã lọc (pretest: chỉ visible) được đưa qua stdin pipe, KHÔNG qua file
      Mỗi check dùng một URLClassLoader mới, parent là platform classloader;
      target class được load và khởi tạo lại từ student output directory.
      Behavior check tạo fixture mới; static state và singleton của student không
      được chia sẻ giữa các check.
      Các check vẫn chạy trong cùng Judge JVM. Thread do student tạo có thể sống
      qua check hiện tại và thay đổi trạng thái JVM-wide; classloader mới không
      phải process isolation. Nếu cần bảo đảm cách ly thread/global state, cần
      đánh giá process-per-check ở phase sau và đo performance trước khi đổi.
      Judge result đi qua protocol channel riêng, không qua stdout của student.
  → Server đọc JSON, tính điểm, lưu bài nộp, trả về theo quyền hiển thị
  → Luôn xóa thư mục tạm trong finally (trừ chế độ debug giữ lại để xem)
```

`ReflectionJudge.java` được biên dịch lazy ở lần chạy hợp lệ đầu tiên. Cache nằm ngoài workspace của từng submission, dùng key từ SHA-256 source cùng đường dẫn/version của `javac`; các class file được kiểm hash trước khi reuse. Build mới được biên dịch trong staging directory rồi publish bằng rename nguyên tử. Lock theo key ngăn các request đồng thời biên dịch trùng; cache hỏng sẽ bị loại bỏ và build lại. Không commit `.class` vào repository. Cache không tạo ranh giới filesystem: process student vẫn chạy dưới cùng Windows account và chỉ được bảo vệ theo giới hạn đã mô tả ở mục 10.

### Điều kiện tiên quyết trên máy giảng viên Windows

- Cài JDK 17+ cho Windows (ví dụ Microsoft OpenJDK hoặc Temurin cho Windows), đưa `java` và `javac` vào `PATH`, hoặc cấu hình `JAVA_HOME`.
- Server kiểm tra lúc khởi động bằng lệnh tương đương `where javac` và `javac -version`, `java -version`. Thiếu JDK phải báo rõ ngay lúc khởi động, không được để tới lúc sinh viên nộp bài mới báo lỗi chung chung.

## 9. Phase 2 — Stdio cho cả Java và Python (làm sau Java Reflection)

- Dạng bài: đọc từ stdin, in ra stdout. Test = cặp `(stdin, expected_stdout)`. Dạng này dùng chung cho cả Java và Python.
- So sánh output theo `compare_mode` của từng test:
  - `exact`: khớp byte sau khi chuẩn hóa CRLF.
  - `normalized` (mặc định): bỏ khoảng trắng thừa cuối dòng, bỏ dòng trống cuối.
  - `tokens`: so theo từng token, bỏ qua mọi khoảng trắng/xuống dòng.
  - `float_tolerance`: so số thực với sai số.
- Verdict dùng chung: `AC`, `WA`, `TLE`, `MLE` (khi đo được), `RE`, `CE` (lỗi biên dịch Java / lỗi cú pháp Python, phát hiện sớm), `OLE`.
- Runner stdio dùng chung một khung cho cả hai ngôn ngữ: thư mục tạm riêng, subprocess riêng, timeout từng test, cắt stdout/stderr, env tối thiểu, lọc visible/hidden trước khi chạy, tính điểm và audit giống Java Reflection. Chỉ lệnh chạy khác nhau theo ngôn ngữ.
- **Java stdio:** 1 file / 1 public class có hàm `main`. Server đặt file đúng cấu trúc package theo spec, chạy `javac -encoding UTF-8`, rồi chạy `java` với stdin pipe cho từng test. Lỗi biên dịch → `CE`.
- **Python stdio:** 1 file Python, server chạy `python.exe` với stdin pipe cho từng test, không import code sinh viên vào process server.
- Không import code sinh viên trực tiếp vào process server. Bài Python dạng viết hàm import trực tiếp **không làm trong đợt này**.

## 10. An toàn trên Windows — đọc kỹ, không quảng cáo quá mức

### Sự thật cần ghi rõ cho giảng viên

`subprocess` một mình **không phải là sandbox tuyệt đối** trên bất kỳ hệ điều hành nào, kể cả Windows. Process con vẫn chạy cùng user với server, vẫn có thể đọc file mà user đó có quyền đọc và truy cập mạng nếu máy có mạng, trừ khi có thêm biện pháp của hệ điều hành. Vì vậy bản này dùng nhiều lớp, và vẫn ghi rõ phần còn sót lại.

### Các lớp bảo vệ của MVP trên Windows (bắt buộc)

1. **Process riêng, không `exec`/`eval` trong server.** Code sinh viên chỉ chạy trong process con (`python.exe` hoặc `java.exe` riêng), server chỉ điều phối.
2. **Workspace riêng cho mỗi lần chấm.** Tạo root duy nhất theo `run_id`, xử lý code trong workspace riêng và cleanup trong `finally`. Production mặc định cleanup; debug có thể truyền `keep_temp=True`. Cleanup Windows bỏ thuộc tính read-only khi cần và retry tối đa 3 lần có giới hạn. Không đi theo symlink, junction hoặc reparse point. Nếu lock/quyền truy cập vẫn cản cleanup, lỗi được ghi log nội bộ, không làm crash server và không thay verdict đã có. Code không chạy trực tiếp trong thư mục project.
3. **Không truyền test/check qua file.** Với stdio, input đưa qua stdin pipe, output kỳ vọng so sánh ở phía server. Với reflection, spec đã lọc được đưa qua stdin pipe cho harness. Như vậy code sinh viên không có file test nào trên đĩa để đọc trộm trong lần chạy đó.
4. **Timeout cứng.** Timeout cho từng test (stdio) và cho toàn bộ lần chạy judge (reflection, Phase 1). Hết timeout thì kill process và cây process con nếu có thể, verdict `TLE`, server vẫn sống.
5. **Cắt output và giới hạn dung lượng.** Cắt stdout/stderr (mặc định 64 KiB cho stdio, theo spec cho reflection), giới hạn độ dài code nộp, giới hạn số lần chạy thử và số lần chấm chạy cùng lúc, kèm cooldown ngắn chống spam nút Run.
6. **Môi trường tối thiểu.** Chạy với env đã lược bỏ, không truyền biến môi trường chứa đường dẫn nhạy cảm hay token. Không truyền đường dẫn thư mục `data/`, `de-thi/`, `submissions/` cho process con.
7. **Job Objects trên Windows (bằng `ctypes`, vẫn là Python stdlib, không thêm pywin32).** Đây là biện pháp thay cho giới hạn tài nguyên kiểu Unix (không dùng `resource.setrlimit`, vì Windows không có). Runner phải tạo Job Object cho mỗi lần chấm và gán process con vào job đó, với ít nhất:
   - `JOBOBJECT_LIMIT_KILL_ON_JOB_CLOSE`: đóng job là kill toàn bộ process trong job, chống process con sống sót sau khi runner thoát.
   - `JOBOBJECT_LIMIT_ACTIVE_PROCESS`: giới hạn số process con (chống fork/process bomb ở mức cơ bản).
   - `JOBOBJECT_LIMIT_PROCESS_MEMORY` / `JOBOBJECT_LIMIT_JOB_MEMORY`: giới hạn RAM cho process/job (ví dụ 256 MB theo spec).
   - Nếu tạo Job Object thất bại trên máy đó, runner phải báo rõ và **không lặng lẽ chạy không giới hạn** — admin phải biết máy đó đang chạy ở mức bảo vệ thấp hơn.
   - Lưu ý: Job Object **không chặn mạng** và **không chặn đọc file** một mình. Nó chỉ giới hạn process, RAM và kill khi đóng job.
8. **Harness Java cách ly classloader.** Harness load class sinh viên bằng `URLClassLoader` riêng, parent là platform classloader, nên code sinh viên không thấy class của harness. Load class cũng nằm trong JVM riêng có timeout, không load trong process server.
9. **Chặn blacklist không được tin.** Không dựa vào việc cấm `import os/sys/subprocess` hay quét code bằng AST để chặn từ khóa. Sinh viên lách blacklist rất dễ (ví dụ nối chuỗi tên module). Blacklist nếu có chỉ là lớp phụ, không phải lớp chính.
10. **Ghi log mọi lần chạy.** Ai, đề nào, câu hỏi nào, test/check nào, verdict, thời gian, exit code — nhưng không log code đầy đủ hay test ẩn vào log công khai.

### Phần còn sót lại ở MVP LAN Windows (phải ghi trong tài liệu giảng viên)

- Code sinh viên vẫn có thể đọc file mà user chạy server có quyền đọc, và vẫn có thể gọi mạng, nếu biết đường dẫn và máy có mạng — **chỉ container hoặc máy ảo mới chặn triệt để hai thứ này**.
- Vì vậy MVP này chỉ phù hợp cho **phòng học LAN có giảng viên giám sát trực tiếp**, trên máy Windows của trường, với Windows Firewall chỉ mở cổng server cho mạng Private/trusted LAN, không mở ra internet, không mở cho mạng Public.
- **Không bật HTTP ra internet.** Mặc định server chỉ dùng HTTP trên LAN tin cậy; nếu cần mã hóa thì dùng TLS với chứng chỉ được máy sinh viên tin cậy, và cookie sẽ có cờ `Secure` khi bật TLS (theo code sẵn có).

### Hardening sau MVP (không phải điều kiện của đợt này, chỉ làm khi cần thi không giám sát)

- **Windows Sandbox** (yêu cầu Windows Pro + Hyper-V) hoặc **Docker Desktop trên Windows** (yêu cầu WSL2) để chạy judge trong container/máy ảo riêng, với mạng bị chặn và thư mục làm việc read-only. Khi làm hướng này, chỉ cần thay backend runner (giữ nguyên interface, spec và luồng chấm), không sửa lại luồng nộp bài.
- Không dùng hướng dẫn sandbox cho Linux (nsjail, bubblewrap, systemd, Linux VPS) trong hệ thống này nữa, vì nhóm đã thống nhất làm chuyên cho Windows.

## 11. Luồng pretest, chấm cuối và tính điểm — theo từng câu hỏi

### Pretest (chạy thử)

```text
Sinh viên bấm "Chạy thử" ở một câu hỏi
  → Kiểm tra: đã bắt đầu thi, còn trong giờ, câu hỏi/đề có allow_pretest,
      còn lượt pretest của câu hỏi đó, không spam
  → Lấy code hiện tại trong editor của câu hỏi đó (CHƯA phải bài nộp chính thức)
  → Server lọc spec chỉ còn test/check visible của câu hỏi đó, rồi mới chạy
  → Trả về: bảng từng test/check visible, stdout/actual vs expected (với check visible),
      lỗi nếu có, thời gian chạy
  → KHÔNG tính điểm, KHÔNG đánh dấu submitted cho câu hỏi đó,
      KHÔNG chạy test/check hidden
```

### Chấm cuối (khi nộp bài)

```text
Sinh viên bấm "Nộp bài" ở một câu hỏi (có xác nhận)
  → Kiểm tra như nộp ZIP: đúng release_id, đã bắt đầu, chưa hết giờ,
      chưa vượt số lần nộp cho phép theo submission_policy
  → Lưu snapshot code + hash SHA-256, theo exam_id + question_id
  → Chấm toàn bộ test/check của câu hỏi đó: visible + hidden
  → Tính điểm câu hỏi: cộng điểm từng test/check pass, không trừ điểm test/check fail
  → Điểm đề = tổng điểm các câu hỏi trong đề
  → Lưu kết quả chi tiết (admin thấy hết, sinh viên thấy theo show_final_score_immediately)
  → Đánh dấu câu hỏi đó đã nộp; khi tất cả câu hỏi đã nộp hoặc hết giờ thì đề được khóa
  → Ghi audit code.submit / code.graded
```

### Verdict dùng chung

`AC` (đúng), `WA` (sai output/kết quả/hành vi), `TLE` (quá thời gian), `MLE` (quá RAM khi đo được), `RE` (crash/exception ngoài kỳ vọng), `CE` (lỗi biên dịch/cú pháp), `OLE` (output quá nhiều). Với Java reflection, `WA` còn bao gồm sai modifier, sai kiểu, sai format `toString`, sai hành vi — kết quả chi tiết phải ghi rõ `expected` vs `actual`.

## 12. API và giao diện (Windows, không CDN)

### API mới (đi theo chuẩn route hiện có, đều yêu cầu session + role)

| Method | Endpoint | Vai trò | Mục đích |
|---|---|---|---|
| GET | `/api/admin/questions` | Admin | Danh sách ngân hàng, lọc theo language, grading_mode, category, từ khóa |
| POST | `/api/admin/questions` | Admin | Tạo câu hỏi trong ngân hàng |
| GET | `/api/admin/questions/{id}` | Admin | Chi tiết câu hỏi + toàn bộ test/check (kể cả hidden, chỉ admin) |
| PUT | `/api/admin/questions/{id}` | Admin | Sửa câu hỏi (chỉ khi chưa dùng trong đề đã phát, hoặc chỉ sửa metadata theo luật đã chốt) |
| POST | `/api/admin/questions/{id}/validate` | Admin | Chạy đáp án mẫu qua toàn bộ test/check để kiểm tra spec, bắt buộc trước khi publish |
| POST | `/api/admin/questions/{id}/duplicate` | Admin | Nhân bản câu hỏi |
| GET | `/api/admin/code-exams` | Admin | Danh sách đề thi code |
| POST | `/api/admin/code-exams` | Admin | Tạo đề thi code |
| POST | `/api/admin/code-exams/{id}/questions` | Admin | Thêm câu hỏi vào đề (tạo snapshot) |
| DELETE | `/api/admin/code-exams/{id}/questions/{question_id}` | Admin | Xóa câu hỏi khỏi đề nháp |
| POST | `/api/admin/code-exams/{id}/questions/{question_id}/refresh` | Admin | Cập nhật snapshot từ ngân hàng (chỉ đề nháp) |
| POST | `/api/admin/code-exams/{id}/distribute` | Admin | Phát đề theo vòng đời kỳ thi |
| POST | `/api/admin/code-exams/{id}/regrade` | Admin | Chấm lại bài đã nộp khi sửa spec/snapshot |
| GET | `/api/student/code-exam` | Sinh viên | Đề thi được giao, danh sách câu hỏi (KHÔNG kèm test/check hidden) |
| POST | `/api/student/code/run` | Sinh viên | Pretest theo question_id — chỉ test/check visible |
| POST | `/api/student/code/submit` | Sinh viên | Nộp bài theo question_id và chấm toàn bộ test/check |
| GET | `/api/student/code/submission` | Sinh viên | Xem lại bài nộp theo question_id + kết quả (theo quyền hiển thị) |
| GET | `/api/admin/code-results` | Admin | Bảng điểm theo đề, theo sinh viên, theo từng câu hỏi |

### Giao diện admin — mục “Quản lý đề thi”

- Sidebar có mục “Quản lý đề thi” với 2 tab: **Ngân hàng câu hỏi** và **Đề thi**.
- Tab ngân hàng: danh sách, lọc, tạo/sửa, nhân bản, lưu trữ, nút “Chạy đáp án mẫu”, import/export spec JSON.
- Tab đề thi: danh sách đề, tạo đề, trình lắp đề (trái là ngân hàng có lọc, phải là câu hỏi đã chọn có kéo thứ tự), tổng điểm tự cộng, xem trước đề ở góc nhìn sinh viên, phát đề, bảng kết quả và nút chấm lại.
- Form tạo câu hỏi theo từng loại bằng dropdown, không bắt admin gõ JSON tay (reflection: field, constructor, method, behavior, toString template, comparable; stdio: stdin, expected, compare_mode).

### Giao diện sinh viên

- Trang làm bài của đề: danh sách câu hỏi bên trái, editor bên phải theo từng câu. MVP dùng `<textarea>` + xử lý phím Tab, không dùng CDN cho editor.
- Java reflection: tiêu đề file hiển thị rõ (ví dụ `Student.java`), nhắc package phải đúng theo đề.
- Java stdio: tiêu đề file và tên class có `main` hiển thị rõ, nhắc package theo spec (nếu spec để trống thì không cần package).
- Python stdio: editor Python, không yêu cầu tên file đặc biệt.
- Nút “Chạy thử” theo từng câu, chỉ hiện khi `allow_pretest=true`. Bảng kết quả pretest chỉ hiện test/check visible của câu đó.
- Nút “Nộp bài” theo từng câu, có xác nhận. Sau khi nộp, hiển thị theo `show_final_score_immediately`: hiện điểm ngay, hoặc chỉ hiện “Đã nộp” tới khi kết thúc kỳ thi.
- Đồng hồ đếm ngược hiển thị mỗi giây nhưng đồng bộ lại với server mỗi 5 giây; đồng hồ server mới là chuẩn để chặn nộp muộn.
- Lưu nháp code theo từng câu ở phía trình duyệt để tải lại trang không mất code đã gõ, và đồng bộ nháp lên server khi có thể.

## 13. Lộ trình triển khai (Windows-only)

### Phase 1 — Java Reflection (làm trước)

- [ ] Hoàn thiện `ReflectionJudge.java` và `app/java_runner.py` từ code khung, kèm Job Objects Windows (mục 10) và kiểm tra JDK lúc khởi động.
- [ ] Hoàn thiện `app/questions.py` cho câu hỏi reflection, route web, dữ liệu, audit, hiển thị điểm, regrade cho reflection.
- [ ] Hoàn thiện frontend ngân hàng cho reflection và trang sinh viên 1 câu hỏi reflection.
- [ ] Chạy checklist kiểm thử Phase 1 trong đặc tả Java (mục 8) trên máy Windows có JDK, cả bằng dòng lệnh và bằng web.
- **Xong Phase 1 khi:** Một lớp thi thử trên LAN Windows chạy được trọn vòng Java reflection bằng web, từ tạo câu hỏi tới chấm lại, mà không cần sửa code tay hay can thiệp dữ liệu tay.

### Phase 2 — Stdio cho cả Java và Python (làm sau Reflection)

- [ ] Hoàn thiện `app/code_runner.py` cho stdio, dùng chung khung runner, pretest, tính điểm, audit của reflection — một runner stdio cho cả hai ngôn ngữ.
- [ ] Mở rộng `app/questions.py` cho `grading_mode=stdio` với cả `language=java` và `language=python`, rẽ nhánh runner theo `language` + `grading_mode` trong cùng route chạy thử/nộp bài.
- [ ] Hoàn thiện frontend cho stdio: chọn ngôn ngữ trước rồi chọn dạng chấm, form test stdin/stdout, editor theo ngôn ngữ, bảng kết quả visible.
- **Xong Phase 2 khi:** Cùng hệ thống chạy được cả Java reflection, Java stdio và Python stdio bằng web, với cùng luật pretest, chấm cuối, hiển thị điểm và audit.

### Phase 3 — Đề thi từ ngân hàng (làm sau khi chấm từng câu đã chạy)

- [ ] Hoàn thiện `app/code_exams.py`: tạo đề, thêm/xóa câu hỏi, snapshot, cập nhật snapshot cho đề nháp, phát đề theo vòng đời, chấm lại theo đề.
- [ ] Hoàn thiện frontend tab Đề thi: trình lắp đề, kéo thứ tự, tổng điểm, xem trước, bảng kết quả theo đề và theo từng câu hỏi.
- [ ] Hoàn thiện trang sinh viên nhiều câu hỏi: điều hướng giữa các câu, lưu nháp theo từng câu, chạy thử và nộp bài theo từng câu, tổng điểm đề.
- **Xong Phase 3 khi:** Admin lắp được một đề thi từ nhiều câu hỏi trong ngân hàng, sinh viên làm và nộp từng câu, sửa ngân hàng sau khi phát đề không làm thay đổi đề đã phát.

### Phase 4 — Hardening Windows và nghiệm thu cuối (chỉ khi cần thi không giám sát, và nghiệm thu LAN)

- [ ] Chạy lại toàn bộ kiểm thử Phase 1 + 2 + 3 trên LAN Windows thật, rồi mới làm hardening nếu cần.
- [ ] Hardening (tùy chọn): thay backend runner bằng Windows Sandbox hoặc Docker Desktop trên Windows, giữ nguyên interface, spec và luồng chấm.
- [ ] Thêm timeout từng check / từng JVM cho Java reflection nếu cần, thay cho timeout toàn bộ lần chạy judge hiện tại.

### Không làm trong đợt này

- Public internet, Linux/macOS, Docker Linux, nsjail/bubblewrap, systemd, Nginx trên Linux.
- Đa file Java, Comparator class riêng, bài Python dạng import trực tiếp.
- Chấm bằng AI, chống đạo văn, WebSocket thay polling 5 giây.
- Gộp đề PDF cũ vào ngân hàng câu hỏi code.

## 14. Kiểm thử và nghiệm thu (tóm tắt, chi tiết trong checklist nhóm)

- **Java reflection:** mẫu đúng 100/100, sai modifier 90/100, sai toString 90/100, sai validator 85/100, lỗi biên dịch `CE` 0 điểm; pretest không chứa check hidden; đổi package sai thì fail load class; vòng lặp vô hạn → `TLE`, `System.exit()` → `RE`, runner không sập.
- **Stdio:** Java và Python đều test đúng/sai, timeout, output quá lớn, lỗi biên dịch/cú pháp, test hidden không lộ. Cùng một bộ test stdio, đổi ngôn ngữ vẫn chấm đúng theo compare_mode.
- **Ngân hàng + đề thi:** tạo 1 câu stdio và 1 câu reflection, dùng chung một câu hỏi trong 2 đề thi khác nhau, sửa ngân hàng sau khi đề đã phát thì đề đã phát không đổi, đề nháp thì cập nhật snapshot được, không thêm trùng câu hỏi vào cùng một đề.
- **Tích hợp web:** tạo câu hỏi → lắp đề → phát đề → bắt đầu thi → chạy thử từng câu → nộp bài từng câu → xem kết quả theo câu và theo đề → chấm lại, với 2–3 sinh viên cùng lúc, điểm không lẫn nhau.
- **LAN Windows thật:** máy giảng viên Windows làm server (có JDK), máy sinh viên Windows cùng phòng, kiểm tra URL LAN, Windows Firewall chỉ mở cổng cho mạng Private, và trường hợp sinh viên dùng Edge/Chrome khác nhau.
- **Sao lưu:** dừng server, copy `data/`, `logs/`, `submissions/`, `de-thi/` sang chỗ khác, khởi động lại vẫn thấy dữ liệu. Không commit dữ liệu chạy thật lên repo.
- **Đáp án mẫu:** đáp án mẫu phải đạt 100/100 qua spec đầy đủ trước khi phát hành câu hỏi. Nếu đáp án mẫu trượt check nào thì spec đó sai, phải sửa spec trước khi thi.

## 15. Rủi ro còn tồn tại — phải ghi trong tài liệu giảng viên

1. **Chưa chặn triệt để đọc file/mạng ở MVP:** Job Objects + timeout + thư mục tạm chưa chặn được việc code đọc file mà user chạy server có quyền đọc, hay gọi mạng. Chỉ container/máy ảo mới chặn triệt để. Vì vậy MVP chỉ dùng cho LAN có giám sát.
2. **Timeout Java reflection hiện tại tính cho toàn bộ lần chạy judge**, chưa phải từng check. Một check vòng lặp vô hạn sẽ làm mất các check sau trong cùng lần chạy.
3. **`toString` exact rất chặt:** sai một dấu cách, dấu phẩy, dấu nháy so với mẫu đã điền là mất trọn điểm check đó. Giảng viên phải ghi mẫu rõ trong đề và cho sinh viên chạy thử check `toString` visible trước khi thi thật (nếu đề cho phép pretest).
4. **JDK là điều kiện tiên quyết cho Java:** máy giảng viên không có JDK 17+ thì tính năng Java không chạy được, và lỗi phải hiện rõ lúc khởi động.
5. **Code khung Java chưa được chạy thử bằng Java trên máy của người viết đặc tả** (máy đó không có JDK). Nhóm phải chạy thử theo README của thư mục skeleton và tick hết checklist trong đặc tả Java trước khi coi Phase 1 là xong bước khung.
6. **Snapshot có thể gây nhầm nếu admin quên cập nhật đề nháp:** đề nháp sẽ không tự lấy bản mới nhất của ngân hàng. Admin phải bấm cập nhật snapshot hoặc thêm lại câu hỏi, và phải xem trước đề trước khi phát.
