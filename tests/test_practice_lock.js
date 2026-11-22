const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const nodes = {};
for (const id of ['practice-lock-title', 'practice-lock-message']) nodes[id] = {textContent:''};
const root = {inert:false};
const handlers = {};
const dialog = {open:false, addEventListener(type, fn) {handlers[type] = fn;}, showModal() {this.open=true;}, close() {this.open=false; handlers.close?.();}};
const window = {};
vm.runInNewContext(fs.readFileSync('static/js/practice-lock.js','utf8'), {window, document:{getElementById:(id)=>nodes[id]}, Error});
let statusHandler, runHandler, statusCalls=0, practiceCalls=0;
const lock = window.createPracticeLock({root,dialog,request:(url) => {
  if (url === '/api/student/status') {statusCalls++; return statusHandler();}
  practiceCalls++; return runHandler();
}});
const deferred = () => {let resolve,reject; const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
(async () => {
  assert(root.inert && dialog.open, 'initial unknown state is blocked');
  statusHandler=async()=>{throw new Error('initial status offline');};
  await lock.check();
  assert(root.inert && nodes['practice-lock-message'].textContent.includes('Chưa thể xác minh'),'initial network error is not an unlocked response');
  let pending=deferred(); statusHandler=()=>pending.promise;
  const beforeStatusCalls=statusCalls;
  const first=lock.check(), second=lock.check(); assert.strictEqual(first,second,'status calls share one in-flight request');
  assert.strictEqual(statusCalls,beforeStatusCalls+1);
  pending.resolve({active_exam_attempt:false}); await first;
  assert(!root.inert && !dialog.open);

  statusHandler=async()=>({active_exam_attempt:false,practice_locked:true});
  await lock.check();
  assert(root.inert && dialog.open, 'ZIP Exam can keep Practice locked while submission eligibility remains');
  statusHandler=async()=>({active_exam_attempt:false,practice_locked:false});
  await lock.check();
  assert(!root.inert && !dialog.open, 'quota exhaustion releases Practice through authoritative status');

  const execution=deferred(); runHandler=()=>execution.promise;
  const accepted=lock.request('/api/student/practice/run');
  statusHandler=async()=>({active_exam_attempt:true}); await lock.check();
  assert(root.inert && dialog.open);
  execution.resolve({completed:true}); assert.strictEqual((await accepted).completed,true,'accepted request may finish while interface remains locked');
  assert(root.inert && dialog.open);
  const previousCalls=practiceCalls;
  await assert.rejects(lock.request('/api/student/practice/run'),(error)=>error.code==='PRACTICE_LOCKED');
  assert.strictEqual(practiceCalls,previousCalls,'new locked operations are not sent');
  let canceled=false; handlers.cancel({preventDefault(){canceled=true;}}); assert(canceled && dialog.open);
  dialog.close(); assert(dialog.open && root.inert,'dismissal cannot reveal Practice');

  statusHandler=async()=>{throw new Error('offline');}; await lock.check(); assert(root.inert);
  statusHandler=async()=>({active_exam_attempt:false}); await lock.check();
  assert(!root.inert && lock.needsRecovery()); assert(lock.needsRecovery(),'recovery stays pending until progress sync succeeds');
  lock.acknowledgeRecovery(); assert(!lock.needsRecovery());

  pending=deferred(); statusHandler=()=>pending.promise;
  const staleStatus=lock.check();
  runHandler=async()=>{const error=new Error('locked');error.status=403;error.code='PRACTICE_LOCKED';throw error;};
  await assert.rejects(lock.request('/api/student/practice/run'));
  pending.resolve({active_exam_attempt:false}); await staleStatus;
  assert(root.inert && dialog.open,'older status response cannot override a newer server denial');
  statusHandler=async()=>({active_exam_attempt:false}); await lock.check();
  statusHandler=async()=>{const error=new Error('login');error.status=401;throw error;}; await lock.check();
  assert(root.inert && nodes['practice-lock-message'].textContent.includes('đăng nhập'),'authentication failure remains distinct from unlocked status');
  console.log('PASS Practice Lock: initial eligibility, single-flight, admitted completion, denial, recovery and response ordering');
})().catch((error)=>{console.error(error);process.exitCode=1;});
