"""Official attempt draft checkpoints and idempotent finalization.

Only work received while the server deadline is open is eligible. The deadline
sweep does not accept fresh answers from a late/disconnected client.
"""
from copy import deepcopy
from datetime import datetime, timezone
from . import code_exams as ce
from .storage import read_json, write_json, transaction, utc_now, audit


def _store():
    return deepcopy(read_json('code_attempts.json', {'attempts': {}}))


def _record(store, sid, exam):
    return store.setdefault('attempts', {}).setdefault(sid, {}).setdefault(exam['id'], {
        'exam_id': exam['id'], 'release_id': exam['release_id'], 'drafts': {},
    })


def _expired(assignment):
    try:
        end = datetime.fromisoformat(assignment['ends_at'])
        if end.tzinfo is None: end = end.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= end
    except (KeyError, TypeError, ValueError):
        return False


def _reason(assignment, settings):
    if assignment.get('forced_submit'): return 'forced'
    if assignment.get('status') == 'ended' or settings.get('exam_state') == 'ended': return 'teacher_end'
    if _expired(assignment): return 'deadline'
    return None


def save_code_drafts(sid, exam_id, answers):
    if not isinstance(answers, dict): raise ce.CodeExamError('answers must be an object', 422)
    with transaction():
        _, assignment, exam = ce._active_context(sid)
        if assignment.get('status') != 'in_progress' or exam['id'] != exam_id:
            raise ce.CodeExamError('The draft does not match an active attempt', 409)
        ids = {q['question_id'] for q in exam['questions']}
        for qid, source in answers.items():
            if qid not in ids: raise ce.CodeExamError('Question is not part of this exam', 400)
            try: valid_source = isinstance(source, str) and len(source.encode('utf-8')) <= ce.MAX_SOURCE_BYTES
            except UnicodeEncodeError: valid_source = False
            if not valid_source:
                raise ce.CodeExamError('Draft source must be a string of at most 1 MiB', 422)
        store = _store()
        record = _record(store, sid, exam)
        if record.get('finalized_at'): raise ce.CodeExamError('Attempt already finalized', 409)
        record['drafts'].update({qid: {'source_code': source, 'saved_at': utc_now()} for qid, source in answers.items()})
        write_json('code_attempts.json', store)
    return {'ok': True}


def completion_state(sid):
    assignment = read_json('assignments.json').get(sid, {})
    exam_id = assignment.get('code_exam_id')
    record = _store().get('attempts', {}).get(sid, {}).get(exam_id, {})
    finalized = bool(record.get('finalized_at') or assignment.get('finalized_at') or (assignment.get('status') == 'submitted' and not exam_id))
    exam = ce.get_code_exam(exam_id) if exam_id else None
    if not finalized and exam and assignment.get('status') == 'submitted':
        graded_ids = {item.get('question_id') for item in read_json('code_submissions.json').get(sid, [])
                      if item.get('exam_id') == exam_id and item.get('release_id') == exam.get('release_id') and item.get('status') == 'graded'}
        finalized = all(q['question_id'] in graded_ids for q in exam['questions'])
    return {'finalized': finalized, 'exam_id': exam_id, 'reason': record.get('reason') or assignment.get('finalization_reason'),
            'result_available': bool(finalized and exam and exam.get('show_final_score_immediately') is True)}


def _summary(sid, exam, record):
    records = read_json('code_submissions.json').get(sid, [])
    latest = {item['question_id']: item for item in records if item.get('exam_id') == exam['id'] and item.get('release_id') == exam['release_id']}
    all_graded = all(latest.get(q['question_id'], {}).get('status') == 'graded' for q in exam['questions'])
    reveal = exam.get('show_final_score_immediately') is True
    progress = []
    for q in exam['questions']:
        item = latest.get(q['question_id'])
        entry = {'question_id': q['question_id'], 'submitted': bool(item), 'status': item.get('status') if item else 'unanswered'}
        if reveal and item and item.get('status') == 'graded': entry.update(score=item.get('score'), total_points=item.get('total_points'))
        progress.append(entry)
    result = {'ok': True, 'finalized': True, 'all_questions_submitted': all_graded,
              'grading_pending': any(item.get('status') == 'grading' for item in latest.values()),
              'submissions': [], 'skipped_question_ids': list(latest), 'progress': progress,
              'exam_total_points': sum(float(q['total_points']) for q in exam['questions']),
              'finalized_at': record.get('finalized_at'), 'reason': record.get('reason')}
    if reveal and all(item.get('status') == 'graded' for item in latest.values()):
        # Same aggregation/missing-answer policy as code_exams._refresh_exam_score.
        total = ce.grade_exam([{'question_id': q['question_id'], 'score': latest.get(q['question_id'], {}).get('score', 0),
                               'total_points': q['total_points']} for q in exam['questions']])
        result['exam_score'] = total.score
    return result


def finalize_code_attempt(sid, answers=None, ip='server', *, expected_exam_id=None, automatic=False):
    """Reserve eligible answers once, then use the existing grading pipeline."""
    if not automatic and (not isinstance(answers, dict) or not answers):
        raise ce.CodeExamError('answers must be a non-empty object', 422)
    if not ce._RUN_SLOTS.acquire(blocking=False): raise ce.CodeExamError('Code execution capacity is busy; retry shortly', 429)
    try:
        with transaction():
            assignments = read_json('assignments.json')
            assignment = assignments.get(sid, {})
            exam = ce.get_code_exam(assignment.get('code_exam_id'))
            if not exam or not assignment.get('started_at') or exam.get('release_id') != assignment.get('release_id'):
                raise ce.CodeExamError('No matching started code attempt', 403)
            if expected_exam_id is not None and exam['id'] != expected_exam_id:
                raise ce.CodeExamError('Exam identity does not match the assignment', 409)
            store = _store()
            record = _record(store, sid, exam)
            if record.get('finalized_at'): return _summary(sid, exam, record)
            reason = _reason(assignment, read_json('settings.json'))
            if automatic and not reason: return {'ok': False, 'finalized': False}
            if not reason: ce._active_context(sid)
            ids = {q['question_id'] for q in exam['questions']}
            if answers is not None and (not isinstance(answers, dict) or set(answers) - ids):
                raise ce.CodeExamError('answers contains unknown questions', 400)
            if not automatic and not reason and ids - set(answers):
                raise ce.CodeExamError('answers must include every question in the exam', 400)
            # A late request can trigger recovery, but cannot replace eligible saved work.
            eligible = {qid: entry['source_code'] for qid, entry in record['drafts'].items()}
            if not reason and answers is not None: eligible.update(answers)
            existing = [item for item in read_json('code_submissions.json').get(sid, [])
                        if item.get('exam_id') == exam['id'] and item.get('release_id') == exam['release_id']]
            latest = {item['question_id']: item for item in existing}
            limit = 1 if exam.get('submission_policy') == 'once' else int(exam.get('max_submissions', 1))
            pending = []
            for q in exam['questions']:
                qid = q['question_id']
                if qid in latest and (latest[qid].get('status') in {'grading', 'graded'} or sum(i.get('question_id') == qid for i in existing) >= limit): continue
                source = eligible.get(qid, '')
                if reason and not source.strip(): continue
                source_hash = ce._validate_source(source)
                pending.append((q, source, source_hash))
            reserved = [(q, source, ce._reserve_submission(sid, exam, q, source, digest, ip)) for q, source, digest in pending]
            record.update(finalized_at=utc_now(), reason=reason or 'manual',
                          unanswered_question_ids=[qid for qid in ids if qid not in latest and not any(q['question_id'] == qid for q, _, _ in reserved)])
            write_json('code_attempts.json', store)
            assignment.update(status='submitted', finalized_at=record['finalized_at'], submitted_at=record['finalized_at'], finalization_reason=record['reason'])
            write_json('assignments.json', assignments)
        submissions = [ce.execute_reserved_submission(sid, exam, q, item, source, ip)[0] for q, source, item in reserved]
        result = _summary(sid, exam, record)
        result['submissions'] = submissions
        result['skipped_question_ids'] = list(latest)
        audit('code.submit_exam', sid, ip, {
            'exam_id': exam['id'], 'release_id': exam['release_id'], 'reason': record['reason'],
            'question_ids': [q['question_id'] for q in exam['questions']],
            'submission_ids': [item.get('submission_id') for item in submissions],
            'skipped_question_ids': list(latest), 'all_questions_submitted': result['all_questions_submitted'],
        })
        return result
    finally:
        ce._RUN_SLOTS.release()


def finalize_due_attempts(student_id=None):
    """Server-driven recovery also works when no Student browser is connected."""
    settings = read_json('settings.json')
    for sid, assignment in read_json('assignments.json').items():
        if student_id is not None and sid != student_id: continue
        if not assignment.get('started_at') or assignment.get('finalized_at') or not _reason(assignment, settings): continue
        if assignment.get('code_exam_id'):
            try: finalize_code_attempt(sid, automatic=True)
            except (ce.CodeExamError, OSError, RuntimeError): continue # Retry on the next bounded sweep.
        else:
            # A file never uploaded cannot be recovered or fabricated by the server.
            with transaction():
                assignments = read_json('assignments.json')
                current = assignments.get(sid, {})
                if current.get('release_id') != assignment.get('release_id') or current.get('finalized_at'): continue
                reason = _reason(current, read_json('settings.json'))
                if not reason: continue
                current.update(finalized_at=utc_now(), finalization_reason=reason)
                if current.get('status') != 'submitted': current['status'] = 'expired'
                write_json('assignments.json', assignments)


def student_results(sid, exam_id):
    exam = ce.get_code_exam(exam_id)
    if not exam or not exam.get('questions') or exam.get('show_final_score_immediately') is not True:
        raise ce.CodeExamError('Detailed results are not available', 403)
    record = _store().get('attempts', {}).get(sid, {}).get(exam_id)
    records = read_json('code_submissions.json').get(sid, [])
    if not record or not record.get('finalized_at'):
        graded = {item.get('question_id'): item for item in records if item.get('exam_id') == exam_id and item.get('release_id') == exam.get('release_id') and item.get('status') == 'graded'}
        if not all(q['question_id'] in graded for q in exam['questions']): raise ce.CodeExamError('No completed attempt belongs to this Student', 404)
        record = {'release_id': exam['release_id'], 'finalized_at': max(item.get('submitted_at', '') for item in graded.values()), 'reason': 'manual'}
    latest = {item['question_id']: item for item in records if item.get('exam_id') == exam_id and item.get('release_id') == record['release_id']}
    questions = []
    for q in exam['questions']:
        item = latest.get(q['question_id'])
        questions.append({'question_id': q['question_id'], 'title': q['title'], 'total_points': q['total_points'],
                          'source_code': item.get('source_code', '') if item else '',
                          'grading_status': item.get('status') if item else 'unanswered',
                          'submission': ce._public_submission(item, reveal_score=True) if item else None})
    return {**_summary(sid, exam, record), 'title': exam['title'], 'exam_id': exam_id, 'student_id': sid, 'questions': questions}
