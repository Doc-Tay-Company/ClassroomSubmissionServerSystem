// Focused DOM/CSS regression checks for the Student Practice catalog cards.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

async function main() {
  const harness = fs.readFileSync(path.join(__dirname, 'test_practice_workspace.js'), 'utf8');
  const prefix = harness.slice(0, harness.indexOf('async function main() {'));
  const cardChecks = `
(async function runCardChecks() {
  const tab = createTab();
  const cards = [
    { question_id:'q0', title:'A long title that should wrap naturally across the available card width', available:true, language:'python', difficulty:'Easy', category:'Basics', version:1, progress:{has_result:true,score_available:true,practice_percentage:0} },
    { question_id:'q35', title:'Second question', available:true, language:'java', difficulty:'Medium', category:'Algorithms', version:2, progress:{has_result:true,score_available:true,practice_percentage:35} },
    { question_id:'q75', title:'Third question', available:true, language:'python', version:1, progress:{has_result:true,score_available:true,practice_percentage:75} },
    { question_id:'q100', title:'Fourth question', available:true, language:'java', version:3, progress:{has_result:true,score_available:true,practice_percentage:100} },
    { question_id:'qNew', title:'No result yet', available:true, language:'python', version:1, progress:null },
  ];
  tab.api.setCatalog(cards);
  let html = tab.elements['practice-catalog-list'].innerHTML;
  assert.strictEqual((html.match(/class="practice-card"/g) || []).length, 5, 'all cards render');
  assert(html.indexOf('practice-card-title') < html.indexOf('practice-meta') && html.indexOf('practice-meta') < html.indexOf('practice-card-footer'), 'title, metadata, and footer are vertically ordered');
  assert(html.includes('A long title that should wrap naturally'));
  assert(html.includes('open-preview-btn') && html.includes('open-workspace-btn'), 'existing result and workspace actions remain');
  assert(html.includes('No result yet') && html.includes('practice-card-footer'));
  assert(!html.includes('qNew') || html.slice(html.indexOf('qNew')).includes('open-workspace-btn'));
  for (const [score, color] of [[0,'fill-red'],[35,'fill-red'],[75,'fill-orange'],[100,'fill-green']]) {
    const i = html.indexOf(score + '%');
    assert(i >= 0, 'numeric percentage is retained: ' + score);
    const cardStart = html.lastIndexOf('<div class="practice-card"', i);
    const nextCard = html.indexOf('<div class="practice-card"', i);
    const cardHtml = html.slice(cardStart, nextCard < 0 ? html.length : nextCard);
    assert(cardHtml.includes('style="width: ' + score + '%"'), 'bar width matches score ' + score);
    assert(cardHtml.includes('practice-progress-fill ' + color), 'bar uses the existing score color ' + score);
  }
  tab.api.setCatalog([{...cards[1], progress:{has_result:true,score_available:true,practice_percentage:75}}]);
  html = tab.elements['practice-catalog-list'].innerHTML;
  assert(html.includes('75%') && html.includes('style="width: 75%"') && html.includes('fill-orange'), 'catalog rerender updates the displayed bar');
  const css = fs.readFileSync(path.join(__dirname, '../static/css/student-practice.css'), 'utf8');
  assert(css.includes('#practice-catalog-list .practice-card {') && /display:\\s*flex;\\s*flex-direction:\\s*column;/.test(css), 'cards use vertical layout');
  assert(css.includes('overflow-wrap: break-word;') && css.includes('word-break: normal;'), 'long titles wrap without forced mid-word breaks');
  assert(css.includes('height: 7px;') && css.includes('max-width: 100%;'), 'progress bar and actions remain compact and responsive');
  assert(script.includes('Math.min(100, Math.max(0, pct))'), 'visual width is clamped to 0–100%');
  console.log('PASS practice cards: vertical layout, score bars, updates, and actions');
})()
`;
  const context = { require, __dirname, console, setTimeout, clearTimeout, setInterval, clearInterval, setImmediate };
  vm.createContext(context);
  await vm.runInContext(prefix + cardChecks, context);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
