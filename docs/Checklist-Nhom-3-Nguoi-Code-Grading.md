# Checklist chia task — Nhóm 3 người làm tính năng chấm code tự động

> **Phiên bản:** v2 — bản tạo lại, đã gộp toàn bộ quyết định mới nhất
> **Cập nhật:** 02/11/2026, cùng đợt với kế hoạch v3
> **Dự án:** ClassroomSubmissionServerSystem (Doc-Tay-Company)
> **Phạm vi phải hoàn thành:** Frontend + Backend, chuyên cho **Windows**, ngân hàng câu hỏi + đề thi, ưu tiên **Java reflection trước, stdio Java + Python sau**
> **Tài liệu gốc để đối chiếu:**
> - Kế hoạch v3: `Ke-hoach-Cham-Code-Tu-Dong-ClassroomSubmission.md`
> - Đặc tả Phase 1 Java: `Dac-ta-Phase1-Java-Reflection.md`
> - Code khung Phase 1 Java: `java-phase1-skeleton/` (ReflectionJudge.java, run_java.py, student-oop-spec.json, samples/)
> - Phân tích repo gốc: `README-ClassroomSubmissionServerSystem-Analysis.md`
>
> **Lưu ý về file bổ sung Windows cũ:** Các mục Windows trước đây nằm ở `Checklist-Bo-Sung-Windows-Code-Grading.md` (16 mục) nay đã gộp vào checklist này, ở đúng phần của từng người. Nhóm chỉ cần tick file này, không cần tick file bổ sung riêng nữa. File bổ sung cũ em vẫn để nguyên để khỏi mất, không xóa.
>
> **Cách dùng file này:**
> - Điền tên vào cột Người phụ trách ở đầu mỗi giai đoạn trước khi bắt đầu.
> - Tick `[x]` khi task xong **và đã qua kiểm tra của người khác**, không tick khi mới code xong chưa test.
> - Task nào bị chặn thì ghi rõ vào mục "Nhật ký blocker" cuối file, không tự đổi phạm vi để lách.
> - Chỉ Người 2 (Tích hợp server) mới merge vào `app/main.py` và nhánh chính.

## Quyết định đã chốt — không được tự ý đổi khi làm

- [ ] Phân loại câu hỏi bằng 2 chiều: `language` (java/python) và `grading_mode` (stdio/reflection). Tổ hợp hợp lệ duy nhất: Java + reflection, Java + stdio, Python + stdio.
- [ ] Java Reflection: **package bắt buộc theo yêu cầu từng đề bài** (ví dụ `model.Student`), sai package là fail check class.
- [ ] Java stdio: 1 file / 1 public class có `main`; package theo spec, spec để trống thì cho phép default package.
- [ ] Hiện tại chỉ **1 file / 1 public class** cho bài Java, chưa làm đa file.
- [ ] `toString` reflection: admin cung cấp **template có sẵn**, sinh viên phải trả về **exact sau khi điền template** (chỉ chuẩn hóa CRLF → LF, không dùng `contains` làm mặc định).
- [ ] Validator reflection: giá trị không hợp lệ phải ném **`IllegalArgumentException`** (predicate kiểu `isValid()` / `isPassing()` vẫn trả boolean, không thuộc quy tắc này).
- [ ] Comparator / Comparable: mặc định **không test `null`** trừ khi spec của check đó ghi rõ.
- [ ] Đề thi gồm **nhiều câu hỏi** từ ngân hàng, điểm đề bằng tổng điểm các câu hỏi.
- [ ] Dùng lại câu hỏi bằng **snapshot, không phải link sống**: sửa ngân hàng sau khi phát đề không làm thay đổi đề đã phát.
- [ ] Test/check ẩn **không bao giờ** được trả về frontend, không nằm trong HTML/JS/log phía sinh viên. Server lọc trước khi trả.
- [ ] Thứ tự: **Java reflection trước, stdio Java + Python sau, đề thi từ ngân hàng sau khi chấm từng câu đã chạy**.

## Vai trò và file sở hữu (để tránh dẫm chân nhau)

| Vai trò | Phụ trách chính | File sở hữu chính | Không ôm thêm |
|---|---|---|---|
| Người 1 — Judge Engine (backend lõi) | Chấm Java reflection, chấm stdio Java + Python, Job Objects Windows, tính điểm | `judge/ReflectionJudge.java`, `app/java_runner.py`, `app/code_runner.py`, `app/grading.py` (phần tính điểm) | Frontend |
| Người 2 — Tích hợp server (backend Python hiện có) | Ngân hàng, đề thi, API, dữ liệu, vòng đời kỳ thi, merge `main.py` | `app/questions.py`, `app/code_exams.py`, `app/main.py` (route), `data/*.json` (schema), `app/storage.py` (nếu cần sửa) | Judge engine |
| Người 3 — Frontend + QA cuối | Giao diện ngân hàng, đề thi, sinh viên nhiều câu hỏi, kiểm thử tổng | `templates/*.html`, `static/js/*.js`, `static/css/*` (nếu cần), checklist kiểm thử | Judge engine, `main.py` |

> Ghi tên thật vào đây trước khi bắt đầu:
> - Người 1 (Judge Engine): ________________
> - Người 2 (Tích hợp server): ________________
> - Người 3 (Frontend + QA): ________________

---

## Giai đoạn 0 — Chốt hợp đồng chung (cả 3 người, làm trước, không bỏ qua)

- [ ] Cả nhóm đọc chung kế hoạch v3 (mục 2, 4, 5, 10) và đặc tả Phase 1 Java (mục 3, 4, 5).
- [ ] Chốt và đóng băng format câu hỏi: `language`, `grading_mode`, `category`, `total_points`, và trường riêng theo dạng chấm (reflection: target_class/package/file/checks; stdio: tests stdin/expected/compare_mode).
- [ ] Chốt và đóng băng format spec reflection và format output của judge: `{score,total_points,checks:[{id,passed,points_earned,expected,actual,error}]}`.
- [ ] Chốt và đóng băng format snapshot đề thi: `question_id`, `snapshot_version`, `snapshot_at`, toàn bộ nội dung câu hỏi lúc snapshot, thứ tự trong đề.
- [ ] Chốt và đóng băng API (tên route, method, body, response, mã lỗi) cho: ngân hàng câu hỏi, validate bằng đáp án mẫu, đề thi, thêm/xóa/cập nhật snapshot, phát đề, chạy thử/nộp bài theo question_id, xem kết quả, chấm lại.
- [ ] Chốt quy tắc hiển thị: pretest chỉ check/test visible; chấm cuối hiện điểm ngay hay giấu điểm tới khi kết thúc kỳ thi (theo `show_final_score_immediately`).
- [ ] Chốt máy test Windows: máy giảng viên Windows 10/11 làm server, máy sinh viên Windows dùng Edge/Chrome. Không đưa hạng mục test Linux/macOS vào đợt này.
- [ ] Chốt cách chạy server: `.venv` + `setup_windows.bat` / `start_windows.bat` sẵn có của repo. Không dùng `start_unix.sh` trong tính năng này.
- [ ] Chốt JDK test: JDK 17+ cho Windows (ví dụ Microsoft OpenJDK hoặc Temurin), có `java` và `javac` trong `PATH` hoặc cấu hình `JAVA_HOME`.
- [ ] Chia nhánh git: mỗi người một nhánh, không commit trực tiếp lên nhánh chính, không commit `data/`, `logs/`, `submissions/`, file rác macOS `._*`, `.DS_Store`.
- [ ] Thống nhất cách kiểm tra JDK trước mỗi buổi test: `where javac`, `javac -version`, `java -version`.

**Xong Giai đoạn 0 khi:** Cả 3 người đều có thể kể lại được format câu hỏi, format snapshot, format output judge và danh sách API mà không cần mở lại file để đoán.

## Giai đoạn 1 — Java Reflection làm song song (không chờ nhau)

### Người 1 — Judge Engine (Java Reflection)

- [ ] Biên dịch được `ReflectionJudge.java` bằng `javac -d judge_out ReflectionJudge.java` trên máy Windows có JDK, không lỗi, không cần thêm thư viện ngoài.
- [ ] Judge kiểm tra được: field (tên, kiểu, modifier), constructor (tham số, modifier).
- [ ] Judge kiểm tra được: method (tên, kiểu trả về, tham số, modifier), `implements`.
- [ ] Judge kiểm tra được: behavior cho getter/setter — set rồi get lại phải đúng, không chỉ kiểm tra tên method.
- [ ] Judge kiểm tra được: validator — `setGpa(-1)` và các giá trị sai khác phải ném `IllegalArgumentException`, và phân biệt được với predicate trả boolean.
- [ ] Judge kiểm tra được: `toString` theo template + exact (điền placeholder `{name}`, `{gpa}` rồi so exact, chỉ chuẩn hóa CRLF → LF).
- [ ] Judge kiểm tra được: `Comparable` — dấu `compareTo` đúng, thứ tự sort đúng (gpa giảm dần, bằng nhau thì name tăng dần, theo spec mẫu).
- [ ] Judge xử lý đúng: overload (match theo tên + tham số, không match theo tên riêng), primitive vs Wrapper (`int` khác `Integer`), exception bị bọc trong `InvocationTargetException` phải mở ra mới so sánh.
- [ ] Mỗi check chạy độc lập: một check lỗi không làm sập cả bài, kết quả từng check ghi rõ `expected` vs `actual`.
- [ ] Hoàn thiện `run_java.py` thành `app/java_runner.py`: thư mục tạm riêng đúng cấu trúc package, `javac -encoding UTF-8`, timeout, `-Xmx suy ra từ memory_limit_mb, chừa headroom cho native JVM`, cắt output, luôn xóa thư mục tạm (trừ chế độ debug `--keep-temp`).
- [ ] Runner tạo một Job Object riêng cho mỗi lần chấm và gán process con vào job đó, bằng `ctypes` (Python stdlib, không thêm pywin32).
- [ ] Bật `JOBOBJECT_LIMIT_KILL_ON_JOB_CLOSE`: đóng job là kill toàn bộ process trong job, chống process con sống sót sau khi runner thoát.
- [ ] Bật `JOBOBJECT_LIMIT_ACTIVE_PROCESS`: giới hạn số process con, chống fork/process bomb ở mức cơ bản.
- [ ] Bật `JOBOBJECT_LIMIT_PROCESS_MEMORY` / `JOBOBJECT_LIMIT_JOB_MEMORY`: memory_limit_mb là tổng committed memory của Job (không phải working set), PROCESS_MEMORY là ceiling từng process.
- [ ] Nếu tạo Job Object thất bại trên máy đó: runner báo rõ, và **không lặng lẽ chạy không giới hạn** — admin phải biết máy đó đang chạy ở mức bảo vệ thấp hơn.
- [ ] Xử lý verdict: `CE` khi lỗi biên dịch (kèm output `javac` cắt ngắn), `TLE` khi quá timeout, `RE` khi JVM chết giữa chừng (ví dụ `System.exit()`), không làm sập runner.
- [ ] Chạy thử bằng dòng lệnh với spec mẫu `student-oop-spec.json` và ghi kết quả vào checklist kiểm thử ở Giai đoạn 1 (bên dưới).

**Kiểm thử Người 1 (bắt buộc, chạy trên máy Windows có JDK):**

- [ ] Mẫu `correct` chấm cuối: **100/100**, mọi check pass.
- [ ] Mẫu `correct` chạy pretest: **không chứa** check hidden `validator-gpa-negative` và `comparable`.
- [ ] Mẫu `wrong-modifier`: **90/100**, chỉ `field-name` fail (field `name` là `public`, kỳ vọng `private`).
- [ ] Mẫu `wrong-tostring`: **90/100**, chỉ `tostring` fail.
- [ ] Mẫu `validator-fail`: **85/100**, chỉ `validator-gpa-negative` fail.
- [ ] Mẫu `compile-error`: verdict `CE`, **0 điểm**, judge không chạy.
- [ ] Đổi package trong mẫu đúng thành package khác hoặc xóa dòng package: mọi check fail vì không load được `model.Student` (đây là hành vi đúng, không phải lỗi hệ thống).
- [ ] Test phá: vòng lặp vô hạn trong getter → `TLE`, runner không treo; `System.exit(0)` trong constructor → `RE`, runner không crash, chạy lại mẫu đúng ngay sau đó vẫn 100/100.
- [ ] Test phá: code đọc file spec trong constructor → ghi rõ kết quả và giới hạn (Phase 1 chưa có container, không được quảng cáo là đã chặn triệt để).

### Người 2 — Tích hợp server (Backend, ngân hàng reflection)

- [ ] Làm `app/questions.py` cho câu hỏi reflection: CRUD, validate spec — id check không trùng, `total_points` bằng tổng điểm các check, `target_package` bắt buộc, kiểu dữ liệu và modifier hợp lệ, đúng 1 file 1 class.
- [ ] Lưu ngân hàng vào `data/questions.json`, bài nộp vào `data/code_submissions.json`, lịch sử chạy thử vào `data/code_runs.json` (giới hạn số bản ghi, không để phình vô hạn).
- [ ] Làm route admin ngân hàng reflection: danh sách, tạo, sửa, xóa (chỉ khi chưa dùng trong đề đã phát, hoặc chỉ lưu trữ), xem chi tiết, chạy đáp án mẫu để validate spec, nhân bản.
- [ ] Làm route sinh viên cho 1 câu hỏi reflection: lấy câu hỏi được giao (không kèm check hidden), chạy thử, nộp bài, xem lại bài nộp cuối.
- [ ] Server kiểm tra lúc khởi động bằng lệnh tương đương `where javac`, `javac -version`, `java -version`. Thiếu JDK phải báo rõ ngay lúc khởi động, không để tới khi sinh viên nộp bài mới báo lỗi chung chung.
- [ ] Gắn vào vòng đời kỳ thi sẵn có: chỉ chấm khi đúng `release_id`, đã bắt đầu, còn trong giờ theo đồng hồ server, đúng `exam_state` (`distributed` → `started` → `ended`).
- [ ] Áp luật pretest: chỉ khi `allow_pretest=true` mới cho chạy thử, giới hạn số lần pretest và cooldown, giới hạn số lần chấm chạy cùng lúc.
- [ ] Áp luật hiển thị điểm: `show_final_score_immediately=false` thì sinh viên chỉ thấy "Đã nộp" cho tới khi kết thúc kỳ thi; `=true` thì hiện điểm + check visible.
- [ ] Áp luật nộp bài: trạng thái assignment chuyển sang `submitted` khi nộp code xong (nếu kỳ thi chỉ có bài code), force-submit của admin cũng đánh dấu được bài code.
- [ ] Ghi audit đầy đủ vào `logs/audit.jsonl`: tạo/sửa câu hỏi, chạy thử, nộp bài, chấm, chấm lại (ghi metadata + hash code, không ghi code đầy đủ hay test ẩn vào audit công khai).
- [ ] Thêm cột điểm/trạng thái code vào dashboard monitor của admin (dùng lại polling 5 giây sẵn có, không làm WebSocket mới ở MVP).
- [ ] Cập nhật `README.md` và `SPECIFICATION.md` của repo theo hướng Windows-only: không còn hướng dẫn Linux/macOS cho tính năng này, ghi rõ yêu cầu JDK và Job Objects.
- [ ] Test API bằng gọi trực tiếp (không cần frontend): tạo câu hỏi reflection → phát đề → bắt đầu thi → chạy thử → nộp bài → xem kết quả → chấm lại, tất cả đều qua với tài khoản admin và sinh viên test.

### Người 3 — Frontend (Ngân hàng reflection + sinh viên 1 câu hỏi)

> Làm trước bằng dữ liệu giả đúng format hợp đồng đã chốt ở Giai đoạn 0, không chờ backend xong mới làm UI.

- [ ] Admin — danh sách ngân hàng reflection: xem, tạo mới, nhân bản câu hỏi mẫu (ví dụ bài `Student`).
- [ ] Admin — form tạo/sửa câu hỏi reflection: tiêu đề, mô tả, `language` + `grading_mode`, `category`, package bắt buộc, file/class, thời gian, điểm, bật/tắt pretest, hiện điểm ngay hay giấu điểm.
- [ ] Admin — form tạo từng loại check bằng dropdown, không bắt admin gõ JSON tay: field, constructor, method, behavior (getter/setter, validator), toString (nhập template), comparable (nhập các case so sánh).
- [ ] Admin — import/export spec JSON, để chia sẻ câu hỏi và lưu version.
- [ ] Admin — nút "Chạy đáp án mẫu": paste đáp án mẫu, chạy qua toàn bộ spec, báo check nào đáp án mẫu còn trượt thì spec đó sai, phải sửa trước khi phát đề.
- [ ] Admin — bảng kết quả 1 câu hỏi: lọc theo sinh viên, xem code đã nộp, xem pass/fail từng check (admin thấy cả check hidden), nút chấm lại.
- [ ] Sinh viên — trang làm bài 1 câu hỏi reflection: hiển thị mô tả đề, editor 1 file, tiêu đề file hiển thị rõ (ví dụ `Student.java`), nhắc rõ "tên public class phải trùng tên file, package phải đúng theo đề", điền sẵn starter code.
- [ ] Sinh viên — editor: gõ được code, phím Tab không nhảy focus lung tung, lưu nháp (ít nhất ở phía trình duyệt) để tải lại trang không mất code đã gõ.
- [ ] Sinh viên — nút "Chạy thử": chỉ hiện khi `allow_pretest=true`, hiển thị bảng từng check visible, stdout/lỗi nếu có, và ghi rõ "đây chưa phải điểm cuối".
- [ ] Sinh viên — nút "Nộp bài": có xác nhận trước khi nộp, hiển thị trạng thái sau khi nộp theo đúng luật hiển thị điểm đã chốt.
- [ ] Sinh viên — đồng hồ đếm ngược vẫn đồng bộ với server (không tin đồng hồ máy sinh viên), hết giờ thì khóa nút chạy thử/nộp bài theo đúng luật server.
- [ ] Sinh viên — thông báo lỗi dễ hiểu bằng tiếng Việt cho `CE` (lỗi biên dịch), `TLE` (quá thời gian), `RE` (lỗi khi chạy), thay vì dump lỗi Java thô.
- [ ] Frontend **không** tự lọc test ẩn, không giấu test ẩn bằng CSS/JS — việc lọc là của server, frontend chỉ hiển thị những gì server trả về.

## Giai đoạn 2 — Stdio cho cả Java và Python (làm sau Reflection)

### Người 1 — Runner stdio chung

- [ ] Làm `app/code_runner.py` cho stdio, dùng chung một khung cho cả Java và Python, không làm hai runner stdio riêng.
- [ ] Java stdio: đặt file đúng cấu trúc package theo spec, `javac -encoding UTF-8`, rồi chạy `java` với stdin pipe cho từng test; lỗi biên dịch → `CE`.
- [ ] Python stdio: chạy `python.exe` với stdin pipe cho từng test, không import code sinh viên vào process server.
- [ ] So sánh output theo 4 mode: `exact`, `normalized` (mặc định), `tokens`, `float_tolerance`.
- [ ] Xử lý verdict stdio: `AC`, `WA`, `TLE`, `MLE` (khi đo được), `RE`, `CE`, `OLE`.
- [ ] Áp Job Objects Windows cho cả runner stdio Java và Python, giống như runner reflection: KILL_ON_JOB_CLOSE, giới hạn process, giới hạn RAM, báo rõ khi tạo job thất bại.
- [ ] Test phá stdio: vòng lặp vô hạn, in vô hạn, đọc file test, lỗi cú pháp/biên dịch, output quá lớn, cùng một bộ test đổi ngôn ngữ vẫn chấm đúng theo compare_mode.

### Người 2 — Tích hợp server (stdio)

- [ ] Mở rộng `app/questions.py` cho `grading_mode=stdio` với cả `language=java` và `language=python`: test gồm `stdin`, `expected_stdout`, `is_visible`, `points`, `compare_mode`.
- [ ] Rẽ nhánh runner theo `language` + `grading_mode` trong cùng route chạy thử/nộp bài đã làm cho reflection, không tạo hệ thống nộp bài riêng cho stdio.
- [ ] Dùng lại luật pretest, hiển thị điểm, audit, regrade, force-submit đã làm cho reflection.
- [ ] Test API stdio bằng gọi trực tiếp: tạo câu hỏi Java stdio và Python stdio → chạy thử → nộp bài → xem kết quả → chấm lại, đều qua với tài khoản admin và sinh viên test.

### Người 3 — Frontend (stdio)

- [ ] Thêm chọn ngôn ngữ trước rồi chọn dạng chấm khi tạo câu hỏi (Java hiện đủ stdio + chấm class, Python chỉ hiện stdio).
- [ ] Form test stdio: nhập `stdin`, `expected_stdout`, chọn visible/hidden, điểm, compare_mode, import test từ JSON.
- [ ] Trang sinh viên cho stdio: editor theo ngôn ngữ (Java: nhắc tên class có `main` và package theo spec; Python: editor Python), nút chạy thử chỉ chạy test visible, bảng kết quả hiện stdout thực tế vs kỳ vọng cho test visible.

**Xong Giai đoạn 2 khi:** Cùng một hệ thống chạy được cả Java reflection, Java stdio và Python stdio bằng web, với cùng luật pretest, chấm cuối, hiển thị điểm và audit.

## Giai đoạn 3 — Đề thi từ ngân hàng (làm sau khi chấm từng câu đã chạy)

### Người 2 — Tích hợp server (đề thi)

- [ ] Làm `app/code_exams.py`: tạo đề, thêm/xóa câu hỏi, snapshot, cập nhật snapshot cho đề nháp, phát đề theo vòng đời, chấm lại theo đề.
- [ ] Khi thêm câu hỏi vào đề, tạo snapshot đầy đủ kèm `question_id`, `snapshot_version`, `snapshot_at`, thứ tự trong đề. Không cho thêm trùng một câu hỏi hai lần vào cùng một đề.
- [ ] Đề đã phát thì không được sửa nội dung câu hỏi trong đề nữa; đề nháp thì cho cập nhật snapshot từ ngân hàng hoặc xóa rồi thêm lại.
- [ ] Lưu bài nộp theo `exam_id` + `question_id`, điểm đề bằng tổng điểm các câu hỏi trong đề, kết quả theo đề và theo từng câu hỏi đều xem được.
- [ ] Ghi audit cho tạo đề, thêm/xóa câu hỏi, phát đề, chấm lại theo đề.

### Người 3 — Frontend (mục “Quản lý đề thi” + sinh viên nhiều câu hỏi)

- [ ] Sidebar có mục “Quản lý đề thi” với 2 tab: **Ngân hàng câu hỏi** và **Đề thi**.
- [ ] Tab ngân hàng hoàn thiện: lọc theo language, grading_mode, category, từ khóa, trạng thái, số lần đã dùng; tạo/sửa, nhân bản, lưu trữ câu hỏi.
- [ ] Tab đề thi: tạo đề, trình lắp đề (trái là ngân hàng có lọc, phải là câu hỏi đã chọn có kéo thứ tự), tổng điểm tự cộng, xem trước đề ở góc nhìn sinh viên, phát đề.
- [ ] Tab đề thi: bảng kết quả theo đề (lọc theo sinh viên, điểm từng câu, tổng điểm đề), nút chấm lại theo đề hoặc theo từng câu hỏi.
- [ ] Sinh viên — trang làm bài nhiều câu hỏi: danh sách câu hỏi bên trái, editor bên phải theo từng câu, lưu nháp theo từng câu, điều hướng giữa các câu không mất code.
- [ ] Sinh viên — chạy thử và nộp bài theo từng câu, bảng kết quả theo từng câu, tổng điểm đề hiển thị đúng theo `show_final_score_immediately`.
- [ ] Kiểm tra snapshot bằng tay: sửa ngân hàng sau khi đề đã phát thì đề đã phát không đổi; đề nháp thì cập nhật snapshot được; không thêm trùng câu hỏi vào cùng một đề.

**Xong Giai đoạn 3 khi:** Admin lắp được một đề thi từ nhiều câu hỏi trong ngân hàng, sinh viên làm và nộp từng câu, sửa ngân hàng sau khi phát đề không làm thay đổi đề đã phát.

## Giai đoạn 4 — Tích hợp tập trung + nghiệm thu LAN Windows (cả 3 người)

- [ ] Thay judge giả (nếu còn) bằng judge thật của Người 1, thay dữ liệu giả của Người 3 bằng API thật của Người 2, cho cả reflection, stdio và đề thi.
- [ ] Chạy trọn vòng bằng web (không chỉ dòng lệnh): tạo câu hỏi → lắp đề từ ngân hàng → phát đề → bắt đầu thi → sinh viên chạy thử từng câu → nộp bài từng câu → admin xem kết quả theo câu và theo đề → admin chấm lại.
- [ ] Kiểm tra lọc test/check ẩn bằng cách gọi trực tiếp API phía sinh viên và xem response: response **không chứa** stdin/expected của test/check hidden, không chứa spec đầy đủ.
- [ ] Kiểm tra đồng hồ thi: đổi giờ máy sinh viên không làm thay đổi deadline, nộp sau `ends_at` bị server từ chối.
- [ ] Kiểm tra force-submit, khóa/mở tài khoản, reset mật khẩu vẫn hoạt động với bài code như với bài ZIP.
- [ ] Kiểm tra 2–3 sinh viên cùng bấm chạy thử/nộp gần như cùng lúc: điểm không lẫn nhau, mỗi lần chấm một thư mục tạm riêng, server không nghẽn.
- [ ] Chạy thử trên LAN thật: máy giảng viên Windows làm server (có JDK), 2–3 máy sinh viên Windows cùng phòng, kiểm tra URL LAN, Windows Firewall chỉ mở cổng cho mạng Private/trusted LAN, **không mở cho mạng Public, không bật HTTP ra internet**, và sinh viên dùng Edge/Chrome khác nhau.
- [ ] Tài liệu giảng viên ghi rõ giới hạn còn tồn tại ở MVP LAN: code sinh viên vẫn có thể đọc file mà user chạy server có quyền đọc và gọi mạng nếu biết đường dẫn — chỉ container/máy ảo mới chặn triệt để hai thứ này, nên MVP chỉ phù hợp phòng học LAN có giảng viên giám sát trực tiếp.
- [ ] Ghi rõ trong tài liệu giảng viên: Job Objects **không chặn đọc file, không chặn mạng** — chỉ giới hạn process, RAM và kill khi đóng job. Đừng quảng cáo là đã chặn triệt để.
- [ ] Sửa hết bug tích hợp trước khi coi là xong, ghi bug và người sửa vào nhật ký cuối file.
- [ ] Chạy lại toàn bộ kiểm thử của Người 1 trên bản web, không chỉ bản dòng lệnh.
- [ ] Chạy checklist kiểm thử Phase 1 Java (đặc tả mục 6) lần cuối trên bản web.
- [ ] Kiểm tra sao lưu/khôi phục: dừng server, copy `data/`, `logs/`, `submissions/`, `de-thi/` sang chỗ khác, khởi động lại vẫn thấy dữ liệu.
- [ ] Dọn repo: xóa file rác, kiểm tra `.gitignore` không để lọt `data/`, `logs/`, `submissions/` (dữ liệu chạy thật) và file `._*`, `.DS_Store` nếu nhóm quyết định dọn.
- [ ] Cập nhật tài liệu cuối: `README.md` (cách chạy Windows, cách tạo câu hỏi/đề thi, yêu cầu JDK), `SPECIFICATION.md` (mô hình dữ liệu mới, API mới, luật chấm), hướng dẫn ngắn cho giảng viên và sinh viên.
- [ ] Demo cuối cho nhóm: một admin tạo câu hỏi, lắp đề, một sinh viên làm đúng được 100/100 ở một câu, một sinh viên làm sai validator/toString bị trừ đúng điểm đã thiết kế, admin chấm lại sau khi sửa spec vẫn giữ lịch sử điểm cũ.

**Xong Giai đoạn 4 khi:** Một lớp thi thử nhỏ trên LAN Windows chạy được trọn vòng bằng web, từ ngân hàng câu hỏi tới đề thi, chấm lại, mà không cần sửa code tay hay can thiệp database tay.

**Không làm trong đợt này (để phase sau, đừng tự thêm vào làm trễ MVP):**

- [ ] Windows Sandbox / Docker Desktop trên Windows trong MVP (Sandbox cần Windows Pro + Hyper-V, Docker Desktop cần WSL2) — chỉ làm khi cần thi không giám sát, và khi đó chỉ thay backend runner, giữ nguyên interface, spec và luồng chấm.
- [ ] Docker Linux / sandbox Linux (nsjail, bubblewrap, systemd, Nginx trên Linux), public web, Linux/macOS.
- [ ] Đa file Java, Comparator dạng class riêng, bài viết hàm Python dạng import trực tiếp.
- [ ] Chấm bằng AI, chống đạo văn, chấm chất lượng code/phong cách.
- [ ] Gộp đề PDF cũ vào ngân hàng câu hỏi code.
- [ ] WebSocket thay polling 5 giây cho dashboard (giữ polling ở MVP).

---

## Nhật ký blocker (điền khi bị kẹt, không xóa)

| Ngày | Người bị chặn | Blocker là gì | Cần ai giúp / cần quyết định gì | Đã xử lý chưa |
|---|---|---|---|---|
| | | | | |
| | | | | |

## Ký xác nhận hoàn thành

- [ ] Người 1 xác nhận: Judge Engine + runner reflection/stdio + Job Objects Windows đã qua hết kiểm thử của mình.
- [ ] Người 2 xác nhận: Ngân hàng, đề thi, API + dữ liệu + vòng đời kỳ thi đã chạy end-to-end bằng web.
- [ ] Người 3 xác nhận: Frontend ngân hàng + đề thi + sinh viên nhiều câu hỏi đã chạy trọn vòng và không lộ test/check ẩn.
- [ ] Cả nhóm xác nhận: Demo cuối đã chạy được trên LAN Windows thật với máy có JDK.
