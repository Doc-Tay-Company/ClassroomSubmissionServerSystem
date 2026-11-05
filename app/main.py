"""Classroom Submission Server built on Python's standard-library HTTP server.
Jinja2 is used only to render the existing HTML templates; no FastAPI, Pydantic,
Uvicorn, Starlette, or multipart package is required.
"""
from __future__ import annotations
import hashlib
import html
import json
import mimetypes
import os
import secrets
import socket
import ssl
import threading
import time
import traceback
import urllib.parse
import zipfile
from datetime import datetime, timezone, timedelta
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape
from .config import BASE_DIR, DATA_DIR, LOG_DIR, EXAM_DIR, UPLOAD_DIR, STATIC_DIR, TEMPLATE_DIR, HOST, PORT, SESSION_COOKIE, MAX_REQUEST_SIZE

# Override OS-provided (e.g. Windows registry) types so scripts/styles pass nosniff checks.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
from .accounts import parse_accounts
from .http import inline_filename_header
from .storage import initialize, read_json, write_json, audit, utc_now
from .security import hash_password, verify_password, new_session, get_session, require_user, client_ip, login_allowed, record_login_failure, clear_login_failures, logout_session, SecurityError
from .exams import list_exam_files, distribute_exams, start_exam, start_exam_session, end_exam_session, remaining_seconds
from . import general_exams
from .general_exams import ExamError
from .submissions import accept_submission
from .questions import (
    QuestionError,
    archive_question,
    create_question,
    delete_question,
    duplicate_question,
    get_question,
    list_questions,
    update_question,
)
from .code_exams import (
    CodeExamError,
    create_code_exam,
    get_student_code_exam,
    get_student_submission,
    get_admin_code_results,
    list_code_exams,
    publish_question,
    validate_question_sample,
    regrade_submission,
    run_pretest,
    submit_code,
    transition_code_exam,
)
from .java_runner import JDKConfigurationError, JDKNotFoundError, verify_jdk_configuration

initialize()
TEMPLATES = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html", "xml"]))

class RequestData:
    def __init__(self, handler, form=None, files=None, json_body=None):
        self.headers = handler.headers
        self.cookies = handler.cookies
        self.client = SimpleNamespace(host=handler.client_address[0])
        self.form = form or {}
        self.files = files or {}
        self.json_body = json_body
        self.path = urllib.parse.urlsplit(handler.path).path
        self.query = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
        self.method = handler.command
        self.scheme = "https" if os.getenv("CSS_TLS_CERT") and os.getenv("CSS_TLS_KEY") else "http"

class ClientError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail); self.status=status; self.detail=detail


def current_exam_for(student_id: str):
    return read_json("assignments.json").get(student_id)

def monitoring_snapshot() -> dict:
    students, sessions = read_json("students.json"), read_json("sessions.json")
    assignments, submissions = read_json("assignments.json"), read_json("submissions.json")
    code_submissions = read_json("code_submissions.json")
    latest = {}; now = datetime.now(timezone.utc)
    for token, sess in sessions.items():
        if sess.get("role") != "student": continue
        sid = sess.get("user_id")
        if sid not in latest or sess.get("last_seen", "") > latest[sid].get("last_seen", ""):
            latest[sid] = {**sess, "session_token": token}
    result=[]
    for sid, student in students.items():
        sess=latest.get(sid); assignment=assignments.get(sid, {}); online=False
        if sess and sess.get("last_seen"):
            try: online=(now-datetime.fromisoformat(sess["last_seen"])).total_seconds() <= 45
            except (ValueError, TypeError): pass
        records=submissions.get(sid, [])
        code_records = [
            item
            for item in code_submissions.get(sid, [])
            if item.get("release_id") == assignment.get("release_id")
        ]
        telemetry=sess.get("telemetry",{}) if sess else {}
        alerts=[]
        if telemetry.get("visibility") == "hidden": alerts.append("tab_hidden")
        if telemetry.get("focused") is False: alerts.append("window_unfocused")
        if int(telemetry.get("tab_count",1) or 1)>1: alerts.append("multiple_tabs")
        latest_code = code_records[-1] if code_records else None
        code_summary = (
            {
                key: latest_code.get(key)
                for key in (
                    "exam_id",
                    "question_id",
                    "status",
                    "submitted_at",
                    "graded_at",
                    "verdict",
                    "score",
                    "total_points",
                    "exam_score",
                    "exam_total_points",
                )
                if key in latest_code
            }
            if latest_code
            else None
        )
        result.append({"student_id":sid,"full_name":student.get("full_name",""),"active":student.get("active",True),"logged_in":online,"ip":sess.get("ip") if sess else student.get("last_ip"),"user_agent":sess.get("user_agent","") if sess else "","last_seen":sess.get("last_seen") if sess else student.get("last_seen"),"exam_file":assignment.get("exam_file"),"exam_status":assignment.get("status","not_assigned"),"started_at":assignment.get("started_at"),"ends_at":assignment.get("ends_at"),"remaining_seconds":remaining_seconds(assignment) if assignment.get("started_at") else None,"submission_count":len(records),"latest_submission":records[-1] if records else None,"code_submission_count":len(code_records),"latest_code_submission":code_summary,"telemetry":telemetry,"alerts":alerts})
    abnormal_count=sum(1 for row in result if row["alerts"])
    return {"occurred_at":utc_now(),"students":result,"online_count":sum(1 for row in result if row["logged_in"]),"abnormal_count":abnormal_count}

class Handler(BaseHTTPRequestHandler):
    server_version = "ClassroomSubmissionServer/2.0"
    protocol_version = "HTTP/1.1"

    @property
    def cookies(self):
        jar=SimpleCookie()
        try: jar.load(self.headers.get("Cookie", ""))
        except Exception: pass
        return {k:v.value for k,v in jar.items()}

    def log_message(self, fmt, *args):
        print("[%s] %s - %s" % (self.log_date_time_string(), self.client_address[0], fmt % args))

    def _send(self, status=200, body=b"", content_type="text/html; charset=utf-8", headers=None, cookie=None, clear_cookie=False):
        if isinstance(body, str): body=body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        for k,v in (headers or {}).items(): self.send_header(k,v)
        if cookie:
            secure = bool(os.getenv("CSS_TLS_CERT") and os.getenv("CSS_TLS_KEY"))
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200" + ("; Secure" if secure else ""))
        if clear_cookie: self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
        self.end_headers()
        if self.command != "HEAD":
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass

    def _json(self, data, status=200, headers=None):
        self._send(status, json.dumps(data,ensure_ascii=False).encode(), "application/json; charset=utf-8", headers)

    def _redirect(self, location, status=303, cookie=None, clear_cookie=False):
        self._send(status, b"", "text/plain; charset=utf-8", {"Location":location}, cookie=cookie, clear_cookie=clear_cookie)

    def _html(self, text, status=200): self._send(status, text, "text/html; charset=utf-8")

    def _render(self, name, **context): return TEMPLATES.get_template(name).render(**context)

    def _parse_body(self):
        length=int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_REQUEST_SIZE: raise ClientError(413, "Request vượt giới hạn 50 MiB.")
        body=self.rfile.read(length) if length else b""
        ctype=self.headers.get("Content-Type", "")
        form={}; files={}; json_body=None
        if ctype.startswith("application/x-www-form-urlencoded"):
            parsed=urllib.parse.parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
            form={k:v[-1] for k,v in parsed.items()}
        elif ctype.startswith("multipart/form-data"):
            msg=BytesParser(policy=default).parsebytes((f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode()+body))
            if msg.is_multipart():
                for part in msg.iter_parts():
                    name=part.get_param("name", header="content-disposition")
                    if not name: continue
                    payload=part.get_payload(decode=True) or b""
                    filename=part.get_filename()
                    if filename is not None: files[name]={"filename":filename,"data":payload,"content_type":part.get_content_type()}
                    else: form[name]=payload.decode(part.get_content_charset() or "utf-8", "replace")
        elif ctype.lower().startswith("application/json"):
            try:
                json_body=json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ClientError(400,"Body JSON không hợp lệ hoặc không phải UTF-8.") from exc
            if not isinstance(json_body, dict):
                raise ClientError(400,"Body JSON phải là một object.")
        return body, RequestData(self,form,files,json_body)

    def _request(self, form=None, files=None): return RequestData(self,form,files)

    @staticmethod
    def _json_body(req):
        if req.json_body is None:
            raise ClientError(415,"Endpoint này yêu cầu Content-Type application/json.")
        return req.json_body

    def _auth(self, req, role=None):
        try: return require_user(req, role)
        except SecurityError as e: raise ClientError(e.status,e.detail)

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        try:
            req=self._request(); path=req.path
            route_path = path.rstrip("/") or "/"
            if path.startswith("/static/"):
                rel=urllib.parse.unquote(path[len("/static/"):]); target=(STATIC_DIR/rel).resolve()
                if not target.is_relative_to(STATIC_DIR.resolve()) or not target.is_file(): return self._send(404,"Not found")
                ctype=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                return self._send(200,target.read_bytes(),ctype)
            if path=="/health": return self._json({"status":"ok","service":"Classroom Submission Server","time":utc_now()})
            if path=="/login": return self._html(self._render("login.html",error=None))
            if path=="/":
                sess=get_session(req)
                if not sess: return self._redirect("/login")
                if sess["role"]=="admin": return self._redirect("/admin")
                student=self._get_user_record(sess); assignment=current_exam_for(sess["user_id"]); settings=read_json("settings.json")
                return self._html(self._render("student.html",session=sess,student=student,published_exams=general_exams.published_for_students(sess["user_id"]),assignment=assignment,settings=settings,remaining=remaining_seconds(assignment or {}) if assignment and assignment.get("started_at") else None))
            admin_sections={
                "/admin/dashboard":"dashboard",
                "/admin/monitor":"monitor",
                "/admin/notifications":"notifications",
                "/admin/exam":"exam",
                "/admin/exams":"exams",
                "/admin/settings":"exam",
                "/admin/distribution":"exam",
                "/admin/accounts":"accounts",
                "/admin/submissions":"submissions",
                "/admin/server":"server",
                "/admin/admins":"admins",
                "/admin/exam-management":"exam-management",
            }
            if route_path=="/admin" or route_path in admin_sections:
                sess=self._auth(req,"admin")
                section=admin_sections.get(route_path, req.query.get("section", ["dashboard"])[0])
                if section in {"settings", "distribution"}:
                    section="exam"
                allowed={"dashboard","monitor","notifications","exam","exams","accounts","submissions","server","admins","exam-management"}
                if section not in allowed: section="dashboard"
                tab=req.query.get("tab", ["questions"])[0]
                if tab not in {"questions","exams","results"}: tab="questions"
                return self._html(self._render("admin.html",session=sess,section=section,tab=tab,exam_id=req.query.get("id",[""])[0],exam_files=list_exam_files(),settings=read_json("settings.json"),monitoring=monitoring_snapshot()))
            if path=="/admin/accounts-template.txt":
                self._auth(req,"admin")
                content="21010001|01/02/2003|Nguyen Van A\n21010002|15/08/2003|Tran Thi B\n"
                return self._send(200,content,"text/plain; charset=utf-8",{"Content-Disposition":"attachment; filename=student_accounts_template.txt"})
            if path=="/api/admin/monitor": self._auth(req,"admin"); return self._json(monitoring_snapshot())
            if path=="/api/admin/exams": self._auth(req,"admin"); return self._json({"exams":list_exam_files()})
            if path=="/api/admin/accounts":
                self._auth(req,"admin")
                participants=set(read_json("settings.json").get("exam_participants") or [])
                return self._json({"students":[{"student_id":sid,"full_name":s.get("full_name"),"active":s.get("active",True),"last_ip":s.get("last_ip"),"last_seen":s.get("last_seen"),"exam_participant":sid in participants} for sid,s in read_json("students.json").items()]})
            if path=="/api/admin/submissions":
                self._auth(req,"admin"); students=read_json("students.json"); records=read_json("submissions.json"); result=[]
                for sid,attempts in records.items():
                    for index,item in enumerate(attempts,start=1): result.append({"student_id":sid,"full_name":students.get(sid,{}).get("full_name",""),"attempt":index,**item})
                result.sort(key=lambda x:x.get("submitted_at",""),reverse=True); return self._json({"submissions":result})
            if path=="/api/admin/admins":
                self._auth(req,"admin"); return self._json({"admins":[{"username":n,"active":d.get("active",True),"created_at":d.get("created_at"),"created_by":d.get("created_by")} for n,d in read_json("admins.json").items()]})
            if path=="/api/admin/questions":
                self._auth(req,"admin"); return self._json({"questions":list_questions()})
            if path.startswith("/api/admin/questions/"):
                self._auth(req,"admin")
                question_id = urllib.parse.unquote(path[len("/api/admin/questions/"):]).strip("/")
                if not question_id or "/" in question_id:
                    raise ClientError(404, "Question was not found.")
                question = get_question(question_id)
                if not question:
                    raise ClientError(404, "Question was not found.")
                return self._json({"question":question})
            if path=="/api/admin/exam-records":
                self._auth(req,"admin"); return self._json({"exams":general_exams.list_exams()})
            if path.startswith("/api/admin/exam-records/"):
                self._auth(req,"admin")
                exam_id=urllib.parse.unquote(path[len("/api/admin/exam-records/"):]).strip("/")
                if not exam_id or "/" in exam_id: raise ClientError(404,"Không tìm thấy kỳ thi.")
                return self._json({"exam":general_exams.get_exam(exam_id)})
            if path=="/api/admin/code-exams":
                self._auth(req,"admin"); return self._json({"code_exams":list_code_exams()})
            if path=="/api/admin/code-results":
                self._auth(req,"admin")
                exam_ids=req.query.get("exam_id",[])
                if not exam_ids or not exam_ids[0]: raise ClientError(400,"exam_id is required.")
                student_ids=req.query.get("student_id",[]); question_ids=req.query.get("question_id",[])
                return self._json(get_admin_code_results(exam_ids[0],student_id=student_ids[0] if student_ids else None,question_id=question_ids[0] if question_ids else None))
            if path=="/api/admin/server-info":
                self._auth(req,"admin"); addresses=self._lan_addresses(); scheme="https" if (os.getenv("CSS_TLS_CERT") and os.getenv("CSS_TLS_KEY")) else "http"
                return self._json({"addresses":sorted(addresses),"current_url":f"{scheme}://{self.headers.get('host',f'127.0.0.1:{PORT}')}","port":PORT,"scheme":scheme})
            if path=="/api/student/exam":
                sess=self._auth(req,"student"); item=current_exam_for(sess["user_id"]); settings=read_json("settings.json")
                if not settings.get("exam_released") or not item or item.get("release_id")!=settings.get("exam_release_id"): raise ClientError(403,"Lượt thi đã kết thúc hoặc chưa được phân phối.")
                if not item.get("started_at"): raise ClientError(403,"Chỉ xem được đề sau khi bắt đầu làm bài.")
                if remaining_seconds(item)<=0: raise ClientError(403,"Đã hết giờ làm bài.")
                if not item.get("exam_file"): raise ClientError(404,"Lượt thi này không có file đề ZIP/PDF; dùng endpoint đề code.")
                target=(EXAM_DIR/item["exam_file"]).resolve()
                if target.parent!=EXAM_DIR.resolve() or not target.is_file() or target.suffix.lower() not in {".pdf",".txt",".png",".jpg",".jpeg",".gif",".webp"}: raise ClientError(404,"File đề không còn tồn tại.")
                audit("exam.viewed",sess["user_id"],client_ip(req),{"exam_file":target.name})
                ctype=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                return self._send(200,target.read_bytes(),ctype,{"Content-Disposition":inline_filename_header(target.name)})
            if path=="/api/student/status":
                sess=self._auth(req,"student"); item=current_exam_for(sess["user_id"]); settings=read_json("settings.json")
                notifications=read_json("notifications.json", [])
                personal=[item for item in notifications if item.get("student_id") in (None, sess["user_id"])]
                return self._json({"assigned":bool(item),"started":bool(item and item.get("started_at")),"exam_file":item.get("exam_file") if item and item.get("started_at") else None,"status":item.get("status") if item else "not_assigned","remaining_seconds":remaining_seconds(item or {}) if item and item.get("started_at") else None,"started_at":item.get("started_at") if item else None,"ends_at":item.get("ends_at") if item else None,"server_time":utc_now(),"exam_state":settings.get("exam_state","idle"),"notifications":personal[-10:],"exam_password_enabled":settings.get("exam_password_enabled",False),                "accepted_submission_extensions":settings.get("accepted_submission_extensions",[".zip"]),"published_exams":general_exams.published_for_students(sess["user_id"])})
            if path=="/api/student/code-exam":
                sess=self._auth(req,"student"); return self._json(get_student_code_exam(sess["user_id"]))
            if path=="/api/student/code/submission":
                sess=self._auth(req,"student"); question_ids=req.query.get("question_id",[])
                if not question_ids or not question_ids[0]: raise ClientError(400,"question_id is required.")
                return self._json(get_student_submission(sess["user_id"],question_ids[0]))
            if path.startswith("/admin/submissions/"):
                sess=self._auth(req,"admin"); parts=[urllib.parse.unquote(x) for x in path.split("/")[3:]]
                if len(parts)!=2: raise ClientError(404,"Không tìm thấy file bài nộp.")
                sid,filename=parts; records=read_json("submissions.json")
                if not any(x.get("filename")==filename and x.get("payload_retained",True) for x in records.get(sid,[])): raise ClientError(404,"Không tìm thấy file bài nộp còn được lưu.")
                target=(UPLOAD_DIR/filename).resolve()
                if target.parent!=UPLOAD_DIR.resolve() or not target.is_file(): raise ClientError(404,"File bài nộp không tồn tại.")
                audit("admin.submission_downloaded",sess["user_id"],client_ip(req),{"student_id":sid,"filename":filename})
                return self._send(200,target.read_bytes(),mimetypes.guess_type(target.name)[0] or "application/octet-stream",{"Content-Disposition":f'attachment; filename="{target.name}"'})
            return self._send(404,"Không tìm thấy trang.")
        except (ClientError, SecurityError, CodeExamError, QuestionError, ExamError) as e: return self._handle_error(e)
        except Exception:
            traceback.print_exc(); return self._json({"detail":"Lỗi máy chủ nội bộ."},500)

    def _get_user_record(self, sess):
        source="admins.json" if sess["role"]=="admin" else "students.json"; record=read_json(source).get(sess["user_id"])
        if not record or not record.get("active",True): raise ClientError(401,"Tài khoản không còn hoạt động.")
        return record

    def do_POST(self):
        try:
            body,req=self._parse_body(); path=req.path; f=req.form; sess=None
            if path=="/login":
                username=f.get("username","").strip(); password=f.get("password",""); ip=client_ip(req); key=username.casefold()
                allowed,seconds=login_allowed(key)
                if not allowed:
                    audit("auth.login_locked",username,ip,{"retry_after_seconds":seconds}); return self._html(self._render("login.html",error=f"Tài khoản tạm khóa. Vui lòng thử lại sau {max(1,seconds//60+1)} phút."),429)
                admins,students=read_json("admins.json"),read_json("students.json")
                role="admin" if username in admins else "student" if username in students else None
                record=admins.get(username) if role=="admin" else students.get(username) if role=="student" else None
                if not record or not record.get("active",True) or not verify_password(password,record.get("password_hash")):
                    seconds=record_login_failure(key); audit("auth.login_failed",username,ip,{"lockout_seconds":seconds}); msg="Thông tin đăng nhập không đúng."
                    if seconds: msg += " Đã khóa tạm trong 15 phút sau 3 lần sai."
                    return self._html(self._render("login.html",error=msg),401)
                clear_login_failures(key)
                if role=="student":
                    sessions=read_json("sessions.json"); revoked=[k for k,v in sessions.items() if v.get("role")=="student" and v.get("user_id")==username]
                    for k in revoked: sessions.pop(k,None)
                    if revoked: write_json("sessions.json",sessions); audit("auth.previous_session_revoked",username,ip,{"revoked_sessions":len(revoked)})
                token=new_session(username,role,ip,self.headers.get("user-agent",""))
                if role=="student":
                    students[username]["last_ip"]=ip; students[username]["last_seen"]=utc_now(); write_json("students.json",students)
                audit("auth.login_success",username,ip,{"role":role}); return self._redirect("/admin" if role=="admin" else "/",cookie=token)
            if path=="/logout":
                sess=get_session(req)
                if sess: logout_session(sess["token"]); audit("auth.logout",sess["user_id"],client_ip(req),{})
                return self._redirect("/login",clear_cookie=True)
            if path=="/api/admin/questions":
                sess=self._auth(req,"admin"); payload=self._json_body(req)
                question=create_question(payload,sess["user_id"],client_ip(req))
                return self._json({"ok":True,"question":question},201)
            if path.startswith("/api/admin/questions/") and path.endswith("/update"):
                sess=self._auth(req,"admin")
                question_id=urllib.parse.unquote(path[len("/api/admin/questions/"):-len("/update")].strip("/"))
                if not question_id or "/" in question_id: raise ClientError(404,"Question was not found.")
                question=update_question(question_id,self._json_body(req),sess["user_id"],client_ip(req))
                return self._json({"ok":True,"question":question})
            if path.startswith("/api/admin/questions/") and path.endswith("/duplicate"):
                sess=self._auth(req,"admin")
                question_id=urllib.parse.unquote(path[len("/api/admin/questions/"):-len("/duplicate")].strip("/"))
                if not question_id or "/" in question_id: raise ClientError(404,"Question was not found.")
                question=duplicate_question(question_id,sess["user_id"],client_ip(req))
                return self._json({"ok":True,"question":question},201)
            if path.startswith("/api/admin/questions/") and path.endswith("/archive"):
                sess=self._auth(req,"admin")
                question_id=urllib.parse.unquote(path[len("/api/admin/questions/"):-len("/archive")].strip("/"))
                if not question_id or "/" in question_id: raise ClientError(404,"Question was not found.")
                question=archive_question(question_id,sess["user_id"],client_ip(req))
                return self._json({"ok":True,"question":question})
            if path.startswith("/api/admin/questions/") and path.endswith("/delete"):
                sess=self._auth(req,"admin")
                question_id=urllib.parse.unquote(path[len("/api/admin/questions/"):-len("/delete")].strip("/"))
                if not question_id or "/" in question_id: raise ClientError(404,"Question was not found.")
                delete_question(question_id,sess["user_id"],client_ip(req))
                return self._json({"ok":True})
            if path.startswith("/api/admin/questions/") and path.endswith("/validate"):
                sess=self._auth(req,"admin"); question_id=urllib.parse.unquote(path[len("/api/admin/questions/"):-len("/validate")].strip("/")); payload=self._json_body(req)
                if not question_id or "/" in question_id: raise ClientError(404,"Question was not found.")
                result=validate_question_sample(question_id,payload.get("sample_source"),sess["user_id"],client_ip(req))
                infra=result.get("error_category") in {"INVALID_REQUEST","JDK_NOT_FOUND","JUDGE_INFRA_ERROR","PROTOCOL_ERROR"}
                return self._json({"ok":not infra,**result},503 if infra else 200)
            if path.startswith("/api/admin/questions/") and path.endswith("/publish"):
                sess=self._auth(req,"admin"); question_id=urllib.parse.unquote(path[len("/api/admin/questions/"):-len("/publish")].strip("/"))
                if not question_id or "/" in question_id: raise ClientError(404,"Question was not found.")
                question=publish_question(question_id,sess["user_id"],client_ip(req))
                return self._json({"ok":True,"question":question,"validation":question.get("validation")},200)
            if path.startswith("/api/admin/code-results/") and path.endswith("/regrade"):
                sess=self._auth(req,"admin")
                exam_id=urllib.parse.unquote(path[len("/api/admin/code-results/"):-len("/regrade")].strip("/"))
                if not exam_id or "/" in exam_id: raise ClientError(404,"Code exam was not found.")
                payload=self._json_body(req)
                submission_id=payload.get("submission_id")
                if not isinstance(submission_id,str) or not submission_id:
                    raise ClientError(400,"submission_id is required.")
                use_latest_spec=payload.get("use_latest_spec",False)
                if not isinstance(use_latest_spec,bool):
                    raise ClientError(400,"use_latest_spec must be a boolean.")
                result=regrade_submission(exam_id,submission_id,sess["user_id"],client_ip(req),use_latest_spec=use_latest_spec)
                return self._json({"ok":True,"submission":result})
            if path=="/api/admin/exam-records":
                sess=self._auth(req,"admin")
                return self._json({"ok":True,"exam":general_exams.create_exam(self._json_body(req),sess["user_id"],client_ip(req))},201)
            if path.startswith("/api/admin/exam-records/"):
                sess=self._auth(req,"admin"); parts=[urllib.parse.unquote(x) for x in path[len("/api/admin/exam-records/"):].strip("/").split("/")]
                if len(parts)!=2: raise ClientError(404,"Không tìm thấy endpoint.")
                exam_id,action=parts; actor=sess["user_id"]; ip=client_ip(req)
                if action=="update": return self._json({"ok":True,"exam":general_exams.update_exam(exam_id,self._json_body(req),actor,ip)})
                actions={"publish":general_exams.publish_exam,"revoke":general_exams.revoke_exam,"start":general_exams.start_exam,"end":general_exams.end_exam,"copy":general_exams.copy_exam}
                if action in actions: return self._json({"ok":True,"exam":actions[action](exam_id,actor,ip)})
                if action=="delete": return self._json({"ok":True,**general_exams.delete_exam(exam_id,actor,ip)})
                raise ClientError(404,"Không tìm thấy endpoint.")
            if path=="/api/admin/code-exams":
                sess=self._auth(req,"admin"); exam=create_code_exam(self._json_body(req),sess["user_id"],client_ip(req))
                return self._json({"ok":True,"code_exam":exam},201)
            if path=="/api/admin/accounts/import":
                sess=self._auth(req,"admin"); text=f.get("pasted_text",""); file=req.files.get("account_file")
                if file and file.get("filename"):
                    if not file["filename"].lower().endswith(".txt"): raise ClientError(400,"Chỉ chấp nhận file .txt.")
                    payload=file["data"]
                    if len(payload)>2*1024*1024: raise ClientError(413,"File danh sách vượt quá 2 MiB.")
                    try: text += "\n"+payload.decode("utf-8-sig",errors="strict")
                    except UnicodeDecodeError: raise ClientError(400,"File .txt phải được mã hóa UTF-8.")
                rows,errors=parse_accounts(text); students=read_json("students.json"); created=[]; duplicates=[]
                for row in rows:
                    sid=row["student_id"]
                    if sid in students: duplicates.append(sid); continue
                    students[sid]={"student_id":sid,"full_name":row["full_name"],"password_hash":hash_password(row["dob"]),"active":True,"created_at":utc_now(),"last_ip":None,"last_seen":None,"must_change_password":False}; created.append(sid)
                write_json("students.json",students); audit("admin.accounts_imported",sess["user_id"],client_ip(req),{"created":len(created),"duplicates":duplicates,"parse_errors":errors})
                return self._json({"created_count":len(created),"created":created,"duplicates":duplicates,"errors":errors,"valid_rows":len(rows)})
            if path=="/api/admin/exam-participants":
                sess=self._auth(req,"admin")
                raw = f.get("student_ids", "")
                ids = [item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()]
                if not ids:
                    raise ClientError(400, "Hãy chọn hoặc nhập ít nhất một MSSV.")
                if len(ids) > 10000 or any(len(item) > 80 or not item.isalnum() for item in ids):
                    raise ClientError(400, "Danh sách MSSV không hợp lệ.")
                ids = list(dict.fromkeys(ids))
                students = read_json("students.json")
                created = []
                for sid in ids:
                    if sid not in students:
                        students[sid] = {"student_id": sid, "full_name": "Chưa cập nhật", "password_hash": hash_password(sid), "active": True, "created_at": utc_now(), "last_ip": None, "last_seen": None, "must_change_password": True}
                        created.append(sid)
                settings = read_json("settings.json")
                if settings.get("exam_state") == "started" or settings.get("exam_released"):
                    raise ClientError(409, "Không thể thay đổi danh sách dự thi khi kỳ thi đã bắt đầu.")
                settings["exam_participants"] = ids
                write_json("students.json", students)
                write_json("settings.json", settings)
                audit("admin.exam_participants_updated", sess["user_id"], client_ip(req), {"count": len(ids), "created": len(created)})
                return self._json({"ok": True, "student_ids": ids, "created": created, "count": len(ids)})
            if path.startswith("/api/admin/accounts/") and path.endswith("/reset-password"):
                sess=self._auth(req,"admin"); sid=urllib.parse.unquote(path[len("/api/admin/accounts/"):-len("/reset-password")].strip("/")); password=f.get("new_password","")
                if not password.strip() or len(password)>200: raise ClientError(400,"Mật khẩu mới không hợp lệ.")
                students=read_json("students.json")
                if sid not in students: raise ClientError(404,"Không tìm thấy MSSV.")
                students[sid]["password_hash"]=hash_password(password); write_json("students.json",students)
                sessions={k:v for k,v in read_json("sessions.json").items() if not (v.get("role")=="student" and v.get("user_id")==sid)}; write_json("sessions.json",sessions)
                audit("admin.password_reset",sess["user_id"],client_ip(req),{"student_id":sid}); return self._json({"ok":True})
            if path.startswith("/api/admin/accounts/") and path.endswith("/unlock-login"):
                sess=self._auth(req,"admin"); sid=urllib.parse.unquote(path[len("/api/admin/accounts/"):-len("/unlock-login")].strip("/"))
                clear_login_failures(sid.casefold())
                audit("admin.login_lockout_cleared",sess["user_id"],client_ip(req),{"student_id":sid})
                return self._json({"ok":True})
            if path.startswith("/api/admin/accounts/") and path.endswith("/toggle"):
                sess=self._auth(req,"admin"); sid=urllib.parse.unquote(path[len("/api/admin/accounts/"):-len("/toggle")].strip("/")); students=read_json("students.json")
                if sid not in students: raise ClientError(404,"Không tìm thấy MSSV.")
                students[sid]["active"]=not students[sid].get("active",True); write_json("students.json",students)
                if not students[sid]["active"]:
                    sessions={k:v for k,v in read_json("sessions.json").items() if not (v.get("role")=="student" and v.get("user_id")==sid)}; write_json("sessions.json",sessions)
                audit("admin.account_toggled",sess["user_id"],client_ip(req),{"student_id":sid,"active":students[sid]["active"]}); return self._json({"active":students[sid]["active"]})
            if path=="/api/admin/settings":
                sess=self._auth(req,"admin")
                try: duration=int(f.get("exam_duration_minutes","90")); max_sub=int(f.get("max_submissions","1"))
                except ValueError: raise ClientError(400,"Thời lượng hoặc số lần nộp không hợp lệ.")
                policy=f.get("submission_policy","once")
                if not 1<=duration<=1440: raise ClientError(400,"Thời lượng phải từ 1 đến 1440 phút.")
                if policy not in {"once","configurable"}: raise ClientError(400,"Chính sách nộp không hợp lệ.")
                if not 1<=max_sub<=20: raise ClientError(400,"Số lần nộp phải từ 1 đến 20.")
                settings=read_json("settings.json")
                if settings.get("exam_released"): raise ClientError(409,"Không thể thay đổi cấu hình khi kỳ thi đang được phát. Hãy kết thúc lượt thi trước.")
                enabled=f.get("exam_password_enabled","false").lower() in {"true","1","on","yes"}; password=f.get("exam_password","")
                if enabled and password: settings["exam_password_hash"]=hash_password(password)
                elif enabled and not settings.get("exam_password_hash"): raise ClientError(400,"Hãy nhập mật khẩu đề khi bật tùy chọn này.")
                elif not enabled: settings["exam_password_hash"]=None
                extension_values = f.get("accepted_submission_extensions", ".zip").replace(",", " ").split()
                accepted_extensions = sorted({value if value.startswith(".") else f".{value}" for value in extension_values if value})
                if not accepted_extensions or any(len(value) > 10 for value in accepted_extensions):
                    raise ClientError(400, "Danh sách loại file nộp không hợp lệ.")
                settings.update({"exam_duration_minutes":duration,"submission_policy":policy,"max_submissions":max_sub,"overwrite_previous":f.get("overwrite_previous","false").lower() in {"true","1","on","yes"},"exam_password_enabled":enabled,"accepted_submission_extensions":accepted_extensions}); write_json("settings.json",settings)
                audit("admin.settings_updated",sess["user_id"],client_ip(req),{"exam_duration_minutes":duration,"submission_policy":policy,"max_submissions":max_sub,"exam_password_enabled":enabled}); return self._json({"ok":True,"settings":settings})
            if path=="/api/admin/distribute":
                sess=self._auth(req,"admin"); mode=f.get("mode","random"); config={}
                try:
                    selected_files = [value for value in f.get("exam_files", "").split(",") if value]
                    if mode=="selected": config={"exam_files":selected_files}
                    elif mode=="random": config={"exam_files":selected_files}
                    elif mode=="parity": config={"even_exam":f.get("even_exam",""),"odd_exam":f.get("odd_exam","")}
                    elif mode=="custom":
                        try:
                            modulus=int(f.get("custom_modulus","0"))
                        except ValueError:
                            raise ValueError("Số chia không hợp lệ.")
                        config={"last_digit_map":json.loads(f.get("last_digit_map","{}")),"custom_modulus":modulus,"exam_files":selected_files}
                    if f.get("code_exam_id"):
                        config["code_exam_id"]=f.get("code_exam_id").strip()
                        config["code_only"]=f.get("code_only","false").lower() in {"true","1","on","yes"}
                    result=distribute_exams(mode,config)
                except CodeExamError as e: raise ClientError(e.status,str(e))
                except (ValueError,json.JSONDecodeError) as e: raise ClientError(400,str(e))
                audit("admin.exam_distributed",sess["user_id"],client_ip(req),{"release_id":result["release_id"],"mode":mode}); return self._json(result)
            if path=="/api/admin/end-exam":
                sess=self._auth(req,"admin")
                try: ended=end_exam_session()
                except ValueError as e: raise ClientError(409,str(e))
                audit("admin.exam_ended",sess["user_id"],client_ip(req),{"release_id":ended["release_id"],"ended_at":ended["ended_at"]})
                return self._json({"ok":True,"note":"Lượt thi đã kết thúc; các đề đã phát của lượt cũ vẫn được giữ trong log nhưng không còn cho phép bắt đầu mới."})
            if path=="/api/admin/start-exam":
                self._auth(req,"admin")
                try: settings=start_exam_session()
                except ValueError as e: raise ClientError(409,str(e))
                return self._json({"ok":True,"state":settings["exam_state"],"started_at":settings["exam_started_at"]})
            if path.startswith("/api/admin/students/") and path.endswith("/force-submit"):
                sess=self._auth(req,"admin"); sid=urllib.parse.unquote(path[len("/api/admin/students/"):-len("/force-submit")])
                assignments=read_json("assignments.json"); item=assignments.get(sid)
                if not item or item.get("status") not in {"assigned","in_progress"}: raise ClientError(404,"Sinh viên không có bài thi đang hoạt động.")
                item.update({"status":"submitted","forced_submit":True,"forced_submit_at":utc_now()}); assignments[sid]=item; write_json("assignments.json",assignments)
                audit("admin.forced_submission",sess["user_id"],client_ip(req),{"student_id":sid}); return self._json({"ok":True})
            if path.startswith("/api/admin/students/") and path.endswith("/adjust-time"):
                sess=self._auth(req,"admin"); sid=urllib.parse.unquote(path[len("/api/admin/students/"):-len("/adjust-time")]); minutes=int(f.get("minutes","0"))
                if minutes < -1440 or minutes > 1440: raise ClientError(400,"Số phút điều chỉnh không hợp lệ.")
                assignments=read_json("assignments.json"); item=assignments.get(sid)
                if not item or not item.get("ends_at"): raise ClientError(404,"Sinh viên chưa bắt đầu làm bài.")
                end=datetime.fromisoformat(item["ends_at"])+timedelta(minutes=minutes); item["ends_at"]=end.isoformat(timespec="seconds"); assignments[sid]=item; write_json("assignments.json",assignments)
                audit("admin.exam_time_adjusted",sess["user_id"],client_ip(req),{"student_id":sid,"minutes":minutes}); return self._json({"ok":True,"ends_at":item["ends_at"]})
            if path=="/api/admin/notifications":
                sess=self._auth(req,"admin"); message=f.get("message","").strip(); raw_targets=f.get("student_ids","").strip()
                if not message or len(message)>1000: raise ClientError(400,"Nội dung thông báo không hợp lệ.")
                students=read_json("students.json")
                targets=[sid.strip() for sid in raw_targets.split(",") if sid.strip()] if raw_targets else [None]
                if any(target is not None and target not in students for target in targets): raise ClientError(404,"Không tìm thấy một hoặc nhiều MSSV.")
                notifications=read_json("notifications.json",[])
                notifications.extend({"id":secrets.token_hex(8),"student_id":target,"message":message,"created_at":utc_now(),"created_by":sess["user_id"]} for target in targets)
                write_json("notifications.json",notifications)
                audit("admin.notification_sent",sess["user_id"],client_ip(req),{"recipient_count":len(students) if targets == [None] else len(targets),"targeted":targets != [None]})
                return self._json({"ok":True,"recipient_count":len(students) if targets == [None] else len(targets)})
            if path=="/api/student/start":
                sess=self._auth(req,"student")
                try: item=start_exam(sess["user_id"],f.get("exam_password",""),client_ip(req))
                except PermissionError as e: raise ClientError(403,str(e))
                except ValueError as e: raise ClientError(400,str(e))
                return self._json({"ok":True,"exam_file":item["exam_file"],"started_at":item["started_at"],"ends_at":item["ends_at"],"remaining_seconds":remaining_seconds(item)})
            if path=="/api/student/code/run":
                sess=self._auth(req,"student"); payload=self._json_body(req)
                question_id=payload.get("question_id"); source_code=payload.get("source_code")
                if not isinstance(question_id,str) or not question_id: raise ClientError(400,"question_id is required.")
                result=run_pretest(sess["user_id"],question_id,source_code,client_ip(req))
                infra=result.get("error_category") in {"INVALID_REQUEST","JDK_NOT_FOUND","JUDGE_INFRA_ERROR","PROTOCOL_ERROR"}
                return self._json({"ok":not infra,**result},503 if infra else 200)
            if path=="/api/student/code/submit":
                sess=self._auth(req,"student"); payload=self._json_body(req)
                question_id=payload.get("question_id"); source_code=payload.get("source_code")
                if not isinstance(question_id,str) or not question_id: raise ClientError(400,"question_id is required.")
                submission,graded=submit_code(sess["user_id"],question_id,source_code,client_ip(req))
                if not graded:
                    return self._json({"ok":False,"submission":submission},503)
                return self._json({"ok":True,"submission":submission},201)
            if path=="/api/student/submit":
                sess=self._auth(req,"student"); file=req.files.get("file")
                if not file or not file.get("filename") or not file["filename"].lower().endswith(".zip"): raise ClientError(400,"Chỉ chấp nhận file .zip.")
                data=file["data"]
                if len(data)>MAX_REQUEST_SIZE: raise ClientError(413,"File vượt giới hạn 50 MiB.")
                try: record=accept_submission(sess["user_id"],file["filename"],data,client_ip(req))
                except ValueError as e: raise ClientError(400,str(e))
                return self._json({"ok":True,"submission":record})
            if path=="/api/student/telemetry":
                sess=self._auth(req,"student")
                sessions=read_json("sessions.json"); token_key=sess.get("token_key")
                current=sessions.get(token_key)
                if not current: raise ClientError(401,"Phiên đăng nhập không hợp lệ.")
                def flag(name, default=False):
                    return f.get(name, str(default)).lower() in {"true","1","on","yes"}
                try: tab_count=max(1,min(20,int(f.get("tab_count","1"))))
                except ValueError: tab_count=1
                current["telemetry"]={"visibility":"hidden" if f.get("visibility")=="hidden" else "visible","focused":flag("focused",True),"tab_count":tab_count,"browser":f.get("browser","")[:80],"updated_at":utc_now()}
                current["last_seen"]=utc_now(); sessions[token_key]=current; write_json("sessions.json",sessions)
                return self._json({"ok":True})
            if path=="/api/admin/admins":
                sess=self._auth(req,"admin"); username=f.get("username","").strip(); password=f.get("password","")
                if not username or len(username)>80 or not all(c.isalnum() or c in "._-@" for c in username): raise ClientError(400,"Tên Admin không hợp lệ.")
                if len(password)<10 or len(password)>200: raise ClientError(400,"Mật khẩu Admin phải dài ít nhất 10 ký tự.")
                admins=read_json("admins.json")
                if username in admins or username in read_json("students.json"): raise ClientError(409,"Tên tài khoản đã tồn tại.")
                admins[username]={"username":username,"password_hash":hash_password(password),"active":True,"created_at":utc_now(),"created_by":sess["user_id"]}; write_json("admins.json",admins); audit("admin.admin_created",sess["user_id"],client_ip(req),{"new_admin":username})
                return self._json({"ok":True,"username":username})
            return self._json({"detail":"Không tìm thấy endpoint."},404)
        except (ClientError, SecurityError, CodeExamError, QuestionError, ExamError) as e: return self._handle_error(e)
        except Exception:
            traceback.print_exc(); return self._json({"detail":"Lỗi máy chủ nội bộ."},500)

    def _handle_error(self,e):
        status=getattr(e,"status",500); detail=getattr(e,"detail",str(e)); code=getattr(e,"code",None); fields=getattr(e,"fields",None)
        if self.path.startswith("/api/") or self.path.startswith("/admin/submissions/") or self.path=="/api/student/exam": return self._json({"detail":detail,**({"code":code} if code else {}),**({"fields":fields} if fields else {})},status)
        return self._html("<!doctype html><meta charset='utf-8'><title>Lỗi</title><h1>Yêu cầu không thể xử lý</h1><p>"+html.escape(detail)+"</p><p><a href='/'>Quay lại</a></p>",status)

    @staticmethod
    def _lan_addresses():
        addresses=set()
        try:
            for item in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET,socket.SOCK_STREAM):
                ip=item[4][0]
                if not ip.startswith("127."): addresses.add(ip)
        except OSError: pass
        for target in ("192.0.2.1","8.8.8.8"):
            s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            try:
                s.connect((target,80)); ip=s.getsockname()[0]
                if not ip.startswith("127."): addresses.add(ip)
            except OSError: pass
            finally: s.close()
        return addresses

def main():
    jdk = None
    if os.name == "nt":
        try:
            jdk = verify_jdk_configuration()
        except (JDKConfigurationError, JDKNotFoundError) as exc:
            raise SystemExit(f"ERROR: Java grading requires a working JDK 17 or newer: {exc}") from exc
    cert,key=os.getenv("CSS_TLS_CERT"),os.getenv("CSS_TLS_KEY")
    scheme="https" if cert and key else "http"
    print("="*66); print("CLASSROOM SUBMISSION SERVER (Python standard-library HTTP server)"); print("="*66)
    print(f"Local URL : {scheme}://127.0.0.1:{PORT}")
    for ip in sorted(Handler._lan_addresses()): print(f"LAN URL   : {scheme}://{ip}:{PORT}")
    if not (cert and key): print("WARNING   : HTTP mode; LAN traffic is not encrypted. Use trusted TLS certs for HTTPS.")
    if jdk:
        print(f"Java JDK  : {jdk.java_version} ({jdk.home})")
    else:
        print("WARNING   : Code grading is unavailable outside Windows; ZIP submission remains enabled.")
    print(f"Exam dir  : {EXAM_DIR}"); print(f"Upload dir: {UPLOAD_DIR}"); print("Ctrl+C to stop. Keep this terminal open during the exam."); print("="*66)
    server=ThreadingHTTPServer((HOST,PORT),Handler); server.daemon_threads=True
    if cert and key:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(cert,key); server.socket=context.wrap_socket(server.socket,server_side=True)
    try: server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt: print("\nStopping server...")
    finally: server.server_close()

if __name__=="__main__": main()
