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
    this.value = attrs.value ?? (this.tagName === 'TEXTAREA' ? this.children.map((child) => String(child)).join('') : '');
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
      if (selector === 'tr') return node.tagName === 'TR';
      if (selector === 'table') return node.tagName === 'TABLE';
      if (selector === 'article') return node.tagName === 'ARTICLE';
      if (selector === 'th') return node.tagName === 'TH';
      if (selector === 'td') return node.tagName === 'TD';
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
  const storedCopies = new Map();
  let copySequence = 0;
  let failNextPublish = false;
  let createSaveGate = null;
  let failNextUpdate = false;
  const windowListeners = new Map();
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const apiRequest = async (url, options = {}) => {
    requests.push({ url, method: options.method || 'GET', body: options.body });
    if (url === '/api/admin/papers' && options.method !== 'POST') return { papers: [...(storedPaper ? [clone(storedPaper)] : []), ...[...storedCopies.values()].map(clone)] };
    if (url === '/api/admin/questions') return { questions: bank };
    const detail = url.match(/^\/api\/admin\/papers\/([^/?]+)$/);
    const paperId = detail?.[1];
    if (paperId && (options.method || 'GET') === 'GET') return { paper: clone(storedPaper?.id === paperId ? storedPaper : storedCopies.get(paperId)) };
    if (paperId && options.method === 'PUT') {
      if (failNextUpdate) { failNextUpdate = false; const error = new Error('temporary network failure'); error.status = 503; throw error; }
      const payload = JSON.parse(options.body);
      storedPaper = { ...storedPaper, title: payload.title, metadata: payload.metadata, question_ids: payload.question_ids,
        question_limit: payload.question_limit, question_filters: payload.question_filters, revision: storedPaper.revision + 1,
        questions: storedPaper.status === 'published' ? payload.question_ids.map((question_id, order) => ({ question_id, order })) : [] };
      return { paper: clone(storedPaper) };
    }
    if (url === '/api/admin/papers/independent' && options.method === 'POST') {
      if (createSaveGate) { const gate = createSaveGate; createSaveGate = null; await gate.promise; }
      const payload = JSON.parse(options.body);
      const isIndependentCopy = storedPaper?.status === 'published';
      const paper = { id: isIndependentCopy ? `paper-copy-${++copySequence}` : 'paper-lifecycle', schema_version: 2,
        title: payload.title, metadata: payload.metadata, status: 'draft', revision: 1,
        question_ids: payload.question_ids, question_limit: payload.question_limit, question_filters: payload.question_filters, questions: [] };
      if (isIndependentCopy) storedCopies.set(paper.id, paper);
      else storedPaper = paper;
      return { paper: clone(paper) };
    }
    const preview = url.match(/^\/api\/admin\/papers\/([^/?]+)\/preview(?:\?.*)?$/);
    if (preview) { const paper = storedPaper?.id === preview[1] ? storedPaper : storedCopies.get(preview[1]);
      return { preview: { paper_id: preview[1], status: paper.status,
        paper: { ...paper, questions: (paper.question_ids || []).map((id) => ({ ...bank.find((q) => q.id === id), question_id: id })) } } };
    }
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
    addEventListener: (type, callback) => windowListeners.set(type, callback),
    removeEventListener: (type) => windowListeners.delete(type),
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console };
  const timers = new Map();
  let nextTimerId = 0;
  context.setTimeout = (callback) => { const id = ++nextTimerId; timers.set(id, callback); return id; };
  context.clearTimeout = (id) => timers.delete(id);
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  await list.querySelectorAll('button').find((button) => button.textContent.includes('Tạo đề thi')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));

  assert(!editor.querySelectorAll('button').some((button) => button.textContent.includes('Preview Draft')),
    'Draft Preview is not rendered for a new Paper');
  assert(editor.querySelectorAll('button').some((button) => button.textContent.includes('Save Draft')),
    `new Paper can be saved as a Draft to create its ID; buttons=${editor.querySelectorAll('button').map((button) => button.textContent).join('|')}; editor=${editor.textContent}`);
  assert(editor.textContent.includes('Lưu thành bản nháp để tạo Paper ID'), 'new Paper explains the Draft creation step');

  const control = (name) => { const node = editor.querySelector(`[data-filter="${name}"]`); assert(node, `missing ${name} filter`); return node; };
  const available = () => editor.querySelector('.qb-picker-list').textContent;
  const selected = () => editor.querySelector('.qb-selected-list').textContent;
  const selectedTitles = () => editor.querySelectorAll('.qb-selected').map((row) => row.children[1].children[0].textContent);
  const questionFilters = editor.querySelector('.qb-question-filters');
  const reset = editor.querySelector('[data-role="clear-question-filters"]');
  assert(questionFilters && questionFilters.attrs.role === 'search', 'Question filters render in a labeled search group');
  assert.strictEqual(questionFilters.querySelectorAll('.paper-question-filter-field').length, 5, 'keyword and existing select filters each have a visible label');
  assert.strictEqual(editor.querySelector('.qb-filter-tags').attrs.role, 'group', 'Tag choices are exposed as a named group');
  assert(editor.querySelectorAll('.qb-tag-option').length >= 3, 'Tags render as individually labeled choices');
  assert(reset.disabled, 'clear filters is disabled when no filter is active');
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
  assert(!reset.disabled, 'clear filters is enabled after a filter is applied');
  await reset.dispatch('click');
  assert(available().includes('Array Basics'), 'reset restores complete eligible pool');
  editor.querySelector('[data-filter-tag="loops"]').checked = true;
  await editor.querySelector('[data-filter-tag="loops"]').dispatch('change');
  editor.querySelector('[data-filter-tag="advanced"]').checked = true;
  await editor.querySelector('[data-filter-tag="advanced"]').dispatch('change');
  assert(available().includes('Loops Intro') && available().includes('Loops Advanced'), 'multiple tags combine with OR');
  assert(editor.querySelectorAll('.qb-tag-option').filter((option) => option.classList.contains('is-selected')).length === 2,
    'selected Tags have a distinct selected-chip state');
  await reset.dispatch('click');

  quantity.value = '2'; await quantity.dispatch('input');
  const loopsTag = editor.querySelector('[data-filter-tag="loops"]');
  loopsTag.checked = true; await loopsTag.dispatch('change');
  const filteredQuestion = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes('Loops Intro'));
  assert(filteredQuestion && !filteredQuestion.querySelector('button').disabled,
    'manual selection stays enabled while a Tag filter is active and under Question Limit');
  await filteredQuestion.querySelector('button').dispatch('click');
  assert(selected().includes('Loops Intro'), 'manual Add selects a question under the active Tag filter');
  const setTag = async (name, checked) => {
    const checkbox = editor.querySelector(`[data-filter-tag="${name}"]`);
    checkbox.checked = checked;
    await checkbox.dispatch('change');
  };
  await setTag('loops', false);
  await setTag('intro', false);
  await setTag('advanced', true);
  assert(selected().includes('Loops Intro'), 'changing from Tag A to Tag B keeps the first selection outside the active pool');
  const advancedQuestion = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes('Loops Advanced'));
  assert(advancedQuestion && !advancedQuestion.querySelector('button').disabled,
    'manual Add remains enabled when the filtered pool is smaller than Question Limit but selection is below the limit');
  const addAdvancedButton = advancedQuestion.querySelector('button');
  await addAdvancedButton.dispatch('click');
  await addAdvancedButton.dispatch('click');
  assert(selected().includes('Loops Intro') && selected().includes('Loops Advanced'), 'manual Add across Tags preserves both selections');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'repeated Add for one ID never creates a duplicate');
  const orderBeforeFilterReset = selectedTitles();
  await reset.dispatch('click');
  assert.deepStrictEqual(selectedTitles(), orderBeforeFilterReset, 'clearing filters leaves the selected IDs and their order unchanged');
  assert.strictEqual(editor.querySelectorAll('.qb-tag-option').filter((option) => option.classList.contains('is-selected')).length, 0,
    'clearing filters clears selected Tag states');
  assert(reset.disabled, 'clear filters becomes disabled after reset');
  await setTag('advanced', false);
  await setTag('intro', true);
  assert(selected().includes('Loops Advanced'), 'changing back to Tag A retains the Tag B question');
  const removeOutsideFilter = editor.querySelectorAll('.qb-selected').find((item) => item.textContent.includes('Loops Advanced'));
  await removeOutsideFilter.querySelectorAll('button').at(-1).dispatch('click');
  assert(!selected().includes('Loops Advanced') && selected().includes('Loops Intro'),
    'manual Remove works for a selected question outside the active Tag filter and preserves the other ID');
  await setTag('intro', false);
  await setTag('advanced', true);
  const addAdvancedAgain = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes('Loops Advanced'));
  await addAdvancedAgain.querySelector('button').dispatch('click');
  assert(editor.querySelectorAll('.qb-selected').map((item) => item.textContent).join('|').indexOf('Loops Intro')
    < editor.querySelectorAll('.qb-selected').map((item) => item.textContent).join('|').indexOf('Loops Advanced'),
  'adding after Tag changes preserves the explicit selection order without duplicates');
  await setTag('advanced', false);
  await setTag('arrays', true);
  const addAtLimit = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes('Array Basics'));
  assert(addAtLimit?.querySelector('button').disabled, 'manual Add is disabled once the full selection reaches Question Limit');
  assert(editor.querySelector('[data-role="question-limit-status"]').textContent.includes('Question Limit reached'),
    'the UI explains that Question Limit blocks additional manual selection');
  const removeAtLimit = editor.querySelectorAll('.qb-selected').find((item) => item.textContent.includes('Loops Intro'));
  await removeAtLimit.querySelectorAll('button').at(-1).dispatch('click');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 1, 'a selected question can be removed at Question Limit');
  const addAfterRemoval = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes('Array Basics'));
  assert(!addAfterRemoval.querySelector('button').disabled, 'removing one selection enables adding another visible question');
  await addAfterRemoval.querySelector('button').dispatch('click');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'remove-then-add respects the limit and retains the remaining selection');
  const noMatchSearch = editor.querySelector('[data-filter="search"]');
  noMatchSearch.value = 'no-such-question'; await noMatchSearch.dispatch('input');
  assert.strictEqual(editor.querySelectorAll('.qb-item').length, 0, 'a Tag/search combination with no matches shows an empty available list');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'an empty filtered pool does not discard selected IDs');
  noMatchSearch.value = ''; await noMatchSearch.dispatch('input');
  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Bỏ chọn tất cả')).dispatch('click');
  await reset.dispatch('click');
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
  assert.deepStrictEqual(editor.querySelectorAll('.qb-selected').map((row) => row.textContent.match(/(?:Loops Intro|Loops Advanced|Array Basics)/)?.[0]),
    ['Loops Intro', 'Loops Advanced'], 'Select All replaces the old selection with the filtered pool in its displayed order');
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

  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Bỏ chọn tất cả')).dispatch('click');
  for (const title of ['Loops Advanced', 'Loops Intro']) {
    const row = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes(title));
    await row.querySelector('button').dispatch('click');
  }
  await setTag('loops', true);
  group.checked = true; await group.dispatch('change');
  assert.deepStrictEqual(editor.querySelectorAll('.qb-selected').map((row) => row.textContent.match(/(?:Loops Intro|Loops Advanced|Array Basics)/)?.[0]),
    ['Loops Advanced', 'Loops Intro'], 'group selection does not reorder questions already selected manually');
  await setTag('loops', false);
  await setTag('arrays', true);
  group.checked = true; await group.dispatch('change');
  assert.deepStrictEqual(editor.querySelectorAll('.qb-selected').map((row) => row.textContent.match(/(?:Loops Intro|Loops Advanced|Array Basics)/)?.[0]),
    ['Loops Advanced', 'Loops Intro', 'Array Basics'], 'Tag group selection appends matching IDs and retains outside selections in order');
  group.checked = false; await group.dispatch('change');
  assert.deepStrictEqual(editor.querySelectorAll('.qb-selected').map((row) => row.textContent.match(/(?:Loops Intro|Loops Advanced|Array Basics)/)?.[0]),
    ['Loops Advanced', 'Loops Intro'], 'Tag group deselection removes only its questions and preserves remaining order');
  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Bỏ chọn tất cả')).dispatch('click');
  await reset.dispatch('click');

  for (const title of ['Loops Intro', 'Loops Advanced']) {
    const row = editor.querySelectorAll('.qb-item').find((item) => item.textContent.includes(title));
    await row.querySelector('button').dispatch('click');
  }
  await reset.dispatch('click');

  const status = editor.querySelector('[data-role="paper-lifecycle"]');
  assert.strictEqual(status.querySelector('.paper-save-status-primary').dataset.status, 'unsaved', 'new Paper shows an unsaved primary status');
  assert(status.textContent.includes('Ch\u01b0a c\u00f3 phi\u00ean b\u1ea3n xu\u1ea5t b\u1ea3n'), 'new Paper explains that no Published Version exists');
  assert(!/\b(null|undefined)\b/i.test(status.textContent), 'new Paper status omits null and undefined values');
  const title = editor.querySelector('#cp-title');
  title.value = 'Lifecycle Paper'; await title.dispatch('input');
  assert.strictEqual(status.querySelector('.paper-save-status-primary').dataset.status, 'unsaved', 'new Paper remains explicitly unsaved before first Save');
  const createCallsBeforeSave = requests.filter((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').length;
  assert.strictEqual(createCallsBeforeSave, 0, 'typing and selecting questions do not create a Paper before explicit Save');
  assert.strictEqual(timers.size, 0, 'editing does not schedule a delayed Paper save');
  await new Promise((resolve) => setTimeout(resolve, 650));
  assert.strictEqual(requests.filter((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').length, 0,
    'waiting after edits does not persist a new Paper');
  const saveButton = () => editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Draft'));
  const saveCallsBefore = requests.filter((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').length;
  const saveGate = deferred();
  createSaveGate = saveGate;
  const firstSave = saveButton().dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(status.querySelector('.paper-save-status-primary').dataset.status, 'saving', 'pending API save is shown as Saving');
  await saveButton().dispatch('click');
  saveGate.resolve();
  await firstSave;
  assert.strictEqual(requests.filter((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').length - saveCallsBefore, 1, 'duplicate save clicks create only one Paper');
  const savePayload = JSON.parse(requests.find((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST').body);
  assert.deepStrictEqual(savePayload.question_ids, ['q1', 'q2'], 'Save serializes the ordered selected state, not the active filtered pool');
  assert.strictEqual(storedPaper.id, 'paper-lifecycle', 'saving a new Paper retains its server ID');
  assert(editor.classList.contains('hidden'), 'saving a new Paper returns to the Paper list');
  assert(list.textContent.includes('Lifecycle Paper'), 'saved Draft appears in the Paper list');
  await list.querySelectorAll('button').find((button) => button.textContent.includes('Chỉnh sửa')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  const savedStatus = editor.querySelector('[data-role="paper-lifecycle"]');
  assert.strictEqual(savedStatus.querySelector('.paper-save-status-primary').dataset.status, 'saved', 'backend confirmation changes status to Saved');
  assert(savedStatus.textContent.includes('L\u1ea7n ch\u1ec9nh s\u1eeda 1'), 'saved status shows the valid revision');
  assert(savedStatus.textContent.includes('Ch\u01b0a c\u00f3 phi\u00ean b\u1ea3n xu\u1ea5t b\u1ea3n'), 'Draft without publication shows a clear message');
  assert(!/\b(null|undefined)\b/i.test(savedStatus.textContent), 'saved Draft status omits invalid optional values');
  const restoredSelection = editor.querySelectorAll('.qb-selected').map((row) => row.textContent).join('|');
  assert(restoredSelection.indexOf('Loops Intro') < restoredSelection.indexOf('Loops Advanced'), 'Edit Mode restores saved question IDs in their original order');

  storedPaper.question_ids = ['q2', 'q1', 'q2'];
  await editor.querySelectorAll('button').find((button) => button.textContent === 'Cancel').dispatch('click');
  await new Promise((resolve) => setTimeout(resolve, 10));
  await list.querySelectorAll('button').find((button) => button.textContent.includes('Chỉnh sửa')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepStrictEqual(editor.querySelectorAll('.qb-selected').map((row) => row.textContent.match(/(?:Loops Intro|Loops Advanced)/)?.[0]),
    ['Loops Advanced', 'Loops Intro'], 'Editor initialization removes duplicate stored IDs while preserving first-seen order');
  assert.strictEqual(editor.querySelectorAll('.qb-selected').length, 2, 'duplicate stored IDs do not render duplicate selected rows');
  storedPaper.question_ids = ['q1', 'q2'];

  const titleForDraftSave = editor.querySelector('#cp-title');
  titleForDraftSave.value = 'Explicit Draft Save'; await titleForDraftSave.dispatch('input');
  assert.strictEqual(editor.querySelector('[data-role="paper-lifecycle"]').querySelector('.paper-save-status-primary').dataset.status, 'dirty', 'editing a saved Draft shows unsaved changes');
  const searchForDraftSave = editor.querySelector('[data-filter="search"]');
  searchForDraftSave.value = 'Loops Intro'; await searchForDraftSave.dispatch('input');
  const filteredSelectionForDraftSave = editor.querySelector('[data-role="filtered-selection"]');
  filteredSelectionForDraftSave.checked = false; await filteredSelectionForDraftSave.dispatch('change');
  filteredSelectionForDraftSave.checked = true; await filteredSelectionForDraftSave.dispatch('change');
  assert.strictEqual(timers.size, 0, 'typing, selecting a question, and changing filters do not schedule persistence');
  const draftUpdateCalls = () => requests.filter((request) => request.url === `/api/admin/papers/${storedPaper.id}` && request.method === 'PUT');
  const updatesBeforeExplicitSave = draftUpdateCalls().length;
  const selectionBeforeFailedSave = editor.querySelectorAll('.qb-selected').map((row) => row.textContent);
  await new Promise((resolve) => setTimeout(resolve, 650));
  assert.strictEqual(draftUpdateCalls().length, updatesBeforeExplicitSave, 'waiting after Draft edits sends no update request');
  assert.strictEqual(storedPaper.title, 'Lifecycle Paper', 'server Draft remains unchanged before explicit Save');

  let beforeUnloadPrevented = false;
  const beforeUnloadEvent = { preventDefault() { beforeUnloadPrevented = true; } };
  windowListeners.get('beforeunload')(beforeUnloadEvent);
  assert(beforeUnloadPrevented && beforeUnloadEvent.returnValue === '', 'unsaved editor changes trigger the browser leave warning');
  confirmNext = false;
  await editor.querySelectorAll('button').find((button) => button.textContent === 'Cancel').dispatch('click');
  assert(!editor.classList.contains('hidden'), 'declining the leave warning keeps the editor open');
  assert.strictEqual(draftUpdateCalls().length, updatesBeforeExplicitSave, 'navigation warning never saves automatically');
  confirmNext = true;

  failNextUpdate = true;
  await saveButton().dispatch('click');
  assert.strictEqual(editor.querySelector('#cp-title').value, 'Explicit Draft Save', 'failed Save retains title input');
  assert.strictEqual(editor.querySelector('[data-filter="search"]').value, 'Loops Intro', 'failed Save retains filter state');
  assert.deepStrictEqual(editor.querySelectorAll('.qb-selected').map((row) => row.textContent), selectionBeforeFailedSave,
    'failed Save retains the selected question state and order');
  assert.strictEqual(storedPaper.title, 'Lifecycle Paper', 'failed Save does not change server content');
  assert.strictEqual(editor.querySelector('[data-role="paper-lifecycle"]').querySelector('.paper-save-status-primary').dataset.status, 'error', 'failed Save shows an error status');
  assert(editor.querySelector('[data-role="paper-lifecycle"]').textContent.includes('temporary network failure'), 'failed Save displays failure feedback');
  await saveButton().dispatch('click');
  assert.strictEqual(storedPaper.id, 'paper-lifecycle', 'saving an existing Draft updates the same Paper ID');
  assert.strictEqual(storedPaper.title, 'Explicit Draft Save', 'explicit Save persists the retained title');
  assert.deepStrictEqual(storedPaper.question_ids, ['q2', 'q1'], 'explicit Save persists the current selected question order');
  assert.strictEqual(storedPaper.status, 'draft', 'saving a Draft does not publish it');
  assert.strictEqual(draftUpdateCalls().length, updatesBeforeExplicitSave + 2, 'only the failed and successful explicit Save attempts issue Draft updates');
  assert(!requests.some((request) => request.url.endsWith('/publish')), 'Save does not call the Publish endpoint');

  const publishButton = () => editor.querySelectorAll('button').find((button) => button.textContent.includes('Publish Paper'));
  const titleForPublish = editor.querySelector('#cp-title');
  titleForPublish.value = 'Published without preview'; await titleForPublish.dispatch('input');
  failNextPublish = true;
  await publishButton().dispatch('click');
  assert.strictEqual(storedPaper.status, 'draft', 'failed publish does not change the server lifecycle');
  assert.strictEqual(editor.querySelector('[data-role="paper-lifecycle"]').querySelector('.paper-save-status-primary').dataset.status, 'saved', 'a failed Publish after a confirmed save still reports Saved');
  assert(editor.querySelector('[data-role="paper-lifecycle"]').textContent.includes('publishing failed'), 'publish failure remains visible as a separate message');
  await publishButton().dispatch('click');
  assert.strictEqual(storedPaper.status, 'published', 'Paper publish changes status without creating a nested version');
  assert.strictEqual(requests.filter((request) => request.url.includes('/preview')).length, 1,
    'publish displays the published Paper preview after saving');
  assert(!requests.some((request) => request.url.endsWith('/preview?draft=1')),
    'publish does not substitute a Draft Preview for the published Paper preview');
  assert.strictEqual(storedPaper.id, 'paper-lifecycle', 'publishing preserves the Paper ID');
  assert(!('versions' in storedPaper) && !('current_version_id' in storedPaper), 'independent Paper has no nested version history');

  const sourceBeforeCopy = JSON.stringify(storedPaper);
  const sourcePutCallsBeforeCopy = requests.filter((request) => request.url === `/api/admin/papers/${storedPaper.id}` && request.method === 'PUT').length;
  const createNewPaper = editor.querySelectorAll('button').find((button) => button.textContent.includes('\u0043h\u1ec9nh s\u1eeda b\u1ea3n m\u1edbi'));
  assert(createNewPaper, 'Published Paper offers the explicit independent-copy action');
  await createNewPaper.dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert(editor.querySelector('#cp-title'), 'copy action opens the Paper editor');
  editor.querySelector('#cp-title').value = 'Independent version 2';
  await editor.querySelector('#cp-title').dispatch('input');
  await editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Draft')).dispatch('click');
  const copy = [...storedCopies.values()][0];
  assert(copy && copy.id !== storedPaper.id, 'editing a published Paper creates a new Paper ID');
  assert.strictEqual(copy.status, 'draft', 'independent copy starts as Draft');
  assert.strictEqual(JSON.stringify(storedPaper), sourceBeforeCopy, 'published source content and revision remain unchanged');
  assert.strictEqual(requests.filter((request) => request.url === `/api/admin/papers/${storedPaper.id}` && request.method === 'PUT').length,
    sourcePutCallsBeforeCopy, 'saving a Published Paper copy never updates its source Paper');
  assert(!('versions' in copy) && !('current_version_id' in copy), 'independent Draft copy has no inherited version history');
  await new Promise((resolve) => setImmediate(resolve));

  storedPaper.warnings = [{ question_id: 'q1', warning: 'unavailable' }];
  onVisibilityChange();
  await new Promise((resolve) => setImmediate(resolve));
  assert(list.querySelector('.qb-change-badge')?.attrs.title.includes('1 câu hỏi nguồn'), 'Paper table retains the warning count in the title badge');
  storedPaper.warnings = ['q1', 'q2', 'q3'].map((question_id) => ({ question_id, warning: 'unavailable' }));
  onVisibilityChange();
  await new Promise((resolve) => setImmediate(resolve));
  assert(list.querySelector('.qb-change-badge')?.attrs.title.includes('3 câu hỏi nguồn'), 'Paper table refreshes the warning badge when the page becomes visible');

  const savedBank = bank.slice();
  bank.splice(0, bank.length);
  await list.querySelectorAll('button')[0].dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  const emptyBankQuantity = editor.querySelector('[data-field="question-limit"]');
  assert.strictEqual(emptyBankQuantity.value, '', 'empty Question Bank does not fabricate a Question Limit');
  assert.strictEqual(emptyBankQuantity.disabled, true, 'empty Question Bank prevents setting Question Limit');
  assert(editor.querySelector('[data-role="question-limit-status"]').textContent.includes('Question Bank is empty'), 'empty Question Bank explains why publishing is blocked');
  bank.splice(0, bank.length, ...savedBank);

  console.log('PASS independent Paper Draft/Published lifecycle, immutable Published source, and independent copy');
  await testCardSwitchRace();
}

async function testCardSwitchRace() {
  const list = new Element('div');
  const editor = new Element('div');
  const notice = new Element('div');
  const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null };
  const makePaper = (id, title, revision) => ({ id, title, metadata: {}, status: 'published', revision,
    current_version_id: `${id}:v1`, version_count: 1,
    versions: { [`${id}:v1`]: { id: `${id}:v1`, version: 1, title, questions: [{ question_id: 'q1', order: 0 }] } },
    draft: { title, metadata: {}, question_ids: ['q1'], question_limit: 1, question_filters: {} } });
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
      return { papers: [...papers.values()].map((paper) => ({ ...clone(paper), has_draft: true, question_count: 1, version_count: 1 })) };
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
      return { preview: { paper_id: preview[1], version: { title: papers.get(preview[1]).title, id: `${preview[1]}:v1`, questions: [] } } };
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
    addEventListener() {},
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console };
  const timers = new Map();
  let nextTimerId = 0;
  context.setTimeout = (callback) => { const id = ++nextTimerId; timers.set(id, callback); return id; };
  context.clearTimeout = (id) => timers.delete(id);
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
  const pendingOpenA = clickOpen('Paper A');
  await clickOpen('Paper B');
  await tick();
  delayedAOpenDetail.resolve({ paper: clone(papers.get('paper-a')) });
  await tick();
  delayedAPreview.resolve({ preview: { paper_id: 'paper-a', version: { title: 'Paper A published preview', questions: [] } } });
  await pendingOpenA;
  assert(editor.textContent.includes('Paper B'), 'late A Published preview cannot replace B detail view');

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
  console.log('PASS Paper card isolation: delayed detail/edit/Published preview/save/publish responses stay bound to their Paper');
}

async function testDraftListOpensEditor() {
  const list = new Element('div');
  const editor = new Element('div');
  const notice = new Element('div');
  const paper = { id: 'draft-only', schema_version: 2, title: 'Draft Only', metadata: {}, status: 'draft', revision: 1,
    question_ids: [], question_limit: 1, question_filters: {}, questions: [] };
  const calls = [];
  const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null };
  const window = {
    cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message, setNotice() {} },
    cssRequest: async (url) => {
      calls.push(url);
      if (url === '/api/admin/papers') return { papers: [paper] };
      if (url === '/api/admin/questions') return { questions: bank };
      if (url === `/api/admin/papers/${paper.id}`) return { paper };
      throw new Error(`Unexpected request: ${url}`);
    },
    addEventListener() {}, confirm: () => true,
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console,
    setTimeout, clearTimeout };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  const actions = list.querySelectorAll('button').map((button) => button.textContent);
  assert.deepStrictEqual(actions.slice(1), ['Chỉnh sửa', 'Lưu trữ', 'Xóa'], 'Draft card exposes only Edit, Archive, and Delete');
  assert(!actions.includes('Mở'), 'Draft row has no Open action');
  await list.querySelectorAll('button').find((button) => button.textContent.includes('Chỉnh sửa')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert(editor.querySelector('#cp-title'), 'clicking a Draft opens its Editor directly');
  assert(!calls.some((url) => url.includes('/preview')), 'Draft navigation does not open a Preview route');
  assert(editor.querySelectorAll('button').some((button) => button.textContent.includes('Save Draft')),
    'persisted Draft editor retains its Save Draft control');
  console.log('PASS Draft list navigation opens the persisted Draft editor directly');
}

async function testSchemaTwoPaperListActions() {
  const list = new Element('div');
  const editor = new Element('div');
  const notice = new Element('div');
  const papers = [
    { id: 'v2-draft', schema_version: 2, title: 'V2 Draft', status: 'draft', revision: 1, question_count: 0 },
    { id: 'v2-published', schema_version: 2, title: 'V2 Published', status: 'published', revision: 2, question_count: 1 },
    { id: 'v2-archived', schema_version: 2, title: 'V2 Archived', status: 'archived', revision: 3, question_count: 1 },
    { id: 'legacy-mixed-draft', title: 'Legacy Mixed Draft', status: 'draft', revision: 1, version_count: 0,
      question_count: 1, draft: { title: 'Legacy Mixed Draft', metadata: {}, question_ids: ['q1'], question_limit: 1 } },
    { id: 'legacy-published-draft', title: 'Legacy Published Draft', status: 'published', has_draft: true, revision: 3, version_count: 1, question_count: 1 },
    { id: 'legacy-published', title: 'Legacy Published', status: 'published', has_draft: false, revision: 2, version_count: 1, question_count: 1 },
  ];
  const calls = [];
  const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null };
  const window = {
    cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message, setNotice() {} },
    cssRequest: async (url, options = {}) => {
      calls.push(url);
      if (url === '/api/admin/papers') return { papers };
      const paperAction = url.match(/^\/api\/admin\/papers\/([^/]+)\/(archive|restore|delete)$/);
      if (paperAction && options.method === 'POST') {
        const index = papers.findIndex((paper) => paper.id === paperAction[1]);
        if (index < 0) throw new Error('Paper not found');
        if (paperAction[2] === 'delete') { papers.splice(index, 1); return {}; }
        papers[index] = { ...papers[index], status: paperAction[2] === 'archive' ? 'archived' : 'published', revision: papers[index].revision + 1 };
        return { paper: papers[index] };
      }
      if (url === '/api/admin/papers/v2-published') return { paper: papers[1] };
      if (url === '/api/admin/papers/v2-published/preview') return { preview: { paper: papers[1] } };
      if (url === '/api/admin/papers/legacy-mixed-draft') return { paper: papers[3] };
      if (url === '/api/admin/questions') return { questions: bank };
      throw new Error(`Unexpected request: ${url}`);
    },
    addEventListener() {}, confirm: () => true,
  };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console,
    setTimeout, clearTimeout };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(list.querySelectorAll('table').length, 1, 'Paper Management renders the restored table');
  assert.strictEqual(list.querySelectorAll('article').length, 0, 'Paper Management no longer renders a card list');
  assert(list.querySelector('.table-scroll'), 'the table stays inside the horizontally scrollable wrapper');
  assert.deepStrictEqual(list.querySelectorAll('th').map((cell) => cell.textContent),
    ['Tên Paper', 'Metadata', 'Số câu', 'Versions', 'Trạng thái', 'Thao tác'], 'the table restores the historical six-column header');
  const groups = list.querySelectorAll('.actions-inline').map((group) => group.querySelectorAll('button').map((button) => button.textContent));
  assert.deepStrictEqual(groups, [
    ['\u0043h\u1ec9nh s\u1eeda', 'L\u01b0u tr\u1eef', 'X\u00f3a'],
    ['M\u1edf', 'L\u01b0u tr\u1eef', 'X\u00f3a'],
    ['Kh\u00f4i ph\u1ee5c', 'X\u00f3a'],
    ['\u0043h\u1ec9nh s\u1eeda', 'L\u01b0u tr\u1eef', 'X\u00f3a'],
    ['M\u1edf', '\u0043h\u1ec9nh s\u1eeda', 'L\u01b0u tr\u1eef', 'X\u00f3a'],
    ['M\u1edf', 'L\u01b0u tr\u1eef', 'X\u00f3a'],
  ], 'schema 2 and legacy rows use status based actions');
  const v2DraftRow = list.querySelectorAll('tr').find((row) => row.textContent.includes('V2 Draft'));
  assert(!v2DraftRow.textContent.includes('Paper ID') && !v2DraftRow.textContent.includes('Revision'), 'the restored title cell omits technical identity metadata');
  assert(v2DraftRow.querySelector('.status-pill').textContent.includes('Nháp'), 'schema 2 Draft status remains localized and accurate');
  assert(v2DraftRow.textContent.includes('—'), 'the Versions column represents schema 2 Papers without version history');
  const v2PublishedRow = list.querySelectorAll('tr').find((row) => row.textContent.includes('V2 Published'));
  assert(v2PublishedRow.querySelector('.status-pill').textContent.includes('Đã xuất bản'), 'schema 2 Published status remains accurate');
  const publishedWithDraftRow = list.querySelectorAll('tr').find((row) => row.textContent.includes('Legacy Published Draft'));
  assert.strictEqual(publishedWithDraftRow.querySelector('.status-pill').textContent,
    'Đã xuất bản · Có bản nháp', 'Published with Draft uses one combined status label');
  assert.strictEqual((publishedWithDraftRow.textContent.match(/Có bản nháp/g) || []).length, 1,
    'Draft status is not duplicated in a separate badge');
  const v2ArchivedRow = list.querySelectorAll('tr').find((row) => row.textContent.includes('V2 Archived'));
  assert(v2ArchivedRow.querySelector('.status-pill').textContent.includes('Lưu trữ'), 'schema 2 Archived status remains accurate');
  await list.querySelectorAll('.actions-inline')[1].querySelectorAll('button')[0].dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert(calls.includes('/api/admin/papers/v2-published/preview') && editor.textContent.includes('V2 Published'),
    'Published Open loads its detail and preview');
  assert(editor.querySelectorAll('button').some((button) => button.textContent.includes('Ch\u1ec9nh s\u1eeda b\u1ea3n m\u1edbi')),
    'schema 2 Published detail offers independent Paper creation');
  await list.querySelectorAll('.actions-inline')[3].querySelectorAll('button')[0].dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(editor.querySelector('#cp-title').value, 'Legacy Mixed Draft', 'legacy Draft in mixed card mode opens its Editor');
  assert(!editor.querySelectorAll('button').some((button) => button.textContent.includes('Preview Draft')), 'legacy Draft editor does not render Draft Preview');

  const publishedRowForArchive = list.querySelectorAll('tr').find((row) => row.textContent.includes('V2 Published'));
  await publishedRowForArchive.querySelector('.actions-inline').querySelectorAll('button')
    .find((button) => button.className.includes('btn-ghost')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  const archivedPublishedRow = list.querySelectorAll('tr').find((row) => row.textContent.includes('V2 Published'));
  assert(archivedPublishedRow.querySelector('.status-pill').textContent.includes('Lưu trữ'), 'Archive refreshes the table status');
  assert.deepStrictEqual(archivedPublishedRow.querySelector('.actions-inline').querySelectorAll('button').map((button) => button.textContent),
    ['Khôi phục', 'Xóa'], 'archived Paper retains Restore and Delete actions');
  await archivedPublishedRow.querySelector('.actions-inline').querySelectorAll('button')
    .find((button) => button.className.includes('btn-danger')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert(!list.querySelectorAll('tr').some((row) => row.textContent.includes('V2 Published')), 'Delete removes the Paper row after confirmation');
  console.log('PASS Paper Management table layout, schema 2 and legacy rows, and Published Open preview');
}

async function testPaperListLoadingErrorAndEmptyStates() {
  const createPage = (request) => {
    const list = new Element('div');
    const editor = new Element('div');
    const notice = new Element('div');
    const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null };
    const window = {
      cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message, setNotice() {} },
      cssRequest: request, addEventListener() {}, confirm: () => true,
    };
    const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console, setTimeout, clearTimeout };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
    return list;
  };

  let rejectList;
  const pendingList = new Promise((resolve, reject) => { rejectList = reject; });
  const loadingPage = createPage(async () => pendingList);
  assert(loadingPage.textContent.includes('Paper'), 'loading state appears while the Paper request is pending');
  rejectList(new Error('Paper list request failed'));
  await new Promise((resolve) => setImmediate(resolve));
  assert(loadingPage.textContent.includes('Paper list request failed'), 'request errors render in the Paper list region');

  const emptyPage = createPage(async () => ({ papers: [] }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(emptyPage.querySelectorAll('table').length, 1, 'empty results keep the table structure');
  assert(emptyPage.querySelector('.empty-cell')?.textContent.includes('Paper'), 'empty results render the table empty state');
  console.log('PASS Paper table loading, error, and empty states');
}


async function testPublishedPaperForkAndStatusRendering() {
  const list = new Element('div');
  const editor = new Element('div');
  const notice = new Element('div');
  const source = { id: 'legacy-source', title: 'Source Paper', metadata: {}, status: 'published', revision: 5,
    current_version_id: 'legacy-source:v2', has_draft: true, version_count: 2, question_count: 2,
    versions: { 'legacy-source:v2': { id: 'legacy-source:v2', version: 2, title: 'Published title',
      metadata: { version: 2 }, questions: [{ question_id: 'q1', order: 0 }, { question_id: 'q2', order: 1 }] } },
    draft: { title: 'Unpublished draft title', metadata: {}, question_ids: ['q3'], question_limit: 1, question_filters: {} } };
  const sourceBefore = JSON.stringify(source);
  const legacyDraft = { id: 'legacy-draft', title: 'Legacy Draft', metadata: {}, status: 'draft', revision: 1,
    version_count: 0, question_count: 1, draft: { title: 'Legacy Draft', metadata: {}, question_ids: ['q1'] } };
  const archived = { id: 'legacy-archived', title: 'Legacy Archived', metadata: {}, status: 'archived', revision: 3,
    version_count: 1, question_count: 2, current_version_id: 'legacy-archived:v1', versions: {} };
  const requests = [];
  let created = null;
  const apiRequest = async (url, options = {}) => {
    const method = options.method || 'GET';
    requests.push({ url, method, body: options.body });
    if (url === '/api/admin/papers' && method === 'GET') return { papers: [source, legacyDraft, archived] };
    if (url === '/api/admin/questions') return { questions: bank };
    if (url === '/api/admin/papers/' + source.id && method === 'GET') return { paper: source };
    if (url === '/api/admin/papers/' + source.id + '/preview') return { preview: { version: source.versions[source.current_version_id] } };
    if (url === '/api/admin/papers/independent' && method === 'POST') {
      const payload = JSON.parse(options.body);
      created = { id: 'independent-copy', schema_version: 2, status: 'draft', revision: 1, ...payload, questions: [] };
      return { ok: true, paper: created };
    }
    throw new Error('Unexpected request: ' + method + ' ' + url);
  };
  const document = { getElementById: (id) => ({ 'code-papers-view': list, 'cp-list': list, 'cp-editor': editor, 'cp-notice': notice })[id] || null };
  const window = { cssUi: { h, errorBox: (error) => h('div', {}, error.message), errorText: (error) => error.message,
      setNotice: (node, message) => { if (node) node.textContent = message; } },
    cssRequest: apiRequest, confirm: () => true, addEventListener() {} };
  const context = { window, document, URLSearchParams, encodeURIComponent, Set, Map, Promise, console,
    setTimeout: () => 1, clearTimeout() {} };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/code-papers.js'), 'utf8'), context);
  await new Promise((resolve) => setImmediate(resolve));
  const sourceRow = list.querySelectorAll('tr').find((row) => row.textContent.includes(source.title));
  assert(sourceRow, 'legacy published Paper appears in the list');
  assert.deepStrictEqual(sourceRow.querySelectorAll('button').map((button) => button.textContent),
    ['Mở', 'Chỉnh sửa', 'Lưu trữ', 'Xóa'], 'legacy Published retains Open, Edit, Archive, and Delete');
  assert(sourceRow.querySelector('.status-pill').textContent.includes('Đã xuất bản · Có bản nháp'),
    'legacy Published with a Draft keeps its combined status label');
  const legacyDraftRow = list.querySelectorAll('tr').find((row) => row.textContent.includes(legacyDraft.title));
  assert.deepStrictEqual(legacyDraftRow.querySelectorAll('button').map((button) => button.textContent),
    ['Chỉnh sửa', 'Lưu trữ', 'Xóa'], 'legacy Draft exposes exactly Edit, Archive, and Delete');
  const archivedRow = list.querySelectorAll('tr').find((row) => row.textContent.includes(archived.title));
  assert.deepStrictEqual(archivedRow.querySelectorAll('button').map((button) => button.textContent),
    ['Kh\u00f4i ph\u1ee5c', 'X\u00f3a'], 'legacy Archived actions match current Archived actions');
  await sourceRow.querySelectorAll('button').find((button) => button.textContent.includes('Mở')).dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  const forkButton = editor.querySelectorAll('button')[1];
  assert(forkButton, 'legacy published Paper offers creating a new editable draft');
  await forkButton.dispatch('click');
  await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(editor.querySelector('#cp-title').value, 'Published title', 'copy starts from the published version title');
  const copyStatus = editor.querySelector('[data-role="paper-lifecycle"]');
  assert(copyStatus.querySelector('.paper-id').textContent.startsWith('Paper legacy-s'), 'legacy Paper status shows a shortened Paper ID');
  assert.strictEqual(copyStatus.querySelector('.paper-id').attrs.title, 'legacy-source', 'the full Paper ID remains available as a tooltip');
  assert(copyStatus.querySelector('.paper-publication-status').textContent.includes('Phi\u00ean b\u1ea3n 2'), 'legacy Paper status shows its latest Published Version');
  assert(!/\b(null|undefined)\b/i.test(copyStatus.textContent), 'legacy Paper status omits null and undefined values');
  assert(editor.querySelector('#cp-metadata').value.includes('"version": 2'), 'copy starts from published version metadata');
  assert(editor.querySelector('.qb-selected-list').textContent.includes('Loops Intro'), 'copy retains published ordered question selection');
  assert(!editor.querySelector('.qb-selected-list').textContent.includes('Array Basics'), 'source mutable Draft selection is excluded');
  editor.querySelector('#cp-title').value = 'Independent copy';
  const saveButton = editor.querySelectorAll('button').find((button) => button.textContent.includes('Save Draft'));
  assert(saveButton, 'new copy uses the current Save Draft control');
  await saveButton.dispatch('click');
  assert(created && created.id !== source.id, 'copy is persisted as an independent Paper');
  const post = requests.find((request) => request.url === '/api/admin/papers/independent' && request.method === 'POST');
  assert(post, 'copy uses the implemented independent Paper endpoint');
  assert.deepStrictEqual(JSON.parse(post.body).question_ids, ['q1', 'q2'], 'copy POST contains the published ordered question IDs');
  assert.strictEqual(JSON.stringify(source), sourceBefore, 'creating the copy does not mutate its source Paper');
  console.log('PASS Published Paper copy uses the published snapshot and preserves its source');
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => { resolve = resolvePromise; reject = rejectPromise; });
  return { promise, resolve, reject };
}

main().then(async () => {
  await testDraftListOpensEditor();
  await testSchemaTwoPaperListActions();
  await testPaperListLoadingErrorAndEmptyStates();
  await testPublishedPaperForkAndStatusRendering();
}).catch((error) => { console.error(error); process.exitCode = 1; });
