// Regression: legacy comparable checks must survive the real editor/test-payload conversions.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(path.join(__dirname, '../static/js/questions.js'), 'utf8');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, '../test-data/grading-questions/R03.json'), 'utf8'));
const check = fixture.checks.find((item) => item.id === 'r03-ordering');
assert(check, 'R03 fixture contains r03-ordering');

const slice = (from, to) => {
  const start = source.indexOf(from);
  const end = source.indexOf(to, start);
  assert(start >= 0 && end > start, `source section found: ${from}`);
  return source.slice(start, end);
};
const editorHelpers = slice('  const splitList =', '  function toEditorQuestion(question)');
const editorQuestion = slice('  function toEditorQuestion(question)', '  let editing = null');
const payloadBuilder = slice('  function buildPayload()', '  function refreshTotalOn(d)');

const context = vm.createContext({});
vm.runInContext(`
  const SERVER_OWNED = ["id", "status", "source", "usage_count", "version", "validation", "reference_source", "sample_source", "practice_revision", "expected_version", "expected_practice_revision"];
  let editing = null;
  function refreshTotalOn(_draft) {}
  ${editorHelpers}
  ${editorQuestion}
  ${payloadBuilder}
  globalThis.runImportedQuestionThroughEditor = (input) => {
    const imported = { language: "java", grading_mode: "reflection", checks: [], ...input };
    for (const key of SERVER_OWNED) delete imported[key];
    editing = { draft: toEditorQuestion(imported), original: null };
    return buildPayload();
  };
`, context);

const payload = context.runImportedQuestionThroughEditor(fixture);
const sent = JSON.parse(JSON.stringify(payload.checks.find((item) => item.id === 'r03-ordering')));
assert.deepStrictEqual(sent, check, 'Teacher Test payload preserves the original comparable check verbatim');
assert.strictEqual(sent.instances.length, 3);
assert.deepStrictEqual(sent.comparisons, [
  { left: 1, right: 0, expected_sign: -1 },
  { left: 2, right: 0, expected_sign: -1 },
]);
assert.deepStrictEqual(sent.expected_order, [1, 2, 0]);
console.log('R03 comparable import/editor/Teacher Test round-trip passed');
