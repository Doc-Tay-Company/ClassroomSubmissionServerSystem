// Focused browser-context harness for Phase 2 Checkpoint 2.
// Each tab has its own VM/DOM/sessionStorage and shares localStorage.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

class Storage {
  constructor() { this.data = Object.create(null); }
  getItem(k) { return Object.prototype.hasOwnProperty.call(this.data, k) ? this.data[k] : null; }
  setItem(k, v) { this.data[k] = String(v); }
  removeItem(k) { delete this.data[k]; }
  clear() { this.data = Object.create(null); }
  key(i) { return Object.keys(this.data)[i] || null; }
  get length() { return Object.keys(this.data).length; }
}

class Element {
  constructor(id = '') {
    this.id = id; this.value = ''; this.disabled = false; this.dataset = {};
    this.textContent = ''; this._html = ''; this.className = ''; this.listeners = {};
    this.children = []; this.style = {}; this.attributes = {};
    const values = new Set();
    this.classList = {
      add: (v) => values.add(v), remove: (v) => values.delete(v),
      contains: (v) => values.has(v),
      toggle: (v, force) => { if (force === undefined) force = !values.has(v); force ? values.add(v) : values.delete(v); return force; },
    };
  }
  set innerHTML(value) {
    this._html = String(value); this.children = [];
    for (const cls of ['modal-update-btn','modal-open-ws-btn','modal-delete-btn','modal-close-btn']) {
      if (this._html.includes(cls)) {
        const child = new Element(); child.classList.add(cls); child.className = cls; this.children.push(child);
      }
    }
  }
  get innerHTML() { return this._html; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  async dispatchEvent(evt) { for (const fn of this.listeners[evt.type] || []) await fn(evt); }
  showModal() { this.open = true; }
  close() { this.open = false; void this.dispatchEvent({ type: 'close' }); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const cls = selector.startsWith('.') ? selector.slice(1).split(/[.[\s]/)[0] : null;
    return this.children.filter((e) => cls && e.classList.contains(cls));
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] ?? null; }
}

const ids = [
  'practice-root','practice-library-view','practice-workspace-view','practice-catalog-list','practice-catalog-count',
  'practice-last-updated','practice-catalog-empty','practice-catalog-error','practice-notice','practice-search',
  'practice-lang-filter','practice-diff-filter','practice-refresh-btn','practice-back-to-library-btn','practice-ws-title',
  'practice-ws-lang-badge','practice-ws-diff-badge','practice-ws-cat-badge','practice-ws-points','practice-retest-badge',
  'practice-ws-statement','practice-ws-target-section','practice-ws-target-info','practice-ws-starter-section',
  'practice-ws-starter-code','practice-ws-tests-table-host','practice-editor-lang-label','practice-editor-filename',
  'practice-code-editor','practice-restore-starter-btn','practice-run-btn','practice-editor-alert','practice-run-result',
  'practice-storage-warning','practice-revision-notice','practice-revision-notice-text','practice-retry-details-btn',
  'practice-ws-update-btn','practice-modal-host','practice-nav-exam',
];
const script = fs.readFileSync(path.join(__dirname, '../static/js/student-practice.js'), 'utf8');
const question = (id, rev = 'rev-1') => ({ question_id:id, title:`Question ${id}`, statement:`Statement ${id}`,
  starter_code:`starter-${id}`, practice_revision:rev, version:1, language:'python', tests:[] });

function createTab({student='student-1', sharedStorage=new Storage(), tabSession=new Storage(), request=async () => ({}), statusRequest=async () => ({active_exam_attempt:false})} = {}) {
  const elements = Object.fromEntries(ids.map((id) => [id, new Element(id)]));
  for (const id of ['practice-lock-dialog','practice-lock-title','practice-lock-message']) elements[id] = new Element(id);
  elements['practice-root'].dataset.studentId = student;
  const documentListeners = {}, windowListeners = {};
  const document = { readyState:'complete', visibilityState:'visible', getElementById:(id) => elements[id] || null,
    createElement:() => new Element(), addEventListener:(type, fn) => { (documentListeners[type] ||= []).push(fn); }, querySelectorAll:() => [] };
  const window = { document, localStorage:sharedStorage, sessionStorage:tabSession, location:{hash:''},
    cssRequest:(url, options) => url === '/api/student/status' ? statusRequest() : request(url, options), cssEscape:(v) => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])), confirm:() => true, alert:() => {},
    addEventListener:(type, fn) => { (windowListeners[type] ||= []).push(fn); }, removeEventListener:() => {}, setTimeout, clearTimeout, setInterval, clearInterval,
    crypto:null };
  const context = { window, document, localStorage:sharedStorage, console, setTimeout, clearTimeout,
    Uint8Array, Math, JSON, Number, String, Boolean, encodeURIComponent, decodeURIComponent, alert:() => {}, confirm:() => true };
  vm.createContext(context); vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/practice-lock.js'), 'utf8'), context); vm.runInContext(script, context);
  return { window, document, documentListeners, windowListeners, elements, storage:sharedStorage, session:tabSession, api:window.PracticeWorkspace };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function main() {
  console.log('Practice workspace and Run integration regressions');

  // CP3: Run is initially disabled until question details and a current attempt exist.
  const runTab = createTab();
  assert.strictEqual(runTab.elements['practice-run-btn'].disabled, true);
  assert.strictEqual((runTab.elements['practice-run-btn'].listeners.click || []).length, 1);
  assert.strictEqual(typeof runTab.api.handleCompletedRun, 'undefined');
  assert(!/setTimeout\s*\(\s*\(\)\s*=>\s*\{\s*setRunButtonProcessing/.test(script));
  const template = fs.readFileSync(path.join(__dirname, '../templates/practice.html'), 'utf8');
  assert(/id="practice-run-btn"[^>]*\bdisabled\b/.test(template));
  assert(script.includes('request("/api/student/practice/run"'));
  console.log('PASS CP3 Run starts disabled and uses the real Practice API path');

  const targetTab = createTab({request:async (url) => {
    if (url.endsWith('/questions/qTarget')) return {question:{...question('qTarget'),grading_mode:'reflection',
      target_package:'model',target_class:'model.Book',target_file:'Book.java'}};
    if (url.endsWith('/run-status')) return {active:false};
    return {progress:[]};
  }});
  await targetTab.api.openWorkspace('qTarget');
  const targetInfo = targetTab.elements['practice-ws-target-info'].innerHTML;
  assert(targetInfo.includes('<span class="practice-target-label">Package</span><code>model</code>'));
  assert(targetInfo.includes('<span class="practice-target-label">Class</span><code>model.Book</code>'));
  assert(targetInfo.includes('<span class="practice-target-label">File</span><code>Book.java</code>'));
  console.log('PASS Java target details render as compact labeled rows');

  // Previously attempted questions keep opening their existing local source from the preview.
  const existingStorage = new Storage(), existingSession = new Storage();
  const existingId = 'a'.repeat(32);
  let attemptedDetailFetched = false;
  const attemptedTab = createTab({sharedStorage:existingStorage,tabSession:existingSession,request:async (url) => {
    if (url.endsWith('/questions/q1')) { attemptedDetailFetched = true; return {question:question('q1')}; }
    if (url.endsWith('/progress')) return {progress:[]};
    return {active:false};
  }});
  attemptedTab.api.saveDraftToStorage('q1', existingId, {attempt_id:existingId,source_code:'existing source',needs_retest:false});
  assert.strictEqual(attemptedTab.api.loadDraftFromStorage('q1', existingId).source_code,'existing source');
  const attemptedItem={question_id:'q1',title:'Question q1',language:'python',available:true,practice_revision:'rev-1',
    progress:{has_result:true,attempt_id:existingId,practice_revision:'rev-1',practice_percentage:0,score_available:true}};
  attemptedTab.api.setCatalog([attemptedItem]);
  attemptedTab.api.openPreviewModal(attemptedItem);
  assert.strictEqual(attemptedTab.elements['practice-modal-host'].querySelector('.modal-redo-btn'),null);
  assert(!/Redo|Làm lại/i.test(attemptedTab.elements['practice-modal-host'].innerHTML));
  await attemptedTab.elements['practice-modal-host'].querySelector('.modal-open-ws-btn').dispatchEvent({type:'click'});
  await tick();
  assert(attemptedDetailFetched);
  assert.strictEqual(attemptedTab.api.getCurrentAttemptId(),existingId);
  assert.strictEqual(attemptedTab.elements['practice-code-editor'].value,'existing source');
  attemptedTab.elements['practice-code-editor'].value='edited existing attempt';
  await attemptedTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  assert.strictEqual(attemptedTab.api.getCurrentAttemptId(),existingId);
  attemptedTab.elements['practice-restore-starter-btn'].dispatchEvent({type:'click'});
  assert.strictEqual(attemptedTab.elements['practice-code-editor'].value,'starter-q1');
  assert.strictEqual(attemptedTab.api.getCurrentAttemptId(),existingId);
  assert.strictEqual(attemptedTab.api.getNeedsRetest(),true,'Reset Code remains an edit in the current attempt');
  assert(!script.includes('handleRedo'));
  assert(!script.includes('/redo'));
  assert(!template.includes('practice-ws-redo-btn'));
  console.log('PASS attempted preview opens existing work; Redo is absent and Reset Code remains');

  // BUG-01: stale Library revision is ignored; Update uses current detail + server progress.
  let updateBody, qBProgressRevision='rev-1';
  const qTab = createTab({request:async (url, opts={}) => {
    if (url.endsWith('/update')) {
      updateBody = JSON.parse(opts.body);
      if (updateBody.new_practice_revision !== 'rev-3') { const e=new Error('revision mismatch'); e.status=409; throw e; }
      qBProgressRevision='rev-3';
      return {ok:true};
    }
    if (url.endsWith('/questions/qA')) return {question:question('qA')};
    if (url.endsWith('/questions/qB')) return {question:question('qB','rev-3')};
    if (url.endsWith('/progress')) return {progress:[{question_id:'qB',available:true,practice_revision:'rev-3',
      progress:{has_result:qBProgressRevision!=='rev-3' ? true : false,attempt_id:idB,practice_revision:qBProgressRevision,practice_percentage:75,score_available:true}}]};
    return {progress:[]};
  }});
  const idA = 'b'.repeat(32), idB = 'c'.repeat(32);
  await qTab.api.openWorkspace('qA');
  qTab.api.saveDraftToStorage('qB', idB, {question_id:'qB',attempt_id:idB,source_code:'B source',needs_retest:false});
  await qTab.api.showLibraryView();
  const qBItem={question_id:'qB',title:'Question qB',language:'python',available:true,practice_revision:'rev-2',version:2,
    progress:{has_result:true,attempt_id:idB,practice_revision:'rev-1',practice_percentage:75,score_available:true}};
  qTab.api.setCatalog([qBItem]);
  qTab.api.openPreviewModal(qBItem);
  await qTab.elements['practice-modal-host'].querySelector('.modal-update-btn').dispatchEvent({type:'click'});
  assert.strictEqual(updateBody.expected_attempt_id,idB);
  assert.notStrictEqual(updateBody.expected_attempt_id,idA);
  assert.strictEqual(updateBody.old_practice_revision,'rev-1');
  assert.strictEqual(updateBody.new_practice_revision,'rev-3','Update must submit the fresh Question Bank revision, not cached Library rev-2');
  assert.strictEqual(qTab.api.getCurrentQuestion().question_id,'qB');
  assert.strictEqual(qTab.elements['practice-code-editor'].value,'B source');
  assert.strictEqual(qTab.api.getCurrentAttemptId(),idB);
  assert.strictEqual(qTab.api.getNeedsRetest(),true,'successful Update invalidates the previous result');
  console.log('PASS BUG-01 Update uses fresh revision and selected question B attempt while preserving source');

  // C2-F04: true tab separation; shared localStorage, separate sessionStorage and JS/DOM contexts.
  const shared = new Storage(), sessionA = new Storage(), sessionB = new Storage();
  let tabMutationRequests = 0;
  let serverAttempt = null, successfulRunRequest = null;
  const detailRequest = async (url, opts={}) => {
    if (/\/(update|run)$/.test(url)) tabMutationRequests++;
    if (url.endsWith('/questions/q1')) return {question:question('q1')};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:serverAttempt,practice_revision:'rev-1'};
    if (url.endsWith('/progress')) return {progress:serverAttempt ? [{question_id:'q1',available:true,practice_revision:'rev-1',
      progress:{attempt_id:serverAttempt,practice_revision:'rev-1',has_result:false}}] : []};
    if (url === '/api/student/practice/run') {
      successfulRunRequest=JSON.parse(opts.body || '{}');
      serverAttempt=successfulRunRequest.attempt_id;
      return {completed:true,attempt_id:successfulRunRequest.attempt_id,practice_revision:'rev-1',score_available:true,
        practice_percentage:100,earned_visible_points:1,maximum_visible_points:1,results:[]};
    }
    return {};
  };
  const tabA = createTab({sharedStorage:shared,tabSession:sessionA,request:detailRequest});
  const tabB = createTab({sharedStorage:shared,tabSession:sessionB,request:detailRequest});
  await Promise.all([tabA.api.openWorkspace('q1'),tabB.api.openWorkspace('q1')]);
  assert.strictEqual(tabA.api.getCurrentAttemptId(),null);
  assert.strictEqual(tabB.api.getCurrentAttemptId(),null);
  tabA.elements['practice-code-editor'].value='source A';
  await tabA.elements['practice-code-editor'].dispatchEvent({type:'input'});
  tabB.elements['practice-code-editor'].value='source B';
  await tabB.elements['practice-code-editor'].dispatchEvent({type:'input'});
  const attemptA=tabA.api.getCurrentAttemptId(), attemptB=tabB.api.getCurrentAttemptId();
  assert.notStrictEqual(attemptA,attemptB);
  assert.strictEqual(Object.keys(shared.data).filter(k=>k.includes(':q1:tab:')).length,2);
  serverAttempt=attemptA; // Tab A's first accepted Run established the shared server attempt.
  const refreshA=createTab({sharedStorage:shared,tabSession:sessionA,request:detailRequest});
  const refreshB=createTab({sharedStorage:shared,tabSession:sessionB,request:detailRequest});
  await Promise.all([refreshA.api.openWorkspace('q1'),refreshB.api.openWorkspace('q1')]);
  assert.strictEqual(refreshA.elements['practice-code-editor'].value,'source A');
  assert.strictEqual(refreshB.elements['practice-code-editor'].value,'source B');
  assert.strictEqual(refreshA.api.getCurrentAttemptId(),attemptA);
  assert.strictEqual(refreshB.api.getCurrentAttemptId(),attemptA,'Tab B adopts server attempt A automatically');
  assert.strictEqual(refreshB.api.loadDraftFromStorage('q1',attemptA).source_code,'source B','only attempt metadata changes; Tab B source stays local');
  assert.strictEqual(refreshA.api.getNeedsRetest(),true);
  assert.strictEqual(refreshB.api.getNeedsRetest(),true);
  const q2Attempt='e'.repeat(32);
  tabA.api.saveDraftToStorage('q2',q2Attempt,{attempt_id:q2Attempt,source_code:'question 2 source'});
  assert.strictEqual(tabA.api.loadDraftFromStorage('q1',attemptA).source_code,'source A');
  assert.strictEqual(tabA.api.loadDraftFromStorage('q2',q2Attempt).source_code,'question 2 source');
  assert.strictEqual(tabMutationRequests,0,'opening/editing in tabs must not create server attempts');
  assert.strictEqual(refreshB.elements['practice-run-btn'].disabled,false,'recovered tab can run after status check');
  const recoveredRun=refreshB.elements['practice-run-btn'].dispatchEvent({type:'click'});
  await recoveredRun;
  assert.strictEqual(successfulRunRequest.attempt_id,attemptA);
  assert.strictEqual(successfulRunRequest.source_code,'source B');
  assert.strictEqual(refreshB.api.getCurrentAttemptId(),attemptA);
  const otherStudent=createTab({student:'student-2',sharedStorage:shared,tabSession:new Storage(),request:async (url) => {
    if (url.endsWith('/questions/q1')) return {question:question('q1')};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:null,practice_revision:null};
    if (url.endsWith('/progress')) return {progress:[]};
    return {};
  }});
  await otherStudent.api.openWorkspace('q1');
  assert.strictEqual(otherStudent.api.getCurrentAttemptId(),null,'another student has no shared attempt');
  otherStudent.elements['practice-code-editor'].value='student 2 source';
  await otherStudent.elements['practice-code-editor'].dispatchEvent({type:'input'});
  assert.notStrictEqual(otherStudent.api.getCurrentAttemptId(),attemptA);
  assert.strictEqual(otherStudent.api.loadDraftFromStorage('q1',otherStudent.api.getCurrentAttemptId()).source_code,'student 2 source');
  assert.strictEqual(tabA.api.loadDraftFromStorage('q1',attemptA).source_code,'source A');
  console.log('PASS BUG-02 separate tab drafts recover independently while sharing the authoritative attempt');

  // A stale tab's Update adopts authoritative attempt metadata and keeps its source.
  let authoritative = attemptA, staleUpdateBody;
  const staleTab = createTab({sharedStorage:shared,tabSession:sessionB,request:async (url,opts={}) => {
    if (url.endsWith('/update')) {
      staleUpdateBody=JSON.parse(opts.body);
      if (staleUpdateBody.expected_attempt_id !== authoritative) { const e=new Error('stale'); e.status=409; throw e; }
      return {ok:true};
    }
    if (url.endsWith('/questions/q1')) return {question:question('q1','rev-2')};
    if (url.endsWith('/progress')) return {progress:[{question_id:'q1',available:true,practice_revision:'rev-2',progress:{
      attempt_id:authoritative,practice_revision:staleUpdateBody ? 'rev-2' : 'rev-1',has_result:false}}]};
    return {};
  }});
  staleTab.api.setCatalog([{question_id:'q1',available:true,practice_revision:'rev-2',progress:{attempt_id:attemptB,practice_revision:'rev-1'}}]);
  staleTab.api.saveDraftToStorage('q1',attemptB,{attempt_id:attemptB,source_code:'preserve B',needs_retest:true});
  await staleTab.api.handleUpdate('q1');
  assert.strictEqual(staleUpdateBody.expected_attempt_id,attemptA);
  assert.strictEqual(authoritative,attemptA);
  assert.strictEqual(staleTab.api.getCurrentAttemptId(),attemptA);
  assert.strictEqual(staleTab.api.loadDraftFromStorage('q1',attemptA).source_code,'preserve B');
  console.log('PASS stale-tab Update uses authoritative attempt and preserves local source');

  // BUG-02: if authority changes while a Run is in flight, reopening recovers the
  // attempt and the delayed old response cannot replace the current result.
  const inflightId='1'.repeat(32), newerId='2'.repeat(32), inflightStorage=new Storage(), inflightSession=new Storage();
  let inflightAuthority=inflightId, finishOldRun, oldRequestBody;
  const inflightRequest=async (url,opts={}) => {
    if (url.endsWith('/questions/qFlight')) return {question:question('qFlight')};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:inflightAuthority,practice_revision:'rev-1'};
    if (url.endsWith('/progress')) return {progress:[{question_id:'qFlight',available:true,practice_revision:'rev-1',progress:{
      attempt_id:inflightAuthority,practice_revision:'rev-1',has_result:false}}]};
    if (url === '/api/student/practice/run') {
      oldRequestBody=JSON.parse(opts.body);
      return new Promise((resolve) => { finishOldRun=resolve; });
    }
    return {};
  };
  const inflightTab=createTab({sharedStorage:inflightStorage,tabSession:inflightSession,request:inflightRequest});
  inflightTab.api.saveDraftToStorage('qFlight',inflightId,{question_id:'qFlight',attempt_id:inflightId,practice_revision:'rev-1',source_code:'in-flight source',needs_retest:true});
  await inflightTab.api.openWorkspace('qFlight');
  const oldRun=inflightTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  await tick();
  assert.strictEqual(oldRequestBody.attempt_id,inflightId);
  inflightAuthority=newerId;
  await inflightTab.api.openWorkspace('qFlight');
  assert.strictEqual(inflightTab.api.getCurrentAttemptId(),newerId);
  assert.strictEqual(inflightTab.elements['practice-code-editor'].value,'in-flight source');
  finishOldRun({completed:true,attempt_id:inflightId,practice_revision:'rev-1',score_available:true,practice_percentage:100,
    earned_visible_points:1,maximum_visible_points:1,results:[]});
  await oldRun;
  assert(!inflightTab.elements['practice-run-result'].innerHTML.includes('100%'));
  assert.strictEqual(inflightTab.api.getCurrentAttemptId(),newerId);
  assert.strictEqual(inflightTab.api.loadDraftFromStorage('qFlight',newerId).source_code,'in-flight source');
  console.log('PASS BUG-02 delayed old-attempt Run response cannot overwrite recovered state');

  // A stale Run rejection itself also fetches authoritative progress and recovers
  // without requiring refresh, logout, or a manual action.
  const retryOld='3'.repeat(32), retryCurrent='4'.repeat(32), retryStorage=new Storage(), retrySession=new Storage();
  let retryAuthority=retryOld, staleRunCount=0, acceptedRunBody;
  const retryAttemptTab=createTab({sharedStorage:retryStorage,tabSession:retrySession,request:async (url,opts={}) => {
    if (url.endsWith('/questions/qRetry')) return {question:question('qRetry')};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:retryAuthority,practice_revision:'rev-1'};
    if (url.endsWith('/progress')) return {progress:[{question_id:'qRetry',available:true,practice_revision:'rev-1',progress:{
      attempt_id:retryAuthority,practice_revision:'rev-1',has_result:false}}]};
    if (url === '/api/student/practice/run') {
      const body=JSON.parse(opts.body);
      if (staleRunCount++ === 0) { retryAuthority=retryCurrent; const e=new Error('stale attempt'); e.status=409; throw e; }
      acceptedRunBody=body;
      return {completed:true,attempt_id:body.attempt_id,practice_revision:'rev-1',score_available:true,practice_percentage:50,
        earned_visible_points:1,maximum_visible_points:2,results:[]};
    }
    return {};
  }});
  retryAttemptTab.api.saveDraftToStorage('qRetry',retryOld,{question_id:'qRetry',attempt_id:retryOld,practice_revision:'rev-1',source_code:'retry this code',needs_retest:true});
  await retryAttemptTab.api.openWorkspace('qRetry');
  await retryAttemptTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  assert.strictEqual(retryAttemptTab.api.getCurrentAttemptId(),retryCurrent);
  assert.strictEqual(retryAttemptTab.elements['practice-code-editor'].value,'retry this code');
  assert.strictEqual(retryAttemptTab.elements['practice-run-btn'].disabled,false,'Run is re-enabled after automatic recovery');
  await retryAttemptTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  assert.strictEqual(acceptedRunBody.attempt_id,retryCurrent);
  assert.strictEqual(acceptedRunBody.source_code,'retry this code');
  console.log('PASS BUG-02 stale Run rejection automatically recovers attempt and permits retry');

  // BUG-01 race: a newer Teacher revision lands after the fresh read but before Update commits.
  let racePayload, raceRevision='rev-C';
  const raceStorage=new Storage(), raceSession=new Storage(), raceId='f'.repeat(32);
  const raceTab=createTab({sharedStorage:raceStorage,tabSession:raceSession,request:async (url,opts={}) => {
    if (url.endsWith('/questions/qRace')) return {question:question('qRace','rev-B')};
    if (url.endsWith('/progress')) return {progress:[{question_id:'qRace',available:true,practice_revision:raceRevision,
      progress:{attempt_id:raceId,practice_revision:'rev-A',has_result:true,practice_percentage:60}}]};
    if (url.endsWith('/update')) { racePayload=JSON.parse(opts.body); const e=new Error('new revision arrived'); e.status=409; throw e; }
    return {};
  }});
  raceTab.api.saveDraftToStorage('qRace',raceId,{question_id:'qRace',attempt_id:raceId,practice_revision:'rev-A',source_code:'race source',needs_retest:true});
  await raceTab.api.handleUpdate('qRace');
  assert.strictEqual(racePayload.new_practice_revision,'rev-B');
  assert.strictEqual(raceTab.api.loadDraftFromStorage('qRace',raceId).source_code,'race source');
  assert.strictEqual(raceTab.api.loadDraftFromStorage('qRace',raceId).practice_revision,'rev-A');
  console.log('PASS BUG-01 revision conflict leaves tab-local source and revision metadata intact');

  // C2-F05: Update commits, detail fetch fails, editor/source remain; explicit retry succeeds.
  let detailCalls=0, updateAttempt, updateApplied=false;
  const updateSession=new Storage(), updateStorage=new Storage();
  const retryTab=createTab({sharedStorage:updateStorage,tabSession:updateSession,request:async (url,opts={}) => {
    if (url.endsWith('/update')) { updateAttempt=JSON.parse(opts.body).expected_attempt_id; updateApplied=true; return {ok:true}; }
    if (url.endsWith('/questions/q1')) { detailCalls++; if(detailCalls===3) throw new Error('temporary fetch failure'); return {question:question('q1','rev-2')}; }
    if (url.endsWith('/progress')) return {progress:[{question_id:'q1',available:true,practice_revision:'rev-2',progress:{
      attempt_id:runId,practice_revision:updateApplied?'rev-2':'rev-1',has_result:!updateApplied,practice_percentage:75}}]};
    return {progress:[]};
  }});
  const runId='d'.repeat(32);
  retryTab.api.setCatalog([{question_id:'q1',available:true,practice_revision:'rev-2',version:2,progress:{attempt_id:runId,practice_revision:'rev-1'}}]);
  await retryTab.api.openWorkspace('q1');
  retryTab.elements['practice-code-editor'].value='keep me';
  await retryTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  await retryTab.api.handleUpdate('q1');
  assert.strictEqual(updateAttempt,runId);
  assert.strictEqual(retryTab.elements['practice-code-editor'].value,'keep me');
  assert(retryTab.elements['practice-revision-notice-text'].textContent.includes('succeeded'));
  assert(!retryTab.elements['practice-retry-details-btn'].classList.contains('hidden'));
  assert.strictEqual(retryTab.elements['practice-run-btn'].disabled,true);
  await retryTab.elements['practice-retry-details-btn'].dispatchEvent({type:'click'});
  assert.strictEqual(retryTab.api.getCurrentQuestion().practice_revision,'rev-2');
  assert.strictEqual(retryTab.elements['practice-code-editor'].value,'keep me');
  assert(retryTab.elements['practice-retry-details-btn'].classList.contains('hidden'));
  console.log('PASS C2-F05 failed refresh preserves workspace and explicit retry loads current revision');

  // C2-F06: 0 is scored; null/invalid/unavailable percentages remain unscored in both preview paths.
  const scoreTab=createTab();
  const preview=(available,pct,scoreAvailable=true)=>scoreTab.api.openPreviewModal({question_id:'qS',title:'Score',language:'python',available,
    practice_revision:'rev-1',progress:{has_result:true,practice_percentage:pct,score_available:scoreAvailable,earned_visible_points:0,maximum_visible_points:10,result_summary:[]}});
  preview(true,0,true);
  assert(scoreTab.elements['practice-modal-host'].innerHTML.includes('0%'));
  preview(true,null,false);
  assert(!scoreTab.elements['practice-modal-host'].innerHTML.includes('0%'));
  assert(scoreTab.elements['practice-modal-host'].innerHTML.includes('Not scored'));
  preview(false,null,false);
  assert(!scoreTab.elements['practice-modal-host'].innerHTML.includes('0%'));
  assert(scoreTab.elements['practice-modal-host'].innerHTML.includes('Not scored'));
  preview(true,NaN,true);
  assert(!scoreTab.elements['practice-modal-host'].innerHTML.includes('NaN'));
  scoreTab.api.setCatalog([{question_id:'qScore',title:'Score',available:true,language:'python',version:1,
    progress:{has_result:true,score_available:false,practice_percentage:null}}]);
  assert(scoreTab.elements['practice-catalog-list'].innerHTML.includes('Not scored'));
  scoreTab.api.setCatalog([{question_id:'qScore',title:'Score',available:true,language:'python',version:1,
    progress:{has_result:true,score_available:true,practice_percentage:0}}]);
  assert(scoreTab.elements['practice-catalog-list'].innerHTML.includes('0%'));
  console.log('PASS C2-F06 zero and unscored states are distinct in available/unavailable previews');

  const feedbackTab=createTab();
  feedbackTab.api.openPreviewModal({question_id:'qFeedback',title:'Feedback',language:'python',available:true,practice_revision:'r1',
    progress:{has_result:true,score_available:true,practice_percentage:50,earned_visible_points:1,maximum_visible_points:2,
      result_summary:[{id:'visible-1',verdict:'WA',passed:false,points_earned:0,points:2,
        expected_output:'expected\n  line  ',actual_output:'<img src=x onerror=alert(1)>\nactual',diagnostic:'SyntaxError: invalid syntax'}]}});
  const feedbackHtml=feedbackTab.elements['practice-modal-host'].innerHTML;
  assert(feedbackHtml.includes('Expected output') && feedbackHtml.includes('expected\n  line  '));
  assert(feedbackHtml.includes('Actual output') && feedbackHtml.includes('0 / 2 points'));
  assert(feedbackHtml.includes('&lt;img') && !feedbackHtml.includes('<img src=x'));
  assert(feedbackHtml.includes('SyntaxError: invalid syntax'));
  console.log('PASS visible feedback is rendered with whitespace preserved and HTML escaped');

  // CP3: an invalid/missing scoring denominator displays unscored, never 0% or 0/0.
  const unscoredTab=createTab({request:async (url,opts={}) => {
    if (url.endsWith('/questions/qNoScore')) return {question:{...question('qNoScore','rev-zero'),starter_code:'starter-qNoScore'}};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:null,practice_revision:null};
    if (url.endsWith('/progress')) return {progress:[{question_id:'qNoScore',title:'Question qNoScore',language:'python',available:true,
      practice_revision:'rev-zero',progress:null}],catalog_token:'token-zero'};
    if (url === '/api/student/practice/run') return {ok:true,completed:true,question_id:'qNoScore',practice_revision:'rev-zero',
      attempt_id:JSON.parse(opts.body).attempt_id,run_sequence:1,verdict:'CE',earned_visible_points:0,
      maximum_visible_points:0,practice_percentage:null,score_available:false,results:[]};
    return {};
  }});
  unscoredTab.api.setCatalog([{question_id:'qNoScore',available:true,practice_revision:'rev-zero',progress:null}]);
  await unscoredTab.api.openWorkspace('qNoScore');
  unscoredTab.elements['practice-code-editor'].value='edited';
  await unscoredTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  await unscoredTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  const unscoredHtml=unscoredTab.elements['practice-run-result'].innerHTML;
  assert(unscoredHtml.includes('No visible test points can be scored'), unscoredHtml);
  assert(!unscoredHtml.includes('0%'));
  assert(!unscoredHtml.includes('0 / 0'));
  console.log('PASS CP3 missing visible denominator remains explicitly unscored');

  // CP3: first Run requires an edit/attempt; valid results render, and edits during a Run keep needs_retest.
  let finishRun, rejectRun, submittedRun, runCount = 0, catalogProgress = [{question_id:'qRun',title:'Question qRun',language:'python',available:true,
    practice_revision:'rev-run',progress:null}];
  const cp3RunTab = createTab({request:async (url, opts={}) => {
    if (url.endsWith('/questions/qRun')) return {question:{...question('qRun','rev-run'),starter_code:'starter-qRun',visible_points:5}};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:null,practice_revision:null};
    if (url.endsWith('/progress')) return {progress:catalogProgress};
    if (url === '/api/student/practice/run') {
      runCount += 1;
      submittedRun=JSON.parse(opts.body);
      return new Promise((resolve, reject) => { finishRun=resolve; rejectRun=reject; });
    }
    return {};
  }});
  cp3RunTab.api.setCatalog([{question_id:'qRun',available:true,practice_revision:'rev-run',progress:null}]);
  await cp3RunTab.api.openWorkspace('qRun');
  assert.strictEqual(cp3RunTab.elements['practice-run-btn'].disabled,true,'no attempt before the first edit');
  cp3RunTab.elements['practice-code-editor'].value='print(1)';
  await cp3RunTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  const editedAttempt=cp3RunTab.api.getCurrentAttemptId();
  assert(editedAttempt);
  assert.strictEqual(cp3RunTab.elements['practice-run-btn'].disabled,false);
  const runPromise=cp3RunTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  await tick();
  assert.strictEqual(submittedRun.attempt_id,editedAttempt);
  assert.strictEqual(submittedRun.source_code,'print(1)');
  assert.strictEqual(cp3RunTab.elements['practice-run-btn'].disabled,true,'button locks while request is pending');
  cp3RunTab.elements['practice-code-editor'].value='print(2)';
  await cp3RunTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  finishRun({ok:true,completed:true,question_id:'qRun',practice_revision:'rev-run',attempt_id:editedAttempt,
    run_sequence:1,verdict:'CE',earned_visible_points:0,maximum_visible_points:5,practice_percentage:0,score_available:true,results:[{id:'v1',verdict:'CE',passed:false,points_earned:0}]});
  await runPromise;
  assert.strictEqual(cp3RunTab.api.getNeedsRetest(),true,'newer editor source remains untested');
  assert(cp3RunTab.elements['practice-run-result'].innerHTML.includes('0%'),'valid zero score is shown');
  assert(cp3RunTab.elements['practice-run-result'].innerHTML.includes('changed since this result'));
  assert.strictEqual(cp3RunTab.elements['practice-run-btn'].disabled,false);
  console.log('PASS CP3 Run requires an edit, disables in flight, and preserves retest state for newer code');

  // A server error cannot erase the last displayed valid result or clear needs_retest.
  const lastResult = cp3RunTab.elements['practice-run-result'].innerHTML;
  cp3RunTab.elements['practice-code-editor'].value='print(3)';
  await cp3RunTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  const failedRun=cp3RunTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  await tick();
  rejectRun(new Error('JUDGE_INFRA_ERROR'));
  await failedRun;
  assert.strictEqual(cp3RunTab.api.getNeedsRetest(),true,'failed execution must retain needs_retest');
  assert.strictEqual(cp3RunTab.elements['practice-run-result'].innerHTML,lastResult);
  assert(cp3RunTab.elements['practice-editor-alert'].textContent.includes('JUDGE_INFRA_ERROR'));

  // A later valid completion replaces the previous result.
  const validRun=cp3RunTab.elements['practice-run-btn'].dispatchEvent({type:'click'});
  await tick();
  finishRun({ok:true,completed:true,question_id:'qRun',practice_revision:'rev-run',attempt_id:editedAttempt,
    run_sequence:2,verdict:'AC',earned_visible_points:5,maximum_visible_points:5,practice_percentage:100,score_available:true,results:[]});
  await validRun;
  assert.strictEqual(cp3RunTab.api.getNeedsRetest(),false,'valid result for unchanged current source clears needs_retest');
  assert(cp3RunTab.elements['practice-run-result'].innerHTML.includes('100%'));
  console.log('PASS CP3 infrastructure failure retains result; later valid Run replaces it');

  // Phase 3: token changes reconcile catalog/progress without replacing Workspace source.
  let remoteToken='token-1', remoteProgress=[{question_id:'qPoll',title:'Question qPoll',language:'python',available:true,
    practice_revision:'rev-1',progress:null}], progressFetches=0, catalogFetches=0;
  const pollTab=createTab({request:async (url) => {
    if (url==='/api/student/practice/questions') { catalogFetches++; return {catalog_token:remoteToken}; }
    if (url.endsWith('/questions/qPoll')) return {question:{...question('qPoll','rev-1'),starter_code:'starter-poll'}};
    if (url.endsWith('/progress')) { progressFetches++; return {progress:remoteProgress,catalog_token:remoteToken}; }
    if (url.endsWith('/run-status')) return {active:false,attempt_id:null,practice_revision:null};
    return {};
  }});
  await tick();
  pollTab.api.setCatalog(remoteProgress);
  pollTab.api.setCatalogToken('token-1');
  await pollTab.api.openWorkspace('qPoll');
  pollTab.elements['practice-code-editor'].value='tab-local-code';
  await pollTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  const initialProgressFetches=progressFetches;
  await pollTab.api.pollCatalogChanges();
  assert.strictEqual(progressFetches,initialProgressFetches,'unchanged token must avoid a progress refresh');
  assert.strictEqual(pollTab.api.getCatalogToken(),'token-1');

  remoteToken='token-2';
  remoteProgress=[{question_id:'qPoll',title:'Question qPoll updated',language:'python',available:true,
    practice_revision:'rev-2',version:2,progress:null}];
  await pollTab.api.pollCatalogChanges();
  assert.strictEqual(catalogFetches,2);
  assert.strictEqual(pollTab.api.getCatalogToken(),'token-2');
  assert.strictEqual(pollTab.elements['practice-code-editor'].value,'tab-local-code');
  assert(pollTab.elements['practice-revision-notice-text'].textContent.includes('Choose Update'));
  assert.strictEqual(pollTab.elements['practice-ws-update-btn'].classList.contains('hidden'),false);
  console.log('PASS Phase 3 token change detects revision and preserves Workspace source');

  // A publication change is reflected in the filtered Library without replacing its state.
  remoteToken='token-published';
  remoteProgress=[...remoteProgress,{question_id:'qNew',title:'Newly published',language:'python',available:true,practice_revision:'rev-new',progress:null}];
  await pollTab.api.pollCatalogChanges();
  assert(pollTab.elements['practice-catalog-list'].innerHTML.includes('Newly published'));
  console.log('PASS Phase 3 catalog polling discovers newly eligible questions');

  // Availability changes disable Run but leave the tab's editor intact.
  remoteToken='token-3';
  remoteProgress=[{question_id:'qPoll',title:'Question qPoll',language:'python',available:false,
    practice_revision:'rev-1',progress:{attempt_id:pollTab.api.getCurrentAttemptId(),has_result:false}}];
  await pollTab.api.pollCatalogChanges();
  assert(pollTab.elements['practice-revision-notice-text'].textContent.includes('Question unavailable'));
  assert.strictEqual(pollTab.elements['practice-code-editor'].value,'tab-local-code');
  assert.strictEqual(pollTab.elements['practice-run-btn'].disabled,true);
  console.log('PASS Phase 3 unavailable question keeps local source and disables Run');

  // Hidden tabs do not poll; visibility and online events trigger prompt synchronization.
  pollTab.document.visibilityState='hidden';
  const beforeHidden=catalogFetches;
  const visibilityHandler=pollTab.documentListeners.visibilitychange[0];
  await visibilityHandler();
  await pollTab.api.pollCatalogChanges();
  assert.strictEqual(catalogFetches,beforeHidden,'hidden tab must not issue catalog requests');
  pollTab.document.visibilityState='visible';
  await visibilityHandler();
  await tick();
  assert.strictEqual(catalogFetches,beforeHidden+1,'visible transition should synchronize promptly');
  console.log('PASS Phase 3 polling pauses while hidden and resumes on visibility');

  // A failed network check retains the last reconciled catalog and draft, then a later check recovers.
  const preservedCatalog=pollTab.elements['practice-catalog-list'].innerHTML;
  const preservedSource=pollTab.elements['practice-code-editor'].value;
  let failNextCatalogCheck=true;
  const originalPollRequest=pollTab.window.cssRequest;
  pollTab.window.cssRequest=async (url,opts) => {
    if (url==='/api/student/practice/questions' && failNextCatalogCheck) { failNextCatalogCheck=false; throw new Error('offline'); }
    return originalPollRequest(url,opts);
  };
  await pollTab.api.pollCatalogChanges();
  assert.strictEqual(pollTab.elements['practice-catalog-list'].innerHTML,preservedCatalog);
  assert.strictEqual(pollTab.elements['practice-code-editor'].value,preservedSource);
  assert(pollTab.elements['practice-notice'].textContent.includes('temporarily unavailable'));
  remoteToken='token-4';
  await pollTab.api.pollCatalogChanges();
  assert.strictEqual(pollTab.api.getCatalogToken(),'token-4');
  console.log('PASS Phase 3 network failure preserves state and later polling recovers');

  // Concurrent triggers share one in-flight catalog request.
  let releaseCatalog, overlapCalls=0;
  const overlapTab=createTab({request:async (url) => {
    if (url==='/api/student/practice/questions') { overlapCalls++; return new Promise(resolve => { releaseCatalog=resolve; }); }
    if (url.endsWith('/progress')) return {progress:[],catalog_token:'overlap-token'};
    return {};
  }});
  await tick();
  overlapTab.api.setCatalogToken('before-overlap');
  const firstPoll=overlapTab.api.pollCatalogChanges();
  await tick();
  const secondPoll=await overlapTab.api.pollCatalogChanges();
  assert.strictEqual(secondPoll,false);
  assert.strictEqual(overlapCalls,1);
  releaseCatalog({catalog_token:'before-overlap'});
  await firstPoll;
  overlapTab.api.stopCatalogPolling();
  console.log('PASS Phase 3 overlapping refresh triggers do not duplicate requests');

  // Phase 4: the same polling loop detects Start and unlock; local source stays intact.
  let examActive = false, statusOffline = false, lockProgressFetches = 0;
  const lockTab = createTab({statusRequest:async () => {
    if (statusOffline) throw new Error('status offline');
    return {active_exam_attempt:examActive};
  }, request:async (url) => {
    if (url.endsWith('/questions/qLock')) return {question:question('qLock')};
    if (url.endsWith('/progress')) { lockProgressFetches++; return {progress:[{question_id:'qLock',title:'Question qLock',language:'python',available:true,practice_revision:'rev-1',progress:null}],catalog_token:'unchanged'}; }
    if (url.endsWith('/run-status')) return {active:false};
    return {catalog_token:'unchanged'};
  }});
  assert.strictEqual(lockTab.elements['practice-root'].inert,true,'initial status must be verified before use');
  await tick();
  assert.strictEqual(lockTab.elements['practice-root'].inert,false);
  await lockTab.api.openWorkspace('qLock');
  lockTab.elements['practice-code-editor'].value='preserved local solution';
  await lockTab.elements['practice-code-editor'].dispatchEvent({type:'input'});
  const draftsBeforeLock = JSON.stringify(lockTab.storage.data);
  examActive = true;
  await lockTab.api.pollCatalogChanges();
  assert(lockTab.elements['practice-lock-dialog'].open && lockTab.elements['practice-root'].inert,'already-open Practice locks after Student Start');
  lockTab.document.fullscreenElement = {};
  await lockTab.api.pollCatalogChanges();
  assert(lockTab.elements['practice-root'].inert,'Fullscreen in Practice cannot bypass Practice Lock');
  await lockTab.elements['practice-lock-dialog'].close(); await tick();
  assert(lockTab.elements['practice-lock-dialog'].open,'closing the modal does not bypass the lock');
  assert.strictEqual(JSON.stringify(lockTab.storage.data),draftsBeforeLock,'lock never clears source drafts');
  statusOffline=true;
  await lockTab.api.pollCatalogChanges();
  assert(lockTab.elements['practice-root'].inert,'network failure cannot unlock');
  const beforeUnlock = lockProgressFetches;
  statusOffline=false; examActive=false;
  await lockTab.api.pollCatalogChanges();
  assert.strictEqual(lockTab.elements['practice-root'].inert,false,'authoritative inactive attempt unlocks');
  assert(lockProgressFetches > beforeUnlock,'unlock refreshes progress even when Question Bank token did not change');
  assert.strictEqual(lockTab.elements['practice-code-editor'].value,'preserved local solution');
  lockTab.api.stopCatalogPolling();
  const openedLocked=createTab({statusRequest:async () => ({active_exam_attempt:true})});
  await tick();
  assert(openedLocked.elements['practice-root'].inert && openedLocked.elements['practice-lock-dialog'].open,'Practice opened after Start is blocked');
  openedLocked.api.stopCatalogPolling();
  assert(template.includes('href="/" class="btn btn-primary">Quay về trang thi'));
  console.log('PASS Phase 4 initial/open-tab lock, protected modal, network recovery, unlock and source preservation');

  await tick();
  console.log('\nAll Practice workspace and Run integration regression tests passed.');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
