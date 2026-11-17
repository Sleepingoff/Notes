import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
function fixture() {
  const nodes=new Map(),calls=[],editors=[];
  const $=key=>{
    if(!nodes.has(key))nodes.set(key,{isConnected:true,htmlWrites:0,
      set innerHTML(value){this.html=value;this.htmlWrites++;},get innerHTML(){return this.html;}});
    return nodes.get(key);
  };
  const S={subject:'s',route:'lecture',page:1,editor:null,data:{bundle:{pages:3,chapters:[]}}};
  let read=async page=>({pageKey:`chapter:${page}`,marks:[],revision:''});
  const api=async(path,data)=>{
    if(data){calls.push(data);return {};}
    if(path.startsWith('/api/related'))return {};
    return read(Number(new URL('http://local'+path).searchParams.get('page')));
  };
  class PdfEditor {
    constructor(root){this.root=root;this.tool='pen';this.flushCount=0;editors.push(this);root.innerHTML='toolbar and canvas';}
    async flush(){this.flushCount++;if(this.pending){await this.onChange(this.pending);this.pending=null;}}
    destroy(){this.destroyed=true;this.root.innerHTML='';}
    setPage(page){this.page=page;}
  }
  const context=vm.createContext({S,$,PdfEditor,api,url:(p,args)=>p+'?'+new URLSearchParams(args),
    action:fn=>fn,flushAutosaves:async()=>{},syncLectureTOC(){},location:{}});
  const editor=source.slice(source.indexOf('function clampPage('),source.indexOf('function lectureAnchor('));
  const painter=source.slice(source.indexOf('let lectureViewVersion'),source.indexOf('function syncLectureTOC('));
  vm.runInContext(editor+painter,context);
  return {S,$,calls,editors,run:code=>vm.runInContext(code,context),setRead:fn=>{read=fn;}};
}
test('previous, next and page input keep the reader DOM and editor settings',async()=>{
  const {S,$,editors,run}=fixture();await run('paintLectureDocument()');
  const viewerWrites=$('#lecture-document').htmlWrites,toolsWrites=$('#lecture-tools').htmlWrites;
  const editor=S.editor;editor.tool='highlight';editor.color='#ffee00';
  await $('#lecture-next').onclick();
  assert.equal(S.page,2);assert.equal(S.editor,editor);assert.equal(editor.tool,'highlight');
  assert.equal(editor.color,'#ffee00');assert.equal(editors.length,1);
  await $('#lecture-page').onchange({target:{value:'3'}});
  assert.equal($('#lecture-next').disabled,true);
  await $('#lecture-prev').onclick();
  assert.equal(S.page,2);assert.equal($('#lecture-page-bottom').value,2);assert.equal($('#lecture-position').textContent,'/ 3');
  assert.equal($('#lecture-document').htmlWrites,viewerWrites);
  assert.equal($('#lecture-tools').htmlWrites,toolsWrites);
  let prevented=false;
  await $('#lecture-page-bottom').onkeydown({key:'Enter',target:{value:'1'},preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(S.page,1);assert.equal($('#lecture-page').value,1);
  const markup=$('#lecture-document').innerHTML;
  assert.ok(markup.indexOf('id="related-page"')>markup.indexOf('id="lecture-editor"'));
  assert.ok(!markup.includes('<label>페이지'));
  assert.equal(S.editor,editor);
});
test('pending annotations finish on the original page before callback changes',async()=>{
  const {S,$,calls,run}=fixture();await run('paintLectureDocument()');
  S.editor.pending={revision:'r1',marks:[{text:'page one'}]};
  await $('#lecture-next').onclick();
  assert.equal(calls[0].page,1);assert.equal(calls[0].marks[0].text,'page one');
  S.editor.pending={revision:'r2',marks:[{text:'page two'}]};
  await S.editor.flush();assert.equal(calls[1].page,2);
});
test('a slower page request cannot overwrite a newer page',async()=>{
  const {S,$,run,setRead}=fixture();await run('paintLectureDocument()');
  let finish;
  setRead(page=>page===2?new Promise(resolve=>{finish=resolve;}):Promise.resolve({pageKey:`chapter:${page}`,marks:[]}));
  const slow=$('#lecture-next').onclick();
  while(!finish)await Promise.resolve();
  await $('#lecture-next').onclick();
  assert.equal(S.editor.page.pageKey,'chapter:3');
  finish({pageKey:'chapter:2',marks:[]});await slow;
  assert.equal(S.editor.page.pageKey,'chapter:3');assert.equal($('#lecture-editor').inert,false);
});
test('rebuilding a PDF reloads its image without rebuilding the editor',async()=>{
  const {S,$,run}=fixture();await run('paintLectureDocument()');
  const editor=S.editor,oldImage=editor.page.image;
  S.pdfRevision=1;S.data.bundle={...S.data.bundle,pages:4};
  await run('paintLectureDocument()');
  assert.equal(S.editor,editor);assert.notEqual(editor.page.image,oldImage);
  assert.equal($('#lecture-page').max,4);
});
