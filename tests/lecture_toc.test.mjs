import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const autoSource=readFileSync(new URL('../web/autosave.js',import.meta.url),'utf8');
const {AutoSave}=await import('data:text/javascript;base64,'+Buffer.from(autoSource).toString('base64'));
function fixture(bundle=null,{failMerge=false}={}) {
  const nodes=new Map(),calls=[];
  const $=key=>{
    if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',inert:false,listeners:{},classList:{toggle(){}},querySelectorAll:()=>[],
      addEventListener(type,callback){this.listeners[type]=callback;},click(){this.clicked=true;}});
    return nodes.get(key);
  };
  const S={subject:'s',route:'lecture',page:bundle?4:1,drafts:{},data:{bundle,lecturePlan:bundle?bundle.chapters.map(c=>({chapter:c.id,title:c.title,included:true})):[]},editor:null};
  const api=async(path,data)=>{
    if(path.startsWith('/api/related'))return {};
    assert.equal(path,'/api/lecture/auto');
    calls.push({payload:structuredClone(data),inert:$('#lecture-document').inert});
    if(failMerge)throw new Error('merge failed');
    let page=1;
    const upload_chapters={};
    const plan=data.order.map(row=>{
      const chapter=row.chapter||row.client_id.replaceAll('-','');
      if(row.upload!==undefined)upload_chapters[row.upload]=chapter;
      return {chapter,title:row.title,included:row.included};
    });
    const chapters=plan.filter(row=>row.included).map(row=>{
      const length=bundle?.chapters.find(c=>c.id===row.chapter)?.end-bundle?.chapters.find(c=>c.id===row.chapter)?.start+1||1;
      const result={id:row.chapter,title:row.title,start:page,end:page+length-1};page+=length;return result;
    });
    return {plan,upload_chapters,bundle:chapters.length?{chapters,pages:page-1}:null};
  };
  const context=vm.createContext({S,$,content:$('#content'),AutoSave,api,crypto:{randomUUID},esc:String,Promise,location:{},
    action:fn=>fn,notify(){},url:(path,params)=>path+'?'+new URLSearchParams(params),subjectIcon:()=>'<svg></svg>',
    readFiles:async files=>files,editorAt:async()=>{},releaseEditor:async()=>{},sidebar(){},render:async()=>{}});
  const helpers=source.slice(source.indexOf('const autoSaves ='),source.indexOf('async function releaseEditor('));
  const clamp=source.slice(source.indexOf('function clampPage('),source.indexOf('async function editorAt('));
  const viewer=source.slice(source.indexOf('function lectureAnchor('),source.indexOf('async function readFiles('));
  const manager=source.slice(source.indexOf('function lectureManage('),source.indexOf('function badge('));
  vm.runInContext(helpers+clamp+viewer+manager,context);
  return {S,$,calls,run:code=>vm.runInContext(code,context)};
}
const original=()=>({pages:5,chapters:[{id:'a',title:'First',start:1,end:2},{id:'b',title:'Second',start:3,end:5}]});

test('empty subjects show a PDF add action below the TOC without going to management',async()=>{
  const {$,run}=fixture();await run('lecture()');
  const toc=$('#lecture-toc').innerHTML;
  assert.ok(toc.indexOf('lecture-order')<toc.indexOf('add-lecture-pdf'));
  assert.ok($('#lecture-document').innerHTML.includes('PDF 추가'));
  assert.ok(!$('#content').innerHTML.includes('manage-body'));
  $('#add-lecture-pdf').onclick();assert.equal($('#lecture-files').clicked,true);
});
test('adding a PDF from the TOC auto-merges and renders the new PDF in the same view',async()=>{
  const {S,$,calls,run}=fixture();await run('lecture()');
  await $('#lecture-files').onchange({target:{files:[{name:'new.pdf',data:'pdf'}]}});
  await run('flushAutosaves()');
  assert.equal(calls.length,1);assert.equal(calls[0].inert,true);
  assert.equal(S.data.bundle.pages,1);assert.equal(S.route,'lecture');
  assert.ok($('#lecture-document').innerHTML.includes('lecture-editor'));
  assert.ok($('#lecture-tools').innerHTML.includes('원본 PDF'));
  assert.equal($('#lecture-document').inert,false);
});
test('reordering the TOC flushes annotations and preserves the same chapter-relative page',async()=>{
  const {S,$,calls,run}=fixture(original());await run('lecture()');
  let flushed=false,destroyed=false;
  S.editor={flush:async()=>{flushed=true;assert.equal($('#lecture-document').inert,true);},destroy(){destroyed=true;}};
  S.drafts.s.order.reverse();S.drafts.s.save.schedule();
  await run('flushAutosaves()');
  assert.equal(flushed,true);assert.equal(destroyed,false);assert.equal(calls[0].inert,true);
  assert.equal(S.data.bundle.chapters[0].id,'b');assert.equal(S.page,2);
  assert.equal($('#lecture-document').inert,false);
});
test('excluding all chapters leaves the manager usable; re-inclusion restores the PDF',async()=>{
  const {S,$,run}=fixture(original());await run('lecture()');
  for(const row of S.drafts.s.order)row.included=false;
  S.drafts.s.save.schedule();await run('flushAutosaves()');
  assert.equal(S.data.bundle,null);
  assert.ok($('#lecture-document').innerHTML.includes('포함'));
  assert.ok($('#lecture-toc').innerHTML.includes('add-lecture-pdf'));
  S.drafts.s.order[0].included=true;S.drafts.s.save.schedule();await run('flushAutosaves()');
  assert.equal(S.data.bundle.pages,2);assert.equal(S.page,1);
});
test('a failed rebuild restores interaction and retains the previous PDF',async()=>{
  const {S,$,run}=fixture(original(),{failMerge:true});await run('lecture()');
  S.drafts.s.order[0].title='Changed';S.drafts.s.save.schedule();
  await assert.rejects(run('flushAutosaves()'),/merge failed/);
  assert.equal($('#lecture-document').inert,false);
  assert.equal(S.data.bundle.chapters[0].title,'First');
  await S.drafts.s.save.cancel();
});
