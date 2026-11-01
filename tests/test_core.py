import io
import os
import unittest
import zipfile
from types import SimpleNamespace
from app.accounts import parse_accounts
from app.http import inline_filename_header
from app.security import hash_password, verify_password, check_origin, SecurityError
from app.submissions import validate_zip

class CoreTests(unittest.TestCase):
    def test_account_parser_trims_spaces_and_flags_duplicates(self):
        rows, errors = parse_accounts(" 21010001 | 01/02/2003 | Nguyen Van A  \n21010001|01/02/2003|Duplicate\n\n# comment")
        self.assertEqual(rows, [{"student_id": "21010001", "dob": "01/02/2003", "full_name": "Nguyen Van A"}])
        self.assertEqual(len(errors), 1)
        self.assertIn("lặp", errors[0]["message"])

    def test_password_hash(self):
        encoded = hash_password("01/02/2003")
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertTrue(verify_password("01/02/2003", encoded))
        self.assertFalse(verify_password("02/01/2003", encoded))


    def test_origin_accepts_same_origin_on_custom_port(self):
        request = SimpleNamespace(headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})
        check_origin(request)

    def test_origin_accepts_host_case_normalization(self):
        request = SimpleNamespace(headers={"Origin": "http://LOCALHOST:8080", "Host": "localhost:8080"})
        check_origin(request)

    def test_origin_rejects_different_host(self):
        request = SimpleNamespace(headers={"Origin": "http://evil.example:8080", "Host": "localhost:8080"})
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_origin_rejects_different_port(self):
        request = SimpleNamespace(headers={"Origin": "http://localhost:8000", "Host": "localhost:8080"})
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_origin_accepts_ipv6_normalization(self):
        request = SimpleNamespace(headers={"Origin": "http://[0:0:0:0:0:0:0:1]:8080", "Host": "[::1]:8080"})
        check_origin(request)

    def test_origin_rejects_different_scheme_when_request_scheme_is_known(self):
        request = SimpleNamespace(
            headers={"Origin": "https://localhost:8080", "Host": "localhost:8080"},
            scheme="http",
        )
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_origin_accepts_trailing_dot_in_host(self):
        request = SimpleNamespace(headers={"Origin": "http://localhost:8080", "Host": "localhost.:8080"})
        check_origin(request)

    def test_origin_error_identifies_received_values(self):
        request = SimpleNamespace(headers={"Origin": "null", "Host": "localhost:8080"})
        with self.assertRaisesRegex(SecurityError, r"Origin=null, Host=localhost:8080"):
            check_origin(request)

    def test_origin_null_accepts_verified_loopback_browser_request(self):
        request = SimpleNamespace(
            headers={
                "Origin": "null",
                "Host": "127.0.0.1:8080",
                "Sec-Fetch-Site": "same-origin",
            }
        )
        check_origin(request)

    def test_origin_null_rejects_file_like_request(self):
        request = SimpleNamespace(
            headers={"Origin": "null", "Host": "127.0.0.1:8080", "Sec-Fetch-Site": "none"}
        )
        with self.assertRaises(SecurityError):
            check_origin(request)

    def test_valid_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Main.java", "class Main {}")
        self.assertEqual(validate_zip(buffer.getvalue()), (True, "ZIP hợp lệ."))

    def test_invalid_zip(self):
        valid, message = validate_zip(b"not a zip")
        self.assertFalse(valid)
        self.assertIn("chữ ký ZIP", message)

    def test_inline_exam_filename_header_is_ascii_safe(self):
        header = inline_filename_header("Đề thi cuối kỳ.pdf")
        self.assertTrue(header.startswith('inline; filename="'))
        self.assertIn("filename*=UTF-8''", header)
        self.assertNotRegex(header, r"[\r\n]")

if __name__ == "__main__":
    unittest.main()
