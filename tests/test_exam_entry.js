const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const tick = () => new Promise((resolve) => setImmediate(resolve));
function setup(tabs = 1, zipExam = false) {
  const nodes = {};
  for (const id of ['start-exam', 'student-panel', 'exam-tab-warning', 'exam-tab-cancel', 'exam-tab-continue', 'exam-fullscreen-gate', 'exam-fullscreen-message', 'exam-fullscreen-choices', 'exam-fullscreen-return', 'exam-fullscreen-agree', 'exam-fullscreen-refuse']) {
    nodes[id] = { open: false, hidden: false, handlers: {}, addEventListener(t, fn) { this.handlers[t] = fn; }, showModal() { this.open = true; }, close() { this.open = false; this.handlers.close?.(); }, click() { return this.handlers.click?.(); } };
  }
  nodes['student-panel'].dataset = { zipExam: zipExam ? 'true' : 'false' };
  const listeners = {};
  const headerClasses = new Set();
  nodes['student-header-actions'] = { classList: { toggle(name, enabled) { if (enabled) headerClasses.add(name); else headerClasses.delete(name); }, contains(name) { return headerClasses.has(name); } } };
  const events = [], starts = [], errors = [], timers = new Map();
  let timerId = 0, reloads = 0, failStart = false;
  const document = { documentElement: {}, fullscreenElement: null, getElementById: (id) => nodes[id], addEventListener: (t, fn) => { listeners[t] = fn; } };
  const window = { addEventListener(t, fn) { listeners[t] = fn; }, setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; }, clearTimeout(id) { timers.delete(id); } };
  vm.runInNewContext(fs.readFileSync('static/js/exam-entry.js', 'utf8'), { window, document, Date, Number, Math });
  const controller = window.createExamEntry({ getTabCount: () => tabs, startRequest: async (confirmed) => { starts.push(confirmed); if (failStart) throw new Error('wrong password'); }, recordEvent: (type) => events.push(type), reload: () => { reloads++; }, reportError: (e) => errors.push(e.message) });
  return { nodes, document, events, starts, errors, listeners, controller, timers, failStart: () => { failStart = true; }, reloads: () => reloads, flushTransitions: () => { for (const [id, timer] of timers) if (timer.ms === 0) { timers.delete(id); timer.fn(); } } };
}
const active = { active_exam_attempt: true, release_id: 'release-A', ends_at: '2030-01-01T01:00:00Z', server_time: '2030-01-01T00:00:00Z' };
(async () => {
  const single = setup();
  single.nodes['start-exam'].click(); single.nodes['start-exam'].click(); await tick();
  assert.deepStrictEqual(single.starts, [false]); assert.equal(single.reloads(), 1);
  const multi = setup(2);
  multi.nodes['start-exam'].click(); assert(multi.nodes['exam-tab-warning'].open);
  multi.nodes['exam-tab-cancel'].click(); assert.equal(multi.starts.length, 0); assert.equal(multi.events.length, 0);
  multi.nodes['start-exam'].click(); multi.nodes['exam-tab-continue'].click(); multi.nodes['exam-tab-continue'].click(); await tick();
  assert.deepStrictEqual(multi.starts, [true]); assert.equal(multi.reloads(), 1);
  const failed = setup(2); failed.failStart(); failed.nodes['start-exam'].click(); failed.nodes['exam-tab-continue'].click(); await tick();
  assert.equal(failed.reloads(), 0); assert.equal(failed.events.length, 0); assert.equal(failed.nodes['start-exam'].disabled, false);

  const zipStart = setup(2, true);
  zipStart.nodes['start-exam'].click(); await tick();
  assert(!zipStart.nodes['exam-tab-warning'].open, 'ZIP exams skip behavioral multi-tab precheck');
  assert.deepStrictEqual(zipStart.starts, [false]);
  assert.equal(zipStart.events.length, 0);

  const s = setup(), gate = s.nodes['exam-fullscreen-gate'], workspace = s.nodes['student-panel'];
  s.controller.setStatus({ active_exam_attempt: false }); assert(!gate.open);
  s.controller.setStatus(active); assert(gate.open && workspace.inert); assert.equal(s.events.length, 0);
  let prevented = false; gate.handlers.cancel({ preventDefault() { prevented = true; } }); assert(prevented && gate.open);
  gate.close(); assert(gate.open, 'programmatic/default close cannot bypass the gate');
  s.nodes['exam-fullscreen-refuse'].click(); assert.deepStrictEqual(s.events, ['fullscreen_refused']); assert(workspace.inert);
  s.controller.setStatus(active); assert(s.nodes['exam-fullscreen-choices'].hidden, 'polling preserves refusal recovery state');
  s.nodes['exam-fullscreen-return'].click(); assert(!s.nodes['exam-fullscreen-choices'].hidden);
  s.document.documentElement.requestFullscreen = async () => { throw new Error('permission'); };
  await s.nodes['exam-fullscreen-agree'].click(); assert(workspace.inert); assert(s.events.includes('fullscreen_request_failed'));
  s.nodes['exam-fullscreen-return'].click();
  let requested = false;
  s.document.documentElement.requestFullscreen = async () => { requested = true; s.document.fullscreenElement = s.document.documentElement; s.listeners.fullscreenchange(); };
  const request = s.nodes['exam-fullscreen-agree'].click(); assert(requested, 'request is invoked directly before awaiting'); await request;
  assert(!gate.open && !workspace.inert);
  assert(s.nodes['student-header-actions'].classList.contains('hidden'), 'active Fullscreen hides navigation');
  s.document.fullscreenElement = null; s.listeners.fullscreenchange(); s.listeners.fullscreenchange(); s.flushTransitions();
  assert(gate.open && workspace.inert); assert.equal(s.events.filter((e) => e === 'fullscreen_lost').length, 1);
  assert(!s.nodes['student-header-actions'].classList.contains('hidden'), 'exit restores navigation');
  s.controller.setStatus(active); assert.equal(s.events.filter((e) => e === 'fullscreen_lost').length, 1);
  s.controller.setStatus({ active_exam_attempt: false }); assert(!gate.open && !workspace.inert);
  assert(!s.nodes['student-header-actions'].classList.contains('hidden'));
  const restored = setup(); restored.controller.setStatus(active); assert(restored.nodes['exam-fullscreen-gate'].open); assert.equal(restored.events.length, 0, 'F5/reauth baseline does not create a lost event');
  const zip = setup(); zip.controller.setStatus({ ...active, exam_file: 'exam.zip' });
  assert(!zip.nodes['exam-fullscreen-gate'].open && !zip.nodes['student-panel'].inert, 'ZIP attempts do not activate the Fullscreen Gate');
  restored.document.documentElement.requestFullscreen = async () => { restored.document.fullscreenElement = restored.document.documentElement; restored.listeners.fullscreenchange(); };
  await restored.nodes['exam-fullscreen-agree'].click(); restored.listeners.pagehide(); restored.document.fullscreenElement = null; restored.listeners.fullscreenchange(); restored.flushTransitions(); assert.equal(restored.events.length, 0, 'unload is not a fullscreen loss');
  console.log('PASS Exam entry: precheck/cancel/continue/retry, gate/refuse/failure/exit, reload/end');
})().catch((error) => { console.error(error); process.exitCode = 1; });
