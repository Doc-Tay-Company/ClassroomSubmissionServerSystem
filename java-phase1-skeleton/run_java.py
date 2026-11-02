#!/usr/bin/env python3
"""Runner mau Phase 1: cham bai Java bang Reflection (chi dung stdlib Python).

Day la ban khung de Trainer chay thu tren may co JDK, CHUA phai module
app/java_runner.py hoan chinh tich hop vao server. Luong chay giong he
thong that, chi khac la chay bang dong lenh thay vi qua web:

  1. Doc problem spec (JSON).
  2. Neu mode=pretest: chi giu check is_visible=true.
     Neu mode=final: giu toan bo check.
     => Test an KHONG BAO GIO duoc dua vao JVM chay thu.
  3. Copy code sinh vien vao thu muc tam rieng, dung cau truc package:
     temp/src/<package-path>/Student.java
  4. Bien dich: javac -encoding UTF-8 -d temp/out temp/src/.../Student.java
     Loi bien dich => verdict CE, diem 0, khong chay judge.
  5. Chay judge: java -Xmx256m -cp judge_out ReflectionJudge temp/out
     voi spec da loc qua stdin (pipe, khong qua file).
     Timeout: mac dinh theo spec time_limit_seconds cho TOAN BO lan chay
     judge (ban tich hop that se co them timeout tung check / tung JVM).
  6. In ket qua JSON ra stdout, xoa thu muc tam (tru khi --keep-temp).

Cach dung:
  # Buoc 1: bien dich judge mot lan
  javac -d judge_out ReflectionJudge.java

  # Buoc 2: chay thu (pretest, chi check visible)
  python run_java.py --spec student-oop-spec.json \
      --student samples/correct/Student.java \
      --judge-dir judge_out --mode pretest

  # Buoc 3: cham cuoi (toan bo check, ke ca hidden)
  python run_java.py --spec student-oop-spec.json \
      --student samples/correct/Student.java \
      --judge-dir judge_out --mode final

  # Thu cac mau sai:
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

Yeu cau: JDK 17+ (java, javac trong PATH). Khong can cai them thu vien Python.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_COMPILER_OUTPUT = 2000
MAX_JUDGE_OUTPUT = 1_000_000


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [output truncated, total {len(text)} chars]"


def main() -> int:
    ap = argparse.ArgumentParser(description="Java Reflection runner (Phase 1 skeleton)")
    ap.add_argument("--spec", required=True, help="Problem spec JSON, e.g. student-oop-spec.json")
    ap.add_argument("--student", required=True, help="Student source file, e.g. samples/correct/Student.java")
    ap.add_argument("--judge-dir", required=True, help="Dir containing compiled ReflectionJudge.class")
    ap.add_argument("--mode", choices=["pretest", "final"], default="final",
                    help="pretest: only visible checks; final: all checks")
    ap.add_argument("--timeout", type=int, default=0,
                    help="Overall judge timeout in seconds (0 = use spec time_limit_seconds, default 5s if missing)")
    ap.add_argument("--keep-temp", action="store_true", help="Keep temp dir for debugging (prints its path)")
    args = ap.parse_args()

    spec_path = Path(args.spec)
    student_path = Path(args.student)
    judge_dir = Path(args.judge_dir)
    if not spec_path.is_file():
        print(json.dumps({"error": f"spec not found: {spec_path}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    if not student_path.is_file():
        print(json.dumps({"error": f"student file not found: {student_path}"}, ensure_ascii=False), file=sys.stderr)
        return 2
    if not (judge_dir / "ReflectionJudge.class").is_file():
        print(json.dumps({"error": f"ReflectionJudge.class not found in {judge_dir}. Run: javac -d {judge_dir} ReflectionJudge.java first."}, ensure_ascii=False), file=sys.stderr)
        return 2

    with spec_path.open(encoding="utf-8") as f:
        spec = json.load(f)

    target_class = spec.get("target_class", "")
    target_package = spec.get("target_package", "")
    target_file = spec.get("target_file", "") or (target_class.rsplit(".", 1)[-1] + ".java")
    checks = spec.get("checks", [])
    total_points = sum(int(c.get("points", 0)) for c in checks)

    if args.mode == "pretest":
        filtered_checks = [c for c in checks if c.get("is_visible", False)]
    else:
        filtered_checks = list(checks)

    judge_spec = {"target_class": target_class, "checks": filtered_checks}
    judge_input = json.dumps(judge_spec, ensure_ascii=False)

    code = student_path.read_text(encoding="utf-8", errors="replace")
    if len(code) > 200_000:
        print(json.dumps({"verdict": "REJECTED", "error": "source too large (max 200000 chars)"}, ensure_ascii=False))
        return 0

    # Kiem tra package khai bao (canh bao som, khong thay cho viec judge load class).
    # Quy tac da chot: package bat buoc theo de. Neu code khong khai bao dung
    # package thi judge se khong load duoc model.Student => cac check fail,
    # day la hanh vi dung, khong phai loi he thong.
    if target_package:
        m = re.search(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", code, re.MULTILINE)
        declared = m.group(1) if m else None
        if declared != target_package:
            print(f"# WARNING: declared package is {declared!r}, expected {target_package!r}. "
                  f"Judge will likely fail to load {target_class}.",
                  file=sys.stderr)

    timeout = args.timeout or int(spec.get("time_limit_seconds", 5) or 5)
    # Timeout tong cho ca lan chay judge: nhan voi so check de tranh truong hop
    # bai dung nhung nhieu check bi kill oan. Ban tich hop that se tinh ky hon
    # (timeout tung check hoac tung JVM), day chi la ban khung chay thu.
    overall_timeout = max(timeout, 5) * max(1, len(filtered_checks))

    tmp = Path(tempfile.mkdtemp(prefix="java-judge-"))
    try:
        src_dir = tmp / "src"
        if target_package:
            src_dir = src_dir.joinpath(*target_package.split("."))
        src_dir.mkdir(parents=True, exist_ok=True)
        src_file = src_dir / target_file
        src_file.write_text(code, encoding="utf-8")

        out_dir = tmp / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Buoc 1: javac
        try:
            comp = subprocess.run(
                ["javac", "-encoding", "UTF-8", "-d", str(out_dir), str(src_file)],
                capture_output=True, text=True, timeout=30,
            )
        except FileNotFoundError:
            print(json.dumps({"error": "javac not found. Install JDK 17+ and put javac in PATH."}, ensure_ascii=False))
            return 0
        except subprocess.TimeoutExpired:
            print(json.dumps({"verdict": "CE", "score": 0, "total_points": total_points,
                              "error": "compilation timed out"}, ensure_ascii=False))
            return 0
        if comp.returncode != 0:
            print(json.dumps({
                "verdict": "CE",
                "score": 0,
                "total_points": total_points,
                "compiler_output": truncate((comp.stdout or "") + (comp.stderr or ""), MAX_COMPILER_OUTPUT),
                "checks": [],
            }, ensure_ascii=False, indent=2))
            return 0

        # Buoc 2: java ReflectionJudge
        try:
            run = subprocess.run(
                ["java", "-Xmx256m", "-cp", str(judge_dir), "ReflectionJudge", str(out_dir)],
                input=judge_input, capture_output=True, text=True, timeout=overall_timeout,
            )
        except FileNotFoundError:
            print(json.dumps({"error": "java not found. Install JDK 17+ and put java in PATH."}, ensure_ascii=False))
            return 0
        except subprocess.TimeoutExpired:
            print(json.dumps({
                "verdict": "TLE",
                "score": 0,
                "total_points": total_points,
                "error": f"judge timed out after {overall_timeout}s (possible infinite loop)",
                "checks": [],
            }, ensure_ascii=False, indent=2))
            return 0

        stdout = (run.stdout or "")[:MAX_JUDGE_OUTPUT]
        if not stdout.strip():
            # JVM chet giua chung (vi du: System.exit trong code sinh vien,
            # hoac judge crash). Day KHONG phai la pass, cung khong lam sap runner.
            print(json.dumps({
                "verdict": "RE",
                "score": 0,
                "total_points": total_points,
                "error": "judge produced no output (JVM may have exited early, e.g. System.exit in student code)",
                "judge_stderr": truncate(run.stderr or "", MAX_COMPILER_OUTPUT),
                "judge_returncode": run.returncode,
                "checks": [],
            }, ensure_ascii=False, indent=2))
            return 0
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as e:
            print(json.dumps({
                "verdict": "RE",
                "score": 0,
                "total_points": total_points,
                "error": f"judge output is not valid JSON: {e}",
                "judge_stdout": truncate(stdout, MAX_COMPILER_OUTPUT),
            }, ensure_ascii=False, indent=2))
            return 0

        result["mode"] = args.mode
        # Diem trong ket qua judge da tinh theo check duoc dua vao (pretest chi
        # tinh tren check visible). Ban tich hop that phai ghi ro dieu nay khi
        # hien thi cho sinh vien, tranh hieu nham pretest 100% la diem cuoi.
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        if args.keep_temp:
            print(f"# temp kept at: {tmp}", file=sys.stderr)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
