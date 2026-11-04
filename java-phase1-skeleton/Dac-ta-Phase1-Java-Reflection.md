# Đặc tả triển khai Phase 1 — Chấm method Java bằng Reflection

> **Phạm vi:** Bản đặc tả này là bước tiếp theo của bản kế hoạch tổng
> (`Ke-hoach-Cham-Code-Tu-Dong-ClassroomSubmission.md`, mục 13–15).
> Nó chỉ làm **Phase 1 Java**, theo đúng các quyết định Trainer đã chốt
> ngày 02/11/2026. Python sẽ làm sau, dùng lại khung này.
> >
> Kết quả kỳ vọng cho từng mẫu
> đã ghi rõ trong README đó — nếu lệch thì đó là lỗi cần sửa
> >
> **Quyết định đã chốt được áp dụng xuyên suốt bản này:**
> >
> 1. Package bắt buộc theo yêu cầu từng đề bài.
> 2. Hiện tại chỉ 1 file / 1 public class.
> 3. toString: template có sẵn + so sánh exact sau khi điền template
>    (chỉ chuẩn hóa CRLF → LF).
> 4. Validator: giá trị không hợp lệ phải ném `IllegalArgumentException`
>    (predicate `isValid()`/`isPassing()` vẫn trả boolean).
> 5. Ưu tiên Java trước, Python sau.

---

## 1. Mục tiêu Phase 1 Java — xong thì phải làm được gì?

Khi Phase 1 này xong và chạy đúng trên dòng lệnh, hệ thống phải làm được:

1. Admin định nghĩa một bài Java bằng **spec JSON** (không cần viết code
   test bằng Java): tên class, package bắt buộc, các check, điểm từng check,
   cờ visible/hidden.
2. Sinh viên nộp **1 file Java duy nhất** chứa 1 public class đúng tên,
   đúng package.
3. Hệ thống biên dịch bằng `javac`. Lỗi biên dịch → verdict `CE`, 0 điểm,
   kèm thông báo lỗi của `javac` (cắt ngắn), không chạy tiếp.
4. Hệ thống chạy **harness Reflection** trong JVM riêng để kiểm tra:
   field, constructor, method, getter/setter (kèm hành vi),
   validator (ném `IllegalArgumentException`), `toString` (template + exact),
   `Comparable` (dấu `compareTo` và thứ tự).
5. **Pretest** chỉ chạy check visible. **Chấm cuối** chạy toàn bộ check.
   Test ẩn không bao giờ được đưa vào lần chạy thử.
6. Kết quả trả về dạng JSON từng check: pass/fail, điểm, `expected`,
   `actual`, lỗi, thời gian chạy. Tổng điểm = tổng điểm các check pass.
7. Code sinh viên vòng lặp vô hạn, `System.exit()`, hay crash cũng
   **không làm sập runner**: timeout sẽ kill, JVM chết thì runner ghi
   nhận `RE`/`TLE` cho bài đó và tiếp tục được.

**Chưa làm trong Phase 1 này** (để phase sau, ghi rõ để khỏi hiểu nhầm):

- Giao diện web, gắn vào `app/main.py`, session, `release_id`, đồng hồ thi.
- Đa file, nhiều class, `Comparator` dạng class riêng (chỉ làm
  `Comparable` trong cùng class chính ở Phase 1).
- Mỗi check một JVM riêng, container Docker, judge worker tách biệt.
- Lưu lịch sử, giới hạn số lần pretest, hàng đợi chấm đồng thời.

---

## 2. Kiến trúc Phase 1 (bản dòng lệnh, trước khi tích hợp web)

```text
Trainer / Admin
  │  viết spec JSON (student-oop-spec.json)
  │  sinh viên nộp Student.java
  ▼
run_java.py  (Python stdlib, chạy bằng dòng lệnh)
  │  1. Đọc spec, lọc check theo mode (pretest: chỉ visible)
  │  2. Copy code vào thư mục tạm: temp/src/model/Student.java
  │     (đúng cấu trúc package đã chốt)
  │  3. javac -encoding UTF-8 -d temp/out temp/src/model/Student.java
  │     → lỗi: trả verdict CE, dừng
  │  4. java -Xmx256m -cp judge_out ReflectionJudge temp/out < spec-da-loc
  │     (spec qua stdin pipe, KHÔNG qua file)
  │  5. Đọc JSON kết quả từ stdout của judge, in ra, xóa thư mục tạm
  ▼
ReflectionJudge.java  (Java, không dùng thư viện ngoài)
  │  - Đọc spec từ stdin bằng bộ parser JSON tự viết
  │  - Load class sinh viên bằng URLClassLoader riêng,
  │    parent là platform classloader (không thấy class của judge)
  │  - Với mỗi check: Reflection kiểm tra / gọi thử, bắt lỗi riêng
  │    từng check để một check lỗi không sập cả bài
  │  - In JSON kết quả ra stdout, không in gì khác ra stdout
  ▼
Kết quả JSON: score, total_points, từng check (passed, points_earned,
expected, actual, error, time_ms)
```

Khi tích hợp vào web sau này, `run_java.py` sẽ được viết lại thành
`app/java_runner.py` với cùng các bước trên, chỉ khác là đầu vào lấy từ
form nộp bài và đầu ra ghi vào `data/code_submissions.json` + audit,
thay vì in ra terminal. `ReflectionJudge.java` giữ nguyên, chỉ cần
biên dịch sẵn một lần và để trong repo (ví dụ `judge/`).

---

## 3. Spec JSON — định dạng chính thức của Phase 1

### 3.1. Cấu trúc problem spec

```json
{
  "id": "student-oop",
  "title": "Lớp Student",
  "statement": "...mô tả đề đầy đủ cho sinh viên...",
  "language": "java",
  "problem_kind": "java_reflection",
  "target_class": "model.Student",
  "target_package": "model",
  "target_file": "Student.java",
  "time_limit_seconds": 5,
  "memory_limit_mb": 256,
  "max_output_bytes": 65536,
  "allow_pretest": true,
  "max_pretest_runs": 20,
  "show_final_score_immediately": false,
  "starter_code": "package model;\n\npublic class Student {\n    // TODO: ...\n}\n",
  "total_points": 100,
  "checks": [ "...xem 3.2..." ]
}
```

Quy tắc bắt buộc:

- `target_package` **không được để trống** trừ khi đề ghi rõ là dùng
  default package và admin chấp nhận rủi ro nhầm lẫn. Mặc định của
  Phase 1 là luôn có package, ví dụ `model`.
- `target_class` phải là tên đầy đủ: `package + "." + tên class`.
- `target_file` phải trùng tên public class + `.java`.
- `total_points` phải bằng tổng `points` của các check. Runner mẫu
  không tự sửa tổng này — admin phải tự kiểm tra khi viết spec.
  (Bản tích hợp web sau này nên tự kiểm tra và báo lỗi nếu lệch.)

### 3.2. Các loại check trong Phase 1

Mỗi check có chung các trường: `id` (duy nhất trong một spec),
`kind`, `points`, `is_visible`. Ngoài ra tùy kind sẽ có thêm trường riêng.

#### a) `field` — kiểm tra attribute

```json
{
  "id": "field-name", "kind": "field", "points": 10, "is_visible": true,
  "field_name": "name",
  "expected_type": "java.lang.String",
  "expected_modifiers": ["private"]
}
```

- Dùng `getDeclaredField` (không dùng `getField`, vì `getField` chỉ
  thấy field `public`).
- `expected_type` chấp nhận cả tên đầy đủ (`java.lang.String`) và tên
  ngắn (`String`, `int`, `double`). Với kiểu nguyên thủy phải ghi đúng
  (`int` khác `Integer`, `double` khác `Double` — judge so sánh chặt).
- `expected_modifiers` là danh sách phải có đủ, ví dụ `["private"]`,
  `["public", "static", "final"]`. Judge chỉ kiểm tra "có đủ các
  modifier này không", không phạt nếu có thêm modifier khác ngoài danh
  sách — trừ khi admin muốn chặt hơn và ghi rõ trong đề.

#### b) `constructor` — kiểm tra constructor

```json
{
  "id": "ctor", "kind": "constructor", "points": 10, "is_visible": true,
  "param_types": ["java.lang.String", "double"],
  "expected_modifiers": ["public"]
}
```

- Dùng `getDeclaredConstructor` với đúng danh sách kiểu tham số.
  Overload khác tham số sẽ không được tính là đúng, kể cả khi tên
  constructor giống nhau (với constructor thì tên luôn là tên class,
  nên phân biệt hoàn toàn bằng tham số).
- Check này chỉ kiểm tra **chữ ký**, chưa kiểm tra hành vi tạo object.
  Hành vi tạo object được kiểm tra gián tiếp qua các check `behavior`
  / `toString` / `comparable` dùng constructor đó để setup.

#### c) `method` — kiểm tra method (chữ ký)

```json
{
  "id": "method-getName", "kind": "method", "points": 5, "is_visible": true,
  "method_name": "getName",
  "param_types": [],
  "expected_return_type": "java.lang.String",
  "expected_modifiers": ["public"]
}
```

- Dùng `getDeclaredMethod` với đúng tên + đúng tham số. Overload sai
  tham số sẽ không được tính.
- Nếu `expected_return_type` để trống thì judge bỏ qua kiểm tra kiểu
  trả về (chỉ kiểm tra tồn tại + modifier). Khuyến nghị luôn ghi rõ.

#### d) `behavior` — kiểm tra hành vi chung (dùng cho getter/setter, validator, method khác)

```json
{
  "id": "behavior-set-get",
  "kind": "behavior", "points": 10, "is_visible": true,
  "setup": {
    "constructor_args": ["An", 8.5],
    "constructor_param_types": ["java.lang.String", "double"]
  },
  "invoke": {
    "method": "setGpa",
    "param_types": ["double"],
    "args": [9.0]
  },
  "expect_state": {"getGpa": 9.0}
}
```

Ba dạng kỳ vọng, **mỗi check chỉ dùng một dạng**:

| Dạng | Trường trong spec | Nghĩa |
| --- | --- | --- |
| Trả về giá trị | `"expect_return": <giá trị>` | Method phải trả về đúng giá trị đó (số thực so với sai số 1e-9 tương đối, các kiểu khác so exact) |
| Thay đổi trạng thái | `"expect_state": {"getGpa": 9.0}` hoặc `{"gpa": 9.0}` | Sau khi gọi method, đọc lại bằng getter (ưu tiên) hoặc field trực tiếp, phải bằng giá trị kỳ vọng |
| Ném exception | `"expect_exception": "java.lang.IllegalArgumentException"` | Method phải ném đúng loại exception đó. Judge "mở" `InvocationTargetException` ra để lấy exception gốc rồi mới so sánh |

Ví dụ validator (hidden trong spec mẫu):

```json
{
  "id": "validator-gpa-negative",
  "kind": "behavior", "points": 15, "is_visible": false,
  "setup": {
    "constructor_args": ["An", 8.5],
    "constructor_param_types": ["java.lang.String", "double"]
  },
  "invoke": {"method": "setGpa", "param_types": ["double"], "args": [-1]},
  "expect_exception": "java.lang.IllegalArgumentException"
}
```

Lưu ý về `constructor_param_types` và `param_types` trong `invoke`:

- **Nên luôn ghi rõ** để tránh nhầm overload. Ví dụ JSON `8` (số nguyên)
  và `8.0` (số thực) khác nhau, và judge chuyển đổi theo đúng kiểu
  tham số đã khai báo. Nếu không ghi `param_types`, judge sẽ thử các
  method/constructor có cùng số lượng tham số theo thứ tự Reflection
  trả về — thứ tự này không đảm bảo, dễ chấm sai oan với bài có overload.
- Trong spec mẫu đi kèm, mọi check `behavior` đều ghi rõ
  `constructor_param_types` và `param_types`.

#### e) `toString` — template + exact (theo quyết định đã chốt)

```json
{
  "id": "tostring", "kind": "toString", "points": 10, "is_visible": true,
  "setup": {
    "constructor_args": ["An", 8.5],
    "constructor_param_types": ["java.lang.String", "double"]
  },
  "expected_template": "Student{name='{name}', gpa={gpa}}"
}
```

Cách judge làm, từng bước:

1. Tạo object bằng setup như check `behavior`.
2. Điền template: placeholder `{name}` → giá trị field `name` của
   object đó (đọc bằng getter nếu có, nếu không đọc field trực tiếp
   bằng `setAccessible(true)`), `{gpa}` → giá trị field `gpa`
   (`String.valueOf(gpa)` — với `8.5` cho ra `"8.5"`, với `8.0` cho ra
   `"8.0"`).
3. So sánh chuỗi đã điền với `object.toString()` **một cách exact**,
   chỉ chuẩn hóa CRLF → LF trước khi so. Không trim, không bỏ khoảng
   trắng, không dùng `contains`.

Hệ quả cần ghi rõ trong đề cho sinh viên: thừa/thiếu một dấu cách,
dấu phẩy, dấu nháy đơn so với mẫu đều làm check này fail, dù logic
các phần khác đúng. Đây là lựa chọn có chủ đích của Trainer (chặt),
không phải lỗi của judge.

#### f) `comparable` — kiểm tra `Comparable` trong cùng class

```json
{
  "id": "comparable", "kind": "comparable", "points": 15, "is_visible": false,
  "constructor_param_types": ["java.lang.String", "double"],
  "cases": [
    {"a": ["An", 9.0], "b": ["Binh", 8.0], "expected_sign": -1},
    {"a": ["Binh", 8.0], "b": ["An", 9.0], "expected_sign": 1},
    {"a": ["An", 8.0], "b": ["Binh", 8.0], "expected_sign": -1},
    {"a": ["An", 8.0], "b": ["An", 8.0], "expected_sign": 0}
  ]
}
```

- Judge kiểm tra trước: class có `implements Comparable` không
  (`Comparable.class.isAssignableFrom(clazz)`). Không có → fail ngay.
- Với mỗi case: tạo `a`, `b` bằng constructor đã cho, gọi
  `a.compareTo(b)`, lấy dấu (`Integer.signum`) rồi so với
  `expected_sign` (`-1`, `0`, `1`). Chỉ cần một case sai dấu là cả
  check fail (không cho điểm từng phần trong một check).
- `Comparator` dạng class riêng **chưa làm trong Phase 1** (cần thêm
  một target class nữa trong spec). Nếu đề cần comparator riêng, có hai
  cách tạm thời trong Phase 1: (1) dùng `Comparable` trong class chính
  thay thế, hoặc (2) đợi Phase mở rộng. Đừng cố nhét comparator riêng
  vào spec Phase 1 này bằng cách hack tên class.

#### g) `implements` — kiểm tra interface (dùng khi cần, không bắt buộc trong spec mẫu)

```json
{
  "id": "implements-comparable", "kind": "implements", "points": 5,
  "is_visible": true, "expected_interface": "java.lang.Comparable"
}
```

Judge dùng `interfaceClass.isAssignableFrom(clazz)` nên tính cả
interface được kế thừa gián tiếp qua superclass, không chỉ khai báo
trực tiếp.

### 3.3. Spec mẫu hoàn chỉnh — bài `Student` (100 điểm)

File đầy đủ nằm ở `java-phase1-skeleton/student-oop-spec.json`.
Tóm tắt các check và điểm:

| Check | Kind | Visible? | Điểm | Ý nghĩa |
| --- | --- | --- | --- | --- |
| `field-name` | field | Có | 10 | Field `name` phải `private String` |
| `field-gpa` | field | Có | 10 | Field `gpa` phải `private double` |
| `ctor` | constructor | Có | 10 | Constructor `public Student(String, double)` |
| `method-getName` | method | Có | 5 | Method `public String getName()` |
| `method-setGpa` | method | Có | 5 | Method `public void setGpa(double)` |
| `behavior-set-get` | behavior | Có | 10 | `setGpa(9.0)` rồi `getGpa()` phải bằng 9.0 |
| `validator-gpa-negative` | behavior | **Không** | 15 | `setGpa(-1)` phải ném `IllegalArgumentException` |
| `behavior-isPassing-true` | behavior | Có | 5 | `Student("An", 8.5).isPassing()` phải `true` |
| `behavior-isPassing-false` | behavior | Có | 5 | `Student("Binh", 4.0).isPassing()` phải `false` |
| `tostring` | toString | Có | 10 | Template `Student{name='{name}', gpa={gpa}}`, exact |
| `comparable` | comparable | **Không** | 15 | `compareTo` theo gpa giảm dần, bằng nhau thì name tăng dần |
| **Tổng** |  |  | **100** |  |

Đề bài đầy đủ cho sinh viên (nằm trong trường `statement` của spec):

> Tạo class `Student` trong package `model` với: attribute \`private
> String name`&#32;và&#32;`private double gpa`; constructor&#32;`public
> Student(String name, double gpa)\`; getter/setter cho cả hai field;
> setter và constructor phải ném `IllegalArgumentException` khi
> `gpa < 0` hoặc `gpa > 10`, và khi `name` null hoặc rỗng; method
> `isPassing()` trả về `true` khi `gpa >= 5`; `toString()` phải trả về
> đúng mẫu `Student{name='<name>', gpa=<gpa>}`; `Student` phải
> implements `Comparable<Student>`, sắp xếp theo `gpa` giảm dần, nếu
> `gpa` bằng nhau thì theo `name` tăng dần.

---

## 4. ReflectionJudge — thiết kế chi tiết

File: `java-phase1-skeleton/ReflectionJudge.java` (một file duy nhất,
không package, không dùng thư viện ngoài).

### 4.1. Vào / ra

- **Tham số dòng lệnh:** `ReflectionJudge <thu-muc-out-cua-sinh-vien>`.
  Thiếu tham số → in `{"error": "..."}` ra stdout và thoát code 2.
- **Input:** toàn bộ spec đã lọc qua **stdin** (UTF-8). Judge không đọc
  spec từ file, để code sinh viên không có file spec nào trên đĩa để
  đọc trộm trong lần chạy đó.
- **Output:** đúng một JSON object ra **stdout**, không in thêm gì khác
  ra stdout (log debug nếu có phải ra stderr, và bản khung này không
  in debug ra đâu cả). Dạng:

```json
{
  "target_class": "model.Student",
  "score": 100,
  "total_points": 100,
  "checks": [
    {
      "id": "field-name", "kind": "field", "passed": true,
      "points": 10, "points_earned": 10,
      "expected": "private java.lang.String name",
      "actual": "private java.lang.String name",
      "error": null, "time_ms": 3
    }
  ]
}
```

- **Thoát code:** `0` nếu judge chạy xong (kể cả khi sinh viên trượt
  hết). Code khác `0` chỉ khi chính judge lỗi (spec JSON sai, thiếu
  tham số, không đọc được stdin). Phân biệt này quan trọng: runner
  không được hiểu "sinh viên trượt" thành "hệ thống lỗi".

### 4.2. Load class sinh viên — cách ly classloader

```java
URL[] urls = new URL[]{ new File(studentOutDir).toURI().toURL() };
URLClassLoader loader = new URLClassLoader(urls, ClassLoader.getPlatformClassLoader());
Class<?> clazz = Class.forName(targetClassName, true, loader);
```

- Parent là **platform classloader**, không phải app classloader, nên
  code sinh viên load bằng loader này **không thấy class của judge**
  (judge được load bằng app classloader). Đây là một lớp cách ly rẻ
  tiền nhưng có thật, khác với việc cứ `Class.forName` trực tiếp trong
  cùng JVM với judge.
- Nếu load class thất bại (sai package, sai tên class, static
  initializer ném exception...), **mọi check đều fail** với lỗi
  `Class not found` / lỗi gốc, chứ judge không crash. Đây là hành vi
  đúng: sai package theo quyết định đã chốt thì phải fail, không phải
  lỗi hệ thống.
- Lưu ý: static initializer của sinh viên **vẫn chạy** lúc load class,
  và nó là code không tin cậy. Vì vậy load class cũng phải nằm trong
  JVM riêng có timeout của runner — tuyệt đối không load class sinh
  viên trong process của server web sau này.

### 4.3. Từng check chạy độc lập

- Mỗi check được bọc trong `try/catch` riêng. Một check ném exception
  ngoài dự kiến (ví dụ `NullPointerException` trong getter của sinh
  viên) thì check đó fail với `error` ghi rõ loại exception, các check
  khác vẫn chạy tiếp.
- Thời gian từng check được đo bằng `System.nanoTime()` và ghi vào
  `time_ms` — để admin phát hiện check nào chậm bất thường.
- Một check chỉ có pass/fail, không có điểm từng phần bên trong check.
  Muốn cho điểm từng phần thì tách check nhỏ ra (ví dụ tách
  `toString` thành 2 check nếu cần, nhưng Phase 1 giữ nguyên 1 check
  cho `toString` như spec mẫu).

### 4.4. Các cạm bẫy Reflection đã xử lý trong code khung

| Cạm bẫy | Cách xử lý trong `ReflectionJudge.java` |
| --- | --- |
| `getField` chỉ thấy field `public` | Dùng `getDeclaredField` / `getDeclaredMethod` / `getDeclaredConstructor` cho mọi kiểm tra cấu trúc |
| Overload cùng tên khác tham số | Match theo tên **+** danh sách kiểu tham số chính xác, không match theo tên riêng |
| Primitive vs Wrapper (`int` vs `Integer`) | So sánh chặt theo `Class` thật. `int` khác `Integer` là fail, đúng như đặc tả kiểu Java |
| Generic bị xóa kiểu | Phase 1 không chấm generic phức tạp. Nếu cần, dùng `getGenericType()` ở phase sau, không dùng `getType()` để đoán generic |
| Đọc field `private` | `field.setAccessible(true)` trước khi đọc. Trong default package / unnamed module thì được; code có `module-info.java` sẽ bị hạn chế — Phase 1 không hỗ trợ `module-info.java` |
| Exception bị bọc trong `InvocationTargetException` | Judge lấy `getCause()` ra rồi mới so sánh loại exception với `expect_exception` |

| So sánh số thực | Sai số \`1e-9 \* max(1, | expected | )`&#32;cho&#32;`double`/`float\`, số nguyên so exact |

| `toString` của `double` | Dùng `String.valueOf(double)` cả hai phía (điền template và `toString()` của sinh viên đều dùng cùng quy tắc của Java), nên `8.0` không bị biến thành `8` |
| `System.exit()` trong code sinh viên | Judge chết theo, runner phát hiện stdout rỗng và ghi `RE`, không sập runner. Xem mục 5 |
| Static state nhiễm giữa các check | Mỗi check `behavior`/`toString`/`comparable` tạo object mới hoàn toàn. Nếu bài dùng static field để đếm và đề không cho phép, đó là lỗi thiết kế của bài, không phải lỗi judge — phase sau có thể thêm chế độ mỗi check một JVM |

### 4.5. Parser JSON tự viết — vì sao không dùng thư viện?

Java stdlib **không có** parser JSON. Repo gốc theo triết lý "không thêm
dependency nếu không cần", nên judge tự viết một parser JSON tối thiểu
(class `JsonParser` trong cùng file): object, array, string (kèm escape
`\n`, `\"`, `\uXXXX`), number (phân biệt số nguyên → `Long`, số thực
→ `Double`), boolean, null. Đủ cho spec Phase 1, không cần Jackson /
Gson / org.json. Khi spec phức tạp hơn (ví dụ thêm kiểu dữ liệu lồng
nhau), parser này vẫn dùng được vì nó là parser JSON tổng quát, không
phải parser riêng cho từng trường.

Tương tự, xuất JSON cũng tự viết hàm escape (`Json.escape`) và
`Json.stringify`, không dùng thư viện.

---

## 5. Runner Python mẫu — `run_java.py`

File: `java-phase1-skeleton/run_java.py` (chỉ dùng Python stdlib).

### 5.1. Các bước runner làm (đúng thứ tự)

1. Đọc problem spec JSON, tính `total_points` từ các check.
2. Lọc check theo mode:

- `pretest`: chỉ giữ check `is_visible=true`.
- `final`: giữ toàn bộ.

3. Đọc code sinh viên, kiểm tra độ dài tối đa (mặc định 200.000 ký tự
   trong bản khung — bản tích hợp web nên lấy giới hạn này từ cấu hình
   chung của server, ví dụ cùng mức với giới hạn upload hiện có).
4. Cảnh báo sớm nếu code không khai báo đúng package (in ra stderr,
   không dừng — vì judge load class thất bại sẽ là kết quả chấm đúng,
   không phải lỗi hệ thống).
5. Tạo thư mục tạm `tempfile.mkdtemp(prefix="java-judge-")`, copy code
   vào `temp/src/<package-path>/Student.java` (ví dụ
   `temp/src/model/Student.java`).
6. Biên dịch:
   `javac -encoding UTF-8 -d temp/out temp/src/model/Student.java`
   với timeout 30 giây. Lỗi → in JSON \`{"verdict": "CE", "score": 0,
   "compiler\_output": "...(cắt 2000 ký tự)..."}\` và dừng.
7. Chạy judge:
   `java -Xmx256m -cp judge_out ReflectionJudge temp/out`
   với spec đã lọc qua stdin, timeout tổng = \`max(time\_limit, 5) \*
   số check`. Hết timeout →&#32;`verdict: TLE\`, điểm 0.
8. Nếu judge không in gì ra stdout (JVM chết giữa chừng, ví dụ
   `System.exit()` trong code sinh viên) → `verdict: RE`, điểm 0,
   kèm `judge_returncode` và stderr (cắt ngắn) để admin đối chiếu.
   Runner **không crash** trong trường hợp này.
9. Nếu stdout không phải JSON hợp lệ → `verdict: RE` với lý do, kèm
   stdout đã cắt ngắn.
10. In kết quả JSON của judge ra stdout (kèm thêm trường `mode`),
    rồi **luôn xóa thư mục tạm** trong khối `finally`, trừ khi chạy
    với `--keep-temp` để debug.

### 5.2. Các lệnh chạy thử (Trainer chạy trên máy có JDK)

Xem đầy đủ trong `java-phase1-skeleton/README.md`. Tóm tắt:

```bash
# 1. Biên dịch judge một lần
javac -d judge_out ReflectionJudge.java

# 2. Pretest mẫu đúng (chỉ check visible)
python run_java.py --spec student-oop-spec.json \
    --student samples/correct/Student.java \
    --judge-dir judge_out --mode pretest

# 3. Chấm cuối mẫu đúng (kỳ vọng 100/100)
python run_java.py --spec student-oop-spec.json \
    --student samples/correct/Student.java \
    --judge-dir judge_out --mode final

# 4. Chấm cuối các mẫu sai (kỳ vọng trong README)
python run_java.py --spec student-oop-spec.json \
    --student samples/wrong-modifier/Student.java \
    --judge-dir judge_out --mode final
python run_java.py --spec student-oop-spec.json \
    --student samples/wrong-tostring/Student.java \
    --judge-dir judge_out --mode final
python run_java.py --spec student-oop-spec.json \
    --student samples/validator-fail/Student.java \
    --judge-dir judge_out --mode final
python run_java.py --spec student-oop-spec.json \
    --student samples/compile-error/Student.java \
    --judge-dir judge_out --mode final
```

### 5.3. Giới hạn của runner mẫu (đừng coi là bản production)

- Timeout tính cho **toàn bộ lần chạy judge**, chưa phải timeout từng
  check. Một check vòng lặp vô hạn sẽ làm các check sau trong cùng lần
  chạy không được chấm. Bản tích hợp thật nên cân nhắc: hoặc timeout
  từng check bằng cách chạy judge nhiều lần, hoặc chế độ mỗi check một
  JVM cho bài quan trọng.
- Chưa giới hạn đồng thời, chưa có hàng đợi, chưa lưu lịch sử, chưa
  kiểm tra số lần pretest — tất cả những thứ đó thuộc về tầng web
  (bước tích hợp), không thuộc về runner dòng lệnh này.
- Chưa có container. Runner mẫu chạy judge trực tiếp trên máy giảng
  viên — chấp nhận được cho LAN có giám sát theo kế hoạch, chưa đủ
  cho thi online với người lạ.

---

## 6. Checklist kiểm thử Phase 1 — Trainer chạy xong phải tick hết

### 6.1. Chức năng (bắt buộc)

- [ ] Mẫu `correct` chấm cuối được **100/100**, mọi check pass.
- [ ] Mẫu `correct` chạy pretest **không chứa** check `validator-gpa-negative`
      và `comparable` (hidden) trong kết quả.
- [ ] Mẫu `wrong-modifier` chấm cuối được **90/100**, chỉ `field-name` fail,
      `actual` ghi rõ field là `public`.
- [ ] Mẫu `wrong-tostring` chấm cuối được **90/100**, chỉ `tostring` fail.
- [ ] Mẫu `validator-fail` chấm cuối được **85/100**, chỉ
      `validator-gpa-negative` fail (không ném exception).
- [ ] Mẫu `compile-error` được verdict **CE**, 0 điểm, kèm thông báo
      lỗi `javac`, judge không chạy.
- [ ] Đổi package trong mẫu đúng thành `package other;` (hoặc xóa dòng
      package) rồi chấm: mọi check phải fail vì không load được
      `model.Student` — đây là hành vi đúng theo quyết định package
      bắt buộc, không phải lỗi hệ thống.
- [ ] Đổi tên file mẫu đúng thành `Foo.java` (nhưng class vẫn là
      `Student`) rồi chạy runner với file đó: runner vẫn copy thành
      `Student.java` trong thư mục tạm nên vẫn chấm được — kiểm tra
      này để chắc runner không phụ thuộc tên file gốc của sinh viên.
      (Bản tích hợp web sau này cũng phải làm vậy: tên file lưu trữ
      lấy từ `target_file` trong spec, không lấy từ tên file upload.)

### 6.2. An toàn / chống phá (bắt buộc trước khi cho lớp thật dùng)

- [ ] Code có vòng lặp vô hạn trong getter: runner phải trả `TLE`
      (hoặc check đó fail) sau timeout, runner không treo, terminal
      vẫn dùng được sau đó.
- [ ] Code gọi `System.exit(0)` trong constructor: runner phải trả
      `RE` với lý do JVM không in output, không crash runner, không
      làm các lần chấm sau bị ảnh hưởng (chạy lại mẫu đúng ngay sau
      đó vẫn được 100/100).
- [ ] Code đọc file `student-oop-spec.json` trong constructor (ví dụ
      `new FileReader("student-oop-spec.json")`): phải \*\*không đọc
      được đáp án từ file đó trong lần chạy judge\*\*, vì spec chỉ được
      đưa qua stdin và thư mục làm việc của judge không phải thư mục
      chứa spec. Nếu code đọc được file khác trên máy (do chạy cùng
      user) thì ghi nhận đây là giới hạn đã biết của Phase 1 không
      container, không được quảng cáo là đã chặn triệt để.
- [ ] Code in ra 1 triệu dòng trong `toString()`: output phải bị cắt
      ở mức runner quy định, không làm đầy RAM.

### 6.3. Đáp án mẫu (bắt buộc trước khi phát đề thật)

- [ ] Lấy chính code mẫu `correct` làm đáp án mẫu, chạy qua spec đầy
      đủ, phải được 100/100. Nếu đáp án mẫu mà trượt check nào thì
      spec đó sai, phải sửa spec trước khi phát đề — không được sửa
      điểm tay sau khi thi.

---

## 7. Bước tích hợp vào server thật (sau khi khung dòng lệnh chạy đúng)

Thứ tự làm, không làm ngược:

1. **Copy khung vào repo, chưa nối web:**

- `judge/ReflectionJudge.java` vào repo, biên dịch sẵn (hoặc biên
     dịch lúc server khởi động nếu `judge_out/` chưa có, và báo lỗi
     rõ nếu thiếu JDK).
- `app/java_runner.py` viết lại từ `run_java.py`, thay đầu vào
     dòng lệnh bằng tham số hàm (`spec`, `code`, `mode`), thay in
     JSON ra terminal bằng trả về dict cho `main.py`.
- `app/problems.py` (mới): lưu/đọc spec Java vào `data/problems.json`,
     validate spec (id check không trùng, `total_points` bằng tổng
     điểm, `target_package` bắt buộc, kiểu dữ liệu hợp lệ).

2. **Nối route web, dùng lại luồng cũ:**

- Dùng lại route `/api/student/code/run` (pretest) và
     `/api/student/code/submit` (chấm cuối) đã thiết kế ở kế hoạch
     tổng, chỉ rẽ nhánh theo `problem_kind == "java_reflection"`.
- Pretest: server lọc check visible **trước khi** gọi runner,
     giống runner mẫu. Tuyệt đối không đưa spec đầy đủ xuống frontend.
- Chấm cuối: ghi vào `data/code_submissions.json` (code snapshot +
     kết quả từng check + điểm + `release_id`), đánh dấu assignment
     `submitted` như nộp ZIP, ghi audit `code.submitted` /
     `code.graded`.
- Hiển thị cho sinh viên: nếu `show_final_score_immediately=false`
     thì chỉ hiện "Đã nộp", điểm và chi tiết check hidden chỉ admin
     thấy; nếu `true` thì hiện điểm + check visible.

3. **Giao diện tối thiểu:**

- Admin: form tạo spec theo từng loại check (dropdown kind, ô nhập
     tên field/method, kiểu, modifier, template `toString`, case
     `compareTo`), nút "Chạy đáp án mẫu" để validate spec trước khi
     phát đề, nút "Chấm lại" (regrade) khi sửa spec.
- Sinh viên: editor 1 file (textarea + xử lý Tab ở Phase 1, chưa cần
     highlight), tiêu đề file hiển thị `Student.java`, nhắc rõ
     "tên public class phải trùng tên file, package phải đúng theo đề",
     nút "Chạy thử" (chỉ hiện khi `allow_pretest=true`), nút "Nộp bài"
     có xác nhận.

4. **Kiểm thử tích hợp trước khi cho lớp thật dùng:**

- Chạy checklist mục 6 trên bản web (không chỉ bản dòng lệnh).
- Thử một ca thi thật nhỏ: 2–3 sinh viên test, 1 admin, cùng bấm
     pretest/nộp gần như cùng lúc, kiểm tra server không nghẽn và
     điểm không bị lẫn giữa các sinh viên (mỗi lần chấm một thư mục
     tạm riêng, `release_id` đúng).

5. **Sau Phase 1 Java mới làm Python:** dùng lại `run_java.py` →
   `app/java_runner.py` làm mẫu cho `app/code_runner.py` của Python
   (temp dir riêng, timeout, cắt output, lọc visible/hidden, audit),
   chỉ thay `javac`/`java` bằng `python` và thay check Reflection bằng
   check stdin/stdout.

---

## 8. Rủi ro còn tồn tại trong Phase 1 — phải ghi rõ cho giảng viên

1. **Chưa chặn triệt để đọc file / mạng:** judge chạy cùng user với
   server, không có container. Sinh viên tinh vi vẫn có thể đọc file
   mà user đó có quyền đọc, hoặc gọi mạng, nếu biết đường dẫn. Phase 1
   chỉ phù hợp cho **phòng học LAN có giảng viên giám sát**, không phù
   hợp cho thi online với người lạ.
2. **Timeout toàn cục, chưa phải từng check:** một check vòng lặp vô
   hạn sẽ làm mất các check sau trong cùng lần chạy. Điểm của bài đó
   sẽ thấp hơn thực tế (vì các check sau không được chấm), nhưng
   không làm sập server — đây là trade-off đã chấp nhận ở Phase 1.
3. **toString exact rất chặt:** sinh viên làm đúng logic nhưng sai một
   dấu cách trong `toString` vẫn mất trọn điểm check đó. Giảng viên
   phải ghi mẫu `toString` rõ ràng trong đề và cho sinh viên chạy thử
   với check `tostring` visible trước khi thi thật (nếu đề cho phép
   pretest).
4. **JDK là điều kiện tiên quyết:** máy giảng viên không có JDK 17+
   thì tính năng Java không chạy được, và lỗi phải hiện rõ ngay lúc
   khởi động server ("thiếu JDK"), không được để đến lúc sinh viên nộp
   bài mới báo lỗi chung chung.
5. **Code khung chưa được chạy thử bằng Java ở đây:** mọi kết quả kỳ
   vọng trong mục 6 đều là kỳ vọng từ thiết kế, chưa phải kết quả chạy
   thật. Trainer chạy thử xong và tick hết checklist mục 6 thì Phase 1
   mới được coi là xong bước khung.

   