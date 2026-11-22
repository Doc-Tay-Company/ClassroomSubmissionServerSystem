const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const tick = () => new Promise((resolve) => setImmediate(resolve));

function setup() {
  let resetCount = 0;
  const nodes = new Map();
  const makeNode = (id) => {
    if (!nodes.has(id)) nodes.set(id, {
      id, dataset: {}, textContent: '', innerHTML: '', hidden: false, disabled: false,
      files: [], handlers: {}, classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(type, fn) { this.handlers[type] = fn; },
      querySelector() { return button; },
      querySelectorAll() { return []; },
      reset() { resetCount++; },
    });
    return nodes.get(id);
  };
  const button = { disabled: false };
  const form = makeNode('submission-form');
  makeNode('submission-result');
  makeNode('zip-submission-allowance');
  form.reset = () => { resetCount++; };
  form.querySelector = () => button;
  const fileInput = makeNode('submission-file');
  fileInput.files = [{ name: 'answer.zip' }];
  const panel = makeNode('student-panel');
  panel.dataset = { homeView: 'false', examState: 'started', published: '', assigned: '1', assignmentRelease: 'rel', assignmentStatus: 'submitted', assignmentStartedAt: 'start' };
  let uploadResult = { ok: true, submission: { filename: 's1.zip', size_bytes: 123 }, zip_submission: { eligible: true, count: 1, limit: 2, remaining_seconds: 300 } };
  let status = { completion: { finalized: false }, active_exam_attempt: false, practice_locked: true,
    exam_file: 'exam.zip', status: 'submitted', release_id: 'rel', remaining_seconds: 300,
    server_time: new Date().toISOString(), exam_state: 'started', assigned: true, started: true, notifications: [] };
  let navigations = 0;
  const window = {
    addEventListener() {}, setInterval() { return 1; }, setTimeout() { return 1; }, clearTimeout() {},
    cssToast() {}, cssEscape: (x) => String(x),
    cssRequest: async (url) => {
      if (url === '/api/student/status') return status;
      if (url === '/api/student/submit') return uploadResult;
      throw new Error(`Unexpected request ${url}`);
    },
    createExamTelemetry: () => ({ setActive() {}, pause() {}, sendSnapshot: async () => {}, onVisibilityChange() {}, onFocus() {}, onBlur() {}, recordEvent() {} }),
    createExamEntry: () => ({ setStatus() {} }),
    location: { assign() { navigations++; } },
  };
  const document = {
    visibilityState: 'visible', hasFocus: () => true, fullscreenElement: null,
    querySelectorAll: () => [], getElementById: (id) => nodes.get(id) || null,
    addEventListener() {},
  };
  class FormDataMock { append() {} }
  vm.runInNewContext(fs.readFileSync('static/js/student.js', 'utf8'), {
    window, document, navigator: { userAgent: 'test' }, localStorage: { getItem: () => null, setItem() {} },
    FormData: FormDataMock, URLSearchParams, setInterval() { return 1; }, console, Date, Math, String, Number,
  });
  return { nodes, form, button, setUploadResult(value) { uploadResult = value; }, navigations: () => navigations, resetCount: () => resetCount, tick };
}

(async () => {
  const app = setup();
  await tick();
  await app.form.handlers.submit({ preventDefault() {} });
  assert.equal(app.navigations(), 0, 'upload 1/2 keeps the Student in the ZIP workspace');
  assert(app.nodes.get('submission-result').textContent.includes('1/2'));
  assert(app.nodes.get('zip-submission-allowance').textContent.includes('1/2'));

  app.setUploadResult({ ok: true, submission: { filename: 's2.zip', size_bytes: 123 }, zip_submission: { eligible: false, reason: 'quota_exhausted', count: 2, limit: 2 } });
  await app.form.handlers.submit({ preventDefault() {} });
  assert.equal(app.navigations(), 1, 'quota exhaustion ends the Student workspace');
  console.log('PASS ZIP Student UI: 1/2 stays in workspace; 2/2 completes');
})().catch((error) => { console.error(error); process.exitCode = 1; });
