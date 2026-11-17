const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'questions.js'), 'utf8');
class Element {
  constructor(tag, attrs, children) {
    Object.assign(this, { tag, attrs, children, listeners: {}, isConnected: true });
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  showModal() { this.open = true; }
  close() { this.open = false; this.listeners.close(); }
  remove() { this.isConnected = false; }
}
const calls = [];
const dialogs = [];
const question = { id: 'q1', title: 'Question', status: 'published', practice_enabled: true };
let table;
const listContext = vm.createContext({
  questions: [question], filteredQuestions: () => [question], practiceSaving: new Set(),
  document: { getElementById: () => ({ value: '', classList: { toggle() {} } }) },
  listHost: { replaceChildren: value => { table = value; } },
  h: (tag, attrs, ...children) => new Element(tag, attrs, children.flat()),
  statusPill: status => status,
});
vm.runInContext(source.slice(source.indexOf('  function renderList('), source.indexOf('  async function mutate(')), listContext);
listContext.renderList();
const headers = table.children[0].children[0].children;
const cells = table.children[1].children[0].children;
assert.strictEqual(headers[6].children[0], 'Luyện tập');
assert.strictEqual(cells[6].children.length, 1);
assert.strictEqual(cells[6].children[0].attrs.type, 'checkbox');
assert.strictEqual(cells[6].children[0].attrs.checked, true);
assert.strictEqual(cells[7].children[0].children.length, 5, 'Practice controls must not be in the action group');
const statusTags = cells[3].children[0];
assert.strictEqual(statusTags.attrs.class, 'question-status-tags');
assert.strictEqual(statusTags.children[0], 'published');
assert.strictEqual(statusTags.children[1].attrs.class, 'status-pill status-practice');
assert.strictEqual(statusTags.children[1].children[0], 'Luyện tập');
question.practice_enabled = false;
listContext.renderList();
assert.strictEqual(table.children[1].children[0].children[3].children[0].children[1], null,
  'Questions without practice enabled must not show a practice tag');
const context = vm.createContext({
  h: (tag, attrs, ...children) => new Element(tag, attrs, children),
  document: { body: { append: dialog => dialogs.push(dialog) } },
  savePracticeChange: (q, enabled) => calls.push({ q, enabled }),
});
vm.runInContext(source.slice(source.indexOf('  function confirmPracticeChange('), source.indexOf('  async function savePracticeChange(')), context);

for (const original of [true, false]) {
  const q = { id: 'question', practice_enabled: original };
  let focused = false;
  const checkbox = { checked: !original, isConnected: true, focus: () => { focused = true; } };
  context.confirmPracticeChange(q, checkbox);
  const dialog = dialogs.at(-1);
  assert.strictEqual(checkbox.checked, original, 'Checkbox must retain saved state until confirmation');
  assert(dialog.open);
  const message = dialog.children[1].children[0];
  assert(message.includes(original ? 'không thể tiếp tục' : 'cho phép sinh viên'));
  const [cancel, confirm] = dialog.children[2].children;
  assert.strictEqual(cancel.children[0], 'Hủy bỏ');
  assert.strictEqual(confirm.children[0], 'Xác nhận');
  const previousCalls = calls.length;
  cancel.attrs.on.click();
  assert.strictEqual(calls.length, previousCalls, 'Cancel must not save');
  assert(focused);
  checkbox.checked = !original;
  context.confirmPracticeChange(q, checkbox);
  dialogs.at(-1).children[2].children[1].attrs.on.click();
  assert.strictEqual(calls.length, previousCalls + 1);
  assert.strictEqual(calls.at(-1).enabled, !original);
  checkbox.checked = !original;
  context.confirmPracticeChange(q, checkbox);
  dialogs.at(-1).close();
  assert.strictEqual(calls.length, previousCalls + 1, 'Dismissing the dialog must not save');
}

async function testSave() {
  const saving = new Set();
  const requests = [];
  const errors = [];
  const saveContext = vm.createContext({
    practiceSaving: saving,
    renderList() {},
    toEditorQuestion: q => ({ ...q }),
    buildPayload: (draft, original) => ({ ...draft, expected_version: original.version }),
    post: async (url, payload) => { requests.push({ url, payload }); return { saved: false }; },
    mutate: async action => { try { await action(); } catch (error) { errors.push(error); } },
  });
  vm.runInContext(source.slice(source.indexOf('  async function savePracticeChange('), source.indexOf('  function duplicate(')), saveContext);
  const q = { id: 'q1', status: 'published', version: 2, reference_source: 'sample', practice_enabled: true };
  await saveContext.savePracticeChange(q, false);
  assert.strictEqual(requests[0].payload.practice_enabled, false);
  assert.strictEqual(requests[0].payload.expected_version, 2);
  assert.strictEqual(requests[0].payload.sample_source, 'sample');
  assert.strictEqual(q.practice_enabled, true, 'A failed save must not alter the saved checkbox state');
  assert.strictEqual(errors.length, 1, 'Rejected validation must surface as an error');
  assert.strictEqual(saving.size, 0);
  await saveContext.savePracticeChange({ ...q, status: 'archived' }, false);
  assert.strictEqual(requests.length, 1, 'Archived questions must not be updated');
}
testSave().then(() => console.log('Question practice confirmation tests passed.')).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
