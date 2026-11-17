import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const helpers=source.slice(source.indexOf('const multipleAnswerSymbols ='),source.indexOf('async function quiz('));
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
function node(){
 const children=new Map();let html='',inputs=[];
 return {isConnected:true,value:'',dataset:{},handlers:{},
  set innerHTML(value){html=value;inputs=[...value.matchAll(/data-answer-number="(\d+)"[^>]*value="([^"]*)"/g)].map(m=>({...node(),value:m[2],dataset:{answerNumber:m[1]}}));},
  get innerHTML(){return html;},querySelector(selector){if(!children.has(selector))children.set(selector,node());return children.get(selector);},
  querySelectorAll(selector){return selector==='[data-answer-number]'?inputs:[];},
  addEventListener(type,fn){(this.handlers[type]||=[]).push(fn);},
 };
}
const key=(year=2020,grade=1)=>({year,term:2,grade,subject:'Test',answers:grade===1?[[1],[1,2],[4]]:[[2],[3],[4]],issues:[]});
function fixture({keys=[],year=2026,answers={},origin=null}={}){
 const root=node(),saves=[],requests=[];let summaries=0;
 const rounds=[{id:1,records:{}}];
 const S={bank:'b',round:1,index:0,data:{answerKeys:keys},quiz:{material:{exam_year:year,exam_term:'2학기'},answers,answerOrigin:origin,questions:[1,2,3].map(number=>({id:`1:${number}`,number})),rounds}};
 const context=vm.createContext({S,esc,root,action:fn=>fn,url:(p,args)=>p+'?'+new URLSearchParams(args),subjectName:()=> 'Test',examName:m=>`${m.exam_year}년 · ${m.exam_term}`,
  summary(){summaries++;},grade(){},
  api:async(path,data)=>{requests.push({path,data});if(data){S.quiz.answers=Object.fromEntries([...data.raw].map((a,i)=>[String(i+1),a==='?'?null:/\d/.test(a)?Number(a):a]));return S.quiz.answers;}return {answers:S.quiz.answers,rounds};},
  autoSave:(id,run)=>{const save={run,schedule(){this.dirty=true;}};saves.push(save);return save;},
  autoInput:(input,save)=>input.addEventListener('input',()=>save.schedule())});
 vm.runInContext(helpers+'\nquizAnswerTable(root);',context);
 return {root,S,saves,requests,get summaries(){return summaries;},run:code=>vm.runInContext(code,context)};
}
test('quiz answer tables show exactly the selected exam without internal period selectors',()=>{
 const f=fixture({keys:[key(2020),key(2019)],year:2020});
 const table=f.root.querySelector('[data-exam-answers]').querySelector('[data-key-tables]').innerHTML;
 assert.ok(table.includes('2020년 2학기'));assert.ok(!table.includes('2019년'));
 assert.ok(!f.root.querySelector('[data-exam-answers]').innerHTML.includes('data-key-year'));
 assert.equal(f.saves.length,0);
});
test('missing exam keys produce editable table cells and save multiple answers with stable positions',async()=>{
 const f=fixture({keys:[key(2019)]});
 assert.ok(f.root.innerHTML.includes('해당 시험의 정답표가 없습니다.'));
 assert.ok(f.root.innerHTML.includes('answer-key-table'));
 const inputs=f.root.querySelectorAll('[data-answer-number]');assert.equal(inputs.length,3);
 inputs[0].value='2';inputs[1].value='1,2';
 for(const input of inputs.slice(0,2))for(const fn of input.handlers.input)fn();
 await f.saves[0].run();
 assert.equal(f.requests[0].path,'/api/answers');assert.equal(f.requests[0].data.raw,'2A');
 assert.equal(f.S.quiz.answers['2'],'A');assert.equal(f.summaries,1);
 inputs[0].value='';for(const fn of inputs[0].handlers.input)fn();
 await f.saves[0].run();assert.equal(f.requests.at(-2).data.raw,'?A');
});
test('saved manual answers are shown in the same cells and invalid values are rejected',async()=>{
 const f=fixture({answers:{'1':2,'2':'A','3':null,'7':4}});
 const inputs=f.root.querySelectorAll('[data-answer-number]');assert.equal(inputs.length,7);
 assert.equal(inputs[0].value,'2');assert.equal(inputs[1].value,'1, 2');assert.equal(inputs[2].value,'');assert.equal(inputs[6].value,'4');
 inputs[0].value='invalid';for(const fn of inputs[0].handlers.input)fn();
 await assert.rejects(f.saves[0].run(),/정답은 보기 번호/);assert.equal(f.requests.length,0);
});
test('previous manual overrides stay visible instead of showing a different grading key',()=>{
 const f=fixture({keys:[key(2020)],year:2020,answers:{'1':4,'2':3,'3':2},origin:'manual'});
 assert.ok(f.root.innerHTML.includes('직접 입력한 정답표입니다.'));
 assert.equal(f.root.querySelectorAll('[data-answer-number]')[0].value,'4');
});
test('grade selection applies the chosen answer key for the selected exam',async()=>{
 const f=fixture({keys:[key(2020,1),key(2020,4)],year:2020});
 const select=f.root.querySelector('[data-answer-grade]');assert.equal(select.value,'');
 select.value='1';await select.onchange();
 assert.equal(f.requests[0].data.raw,'234');assert.equal(f.S.quiz.answers['1'],2);
});
test('quiz layout puts exam and round together, then the open question list and collapsible answer table',async()=>{
 const content=node(),elements=new Map();const $=selector=>{if(!elements.has(selector))elements.set(selector,node());return elements.get(selector);};
 const bank={id:'b',ready:true};
 const S={bank:'b',round:1,index:0,data:{banks:[bank]},filter:null};
 const context=vm.createContext({S,$,content,esc,flushAutosaves:async()=>{},url:p=>p,api:async()=>({rounds:[{id:1,number:1}],questions:[],material:{}}),
  bankSelect:()=>'<select id="bank-select"></select>',manualWriteButton:()=>'',bindManualWriting(){},quizAnswerTable(){},action:fn=>fn,summary(){},question:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('async function quiz('),source.indexOf('function recordStatus(')),context);
 await vm.runInContext('quiz()',context);
 const html=content.innerHTML;
 assert.ok(html.indexOf('id="round-select"')<html.indexOf('class="question-list-section"'));
 assert.ok(html.indexOf('class="question-list-section"')<html.indexOf('<details><summary>정답표'));
 assert.ok(!html.includes('<summary>문제 목록'));assert.ok(!html.includes('answer-form'));
});
