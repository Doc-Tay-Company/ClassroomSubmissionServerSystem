# Đặc tả kỹ thuật — Classroom Submission Server

**Phiên bản:** 0.1.0 (MVP chạy LAN)  
**Mục tiêu:** Quản lý tài khoản, phân phối đề thi, theo dõi tiến độ và nhận bài ZIP trên máy giảng viên.  
**Mô hình lưu trữ:** JSON/JSONL + thư mục file; không cần database server.

**Dependency runtime:** chỉ Jinja2 để render HTML. HTTP server, parser form và multipart upload dùng thư viện chuẩn Python. Không sử dụng FastAPI, Pydantic, Uvicorn, Starlette, `python-multipart` hoặc PyYAML.

## 1. Quyết định kiến trúc

| Thành phần | Quyết định | Lý do |
|---|---|---|
| Backend | `http.server.ThreadingHTTPServer` của Python standard library | Không phụ thuộc FastAPI/Pydantic/Uvicorn; xử lý HTTP trong project |
| Giao diện | HTML template + JavaScript | Không cần framework frontend riêng để triển khai bản đầu |
| CSS | Tailwind CSS build thành file local; `app.css` làm lớp giao diện | Không dùng CDN khi chạy |
| Icon | Font Awesome 4.7.0 CSS/font local | Không tải font ngoài khi chạy |
| Cập nhật Dashboard | Polling HTTP mỗi 5 giây | Không cần WebSocket hoặc thư viện mạng bổ sung |
| Lưu tài khoản/cấu hình | JSON | Dễ sao lưu, đọc và vận hành offline |
| Nhật ký | JSONL append-only | Ghi từng sự kiện độc lập, thuận tiện kiểm tra |
| Mật khẩu | `hashlib.scrypt` + salt riêng | Không lưu mật khẩu thuần |
| Session | Token ngẫu nhiên trong cookie HttpOnly; chỉ lưu SHA-256 token ở server | File session bị lộ không trực tiếp cung cấp bearer token |
| Nộp bài | File ZIP trong `submissions/` | Giữ tương thích luồng nộp file cũ |
| Chạy process | Một process `ThreadingHTTPServer` | Khóa JSON trong bộ nhớ chỉ bảo vệ một process |

## 2. Vai trò

### Sinh viên

- Đăng nhập bằng MSSV và mật khẩu ban đầu là chuỗi ngày sinh đã nhập khi tạo tài khoản.
- Chỉ thấy thông báo được phân phối đề; không thấy tên/nội dung đề qua giao diện trước khi bắt đầu.
- Nếu Admin bật mật khẩu đề, nhập mật khẩu trước khi bắt đầu.
- Bắt đầu thi một lần; server ghi `started_at` và `ends_at` theo UTC.
- Xem đề được giao sau khi bắt đầu; server từ chối mở đề sau khi hết giờ hoặc lượt thi đã kết thúc.
- Nộp một file `.zip`; server xác thực ZIP và chính sách số lần nộp.

### Admin

- Đăng nhập bằng tài khoản Admin được tạo ở bước bootstrap hoặc bởi Admin hiện có.
- Xem IP, User-Agent, trạng thái hoạt động trong web app, đề đã giao, thời gian còn lại và bài nộp.
- Nhập tài khoản từ text hoặc `.txt`; tải mẫu; reset mật khẩu; khóa/mở tài khoản sinh viên.
- Tạo thêm Admin.
- Chọn file đề từ `de-thi/`, cấu hình chế độ phân phối, thời gian thi, mật khẩu đề và chính sách nộp.
- Tải file bài nộp còn được lưu và xem metadata/audit.
- Kết thúc lượt thi hiện tại. Kết thúc không thay đổi lịch sử audit; muốn phát lượt mới thì phải kết thúc lượt trước.

## 3. Mô hình dữ liệu

### `students.json`

```json
{
  "21010001": {
    "student_id": "21010001",
    "full_name": "Nguyen Van A",
    "password_hash": "scrypt$...$...",
    "active": true,
    "created_at": "2026-10-24T00:00:00+00:00",
    "last_ip": "192.168.1.101",
    "last_seen": "2026-10-24T00:00:00+00:00",
    "must_change_password": false
  }
}
```

Không lưu ngày sinh sau khi tạo tài khoản. Admin không thể đọc lại mật khẩu; phải reset nếu cần cấp lại.

### `admins.json`

Tương tự `students.json`, nhưng khóa theo username, gồm `password_hash`, `active`, `created_at`, `created_by`.

### `settings.json`

Gồm `exam_duration_minutes`, `submission_policy` (`once` hoặc `configurable`), `max_submissions`, `overwrite_previous`, `exam_password_enabled`, `exam_password_hash`, `distribution_mode`, `distribution_config`, `exam_released`, `exam_release_id`, `exam_release_at`.

### `assignments.json`

Khóa theo MSSV; mỗi record gồm `exam_file`, `release_id`, `assigned_at`, `ip_at_assignment`, `ip_at_start`, `started_at`, `ends_at`, `status`. Sau khi phát, endpoint phân phối bị khóa trong cùng lượt.

### `submissions.json`

Khóa theo MSSV, giá trị là danh sách các lần nộp. Mỗi record lưu tên file lưu trên server, tên gốc đã làm sạch, dung lượng, thời gian, IP, SHA-256, trạng thái và `payload_retained`. Nếu ghi đè payload cũ, metadata lần nộp cũ vẫn được giữ để đếm số lần.

### `sessions.json`

Khóa theo SHA-256 của session token; record gồm user ID, role, thời điểm tạo/hết hạn, IP, User-Agent và `last_seen`. Mỗi tài khoản sinh viên chỉ giữ một phiên đăng nhập đang hoạt động; đăng nhập từ máy khác thu hồi phiên cũ.

### `audit.jsonl`

Mỗi dòng là một JSON object độc lập gồm `occurred_at`, `event`, `actor`, `ip`, `details`. Các sự kiện gồm đăng nhập thành công/thất bại/khóa, tạo tài khoản, reset mật khẩu, thay đổi cấu hình, phát đề, bắt đầu/xem đề, nộp bài, tải bài.

## 4. Quy tắc nghiệp vụ

### 4.1 Đăng nhập

- Sau 3 lần đăng nhập sai liên tiếp theo tên tài khoản, khóa trong 15 phút.
- Sau đăng nhập thành công, bộ đếm sai được xóa.
- Session hết hạn sau 12 giờ; cookie `HttpOnly`, `SameSite=Strict`, `Secure` khi bật TLS.
- POST endpoint xác thực bằng session và quyền; không phụ thuộc header Origin để tương thích Windows/WebView.
- Mật khẩu dùng scrypt và salt riêng; không thể hiển thị lại.

### 4.2 Nhập tài khoản

- Mỗi dòng: `MSSV|Ngày sinh|Họ tên`.
- Trim đầu/cuối của dòng và từng trường.
- Bỏ dòng trống và dòng comment bắt đầu bằng `#`.
- Dòng không đủ/ thừa trường, MSSV không hợp lệ, MSSV lặp trong batch được báo lỗi.
- MSSV đã có trong `students.json` không bị ghi đè.
- File import tối đa 2 MiB, encoding UTF-8.

### 4.3 Phân phối đề

- `random`: xáo trộn tập file đề, phân nhóm theo subnet (`/24` IPv4 hoặc `/64` IPv6), sắp xếp theo IP đã biết và luân phiên đề để các IP gần nhau ưu tiên nhận đề khác nhau.
- `parity`: chữ số cuối cùng có giá trị số trong MSSV quyết định nhóm chẵn/lẻ; Admin chọn file cụ thể cho từng nhóm.
- `custom`: ánh xạ chữ số cuối `0`–`9` tới tên file đề thực tế.
- Chỉ file trong `de-thi/` với phần mở rộng PDF/TXT/ảnh được hỗ trợ mới được chọn.
- Nếu có ít đề hơn số máy, không thể bảo đảm mọi sinh viên có đề khác nhau; hệ thống phân bổ vòng tròn để giảm trùng giữa các IP liền kề.
- Nếu IP chưa từng quan sát được, server không thể biết vị trí thực của máy đó. Khuyến nghị cho sinh viên đăng nhập trước khi phát đề để có IP hiện tại.
- Phát đề lưu snapshot gắn `release_id`; không cho phát lần nữa hoặc thay đổi cấu hình trong cùng lượt. Admin phải kết thúc lượt trước khi phát lượt mới.

### 4.4 Thời gian thi

- `started_at` do server ghi khi nhận yêu cầu bắt đầu.
- `ends_at = started_at + exam_duration_minutes`.
- Countdown phía client chỉ để hiển thị; endpoint xem đề và nộp bài đều kiểm tra đồng hồ server.
- Khi hết giờ, server từ chối mở đề và từ chối nộp muộn; không tự động nộp bài.

### 4.5 Nộp bài

- Chỉ file `.zip`; tối đa 50 MiB.
- Kiểm tra signature ZIP, cấu trúc archive, CRC, số entry tối đa 3.000, tổng kích thước giải nén tối đa 250 MiB và đường dẫn không an toàn.
- Không giải nén archive lên đĩa.
- Chính sách `once`: chỉ một lần. `configurable`: theo `max_submissions` từ 1–20.
- Nếu bật `overwrite_previous`, payload cũ bị xóa nhưng metadata lịch sử giữ lại; lần nộp vẫn được tính vào giới hạn.

## 5. HTTP API

| Method | Endpoint | Vai trò | Mục đích |
|---|---|---|---|
| GET | `/login` | Công khai | Trang đăng nhập |
| POST | `/login` | Công khai | Xác thực, lockout và tạo session |
| POST | `/logout` | Đã đăng nhập | Thu hồi session |
| GET | `/` | Sinh viên | Trang làm bài |
| GET | `/admin` | Admin | Dashboard |
| GET | `/health` | Công khai | Kiểm tra server |
| GET | `/admin/accounts-template.txt` | Admin | Tải mẫu nhập tài khoản |
| GET | `/api/admin/monitor` | Admin | Snapshot giám sát |
| GET | `/api/admin/accounts` | Admin | Danh sách tài khoản |
| POST | `/api/admin/accounts/import` | Admin | Import/paste danh sách |
| POST | `/api/admin/accounts/{id}/reset-password` | Admin | Reset mật khẩu |
| POST | `/api/admin/accounts/{id}/toggle` | Admin | Khóa/mở tài khoản |
| GET | `/api/admin/admins` | Admin | Danh sách Admin |
| POST | `/api/admin/admins` | Admin | Tạo Admin |
| GET | `/api/admin/server-info` | Admin | IP/URL server |
| GET | `/api/admin/exams` | Admin | Danh sách file đề |
| POST | `/api/admin/settings` | Admin | Lưu cấu hình trước khi phát đề |
| POST | `/api/admin/distribute` | Admin | Phát đề |
| POST | `/api/admin/end-exam` | Admin | Kết thúc lượt thi |
| GET | `/api/admin/submissions` | Admin | Danh sách metadata bài nộp |
| GET | `/admin/submissions/{id}/{filename}` | Admin | Tải file ZIP còn được lưu |
| POST | `/api/student/start` | Sinh viên | Bắt đầu thi |
| GET | `/api/student/exam` | Sinh viên | Mở đề đã được giao sau khi bắt đầu |
| GET | `/api/student/status` | Sinh viên | Trạng thái/countdown server |
| POST | `/api/student/submit` | Sinh viên | Nộp ZIP |

## 6. An toàn dữ liệu và giới hạn

- JSON atomic replacement giúp tránh file bị ghi dở khi process dừng, nhưng không thay thế transaction database. Chạy đúng một worker.
- Audit JSONL được append và flush sau mỗi sự kiện. Cần backup thư mục `data/`, `logs/`, `submissions/` khi server dừng hoặc theo quy trình backup nhất quán.
- File tài khoản có hash mật khẩu nhưng vẫn chứa thông tin cá nhân như họ tên và IP; cần giới hạn quyền truy cập thư mục trên hệ điều hành.
- HTTP không mã hóa. Có thể bật HTTPS bằng `CSS_TLS_CERT` và `CSS_TLS_KEY` với chứng chỉ được máy trạm tin cậy; cookie Secure được bật khi dùng TLS.
- Trình duyệt chỉ cho server biết các hoạt động bên trong ứng dụng, IP kết nối và User-Agent; không cho phép theo dõi toàn bộ desktop/ứng dụng khác.
- Không có endpoint tự động chạy code nộp bài; ZIP chỉ được kiểm tra và lưu.

## 7. Tiêu chí nghiệm thu bản đầu

1. Khởi tạo Admin bằng CLI, đăng nhập thành công và mật khẩu không xuất hiện dạng thuần trong JSON.
2. Ba lần đăng nhập sai khóa tài khoản 15 phút; tài khoản bị khóa không tạo session.
3. Import `.txt` và paste đều trim space; dòng sai và MSSV trùng được báo; MSSV hiện có không bị thay thế.
4. Admin thấy URL LAN, danh sách đề thực tế và danh sách sinh viên/IP/hoạt động.
5. Ba chế độ phân phối hoạt động; random ưu tiên đề khác nhau cho IP gần nhau khi có ít nhất hai đề.
6. Sau phát đề, phân phối lại và chỉnh cấu hình bị từ chối; kết thúc lượt cho phép tạo lượt mới.
7. Sinh viên không thể xem file đề trước khi bắt đầu; bắt đầu ghi mốc giờ server; thay đổi giờ máy không thay đổi deadline.
8. ZIP hợp lệ được nhận; file không phải ZIP, ZIP hỏng, ZIP quá lớn và nộp sau giờ bị từ chối.
9. Chính sách nộp một lần/số lần cấu hình hoạt động; ghi đè xóa payload cũ nhưng vẫn giữ metadata lịch sử.
10. Admin tải được file còn lưu; Dashboard cập nhật theo chu kỳ polling HTTP.
