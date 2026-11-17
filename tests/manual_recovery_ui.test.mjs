import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const esc=s=>String(s).replaceAll('<','&lt;').replaceAll('>','&gt;');
function fixture() {
 const nodes=new Map(),calls=[],errors=[];let renders=0;
 function element(key){return {value:'',open:false,innerHTML:'',hidden:false,
   cloneNode(){return element(key);},replaceWith(node){nodes.set(key,node);},
   showModal(){this.open=true;},close(){this.open=false;}};}
 const $=key=>{if(!nodes.has(key))nodes.set(key,element(key));return nodes.get(key);};
 const S={bank:'b',route:'manage',data:{banks:[{id:'b',pages:3}]}};
 const context=vm.createContext({S,$,esc,bindReextraction(){},cancelReextraction(){},action:f=>f,notify:message=>errors.push(message),url:(p,args)=>p+'?'+new URLSearchParams(args),
  api:async(path,data)=>{calls.push({path,data});return data?{ok:true}:{text:'',suggestedNumber:5,warnings:[{message:'공통 지문 확인',original_values:{text:'<원문>'}}]};},
  autoSave:(key,run)=>({run}),autoInput:(editor,save)=>editor.save=save,flushAutosaves:async()=>{},releaseEditor:async()=>{},sidebar(){},render:async()=>renders++});
 const code=source.slice(source.indexOf('let questionEdited ='),source.indexOf('$("#close-edit").onclick'));
 vm.runInContext(code,context);
 return {$,S,calls,errors,run:code=>vm.runInContext(code,context),get renders(){return renders;}};
}
test('page recovery loads original PDF, preserves review text and autosaves the whole page',async()=>{
 const f=fixture();await f.run('editQuestion({page:2,id:"page-2"},true)');
 assert.ok(f.calls[0].path.includes('mode=page'));assert.ok(f.$('#edit-original').src.includes('page=2'));
 assert.ok(f.$('#edit-text').value.startsWith('5)'));assert.equal(f.$('#edit-page-field').hidden,false);
 assert.ok(f.$('#edit-context').innerHTML.includes('&lt;원문&gt;'));
 f.$('#edit-text').value='5) 작성한 문제\n- [ ] 보기 1\n- [ ] 보기 2';
 await f.$('#edit-text').save.run();
 assert.equal(f.calls.at(-1).path,'/api/question/edit');assert.equal(f.calls.at(-1).data.mode,'page');
 assert.equal(f.calls.at(-1).data.page,2);
 await f.$('#edit-page').onchange({target:{value:'3'}});
 assert.ok(f.calls.at(-1).path.includes('page=3'));
 await f.run('closeQuestionEditor()');
 assert.equal(f.S.route,'quiz');assert.equal(f.renders,1);assert.deepEqual(f.errors,[]);
});
test('failed-bank writing opens the first unfinished page instead of gating on ready',async()=>{
 const button={dataset:{writeBank:'b'}};const root={querySelectorAll:()=>[button]};const written=[];
 const S={bank:null,data:{banks:[{id:'b',ready:false,incompletePages:[2,3],task:{status:'failed'}}]}};
 const context=vm.createContext({S,root,esc,action:f=>f,releaseEditor:async()=>{},editQuestion:async(q,mode)=>written.push({q,mode})});
 vm.runInContext(source.slice(source.indexOf('function manualWriteButton('),source.indexOf('function bankList('))+'\nbindManualWriting(root);',context);
 await button.onclick();assert.equal(S.bank,'b');assert.equal(written[0].q.page,2);assert.equal(written[0].mode,true);
 assert.ok(vm.runInContext('manualWriteButton(S.data.banks[0])',context).includes('직접 작성'));
});
