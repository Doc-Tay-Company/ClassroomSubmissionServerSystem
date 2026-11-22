const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

class Element {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.listeners = {};
    this.value = '';
    this.disabled = false;
    this.className = '';
    this.classValues = new Set();
    this.classList = {
      add: (name) => { this.classValues.add(name); this.className = [...this.classValues].join(' '); },
      remove: (name) => { this.classValues.delete(name); this.className = [...this.classValues].join(' '); },
      toggle: (name, force) => force ? this.classList.add(name) : this.classList.remove(name),
      contains: (name) => this.classValues.has(name),
    };
  }
  get options() { return this.children.filter((child) => child instanceof Element && child.tagName === 'OPTION'); }
  get lastChild() { return this.children.at(-1); }
  append(...items) { this.children.push(...items.filter((item) => item !== null && item !== undefined)); }
  replaceChildren(...items) { this.children = items.filter((item) => item !== null && item !== undefined); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  async dispatch(type) { if (!this.disabled && this.listeners[type]) await this.listeners[type]({ type, target: this }); }
  setAttribute(name, value) { this[name] = value; }
  get textContent() { return this.children.map((child) => child instanceof Element ? child.textContent : String(child)).join(''); }
  set textContent(value) { this.children = [String(value)]; }
  querySelector(selector) {
    if (selector !== 'button') return null;
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      if (child.tagName === 'BUTTON') return child;
      const nested = child.querySelector(selector);
      if (nested) return nested;
    }
    return null;
  }
}

async function main() {
  const ids = ['code-results-view', 'cr-exam', 'cr-student', 'cr-question', 'cr-list', 'cr-detail',
    'cr-notice', 'cr-matrix', 'cr-refresh', 'cr-clear'];
  const elements = new Map(ids.map((id) => [id, new Element(id === 'cr-exam' || id === 'cr-student' || id === 'cr-question' ? 'select' : 'div')]));
  const requests = [];
  const operations = [];
  let includeSubmission = false;
  let participationStatus = null;
  const questions = [
    { question_id: 'q1', title: 'Question One' }, { question_id: 'q2', title: 'Question Two' },
  ];
  const exam = { id: 'exam-1', title: 'Main Exam One', status: 'ended' };
  const submission = { id: 'submission-1', exam_id: 'internal-runtime-id', student_id: 'student-1',
    question_id: 'q1', status: 'graded', score: 8, total_points: 10, attempt: 1, source_code: 'print(1)' };
  const document = {
    getElementById: (id) => elements.get(id) || null,
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => String(text),
  };
  const window = {
    confirm: () => true,
    cssRequest: async (url, options = {}) => {
      requests.push(url);
      if (options.method === 'POST') {
        operations.push({ url, body: JSON.parse(options.body) });
        if (url === '/api/admin/exam-results/exam-1/regrade') return { submission };
        if (url === '/api/admin/exam-results/exam-1/regrade-student') return { result: { regraded: [{ question_id: 'q1' }], failed: [], skipped: [] } };
        throw new Error(`Unexpected POST ${url}`);
      }
      if (url === '/api/admin/exam-results') return { exams: [exam] };
      if (url === '/api/admin/accounts') return { students: [{ student_id: 'student-1', full_name: 'Student One' }] };
      if (url.startsWith('/api/admin/exam-results/exam-1?')) return { status: 'ended', questions,
        submissions: includeSubmission ? [submission] : [],
        matrix: participationStatus ? [{ student_id: 'student-1', participation_status: participationStatus,
          total_score: includeSubmission ? 8 : null, total_points: includeSubmission ? 10 : null, cells: [
          { question_id: 'q1', status: 'graded', score: 8, total_points: 10, submission_id: 'submission-1', attempts: 1 },
          { question_id: 'q2', status: 'not_assigned' },
        ] }] : [] };
      throw new Error(`Unexpected API request: ${url}`);
    },
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Map, Promise, console };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-results.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));

  const examSelect = elements.get('cr-exam');
  const studentSelect = elements.get('cr-student');
  const questionSelect = elements.get('cr-question');
  const clear = elements.get('cr-clear');
  assert.deepStrictEqual(examSelect.options.map((option) => option.value), ['', 'exam-1'], 'options use main exam IDs');
  assert(examSelect.options[1].textContent.includes('Main Exam One'), 'options use main exam titles and lifecycle state');
  assert.deepStrictEqual(studentSelect.options.map((option) => option.value), ['', 'student-1'], 'student options remain available');

  examSelect.value = 'exam-1';
  await examSelect.dispatch('change');
  assert.strictEqual(clear.disabled, false, 'clear action is enabled once an exam is selected');
  assert.strictEqual(new URL(requests.at(-1), 'http://local').pathname, '/api/admin/exam-results/exam-1',
    'results are requested using the main exam ID');
  assert.deepStrictEqual(questionSelect.options.map((option) => option.value), ['', 'q1', 'q2'],
    'question options come from the selected release results, not the legacy exam list');

  studentSelect.value = 'student-1';
  questionSelect.value = 'q2';
  await studentSelect.dispatch('change');
  const filtered = [...new URL(requests.at(-1), 'http://local').searchParams.entries()];
  assert.deepStrictEqual(filtered, [['student_id', 'student-1'], ['question_id', 'q2']],
    'combined filters preserve the existing server-side parameter names and values');

  await clear.dispatch('click');
  assert.strictEqual(studentSelect.value, '', 'clear resets the student filter');
  assert.strictEqual(questionSelect.value, '', 'clear resets the question filter');
  assert.strictEqual(examSelect.value, 'exam-1', 'clear retains the selected exam');
  assert.deepStrictEqual([...new URL(requests.at(-1), 'http://local').searchParams.entries()], [],
    'clearing filters reloads the full result set for the selected exam');
  participationStatus = 'no_show';
  await elements.get('cr-refresh').dispatch('click');
  assert(elements.get('cr-matrix').textContent.includes('Không dự thi'), 'release roster shows students who never started');
  includeSubmission = true;
  participationStatus = 'submitted';
  await elements.get('cr-refresh').dispatch('click');
  assert(elements.get('cr-matrix').textContent.includes('Không được giao'), 'other Papers do not count as unsubmitted questions');
  assert(elements.get('cr-matrix').textContent.includes('Đã nộp'), 'submitted participation status is visible beside the Student');
  await elements.get('cr-list').querySelector('button').dispatch('click');
  const buttons = (node) => node.children.flatMap((child) => child instanceof Element
    ? [...(child.tagName === 'BUTTON' ? [child] : []), ...buttons(child)] : []);
  await buttons(elements.get('cr-detail')).find((button) => button.textContent === 'Chấm lại').dispatch('click');
  assert.deepStrictEqual(operations.at(-1), { url: '/api/admin/exam-results/exam-1/regrade',
    body: { submission_id: 'submission-1', use_latest_spec: false } }, 'single regrading uses the selected main exam ID');
  await buttons(elements.get('cr-matrix')).find((button) => button.textContent === 'Chấm lại cả đề').dispatch('click');
  assert.deepStrictEqual(operations.at(-1), { url: '/api/admin/exam-results/exam-1/regrade-student',
    body: { student_id: 'student-1', use_latest_spec: false } }, 'bulk regrading also uses the selected main exam ID');
  assert(!requests.some((url) => url.includes('/code-exams') || url.includes('/code-results')),
    'results no longer fetch legacy code exam options or legacy results');
  console.log('PASS Code Results filter options, API parameters, combined selection, and clear behavior');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
