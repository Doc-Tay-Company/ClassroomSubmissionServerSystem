import unittest
from unittest.mock import patch

from app import exam_monitoring, exams, main, storage
from app.security import hash_password
from tests import test_exam_monitoring as monitoring_tests


class StartMonitoringTests(unittest.TestCase):
    setUp = monitoring_tests.ExamMonitoringTests.setUp
    tearDown = monitoring_tests.ExamMonitoringTests.tearDown
    _handler = monitoring_tests.ExamMonitoringTests._handler

    def prepare(self, password=False):
        self.settings.update(exam_duration_minutes=30, exam_password_enabled=password,
                             exam_password_hash=hash_password('secret') if password else None)
        storage.write_json('settings.json', self.settings)
        storage.write_json('assignments.json', {self.student: {
            'release_id': self.release, 'exam_file': 'exam.pdf', 'status': 'assigned',
            'started_at': None, 'ends_at': None,
        }})

    def start(self, confirmed=None, password=''):
        handler = self._handler('/api/student/start')
        _, request = handler._parse_body()
        request.form['exam_password'] = password
        if confirmed is not None:
            request.form['confirmed_multiple_tabs'] = confirmed
        handler._parse_body = lambda: (b'', request)
        handler._handle_error = lambda error: {'error_status': error.status, 'detail': error.detail}
        with patch('app.main.client_ip', return_value='127.0.0.1'), patch('app.exams.audit'):
            return handler.do_POST()

    def test_old_start_contract_single_tab_has_no_event(self):
        self.prepare()
        result = self.start()
        self.assertTrue(result['ok'])
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)['latest_event_seq'], 0)

    def test_confirmed_start_is_idempotent_and_preserves_deadline(self):
        self.prepare()
        first = self.start('true')
        again = self.start('true')
        self.assertEqual(first['started_at'], again['started_at'])
        self.assertEqual(first['ends_at'], again['ends_at'])
        summary = exam_monitoring.attempt_summary(self.student, self.release)
        self.assertEqual(summary['latest_event_seq'], 1)
        self.assertEqual(summary['event_counters']['multiple_tabs_detected'], 1)
        self.assertNotIn('monitoring_precheck_pending', storage.read_json('assignments.json')[self.student])

    def test_password_teacher_start_assignment_and_metadata_validation(self):
        self.prepare(password=True)
        before = storage.read_json('assignments.json')
        self.assertEqual(self.start('true', 'wrong')['error_status'], 403)
        self.assertEqual(self.start('forged', 'secret')['error_status'], 400)
        self.settings['exam_state'] = 'distributed'
        storage.write_json('settings.json', self.settings)
        self.assertEqual(self.start('true', 'secret')['error_status'], 400)
        self.assertEqual(storage.read_json('assignments.json'), before)
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)['latest_event_seq'], 0)
        self.settings['exam_state'] = 'started'
        storage.write_json('settings.json', self.settings)
        storage.write_json('assignments.json', {})
        self.assertEqual(self.start('true', 'secret')['error_status'], 400)

    def test_failed_event_write_keeps_durable_marker_and_replay_is_exactly_once(self):
        self.prepare()
        with patch('app.exam_monitoring.record_event', side_effect=OSError('disk write')):
            self.assertTrue(self.start('true')['ok'])
        assignment = storage.read_json('assignments.json')[self.student]
        self.assertTrue(assignment['monitoring_precheck_pending'])
        self.assertTrue(assignment['started_at'])
        # The normal status path recovers after reload/reauth without restarting.
        status = self._handler('/api/student/status').do_GET()
        self.assertTrue(status['active_exam_attempt'])
        self.assertEqual(status['started_at'], assignment['started_at'])
        exam_monitoring.flush_start_precheck(self.student)
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)['latest_event_seq'], 1)

    def test_marker_clear_failure_does_not_duplicate_durable_event(self):
        self.prepare()
        with patch('app.exams.audit'):
            exams.start_exam(self.student, confirmed_multiple_tabs=True)
        def fail_marker_clear(name, value):
            if name == 'assignments.json':
                raise OSError('marker clear')
            storage.write_json(name, value)
        with patch('app.exam_monitoring.write_json', side_effect=fail_marker_clear):
            with self.assertRaises(OSError):
                exam_monitoring.flush_start_precheck(self.student)
        self.assertTrue(storage.read_json('assignments.json')[self.student]['monitoring_precheck_pending'])
        exam_monitoring.flush_start_precheck(self.student)
        self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)['latest_event_seq'], 1)

    def test_all_new_event_types_and_counters_are_idempotent(self):
        for index, event_type in enumerate(sorted(exam_monitoring.EVENT_TYPES), 1):
            handler = self._handler('/api/student/telemetry/event', {
                'release_id': self.release, 'event_id': 'phase3-' + event_type,
                'event_type': event_type,
            })
            self.assertTrue(handler.do_POST()['recorded'])
            self.assertFalse(handler.do_POST()['recorded'])
            self.assertEqual(exam_monitoring.attempt_summary(self.student, self.release)['latest_event_seq'], index)
        self.assertTrue(all(value == 1 for value in exam_monitoring.attempt_summary(self.student, self.release)['event_counters'].values()))


if __name__ == '__main__':
    unittest.main()
