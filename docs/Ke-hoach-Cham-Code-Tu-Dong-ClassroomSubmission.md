# Kế hoạch: Làm bài code + chấm code tự động cho ClassroomSubmissionServerSystem

> **Trạng thái:** Bản brainstorm / kế hoạch v1 — chưa code, chờ Trainer chốt các quyết định ở mục 10.
> **Ý tưởng gốc:** Dùng Python `subprocess` để chấm code "an toàn", sinh viên được test trước với test case (hoặc không, tùy người tạo đề), chấm cuối cùng theo test case có sẵn.
> **Nền tảng hiện có để tích hợp:** Server Python stdlib + Jinja2, 1 process, dữ liệu JSON/JSONL, vòng đời kỳ thi `idle → distributed → started → ended` với `release_id`, đăng nhập session, dashboard admin polling 5 giây. Xem chi tiết trong file phân tích repo đã làm trước đó.

---

## 1. Mục tiêu và phạm vi

### Vấn đề cần giải quyết

Hiện tại hệ thống chỉ thu bài dạng file ZIP rồi giảng viên tải về chấm tay. Với bài code, việc đó vừa chậm, vừa không cho sinh viên biết ngay bài mình đúng hay sai, vừa khó chấm công bằng khi có nhiều test case.

### Mục tiêu của tính năng mới

1. Sinh viên làm bài code **ngay trên web**, không cần nộp ZIP rồi chờ.
2. Sinh viên được **chạy thử (pretest)** với các test case mà người tạo đề cho phép thấy trước — hoặc **không được chạy thử gì cả** nếu đề yêu cầu thi kín.
3. Khi nộp bài, server **tự chấm theo toàn bộ test case có sẵn** (cả test công khai lẫn test ẩn) và lưu điểm + chi tiết từng test.
4. Admin quản lý được đề code, test case, điểm, giới hạn chạy, và xem kết quả trên dashboard hiện có.
5. Code của sinh viên **không được làm hại server, không đọc được đáp án/test ẩn, không đọc được dữ liệu của người khác**.

### Ngoài phạm vi (đừng ôm vào MVP)

- Chấm code bằng AI / chấm theo chất lượng code, phong cách, độ phức tạp.
- Chống đạo văn / so sánh code giống nhau giữa các sinh viên.
- Chạy code trên máy sinh viên rồi gửi kết quả về (dễ gian lận, không tin được).
- Hỗ trợ nhiều ngôn ngữ ngay từ đầu.
- Judge server riêng, hàng đợi phân tán, auto-scale cho hàng nghìn thí sinh cùng lúc.

---

## 2. Brainstorm: bài code sẽ có dạng gì?

Đây là quyết định nền tảng nhất, vì nó quyết định luôn cách viết test.

### Phương án A — Bài stdin/stdout (khuyến nghị cho MVP)

- Đề mô tả: đọc input từ bàn phím (stdin), in output ra màn hình (stdout).
- Ví dụ: nhập `3 5` → in `8`.
- Test case = một cặp `(stdin, expected_stdout)`.
- **Ưu điểm:** Dễ hiểu nhất cho sinh viên năm nhất, dễ viết test, dễ chấm, không cần biết sinh viên đặt tên hàm là gì.
- **Nhược điểm:** Không chấm được bài yêu cầu viết hàm/class cụ thể, không chấm được bài có nhiều file.

### Phương án B — Bài viết hàm (để dành Phase 2)

- Đề yêu cầu viết hàm `solve(a, b)` chẳng hạn.
- Server import code sinh viên rồi gọi hàm với các input khác nhau, so sánh return value.
- **Ưu điểm:** Chấm chính xác theo từng hàm, gần với kiểu bài tập lập trình nâng cao.
- **Nhược điểm:** Nguy hiểm hơn nhiều nếu import trực tiếp vào process server — code sinh viên chạy ngay trong process chính, có thể đọc/ghi mọi thứ. Muốn an toàn thì vẫn phải đẩy sang subprocess riêng, và phải viết harness trung gian. Phức tạp hơn hẳn.

### Phương án C — Bài nhiều file / project (để dành rất xa)

- Sinh viên nộp cả thư mục, có file chính, file phụ, test riêng.
- Chỉ nên làm khi đã có sandbox container thật sự.

**Đề xuất:** MVP chỉ làm **phương án A (stdin/stdout, Python)**. Thiết kế module chấm sao cho sau này thêm phương án B chỉ cần thêm một loại "runner" mới, không sửa lại luồng nộp bài, tính điểm, hiển thị.

---

## 3. Câu chuyện người dùng (user stories)

### Phía người tạo đề / admin

1. Admin tạo một **Coding Problem**: tiêu đề, mô tả đề, code mẫu ban đầu (starter code), ngôn ngữ (MVP: chỉ Python), giới hạn thời gian/chạy, tổng điểm.
2. Admin thêm **test case**: mỗi test có input, output kỳ vọng, điểm, và cờ `is_visible` (cho sinh viên thấy trước hay không).
3. Admin bật/tắt **cho phép pretest**: nếu bật, sinh viên được bấm "Chạy thử" với các test visible; nếu tắt, nút này biến mất hoàn toàn.
4. Admin chọn **cách hiển thị kết quả chấm cuối**: (a) hiện điểm ngay sau khi nộp, (b) chỉ hiện "đã nộp" và công bố điểm sau khi kết thúc kỳ thi. Mặc định khuyến nghị là (b) cho thi thật, (a) cho luyện tập.
5. Admin **chạy thử bằng đáp án mẫu (reference solution)** trước khi phát đề: nếu đáp án mẫu mà còn trượt test của chính mình thì test đó sai, phải sửa trước khi thi.
6. Admin xem bảng kết quả: từng sinh viên được bao nhiêu điểm, pass/fail từng test (với test ẩn thì chỉ admin thấy chi tiết), code đã nộp lần cuối, thời gian nộp.
7. Admin có thể **chấm lại (regrade)** toàn bộ hoặc một sinh viên khi sửa test case sau khi thi — điểm cũ được giữ lại lịch sử, không ghi đè lén.

### Phía sinh viên

1. Sinh viên đăng nhập, bắt đầu thi như bình thường (đồng hồ server vẫn làm chuẩn).
2. Sinh viên thấy đề code thay vì (hoặc kèm với) file đề PDF — xem mục 5 về cách gắn đề code vào kỳ thi.
3. Sinh viên gõ code vào editor trên web, bấm **Chạy thử** (nếu đề cho phép) → thấy kết quả từng test visible: pass/fail, stdout thực tế, stdout kỳ vọng, lỗi (nếu có), thời gian chạy.
4. Sinh viên bấm **Nộp bài** → server chấm toàn bộ test (visible + hidden), lưu code và kết quả, đánh dấu trạng thái `submitted` như nộp ZIP hiện tại.
5. Sinh viên xem lại code và kết quả của lần nộp cuối (trong phạm vi admin cho phép hiển thị).

---

## 4. Tích hợp vào kiến trúc hiện có — không đập đi xây lại

### Sơ đồ tích hợp

```text
Trình duyệt sinh viên / admin
  │
  │  HTTP (như hiện tại, qua Handler trong app/main.py)
  ▼
app/main.py — thêm route mới, vẫn dùng session + role check cũ
  ├── app/problems.py      (MỚI) CRUD đề code, test case, validate
  ├── app/grading.py       (MỚI) Tính điểm, so sánh output, verdict
  ├── app/code_runner.py   (MỚI) Chạy code sinh viên trong subprocess
  │                         bị giới hạn, trong thư mục tạm riêng
  ├── app/exams.py         (SỬA ÍT) Gắn coding problem vào lượt thi,
  │                         dùng lại release_id, started_at, ends_at
  ├── app/submissions.py   (SỬA ÍT) Thêm loại submission "code",
  │                         hoặc tách file code_submissions.json riêng
  └── app/storage.py       (DÙNG LẠI) JSON/JSONL + audit, không đổi
        │
        ▼
data/problems.json         Đề code + test case
data/code_submissions.json Bài code + kết quả chấm từng test
data/code_runs.json        Lịch sử chạy thử (pretest) — có thể giới hạn giữ lại
logs/audit.jsonl           Thêm event: code.run, code.submit, code.graded, code.regraded
```

### Nguyên tắc tích hợp

- **Dùng lại, không nhân bản:** đăng nhập, session, lockout, trạng thái kỳ thi, đồng hồ server, audit, dashboard monitor đều giữ nguyên. Tính năng code chỉ là một loại "bài nộp" mới.
- **Code chấm không chạy trong process server:** `main.py` chỉ điều phối. Code sinh viên luôn chạy trong một process con riêng, và process đó sẽ bị kill khi hết timeout.
- **Tách runner ra khỏi web server về mặt logic ngay từ đầu**, để sau này thay subprocess bằng Docker mà không phải sửa luồng nộp bài.

---

## 5. Gắn đề code vào kỳ thi như thế nào? (3 phương án)

| Phương án | Cách làm | Khi nào hợp |
| --- | --- | --- |
| **A. Một đề code cho cả kỳ thi (khuyến nghị MVP)** | Kỳ thi có thêm trường `coding_problem_id` trong `settings.json`. Mọi thí sinh làm cùng một đề code. | Thi lập trình 1 bài, lớp học nhỏ, làm nhanh nhất |
| **B. Đề code đi kèm file đề PDF** | Mỗi file trong `de-thi/` có thể gắn một coding problem. Phân phối đề bằng 4 chế độ có sẵn (random/selected/parity/custom) sẽ tự phân phối luôn đề code tương ứng. | Muốn mỗi nhóm sinh viên làm đề code khác nhau, tận dụng luôn cơ chế phát đề hiện có |
| **C. Nhiều đề code, mỗi sinh viên làm nhiều bài** | Một kỳ thi có danh sách problem, sinh viên làm lần lượt từng bài, mỗi bài tính điểm riêng. | Thi có nhiều bài code, cần bảng điểm tổng hợp |

**Đề xuất:** Làm **A trước**, thiết kế dữ liệu theo hướng **B** (problem gắn với assignment, không gắn cứng vào settings toàn cục) để lên B không phải đổi schema. C để Phase 2.

Cụ thể, `assignments.json` của mỗi sinh viên sẽ thêm:

```json
{
  "coding_problem_id": "sum-two-numbers",
  "code_status": "not_started",
  "code_score": 0
}
```

Còn nếu kỳ thi vẫn cần nộp ZIP song song (ví dụ: vừa code vừa nộp báo cáo), thì coi code và ZIP là 2 submission độc lập, trạng thái chung `submitted` chỉ khi cả 2 xong — hoặc admin chọn "chỉ cần code là đủ". Đây là một điểm cần Trainer chốt (mục 10, Q3).

---

## 6. Thiết kế dữ liệu

### 6.1. Đề code (`data/problems.json`)

```json
{
  "sum-two-numbers": {
    "id": "sum-two-numbers",
    "title": "Cộng hai số",
    "statement": "Đọc 2 số nguyên từ stdin, in ra tổng của chúng.",
    "language": "python",
    "starter_code": "a, b = map(int, input().split())\nprint(a + b)\n",
    "time_limit_seconds": 2,
    "memory_limit_mb": 256,
    "max_output_bytes": 65536,
    "allow_pretest": true,
    "max_pretest_runs": 20,
    "show_final_score_immediately": false,
    "total_points": 100,
    "created_by": "admin",
    "created_at": "2026-11-01T10:00:00+00:00"
  }
}
```

### 6.2. Test case (nằm trong problem, hoặc file riêng `data/testcases.json` nếu muốn sửa test mà không chạm problem)

```json
{
  "id": "t1",
  "problem_id": "sum-two-numbers",
  "stdin": "3 5\n",
  "expected_stdout": "8\n",
  "is_visible": true,
  "points": 25,
  "order": 1,
  "compare_mode": "normalized"
}
```

Các `compare_mode` nên có ngay từ đầu:

| Mode | Cách so sánh | Dùng khi nào |
| --- | --- | --- |
| `exact` | So byte-for-byte (sau khi chuẩn hóa CRLF) | Đề yêu cầu format output chính xác |
| `normalized` (mặc định) | Bỏ khoảng trắng thừa ở cuối dòng, bỏ dòng trống cuối, chuẩn hóa xuống dòng | Hầu hết bài stdin/stdout — tránh trừ điểm oan vì thừa dấu cách |
| `tokens` | So theo từng token, bỏ qua mọi khoảng trắng/xuống dòng | Bài chỉ quan tâm dãy số, không quan tâm trình bày |
| `float_tolerance` | So số thực với sai số, ví dụ `1e-6` | Bài tính toán số thực |

### 6.3. Bài nộp code (`data/code_submissions.json`)

```json
{
  "MSSV": [
    {
      "problem_id": "sum-two-numbers",
      "release_id": "abc123...",
      "code": "a, b = map(int, input().split())\nprint(a + b)",
      "language": "python",
      "submitted_at": "2026-11-01T10:20:00+00:00",
      "score": 75,
      "total_points": 100,
      "status": "graded",
      "results": [
        {"test_id": "t1", "verdict": "AC", "points_earned": 25, "time_ms": 120, "stdout": "8\n", "stderr": ""},
        {"test_id": "t2", "verdict": "WA", "points_earned": 0, "time_ms": 110, "stdout": "9\n", "stderr": ""}
      ]
    }
  ]
}
```

**Quy tắc bảo mật dữ liệu quan trọng:**

- API trả về cho sinh viên **không bao giờ** chứa test ẩn: không `stdin`, không `expected_stdout`, không `points` chi tiết của test ẩn nếu admin chọn giấu. Sinh viên chỉ thấy verdict tổng quát (ví dụ: "3/5 test ẩn pass") hoặc chỉ thấy điểm, tùy cấu hình.
- Test ẩn cũng **không được render vào HTML, JS, hay log**. Chỉ admin và server mới thấy.
- Lịch sử pretest chỉ lưu kết quả của test visible.

---

## 7. Chấm code "an toàn" bằng subprocess — phần quan trọng nhất, cần nói thẳng

### 7.1. Sự thật cần chốt trước: `subprocess` một mình KHÔNG phải là sandbox

`subprocess.run()` chỉ có nghĩa là "chạy code ở process khác". Process đó vẫn:

- Chạy cùng user với server.
- Đọc được file trên máy nếu có quyền đọc (kể cả `data/`, `de-thi/`, test case nếu để trên đĩa).
- Truy cập mạng nếu máy có mạng.
- Ghi/xóa file, tạo process con, chiếm CPU/RAM nếu không bị giới hạn.

Vì vậy **không bao giờ** được tin vào các biện pháp kiểu "cấm import os/sys/subprocess" hay "quét code bằng AST để chặn từ khóa nguy hiểm". Sinh viên có thể lách blacklist bằng nhiều cách (ví dụ: `__import__('o'+'s')`, dùng `eval`, dùng thư viện khác gọi xuống hệ thống). Blacklist chỉ là lớp phòng thủ phụ, không phải lớp chính.

**Lớp bảo vệ thật sự phải đến từ hệ điều hành / container**, còn subprocess chỉ là cách để ta áp các giới hạn đó lên một process riêng và kill nó khi cần.

### 7.2. Thiết kế runner theo tầng (defense in depth)

#### Tầng 0 — Luôn có, bất kể chạy ở đâu (MVP)

Áp dụng cho mọi lần chạy, kể cả trên máy Windows của giảng viên:

1. **Process riêng, không phải thread, không&#32;`exec`/`eval`&#32;trong server.** Server chỉ gọi `subprocess.run([sys.executable, student_file], ...)`.
2. **Thư mục làm việc tạm, riêng cho từng lần chạy.** Ví dụ: tạo `tempfile.TemporaryDirectory()` cho mỗi lần chấm, copy code sinh viên vào đó với tên cố định như `solution.py`, chạy xong xóa sạch luôn (`try/finally`). Code sinh viên không bao giờ được chạy trực tiếp trong thư mục project.
3. **Không truyền test case qua file.** Với bài stdin/stdout, input được đưa qua `stdin` bằng pipe, output kỳ vọng được so sánh ở phía server. Như vậy code sinh viên không có file test nào trên đĩa để đọc trộm.
4. **Timeout cứng cho từng test.** Ví dụ mặc định 2 giây/test. Hết timeout → kill process và cả cây process con nếu có thể, verdict `TLE`, không chờ thêm.
5. **Giới hạn output.** `stdout`/`stderr` bị cắt ở mức ví dụ 64 KiB. Code in vô hạn sẽ không làm đầy RAM server.
6. **Dọn dẹp môi trường.** Chạy với env tối thiểu (`PATH` + `SYSTEMROOT` trên Windows, hoặc gần như rỗng trên Linux), không truyền biến môi trường chứa đường dẫn nhạy cảm, không truyền token.
7. **Chạy tuần tự có giới hạn đồng thời.** Ví dụ tối đa 2–4 lần chấm chạy cùng lúc, còn lại xếp hàng. Tránh một lớp cùng bấm Run làm server nghẽn.
8. **Giới hạn số lần chạy thử.** Pretest không phải vô hạn: mặc định 20 lần/bài/kỳ thi, hoặc theo cấu hình admin. Kèm cooldown ngắn (ví dụ 2 giây/lần) để chống spam.
9. **Ghi log mọi lần chạy.** Ai, bài nào, test nào, verdict, thời gian, exit code — nhưng **không log code đầy đủ vào audit công khai**, chỉ log metadata + hash code để đối chiếu khi cần.

#### Tầng 1 — Giới hạn tài nguyên của hệ điều hành (khuyến nghị, Linux làm được đầy đủ nhất)

Trên Linux, dùng `preexec_fn` với module `resource` để đặt giới hạn **trước khi** code sinh viên chạy:

- `RLIMIT_CPU`: tối đa số giây CPU.
- `RLIMIT_AS`: tối đa bộ nhớ ảo (ví dụ 256–512 MB).
- `RLIMIT_FSIZE`: tối đa kích thước file code có thể tạo ra.
- `RLIMIT_NPROC`: hạn chế số process con (chống fork bomb ở mức cơ bản).
- `RLIMIT_NOFILE`: hạn chế số file mở.

Trên **Windows**, `resource` không có. Các biện pháp thay thế yếu hơn: timeout của subprocess, giới hạn output, Job Objects (phức tạp, cần code riêng bằng Win32 API). **Đây là giới hạn thật của MVP trên Windows** — phải ghi rõ trong tài liệu cho giảng viên, không được quảng cáo là "an toàn tuyệt đối" khi chạy trên Windows mà không có container.

#### Tầng 2 — Container / sandbox thật sự (Phase 2, cho môi trường không tin cậy)

Khi cần mức an toàn cao hơn (thi online, sinh viên không ở trong phòng), thay `subprocess` trực tiếp bằng một trong các lựa chọn sau, **không đổi luồng chấm**:

- **Docker (khuyến nghị nếu máy giảng viên cài được):**
  `docker run --rm --network none --read-only --memory 256m --cpus 1 --pids-limit 64 --user nobody -v <tmpdir>:/work:ro` rồi chạy code trong container, mỗi lần chạy là một container mới, xong là xóa.
- **nsjail / bubblewrap (Linux):** nhẹ hơn Docker, tạo namespace riêng, chặn network, mount thư mục làm việc read-only trừ thư mục tạm.
- **Máy ảo / judge worker tách biệt:** server web chỉ gửi job sang một máy/worker khác, worker đó không chứa dữ liệu thật, không có quyền truy cập database/file của server.

**Thiết kế code phải cho phép đổi backend runner bằng cấu hình**, ví dụ:

```python
# app/code_runner.py — interface chung, backend thay được
class CodeRunner:
    def run(self, code: str, stdin: str, limits: Limits) -> RunResult: ...

# MVP:  SubprocessRunner
# Phase 2: DockerRunner, NsJailRunner — cùng interface, cùng RunResult
```

### 7.3. Bảng đe dọa (threat model) — sinh viên có thể làm gì và ta chặn bằng gì

| Hành vi nguy hiểm | Cách chặn ở MVP | Còn sót lại nếu không có container |
| --- | --- | --- |
| Vòng lặp vô hạn | Timeout từng test + kill | — (đã chặn tốt) |
| In vô hạn, làm đầy RAM/đĩa | Cắt stdout/stderr, giới hạn file tạo ra (Linux) | Trên Windows vẫn có nguy cơ ghi file rác vào thư mục tạm — nhưng thư mục tạm bị xóa sau mỗi lần chạy |
| Fork bomb (tạo process vô hạn) | Giới hạn đồng thời + `RLIMIT_NPROC` (Linux) | Trên Windows, Job Objects mới chặn triệt để được |
| Đọc `data/`, test ẩn, bài của người khác | Không để test trên đĩa, chạy trong thư mục tạm riêng, chỉ trả về verdict cho sinh viên | Code vẫn có thể đọc file nếu biết đường dẫn và có quyền đọc — **chỉ container / user riêng mới chặn triệt để** |
| Gửi dữ liệu ra ngoài qua mạng | — (subprocess không tự chặn mạng) | **Chỉ&#32;`--network none`&#32;của container mới chặn được** |
| Xóa/ghi đè file của server | Chạy trong thư mục tạm, không chạy trong thư mục project | Code vẫn có thể ghi vào các thư mục mà user chạy server có quyền ghi — cần user riêng / container |
| Giả mạo kết quả chấm | Kết quả chỉ tính ở phía server, sinh viên không tự báo điểm | — (đã chặn nếu không để logic chấm ở client) |
| Spam nút Run làm sập server | Giới hạn đồng thời + giới hạn số lần pretest + cooldown | — |

**Kết luận cho phần này, nói thẳng với Trainer:** Với lớp học LAN có giảng viên giám sát trực tiếp, MVP tầng 0 + tầng 1 là chấp nhận được và đã tốt hơn nhiều so với việc chạy code trực tiếp trong server. Nhưng nếu đem lên internet cho người lạ thi, **bắt buộc phải có container / judge tách biệt** — không có ngoại lệ.

---

## 8. Luồng chấm chi tiết

### 8.1. Pretest (chạy thử, chỉ test visible)

```text
Sinh viên bấm "Chạy thử"
  → Kiểm tra: đã bắt đầu thi chưa, còn trong giờ không, đề có allow_pretest không,
      còn lượt pretest không, có đang spam không
  → Lấy code hiện tại trong editor (CHƯA phải là bài nộp chính thức)
  → Với mỗi test visible (theo thứ tự):
      Chạy code với stdin của test đó, timeout = time_limit_seconds
      So sánh stdout theo compare_mode của test
      Ghi verdict từng test: AC / WA / TLE / RE / MLE / OLE
  → Trả về cho sinh viên: bảng từng test visible, stdout thực tế (cắt ngắn),
      stdout kỳ vọng, stderr (cắt ngắn), thời gian chạy
  → KHÔNG tính điểm, KHÔNG đánh dấu submitted, KHÔNG chạy test ẩn
  → Lưu lịch sử pretest (giới hạn, ví dụ 50 lần gần nhất/sinh viên/bài)
```

### 8.2. Chấm cuối (khi nộp bài)

```text
Sinh viên bấm "Nộp bài"
  → Kiểm tra như nộp ZIP: đúng release_id, đã bắt đầu, chưa hết giờ,
      chưa vượt số lần nộp cho phép (nếu admin giới hạn số lần nộp code)
  → Lưu snapshot code vào code_submissions.json (kèm hash SHA-256)
  → Chấm toàn bộ test: visible + hidden, theo thứ tự
  → Tính điểm: cộng điểm của từng test pass, không trừ điểm test fail
      (trừ khi admin cấu hình khác — nên để mặc định là không trừ)
  → Lưu kết quả chi tiết (admin thấy hết, sinh viên thấy theo cấu hình hiển thị)
  → Đánh dấu assignment: code_status = submitted, code_score = điểm
  → Ghi audit: code.submitted, code.graded
  → Nếu kỳ thi chỉ có bài code: trạng thái chung chuyển sang submitted
      (tương tự như khi nộp ZIP xong)
```

### 8.3. Các verdict (kết quả từng test)

| Verdict | Nghĩa | Điểm |
| --- | --- | --- |
| `AC` | Accepted — output khớp | Đủ điểm test đó |
| `WA` | Wrong Answer — output không khớp | 0 |
| `TLE` | Time Limit Exceeded — quá timeout | 0 |
| `MLE` | Memory Limit Exceeded — vượt RAM (khi đo được) | 0 |
| `RE` | Runtime Error — crash, exit code khác 0, exception | 0 |
| `CE` | Compilation Error — lỗi cú pháp, code không chạy được test nào | 0 cho tất cả |
| `OLE` | Output Limit Exceeded — in quá nhiều | 0 |

Lưu ý: `CE` nên phát hiện sớm bằng cách chạy `python -m py_compile` (hoặc chạy test đầu tiên) và báo ngay, thay vì để sinh viên tưởng là WA ở tất cả test.

---

## 9. API và giao diện mới (đề xuất)

### API mới (đi theo chuẩn route hiện có, đều yêu cầu session + role)

| Method | Endpoint | Vai trò | Mục đích |
| --- | --- | --- | --- |
| GET | `/api/admin/problems` | Admin | Danh sách đề code |
| POST | `/api/admin/problems` | Admin | Tạo đề code |
| GET | `/api/admin/problems/{id}` | Admin | Chi tiết đề + toàn bộ test (kể cả ẩn) |
| PUT | `/api/admin/problems/{id}` | Admin | Sửa đề, test, cấu hình pretest |
| POST | `/api/admin/problems/{id}/validate` | Admin | Chạy đáp án mẫu qua toàn bộ test để kiểm tra test có đúng không |
| POST | `/api/admin/problems/{id}/regrade` | Admin | Chấm lại tất cả bài đã nộp của đề đó |
| GET | `/api/student/problem` | Sinh viên | Đề code được giao (KHÔNG kèm test ẩn) |
| POST | `/api/student/code/run` | Sinh viên | Pretest — chỉ test visible |
| POST | `/api/student/code/submit` | Sinh viên | Nộp bài và chấm toàn bộ test |
| GET | `/api/student/code/submission` | Sinh viên | Xem lại bài nộp cuối + kết quả (theo quyền hiển thị) |
| GET | `/api/admin/code-results` | Admin | Bảng điểm code của kỳ thi hiện tại |

### Giao diện

**Admin:**

- Tab mới trong dashboard: "Đề code" — danh sách problem, nút tạo/sửa.
- Form tạo test case: thêm từng test, chọn visible/hidden, nhập stdin/expected, điểm, compare mode. Hỗ trợ import test từ JSON để khỏi nhập tay từng test khi có nhiều test.
- Nút "Kiểm tra bằng đáp án mẫu": admin paste đáp án mẫu, hệ thống chạy qua tất cả test và báo test nào đáp án mẫu còn trượt.
- Bảng kết quả: lọc theo sinh viên, xem code đã nộp, xem pass/fail từng test, nút chấm lại.

**Sinh viên:**

- Trang làm bài thêm khu vực code: mô tả đề bên trái, editor bên phải (MVP: `<textarea>` + xử lý phím Tab, giữ nguyên phong cách offline — không dùng CDN cho editor. Phase 2 mới cân nhắc CodeMirror/Monaco bản local).
- Nút "Chạy thử" chỉ hiện khi `allow_pretest = true`.
- Bảng kết quả pretest: từng test visible, stdout thực tế vs kỳ vọng, lỗi nếu có.
- Nút "Nộp bài" + xác nhận (tránh bấm nhầm khi đã hết lượt nộp).
- Sau khi nộp, hiển thị theo cấu hình: điểm ngay, hoặc chỉ "Đã nộp — điểm sẽ công bố sau khi kết thúc kỳ thi".

---

## 10. Lộ trình triển khai

### Phase 0 — Chốt thiết kế (trước khi code, chính là bản này)

- Trainer chốt các câu hỏi ở mục 11.
- Viết test case mẫu cho 2–3 bài code điển hình (cộng 2 số, tìm max, xử lý chuỗi) để dùng làm fixture cho mọi phase sau.

### Phase 1 — MVP: Python stdin/stdout, 1 đề/kỳ thi (khuyến nghị làm trước)

- [ ] `app/code_runner.py`: `SubprocessRunner` với temp dir riêng, timeout, cắt output, env tối thiểu, giới hạn tài nguyên trên Linux.
- [ ] `app/grading.py`: so sánh output theo 4 mode, tính điểm, verdict.
- [ ] `app/problems.py`: CRUD problem + test case, validate dữ liệu đầu vào.
- [ ] Route + template: admin tạo đề/test, sinh viên làm bài + pretest + nộp, bảng điểm admin.
- [ ] Tích hợp vòng đời kỳ thi: chỉ chấm khi đúng `release_id`, trong giờ, đã bắt đầu.
- [ ] Audit + giới hạn pretest + giới hạn đồng thời.
- [ ] Test: unit cho grading + runner, test adversarial (vòng lặp vô hạn, in vô hạn, đọc file, lỗi cú pháp).

- **Tiêu chí xong Phase 1:** Một lớp thi thử trên LAN: admin tạo đề, sinh viên pretest được, nộp bài được chấm đúng, test ẩn không lộ ra frontend, code vòng lặp vô hạn bị kill sau timeout mà server vẫn sống.

### Phase 2 — Mở rộng đề và trải nghiệm

- [ ] Nhiều đề/kỳ thi, gắn đề theo chế độ phân phối (phương án B, mục 5).
- [ ] Đáp án mẫu + validate test trước khi phát đề.
- [ ] Regrade, import/export problem + test bằng JSON.
- [ ] Editor tốt hơn (highlight, Tab, lưu nháp code tự động vào localStorage + server).
- [ ] Số lần nộp code có giới hạn, lịch sử các lần nộp.

### Phase 3 — Hardening sandbox

- [ ] `DockerRunner` / `NsJailRunner` cùng interface với `SubprocessRunner`, chọn bằng cấu hình.
- [ ] Judge worker tách biệt (tùy chọn), hàng đợi chấm.
- [ ] Runner cho bài viết hàm (phương án B, mục 2) qua harness riêng.
- [ ] Thêm ngôn ngữ khác (ví dụ: C++ qua `g++`, Java qua `javac/java`) — mỗi ngôn ngữ là một runner riêng.

### Phase 4 — Lên public web (đi chung roadmap gốc của repo)

- CSRF, rate-limit upload/run, SQLite thay JSON, Nginx + HTTPS, Docker deploy. **Không nên public tính năng chấm code trước khi xong Phase 3 + Phase 4.**

### Ước lượng (chỉ là ước lượng, không phải cam kết)

| Phase | Quy mô tương đối |
| --- | --- |
| Phase 0 (thiết kế) | Đã làm xong bản này — chỉ còn chốt câu hỏi |
| Phase 1 (MVP) | Lớn nhất, khoảng 1–2 tuần làm đều tay nếu làm một mình (phần runner + test adversarial chiếm nhiều thời gian nhất) |
| Phase 2 | Bằng khoảng 50–70% Phase 1 |
| Phase 3 | Tùy chọn container — nếu máy đã có Docker thì nhanh, nếu phải tự build sandbox thì lâu hơn nhiều |
| Phase 4 | Đi chung roadmap public web của repo gốc, không tính riêng cho tính năng code |

---

## 11. Những điểm cần Trainer chốt (brainstorm tiếp từ đây)

Trainer cứ trả lời ngắn gọn từng câu, hoặc sửa thẳng đề xuất của em. Em sẽ cập nhật lại bản kế hoạch này thành bản chốt rồi mới bắt đầu code Phase 1.

**Q1. Dạng bài MVP:** Chỉ stdin/stdout Python trước, đúng không? Hay Trainer muốn luôn cả bài viết hàm ngay từ đầu?

**Q2. Pretest:** Mặc định cho phép pretest với test visible, nhưng admin tắt được — Trainer đồng ý chứ? Và có nên giới hạn số lần pretest không (ví dụ 20 lần), hay cho chạy thoải mái trong giờ thi?

**Q3. Đề code gắn với kỳ thi kiểu nào:** (A) Một đề cho cả kỳ thi, (B) đề đi kèm file PDF và phân phối theo nhóm, hay (C) nhiều đề? Và kỳ thi code có cần nộp ZIP kèm theo không, hay nộp code là xong?

**Q4. Hiển thị điểm chấm cuối:** Hiện điểm ngay sau khi nộp, hay chỉ hiện "đã nộp" và công bố sau khi kết thúc kỳ thi? Em khuyến nghị: luyện tập thì hiện ngay, thi thật thì giấu đến khi kết thúc để tránh sinh viên dò test ẩn bằng cách nộp nhiều lần.

**Q5. Số lần nộp code:** Cho nộp nhiều lần và lấy điểm cao nhất / lần cuối, hay chỉ 1 lần duy nhất như nộp ZIP chế độ `once`? Em khuyến nghị: luyện tập thì nhiều lần lấy max, thi thật thì giới hạn (ví dụ 3–5 lần) để tránh brute-force test ẩn.

**Q6. Mức an toàn chấp nhận được cho MVP:** Chạy trên máy Windows của giảng viên trong phòng học, chỉ dùng subprocess + timeout + thư mục tạm (tầng 0), Trainer chấp nhận rủi ro còn lại chứ? Hay Trainer muốn làm luôn Docker từ Phase 1 (đòi hỏi máy giảng viên phải cài Docker)?

**Q7. So sánh output:** Dùng `normalized` làm mặc định (bỏ khoảng trắng thừa cuối dòng) chứ? Hay Trainer muốn `exact` cho chặt? Và có cần mode số thực với sai số không?

---

## 12. Rủi ro lớn nhất cần nhớ

1. **Ảo tưởng an toàn:** Nghĩ rằng "dùng subprocess là an toàn" trong khi code sinh viên vẫn đọc được file server và truy cập mạng nếu không có container. Phải ghi rõ giới hạn này trong tài liệu giảng viên.
2. **Lộ test ẩn:** Chỉ cần một chỗ vô tình trả test ẩn về frontend (API, HTML, log, thông báo lỗi) là cả kỳ thi mất ý nghĩa. Cần test riêng: gọi mọi API phía sinh viên và kiểm tra response không chứa test ẩn.
3. **Test case sai:** Đáp án đúng mà vẫn trượt vì expected output gõ sai, hoặc vì compare mode quá chặt. Vì vậy bước "validate bằng đáp án mẫu" phải bắt buộc trước khi phát đề.
4. **Server bị nghẽn khi cả lớp cùng bấm Run:** Phải có giới hạn đồng thời + hàng đợi + timeout, nếu không một bài vòng lặp vô hạn của vài sinh viên cũng đủ làm chậm cả lớp.
5. **Nộp muộn / mất bài:** Code nộp phải tuân thủ đúng đồng hồ server và `release_id` như nộp ZIP hiện tại, không được để client tự báo "em nộp rồi".

---

## 13. Tính năng bổ sung: Chấm method Java bằng Reflection

> Đây là phần Trainer vừa thêm vào sau bản kế hoạch Python. Nó không thay thế phần chấm Python stdin/stdout ở trên, mà là **một loại đề thứ hai chạy song song**, dùng chung luồng nộp bài, pretest, tính điểm và dashboard.

### 13.1. Vì sao cần Reflection, không chỉ chấm stdin/stdout cho Java?

Bài Java trong môn Java Software Development thường không phải là "viết chương trình in ra đáp án", mà là **"thiết kế một class đúng đặc tả OOP"**, ví dụ:

- Class `Student` phải có attribute `private String name`, `private double gpa`.
- Phải có constructor `Student(String name, double gpa)`.
- Phải có getter/setter đúng chuẩn, và setter phải kiểm tra `gpa` từ 0 đến 10.
- Phải có `toString()` đúng format mà đề yêu cầu.
- Phải sắp xếp được bằng `Comparable` hoặc `Comparator`.

Chấm stdin/stdout không kiểm tra được những thứ này: sinh viên có thể làm ra output đúng nhưng class sai hoàn toàn về mặt thiết kế (attribute để `public`, không có setter, không có constructor yêu cầu...). Reflection giải quyết đúng chỗ đó: **chương trình chấm sẽ "soi" vào class của sinh viên lúc chạy và hỏi: class này có đúng field, đúng method, đúng modifier, và hành vi có đúng không?**

### 13.2. Luồng tổng thể — Python server không tự reflect Java được

Server hiện tại viết bằng Python, nên nó không thể dùng Reflection của Java trực tiếp. Cần một **chương trình chấm trung gian viết bằng Java (harness)**, chạy trong process riêng:

```text
Sinh viên nộp code Java (editor / upload .java)
  │
  ▼
Python server (app/main.py, dùng lại session + release_id + đồng hồ thi)
  │  1. Lưu code vào thư mục tạm riêng cho lần chấm này
  │  2. Lọc spec: pretest chỉ gửi check visible, chấm cuối mới gửi toàn bộ
  ▼
Subprocess 1: javac
  │  Biên dịch code sinh viên vào thư mục out/ riêng
  │  Lỗi biên dịch → verdict CE, dừng luôn, không chạy tiếp
  ▼
Subprocess 2: java ReflectionJudge (harness tin cậy, code của hệ thống)
  │  - Nhận spec chấm qua stdin (pipe, KHÔNG qua file để sinh viên khỏi đọc trộm)
  │  - Load class sinh viên bằng URLClassLoader, chỉ trỏ vào thư mục out/
  │  - Dùng Reflection để kiểm tra từng check, gọi thử method/constructor
  │  - In kết quả JSON ra stdout (pipe về cho Python server)
  ▼
Python server (app/java_grading.py)
  │  Đọc JSON kết quả, tính điểm từng check, lưu vào code_submissions.json
  ▼
Trả về cho sinh viên / admin theo đúng quyền hiển thị (test ẩn chỉ admin thấy)
```

Điểm mấu chốt: **code sinh viên không bao giờ chạy trong process của Python server**, và cũng không chạy chung process với code web. Nó chỉ chạy trong JVM của harness, và JVM đó sẽ bị kill khi hết timeout.

### 13.3. Mô hình đề Java — thêm một loại problem, không làm lại hệ thống

Mở rộng `problems.json` từ mục 6 bằng một trường phân loại:

```json
{
  "student-oop": {
    "id": "student-oop",
    "title": "Lớp Student",
    "language": "java",
    "problem_kind": "java_reflection",
    "target_class": "Student",
    "target_package": "model",  // BẮT BUỘC: theo yêu cầu từng đề, không để rỗng trừ khi đề ghi rõ là default package
    "starter_code": "public class Student {\n    // TODO: khai báo attribute, constructor, getter/setter\n}\n",
    "time_limit_seconds": 5,
    "memory_limit_mb": 256,
    "allow_pretest": true,
    "show_final_score_immediately": false,
    "total_points": 100
  }
}
```

Quy ước MVP:

- **Một file, một public class chính — PHẠM VI ĐÃ CHỐT cho hiện tại (02/11/2026).** Mỗi bài nộp Java chỉ gồm 1 file chứa 1 public class chính. Tên file phải trùng tên public class (quy tắc của `javac`), ví dụ `Student.java` chứa `public class Student`. Chưa làm đa file, chưa chấm class phụ trong cùng kỳ thi; nếu sinh viên nộp thêm public class khác trong cùng file thì `javac` sẽ lỗi và tính là CE.
- `target_package`: **BẮT BUỘC theo yêu cầu của từng đề bài (ĐÃ CHỐT 02/11/2026).** Admin phải ghi rõ package trong spec, ví dụ `model` cho class `model.Student`. Code sinh viên phải khai báo đúng package đó, nếu sai hoặc không khai báo thì check class tồn tại sẽ fail. Khi biên dịch, server phải đặt file nguồn đúng cấu trúc thư mục của package (ví dụ `temp_src/model/Student.java`) rồi mới gọi `javac`, để `javac` và classloader load được đúng tên đầy đủ.
- Đa file / nhiều class phụ: để Phase sau (mục 13.13).
- Các route API ở mục 9 được **dùng lại nguyên vẹn** (`/api/student/code/run`, `/api/student/code/submit`...). Server chỉ cần rẽ nhánh theo `problem_kind`: `python_stdio` thì gọi `SubprocessRunner`, `java_reflection` thì gọi `JavaRunner`.

### 13.4. Bảng các loại check bằng Reflection — đây là "trái tim" của tính năng

Mỗi check là một test case có điểm riêng, có cờ visible/hidden riêng. Admin không cần viết code Java để tạo check, chỉ cần điền form theo bảng dưới đây.

| Loại check | Kiểm tra cái gì | Cách làm bằng Reflection | Ví dụ |
| --- | --- | --- | --- |
| **Class tồn tại** | Class có tồn tại, đúng tên/package không | `Class.forName()` / `ClassLoader.loadClass()` | `Student` phải tồn tại |
| **Kế thừa / Interface** | Class có extends / implements đúng không | `getSuperclass()`, `getInterfaces()` | `Student implements Comparable<Student>` |
| **Attribute (field)** | Tên field, kiểu dữ liệu, modifier | `getDeclaredField(name)`, `getType()`, `getModifiers()` | Field `name` phải là `private String`, `gpa` phải là `private double` |
| **Modifier** | `public` / `private` / `protected`, `static`, `final`, `abstract` | `Modifier.isPrivate()`, `isStatic()`, `isFinal()`... trên field/method/constructor/class | `name` phải `private`, hằng số phải `public static final` |
| **Constructor** | Có constructor với đúng danh sách tham số và modifier không, và tạo object có đúng trạng thái không | `getDeclaredConstructor(paramTypes)`, `newInstance(args)` rồi đọc lại bằng getter/field | `Student(String, double)` phải `public`, tạo xong `getName()` trả về đúng tên |
| **Method (chung)** | Tên method, kiểu trả về, danh sách tham số, modifier, `static` hay instance, có throws gì không | `getDeclaredMethod(name, paramTypes)`, `getReturnType()`, `getParameterTypes()`, `getExceptionTypes()` | Method `calculateGPA()` phải `public double`, không tham số |
| **Getter / Setter** | Cặp getter/setter đúng chuẩn JavaBean, đúng kiểu, và **hành vi** đúng (không chỉ có tên) | Tìm `getX()` / `isX()` (cho boolean) và `setX(...)`, gọi `setX(value)` rồi `getX()` phải trả về đúng value | `setGpa(8.5)` rồi `getGpa()` phải bằng 8.5 |
| **Validator (trong setter hoặc method riêng)** | Setter/method kiểm tra dữ liệu có từ chối giá trị không hợp lệ không | **ĐÃ CHỐT 02/11/2026: giá trị không hợp lệ phải ném&#32;`IllegalArgumentException`.** Không chấp nhận trả về `false` hay giữ nguyên giá trị cũ làm cách xử lý chính cho setter/constructor/method kiểm tra đầu vào, trừ khi một check cụ thể trong spec ghi rõ ngoại lệ. Lưu ý phân biệt: method dạng predicate như `isValid()` / `isPassing()` thì vẫn trả về boolean (đúng/sai), còn method dạng setter/validator kiểm tra đầu vào thì phải ném `IllegalArgumentException` khi đầu vào sai | `setGpa(-1)` phải ném `IllegalArgumentException` |
| **Method validator riêng** | Method kiểu `isValid()`, `validate()`, `isAdult()`... trả về đúng boolean với từng input | Gọi method với các bộ input mẫu, so sánh return value | `isPassing()` trả về `true` khi `gpa >= 5`, `false` khi nhỏ hơn |
| **toString()** | Format chuỗi có đúng như đề yêu cầu không | **ĐÃ CHỐT 02/11/2026: dùng template có sẵn + so sánh exact sau khi điền template.** Admin cung cấp sẵn mẫu, ví dụ `Student{name='{name}', gpa={gpa}}`. Harness điền giá trị field thực tế của object vào placeholder, rồi so sánh chuỗi kết quả với `toString()` của sinh viên **một cách exact** (chỉ chuẩn hóa CRLF → LF để tránh lệch hệ điều hành, không bỏ khoảng trắng, không dùng mode `contains` làm mặc định). Sinh viên phải trả về đúng chính xác giá trị theo mẫu | `Student{name='An', gpa=8.5}` — nếu thừa/thiếu một dấu cách, dấu phẩy hay dấu nháy so với mẫu đã điền thì check này fail |
| **Comparable** | Class có sắp xếp được không, thứ tự có đúng không | Kiểm tra `Comparable` interface, gọi `compareTo()` với các cặp object, kiểm tra dấu (`<0`, `=0`, `>0`), rồi sort một list mẫu và so thứ tự | `compareTo()` sắp xếp theo `gpa` giảm dần, bằng nhau thì theo `name` tăng dần |
| **Comparator** | Class Comparator riêng có so sánh đúng không | Load class Comparator yêu cầu, `newInstance()`, gọi `compare(a, b)`, kiểm tra dấu và thứ tự sort | `StudentNameComparator` sắp xếp theo tên A–Z |
| **Method khác (tổng quát)** | Bất kỳ method nào đề yêu cầu: hành vi, return, thay đổi trạng thái, exception | Dạng "behavior case" chung (xem 13.5): setup object → gọi method với args → so return / state sau khi gọi / exception kỳ vọng | `deposit(100)` làm `balance` tăng 100, `withdraw(1000)` khi số dư không đủ phải ném exception |
| **(Mở rộng) equals / hashCode** | Hai object cùng dữ liệu có equal nhau không, hashCode có nhất quán không | Gọi `equals()` với các cặp object, kiểm tra `hashCode()` bằng nhau khi equal | Để Phase sau, vì dễ gây tranh cãi về đặc tả |

**Lưu ý quan trọng về getter/setter và validator:**

- Chỉ kiểm tra "có method tên `getX`" là **chưa đủ**. Sinh viên có thể viết getter trả về hằng số, hoặc setter không làm gì. Vì vậy check getter/setter bắt buộc phải kèm **behavior case**: set một giá trị rồi get lại, set giá trị biên (0, giá trị max), set giá trị sai rồi kiểm tra phản ứng.
- Validator đã chốt chung (02/11/2026): giá trị sai thì **ném&#32;`IllegalArgumentException`**. Admin không cần chọn lại semantics cho từng bài nữa, trừ khi một check cụ thể ghi rõ ngoại lệ. Predicate kiểu `isValid()` vẫn trả boolean như bình thường, không áp quy tắc ném exception này.

### 13.5. Đặc tả check bằng JSON — admin điền form, hệ thống sinh ra JSON này

Ví dụ đầy đủ cho bài `Student`:

```json
{
  "problem_id": "student-oop",
  "checks": [
    {
      "id": "field-name",
      "kind": "field",
      "class_name": "Student",
      "field_name": "name",
      "expected_type": "java.lang.String",
      "expected_modifiers": ["private"],
      "is_visible": true,
      "points": 10
    },
    {
      "id": "ctor",
      "kind": "constructor",
      "class_name": "Student",
      "param_types": ["java.lang.String", "double"],
      "expected_modifiers": ["public"],
      "is_visible": true,
      "points": 10
    },
    {
      "id": "setter-validation",
      "kind": "behavior",
      "class_name": "Student",
      "description": "setGpa(-1) phải ném IllegalArgumentException",
      "setup": {"constructor_args": ["An", 8.5]},
      "invoke": {"method": "setGpa", "args": [-1]},
      "expect_exception": "java.lang.IllegalArgumentException",
      "is_visible": false,
      "points": 15
    },
    {
      "id": "tostring",
      "kind": "toString",
      "class_name": "Student",
      "setup": {"constructor_args": ["An", 8.5]},
      "compare_mode": "template",
      "expected_template": "Student{name='{name}', gpa={gpa}}",
      "is_visible": true,
      "points": 15
    },
    {
      "id": "compareto",
      "kind": "comparable",
      "class_name": "Student",
      "sort_cases": [
        {"a": ["An", 9.0], "b": ["Binh", 8.0], "expected_sign": -1}
      ],
      "is_visible": false,
      "points": 20
    }
  ]
}
```

Dạng "behavior case" tổng quát (dùng cho mọi method khác) có cấu trúc chung:

```text
setup:   tạo object bằng constructor nào, với args nào
         (hoặc gọi thêm các setter để đưa object về trạng thái cần test)
invoke:  gọi method nào, với args nào
expect:  một trong ba thứ (chỉ chọn một cho mỗi case):
         - expected_return: giá trị trả về kỳ vọng
         - expected_state:  giá trị của các field sau khi gọi (đọc bằng getter
           hoặc bằng Reflection setAccessible(true) nếu field private)
         - expect_exception: loại exception kỳ vọng
```

### 13.6. Harness Java (ReflectionJudge) — code tin cậy, chạy riêng

Harness là một file Java của hệ thống, ví dụ `judge/ReflectionJudge.java`, **không phải code sinh viên**:

```text
1. Đọc spec JSON từ stdin (đã được Python server lọc: pretest chỉ có check visible)
2. Với mỗi check, chạy trong try/catch riêng để một check lỗi không làm sập cả bài:
   - Field/method/constructor: dùng getDeclaredField / getDeclaredMethod /
     getDeclaredConstructor, so sánh type và Modifier
   - Behavior: tạo object bằng Constructor.newInstance(), gọi Method.invoke(),
     bắt InvocationTargetException và "mở" ra exception gốc bên trong để so sánh
   - toString / Comparable / Comparator: gọi trực tiếp rồi so sánh theo mode đã chốt ở 13.4 (toString: template + exact)
3. In ra stdout một JSON kết quả cho từng check:
   { check_id, passed, expected, actual, error, time_ms }
4. Thoát với exit code 0 nếu harness chạy xong (kể cả khi sinh viên trượt hết),
   exit code khác 0 chỉ khi chính harness bị lỗi
```

**Các cạm bẫy Reflection cần xử lý trong harness (không xử lý là chấm sai oan):**

- `getDeclaredField` vs `getField`: `getField` chỉ thấy field `public` (kể cả kế thừa), còn field `private` của chính class thì phải dùng `getDeclaredField`. Harness phải dùng `getDeclared*` cho kiểm tra cấu trúc của chính class đó.
- **Overload:** chỉ tìm theo tên là chưa đủ. `setScore(int)` và `setScore(double)` là 2 method khác nhau. Harness phải match theo tên **+ danh sách kiểu tham số**.
- **Primitive vs Wrapper:** `int` khác `Integer`, `double` khác `Double` trong Reflection. Spec phải ghi đúng kiểu, và harness nên có tùy chọn "coi int/Integer là tương đương" nếu admin muốn nới lỏng — mặc định là chặt (khác là fail).
- **Generic bị xóa kiểu (type erasure):** `List<String>` lúc chạy chỉ còn `List`. Kiểm tra generic phải dùng `getGenericType()` và so chuỗi, không dùng `getType()` được.
- **Đọc field private:** dùng `field.setAccessible(true)`. Trong default package (unnamed module) thì được. Nếu sinh viên dùng module (`module-info.java`) thì có thể bị chặn — MVP nên cấm/không hỗ trợ `module-info.java`, hoặc yêu cầu code ở default package.
- **Exception bị bọc:** khi gọi method qua Reflection mà method đó ném exception, Java bọc nó trong `InvocationTargetException`. Harness phải lấy `getCause()` ra mới so được loại exception thật.
- **So sánh số thực:** `double`/`float` phải so với sai số (ví dụ `1e-9`), không so `==` tuyệt đối. So sánh mảng/collection phải dùng `Arrays.equals` / so từng phần tử, không dùng `==`.
- **Trạng thái tĩnh (static state):** nếu sinh viên dùng static field để đếm object, chạy nhiều check trong cùng một JVM sẽ làm các check sau bị "nhiễm" trạng thái của check trước. Cách xử lý: mỗi behavior case quan trọng nên tạo object mới hoàn toàn, và nếu cần chặt hơn thì chuyển sang chế độ "mỗi check một JVM" (xem 13.8).

### 13.7. Biên dịch Java — lỗi biên dịch là một verdict riêng

```text
javac -encoding UTF-8 -d <out_dir> <student_dir>/Student.java
  → Thành công: chuyển sang bước chạy harness
  → Thất bại: verdict CE cho toàn bộ bài, trả về thông báo lỗi của javac
    (đã cắt ngắn, ví dụ tối đa 2000 ký tự) để sinh viên sửa được
  → Lưu ý: tên file phải trùng tên public class, nếu không javac báo lỗi
    ngay cả khi code đúng logic — admin nên ghi rõ quy tắc này trong đề
```

Cấu hình cần có: đường dẫn `javac`/`java` (mặc định lấy từ `PATH`, cho phép admin cấu hình `JAVA_HOME` nếu máy có nhiều JDK), phiên bản JDK tối thiểu (ví dụ JDK 17 trở lên, vì các bản cũ hơn có hành vi Reflection/SecurityManager khác nhau).

### 13.8. An toàn cho Java — giống Python nhưng có thêm vài điểm riêng của JVM

Áp dụng lại toàn bộ tầng 0 và tầng 1 ở mục 7, cộng thêm:

| Nguy cơ riêng của Java | Cách xử lý |
| --- | --- |
| `System.exit()` trong code sinh viên làm chết harness | Chạy harness trong JVM riêng (không phải server). Nếu harness chết giữa chừng, Python server đánh dấu các check còn lại là `RE` và báo rõ, không làm sập server. Chế độ chặt hơn: mỗi check chạy một JVM riêng — chậm hơn (mỗi JVM khởi động \~100–200ms) nhưng `System.exit()` chỉ giết đúng check đó |
| Static initializer chạy ngay khi load class | Coi static initializer là code không tin cậy ngay từ lúc load class. Load class cũng phải nằm trong JVM riêng có timeout, không load trong server |
| Vòng lặp vô hạn / đệ quy vô hạn | Timeout của subprocess (Python) + `-Xmx` giới hạn RAM cho JVM (ví dụ `-Xmx256m`), `-Xss` giới hạn stack. Vượt quá → kill JVM, verdict `TLE`/`MLE` |
| Đọc/ghi file, truy cập mạng | Như mục 7: thư mục tạm riêng, spec qua stdin (không qua file), classpath chỉ có thư mục out/ của sinh viên + harness. **Chặn triệt để chỉ khi có container (`--network none`, mount read-only)** |
| `SecurityManager` | **Không dựa vào nó.** SecurityManager đã deprecated và sẽ bị gỡ khỏi các JDK mới, hành vi không ổn định theo phiên bản. Dùng process/container isolation thay vì SecurityManager |
| Sinh viên "nhìn trộm" harness | Harness và code sinh viên tuy cùng JVM nhưng ở classloader khác nhau, và spec đã được lọc trước khi đưa vào harness (pretest chỉ có visible). Tuy vậy, đây vẫn là lý do container mới là lớp chặn cuối cùng cho kỳ thi không tin cậy |

### 13.9. Pretest và test ẩn cho Java — nguyên tắc giống Python, nhưng lọc spec sớm hơn

- **Pretest:** Python server lọc spec chỉ còn check `is_visible = true`, rồi mới đưa spec đó cho harness. Như vậy test ẩn **không bao giờ xuất hiện trong input của lần chạy thử**, kể cả khi code sinh viên cố tình đọc stdin hay reflection vào harness.
- **Chấm cuối:** đưa toàn bộ spec (visible + hidden) cho harness, nhưng kết quả trả về cho sinh viên vẫn phải lọc lại: sinh viên chỉ thấy điểm tổng và kết quả của check visible (hoặc chỉ thấy "đã nộp", tùy cấu hình ở Q4 cũ). Chi tiết check hidden chỉ admin thấy.
- **Validate bằng đáp án mẫu:** bắt buộc trước khi phát đề. Admin paste đáp án mẫu, hệ thống chạy toàn bộ spec lên đáp án đó. Nếu đáp án mẫu mà trượt check nào thì spec đó sai, phải sửa trước khi thi — đặc biệt quan trọng với `toString` template và validator semantics.

### 13.10. Tính điểm cho Java

- Mỗi check có điểm riêng, tổng điểm = tổng điểm các check.
- Khuyến nghị chia trọng số để sinh viên không "ăn điểm" chỉ bằng cách khai báo đúng tên mà không làm đúng hành vi, ví dụ: **cấu trúc (field/method/constructor/modifier) khoảng 30%, hành vi (getter/setter/validator/toString/comparator/method) khoảng 70%**. Admin vẫn sửa được trọng số này theo từng đề.
- Một check chỉ có pass/fail, không chấm điểm từng phần bên trong một check (trừ khi admin tách nhỏ check đó ra thành nhiều check con). Ví dụ: thay vì một check "toString đúng" 20 điểm, có thể tách thành "toString chứa name" 10 điểm + "toString đúng format" 10 điểm nếu muốn cho điểm từng phần.
- Verdict dùng chung với mục 8.3 (`AC`, `WA`, `TLE`, `MLE`, `RE`, `CE`, `OLE`), cộng thêm ý nghĩa riêng: `WA` ở đây có thể là sai modifier, sai kiểu, sai format `toString`, hoặc sai hành vi — kết quả chi tiết phải ghi rõ `expected` vs `actual` để admin và sinh viên (với check visible) hiểu vì sao trượt.

### 13.11. Giao diện admin và sinh viên cho Java

**Admin — form tạo check theo từng loại (không bắt admin viết JSON tay):**

- Chọn loại check từ dropdown: Field / Constructor / Method / Getter-Setter / Validator / toString / Comparable / Comparator / Behavior chung.
- Tùy loại check mà form hiện các ô tương ứng: tên class, tên field/method, kiểu dữ liệu, modifier (checkbox: private/public/static/final...), tham số, giá trị setup, giá trị kỳ vọng, loại exception kỳ vọng.
- Thư viện mẫu: các đề mẫu có sẵn như `Student`, `BankAccount`, `Rectangle`, `Product` để admin nhân bản rồi sửa, thay vì tạo từ số 0.
- Import/export spec JSON để chia sẻ đề giữa các giảng viên, và để lưu trữ đề theo version.

**Sinh viên:**

- Editor một file Java, tiêu đề file hiển thị rõ (ví dụ `Student.java`), kèm nhắc "tên public class phải trùng tên file".
- Nút "Chạy thử" chỉ hiện khi `allow_pretest = true`, và chỉ chạy các check visible.
- Bảng kết quả: từng check visible với trạng thái pass/fail, `expected` vs `actual` (ví dụ: kỳ vọng field `private`, thực tế là `public`), thông báo lỗi biên dịch nếu có.
- Nút "Nộp bài" và xem lại bài nộp cuối như luồng Python.

### 13.12. Module code mới cần thêm (bổ sung cho mục 10)

| File mới | Vai trò |
| --- | --- |
| `judge/ReflectionJudge.java` | Harness tin cậy: đọc spec từ stdin, load class sinh viên, chạy từng check, in JSON kết quả |
| `app/java_runner.py` | Biên dịch bằng `javac`, chạy harness bằng `java` trong subprocess có timeout, temp dir riêng, giới hạn JVM (`-Xmx`, output cap) |
| `app/java_grading.py` | Chuyển kết quả harness thành điểm: cộng điểm từng check, áp trọng số, tạo verdict, lọc kết quả theo quyền hiển thị |
| `app/problems.py` (mở rộng) | Thêm `problem_kind = java_reflection`, validate spec Java (tên class, kiểu dữ liệu, modifier hợp lệ, check không trùng id) |
| `app/main.py` (mở rộng, ít) | Rẽ nhánh runner theo `problem_kind` trong route `/api/student/code/run` và `/api/student/code/submit` đã có, không tạo route mới nếu không cần |

### 13.13. Lộ trình cập nhật — Java đi vào sau Python MVP, trước khi làm Docker

Thứ tự khuyến nghị (cập nhật cho mục 10):

1. **Phase 1 (ĐÃ CHỐT 02/11/2026 — ƯU TIÊN JAVA TRƯỚC):** Java Reflection MVP — một file, một public class, package bắt buộc theo đề, toString template + exact, validator ném `IllegalArgumentException`, các check ở bảng 13.4, pretest visible, chấm cuối toàn bộ, validate bằng đáp án mẫu.
2. **Phase 2 (sau Java):** Python stdin/stdout — dùng lại khung runner, pretest, tính điểm, audit đã làm cho Java (đảo thứ tự so với bản kế hoạch ban đầu, vì môn Java đang cần gấp hơn).
3. **Phase 3 (mở rộng):** Nhiều file Java, nhiều class, template đề mẫu, import/export spec, regrade cho Java, editor tốt hơn.
4. **Phase 4:** Docker/container cho cả Python và Java runner, judge worker tách biệt, bài viết hàm Python (phương án B ở mục 2) nếu còn cần.
5. **Phase 5:** Public web — như cũ, không public tính năng chấm code trước khi xong Phase 4.

**Điều kiện tiên quyết trước khi chạy Java:** máy giảng viên phải cài JDK (khuyến nghị JDK 17+). Server nên kiểm tra `java -version` và `javac -version` lúc khởi động và in cảnh báo rõ ràng nếu thiếu, thay vì để đến lúc sinh viên nộp bài mới báo lỗi.

### 13.14. Fixture test để kiểm chứng Java MVP

- **Bài mẫu 1 —&#32;`Student`:** field private, constructor, getter/setter, validator `gpa` 0–10, `toString` template, `Comparable` theo `gpa`.
- **Bài mẫu 2 —&#32;`BankAccount`:** `deposit`/`withdraw`, validator số dư không âm, `withdraw` vượt số dư phải ném exception, `toString` chứa số dư.
- **Bài mẫu 3 —&#32;`StudentNameComparator`:** class Comparator riêng, sort theo tên.
- **Bài adversarial (phải chặn được):** `System.exit(0)` trong constructor, vòng lặp vô hạn trong getter, static initializer đọc file, setter ném sai loại exception, `toString` trả về format sai một ký tự.

---

## 14. Câu hỏi mới cần Trainer chốt cho phần Java (bổ sung cho mục 11)

**Q8. Package: ĐÃ CHỐT 02/11/2026 — Bắt buộc package theo yêu cầu từng đề bài.** Admin phải ghi rõ package trong spec, sinh viên phải khai báo đúng package đó, sai là fail check class.

**Q9. Số file: ĐÃ CHỐT 02/11/2026 — Chỉ 1 file / 1 public class cho hiện tại.** Chưa làm đa file. `StudentComparator` dạng class riêng sẽ để Phase mở rộng sau, trừ khi đề gộp comparator vào cùng class chính bằng `Comparable`.

**Q10. toString: ĐÃ CHỐT 02/11/2026 — Template có sẵn + exact sau khi điền template.** Admin cung cấp mẫu, sinh viên phải trả về đúng chính xác giá trị theo mẫu đã điền (chỉ chuẩn hóa CRLF → LF). Không dùng `contains` làm mặc định.

**Q11. Validator: ĐÃ CHỐT 02/11/2026 — Thống nhất ném&#32;`IllegalArgumentException`&#32;khi giá trị không hợp lệ.** Áp cho setter/constructor/method kiểm tra đầu vào. Predicate `isValid()`/`isPassing()` vẫn trả boolean, không thuộc quy tắc này.

**Q12. Comparator và null: CHƯA CHỐT — mặc định tạm thời: không test&#32;`null`&#32;trừ khi đề ghi rõ.** Trainer xác nhận giúp em điểm này khi chốt spec bài comparator đầu tiên.

**Q13. Thứ tự làm: ĐÃ CHỐT 02/11/2026 — Ưu tiên Java trước, sau đó đến Python.** Vì yêu cầu môn học hiện tại cần Java gấp hơn. Khung runner (temp dir, timeout, pretest, tính điểm, audit) sẽ được làm cho Java trước, rồi Python dùng lại khung đó ở Phase sau.

---

## 15. Nhật ký quyết định — Đã chốt ngày 02/11/2026 (bổ sung sau mục 13–14)

Trainer đã chốt các điểm sau, và các mục 13.3, 13.4, 13.13, 14 trong file này đã được sửa theo đúng các quyết định này (không còn là đề xuất nữa):

| # | Quyết định đã chốt | Áp dụng ở đâu |
| --- | --- | --- |
| 1 | **Package bắt buộc theo yêu cầu từng đề bài.** Spec phải ghi rõ package, sinh viên phải khai báo đúng package đó. Server đặt file nguồn đúng cấu trúc thư mục package trước khi gọi `javac`. | Mục 13.3, Q8 |
| 2 | **Hiện tại chỉ 1 file / 1 public class.** Chưa làm đa file, chưa chấm class phụ riêng. | Mục 13.3, Q9 |
| 3 | **toString: template có sẵn + exact sau khi điền template.** Admin cung cấp mẫu, sinh viên phải trả về đúng chính xác giá trị theo mẫu đã điền (chỉ chuẩn hóa CRLF → LF). | Mục 13.4, Q10 |
| 4 | **Validator chốt chung: ném&#32;`IllegalArgumentException`&#32;khi giá trị không hợp lệ.** Áp cho setter/constructor/method kiểm tra đầu vào. Predicate `isValid()`/`isPassing()` vẫn trả boolean, không thuộc quy tắc này. | Mục 13.4, Q11 |
| 5 | **Ưu tiên Java trước, sau đó đến Python.** Vì yêu cầu môn học hiện tại cần Java gấp hơn. Khung runner làm cho Java trước, Python dùng lại khung đó ở phase sau. | Mục 13.13, Q13 |

**Chưa chốt, cần xác nhận thêm khi làm bài comparator đầu tiên:**

- **Q12 — null trong Comparator/Comparable:** mặc định tạm thời là không test `null` trừ khi đề ghi rõ. Nếu đề nào cần test `null`, phải ghi rõ trong spec của check đó (ví dụ: `compare(null, x)` kỳ vọng ném `NullPointerException` hay được coi là nhỏ nhất).

**Các câu hỏi Python ở mục 11 (Q1–Q7) tạm hoãn, không hủy:** vì Java được ưu tiên trước, các quyết định về Python (stdin/stdout, pretest, số lần nộp, hiển thị điểm) sẽ chốt lại khi bắt đầu Phase Python, dựa trên kinh nghiệm làm Java trước đó.

**Bước tiếp theo đề xuất (chờ Trainer gật đầu mới làm):** Chuyển mục 13 thành **bản đặc tả triển khai Phase 1 Java** chi tiết hơn — gồm spec JSON mẫu hoàn chỉnh cho một bài `Student`, code khung `ReflectionJudge.java`, và checklist test — rồi mới bắt đầu code thật vào repo.