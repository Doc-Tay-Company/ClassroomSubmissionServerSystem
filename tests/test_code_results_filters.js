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
  const exam = { id: 'exam-1', title: 'Exam One', status: 'ended', questions: [
    { question_id: 'q1', title: 'Question One' }, { question_id: 'q2', title: 'Question Two' },
  ] };
  const document = {
    getElementById: (id) => elements.get(id) || null,
    createElement: (tag) => new Element(tag),
    createTextNode: (text) => String(text),
  };
  const window = {
    cssRequest: async (url) => {
      requests.push(url);
      if (url === '/api/admin/code-exams') return { code_exams: [exam] };
      if (url === '/api/admin/accounts') return { students: [{ student_id: 'student-1', full_name: 'Student One' }] };
      if (url.startsWith('/api/admin/code-results?')) return { status: 'ended', submissions: [], matrix: [] };
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
  assert.deepStrictEqual(examSelect.options.map((option) => option.value), ['', 'exam-1'], 'exam options remain available');
  assert.deepStrictEqual(studentSelect.options.map((option) => option.value), ['', 'student-1'], 'student options remain available');

  examSelect.value = 'exam-1';
  await examSelect.dispatch('change');
  assert.strictEqual(clear.disabled, false, 'clear action is enabled once an exam is selected');
  assert.deepStrictEqual([...new URL(requests.at(-1), 'http://local').searchParams.entries()], [['exam_id', 'exam-1']],
    'unfiltered request keeps the existing exam_id parameter');

  studentSelect.value = 'student-1';
  questionSelect.value = 'q2';
  await studentSelect.dispatch('change');
  const filtered = [...new URL(requests.at(-1), 'http://local').searchParams.entries()];
  assert.deepStrictEqual(filtered, [['exam_id', 'exam-1'], ['student_id', 'student-1'], ['question_id', 'q2']],
    'combined filters preserve the existing server-side parameter names and values');

  await clear.dispatch('click');
  assert.strictEqual(studentSelect.value, '', 'clear resets the student filter');
  assert.strictEqual(questionSelect.value, '', 'clear resets the question filter');
  assert.strictEqual(examSelect.value, 'exam-1', 'clear retains the selected exam');
  assert.deepStrictEqual([...new URL(requests.at(-1), 'http://local').searchParams.entries()], [['exam_id', 'exam-1']],
    'clearing filters reloads the full result set for the selected exam');
  console.log('PASS Code Results filter options, API parameters, combined selection, and clear behavior');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
