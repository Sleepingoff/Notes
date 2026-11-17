import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('const multipleAnswerSymbols ='),source.indexOf('async function quiz('));
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const keys=[
 {year:2020,term:2,grade:1,subject:'놀이지도',answers:[[1,2],[4],[]],issues:[{questions:[3,3],raw:'<invalid>'}]},
 {year:2020,term:2,grade:4,subject:'놀이지도',answers:[[1],[1,2,3,4]],issues:[]},
 {year:2019,term:1,grade:1,subject:'놀이지도',answers:[[3]],issues:[]},
 {year:2018,term:2,grade:1,subject:'놀이지도',answers:[],issues:[]},
];
function fixture(answerKeys=keys,preferred={}) {
 const elements=new Map(),copied=[];
 let buttons=[];
 const root={innerHTML:'',querySelectorAll:()=>{buttons=[...(elements.get('[data-key-tables]')?.innerHTML||'').matchAll(/data-copy-key="(\d+)"/g)].map(match=>({dataset:{copyKey:match[1]},textContent:'복사하기'}));return buttons;},querySelector(selector){if(!elements.has(selector))elements.set(selector,{value:'',innerHTML:''});return elements.get(selector);}};
 const context=vm.createContext({S:{data:{answerKeys}},root,preferred,esc,action:fn=>fn,navigator:{clipboard:{writeText:async text=>copied.push(text)}}});
 vm.runInContext(code+'\nanswerTables(root,preferred);',context);
 return {root,copied,get buttons(){return buttons;},year:elements.get('[data-key-year]'),term:elements.get('[data-key-term]'),get html(){return elements.get('[data-key-tables]')?.innerHTML||root.innerHTML;}};
}
test('tables preserve multiple accepted choices, grades and unresolved source cells',()=>{
 const f=fixture();
 assert.ok(f.html.includes('2020년 2학기 · 1학년'));assert.ok(f.html.includes('2020년 2학기 · 4학년'));
 assert.ok(f.html.includes('1, 2'));assert.ok(f.html.includes('1, 2, 3, 4'));
 assert.ok(f.html.includes('확인 필요'));assert.ok(f.html.includes('&lt;invalid&gt;'));
 assert.ok(!f.html.includes('<invalid>'));
 f.year.value='2018';f.term.value='2';f.year.onchange();
 assert.ok(f.html.includes('원본 정답표에 정답이 비어 있습니다.'));
});
test('the current bank year and term filter the tables without merging grades',()=>{
 const f=fixture(keys,{year:2020,term:'2학기'});
 assert.equal(f.year.value,'2020');assert.equal(f.term.value,'2');
 assert.ok(f.html.includes('1학년'));assert.ok(f.html.includes('4학년'));assert.ok(!f.html.includes('2019년'));
 f.year.value='2019';f.term.value='1';f.year.onchange();
 assert.ok(f.html.includes('2019년 1학기'));assert.ok(!f.html.includes('2020년'));
});
test('an unmatched exam stays filtered instead of showing answers from other years',()=>{
 const f=fixture(keys,{year:2026,term:'1학기'});
 assert.equal(f.year.value,'2026');assert.ok(!f.html.includes('2020년'));assert.ok(!f.html.includes('2019년'));
 assert.ok(f.html.includes('선택한 연도·학기의 정답표가 없습니다.'));
 f.year.value='2019';f.term.value='2';f.term.onchange();
 assert.ok(f.html.includes('선택한 연도·학기의 정답표가 없습니다.'));
});
test('subjects without keys show a clear empty state',()=>{
 const f=fixture([]);assert.ok(f.html.includes('이 과목의 정답표가 없습니다.'));
});

 test('copy buttons preserve multiple answers and unresolved positions in pasteable text',async()=>{
 const f=fixture(keys,{year:2020,term:'2학기'});
 await f.buttons[0].onclick();await f.buttons[1].onclick();
 assert.deepEqual(f.copied,['A4?','1K']);assert.equal(f.buttons[0].textContent,'복사됨');
 f.year.value='2019';f.term.value='1';f.year.onchange();
 await f.buttons[0].onclick();assert.equal(f.copied.at(-1),'3');
});
 test('clipboard fallback restores focus and reports failure without leaving an input',async()=>{
 const input={value:'',style:{},select(){this.selected=true;},remove(){this.removed=true;}};
 const previous={focus(){this.focused=true;}};
 const document={activeElement:previous,createElement:()=>input,body:{append(){}},execCommand:()=>true};
 const context=vm.createContext({document,navigator:{clipboard:{writeText:async()=>{throw Error('denied');}}}});
 vm.runInContext(source.slice(source.indexOf('async function copyAnswerText('),source.indexOf('function answerTables(')),context);
 await vm.runInContext('copyAnswerText("1AK?")',context);
 assert.equal(input.value,'1AK?');assert.equal(input.selected,true);assert.equal(input.removed,true);assert.equal(previous.focused,true);
 document.execCommand=()=>false;
 await assert.rejects(vm.runInContext('copyAnswerText("1")',context),/복사하지 못했습니다/);
});

test('grading feedback displays all accepted choices instead of the stored symbol',()=>{
 const root={innerHTML:''};
 const context=vm.createContext({$:()=>root,esc});
 const helpers=source.slice(source.indexOf('const multipleAnswerSymbols ='),source.indexOf('async function copyAnswerText('));
 const grade=source.slice(source.indexOf('function grade('),source.indexOf('async function showExplanations('));
 vm.runInContext(helpers+grade,context);
 vm.runInContext('grade({selected:2,correct:1,answer:"A"})',context);
 assert.ok(root.innerHTML.includes('정답입니다.'));assert.ok(root.innerHTML.includes('1, 2번 보기'));
 vm.runInContext('grade({selected:3,correct:0,answer:"A"})',context);
 assert.ok(root.innerHTML.includes('오답입니다.'));assert.ok(root.innerHTML.includes('1, 2번 보기'));
 vm.runInContext('grade({selected:1,correct:null,answer:null})',context);
 assert.ok(root.innerHTML.includes('정답표가 확정되면 채점됩니다.'));
});
