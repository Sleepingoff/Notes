import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('const openExtractionErrors ='),source.indexOf('function bankManage('));
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function fixture(){
 const requests=[];let rendered=0;
 const details={dataset:{errorDetails:'job-1'},open:false,isConnected:true};
 const button={dataset:{retry:'job-1'},disabled:false};
 const root={querySelectorAll:selector=>selector==='[data-error-details]'?[details]:[button]};
 const context=vm.createContext({esc,action:f=>f,api:async(path,data)=>requests.push({path,data}),render:async()=>rendered++,root});
 vm.runInContext(code+'\nbindExtractionErrors(root);',context);
 return {details,button,requests,get rendered(){return rendered;},run:expression=>vm.runInContext(expression,context)};
}
test('failure details and retry appear beside the message with safely escaped logs',()=>{
 const f=fixture();
 const html=f.run('extractionError({id:"job-1",status:"failed",error_code:"EXTRACTION_FAILED",error_message:"추출 현황에서 상세 내용을 확인해 주세요.",error:"Traceback:\\nValueError: <bad response>"})');
 assert.ok(html.includes('오류 상세 내용'));
 assert.ok(html.includes('Traceback:\nValueError: &lt;bad response&gt;'));
 assert.ok(html.includes('data-retry="job-1"'));
 assert.ok(!html.includes('추출 현황에서'));
});
test('expanded details remain expanded when the list is rebuilt',()=>{
 const f=fixture();f.details.open=true;f.details.ontoggle();
 const html=f.run('extractionError({id:"job-1",status:"failed",error:"detail"})');
 assert.ok(html.includes('data-error-details="job-1" open'));
 f.details.open=false;f.details.ontoggle();
 assert.ok(!f.run('extractionError({id:"job-1",status:"failed",error:"detail"})').includes('data-error-details="job-1" open'));
 assert.equal(f.requests.length,0);
});
test('retry uses the same task and refreshes the current page',async()=>{
 const f=fixture();f.details.open=true;f.details.ontoggle();
 await f.button.onclick();
 assert.equal(f.requests.length,1);assert.equal(f.requests[0].path,'/api/job/retry');
 assert.equal(f.requests[0].data.id,'job-1');assert.equal(f.rendered,1);
 assert.equal(f.button.disabled,false);
 assert.equal(f.run('openExtractionErrors.size'),0);
});
test('missing logs are explained inline; nonfailed tasks do not show an error',()=>{
 const f=fixture();
 assert.ok(f.run('extractionError({id:"job-1",status:"failed"})').includes('저장된 상세 로그가 없습니다.'));
 for(const status of ['queued','running','done'])assert.equal(f.run(`extractionError({status:"${status}",error:"old error"})`),'');
});
test('an old detached disclosure cannot restore stale expansion state',()=>{
 const f=fixture();f.details.open=true;f.details.isConnected=false;f.details.ontoggle();
 assert.equal(f.run('openExtractionErrors.size'),0);
});
