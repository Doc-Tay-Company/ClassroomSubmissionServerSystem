// UI state regression tests for the Exam Code/ZIP selector.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

class Element {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = String(tag).toUpperCase();
    this.attrs = attrs;
    this.children = children.filter((child) => child !== null && child !== undefined && child !== false);
    this.listeners = attrs.on || {};
    this.dataset = {};
    this.className = attrs.class || '';
    this.type = attrs.type || '';
    this.name = attrs.name || '';
    this.value = attrs.value ?? (this.tagName === 'SELECT' ? (children.find((child) => child?.attrs?.selected)?.attrs?.value ?? children.find((child) => child?.tagName === 'option')?.attrs?.value ?? '') : '');
    this.checked = Boolean(attrs.checked);
    this.disabled = Boolean(attrs.disabled);
    this.style = {};
    this._textContent = '';
    this.classList = { add() {}, remove() {}, contains: () => false };
  }
  append(...items) { this.children.push(...items.filter((item) => item != null)); }
  replaceChildren(...items) { this.children = items.filter((item) => item != null); }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  async dispatch(type) {
    const handler = this.listeners[type];
    if (handler) await handler({ type, target: this, stopPropagation() {} });
  }
  get textContent() { return this._textContent + this.children.map((child) => child instanceof Element ? child.textContent : String(child)).join(''); }
  set textContent(value) { this._textContent = String(value); this.children = []; }
  querySelectorAll(selector) {
    const matches = (element) => {
      if (!(element instanceof Element)) return false;
      if (selector === '[data-guard]') return Boolean(element.dataset.guard);
      if (selector.startsWith('.')) return element.className.split(/\s+/).includes(selector.slice(1));
      const dataField = selector.match(/^\[data-field="([^"]+)"\]$/);
      if (dataField) return element.dataset.field === dataField[1];
      const radio = selector.match(/^input\[name="([^"]+)"\]\[value="([^"]*)"\]$/);
      if (radio) return element.tagName === 'INPUT' && element.name === radio[1] && element.value === radio[2];
      if (selector === 'button') return element.tagName === 'BUTTON';
      return false;
    };
    const result = [];
    const visit = (node) => {
      for (const child of node.children || []) if (child instanceof Element) {
        if (matches(child)) result.push(child);
        visit(child);
      }
    };
    visit(this);
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  findAll(predicate) {
    const result = [];
    const visit = (node) => {
      for (const child of node.children || []) if (child instanceof Element) {
        if (predicate(child)) result.push(child);
        visit(child);
      }
    };
    visit(this);
    return result;
  }
  focus() {}
  scrollIntoView() {}
}

function h(tag, attrs, ...children) {
  const node = new Element(tag, attrs || {}, children.flat(Infinity));
  if (attrs) for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith('data-')) node.dataset[key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
  }
  return node;
}

const config = (overrides = {}) => ({
  duration_minutes: 75, submission_policy: 'configurable', max_submissions: 2,
  overwrite_previous: true, accepted_submission_extensions: ['.zip'],
  password_enabled: false, has_password: false, participants: ['student1'], ...overrides,
});
const codeItem = () => ({
  item_id: 'code-item', type: 'code', distribution: { mode: 'common', paper_versions: [{ paper_id: 'p1', paper_version_id: 'p1:v1' }] },
  question_ids: [], show_final_score_immediately: false, allow_pretest: true, max_pretest_runs: 20, pretest_cooldown_seconds: 2,
});
const zipItem = () => ({
  item_id: 'zip-item', type: 'zip', distribution_mode: 'selected', distribution_config: { exam_files: ['exam.zip'] },
});
const examRecord = (items, extra = {}) => ({
  id: 'exam-1', title: 'Existing Exam', tag: '', status: 'draft', config: config(), ...extra, items,
});

async function openEditor(existing = null, options = {}) {
  const root = new Element('main');
  root.dataset.examId = existing ? existing.id : '';
  const calls = [];
  const toasts = [];
  let created = existing;
  const request = async (url, requestOptions = {}) => {
    calls.push({ url, options: requestOptions });
    if (!requestOptions.method) {
      if (url === '/api/admin/accounts') return { students: [{ student_id: 'student1', full_name: 'Student One' }] };
      if (url === '/api/admin/exams') return { exams: [] };
      if (url === '/api/admin/questions') return { questions: [] };
      if (url === '/api/admin/papers') return { papers: options.papers || [] };
      if (url === '/api/admin/exam-records') return { exams: [] };
      if (url === `/api/admin/exam-records/${existing.id}`) return { exam: existing };
      throw new Error(`Unexpected GET ${url}`);
    }
    const payload = JSON.parse(requestOptions.body || '{}');
    const savedConfig = { ...config(), ...payload.config };
    if (typeof savedConfig.accepted_submission_extensions === 'string') {
      savedConfig.accepted_submission_extensions = savedConfig.accepted_submission_extensions.split(/[,\s]+/).filter(Boolean);
    }
    if (url === '/api/admin/exam-records') {
      created = examRecord(payload.items, { ...created, title: payload.title, config: savedConfig });
    } else if (url.endsWith('/update')) {
      if (options.rejectUpdate) throw new Error('stale revision');
      created = examRecord(payload.items, { ...created, title: payload.title, config: savedConfig, revision: (created.revision || 1) + 1 });
    }
    return { exam: created };
  };
  const document = { getElementById: (id) => id === 'exam-root' ? root : null, body: new Element('body') };
  const window = {
    cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message, setNotice() {} },
    cssRequest: request, cssToast: (message) => toasts.push(message), addEventListener() {},
  };
  const location = { search: existing ? `?section=exam&id=${existing.id}${options.editMode ? '&mode=edit' : ''}` : '?section=exam', href: '' };
  const context = {
    window, document, location, URLSearchParams, history: { replaceState() {} },
    setTimeout: () => 1, clearTimeout() {}, console, Set, Map, Date, Number, String, Boolean, Math, Promise,
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/exams.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  return {
    root, calls, toasts, get saved() { return created; },
    radio(value) { return root.querySelector(`input[name="exam-item-type"][value="${value}"]`); },
    select: async (value) => { const radio = root.querySelector(`input[name="exam-item-type"][value="${value}"]`); assert(radio, `missing radio ${value}`); radio.checked = true; await radio.dispatch('change'); },
    async fillBasics() {
      const title = root.findAll((node) => node.tagName === 'INPUT' && String(node.attrs.placeholder || '').startsWith('Ví dụ:'))[0];
      assert(title, 'missing exam title input'); title.value = 'New Exam'; await title.dispatch('input');
      const duration = root.findAll((node) => node.tagName === 'INPUT' && node.attrs.min === 1 && node.attrs.max === 1440)[0];
      assert(duration, 'missing duration input'); duration.value = '75'; await duration.dispatch('input');
      const participant = root.findAll((node) => node.className.split(/\s+/).includes('student-option'))[0]?.children[0];
      assert(participant, 'missing participant checkbox'); participant.checked = true; await participant.dispatch('change');
    },
    async save() { const button = root.querySelectorAll('button').find((item) => item.textContent.includes('Lưu nháp')); assert(button, 'missing Save Draft button'); await button.dispatch('click'); },
    paperChoice(id) { return root.findAll((node) => node.tagName === 'LABEL' && node.className.includes('paper-choice')).find((label) => label.children[0]?.attrs.type === 'checkbox' && label.textContent.includes(id))?.children[0]; },
    paperMode() { return root.findAll((node) => node.tagName === 'SELECT' && node.children.some((child) => child.attrs?.value === 'common') && node.children.some((child) => child.attrs?.value === 'random'))[0] || null; },
    paperChoices() { return root.findAll((node) => node.tagName === 'LABEL' && node.className.includes('paper-choice')); },
    async saveChanges() { const button = root.querySelectorAll('button').find((item) => item.textContent.includes('Lưu thay đổi')); assert(button, 'missing Save Changes button'); await button.dispatch('click'); },
    panelText() { return root.textContent; },
  };
}

async function main() {
  const empty = await openEditor();
  assert(empty.radio('code') && empty.radio('zip') && empty.radio(''), 'selector remains visible in empty state');
  assert.strictEqual(empty.radio('code').checked, false);
  assert(!empty.panelText().includes('Chế độ phân phối Paper'));
  assert(!empty.panelText().includes('Đề dùng để phân phối'));
  const publishButton = empty.root.querySelectorAll('button').find((item) => item.textContent.includes('Phát đề'));
  assert(publishButton, 'missing Publish button'); await publishButton.dispatch('click');
  assert(empty.toasts.some((message) => message.includes('chọn Bài code hoặc Bài nộp file')), 'missing clear validation for empty type');
  await empty.select('code');
  assert(empty.panelText().includes('Chế độ phân phối Paper'), 'selecting Code renders Code configuration');
  assert(!empty.panelText().includes('Đề dùng để phân phối'), 'Code selection hides ZIP configuration only');
  await empty.select('zip');
  assert(empty.panelText().includes('Đề dùng để phân phối'), 'switching to ZIP renders ZIP configuration');
  assert(!empty.panelText().includes('Chế độ phân phối Paper'), 'ZIP selection hides Code configuration only');
  await empty.select('code');
  assert(empty.panelText().includes('Chế độ phân phối Paper'), 'switching back to Code works');
  await empty.fillBasics();
  await empty.save();
  const createdPayload = JSON.parse(empty.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.strictEqual(createdPayload.items.length, 1);
  assert.strictEqual(createdPayload.items[0].type, 'code');
  assert.strictEqual(createdPayload.config.duration_minutes, 75);
  assert.deepStrictEqual(createdPayload.config.participants, ['student1']);

  const malformed = await openEditor(examRecord([codeItem(), zipItem()]));
  assert(malformed.radio('code') && malformed.radio('zip'), 'selector remains visible for malformed dual-item draft');
  assert.strictEqual(malformed.radio('').disabled, true, 'malformed draft cannot be cleared without choosing a recovery type');
  assert(!malformed.radio('code').checked && !malformed.radio('zip').checked, 'malformed draft does not choose a type implicitly');
  assert(malformed.panelText().includes('Bản nháp cũ có lựa chọn loại bài không hợp lệ.'));
  assert(!malformed.panelText().includes('Chế độ phân phối Paper') && !malformed.panelText().includes('Đề dùng để phân phối'));
  await malformed.select('zip');
  await malformed.save();
  const repairedPayload = JSON.parse(malformed.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.strictEqual(repairedPayload.items.length, 1);
  assert.strictEqual(repairedPayload.items[0].type, 'zip');
  assert.strictEqual(repairedPayload.title, 'Existing Exam');
  assert.strictEqual(repairedPayload.config.duration_minutes, 75);
  assert.deepStrictEqual(repairedPayload.config.participants, ['student1']);

  const malformedCode = await openEditor(examRecord([zipItem(), codeItem()]));
  assert(!malformedCode.radio('code').checked && !malformedCode.radio('zip').checked);
  await malformedCode.select('code');
  await malformedCode.save();
  const repairedCodePayload = JSON.parse(malformedCode.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.strictEqual(repairedCodePayload.items.length, 1);
  assert.strictEqual(repairedCodePayload.items[0].type, 'code');

  for (const item of [codeItem(), zipItem()]) {
    const existing = await openEditor(examRecord([item]));
    assert.strictEqual(existing.radio(item.type).checked, true, `${item.type} type hydrates on edit/reload`);
    await existing.save();
    const payload = JSON.parse(existing.calls.filter((call) => call.options.method).at(-1).options.body);
    assert.strictEqual(payload.items.length, 1);
    assert.strictEqual(payload.items[0].type, item.type);
    const reloaded = await openEditor(existing.saved);
    assert(reloaded.radio(item.type), `${item.type} selector missing after reload; response=${JSON.stringify(existing.saved)}; calls=${JSON.stringify(reloaded.calls)}; text=${reloaded.panelText()}`);
    assert.strictEqual(reloaded.radio(item.type).checked, true, `${item.type} remains selected after reload`);
  }

  const papers = [
    { id: 'paper-a', title: 'Paper A', schema_version: 2, status: 'published', question_count: 1 },
    { id: 'paper-b', title: 'Paper B', schema_version: 2, status: 'published', question_count: 1 },
  ];
  const independentCode = {
    item_id: 'independent-code', type: 'code',
    distribution: { mode: 'common', paper_versions: [{ paper_id: 'paper-a' }] },
    question_ids: [], show_final_score_immediately: false, allow_pretest: true,
    max_pretest_runs: 20, pretest_cooldown_seconds: 2,
  };
  const randomEditor = await openEditor(null, { papers });
  await randomEditor.select('code');
  assert.strictEqual(randomEditor.paperMode().value, 'common', 'Code Paper distribution defaults to COMMON');
  randomEditor.paperMode().value = 'random';
  await randomEditor.paperMode().dispatch('change');
  assert.strictEqual(randomEditor.paperMode().value, 'random', 'RANDOM mode survives rerender');
  for (const title of ['Paper A', 'Paper B']) {
    const choice = randomEditor.paperChoices().find((label) => label.textContent.includes(title));
    assert(choice, 'RANDOM pool includes ' + title);
    choice.children[0].checked = true;
    await choice.children[0].dispatch('change');
  }
  await randomEditor.fillBasics();
  await randomEditor.save();
  const randomPayload = JSON.parse(randomEditor.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.strictEqual(randomPayload.items[0].distribution.mode, 'random');
  assert.deepStrictEqual(randomPayload.items[0].distribution.paper_versions, [{ paper_id: 'paper-a' }, { paper_id: 'paper-b' }]);
  const reopenedRandom = await openEditor(randomEditor.saved, { papers, editMode: true });
  assert.strictEqual(reopenedRandom.paperMode().value, 'random', 'RANDOM configuration hydrates after reopening');
  assert.strictEqual(reopenedRandom.paperChoices().filter((label) => label.children[0].checked).length, 2, 'saved RANDOM pool hydrates');
  reopenedRandom.paperMode().value = 'common';
  await reopenedRandom.paperMode().dispatch('change');
  assert.strictEqual(reopenedRandom.paperMode().value, 'common');
  assert.strictEqual(reopenedRandom.paperChoices().filter((label) => label.children[0].checked).length, 1, 'COMMON retains one Paper');
  await reopenedRandom.save();
  const commonPayload = JSON.parse(reopenedRandom.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.strictEqual(commonPayload.items[0].distribution.mode, 'common');
  assert.strictEqual(commonPayload.items[0].distribution.paper_versions.length, 1);

  const draftSelection = await openEditor(null, { papers });
  await draftSelection.select('code');
  const draftPaper = draftSelection.paperChoice('Paper B');
  assert(draftPaper && !draftPaper.disabled, `Draft permits selecting an independent Published Paper; ${draftSelection.panelText()}`);
  draftPaper.checked = true;
  await draftPaper.dispatch('change');
  await draftSelection.fillBasics();
  await draftSelection.save();
  const draftPayload = JSON.parse(draftSelection.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.deepStrictEqual(draftPayload.items[0].distribution.paper_versions, [{ paper_id: 'paper-b' }]);

  const published = examRecord([independentCode], { status: 'distributed', revision: 7, release: { release_id: 'release-1', applied: true } });
  const publishedEdit = await openEditor(published, { papers, editMode: true });
  const publishedPaper = publishedEdit.paperChoice('Paper B');
  assert(publishedPaper && !publishedPaper.disabled, 'Published but not Started permits selection changes even when preparatory state is applied');
  publishedPaper.checked = true;
  await publishedPaper.dispatch('change');
  await publishedEdit.saveChanges();
  const publishedPayload = JSON.parse(publishedEdit.calls.filter((call) => call.options.method).at(-1).options.body);
  assert.deepStrictEqual(publishedPayload.items[0].distribution.paper_versions, [{ paper_id: 'paper-b' }]);
  assert.strictEqual(publishedPayload.expected_revision, 7, 'selection save retains optimistic concurrency');

  const started = await openEditor(examRecord([independentCode], { status: 'started', revision: 8 }), { papers, editMode: true });
  const startedPaper = started.paperChoice('Paper B');
  assert(startedPaper && startedPaper.disabled, 'Started Exam keeps Paper controls locked');
  assert(!started.root.querySelectorAll('button').some((item) => item.textContent.includes('Lưu thay đổi')), 'Started Exam has no Save Changes action');

  console.log('PASS Draft and Published Paper selection editing; Started Exam remains locked');
  console.log('PASS Exam Code/ZIP selector UI state regressions');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
