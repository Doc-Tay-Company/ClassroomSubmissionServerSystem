# Phase 3 fixtures

Dữ liệu mẫu độc lập cho các checkpoint Phase 3. **Không được app tự động nạp** và không ghi đè `data\*.json`.

## Nội dung

`questions.phase3.json` (định dạng như `data\questions.json`: dict theo id)

| id | Danh mục | Điểm | usage_count | Trạng thái |
|----|----------|------|-------------|-----------|
| p3-java-square | OOP | 50 | 0 | published |
| p3-java-point | Đối tượng cơ bản | 80 | 1 | published |
| p3-java-temperature | Tính toán | 100 | 3 | published |
| p3-java-rectangle | OOP | 70 | 5 | published |
| p3-java-circle-draft | Hình học | 60 | 0 | **draft** (dùng cho kiểm tra publish) |

`code_exams.phase3.json`: một Code Exam nháp `p3-code-exam-draft` tham chiếu `p3-java-point` và `p3-java-temperature` (snapshot đầy đủ, đúng schema của `create_code_exam`).

`questions.stdio.phase3.json`: hai câu **Draft** (Java STDIO 40 điểm, Python STDIO 60 điểm), cùng định dạng dict theo id. Chúng ở trạng thái Draft có chủ đích vì chưa có bản ghi validation: hãy mở trong Ngân hàng câu hỏi, nhập đáp án mẫu, chạy Validate rồi Xuất bản bằng quy trình thật. Không nạp file này nếu chỉ cần kiểm tra Reflection.

Đề nhiều câu, đề ZIP và bài nộp mẫu không được tạo giả: hãy tạo bằng giao diện (Exam Builder → Xuất bản; tài khoản sinh viên → Nộp bài) để dữ liệu đi qua đúng workflow.

## Lưu ý

- Tất cả là Java reflection; tổng điểm các check bằng `total_points`.
- Không có bản ghi `validation` (chưa chạy qua judge). `usage_count` là số lưu sẵn; lượt dùng từ đề ngoài bộ fixture không được phản ánh.
- Id đều có tiền tố `p3-` nên không trùng dữ liệu thật.

## Nạp an toàn (thủ công)

1. Dừng server, sao lưu: `Copy-Item data data.bak -Recurse`.
2. Gộp theo key, không ghi đè key sẵn có:

```powershell
python -c "
import json
def merge(real, fx):
    a = json.load(open(real, encoding='utf-8')); b = json.load(open(fx, encoding='utf-8'))
    for k, v in b.items(): a.setdefault(k, v)
    json.dump(a, open(real, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
merge('data/questions.json', 'tests/fixtures/phase3/questions.phase3.json')
merge('data/code_exams.json', 'tests/fixtures/phase3/code_exams.phase3.json')
"
```

3. Khởi động lại server và kiểm tra trong Ngân hàng câu hỏi.
4. Hoàn tác: dừng server và khôi phục `data.bak`.
