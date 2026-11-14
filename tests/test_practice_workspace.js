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

function createTab({student='student-1', sharedStorage=new Storage(), tabSession=new Storage(), request=async () => ({})} = {}) {
  const elements = Object.fromEntries(ids.map((id) => [id, new Element(id)]));
  elements['practice-root'].dataset.studentId = student;
  const document = { readyState:'complete', getElementById:(id) => elements[id] || null,
    createElement:() => new Element(), addEventListener:() => {}, querySelectorAll:() => [] };
  const window = { document, localStorage:sharedStorage, sessionStorage:tabSession, location:{hash:''},
    cssRequest:request, cssEscape:(v) => String(v ?? ''), confirm:() => true, alert:() => {},
    addEventListener:() => {}, removeEventListener:() => {}, setTimeout, clearTimeout, setInterval, clearInterval,
    crypto:null };
  const context = { window, document, localStorage:sharedStorage, console, setTimeout, clearTimeout,
    Uint8Array, Math, JSON, Number, String, Boolean, encodeURIComponent, decodeURIComponent, alert:() => {}, confirm:() => true };
  vm.createContext(context); vm.runInContext(script, context);
  return { window, elements, storage:sharedStorage, session:tabSession, api:window.PracticeWorkspace };
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

  // C2-F03: A -> Library -> Update B uses B's draft/attempt, never A's global state.
  let updateBody;
  const qTab = createTab({request:async (url, opts={}) => {
    if (url.endsWith('/update')) { updateBody = JSON.parse(opts.body); return {ok:true}; }
    if (url.endsWith('/questions/qA')) return {question:question('qA')};
    if (url.endsWith('/questions/qB')) return {question:question('qB','rev-2')};
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
  assert.strictEqual(qTab.api.getCurrentQuestion().question_id,'qB');
  assert.strictEqual(qTab.elements['practice-code-editor'].value,'B source');
  assert.strictEqual(qTab.api.getCurrentAttemptId(),idB);
  console.log('PASS C2-F03 Update uses selected question B attempt and source');

  // C2-F04: true tab separation; shared localStorage, separate sessionStorage and JS/DOM contexts.
  const shared = new Storage(), sessionA = new Storage(), sessionB = new Storage();
  let tabMutationRequests = 0;
  const detailRequest = async (url) => {
    if (/\/(update|run)$/.test(url)) tabMutationRequests++;
    return url.includes('/questions/') ? {question:question('q1')} : {progress:[]};
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
  const refreshA=createTab({sharedStorage:shared,tabSession:sessionA,request:detailRequest});
  const refreshB=createTab({sharedStorage:shared,tabSession:sessionB,request:detailRequest});
  await Promise.all([refreshA.api.openWorkspace('q1'),refreshB.api.openWorkspace('q1')]);
  assert.strictEqual(refreshA.elements['practice-code-editor'].value,'source A');
  assert.strictEqual(refreshB.elements['practice-code-editor'].value,'source B');
  assert.strictEqual(refreshA.api.getCurrentAttemptId(),attemptA);
  assert.strictEqual(refreshB.api.getCurrentAttemptId(),attemptB);
  assert.strictEqual(refreshA.api.getNeedsRetest(),true);
  assert.strictEqual(refreshB.api.getNeedsRetest(),true);
  const q2Attempt='e'.repeat(32);
  tabA.api.saveDraftToStorage('q2',q2Attempt,{attempt_id:q2Attempt,source_code:'question 2 source'});
  assert.strictEqual(tabA.api.loadDraftFromStorage('q1',attemptA).source_code,'source A');
  assert.strictEqual(tabA.api.loadDraftFromStorage('q2',q2Attempt).source_code,'question 2 source');
  assert.strictEqual(tabMutationRequests,0,'opening/editing in tabs must not create server attempts');
  const otherStudent=createTab({student:'student-2',sharedStorage:shared,tabSession:new Storage(),request:detailRequest});
  await otherStudent.api.openWorkspace('q1');
  otherStudent.elements['practice-code-editor'].value='student 2 source';
  await otherStudent.elements['practice-code-editor'].dispatchEvent({type:'input'});
  assert.notStrictEqual(otherStudent.api.getCurrentAttemptId(),attemptA);
  assert.strictEqual(otherStudent.api.loadDraftFromStorage('q1',otherStudent.api.getCurrentAttemptId()).source_code,'student 2 source');
  assert.strictEqual(tabA.api.loadDraftFromStorage('q1',attemptA).source_code,'source A');
  console.log('PASS C2-F04 separate tab drafts recover without cross-tab/student overwrites');

  // A stale tab cannot Update shared progress with its independent stale attempt ID.
  let authoritative = attemptA, staleUpdateBody;
  const staleTab = createTab({sharedStorage:shared,tabSession:sessionB,request:async (url,opts={}) => {
    if (url.endsWith('/update')) {
      staleUpdateBody=JSON.parse(opts.body);
      if (staleUpdateBody.expected_attempt_id !== authoritative) { const e=new Error('stale'); e.status=409; throw e; }
      return {ok:true};
    }
    return url.endsWith('/questions/q1') ? {question:question('q1')} : {progress:[]};
  }});
  staleTab.api.setCatalog([{question_id:'q1',available:true,practice_revision:'rev-2',progress:{attempt_id:attemptB,practice_revision:'rev-1'}}]);
  staleTab.api.saveDraftToStorage('q1',attemptB,{attempt_id:attemptB,source_code:'preserve B',needs_retest:true});
  await staleTab.api.handleUpdate('q1');
  assert.strictEqual(staleUpdateBody.expected_attempt_id,attemptB);
  assert.strictEqual(authoritative,attemptA);
  assert.strictEqual(staleTab.api.loadDraftFromStorage('q1',attemptB).source_code,'preserve B');
  console.log('PASS stale tab Update cannot replace shared attempt and preserves local source');

  // C2-F05: Update commits, detail fetch fails, editor/source remain; explicit retry succeeds.
  let detailCalls=0, updateAttempt;
  const updateSession=new Storage(), updateStorage=new Storage();
  const retryTab=createTab({sharedStorage:updateStorage,tabSession:updateSession,request:async (url,opts={}) => {
    if (url.endsWith('/update')) { updateAttempt=JSON.parse(opts.body).expected_attempt_id; return {ok:true}; }
    if (url.endsWith('/questions/q1')) { detailCalls++; if(detailCalls===2) throw new Error('temporary fetch failure'); return {question:question('q1','rev-2')}; }
    if (url.endsWith('/progress')) return new Promise(() => {});
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

  // CP3: an invalid/missing scoring denominator displays unscored, never 0% or 0/0.
  const unscoredTab=createTab({request:async (url,opts={}) => {
    if (url.endsWith('/questions/qNoScore')) return {question:{...question('qNoScore','rev-zero'),starter_code:'starter-qNoScore'}};
    if (url.endsWith('/run-status')) return {active:false,attempt_id:null,practice_revision:null};
    if (url.endsWith('/progress')) return {progress:[]};
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
  assert(unscoredHtml.includes('No visible test points can be scored'));
  assert(!unscoredHtml.includes('0%'));
  assert(!unscoredHtml.includes('0 / 0'));
  console.log('PASS CP3 missing visible denominator remains explicitly unscored');

  // CP3: first Run requires an edit/attempt; valid results render, and edits during a Run keep needs_retest.
  let finishRun, rejectRun, submittedRun, runCount = 0, catalogProgress = [];
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

  await tick();
  console.log('\nAll Checkpoint 2 correction regression tests passed.');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
