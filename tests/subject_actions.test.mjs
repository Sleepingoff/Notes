import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const autoSource=readFileSync(new URL('../web/autosave.js',import.meta.url),'utf8');
const {AutoSave}=await import('data:text/javascript;base64,'+Buffer.from(autoSource).toString('base64'));
function fixture({deleteFails=false}={}) {
  const nodes=new Map(),calls=[];
  class Element {
    constructor(key){this.key=key;this.value='';this.textContent='';this.innerHTML='';this.dataset={};this.listeners={};this.classList={toggle(){}};}
    focus(){} select(){}
    showModal(){this.open=true;} close(){this.open=false;}
    addEventListener(type,handler){this.listeners[type]=handler;}
    cloneNode(){return new Element(this.key);}
    replaceWith(node){nodes.set(this.key,node);}
    querySelector(){return new Element('form');}
    querySelectorAll(){return [];}
  }
  const $=key=>{if(!nodes.has(key))nodes.set(key,new Element(key));return nodes.get(key);};
  const backend=[{id:'a',name:'First'},{id:'b',name:'Second'}];
  const S={subjects:structuredClone(backend),subject:'a',drafts:{a:{}},explanationDrafts:{'bank-a1:1':{}},bank:'bank-a',quiz:{},data:{},filter:{},page:3};
  const api=async(path,data)=>{
    calls.push({path,data});
    if(path.startsWith('/api/subject?'))return {banks:[{id:'bank-a'}]};
    if(path==='/api/subject/rename'){
      if(backend.some(s=>s.id!==data.id&&s.name===data.name))throw new Error('duplicate');
      backend.find(s=>s.id===data.id).name=data.name;return {ok:true};
    }
    if(path==='/api/subject/delete'){
      if(deleteFails)throw new Error('delete failed');
      backend.splice(backend.findIndex(s=>s.id===data.id),1);return {ok:true};
    }
    throw new Error(path);
  };
  const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const context=vm.createContext({S,$,AutoSave,api,esc,url:(path,params)=>path+'?'+new URLSearchParams(params),
    action:fn=>fn,notify(){},releaseEditor:async()=>{},bootstrap:async()=>{S.subjects=structuredClone(backend);S.subject ||= S.subjects[0]?.id||null;}});
  const helper=source.slice(source.indexOf('const autoSaves ='),source.indexOf('async function releaseEditor('));
  const actions=source.slice(source.indexOf('function subjectIcon('),source.indexOf('async function go('));
  vm.runInContext(helper+actions,context);
  return {context,S,$,calls,backend,run:code=>vm.runInContext(code,context)};
}
const event=()=>({preventDefault(){}});

test('rename uses a separate input modal and autosaves without changing the subject ID',async()=>{
  const {$,calls,S,run}=fixture();
  await run('openSubjectRename("a")');
  assert.equal($('#subject-rename-dialog').open,true);
  const input=$('#subject-name-input');
  assert.equal(input.value,'First');
  input.value='Renamed';input.listeners.input({isComposing:false});
  await $('#close-subject-rename').onclick();
  assert.equal($('#subject-rename-dialog').open,false);
  assert.equal(S.subjects[0].id,'a');
  assert.equal(S.subjects[0].name,'Renamed');
  assert.equal($('#page-header h1').textContent,'Renamed');
  assert.equal(calls.filter(c=>c.path==='/api/subject/rename').length,1);
});
test('Escape cancels an unsent rename instead of leaving a pending save',async()=>{
  const {$,calls,run}=fixture();
  await run('openSubjectRename("a")');
  const input=$('#subject-name-input');input.value='Unsent';input.listeners.input({isComposing:false});
  await run('closeSubjectRename(true)');
  await run('flushAutosaves()');
  assert.equal(calls.length,0);assert.equal($('#subject-rename-dialog').open,false);
});
test('opening or cancelling deletion never sends a delete request',async()=>{
  const {$,calls,run}=fixture();
  run('openSubjectDelete("a")');
  assert.equal($('#subject-delete-dialog').open,true);
  assert.equal($('#subject-delete-name').textContent,'First');
  assert.equal(calls.length,0);
  $('#cancel-subject-delete').onclick();
  await $('#subject-delete-form').onsubmit(event());
  assert.equal($('#subject-delete-dialog').open,false);
  assert.equal(calls.length,0);
});
test('confirmation deletes the chosen subject and clears only its client state',async()=>{
  const {$,calls,S,run}=fixture();
  run('openSubjectDelete("a")');
  await $('#subject-delete-form').onsubmit(event());
  assert.equal(calls.at(-1).path,'/api/subject/delete');
  assert.equal(calls.at(-1).data.id,'a');
  assert.equal($('#subject-delete-dialog').open,false);
  assert.equal(S.subject,'b');assert.equal(S.bank,null);
  assert.equal(S.drafts.a,undefined);assert.deepEqual(Object.keys(S.explanationDrafts),[]);
});
test('a failed delete keeps the confirmation modal open and allows retry',async()=>{
  const {$,S,run}=fixture({deleteFails:true});
  run('openSubjectDelete("a")');await $('#subject-delete-form').onsubmit(event());
  assert.equal($('#subject-delete-dialog').open,true);
  assert.equal($('#subject-delete-error').textContent,'delete failed');
  assert.equal($('#confirm-subject-delete').disabled,false);
  assert.equal(S.subject,'a');assert.equal(S.subjects.length,2);
});
