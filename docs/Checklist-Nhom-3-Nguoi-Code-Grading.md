
## Checklist chia task — Nhóm 3 người làm tính năng chấm code tự động

> **Dự án:** ClassroomSubmissionServerSystem (Doc-Tay-Company)
> **Phạm vi phải hoàn thành:** Frontend + Backend, ưu tiên **Java trước, Python sau**
> **Tài liệu gốc để đối chiếu:**
> - Kế hoạch tổng: `Ke-hoach-Cham-Code-Tu-Dong-ClassroomSubmission.md`
> - Đặc tả Phase 1 Java: `Dac-ta-Phase1-Java-Reflection.md`
> - Code khung Phase 1 Java: `java-phase1-skeleton/` (ReflectionJudge.java, run_java.py, student-oop-spec.json, samples/)
> - Phân tích repo gốc: `README-ClassroomSubmissionServerSystem-Analysis.md`
>
> **Cách dùng file này:**
> - Điền tên vào cột Người phụ trách ở đầu mỗi giai đoạn trước khi bắt đầu.
> - Tick `[x]` khi task xong **và đã qua kiểm tra của người khác**, không tick khi mới code xong chưa test.
> - Task nào bị chặn thì ghi rõ vào mục "Nhật ký blocker" cuối file, không tự đổi phạm vi để lách.
> - Chỉ Người 2 (Tích hợp server) mới merge vào `app/main.py` và nhánh chính.

## Quyết định đã chốt — không được tự ý đổi khi làm

- [ ] Package **bắt buộc theo yêu cầu từng đề bài** (ví dụ `model.Student`), sai package là fail check class.
- [ ] Hiện tại chỉ **1 file / 1 public class** cho bài Java, chưa làm đa file.
- [ ] `toString`: admin cung cấp **template có sẵn**, sinh viên phải trả về **exact sau khi điền template** (chỉ chuẩn hóa CRLF → LF, không dùng `contains` làm mặc định).
- [ ] Validator: giá trị không hợp lệ phải ném **`IllegalArgumentException`** (predicate kiểu `isValid()` / `isPassing()` vẫn trả boolean, không thuộc quy tắc này).
- [ ] Thứ tự: **Java trước, Python sau**.
- [ ] Comparator / Comparable: mặc định **không test `null`** trừ khi spec của check đó ghi rõ.
- [ ] Test ẩn **không bao giờ** được trả về frontend, không nằm trong HTML/JS/log phía sinh viên. Server lọc trước khi trả.

## Vai trò và file sở hữu (để tránh dẫm chân nhau)

| Vai trò | Phụ trách chính | File sở hữu chính | Không ôm thêm |
|---|---|---|---|
| Người 1 — Judge Engine (backend lõi) | Chấm Java + chấm Python, sandbox, tính điểm | `judge/ReflectionJudge.java`, `app/java_runner.py`, `app/code_runner.py`, `app/grading.py` (phần tính điểm) | Frontend |
| Người 2 — Tích hợp server (backend Python hiện có) | API, dữ liệu, vòng đời kỳ thi, merge `main.py` | `app/problems.py`, `app/main.py` (route), `data/*.json` (schema), `app/storage.py` (nếu cần sửa) | Judge engine |
| Người 3 — Frontend + QA cuối | Giao diện admin + sinh viên, kiểm thử tổng | `templates/*.html`, `static/js/*.js`, `static/css/*` (nếu cần), checklist kiểm thử | Judge engine, `main.py` |

> Ghi tên thật vào đây trước khi bắt đầu:
> - Người 1 (Judge Engine): ________________
> - Người 2 (Tích hợp server): ________________
> - Người 3 (Frontend + QA): ________________

---

## Giai đoạn 0 — Chốt hợp đồng chung (cả 3 người, làm trước, không bỏ qua)

- [ ] Cả nhóm đọc chung đặc tả Phase 1 Java (mục 3, 4, 5) và kế hoạch tổng (mục 4, 6, 8, 9).
- [ ] Chốt và đóng băng format spec JSON bài Java: `target_class`, `target_package`, `target_file`, `checks[]` (id, kind, points, is_visible).
- [ ] Chốt và đóng băng format output của judge: `{target_class, score, total_points, checks: [{id, kind, passed, points, points_earned, expected, actual, error, time_ms}]}`.
- [ ] Chốt và đóng băng API (tên route, method, body, response, mã lỗi) cho: tạo đề, lấy đề, chạy thử, nộp bài, xem bài nộp, xem kết quả admin, chấm lại, validate bằng đáp án mẫu.
- [ ] Chốt quy tắc hiển thị: pretest chỉ check visible; chấm cuối hiện điểm ngay hay giấu điểm tới khi kết thúc kỳ thi (theo `show_final_score_immediately` trong spec).
- [ ] Chia nhánh git: mỗi người một nhánh, không commit trực tiếp lên nhánh chính, không commit `data/`, `logs/`, `submissions/`, file rác macOS `._*`, `.DS_Store`.
- [ ] Thống nhất máy test có JDK 17+ để chạy Java, và cách kiểm tra `java -version`, `javac -version` trước mỗi buổi test.

**Xong Giai đoạn 0 khi:** Cả 3 người đều có thể kể lại được format spec, format output judge và danh sách API mà không cần mở lại file để đoán.

---

## Giai đoạn 1 — Java MVP làm song song (không chờ nhau)

### Người 1 — Judge Engine (Java)

- [ ] Biên dịch được `ReflectionJudge.java` bằng `javac -d judge_out ReflectionJudge.java` trên máy có JDK, không lỗi, không cần thêm thư viện ngoài.
- [ ] Judge kiểm tra được: field (tên, kiểu, modifier), constructor (tham số, modifier).
- [ ] Judge kiểm tra được: method (tên, kiểu trả về, tham số, modifier), `implements`.
- [ ] Judge kiểm tra được: behavior cho getter/setter — set rồi get lại phải đúng, không chỉ kiểm tra tên method.
- [ ] Judge kiểm tra được: validator — `setGpa(-1)` và các giá trị sai khác phải ném `IllegalArgumentException`, và phân biệt được với predicate trả boolean.
- [ ] Judge kiểm tra được: `toString` theo template + exact (điền placeholder `{name}`, `{gpa}` rồi so exact, chỉ chuẩn hóa CRLF → LF).
- [ ] Judge kiểm tra được: `Comparable` — dấu `compareTo` đúng, thứ tự sort đúng (gpa giảm dần, bằng nhau thì name tăng dần, theo spec mẫu).
- [ ] Judge xử lý đúng: overload (match theo tên + tham số, không match theo tên riêng), primitive vs Wrapper (`int` khác `Integer`), exception bị bọc trong `InvocationTargetException` phải mở ra mới so sánh.
- [ ] Mỗi check chạy độc lập: một check lỗi không làm sập cả bài, kết quả từng check ghi rõ `expected` vs `actual`.
- [ ] Hoàn thiện `run_java.py` thành `app/java_runner.py`: thư mục tạm riêng đúng cấu trúc package, `javac -encoding UTF-8`, timeout, `-Xmx256m`, cắt output, luôn xóa thư mục tạm (trừ chế độ debug `--keep-temp`).
- [ ] Xử lý verdict: `CE` khi lỗi biên dịch (kèm output `javac` cắt ngắn), `TLE` khi quá timeout, `RE` khi JVM chết giữa chừng (ví dụ `System.exit()`), không làm sập runner.
- [ ] Chạy thử bằng dòng lệnh với spec mẫu `student-oop-spec.json` và ghi kết quả vào checklist kiểm thử ở Giai đoạn 1 (bên dưới).

**Kiểm thử Người 1 (bắt buộc, chạy trên máy có JDK):**

- [ ] Mẫu `correct` chấm cuối: **100/100**, mọi check pass.
- [ ] Mẫu `correct` chạy pretest: **không chứa** check hidden `validator-gpa-negative` và `comparable`.
- [ ] Mẫu `wrong-modifier`: **90/100**, chỉ `field-name` fail (field `name` là `public`, kỳ vọng `private`).
- [ ] Mẫu `wrong-tostring`: **90/100**, chỉ `tostring` fail.
- [ ] Mẫu `validator-fail`: **85/100**, chỉ `validator-gpa-negative` fail.
- [ ] Mẫu `compile-error`: verdict `CE`, **0 điểm**, judge không chạy.
- [ ] Đổi package trong mẫu đúng thành package khác hoặc xóa dòng package: mọi check fail vì không load được `model.Student` (đây là hành vi đúng, không phải lỗi hệ thống).
- [ ] Test phá: vòng lặp vô hạn trong getter → `TLE`, runner không treo; `System.exit(0)` trong constructor → `RE`, runner không crash, chạy lại mẫu đúng ngay sau đó vẫn 100/100.
- [ ] Test phá: code đọc file spec trong constructor → ghi rõ kết quả và giới hạn (Phase 1 chưa có container, không được quảng cáo là đã chặn triệt để).

### Người 2 — Tích hợp server (Backend)

- [ ] Làm `app/problems.py`: CRUD đề code, validate spec — id check không trùng, `total_points` bằng tổng điểm các check, `target_package` bắt buộc, kiểu dữ liệu và modifier hợp lệ, đúng 1 file 1 class.
- [ ] Lưu spec vào `data/problems.json`, bài nộp vào `data/code_submissions.json`, lịch sử chạy thử vào `data/code_runs.json` (giới hạn số bản ghi, không để phình vô hạn).
- [ ] Làm route admin: danh sách đề, tạo đề, sửa đề, xóa đề (chỉ trước khi phát đề hoặc theo luật đã chốt), xem kết quả, chấm lại (regrade), chạy đáp án mẫu để validate spec.
- [ ] Làm route sinh viên: lấy đề được giao (không kèm test ẩn), chạy thử, nộp bài, xem lại bài nộp cuối.
- [ ] Gắn vào vòng đời kỳ thi sẵn có: chỉ chấm khi đúng `release_id`, đã bắt đầu, còn trong giờ theo đồng hồ server, đúng `exam_state` (`distributed` → `started` → `ended`).
- [ ] Áp luật pretest: chỉ khi `allow_pretest=true` mới cho chạy thử, giới hạn số lần pretest và cooldown, giới hạn số lần chấm chạy cùng lúc.
- [ ] Áp luật hiển thị điểm: `show_final_score_immediately=false` thì sinh viên chỉ thấy "Đã nộp" cho tới khi kết thúc kỳ thi; `=true` thì hiện điểm + check visible.
- [ ] Áp luật nộp bài: trạng thái assignment chuyển sang `submitted` khi nộp code xong (nếu kỳ thi chỉ có bài code), force-submit của admin cũng đánh dấu được bài code.
- [ ] Ghi audit đầy đủ vào `logs/audit.jsonl`: tạo đề, sửa spec, phát đề, chạy thử, nộp bài, chấm, chấm lại, tải bài, force-submit (ghi metadata + hash code, không ghi code đầy đủ vào audit công khai nếu không cần).
- [ ] Thêm cột điểm/trạng thái code vào dashboard monitor của admin (dùng lại polling 5 giây sẵn có, không làm WebSocket mới ở MVP).
- [ ] Cập nhật `README.md` và `SPECIFICATION.md` của repo theo đúng những gì đã làm, không để tài liệu lệch code.
- [ ] Test API bằng gọi trực tiếp (không cần frontend): tạo đề → phát đề → bắt đầu thi → chạy thử → nộp bài → xem kết quả → chấm lại, tất cả đều qua với tài khoản admin và sinh viên test.

### Người 3 — Frontend (Admin + Sinh viên)

> Làm trước bằng dữ liệu giả đúng format hợp đồng đã chốt ở Giai đoạn 0, không chờ backend xong mới làm UI.

- [ ] Admin — danh sách đề: xem, tạo mới, nhân bản đề mẫu (ví dụ bài `Student`).
- [ ] Admin — form tạo/sửa đề: tiêu đề, mô tả, package bắt buộc, file/class, thời gian, điểm, bật/tắt pretest, hiện điểm ngay hay giấu điểm.
- [ ] Admin — form tạo từng loại check bằng dropdown, không bắt admin gõ JSON tay: field, constructor, method, behavior (getter/setter, validator), toString (nhập template), comparable (nhập các case so sánh).
- [ ] Admin — import/export spec JSON, để chia sẻ đề và lưu version.
- [ ] Admin — nút "Chạy đáp án mẫu": paste đáp án mẫu, chạy qua toàn bộ spec, báo check nào đáp án mẫu còn trượt thì spec đó sai, phải sửa trước khi phát đề.
- [ ] Admin — bảng kết quả: lọc theo sinh viên, xem code đã nộp, xem pass/fail từng check (admin thấy cả check hidden), nút chấm lại.
- [ ] Sinh viên — trang làm bài: hiển thị mô tả đề, editor 1 file, tiêu đề file hiển thị rõ (ví dụ `Student.java`), nhắc rõ "tên public class phải trùng tên file, package phải đúng theo đề", điền sẵn starter code.
- [ ] Sinh viên — editor: gõ được code, phím Tab không nhảy focus lung tung, lưu nháp (ít nhất ở phía trình duyệt) để tải lại trang không mất code đã gõ.
- [ ] Sinh viên — nút "Chạy thử": chỉ hiện khi `allow_pretest=true`, hiển thị bảng từng check visible, stdout/lỗi nếu có, và ghi rõ "đây chưa phải điểm cuối".
- [ ] Sinh viên — nút "Nộp bài": có xác nhận trước khi nộp, hiển thị trạng thái sau khi nộp theo đúng luật hiển thị điểm đã chốt.
- [ ] Sinh viên — đồng hồ đếm ngược vẫn đồng bộ với server (không tin đồng hồ máy sinh viên), hết giờ thì khóa nút chạy thử/nộp bài theo đúng luật server.
- [ ] Sinh viên — thông báo lỗi dễ hiểu bằng tiếng Việt cho `CE` (lỗi biên dịch), `TLE` (quá thời gian), `RE` (lỗi khi chạy), thay vì dump lỗi Java thô.
- [ ] Frontend **không** tự lọc test ẩn, không giấu test ẩn bằng CSS/JS — việc lọc là của server, frontend chỉ hiển thị những gì server trả về.

---

## Giai đoạn 2 — Tích hợp tập trung (cả 3 người, không làm riêng)

- [ ] Thay judge giả của Người 2 bằng judge thật của Người 1, thay dữ liệu giả của Người 3 bằng API thật của Người 2.
- [ ] Chạy trọn vòng Java bằng web (không chỉ dòng lệnh): admin tạo đề → phát đề → bắt đầu thi → sinh viên chạy thử → nộp bài → admin xem kết quả → admin chấm lại.
- [ ] Kiểm tra lọc test ẩn bằng cách gọi trực tiếp API phía sinh viên và xem response: response **không chứa** stdin/expected của check hidden, không chứa spec đầy đủ.
- [ ] Kiểm tra đồng hồ thi: đổi giờ máy sinh viên không làm thay đổi deadline, nộp sau `ends_at` bị server từ chối.
- [ ] Kiểm tra force-submit, khóa/mở tài khoản, reset mật khẩu vẫn hoạt động với bài code như với bài ZIP.
- [ ] Kiểm tra 2–3 sinh viên cùng bấm chạy thử/nộp gần như cùng lúc: điểm không lẫn nhau, mỗi lần chấm một thư mục tạm riêng, server không nghẽn.
- [ ] Sửa hết bug tích hợp trước khi sang Python, ghi bug và người sửa vào nhật ký cuối file.
- [ ] Chạy lại toàn bộ kiểm thử của Người 1 trên bản web, không chỉ bản dòng lệnh.

**Xong Giai đoạn 2 khi:** Một lớp thi thử nhỏ trên LAN (máy giảng viên có JDK) chạy được trọn vòng Java bằng web, từ tạo đề tới chấm lại, mà không cần sửa code tay hay can thiệp database tay.

---

## Giai đoạn 3 — Python (sau khi Java đã chạy được trên web)

### Người 1 — Runner Python

- [ ] Làm `app/code_runner.py` (Python stdlib, subprocess riêng, thư mục tạm riêng, timeout từng test, cắt stdout/stderr, env tối thiểu).
- [ ] So sánh output theo 4 mode: `exact`, `normalized` (mặc định), `tokens`, `float_tolerance`.
- [ ] Xử lý verdict Python: `AC`, `WA`, `TLE`, `MLE` (khi đo được), `RE`, `CE` (lỗi cú pháp, phát hiện sớm), `OLE`.
- [ ] Test phá Python: vòng lặp vô hạn, in vô hạn, đọc file test, lỗi cú pháp, output quá lớn.

### Người 2 — Tích hợp Python vào server

- [ ] Mở rộng `app/problems.py` cho `problem_kind=python_stdio`: test case gồm `stdin`, `expected_stdout`, `is_visible`, `points`, `compare_mode`.
- [ ] Rẽ nhánh runner theo `problem_kind` trong cùng route chạy thử/nộp bài đã làm cho Java, không tạo hệ thống nộp bài riêng cho Python.
- [ ] Dùng lại luật pretest, hiển thị điểm, audit, regrade, force-submit đã làm cho Java.

### Người 3 — Frontend cho Python

- [ ] Thêm chọn loại đề Java/Python khi tạo đề (admin không bị nhầm loại).
- [ ] Form test Python: nhập `stdin`, `expected_stdout`, chọn visible/hidden, điểm, compare mode, import test từ JSON.
- [ ] Trang sinh viên cho Python: editor Python, nút chạy thử chỉ chạy test visible, bảng kết quả hiện stdout thực tế vs kỳ vọng cho test visible.

**Xong Giai đoạn 3 khi:** Cùng một kỳ thi (hoặc hai kỳ thi riêng, tùy cấu hình nhóm chốt) chạy được cả bài Java và bài Python bằng web, với cùng luật pretest, chấm cuối, hiển thị điểm và audit.

---

## Giai đoạn 4 — Hoàn thiện, tài liệu và nghiệm thu cuối

- [ ] Chạy checklist kiểm thử Phase 1 Java (đặc tả mục 6) lần cuối trên bản web, không chỉ bản dòng lệnh.
- [ ] Chạy thử trên LAN thật: máy giảng viên làm server (có JDK), 2–3 máy sinh viên cùng phòng, cùng mạng, kiểm tra URL LAN, firewall cổng, và trường hợp sinh viên dùng trình duyệt khác nhau.
- [ ] Kiểm tra sao lưu/khôi phục: dừng server, copy `data/`, `logs/`, `submissions/`, `de-thi/` (và thư mục đề code mới nếu có) sang chỗ khác, khởi động lại vẫn thấy dữ liệu.
- [ ] Dọn repo: xóa file rác, kiểm tra `.gitignore` không để lọt `data/`, `logs/`, `submissions/` (dữ liệu chạy thật) và file `._*`, `.DS_Store` nếu nhóm quyết định dọn.
- [ ] Cập nhật tài liệu cuối: `README.md` (cách chạy, cách tạo đề Java/Python, yêu cầu JDK), `SPECIFICATION.md` (mô hình dữ liệu mới, API mới, luật chấm), hướng dẫn ngắn cho giảng viên và sinh viên.
- [ ] Ghi rõ giới hạn còn tồn tại trong tài liệu giảng viên: chưa có container/Docker, chưa chặn triệt để đọc file/mạng khi thi online với người lạ, timeout hiện tại tính cho toàn bộ lần chạy judge (chưa phải từng check), `toString` exact rất chặt — những mục này để phase sau, không quảng cáo là đã an toàn tuyệt đối.
- [ ] Demo cuối cho nhóm: một admin tạo đề, một sinh viên làm đúng được 100/100, một sinh viên làm sai validator/toString bị trừ đúng điểm đã thiết kế, admin chấm lại sau khi sửa spec vẫn giữ lịch sử điểm cũ.

**Không làm trong đợt này (để phase sau, đừng tự thêm vào làm trễ MVP):**

- [ ] Docker / judge worker tách biệt / public web (đi chung roadmap gốc của repo).
- [ ] Đa file Java, Comparator dạng class riêng, bài viết hàm Python dạng import trực tiếp.
- [ ] Chấm bằng AI, chống đạo văn, chấm chất lượng code/phong cách.
- [ ] WebSocket thay polling 5 giây cho dashboard (giữ polling ở MVP).

---

## Nhật ký blocker (điền khi bị kẹt, không xóa)

| Ngày | Người bị chặn | Blocker là gì | Cần ai giúp / cần quyết định gì | Đã xử lý chưa |
|---|---|---|---|---|
| | | | | |
| | | | | |

## Ký xác nhận hoàn thành

- [ ] Người 1 xác nhận: Judge Engine + runner Java/Python đã qua hết kiểm thử của mình.
- [ ] Người 2 xác nhận: API + dữ liệu + vòng đời kỳ thi đã chạy end-to-end bằng web.
- [ ] Người 3 xác nhận: Frontend admin + sinh viên đã chạy trọn vòng và không lộ test ẩn.
- [ ] Cả nhóm xác nhận: Demo cuối đã chạy được trên LAN thật với máy có JDK.
