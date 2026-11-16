// Exercises the real Paper builder module against a small simulated DOM.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

class Element {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = String(tag).toUpperCase();
    this.attrs = attrs;
    this.children = children.filter((child) => child !== null && child !== undefined && child !== false);
    this.listeners = {};
    this.dataset = {};
    this.className = attrs.class || '';
    this.type = attrs.type || '';
    this.value = attrs.value ?? '';
    this.checked = Boolean(attrs.checked);
    this.disabled = Boolean(attrs.disabled);
    this.indeterminate = Boolean(attrs.indeterminate);
    this.classValues = new Set(this.className.split(/\s+/).filter(Boolean));
    this.classList = {
      add: (value) => { this.classValues.add(value); this.className = [...this.classValues].join(' '); },
      remove: (value) => { this.classValues.delete(value); this.className = [...this.classValues].join(' '); },
      contains: (value) => this.classValues.has(value),
      toggle: (value, force) => { if (force) this.classList.add(value); else this.classList.remove(value); },
    };
    this._text = '';
    for (const [event, callback] of Object.entries(attrs.on || {})) this.listeners[event] = callback;
    for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-')) {
      this.dataset[key.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
    }
  }
  append(...items) { this.children.push(...items.filter((item) => item != null)); }
  replaceChildren(...items) { this.children = items.filter((item) => item != null); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  async dispatch(type) { if (this.listeners[type]) await this.listeners[type]({ type, target: this, stopPropagation() {} }); }
  get textContent() { return this._text + this.children.map((child) => child instanceof Element ? child.textContent : String(child)).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  querySelectorAll(selector) {
    const match = (node) => {
      if (!(node instanceof Element)) return false;
      if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
      if (selector.startsWith('#')) return node.attrs.id === selector.slice(1);
      if (selector === 'button') return node.tagName === 'BUTTON';
      if (selector === 'input') return node.tagName === 'INPUT';
      const field = selector.match(/^\[data-field="?([^\]"]+)"?\]$/);
      if (field) return node.dataset.field === field[1];
      const filter = selector.match(/^\[data-filter="?([^\]"]+)"?\]$/);
      if (filter) return node.dataset.filter === filter[1];
      const role = selector.match(/^\[data-role="?([^\]"]+)"?\]$/);
      if (role) return node.dataset.role === role[1];
      const tag = selector.match(/^\[data-filter-tag="?([^\]"]+)"?\]$/);
      if (tag) return node.dataset.filterTag === tag[1];
      return false;
    };
    const result = [];
    const visit = (node) => { for (const child of node.children || []) if (child instanceof Element) { if (match(child)) result.push(child); visit(child); } };
    visit(this);
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

function h(tag, attrs, ...children) { return new Element(tag, attrs || {}, children.flat(Infinity)); }

const bank = [
  { id: 'q1', title: 'Loops Intro', status: 'published', language: 'python', grading_mode: 'stdio', category: 'Math', difficulty: 'Easy', tags: ['loops', 'intro'], total_points: 10 },
  { id: 'q2', title: 'Loops Advanced', status: 'published', language: 'python', grading_mode: 'stdio', category: 'Math', difficulty: 'Hard', tags: ['loops', 'advanced'], total_points: 10 },
  { id: 'q3', title: 'Array Basics', status: 'published', language: 'java', grading_mode: 'stdio', category: 'Science', difficulty: 'Easy', tags: ['arrays'], total_points: 10 },
];

async function main() {
  const list = new Element('div');
  const editor = new Element('div');
  const notice = new Element('div');
  let onVisibilityChange = null;
  const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null,
    addEventListener: (type, callback) => { if (type === 'visibilitychange') onVisibilityChange = callback; }, hidden: false };
  let confirmNext = true;
  const confirmations = [];
  const requests = [];
  let storedPaper = null;
  let failNextPublish = false;
  let staleNextUpdate = false;
  let mismatchNextUpdate = false;
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const apiRequest = async (url, options = {}) => {
    requests.push({ url, method: options.method || 'GET' });
    if (url === '/api/admin/papers' && options.method !== 'POST') return { papers: storedPaper ? [clone(storedPaper)] : [] };
    if (url === '/api/admin/questions') return { questions: bank };
    const detail = url.match(/^\/api\/admin\/papers\/([^/?]+)$/);
    const paperId = detail?.[1];
    if (paperId && (options.method || 'GET') === 'GET') return { paper: clone(storedPaper) };
    if (paperId && options.method === 'PUT') {
      if (staleNextUpdate) {
        staleNextUpdate = false;
        const error = new Error('Paper has changed; reload before retrying'); error.status = 409; error.code = 'PAPER_CHANGED'; throw error;
      }
      const payload = JSON.parse(options.body);
      if (mismatchNextUpdate) {
        mismatchNextUpdate = false;
        const error = new Error('The number of selected questions must exactly match question_limit');
        error.status = 422; error.code = 'QUESTION_LIMIT_MISMATCH';
        error.body = { expected_count: payload.question_limit, actual_count: payload.question_ids.length };
        throw error;
      }
      storedPaper = { ...storedPaper, title: payload.title, metadata: payload.metadata, question_ids: payload.question_ids,
        question_limit: payload.question_limit, question_filters: payload.question_filters, revision: storedPaper.revision + 1,
        questions: storedPaper.status === 'published' ? payload.question_ids.map((question_id, order) => ({ question_id, order })) : [] };
      return { paper: clone(storedPaper) };
    }
    if (url === '/api/admin/papers/independent' && options.method === 'POST') {
      const payload = JSON.parse(options.body);
      storedPaper = { id: 'paper-lifecycle', schema_version: 2, title: payload.title, metadata: payload.metadata, status: 'draft', revision: 1,
        question_ids: payload.question_ids, question_limit: payload.question_limit, question_filters: payload.question_filters, questions: [] };
      return { paper: clone(storedPaper) };
    }
    const preview = url.match(/^\/api\/admin\/papers\/([^/?]+)\/preview(?:\?.*)?$/);
    if (preview) return { preview: { paper_id: preview[1], status: storedPaper.status,
      paper: { ...storedPaper, questions: (storedPaper.question_ids || []).map((id) => ({ ...bank.find((q) => q.id === id), question_id: id })) } } };
    const publish = url.match(/^\/api\/admin\/papers\/([^/?]+)\/publish$/);
    if (publish) {
      if (failNextPublish) { failNextPublish = false; const error = new Error('publish service unavailable'); error.status = 503; throw error; }
      storedPaper = { ...storedPaper, status: 'published', revision: storedPaper.revision + 1,
        questions: storedPaper.question_ids.map((question_id, order) => ({ question_id, order })) };
      return { paper: clone(storedPaper) };
    }
    throw new Error(`Unexpected request: ${options.method || 'GET'} ${url}`);
  };
  const window = {
    cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message, setNotice: (node, message) => { if (node) node.textContent = message; } },
    cssRequest: apiRequest,
    confirm: (message) => { confirmations.push(message); return confirmNext; },
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  await list.querySelectorAll('button').find((button) => button.textContent.includes('Tạo đề thi')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));

  assert(editor.querySelectorAll('button').find((button) => button.textContent.includes('Preview Draft')).disabled, 'new unsaved Paper explains that it must be saved before preview');
  assert(editor.textContent.includes('Lưu bản nháp để có Paper ID'), 'new Paper preview prerequisite is explained');

  const control = (name) => { const node = editor.querySelector(`[data-filter="${name}"]`); assert(node, `missing ${name} filter`); return node; };
  const available = () => editor.querySelector('.qb-picker-list').textContent;
  const selected = () => editor.querySelector('.qb-selected-list').textContent;
  assert(available().includes('Loops Intro') && available().includes('Array Basics'), 'all eligible questions initially visible');

  control('language').value = 'python'; await control('language').dispatch('change');
  assert(available().includes('Loops Intro') && !available().includes('Array Basics'), 'language filter works');
  control('category').value = 'math'; await control('category').dispatch('change');
  control('difficulty').value = 'easy'; await control('difficulty').dispatch('change');
  assert(available().includes('Loops Intro') && !available().includes('Loops Advanced'), 'filters combine with AND');

  const quantity = editor.querySelector('[data-field="question-limit"]');
  quantity.value = '-5'; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '1', 'negative Question Limit clamps to one on blur');
  quantity.value = '0'; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '1', 'zero Question Limit clamps to one on blur');
  quantity.value = '2'; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '2', 'valid Question Limit stays unchanged on blur');
  quantity.value = '25'; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '3', 'above-bank Question Limit clamps to total bank count');
  quantity.value = '1.5'; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '3', 'decimal Question Limit restores the last valid value');
  quantity.value = 'not-a-number'; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '3', 'non-numeric Question Limit restores the last valid value');
  quantity.value = ''; await quantity.dispatch('blur');
  assert.strictEqual(quantity.value, '', 'empty Question Limit remains empty for incomplete Draft editing');
  quantity.value = '2'; await quantity.dispatch('blur');
  const tag = editor.querySelector('[data-filter-tag="loops"]');
  tag.checked = true; await tag.dispatch('change');
  assert(available().includes('Loops Intro'), 'tag filter matches selected tag');
  const reset = editor.querySelectorAll('button').find((button) => button.textContent.includes('Xóa bộ lọc'));
  await reset.dispatch('click');
  assert(available().includes('Array Basics'), 'reset restores complete eligible pool');
  editor.querySelector('[data-filter-tag="loops"]').checked = true;
  await editor.querySelector('[data-filter-tag="loops"]').dispatch('change');
  editor.querySelector('[data-filter-tag="advanced"]').checked = true;
  await editor.querySelector('[data-filter-tag="advanced"]').dispatch('change');
  assert(available().includes('Loops Intro') && available().includes('Loops Advanced'), 'multiple tags combine with OR');
  await reset.dispatch('click');

  const search = editor.querySelector('[data-filter="search"]');
  search.value = 'no-such-question'; await search.dispatch('input');
  assert.strictEqual(quantity.max, '3', 'Question Limit maximum uses the full Question Bank, not the filtered pool');
  assert.strictEqual(quantity.disabled, false, 'a filter with no matches does not disable Question Limit');
  await reset.dispatch('click');

  quantity.value = '2'; await quantity.dispatch('input');
  const addButtons = () => editor.querySelectorAll('.qb-item').map((item) => item.querySelector('button'));
  for (const title of ['Loops Intro', 'Loops Advanced']) {
    const row = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes(title));
    await row.querySelector('button').dispatch('click');
  }
  assert(selected().indexOf('Loops Intro') < selected().indexOf('Loops Advanced'), 'selected order remains explicit');

  control('category').value = 'science'; await control('category').dispatch('change');
  assert(selected().includes('Loops Intro') && selected().includes('Loops Advanced'), 'filter changes retain selected questions');
  assert(selected().includes('Ngoài bộ lọc hiện tại'), 'selected questions outside filters are marked');
  assert.strictEqual(quantity.value, '2', 'filter changes do not alter the configured Question Limit');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'selected rows remain in their original order and are not dropped');

  control('category').value = ''; await control('category').dispatch('change');
  const randomButton = () => editor.querySelectorAll('button').find((button) => button.textContent.includes('ngẫu nhiên'));
  quantity.value = '1'; await quantity.dispatch('input');
  assert.strictEqual(randomButton().disabled, false, 'random is enabled when the full filtered pool can supply N');
  confirmNext = false;
  await randomButton().dispatch('click');
  assert(selected().includes('Loops Intro') && selected().includes('Loops Advanced'), 'cancelled replacement leaves explicit selection untouched');
  confirmNext = true;
  await randomButton().dispatch('click');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 1, 'random selects exactly configured N');
  assert(new Set(editor.querySelectorAll('.qb-selected').map((row) => row.textContent.match(/(?:Loops Intro|Loops Advanced|Array Basics)/)?.[0])).size === 1, 'random selection has unique question IDs');
  quantity.value = '2'; await quantity.dispatch('input');
  await randomButton().dispatch('click');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'random can explicitly replace with the configured larger N');

  const selectAll = () => editor.querySelectorAll('button').find((button) => button.textContent.includes('Chọn tất cả câu phù hợp'));
  control('category').value = 'math'; await control('category').dispatch('change');
  await selectAll().dispatch('click');
  assert.strictEqual(quantity.value, '2', 'select all leaves the configured Question Limit unchanged');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'select all covers all filtered matching questions');
  assert(editor.querySelector('[data-role="filtered-selection"]').checked, 'filtered group checkbox is checked when all matching IDs are selected');

  control('category').value = 'science'; await control('category').dispatch('change');
  quantity.value = '2'; await quantity.dispatch('input');
  assert.strictEqual(randomButton().disabled, true, 'random is disabled when fewer filtered candidates than N exist');
  await randomButton().dispatch('click');
  assert(editor.querySelector('[data-role="selection-status"]').textContent.includes('Không đủ câu phù hợp'), 'small-pool random attempt explains why it cannot run');

  control('category').value = ''; await control('category').dispatch('change');
  const group = editor.querySelector('[data-role="filtered-selection"]');
  control('category').value = 'science'; await control('category').dispatch('change');
  group.checked = true; await group.dispatch('change');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 3, 'group select preserves selected nonmatching questions and adds all matching questions');
  assert.strictEqual(group.checked, true, 'group checkbox is checked when all matching questions are selected');
  group.checked = false; await group.dispatch('change');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'group deselect removes matching questions only');
  assert(editor.querySelector('.qb-selected-list').textContent.includes('Ngoài bộ lọc hiện tại'), 'group deselect retains and labels nonmatching selections');
  control('category').value = ''; await control('category').dispatch('change');
  assert(group.indeterminate, 'group checkbox represents a partial selection across the full matching pool');
  assert(confirmations.length >= 1, 'replacing a different existing selection requires explicit confirmation');

  const title = editor.querySelector('#cp-title');
  title.value = 'Lifecycle Paper'; await title.dispatch('input');
  assert(editor.querySelector('[data-role="paper-lifecycle"]').textContent.includes('Unsaved Changes'), 'editor shows unsaved changes');
  const saveButton = () => editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Draft'));
  const saveCallsBefore = requests.filter((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').length;
  const firstSave = saveButton().dispatch('click');
  await saveButton().dispatch('click');
  await firstSave;
  assert.strictEqual(requests.filter((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').length - saveCallsBefore, 1, 'duplicate save clicks create only one Paper');
  assert.strictEqual(storedPaper.id, 'paper-lifecycle', 'saving a new Paper retains its server ID');
  assert(editor.querySelector('[data-role="paper-lifecycle"]').textContent.includes('draft revision 1'), 'saved state shows server revision');

  const publishButton = () => editor.querySelectorAll('button').find((button) => button.textContent.includes('Publish Paper'));
  const titleForPublish = editor.querySelector('#cp-title');
  titleForPublish.value = 'Published without preview'; await titleForPublish.dispatch('input');
  await publishButton().dispatch('click');
  assert.strictEqual(storedPaper.status, 'published', 'Paper publish changes status without creating a nested version');
  assert.strictEqual(requests.filter((request) => request.url.includes('/preview')).length, 0, 'publish path does not call preview');
  assert.strictEqual(storedPaper.id, 'paper-lifecycle', 'publishing preserves the Paper ID');
  assert(!('versions' in storedPaper) && !('current_version_id' in storedPaper), 'independent Paper has no nested version history');

  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Edit Paper')).dispatch('click');
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert(editor.querySelector('#cp-title'), `editor did not reopen: ${editor.textContent}`);
  const titleAfterEdit = editor.querySelector('#cp-title');
  titleAfterEdit.value = 'Saved in place'; await titleAfterEdit.dispatch('input');
  const publishedLimit = editor.querySelector('[data-field="question-limit"]');
  publishedLimit.value = '1'; await publishedLimit.dispatch('input');
  mismatchNextUpdate = true;
  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Changes')).dispatch('click');
  assert.strictEqual(editor.querySelector('#cp-title').value, 'Saved in place', 'rejected mismatch keeps unsaved title input');
  assert.strictEqual(publishedLimit.value, '1', 'rejected mismatch keeps unsaved Question Limit');
  assert(editor.querySelector('[data-role="paper-lifecycle"]').textContent.includes('1 expected, 2 selected'), 'count error reports expected and actual values');
  publishedLimit.value = '2'; await publishedLimit.dispatch('input');
  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Changes')).dispatch('click');
  assert.strictEqual(storedPaper.title, 'Saved in place', 'Save Changes updates the Published Paper in place');
  assert.strictEqual(storedPaper.id, 'paper-lifecycle', 'Save Changes preserves the Paper ID');
  assert.strictEqual(storedPaper.status, 'published', 'Save Changes preserves Published status');
  assert(!('versions' in storedPaper), 'Save Changes does not create a version');

  const staleTitle = editor.querySelector('#cp-title');
  staleTitle.value = 'Local edits retained after conflict'; await staleTitle.dispatch('input');
  staleNextUpdate = true;
  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Changes')).dispatch('click');
  assert.strictEqual(editor.querySelector('#cp-title').value, 'Local edits retained after conflict', 'stale revision keeps the local edits');
  assert(editor.querySelector('[data-role="reload-stale-paper"]'), 'stale revision offers an explicit reload action');
  await editor.querySelector('[data-role="reload-stale-paper"]').dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert(editor.querySelector('#cp-title'), 'stale reload returns to the Paper editor');

  storedPaper.warnings = [{ question_id: 'q1', warning: 'unavailable' }];
  await editor.querySelectorAll('button')[0].dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert(list.textContent.includes('1 question is unavailable'), 'Paper Card shows the unavailable-question count');
  storedPaper.warnings = ['q1', 'q2', 'q3'].map((question_id) => ({ question_id, warning: 'unavailable' }));
  onVisibilityChange();
  await new Promise((resolve) => setImmediate(resolve));
  assert(list.textContent.includes('3 questions are unavailable'), 'Paper Card refreshes warning count when the page becomes visible');

  bank.splice(0, bank.length);
  await list.querySelectorAll('button')[0].dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  const emptyBankQuantity = editor.querySelector('[data-field="question-limit"]');
  assert.strictEqual(emptyBankQuantity.value, '', 'empty Question Bank does not fabricate a Question Limit');
  assert.strictEqual(emptyBankQuantity.disabled, true, 'empty Question Bank prevents setting Question Limit');
  assert(editor.querySelector('[data-role="question-limit-status"]').textContent.includes('Question Bank is empty'), 'empty Question Bank explains why publishing is blocked');

  console.log('PASS independent Paper Draft/Published lifecycle, in-place edits, and stale conflict');
  await testCardSwitchRace();
}

async function testCardSwitchRace() {
  const list = new Element('div');
  const editor = new Element('div');
  const notice = new Element('div');
  const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null };
  const makePaper = (id, title, revision) => ({ id, title, metadata: {}, status: 'draft', revision,
    current_version_id: null, versions: {}, draft: { title, metadata: {}, question_ids: ['q1'], question_limit: 1, question_filters: {} } });
  const papers = new Map([['paper-a', makePaper('paper-a', 'Paper A', 2)], ['paper-b', makePaper('paper-b', 'Paper B', 7)]]);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const requests = [];
  const delayedAOpen = deferred();
  const delayedAOpenDetail = deferred();
  const delayedAPreview = deferred();
  const delayedASave = deferred();
  const delayedAPublish = deferred();
  let delayAOpen = true;
  let delayAOpenDetail = true;
  let delayAPreview = true;
  let delayASave = true;
  const apiRequest = async (url, options = {}) => {
    const method = options.method || 'GET';
    requests.push({ url, method, body: options.body });
    if (url === '/api/admin/papers' && method === 'GET') {
      return { papers: [...papers.values()].map((paper) => ({ ...clone(paper), question_count: 1, version_count: 0 })) };
    }
    if (url === '/api/admin/questions') return { questions: bank };
    const detail = url.match(/^\/api\/admin\/papers\/([^/?]+)$/);
    if (detail && method === 'GET') {
      if (detail[1] === 'paper-a' && delayAOpen) {
        delayAOpen = false;
        return delayedAOpen.promise;
      }
      if (detail[1] === 'paper-a' && delayAOpenDetail) {
        delayAOpenDetail = false;
        return delayedAOpenDetail.promise;
      }
      return { paper: clone(papers.get(detail[1])) };
    }
    if (detail && method === 'PUT') {
      const id = detail[1];
      const payload = JSON.parse(options.body);
      assert.strictEqual(payload.expected_revision, papers.get(id).revision, 'save sends the revision loaded for its Paper');
      const updated = { ...papers.get(id), title: payload.title, revision: papers.get(id).revision + 1,
        draft: { ...papers.get(id).draft, title: payload.title, question_ids: payload.question_ids,
          question_limit: payload.question_limit, question_filters: payload.question_filters } };
      if (id === 'paper-a' && delayASave) {
        delayASave = false;
        return delayedASave.promise.then(() => {
          papers.set(id, updated);
          return { paper: clone(updated) };
        });
      }
      papers.set(id, updated);
      return { paper: clone(updated) };
    }
    const preview = url.match(/^\/api\/admin\/papers\/([^/?]+)\/preview/);
    if (preview) {
      if (preview[1] === 'paper-a' && delayAPreview) {
        delayAPreview = false;
        return delayedAPreview.promise;
      }
      return { preview: { paper_id: preview[1], draft: { title: papers.get(preview[1]).title, questions: [] } } };
    }
    const publish = url.match(/^\/api\/admin\/papers\/([^/?]+)\/publish$/);
    if (publish && method === 'POST') {
      const paper = papers.get(publish[1]);
      const updated = { ...paper, status: 'published', revision: paper.revision + 1,
        current_version_id: `${paper.id}:v1`, versions: { [`${paper.id}:v1`]: { id: `${paper.id}:v1`, version: 1, title: paper.title, questions: [] } } };
      if (paper.id === 'paper-a') {
        return delayedAPublish.promise.then(() => {
          papers.set(paper.id, updated);
          return { paper: clone(updated) };
        });
      }
      papers.set(paper.id, updated);
      return { paper: clone(updated) };
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  };
  const window = {
    cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message, setNotice: () => {} },
    cssRequest: apiRequest,
    confirm: () => true,
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  await tick();
  const clickEdit = async (title) => {
    const buttonIndex = title === 'Paper A' ? 2 : 6;
    const target = list.querySelectorAll('button')[buttonIndex];
    assert(target, `missing edit action for ${title}; list=${list.textContent}`);
    return target.dispatch('click');
  };
  const clickOpen = (title) => list.querySelectorAll('button')[title === 'Paper A' ? 1 : 5].dispatch('click');
  const editTitle = () => editor.querySelector('#cp-title');
  const backToList = async () => {
    const button = editor.querySelectorAll('button')[0];
    assert(button, 'missing back-to-list control');
    await button.dispatch('click');
    await tick();
  };

  await clickEdit('Paper A');
  await clickEdit('Paper B');
  await tick();
  assert.strictEqual(editTitle().value, 'Paper B', 'later card becomes the active editor while A is pending');
  delayedAOpen.resolve({ paper: clone(papers.get('paper-a')) });
  await tick();
  assert.strictEqual(editTitle().value, 'Paper B', 'late A editor hydration cannot replace B');

  await backToList();
  clickOpen('Paper A');
  await clickOpen('Paper B');
  await tick();
  delayedAOpenDetail.resolve({ paper: clone(papers.get('paper-a')) });
  await tick();
  assert(editor.textContent.includes('Paper B'), 'late A detail load cannot replace B detail view');

  await backToList();
  await clickEdit('Paper A');
  await tick();
  const previewButton = editor.querySelectorAll('button').find((button) => button.textContent.includes('Preview Draft'));
  const pendingPreview = previewButton.dispatch('click');
  await backToList();
  await clickEdit('Paper B');
  await tick();
  delayedAPreview.resolve({ preview: { paper_id: 'paper-a', draft: { title: 'Paper A preview', questions: [] } } });
  await pendingPreview;
  assert.strictEqual(editTitle().value, 'Paper B', 'late A draft preview cannot replace B editor');

  await backToList();
  await clickEdit('Paper A');
  await tick();
  editTitle().value = 'Paper A saved in background';
  await editTitle().dispatch('input');
  const saveButton = editor.querySelectorAll('button')[1];
  const pendingSave = saveButton.dispatch('click');
  await tick();
  await backToList();
  await clickEdit('Paper B');
  await tick();
  delayedASave.resolve();
  await pendingSave;
  assert.strictEqual(editTitle().value, 'Paper B', 'late A save completion cannot replace B editor');
  assert.strictEqual(papers.get('paper-a').title, 'Paper A saved in background', 'the request still saves to its captured Paper A ID');

  editTitle().value = 'Paper B updated';
  await editTitle().dispatch('input');
  await editor.querySelectorAll('button')[1].dispatch('click');
  const bUpdate = requests.find((request) => request.method === 'PUT' && request.url.endsWith('/paper-b'));
  assert(bUpdate, 'Paper B save uses Paper B URL');
  assert.strictEqual(JSON.parse(bUpdate.body).expected_revision, 7, 'Paper B save uses Paper B revision');
  assert.strictEqual(papers.get('paper-b').title, 'Paper B updated', 'updating B leaves the separate A record unchanged');
  assert.strictEqual(papers.get('paper-a').title, 'Paper A saved in background', 'updating B does not mutate A');

  await backToList();
  await clickEdit('Paper A');
  await tick();
  const publishButton = editor.querySelectorAll('button')[3];
  const pendingPublish = publishButton.dispatch('click');
  await tick();
  await backToList();
  await clickEdit('Paper B');
  await tick();
  delayedAPublish.resolve();
  await pendingPublish;
  assert.strictEqual(editTitle().value, 'Paper B updated', 'late A publish response cannot replace B editor');
  assert.strictEqual(papers.get('paper-a').status, 'published', 'the pending publish remains bound to Paper A');
  console.log('PASS Paper card isolation: delayed detail/edit/preview/save/publish responses stay bound to their Paper');
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
