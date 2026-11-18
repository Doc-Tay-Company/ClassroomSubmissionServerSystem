import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import exams, main, practice, storage
from tests.test_practice import _make_stdio_payload, _mock_exec


class PracticeLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='css-practice-lock-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for attr, folder in [('DATA_DIR', 'data'), ('LOG_DIR', 'logs')]:
            value = root / folder
            value.mkdir()
            p = patch.object(storage, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.now = datetime.now(timezone.utc)
        self.settings = {'exam_state': 'started', 'exam_released': True, 'exam_release_id': 'release-lock', 'exam_duration_minutes': 30}
        self.assignment = {'release_id': 'release-lock', 'status': 'assigned', 'exam_file': 'exam.pdf', 'started_at': None, 'ends_at': None}
        storage.write_json('settings.json', self.settings)
        storage.write_json('assignments.json', {'A': self.assignment})
        storage.write_json('students.json', {'A': {'active': True}, 'B': {'active': True}})
        storage.write_json('practice_progress.json', {})
        self.question = _make_stdio_payload('lock-question', practice_enabled=True)
        self.question.update(status='published', practice_revision='e' * 32, version=1)
        storage.write_json('questions.json', {self.question['id']: self.question})
        self.payload = {'question_id': self.question['id'], 'expected_practice_revision': 'e' * 32,
                        'attempt_id': 'a' * 32, 'source_code': "print('hello')"}

    def activate(self):
        with storage.transaction(), patch('app.exams.audit'):
            return exams.start_exam('A')

    def handler(self, path, method='GET', payload=None, student='A', role='student'):
        req = SimpleNamespace(path=path, query={}, json_body=payload or {}, form={}, cookies={})
        h = object.__new__(main.Handler)
        h.path = path
        h._request = lambda: req
        h._parse_body = lambda: (json.dumps(payload or {}).encode(), req)
        def auth(_req, wanted=None):
            if role is None: raise main.ClientError(401, 'Authentication required')
            if wanted and wanted != role: raise main.ClientError(403, 'Student required')
            return {'user_id': student, 'role': role}
        h._auth = auth
        h._json = lambda data, status=200, headers=None: (status, data)
        return h

    def request(self, path, method='GET', payload=None, student='A', role='student'):
        h = self.handler(path, method, payload, student, role)
        return getattr(h, 'do_' + method)()

    def test_login_and_teacher_start_without_student_start_allow_practice(self):
        for state in ['idle', 'distributed', 'started', 'ended']:
            storage.write_json('settings.json', {**self.settings, 'exam_state': state})
            self.assertEqual(self.request('/api/student/practice/questions')[0], 200)
        storage.write_json('assignments.json', {})
        self.assertEqual(self.request('/api/student/practice/progress')[0], 200)

    def test_every_practice_endpoint_rejects_active_attempt_without_partial_writes(self):
        self.activate() # No Fullscreen field is involved in the rule.
        before = copy.deepcopy(storage.read_json('practice_progress.json'))
        routes = [
            ('GET', '/api/student/practice/questions'),
            ('GET', '/api/student/practice/questions/lock-question'),
            ('GET', '/api/student/practice/progress'),
            ('GET', '/api/student/practice/questions/lock-question/run-status'),
            ('POST', '/api/student/practice/run'),
            ('POST', '/api/student/practice/questions/lock-question/update'),
            ('DELETE', '/api/student/practice/progress/lock-question'),
        ]
        for method, path in routes:
            with self.subTest(method=method, path=path):
                status, body = self.request(path, method, self.payload)
                self.assertEqual((status, body.get('code')), (403, 'PRACTICE_LOCKED'))
        self.assertEqual(storage.read_json('practice_progress.json'), before)
        self.assertEqual(self.request('/api/student/status')[0], 200)

    def test_lock_is_student_scoped_and_survives_new_session_handlers(self):
        self.activate()
        self.assertEqual(self.request('/api/student/practice/questions', student='A')[0], 403)
        self.assertEqual(self.request('/api/student/practice/questions', student='B')[0], 200)
        self.assertEqual(self.request('/api/student/practice/questions', student='A')[0], 403)

    def test_authentication_and_role_are_checked_before_lock(self):
        self.activate()
        self.assertEqual(self.request('/api/student/practice/questions', role=None)[0], 401)
        self.assertEqual(self.request('/api/student/practice/questions', role='admin')[0], 403)

    def test_failed_start_does_not_lock(self):
        storage.write_json('settings.json', {**self.settings, 'exam_state': 'distributed'})
        with self.assertRaises(ValueError): self.activate()
        self.assertEqual(self.request('/api/student/practice/questions')[0], 200)

    def test_terminal_states_expiry_force_and_release_mismatch_unlock(self):
        active = self.activate()
        cases = [
            {**active, 'status': status} for status in ['submitted', 'ended', 'expired']
        ] + [{**active, 'forced_submit': True},
             {**active, 'ends_at': (self.now - timedelta(seconds=1)).isoformat()},
             {**active, 'release_id': 'old-release'}]
        for assignment in cases:
            with self.subTest(assignment=assignment):
                storage.write_json('assignments.json', {'A': assignment})
                self.assertEqual(self.request('/api/student/practice/questions')[0], 200)
        storage.write_json('assignments.json', {'A': active})
        storage.write_json('settings.json', {**self.settings, 'exam_state': 'ended'})
        self.assertEqual(self.request('/api/student/practice/questions')[0], 200)

    def test_admitted_run_finishes_and_persists_after_start_while_new_run_is_rejected(self):
        executing, finish = threading.Event(), threading.Event()
        result, errors = [], []
        def execute(*args, **kwargs):
            executing.set()
            if not finish.wait(5): raise RuntimeError('test synchronization timeout')
            return _mock_exec()
        def run():
            try: result.append(practice.run_practice('A', self.payload))
            except Exception as error: errors.append(error)
        with patch('app.code_exams.execute_question', side_effect=execute):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(executing.wait(3))
                self.activate()
                with self.assertRaises(practice.PracticeError) as caught:
                    practice.run_practice('A', self.payload)
                self.assertEqual(caught.exception.code, 'PRACTICE_LOCKED')
                self.assertEqual(self.request('/api/student/practice/questions/lock-question/run-status')[0], 403)
            finally:
                finish.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors, errors)
        self.assertTrue(result[0]['completed'])
        self.assertTrue(storage.read_json('practice_progress.json')['A']['lock-question']['has_result'])
        assignments = storage.read_json('assignments.json')
        assignments['A']['status'] = 'submitted'
        storage.write_json('assignments.json', assignments)
        status, body = self.request('/api/student/practice/progress')
        self.assertEqual(status, 200)
        self.assertTrue(body['progress'][0]['progress']['has_result'])

    def test_start_owns_admission_lock_before_late_run(self):
        attempted = threading.Event()
        errors = []
        def run():
            attempted.set()
            try: practice.run_practice('A', self.payload)
            except practice.PracticeError as error: errors.append(error.code)
        with storage.transaction():
            worker = threading.Thread(target=run)
            worker.start()
            self.assertTrue(attempted.wait(2))
            self.activate()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ['PRACTICE_LOCKED'])
        self.assertNotIn('A', storage.read_json('practice_progress.json'))

    def test_update_and_delete_service_guards_preserve_progress(self):
        saved = {'A': {'lock-question': {'attempt_id': 'a' * 32, 'practice_revision': 'e' * 32, 'has_result': True}}}
        storage.write_json('practice_progress.json', saved)
        self.activate()
        for operation in [lambda: practice.delete_student_question_progress('A', 'lock-question'),
                          lambda: practice.update_question_progress('A', 'lock-question', 'a' * 32, 'e' * 32, 'e' * 32)]:
            with self.assertRaises(practice.PracticeError) as caught: operation()
            self.assertEqual(caught.exception.code, 'PRACTICE_LOCKED')
        self.assertEqual(storage.read_json('practice_progress.json'), saved)


if __name__ == '__main__':
    unittest.main()
