"""Deadline/result contracts use temporary storage, never operational records."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import code_exams as ce, exam_completion as completion, storage


def execution():
    return {'verdict': 'AC', 'score': 10, 'total_points': 10, 'duration_ms': 1,
            'tests': [dict(id=key, verdict='AC', passed=True, points=points,
                           points_earned=points, is_visible=visible,
                           expected_stdout=text, actual_stdout=text, stderr='', duration_ms=1)
                      for key, points, visible, text in [('visible', 8, True, 'ok'), ('hidden', 2, False, 'PRIVATE-TEST')]]}


class ExamCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='exam-completion-')
        self.addCleanup(self.temp.cleanup)
        self.data = patch.object(storage, 'DATA_DIR', Path(self.temp.name))
        self.data.start()
        self.addCleanup(self.data.stop)
        now = datetime.now(timezone.utc)
        self.assignment = {'release_id': 'release', 'code_exam_id': 'exam', 'status': 'in_progress',
                           'started_at': now.isoformat(), 'ends_at': (now + timedelta(minutes=10)).isoformat(),
                           'exam_file': None}
        self.exam = {'id': 'exam', 'title': 'Official Exam', 'release_id': 'release', 'status': 'started',
                     'submission_policy': 'once', 'max_submissions': 1, 'show_final_score_immediately': True,
                     'questions': [{'question_id': 'q', 'title': 'Question', 'language': 'python',
                                    'grading_mode': 'stdio', 'target_file': 'main.py', 'total_points': 10,
                                    'tests': [dict(id=key, points=points, is_visible=visible, stdin='',
                                                   expected_stdout=text, compare_mode='exact')
                                              for key, points, visible, text in [('visible', 8, True, 'ok'), ('hidden', 2, False, 'PRIVATE-TEST')]]}]}
        for name, value in {'settings.json': {'exam_state': 'started', 'exam_released': True, 'exam_release_id': 'release'},
                            'assignments.json': {'s': self.assignment}, 'code_exams.json': {'exam': self.exam},
                            'code_submissions.json': {}, 'code_attempts.json': {'attempts': {}}}.items():
            storage.write_json(name, value)
        self.runner = patch.object(ce, 'execute_question', return_value=execution()).start()
        self.addCleanup(patch.stopall)

    def change_assignment(self, **fields):
        storage.update_json('assignments.json', lambda data: data['s'].update(fields))

    def expire(self):
        self.change_assignment(ends_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())

    def test_manual_finalization_and_retry_grade_only_once(self):
        first = completion.finalize_code_attempt('s', {'q': 'print("latest")'})
        second = completion.finalize_code_attempt('s', {'q': 'print("different")'})
        self.assertTrue(first['finalized'])
        self.assertEqual(first['exam_score'], 10)
        self.assertTrue(second['finalized'])
        self.assertEqual(self.runner.call_count, 1)
        self.assertEqual(len(storage.read_json('code_submissions.json')['s']), 1)
        self.assertEqual(storage.read_json('code_submissions.json')['s'][0]['source_code'], 'print("latest")')

    def test_deadline_preserves_latest_checkpoint_not_late_payload(self):
        completion.save_code_drafts('s', 'exam', {'q': 'old'})
        completion.save_code_drafts('s', 'exam', {'q': 'latest received in time'})
        self.expire()
        result = completion.finalize_code_attempt('s', {'q': 'late replacement'}, automatic=True)
        self.assertTrue(result['finalized'])
        self.assertEqual(result['reason'], 'deadline')
        self.assertEqual(self.runner.call_args.args[1], 'latest received in time')
        with self.assertRaises(ce.CodeExamError):
            completion.save_code_drafts('s', 'exam', {'q': 'late checkpoint'})

    def test_server_sweep_without_browser_is_idempotent(self):
        completion.save_code_drafts('s', 'exam', {'q': 'saved source'})
        self.expire()
        completion.finalize_due_attempts()
        completion.finalize_due_attempts()
        self.assertTrue(completion.completion_state('s')['finalized'])
        self.assertEqual(self.runner.call_count, 1)

    def test_automatic_before_deadline_does_not_finalize(self):
        result = completion.finalize_code_attempt('s', automatic=True)
        self.assertFalse(result['finalized'])
        self.assertFalse(self.runner.called)
        self.assertNotIn('finalized_at', storage.read_json('assignments.json')['s'])

    def test_all_answers_are_admitted_before_grading_crosses_deadline(self):
        second = deepcopy(self.exam['questions'][0])
        second['question_id'] = 'q2'
        self.exam['questions'].append(second)
        storage.write_json('code_exams.json', {'exam': self.exam})
        def grade_then_expire(*args):
            self.expire()
            return execution()
        self.runner.side_effect = grade_then_expire
        result = completion.finalize_code_attempt('s', {'q': 'first source', 'q2': 'second source'})
        self.assertTrue(result['all_questions_submitted'])
        self.assertEqual(result['exam_score'], 20)
        self.assertEqual(self.runner.call_count, 2)

    def test_invalid_request_has_no_partial_submission(self):
        before = deepcopy(storage.read_json('assignments.json'))
        for answers in ({'wrong': 'source'}, {}, {'q': 123}):
            with self.assertRaises(ce.CodeExamError):
                completion.finalize_code_attempt('s', answers)
            self.assertEqual(storage.read_json('code_submissions.json'), {})
            self.assertEqual(storage.read_json('assignments.json'), before)
        with self.assertRaises(ce.CodeExamError):
            completion.finalize_code_attempt('s', {'q': 'source'}, expected_exam_id='other')

    def test_result_is_owned_persistent_and_hidden_tests_remain_private(self):
        completion.finalize_code_attempt('s', {'q': '<script>student source</script>'})
        result = completion.student_results('s', 'exam')
        self.assertEqual(result['questions'][0]['source_code'], '<script>student source</script>')
        self.assertEqual([row['id'] for row in result['questions'][0]['submission']['results']], ['visible'])
        self.assertNotIn('PRIVATE-TEST', str(result))
        self.assertEqual(completion.student_results('s', 'exam'), result)
        with self.assertRaises(ce.CodeExamError) as error:
            completion.student_results('other-student', 'exam')
        self.assertEqual(error.exception.status, 404)

    def test_false_and_absent_policy_reject_results_even_after_teacher_end(self):
        completion.finalize_code_attempt('s', {'q': 'source'})
        for policy in (False, None):
            self.exam['show_final_score_immediately'] = policy
            self.exam['status'] = 'ended'
            storage.write_json('code_exams.json', {'exam': self.exam})
            with self.assertRaises(ce.CodeExamError) as error:
                completion.student_results('s', 'exam')
            self.assertEqual(error.exception.status, 403)
            self.assertFalse(completion.completion_state('s')['result_available'])
            self.assertNotIn('score', ce.get_student_submission('s', 'q'))

    def test_teacher_end_and_force_finalize_saved_work(self):
        for reason in ('teacher_end', 'forced'):
            with self.subTest(reason=reason):
                storage.write_json('code_attempts.json', {'attempts': {}})
                storage.write_json('code_submissions.json', {})
                storage.write_json('assignments.json', {'s': self.assignment})
                completion.save_code_drafts('s', 'exam', {'q': 'checkpoint'})
                if reason == 'forced': self.change_assignment(forced_submit=True, status='submitted')
                else: self.change_assignment(status='ended')
                completion.finalize_due_attempts()
                self.assertEqual(completion.completion_state('s')['reason'], reason)

    def test_unanswered_is_not_fabricated(self):
        self.expire()
        completion.finalize_due_attempts()
        result = completion.student_results('s', 'exam')
        self.assertEqual(result['questions'][0]['grading_status'], 'unanswered')
        self.assertEqual(result['exam_score'], 0)
        self.assertFalse(self.runner.called)
        self.assertFalse(result['grading_pending'])

    def test_concurrent_manual_and_deadline_finalize_reserve_once_and_show_pending(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def slow_execution(*args):
            entered.set()
            if not release.wait(5): raise RuntimeError('test synchronization timed out')
            return execution()
        self.runner.side_effect = slow_execution
        def submit():
            try: completion.finalize_code_attempt('s', {'q': 'accepted source'})
            except Exception as exc: errors.append(exc)
        worker = threading.Thread(target=submit)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.expire()
            duplicate = completion.finalize_code_attempt('s', automatic=True)
            self.assertTrue(duplicate['finalized'])
            self.assertTrue(duplicate['grading_pending'])
            self.assertTrue(completion.student_results('s', 'exam')['grading_pending'])
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(errors)
        self.assertEqual(self.runner.call_count, 1)

    def test_file_expiration_does_not_invent_uploaded_work(self):
        self.change_assignment(code_exam_id=None, exam_file='exam.zip')
        self.expire()
        completion.finalize_due_attempts()
        assignment = storage.read_json('assignments.json')['s']
        self.assertEqual(assignment['status'], 'expired')
        self.assertIn('finalized_at', assignment)
        self.assertEqual(storage.read_json('code_submissions.json'), {})

    def test_drafts_validate_types_and_identity_without_writes(self):
        for exam_id, answers in [('other', {'q': 'source'}), ('exam', {'q': 1}), ('exam', {'wrong': 'source'}),
                                 ('exam', {'q': '\ud800'}), ('exam', {'q': 'x' * (ce.MAX_SOURCE_BYTES + 1)})]:
            with self.assertRaises(ce.CodeExamError):
                completion.save_code_drafts('s', exam_id, answers)
            self.assertEqual(storage.read_json('code_attempts.json'), {'attempts': {}})


if __name__ == '__main__':
    unittest.main()
