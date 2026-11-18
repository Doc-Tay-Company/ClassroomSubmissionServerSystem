const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const tick = () => new Promise(resolve => setImmediate(resolve));

const display = { window: {}, Intl, Date };
vm.runInNewContext(fs.readFileSync('static/js/student-display.js', 'utf8'), display);
assert.equal(display.window.formatExamClock('2026-11-17T10:17:15+00:00'), '17:17:15');
assert.equal(display.window.formatExamClock('2026-11-17T10:17:15+07:00'), '10:17:15');
assert.equal(display.window.formatExamClock('invalid'), '—');
assert.equal(display.window.formatExamClock(''), '—');
const template = fs.readFileSync('templates/student.html', 'utf8');
assert(!template.includes('id="code-submit"'));
assert(template.includes('id="code-submit-all"'));
assert(template.includes("'in_progress':'Đã bắt đầu'"));

function setup({remaining = 20, finalized = true, failed = false} = {}) {
  const nodes = {}, intervals = [], timers = [], requests = [], cache = new Map();
  function element() {
    const classes = new Set();
    return {dataset:{}, children:[], handlers:{}, value:'', textContent:'',
      classList:{add(...names){names.forEach(n=>classes.add(n));},remove(...names){names.forEach(n=>classes.delete(n));},toggle(n,v){if(v)classes.add(n);else classes.delete(n);}},
      addEventListener(t,fn){this.handlers[t]=fn;}, append(...items){this.children.push(...items);},
      replaceChildren(...items){this.children=items;}, querySelector(){return null;}, focus(){}, setSelectionRange(){},setAttribute(){},removeAttribute(){}};
  }
  for (const match of template.matchAll(/id="([^"]+)"/g)) nodes[match[1]]=element();
  nodes['student-code-root'].dataset={studentId:'s',assignedExamId:'exam'};
  const question = {question_id:'q', title:'Question',language:'python',grading_mode:'stdio',starter_code:'starter',total_points:10,tests:[]};
  cache.set('css-code-draft-v1:s:exam:q',JSON.stringify({source_code:'latest local work',starter_code:'starter'}));
  let completed = 0;
  const window = {
    confirm:()=>true, addEventListener(){},
    setTimeout(fn,ms){timers.push({fn,ms});return timers.length;},clearTimeout(){},
    setInterval(fn,ms){intervals.push({fn,ms});return intervals.length;},
    completeOfficialExam:async()=>{completed++;},
    cssRequest:async(path,options)=>{
      requests.push({path,payload:options?.body && JSON.parse(options.body)});
      if(path==='/api/student/code-exam') return {exam_id:'exam',title:'Exam',questions:[question],progress:[],drafts:{}};
      if(path==='/api/student/status') return {remaining_seconds:remaining,exam_state:'started'};
      if(path.includes('/submission?')) throw {status:404};
      if(path==='/api/student/code/draft') return {ok:true};
      if(path==='/api/student/code/submit-exam') {
        if(failed) throw {status:503,detail:'temporarily unavailable'};
        return {ok:true,finalized,progress:[]};
      }
      throw Error('unexpected request '+path);
    },
  };
  const document={getElementById:id=>nodes[id]||null,createElement:element,createTextNode:t=>({textContent:t})};
  vm.runInNewContext(fs.readFileSync('static/js/student-code.js','utf8'),{window,document,localStorage:{getItem:k=>cache.get(k)||null,setItem:(k,v)=>cache.set(k,v)},
    console,Date,performance:{now:()=>0},Set,Map,Number,Math,encodeURIComponent});
  return {nodes,intervals,timers,requests,cache,completed:()=>completed};
}

(async()=>{
  const active=setup();await tick();await tick();
  assert.equal(active.nodes['student-code-editor'].value,'latest local work');
  assert(!active.nodes['student-code-editor'].disabled);
  active.nodes['student-code-editor'].value='current editor';
  await active.nodes['code-submit-all'].handlers.click();await tick();
  const manual=active.requests.find(r=>r.path==='/api/student/code/submit-exam');
  assert.equal(manual.payload.answers.q,'current editor');
  assert.strictEqual(manual.payload.automatic,false);
  assert.equal(active.completed(),1);
  const expired=setup({remaining:0});await tick();await tick();
  assert(expired.nodes['student-code-editor'].disabled);
  assert.equal(expired.requests.find(r=>r.path==='/api/student/code/submit-exam').payload.automatic,true);
  assert.equal(expired.completed(),1);
  const failure=setup({remaining:0,failed:true});await tick();await tick();
  assert.equal(failure.completed(),0,'failure must not announce success or navigate');
  assert(failure.nodes['student-code-editor'].disabled);
  assert(JSON.parse(failure.cache.get('css-code-draft-v1:s:exam:q')).source_code==='latest local work');
  const sent=failure.requests.filter(r=>r.path==='/api/student/code/submit-exam').length;
  failure.intervals.find(t=>t.ms===1000).fn();await tick();
  assert.equal(failure.requests.filter(r=>r.path==='/api/student/code/submit-exam').length,sent,'retry is bounded');
  const pending=setup({remaining:0,finalized:false});await tick();await tick();
  assert.equal(pending.completed(),0,'unconfirmed completion must not navigate');
  console.log('PASS Official Exam UI: local clock, controls, manual/automatic completion, failure/retry, draft recovery');
})().catch(error=>{console.error(error);process.exitCode=1;});
