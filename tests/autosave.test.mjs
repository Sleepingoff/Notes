import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
const source = readFileSync(new URL('../web/autosave.js', import.meta.url), 'utf8');
const {AutoSave} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const deferred = () => {let resolve; const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};

test('rapid edits are coalesced; explicit flush saves before leaving a view', async () => {
  let value='', writes=[];
  const save = new AutoSave(async()=>writes.push(value),{delay:20});
  value='1';save.schedule(); value='12';save.schedule();value='123';save.schedule();
  assert.deepEqual(writes,[]);
  await save.flush();
  assert.deepEqual(writes,['123']);
  assert.equal(save.dirty,false);
});
test('edits during an in-flight request are serialized and the newest value wins', async () => {
  const started=deferred(), release=deferred();
  const writes=[];let value='old',active=0,max=0;
  const save=new AutoSave(async()=>{
    const snapshot=value; active++;max=Math.max(max,active);
    if(snapshot==='old'){started.resolve();await release.promise;}
    writes.push(snapshot);active--;
  });
  save.schedule();const flushing=save.flush();await started.promise;
  value='new';save.schedule();const secondFlush=save.flush();
  release.resolve();await Promise.all([flushing,secondFlush]);
  assert.deepEqual(writes,['old','new']);assert.equal(max,1);assert.equal(save.dirty,false);
});
test('errors keep edits dirty, are visible, and can be retried with corrected input', async () => {
  const errors=[],states=[],writes=[];let value='invalid';
  const save=new AutoSave(async()=>{if(value==='invalid')throw new Error('invalid');writes.push(value);},
    {onError:error=>errors.push(error.message),onStatus:state=>states.push(state)});
  save.schedule();await assert.rejects(save.flush(),/invalid/);
  assert.equal(save.dirty,true);assert.deepEqual(errors,['invalid']);assert.equal(states.at(-1),'error');
  value='corrected';save.schedule();await save.flush();
  assert.deepEqual(writes,['corrected']);assert.equal(states.at(-1),'saved');
});
test('idle timeout saves without requiring a button or blur', async () => {
  const done=deferred();let writes=0;
  const save=new AutoSave(async()=>{writes++;done.resolve();},{delay:5});
  save.schedule();await done.promise;await save.flush();assert.equal(writes,1);
});
