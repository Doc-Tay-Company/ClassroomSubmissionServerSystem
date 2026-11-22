const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const tick = () => new Promise((resolve) => setImmediate(resolve));
const handlers = new Map();
const nodes = new Map();
const node = (id) => {
  if (!nodes.has(id)) nodes.set(id, { id, textContent: '', innerHTML: '', value: '', href: '', classList: { add() {}, remove() {}, toggle() {} }, style: {}, addEventListener(type, fn) { handlers.set(`${id}:${type}`, fn); }, removeAttribute(name) { if (name === 'href') this.href = ''; }, querySelector() { return null; } });
  return nodes.get(id);
};
const monitorBody = node('monitor-body');
const dialog = node('monitor-history-modal');
dialog.open = false;
dialog.showModal = () => { dialog.open = true; };
dialog.close = () => { dialog.open = false; handlers.get('monitor-history-modal:close')?.(); };
const content = node('monitor-history-content');

const attempt = { student_id: 'student-7', release_id: 'release-3' };
const makeRow = (seq) => ({
  student_id: attempt.student_id, full_name: 'Nguyen An', logged_in: true, exam_file: 'midterm',
  monitoring_attempt: attempt, latest_event_seq: seq,
  event_counters: { window_blur: Math.min(seq, 2), document_hidden: 0, multiple_tabs_detected: seq >= 3 ? 1 : 0, fullscreen_refused: seq >= 4 ? 1 : 0, fullscreen_request_failed: seq >= 5 ? 1 : 0, fullscreen_lost: seq >= 6 ? 1 : 0 }, alerts: ['recorded_window_blur'],
});
let currentSeq = 1;
const eventRequests = [];
const eventForSeq = (seq) => ({
  seq, event_id: `event-${seq}`, event_type: seq < 3 ? 'window_blur' : ['multiple_tabs_detected', 'fullscreen_refused', 'fullscreen_request_failed', 'fullscreen_lost'][seq - 3], received_at: '2026-11-17T01:02:03Z',
  source: 'student_browser', client_occurred_at: '2026-11-17T01:02:00Z',
});
const window = {
  cssEscape: (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]),
  cssToast() {},
  setInterval() {},
  confirm() { return false; },
  prompt() { return null; },
  cssRequest: async (url) => {
    if (url === '/api/admin/monitor') return { students: [makeRow(currentSeq)], occurred_at: '2026-11-17T01:02:03Z', online_count: 1 };
    if (url === '/api/admin/exam-records') return { exams: [{ id: 'exam-current', status: 'started', release: { release_id: 'release-3' } }] };
    if (url.startsWith('/api/admin/monitor/events?')) {
      const params = new URLSearchParams(url.split('?')[1]);
      eventRequests.push(Number(params.get('after_seq')));
      const seq = Number(params.get('after_seq')) + 1;
      return { events: seq <= currentSeq ? [eventForSeq(seq)] : [], has_more: false };
    }
    throw new Error(`Unexpected request: ${url}`);
  },
};
const document = {
  getElementById(id) { return id === 'monitor-body' ? monitorBody : id === 'monitor-history-modal' ? dialog : id === 'monitor-history-content' ? content : id === 'monitor-return-exam' ? node(id) : id === 'refresh-monitor' ? node(id) : null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  body: { addEventListener(type, fn) { handlers.set(`body:${type}`, fn); } },
};

vm.runInNewContext(fs.readFileSync('static/js/admin.js', 'utf8'), { window, document, URLSearchParams, Date, Map, Promise, Number, String, Math, FormData: class {} });

(async () => {
  await tick();
  await tick();
  assert.strictEqual(node('monitor-return-exam').href, '/admin?section=exam&id=exam-current', 'Monitoring links directly to the matching General Exam');
  assert(monitorBody.innerHTML.includes('<summary>Xem chi tiết</summary>'), 'disclosure uses only the required label');
  assert(monitorBody.innerHTML.includes('<details class="monitor-event-history"'), 'native disclosure arrow remains');
  assert(!monitorBody.innerHTML.includes('<ol>'), 'event history is not rendered inline');
  assert(!monitorBody.innerHTML.includes('Sự kiện kỹ thuật ('), 'disclosure does not show totals');
  assert(monitorBody.innerHTML.includes('Đã ghi nhận mất focus'), 'existing warning badge remains');

  const key = JSON.stringify([attempt.student_id, attempt.release_id]);
  const target = { closest(selector) { return selector === 'details[data-monitor-history]' ? { dataset: { monitorHistory: key } } : null; } };
  handlers.get('monitor-body:click')({ target, preventDefault() {} });
  assert.strictEqual(dialog.open, true, 'clicking the disclosure opens the modal');
  assert(content.innerHTML.includes('Chi tiết sự kiện') === false, 'heading is supplied by the modal template');
  assert(content.innerHTML.includes('Nguyen An') && content.innerHTML.includes('student-7'), 'modal identifies the selected Student');
  assert(content.innerHTML.includes('Release: release-3'), 'modal identifies the selected attempt');
  assert(content.innerHTML.includes('#1 · Mất focus cửa sổ'), 'modal shows sequence and localized event type');
  assert(content.innerHTML.includes('Nguồn: student_browser'), 'modal shows only recorded technical provenance');
  assert(content.innerHTML.includes('17/11/2026'), 'server event timestamp is formatted for display');

  currentSeq = 2;
  await handlers.get('refresh-monitor:click')();
  assert(content.innerHTML.includes('#2 · Mất focus cửa sổ'), 'open modal refreshes when incremental synchronization receives new events');
  assert.deepStrictEqual(eventRequests, [0, 1], 'history polling fetches only new sequence entries');
  assert(content.innerHTML.includes('Focus: <strong>2</strong>'), 'modal counters refresh without reopening');

  for (const label of ['Phát hiện nhiều trang ứng dụng', 'Từ chối toàn màn hình', 'Yêu cầu toàn màn hình thất bại (kỹ thuật)', 'Rời chế độ toàn màn hình']) {
    currentSeq++;
    await handlers.get('refresh-monitor:click')();
    assert(content.innerHTML.includes(label), 'modal displays new technical event types and their counters');
  }
  assert.deepStrictEqual(eventRequests, [0, 1, 2, 3, 4, 5], 'new types keep incremental synchronization');

  handlers.get('monitor-history-modal:click')({ target: { closest(selector) { return selector === '[data-monitor-history-close]' ? {} : null; } } });
  assert.strictEqual(dialog.open, false, 'close control closes the modal');
  assert.strictEqual(eventRequests.length, 6, 'closing the modal does not request or reset history');
  console.log('Teacher Monitoring history modal tests passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
