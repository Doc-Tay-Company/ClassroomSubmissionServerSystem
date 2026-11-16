# Project Context & Engineering Rules
## ClassroomSubmissionServerSystem

> Tài liệu này là nguồn context và quy tắc làm việc nền tảng dành cho Codex/AI coding agent khi đọc, phân tích, sửa lỗi hoặc phát triển dự án.  
> Đọc toàn bộ tài liệu này trước khi thực hiện bất kỳ thay đổi mã nguồn nào.

---

## 1. Mục đích tài liệu

Tài liệu xác định:

- Bối cảnh và kiến trúc dự án đã được xác nhận.
- Các thuật ngữ nghiệp vụ cần sử dụng thống nhất.
- Các quyết định thiết kế đã được chủ dự án chốt.
- Những quy tắc bắt buộc khi chỉnh sửa mã nguồn.
- Các yêu cầu bảo toàn dữ liệu, lịch sử và hành vi hiện có.
- Quy trình kiểm tra và báo cáo sau mỗi tác vụ.

Tài liệu này đóng vai trò **Project Context / Engineering Rules**, không phải yêu cầu triển khai một tính năng riêng lẻ.

Nếu một prompt tác vụ cụ thể có phạm vi hẹp hơn, hãy tuân thủ phạm vi của prompt đó nhưng không được vi phạm các quy tắc nền tảng trong tài liệu này.

---

## 2. Thông tin dự án

- **Tên dự án:** ClassroomSubmissionServerSystem
- **Loại dự án:** Hệ thống quản lý kỳ thi lập trình, nộp bài và chấm điểm tự động.
- **Môi trường phát triển:** Windows.
- **Repository được cung cấp:** `D:\JSD\ClassroomSubmissionServerSystem`
- **Branch làm việc được ghi nhận:** `feature/JudgeEngine`
- **HEAD được ghi nhận gần nhất:** `752402b8a84d98416a3f58f7f3294b161adc2fa7`

Các thông tin về branch và commit ở trên chỉ là trạng thái được ghi nhận tại một thời điểm. **Luôn kiểm tra trạng thái Git thực tế trước khi làm việc**, không được mặc định chúng vẫn còn chính xác.

### 2.1. Mục tiêu nghiệp vụ

Hệ thống hỗ trợ các hoạt động chính:

- Quản lý câu hỏi lập trình.
- Tạo và quản lý Paper (đề thi/bộ câu hỏi).
- Tạo và quản lý Exam (kỳ thi).
- Phát hành đề thi cho người học.
- Gán Paper hoặc phiên bản Paper cụ thể cho người học.
- Nhận bài nộp và xử lý chấm điểm.
- Hỗ trợ các luồng làm bài và nộp bài hiện có.
- Quản lý dữ liệu, lịch sử và trạng thái liên quan đến kỳ thi.

Không được suy luận rằng mọi chức năng được mô tả trong tài liệu định hướng đều đã được triển khai trong source code.

---

## 3. Kiến trúc và nguyên tắc xác định sự thật

### 3.1. Kiến trúc source code đã được ghi nhận

Dự án hiện tại được ghi nhận sử dụng:

- Python `ThreadingHTTPServer`.
- Jinja2 để render template.
- HTML, CSS và Vanilla JavaScript ở frontend.
- JSON / JSONL và filesystem để lưu trữ dữ liệu.

Các module chính:

```text
app/
├── main.py
├── storage.py
├── questions.py
├── general_exams.py
├── code_exams.py
├── exams.py
└── papers.py

static/
└── js/
    ├── exams.js
    ├── code-papers.js
    └── ...
```

Đây là mô tả kiến trúc đã được ghi nhận từ quá trình làm việc trước đó. Codex phải kiểm tra repository thực tế để xác nhận cấu trúc hiện tại trước khi sửa.

### 3.2. Thứ tự ưu tiên nguồn thông tin

Khi có sự khác biệt giữa tài liệu, prompt cũ và source code, áp dụng thứ tự sau:

1. Yêu cầu mới nhất và rõ ràng của chủ dự án.
2. Source code và hành vi thực tế hiện tại.
3. Các quyết định thiết kế đã được chủ dự án xác nhận trong tài liệu này.
4. README, tài liệu thiết kế hoặc tài liệu định hướng.
5. Giả định của AI.

**Không được tự ý thay đổi kiến trúc đang chạy chỉ vì README hoặc tài liệu định hướng đề xuất một kiến trúc khác.**

Ví dụ: nếu README đề cập Next.js, FastAPI, SQLite, SQLAlchemy hoặc Judge0 nhưng source code thực tế vẫn đang sử dụng `ThreadingHTTPServer`, Jinja2 và JSON/JSONL, không được tự ý chuyển đổi hệ thống sang stack trong README. Chỉ thực hiện migration khi chủ dự án yêu cầu rõ ràng.

### 3.3. Quy tắc kiểm chứng

- Không khẳng định một chức năng tồn tại nếu chưa tìm thấy trong source code.
- Không suy luận API, schema, route hoặc field chỉ từ tên file.
- Không coi comment hoặc README là bằng chứng chắc chắn về hành vi runtime.
- Khi phát hiện khác biệt giữa tài liệu và implementation, ghi rõ khác biệt trong báo cáo.
- Nếu chưa đủ bằng chứng để xác định nguyên nhân, phải ghi là **chưa xác định**, không được biến giả thuyết thành kết luận.

---

## 4. Các thuật ngữ nghiệp vụ bắt buộc

Không được sử dụng lẫn lộn các khái niệm sau.

### 4.1. Question

Một câu hỏi/bài tập được lưu trong Question Bank.

Question có thể chứa nội dung, loại câu hỏi, Tag, cấu hình ngôn ngữ, test case và các metadata khác tùy theo implementation thực tế.

### 4.2. Paper

Một bộ câu hỏi lập trình có thứ tự.

Paper có thể có:

- Draft hiện tại.
- Một hoặc nhiều Published Version.
- Trạng thái quản lý như draft, published hoặc archived.
- Danh sách Question ID và thứ tự câu hỏi.

Paper không đồng nghĩa với một kỳ thi đang diễn ra.

### 4.3. Exam

Một kỳ thi/sự kiện tổ chức thi.

Exam quản lý các thông tin vận hành như:

- Thời gian và thời lượng.
- Trạng thái vòng đời kỳ thi.
- Người tham gia.
- Loại nội dung hoặc loại đề thi được sử dụng.
- Cấu hình và quy tắc tổ chức thi.

Exam không đồng nghĩa với Paper. Một Exam có thể tham chiếu đến Paper hoặc một loại nội dung thi khác theo thiết kế hiện tại.

### 4.4. Release

Một sự kiện phát hành/phân phối nội dung thi.

Release ghi nhận việc nội dung thi được phát hành theo một cấu hình hoặc thời điểm cụ thể.

### 4.5. Assignment

Bản ghi gán nội dung thi cho người học.

Assignment phải giữ tham chiếu chính xác đến Paper Version hoặc nội dung được gán tại thời điểm tạo. Không được âm thầm chuyển Assignment cũ sang phiên bản mới khi Paper được chỉnh sửa hoặc xuất bản lại.

### 4.6. Snapshot

Bản chụp nội dung bất biến dùng để bảo toàn lịch sử tại một thời điểm, ví dụ khi phát hành đề hoặc ghi nhận bài nộp.

Không được cập nhật nội dung Snapshot lịch sử theo thay đổi mới của Paper hoặc Question.

---

## 5. Quyết định thiết kế đã được xác nhận

Các quyết định dưới đây được xem là yêu cầu đã chốt. Không tự ý thay đổi nếu chưa có yêu cầu mới từ chủ dự án.

### 5.1. Paper Draft và Published Version

- Mỗi Paper ID có một Draft hiện tại có thể chỉnh sửa.
- Draft không có lịch sử revision riêng.
- Published Version là phiên bản đã phát hành và phải được bảo toàn.
- Published Version không được sửa trực tiếp.
- Khi tạo Published Version mới, các Published Version cũ vẫn phải được giữ nguyên.
- Không được ghi đè nội dung Published Version cũ bằng nội dung Draft mới.

### 5.2. Chức năng “Chỉnh sửa bản mới” từ Published Paper

Khi người dùng chọn **“Chỉnh sửa bản mới”** từ màn hình xem chi tiết một Published Paper:

- Phải tạo một Paper độc lập với Paper ID mới.
- Paper nguồn không bị thay đổi.
- Draft hiện có của Paper nguồn, nếu có, không bị thay đổi.
- Paper mới có trạng thái `draft`.
- Nội dung Draft ban đầu được khởi tạo từ Published Version mới nhất của Paper nguồn.
- Paper mới không có Published Version:
  - `versions = {}`
  - `current_version_id = None`
- Lần lưu đầu tiên phải tạo Paper mới bằng API tạo mới, ví dụ `POST /api/admin/papers`, nếu đây là API thực tế đang được sử dụng.
- Không được gửi yêu cầu cập nhật Paper nguồn bằng ID cũ.
- Payload tạo Paper mới phải phản ánh nội dung hiện tại trong Editor, không chỉ lấy lại dữ liệu ban đầu.
- Khi tạo thành công: refresh danh sách và đóng Editor/quay lại danh sách theo UX hiện có.
- Khi tạo thất bại: giữ Editor mở và giữ nguyên nội dung người dùng đang nhập.
- Không thay đổi Exam, Assignment, Release hoặc tham chiếu lịch sử hiện có.
- Không tự động phân phối Paper mới.

Lưu ý: phải xác minh route/API và schema thực tế trước khi sửa; ví dụ endpoint ở trên không phải giấy phép để tự tạo API mới nếu dự án đã có quy ước khác.

### 5.3. Chỉnh sửa Paper thông thường

Hành động **“Chỉnh sửa”** trên Paper đang có tiếp tục chỉnh sửa Draft của chính Paper đó theo ID hiện tại.

Không áp dụng hành vi tạo Paper mới cho chức năng chỉnh sửa thông thường.

### 5.4. Trạng thái hiển thị trong Paper List

Nhãn trạng thái chính cần thể hiện:

| Trạng thái dữ liệu | Nội dung hiển thị |
|---|---|
| Draft | `Nháp` |
| Published, không có Draft | `Đã xuất bản` |
| Published và có Draft | `Đã xuất bản · Có bản nháp` |
| Archived | `Lưu trữ` |

Quy tắc bổ sung:

- Không hiển thị thêm một Draft badge riêng cạnh tiêu đề nếu trạng thái chính đã thể hiện thông tin đó.
- Có thể giữ các warning badge khác nếu chúng phục vụ mục đích riêng.
- Với Paper Draft, các hành động chính xác là:
  - `Chỉnh sửa`
  - `Lưu trữ`
  - `Xóa`
- Không hiển thị hành động `Mở` cho Paper Draft.
- Published Paper có thể có hành động `Mở` và các hành động hợp lệ khác theo implementation hiện tại.
- Phải bảo toàn quy tắc Archive hiện có; không tự ý thay đổi cách lưu trữ hoặc xóa dữ liệu.

### 5.5. Paper Management layout

- Khôi phục bố cục bảng (table) ban đầu tại khu vực Paper Management:
  `/admin?section=exam-management&tab=papers`
- Không tự ý thay thế bảng desktop bằng card layout hoặc một vùng cuộn dọc mới.
- Trên màn hình nhỏ, có thể dùng cuộn ngang nếu cần để giữ cấu trúc bảng.
- Giữ các cột và thao tác phù hợp với thiết kế gốc sau khi kiểm tra Git history/source hiện tại.

---

## 6. Quy tắc Tag, Filter và Selection trong Paper Editor

Đây là các trạng thái độc lập và phải được quản lý riêng.

### 6.1. Filter State và Selection State

- **Filter State:** điều khiển Question nào đang hiển thị trong danh sách.
- **Selection State:** lưu Question ID nào đã được chọn cho Paper và thứ tự chọn.

Thay đổi bộ lọc không được làm thay đổi Selection State.

### 6.2. Thay đổi Filter

Khi người dùng thay đổi Tag, từ khóa tìm kiếm hoặc filter khác:

- Chỉ cập nhật danh sách Question đang hiển thị.
- Không xóa các Question đã chọn.
- Không thay đổi thứ tự các Question đã chọn.
- Question đã chọn nhưng bị ẩn bởi filter vẫn phải nằm trong Selection State.
- Khi bỏ filter, danh sách phải hiển thị lại các Question phù hợp mà không làm mất lựa chọn trước đó.

### 6.3. Chọn/bỏ chọn thủ công

- Thao tác thêm một Question chỉ thêm đúng Question ID đó.
- Thao tác bỏ chọn một Question chỉ xóa đúng Question ID đó.
- Không được xóa các Question đã chọn khác chỉ vì chúng không nằm trong danh sách đang lọc.
- Không tạo ID trùng lặp.
- Phải bảo toàn thứ tự đã chọn theo quy tắc hiện có.

### 6.4. Quy tắc kết hợp Filter

- Nhiều Tag được chọn: kết hợp theo OR.
- Các nhóm filter khác nhau: kết hợp theo AND.
- Ví dụ: Question phải khớp ít nhất một Tag được chọn, đồng thời phải thỏa các filter loại câu hỏi, mức độ hoặc từ khóa khác nếu các filter này đang bật.

Chỉ áp dụng cho các filter thực sự tồn tại trong implementation; không tự thêm filter mới.

### 6.5. Chọn tất cả câu phù hợp

Hành động **“Chọn tất cả câu phù hợp”** có ý nghĩa thay thế toàn bộ Selection State bằng danh sách Question đang khớp với bộ lọc hiện tại.

Đây là hành vi thay thế có chủ đích, khác với checkbox chọn một nhóm.

### 6.6. Checkbox chọn nhóm

Checkbox chọn nhóm chỉ thêm hoặc bỏ các Question thuộc nhóm đang hiển thị/lọc.

- Khi chọn nhóm: thêm các Question hiện thuộc nhóm vào Selection State.
- Khi bỏ chọn nhóm: xóa các Question hiện thuộc nhóm khỏi Selection State.
- Các Question đã chọn nằm ngoài nhóm hiện tại phải được giữ nguyên.

### 6.7. Question Limit

- Không cho phép thêm Question mới khi đã đạt giới hạn.
- Vẫn cho phép bỏ chọn Question khi đã đạt giới hạn.
- UI phải thể hiện rõ giới hạn và trạng thái hiện tại.
- Không được vô hiệu hóa toàn bộ thao tác checkbox nếu điều đó khiến người dùng không thể bỏ chọn.

### 6.8. Edit mode và Save payload

- Khi mở Paper để chỉnh sửa, phải khôi phục chính xác danh sách `question_ids` và thứ tự của chúng.
- Save payload phải được tạo từ Selection State đầy đủ.
- Không được tạo payload chỉ từ danh sách Question đang hiển thị sau filter.
- Không được làm mất các Question đã chọn nhưng hiện đang bị filter ẩn.

---

## 7. Quy tắc Save và Publish

### 7.1. Nguyên tắc chung

- Không sử dụng autosave cho Paper.
- Người dùng phải chủ động nhấn nút Save để lưu thay đổi.
- Quy tắc lưu phải nhất quán cho các trạng thái Paper có thể chỉnh sửa.
- Không được âm thầm lưu nội dung khi người dùng chỉ thay đổi trường dữ liệu hoặc chuyển tab.
- Nếu có thay đổi chưa lưu, UI cần thể hiện trạng thái chưa lưu phù hợp.
- Khi người dùng rời Editor hoặc đóng Editor trong lúc còn thay đổi chưa lưu, cần cảnh báo/xác nhận theo UX hiện có.

### 7.2. Save không đồng nghĩa với Publish

Hai hành động phải tách biệt:

- **Save:** lưu nội dung Draft hiện tại.
- **Publish:** tạo Published Version mới từ nội dung được xác nhận.

Không được tự động Publish khi Save.

Không được tự động Save nội dung mới vào Published Version cũ.

### 7.3. Xử lý lỗi

Nếu Save thất bại:

- Không xóa nội dung đang chỉnh sửa.
- Không đóng Editor.
- Không cập nhật UI như thể đã lưu thành công.
- Hiển thị lỗi đủ rõ để người dùng biết thao tác chưa hoàn tất.
- Cho phép người dùng thử Save lại.

Nếu Publish thất bại, phải giữ nguyên dữ liệu và trạng thái trước thao tác; không được tạo Published Version giả hoặc hiển thị thành công sai thực tế.

---

## 8. Quy tắc hiển thị thông tin trong Exam Management

- Không hiển thị Paper ID, revision ID, version ID hoặc các định danh nội bộ không cần thiết trên giao diện Exam Management dành cho người dùng.
- Không hiển thị những thông tin kỹ thuật có thể gây lộ cấu trúc nội bộ hoặc gây nhầm lẫn cho người dùng.
- Chỉ ẩn ở lớp giao diện nếu API/backend vẫn cần các định danh này để xử lý.
- Không xóa field khỏi database, JSON, API response hoặc internal state chỉ vì không muốn hiển thị trên UI.
- Không thay đổi contract của API nếu không có bằng chứng rằng contract đó cần thay đổi.
- Exam vẫn phải tham chiếu đúng Paper/Published Version/Assignment theo cấu trúc dữ liệu hiện tại.
- Việc ẩn ID trên UI không được làm hỏng chức năng mở, sửa, phát hành hoặc truy xuất Paper.

---

## 9. Quy tắc bảo toàn dữ liệu và tương thích ngược

Đây là nhóm quy tắc bắt buộc.

### 9.1. Không phá hủy dữ liệu

Không được tự ý:

- Xóa dữ liệu Exam cũ hoặc mới.
- Xóa Paper hoặc Question đang được tham chiếu.
- Xóa Published Version.
- Xóa Release hoặc Assignment lịch sử.
- Ghi đè Snapshot lịch sử.
- Thay đổi bài nộp hoặc kết quả đã lưu.
- Chạy script reset, seed, migration hoặc cleanup có khả năng làm mất dữ liệu mà chưa được cho phép rõ ràng.

### 9.2. Tương thích Paper cũ và mới

Hệ thống có thể chứa Paper được tạo từ các phiên bản cấu trúc khác nhau.

Khi đọc dữ liệu:

- Kiểm tra schema thực tế của các Paper cũ và mới.
- Xác định field bắt buộc, field tùy chọn, field thiếu và giá trị mặc định.
- Chuẩn hóa dữ liệu ở lớp đọc/adapter nếu cần.
- Không tự ý ghi lại toàn bộ dữ liệu cũ chỉ để phù hợp với UI mới.
- Không giả định mọi Paper đều có cùng cấu trúc hoặc cùng lịch sử version.
- Không làm mất nội dung, Question ID, thứ tự câu hỏi, trạng thái hoặc tham chiếu.
- Nếu một cấu trúc cũ không thể chuyển đổi an toàn, phải báo cáo và đề xuất phương án thay vì tự sửa dữ liệu.

### 9.3. Không cập nhật lịch sử theo dữ liệu hiện tại

- Published Version cũ phải giữ nguyên nội dung tại thời điểm Publish.
- Assignment cũ phải tiếp tục tham chiếu đúng nội dung đã được gán.
- Release cũ phải giữ nguyên dữ liệu phát hành.
- Snapshot cũ không được đồng bộ ngược từ Paper hiện tại.
- Sửa Draft không được làm thay đổi nội dung của kỳ thi đã phát hành trước đó.

### 9.4. Phạm vi thay đổi tối thiểu

Chỉ sửa đúng khu vực cần thiết để giải quyết yêu cầu đã xác nhận.

Không refactor diện rộng hoặc thay đổi module không liên quan nếu không có lý do kỹ thuật rõ ràng.

---

## 10. Quy tắc làm việc với Git

Trước khi sửa code, bắt buộc kiểm tra:

```bash
git status --short
git branch --show-current
git log -1 --oneline
```

Nếu cần hiểu lịch sử thay đổi, kiểm tra thêm:

```bash
git diff
git diff --cached
git log --oneline --decorate -n 10
```

Quy tắc:

- Không xóa hoặc ghi đè thay đổi chưa commit của người dùng.
- Không chạy `git reset --hard`.
- Không chạy `git clean -fd` hoặc các lệnh cleanup tương tự.
- Không tự ý checkout branch khác.
- Không tự ý stash, discard hoặc restore file đang có thay đổi.
- Không tự ý commit hoặc push.
- Không sửa file ngoài phạm vi nếu không có lý do được giải thích.
- Nếu phát hiện thay đổi chưa commit có thể bị ảnh hưởng, dừng và báo cáo trước khi tiếp tục.
- Sau khi hoàn tất, báo cáo rõ các file đã thay đổi và trạng thái Git.

---

## 11. Quy tắc kiểm thử

Sau mỗi thay đổi, lựa chọn kiểm thử phù hợp với phạm vi.

### 11.1. Kiểm tra cú pháp

Với JavaScript:

```bash
node --check static/js/code-papers.js
node --check static/js/exams.js
```

Chỉ chạy với file thực tế có trong repository.

### 11.2. Kiểm thử chức năng

Ưu tiên kiểm thử các hành vi liên quan trực tiếp đến thay đổi, ví dụ:

- Paper cũ và Paper mới đều mở được.
- Paper Draft được chỉnh sửa và Save đúng.
- Published Paper vẫn giữ nguyên Published Version cũ.
- “Chỉnh sửa bản mới” tạo Paper ID mới.
- Save không tự động Publish.
- Publish tạo version mới mà không ghi đè version cũ.
- Exam cũ và mới vẫn hiển thị và hoạt động đúng.
- Exam Management không hiển thị ID/revision nội bộ.
- Tag filter không làm mất Question đã chọn.
- Chọn/bỏ chọn thủ công không ảnh hưởng các Question ngoài filter.
- Select All và checkbox nhóm tuân thủ đúng hai hành vi khác nhau.
- Edit mode khôi phục đúng danh sách và thứ tự Question.
- Save payload chứa toàn bộ Selection State.

### 11.3. Kiểm tra diff

Sau khi sửa:

```bash
git diff --check
git status --short
git diff --stat
```

Nếu có thể, kiểm tra thêm conflict marker:

```bash
git grep -n -E '^(<<<<<<<|=======|>>>>>>>)' -- .
```

Không kết luận test thành công nếu chưa thực sự chạy test và xem kết quả.

### 11.4. Không làm thay đổi dữ liệu runtime khi không cần thiết

- Không khởi động workflow có thể tự ghi dữ liệu production/local runtime nếu chưa hiểu tác động.
- Không tạo Exam, Paper, Release hoặc Assignment giả trong dữ liệu thật để thử nghiệm.
- Ưu tiên fixture, temporary test data hoặc test environment.
- Nếu một test có nguy cơ ghi dữ liệu thật, phải kiểm tra cơ chế trước khi chạy.

---

## 12. Quy trình thực hiện mỗi tác vụ

Codex phải thực hiện theo trình tự sau:

1. Đọc tài liệu này.
2. Kiểm tra Git status, branch và commit hiện tại.
3. Đọc `AGENTS.md` hoặc các chỉ dẫn repository khác nếu tồn tại.
4. Tìm đúng module, route, API, schema và UI liên quan.
5. Truy vết luồng dữ liệu từ UI đến backend/storage và ngược lại khi cần.
6. Xác định nguyên nhân bằng bằng chứng từ source code hoặc test.
7. Nêu rõ phạm vi dự kiến thay đổi.
8. Thực hiện thay đổi nhỏ nhất đáp ứng yêu cầu.
9. Bổ sung hoặc cập nhật test hồi quy.
10. Chạy kiểm tra cú pháp, test và diff phù hợp.
11. Kiểm tra lại dữ liệu lịch sử và các luồng liên quan.
12. Báo cáo kết quả, giới hạn và vấn đề chưa giải quyết.

Nếu tác vụ yêu cầu audit-only hoặc chỉ phân tích, **không được sửa bất kỳ file nào**.

Nếu phát hiện yêu cầu mới xung đột với quyết định đã chốt trong tài liệu này, không tự chọn một phương án. Hãy nêu xung đột và xin xác nhận.

---

## 13. Định dạng báo cáo bắt buộc

Sau mỗi tác vụ, báo cáo bằng tiếng Việt theo cấu trúc:

### 1. Kết quả
- Đã hoàn thành/chưa hoàn thành.
- Hành vi nào đã được sửa hoặc xác nhận.

### 2. Nguyên nhân gốc
- Nguyên nhân được xác nhận.
- File và vị trí liên quan.
- Phân biệt rõ nguyên nhân đã chứng minh với giả thuyết.

### 3. File thay đổi
- Danh sách file.
- Mục đích thay đổi của từng file.

### 4. Kiểm thử
- Lệnh đã chạy.
- Kết quả thực tế.
- Test chưa chạy và lý do.

### 5. Bảo toàn dữ liệu
- Có hoặc không thay đổi dữ liệu runtime.
- Đã kiểm tra Paper/Exam/Published Version/Release/Assignment/Snapshot nào.
- Rủi ro còn lại nếu có.

### 6. Git
- Branch và commit nền.
- Trạng thái working tree trước/sau nếu đã ghi nhận.
- Có hay không commit/push.
- Các thay đổi có sẵn của người dùng có được giữ nguyên không.

### 7. Vấn đề còn tồn tại
- Những phần chưa xử lý.
- Những phần chưa thể xác minh.
- Bước kiểm thử tiếp theo được đề xuất.

Không được dùng các câu như “đã hoàn tất 100%”, “không còn lỗi” hoặc “mọi thứ hoạt động hoàn hảo” nếu phạm vi kiểm thử không đủ để chứng minh.

---

## 14. Những hành động bị cấm nếu chưa được chủ dự án cho phép

- Thay đổi framework hoặc database.
- Migration toàn bộ kiến trúc.
- Xóa hoặc tái tạo dữ liệu.
- Reset database hoặc runtime data.
- Xóa Exam, Paper, Question, Published Version, Release, Assignment, Submission hoặc Snapshot lịch sử.
- Thay đổi API contract trên diện rộng.
- Viết lại Judge Engine hoặc các execution runner.
- Thay đổi Java Reflection, Java/Python STDIO runner, hidden tests hoặc pretest.
- Loại bỏ editor hoặc các workflow nộp bài hiện có.
- Thay đổi Practice Mode hoặc ZIP Exam.
- Thay đổi authentication/authorization ngoài phạm vi.
- Tự động phân phối Paper mới.
- Tự ý commit hoặc push.
- Khẳng định đã kiểm thử browser, LAN hoặc offline khi chưa thực hiện.

---

## 15. Các khu vực cần bảo vệ đặc biệt

Trừ khi tác vụ yêu cầu trực tiếp và có phân tích tác động rõ ràng, phải giữ nguyên:

- Judge Engine.
- Java Reflection.
- Java/Python STDIO runners.
- Hidden tests.
- Pretest.
- Code editor.
- Single submission workflow.
- Whole submission workflow.
- Practice Mode.
- ZIP Exam.
- Authentication và authorization.
- Existing APIs và data contracts.
- Exam, Paper, Question và các liên kết dữ liệu.
- Published Versions và historical snapshots.
- Submission records và grading results.

Không được xem đây là danh sách cho phép sửa. Đây là danh sách các thành phần cần được bảo vệ khỏi thay đổi ngoài phạm vi.

---

## 16. Nguyên tắc cuối cùng

**Ưu tiên tính đúng đắn, khả năng tương thích và bảo toàn dữ liệu hơn việc refactor hoặc làm mới giao diện.**

Mọi thay đổi phải:

1. Có yêu cầu rõ ràng.
2. Có nguyên nhân hoặc mục tiêu kỹ thuật xác định.
3. Có phạm vi nhỏ nhất hợp lý.
4. Không phá vỡ dữ liệu và workflow hiện có.
5. Có kiểm thử phù hợp.
6. Có báo cáo trung thực về những gì đã và chưa được xác minh.

Nếu không chắc chắn về schema, dữ liệu lịch sử hoặc hành vi của một workflow, hãy dừng ở bước phân tích và báo cáo bằng chứng cần thiết. Không tự suy đoán rồi sửa dữ liệu.
