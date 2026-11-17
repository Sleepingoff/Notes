import test from 'node:test';
import assert from 'node:assert/strict';
import {RegionSelector} from '../web/region_selector.js';

function setup() {
  const svg = {innerHTML: '', setPointerCapture() {}, getBoundingClientRect: () => ({left: 10, top: 20, width: 200, height: 300})};
  const selector = new RegionSelector(svg);
  const event = (x,y) => ({clientX:x,clientY:y,pointerId:1,button:0,preventDefault(){}});
  const drag = (a,b) => {svg.onpointerdown(event(...a));svg.onpointermove(event(...b));svg.onpointerup();};
  return {svg, selector, drag};
}
test('PDF region coordinates account for displayed scale and reverse dragging', () => {
  const {selector, drag} = setup();
  drag([210,320],[110,170]);
  assert.deepEqual(selector.problem,[500,500,1000,1000]);
  selector.mode='image';drag([10,20],[50,80]);
  assert.deepEqual(selector.images,[[0,0,200,200]]);
  selector.undoImage();assert.equal(selector.images.length,0);
  assert.ok(selector.problem);
});
test('cancelled gestures and clicks do not create regions; clearing resets both types', () => {
  const {svg,selector,drag} = setup();
  drag([10,20],[10,20]);assert.equal(selector.problem,null);
  svg.onpointerdown({clientX:10,clientY:20,pointerId:1,preventDefault(){}});
  svg.onpointercancel();svg.onpointerup();assert.equal(selector.problem,null);
  drag([10,20],[210,320]);selector.mode='image';drag([10,20],[50,80]);
  selector.clear();assert.equal(selector.problem,null);assert.equal(selector.images.length,0);
  selector.destroy();assert.equal(svg.onpointerdown,null);
});
