import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../annotation_component/editor.js', import.meta.url), 'utf8');
const { PdfEditor } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
globalThis.Image = class {
  complete = true;
  naturalWidth = 1000;
  naturalHeight = 1400;
  set src(value) { this.url = value; this.onload?.(); }
  get src() { return this.url; }
};
globalThis.ResizeObserver = class {
  constructor(callback) { this.callback = callback; }
  observe() {}
  disconnect() { this.disconnected = true; }
};

function fixture(marks = []) {
  const elements = new Map(), drawing = [], saves = [];
  const context = new Proxy({measureText: text => ({width: text.length * 10})}, {
    get: (target, key) => key in target ? target[key] : (...args) => drawing.push([key, ...args]),
  });
  const element = key => {
    if (!elements.has(key)) elements.set(key, {
      style: {}, hidden: true, value: '', textContent: '', offsetLeft: 0, offsetTop: 0,
      scrollHeight: 80, disabled: false, classList: {toggle() {}},
      focus() { this.focused = true; },
      getContext: () => context,
      getBoundingClientRect: () => ({left: 0, top: 0, width: 500, height: 700}),
      setPointerCapture() {}, contains: node => [...elements].some(([k, v]) => k.startsWith('[data-id=') && v === node),
    });
    return elements.get(key);
  };
  const tools = ['pen', 'highlight', 'text', 'erase'].map(tool => ({dataset: {tool}, classList: {toggle() {}}}));
  const root = {innerHTML: '', classList: {add() {}}, querySelector: element, querySelectorAll: () => tools};
  const editor = new PdfEditor(root, {onChange: async payload => saves.push(payload)});
  editor.el('color').value = '#2563eb';
  editor.el('font').value = '18';
  editor.el('width').value = '4';
  editor.setPage({pageKey: 'chapter:0', image: '/page.png', marks, revision: 'initial'});
  tools[2].onclick();
  const click = (x, y) => editor.down({isPrimary: true, clientX: x * 500, clientY: y * 700, preventDefault() {}, stopPropagation() {}, pointerId: 1});
  const type = value => { editor.textArea.value = value; editor.textArea.oninput({isComposing: false}); };
  return {editor, root, saves, drawing, tools, click, type};
}
const mark = () => ({type: 'text', text: '기존 내용', x: .1, y: .1, boxWidth: .3, boxHeight: .12, size: .025, color: '#112233', width: .001, opacity: 1});

test('edits existing text inside its original region and autosaves without duplication', async () => {
  const {editor, root, saves, drawing, click, type} = fixture([mark()]);
  assert.ok(!root.innerHTML.includes('data-id="commit"'));
  assert.ok(!root.innerHTML.includes('ink-text-edit'));
  click(.15, .15);
  assert.equal(editor.textArea.hidden, false);
  assert.equal(editor.textArea.value, '기존 내용');
  assert.equal(editor.textArea.style.left, '50px');
  assert.equal(editor.textArea.style.top, '70px');
  assert.equal(editor.textArea.style.width, '150px');
  assert.equal(editor.textArea.style.fontSize, '12.5px');
  assert.equal(editor.textArea.style.color, '#112233');
  drawing.length = 0;
  type('수정한 내용\n다음 줄');
  await editor.saveChain;
  assert.equal(saves.length, 1);
  assert.equal(saves[0].marks.length, 1);
  assert.equal(saves[0].marks[0].text, '수정한 내용\n다음 줄');
  assert.equal(saves[0].marks[0].x, .1);
  assert.ok(!drawing.some(call => call[0] === 'fillText')); // active text is rendered by the input only
  assert.equal(editor.el('undo').disabled, false);
  editor.textArea.onblur({relatedTarget: null});
  assert.equal(editor.textArea.hidden, true);
  assert.equal(editor.undo.length, 1);
  editor.el('undo').onclick(); await editor.flush();
  assert.equal(editor.marks[0].text, '기존 내용');
  editor.el('redo').onclick(); await editor.flush();
  assert.equal(editor.marks[0].text, '수정한 내용\n다음 줄');
});

test('new text starts at the clicked location; repeated input updates one object', async () => {
  const {editor, saves, click, type} = fixture();
  click(.8, .4);
  assert.equal(editor.textArea.style.left, '400px');
  assert.equal(editor.marks.length, 0);
  assert.equal(saves.length, 0);
  type('새'); type('새 텍스트');
  await editor.flush();
  assert.equal(editor.marks.length, 1);
  assert.equal(editor.marks[0].text, '새 텍스트');
  assert.equal(editor.marks[0].x, .8);
  assert.equal(editor.undo.length, 1);
  editor.el('undo').onclick(); await editor.flush();
  assert.equal(editor.marks.length, 0);
});

test('Korean composition is saved when complete; Escape does not interrupt composition', async () => {
  const {editor, saves, click} = fixture([mark()]);
  click(.15, .15);
  editor.textArea.oncompositionstart();
  editor.textArea.value = '한';
  editor.textArea.oninput({isComposing: true});
  editor.textArea.onkeydown({key: 'Escape', isComposing: true});
  assert.equal(editor.textArea.hidden, false);
  assert.equal(saves.length, 0);
  editor.textArea.value = '한글';
  editor.textArea.oncompositionend();
  await editor.saveChain;
  assert.equal(saves.at(-1).marks[0].text, '한글');
  editor.textArea.onkeydown({key: 'Escape', preventDefault() {}, stopPropagation() {}});
  assert.equal(editor.textArea.hidden, true);
  assert.equal(editor.marks.length, 1);
});

test('empty drafts are discarded; clearing an existing field removes it on exit', async () => {
  const {editor, click, type} = fixture([mark()]);
  click(.8, .8); editor.commitText();
  assert.equal(editor.marks.length, 1);
  click(.15, .15); type('');
  await editor.flush();
  assert.equal(editor.marks.length, 0);
  editor.el('undo').onclick(); await editor.flush();
  assert.equal(editor.marks[0].text, '기존 내용');
});

test('style controls affect active and draft text; multiline input grows within the page', async () => {
  const {editor, click, type} = fixture();
  click(.2, .8);
  editor.updateSelected({color: '#abcdef', size: .03});
  assert.equal(editor.textArea.style.color, '#abcdef');
  editor.textArea.scrollHeight = 500;
  type('long\ntext');
  editor.updateSelected({color: '#123456'});
  await editor.saveChain;
  assert.equal(editor.marks[0].color, '#123456');
  assert.ok(editor.marks[0].boxHeight <= 1 - editor.marks[0].y);
  assert.equal(editor.textArea.style.color, '#123456');
  editor.textArea.onblur({relatedTarget: editor.el('font')});
  assert.equal(editor.textArea.hidden, false);
  await editor.flush();
});

test('switching tools and flushing saves current input before navigation', async () => {
  const {editor, tools, saves, click} = fixture([mark()]);
  click(.15, .15);
  editor.textArea.value = '페이지 이동 전 내용'; // still inside an IME session
  tools[0].onclick();
  await editor.flush();
  assert.equal(editor.textArea.hidden, true);
  assert.equal(saves.at(-1).marks[0].text, '페이지 이동 전 내용');
  assert.equal(saves.at(-1).pageKey, 'chapter:0');
  editor.destroy();
  assert.equal(editor.resizeObserver.disconnected, true);
});

function pointer(x, y, extra = {}) {
  return {isPrimary: true, clientX: x * 500, clientY: y * 700,
    preventDefault() {}, stopPropagation() {}, pointerId: 1, target: {dataset: {}}, ...extra};
}
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);

test('border click selects a box; dragging moves it without editing text or adding marks', async () => {
  const {editor, click, saves} = fixture([mark()]);
  click(.25, .1);
  assert.equal(editor.gesture.type, 'drag');
  assert.equal(editor.editing, null);
  assert.equal(editor.textArea.hidden, true);
  assert.equal(editor.textFrame.hidden, false);
  editor.move(pointer(.45, .3));
  near(editor.marks[0].x, .3);
  near(editor.marks[0].y, .3);
  editor.finish(); await editor.flush();
  assert.equal(saves.length, 1);
  assert.equal(editor.marks.length, 1);
  assert.equal(editor.marks[0].text, '기존 내용');
  near(editor.marks[0].boxWidth, .3);
  near(editor.marks[0].size, .025);
  editor.el('undo').onclick(); await editor.flush();
  near(editor.marks[0].x, .1); near(editor.marks[0].y, .1);
  editor.el('redo').onclick(); await editor.flush();
  near(editor.marks[0].x, .3);
});

test('selected box border receives pointer events while inline text is active', async () => {
  const {editor, click, type, saves} = fixture([mark()]);
  click(.15, .15); type('편집 후 이동');
  assert.equal(editor.editing, 0);
  editor.textFrame.onpointerdown(pointer(.25, .1, {currentTarget: editor.textFrame}));
  assert.equal(editor.editing, null);
  assert.equal(editor.gesture.type, 'drag');
  editor.textFrame.onpointermove(pointer(.35, .2));
  editor.textFrame.onpointerup();
  await editor.flush();
  assert.equal(saves.at(-1).marks[0].text, '편집 후 이동');
  near(saves.at(-1).marks[0].x, .2);
  assert.equal(editor.undo.length, 2); // content and movement are separate undo steps
  editor.el('undo').onclick(); await editor.flush();
  near(editor.marks[0].x, .1);
  assert.equal(editor.marks[0].text, '편집 후 이동');
  click(.15, .15);
  assert.equal(editor.textArea.value, '편집 후 이동');
});

test('corner resizing changes the box region, preserving text and font size', async () => {
  const {editor, click} = fixture([mark()]);
  click(.4, .22);
  assert.equal(editor.gesture.handle, 'se');
  editor.move(pointer(.7, .5)); editor.finish(); await editor.flush();
  near(editor.marks[0].boxWidth, .6); near(editor.marks[0].boxHeight, .4);
  near(editor.marks[0].x, .1); near(editor.marks[0].size, .025);
  assert.equal(editor.marks.length, 1);
  assert.equal(editor.marks[0].text, '기존 내용');
  editor.el('undo').onclick(); await editor.flush();
  near(editor.marks[0].boxWidth, .3); near(editor.marks[0].boxHeight, .12);
});

test('all eight resize handles respect minimum size and page bounds', async () => {
  for (const handle of ['nw','n','ne','e','se','s','sw','w']) {
    const {editor, click} = fixture([mark()]);
    click(.15, .15); editor.commitText();
    editor.textFrame.onpointerdown(pointer(.4, .22, {
      currentTarget: editor.textFrame, target: {dataset: {resize: handle}},
    }));
    assert.equal(editor.gesture.handle, handle);
    editor.move(pointer(2, 2)); editor.finish(); await editor.flush();
    const m = editor.marks[0];
    assert.ok(m.x >= 0 && m.y >= 0);
    assert.ok(m.boxWidth >= .005 && m.boxHeight >= .005);
    assert.ok(m.x + m.boxWidth <= 1.000000001);
    assert.ok(m.y + m.boxHeight <= 1.000000001);
    near(m.size, .025);
  }
});

test('dragging is clamped to the page; flush saves an unfinished gesture', async () => {
  const {editor, click, saves} = fixture([mark()]);
  click(.25, .1); editor.move(pointer(2, 2));
  await editor.flush();
  assert.equal(editor.gesture, null);
  near(editor.marks[0].x, .7); near(editor.marks[0].y, .88);
  near(saves.at(-1).marks[0].x, .7);
  assert.equal(editor.undo.length, 1);
});

test('hover distinguishes text interiors, borders and corners; no-op border clicks do not save', async () => {
  const {editor, click, saves, tools} = fixture([mark()]);
  editor.move(pointer(.15, .15)); assert.equal(editor.canvas.style.cursor, 'text');
  editor.move(pointer(.25, .1)); assert.equal(editor.canvas.style.cursor, 'move');
  editor.move(pointer(.4, .22)); assert.equal(editor.canvas.style.cursor, 'se-resize');
  click(.25, .1); editor.finish(); await editor.flush();
  assert.equal(saves.length, 0);
  assert.equal(editor.undo.length, 0);
  tools[0].onclick();
  assert.equal(editor.textFrame.hidden, true);
});

test('page switches retain tools and canvas while resetting page-specific edit history', async () => {
  const {editor, root, tools, click, type, saves} = fixture([mark()]);
  const canvas=editor.canvas, textarea=editor.textArea, toolbar=root.innerHTML;
  click(.15,.15);type('이전 페이지 수정');await editor.flush();
  assert.equal(saves.at(-1).pageKey,'chapter:0');
  tools[1].onclick();editor.el('width').value='8';editor.el('font').value='24';
  editor.setPage({pageKey:'chapter:1',image:'/page-2.png',marks:[],revision:'new'});
  assert.equal(editor.canvas,canvas);assert.equal(editor.textArea,textarea);
  assert.equal(root.innerHTML,toolbar);assert.equal(editor.tool,'highlight');
  assert.equal(editor.el('width').value,'8');assert.equal(editor.el('font').value,'24');
  assert.equal(editor.el('color').value,'#ffe066');
  assert.equal(editor.undo.length,0);assert.equal(editor.redo.length,0);
  assert.equal(editor.marks.length,0);assert.equal(editor.textArea.hidden,true);
  assert.equal(editor.textFrame.hidden,true);
});
