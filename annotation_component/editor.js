export class PdfEditor {
  constructor(root, { onChange = () => {} } = {}) {
    this.root = root;
    this.onChange = onChange;
    this.marks = [];
    this.undo = [];
    this.redo = [];
    this.tool = "pen";
    this.selected = -1;
    this.pageKey = "";
    this.lastSent = "";
    this.revision = "";
    this.pending = false;
    this.gesture = null;
    this.current = null;
    this.editing = null;
    this.composing = false;
    this.saveChain = Promise.resolve();
    root.classList.add("ink-editor");
    root.innerHTML = `<div class="ink-tools" role="toolbar" aria-label="PDF 편집 도구"><button data-tool="pen" class="active">펜</button><button data-tool="highlight">형광펜</button><button data-tool="text">텍스트</button><button data-tool="erase">지우개</button><label>색상 <input data-id="color" type="color" value="#2563eb"></label><label>굵기 <select data-id="width"><option>2</option><option selected>4</option><option>8</option><option>16</option></select></label><label>글자 <input data-id="font" type="number" min="4" max="120" value="18"></label><button data-id="delete">선택 삭제</button><button data-id="undo">되돌리기</button><button data-id="redo">다시 실행</button><button data-id="clear">페이지 필기 지우기</button></div><div class="ink-status" role="status"></div><div class="ink-paper"><canvas aria-label="PDF 필기 영역" tabindex="0"></canvas><textarea class="ink-text-input" aria-label="PDF 텍스트 직접 편집" spellcheck="false" hidden></textarea><div class="ink-text-frame" aria-label="텍스트 영역 위치와 크기 조절" hidden><span class="ink-text-border" data-border="n"></span><span class="ink-text-border" data-border="e"></span><span class="ink-text-border" data-border="s"></span><span class="ink-text-border" data-border="w"></span><span class="ink-text-handle" data-resize="nw"></span><span class="ink-text-handle" data-resize="n"></span><span class="ink-text-handle" data-resize="ne"></span><span class="ink-text-handle" data-resize="e"></span><span class="ink-text-handle" data-resize="se"></span><span class="ink-text-handle" data-resize="s"></span><span class="ink-text-handle" data-resize="sw"></span><span class="ink-text-handle" data-resize="w"></span></div></div>`;
    this.el = (id) => root.querySelector(`[data-id="${id}"]`);
    this.canvas = root.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
    this.paper = root.querySelector(".ink-paper");
    this.status = root.querySelector(".ink-status");
    this.textArea = root.querySelector(".ink-text-input");
    this.textFrame = root.querySelector(".ink-text-frame");
    this.image = new Image();
    this.image.onload = () => {
      this.canvas.width = this.image.naturalWidth;
      this.canvas.height = this.image.naturalHeight;
      this.draw();
    };
    root.querySelectorAll("[data-tool]").forEach(
      (b) =>
        (b.onclick = () => {
          this.commitText();
          this.tool = b.dataset.tool;
          this.canvas.style.cursor = this.tool === "text" ? "text" : "crosshair";
          if (this.tool !== "text") this.selected = -1;
          root
            .querySelectorAll("[data-tool]")
            .forEach((x) => x.classList.toggle("active", x === b));
          if (this.tool === "highlight") this.el("color").value = "#ffe066";
          else if (this.el("color").value === "#ffe066")
            this.el("color").value = "#2563eb";
          this.draw();
        }),
    );
    this.canvas.onpointerdown = (e) => this.down(e);
    this.canvas.onpointermove = (e) => this.move(e);
    this.canvas.onpointerup = () => this.finish();
    this.canvas.onpointercancel = () => this.finish();
    this.canvas.onlostpointercapture = () => this.finish();
    this.textFrame.onpointerdown = (event) => {
      this.commitText();
      if (this.selected >= 0)
        this.startBoxGesture(event, this.selected, event.target.dataset.resize || null);
    };
    this.textFrame.onpointermove = (event) => this.move(event);
    this.textFrame.onpointerup = () => this.finish();
    this.textFrame.onpointercancel = () => this.finish();
    this.textFrame.onlostpointercapture = () => this.finish();
    this.textArea.oninput = (event) => {
      if (!event.isComposing && !this.composing) this.readText();
    };
    this.textArea.oncompositionstart = () => { this.composing = true; };
    this.textArea.oncompositionend = () => {
      this.composing = false;
      this.readText();
    };
    this.textArea.onblur = (event) => {
      if (!root.querySelector(".ink-tools").contains(event.relatedTarget))
        this.commitText();
    };
    this.textArea.onkeydown = (event) => {
      if (event.isComposing || this.composing || event.keyCode === 229) return;
      if (event.key === "Escape" || (event.key === "Enter" && (event.ctrlKey || event.metaKey))) {
        event.preventDefault();
        event.stopPropagation();
        this.commitText();
        this.canvas.focus();
      }
    };
    this.resizeObserver = new ResizeObserver(() => {
      this.layoutTextInput();
      this.layoutTextFrame();
    });
    this.resizeObserver.observe(this.canvas);
    this.el("delete").onclick = () => {
      this.commitText();
      if (this.selected < 0) return;
      const before = this.copy();
      this.marks.splice(this.selected, 1);
      this.selected = -1;
      this.change(before);
    };
    this.el("undo").onclick = () => {
      this.commitText();
      if (!this.undo.length) return;
      this.redo.push(this.copy());
      this.marks = this.undo.pop();
      this.selected = -1;
      this.publish();
    };
    this.el("redo").onclick = () => {
      this.commitText();
      if (!this.redo.length) return;
      this.undo.push(this.copy());
      this.marks = this.redo.pop();
      this.selected = -1;
      this.publish();
    };
    this.el("clear").onclick = () => {
      this.commitText();
      if (this.marks.length) {
        const before = this.copy();
        this.marks = [];
        this.selected = -1;
        this.change(before);
      }
    };
    this.el("color").onchange = () =>
      this.updateSelected({ color: this.el("color").value });
    this.el("font").onchange = () =>
      this.updateSelected({
        size: Math.max(
          0.005,
          Math.min(0.15, Number(this.el("font").value || 18) / 800),
        ),
      });
  }
  copy() {
    return JSON.parse(JSON.stringify(this.marks));
  }
  setPage({ pageKey, image, marks = [], revision = "" }) {
    if (pageKey !== this.pageKey) {
      this.commitText();
      this.pageKey = pageKey;
      this.marks = JSON.parse(JSON.stringify(marks));
      this.undo = [];
      this.redo = [];
      this.selected = -1;
      this.pending = false;
      this.lastSent = "";
    } else if (this.pending) {
      if (revision === this.lastSent) this.pending = false;
    } else if (!this.gesture && this.editing === null && revision !== this.revision)
      this.marks = JSON.parse(JSON.stringify(marks));
    if (!this.pending) this.revision = revision;
    this.layoutTextFrame();
    if (image !== this.image.src) this.image.src = image;
    else this.draw();
    this.status.textContent = this.pending
      ? ""
      : "텍스트 내부는 글 수정, 테두리는 이동, 조절점은 영역 크기 변경입니다. 빈 곳을 누르면 새 텍스트를 추가합니다.";
  }
  point(e) {
    const r = this.canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    ];
  }
  box(m) {
    const size = m.size || 0.0225;
    return {
      x: m.x,
      y: m.y,
      w: m.boxWidth || 0.3,
      h:
        m.boxHeight ||
        Math.max(
          0.06,
          ((m.text.split("\n").length * size * this.canvas.width) /
            this.canvas.height) *
            1.35,
        ),
    };
  }
  hit(p) {
    for (let i = this.marks.length - 1; i >= 0; i--) {
      const m = this.marks[i];
      if (m.type !== "text") continue;
      const b = this.box(m);
      if (p[0] >= b.x && p[0] <= b.x + b.w && p[1] >= b.y && p[1] <= b.y + b.h)
        return i;
    }
    return -1;
  }
  borderHit(p) {
    const rect = this.canvas.getBoundingClientRect();
    const candidates = this.marks.map((_, index) => index).reverse();
    if (candidates.includes(this.selected)) {
      candidates.splice(candidates.indexOf(this.selected), 1);
      candidates.unshift(this.selected);
    }
    for (const index of candidates) {
      if (this.marks[index].type !== "text") continue;
      const b = this.box(this.marks[index]);
      const left = Math.abs(p[0] - b.x) * rect.width <= 6,
        right = Math.abs(p[0] - b.x - b.w) * rect.width <= 6,
        top = Math.abs(p[1] - b.y) * rect.height <= 6,
        bottom = Math.abs(p[1] - b.y - b.h) * rect.height <= 6;
      if (p[0] < b.x - 6 / rect.width || p[0] > b.x + b.w + 6 / rect.width ||
          p[1] < b.y - 6 / rect.height || p[1] > b.y + b.h + 6 / rect.height) continue;
      if ((left || right) && (top || bottom))
        return { index, handle: `${top ? "n" : "s"}${left ? "w" : "e"}` };
      if (left || right || top || bottom) return { index, handle: null };
      // An upper text box covers any borders belonging to boxes underneath it.
      if (this.hit(p) === index) return null;
    }
    return null;
  }
  startBoxGesture(event, index, handle = null) {
    if (!event.isPrimary || this.tool !== "text" || this.marks[index]?.type !== "text") return;
    event.preventDefault();
    event.stopPropagation();
    this.selected = index;
    this.syncFields();
    this.gesture = {
      type: handle ? "resize" : "drag", handle, index, pointerId: event.pointerId,
      before: this.copy(), start: this.point(event), box: this.box(this.marks[index]),
    };
    (event.currentTarget || this.canvas).setPointerCapture(event.pointerId);
    this.draw();
  }
  layoutTextFrame() {
    const mark = this.marks[this.selected];
    this.textFrame.hidden = this.tool !== "text" || mark?.type !== "text";
    if (this.textFrame.hidden) return;
    const b = this.box(mark), rect = this.canvas.getBoundingClientRect();
    this.textFrame.style.left = `${this.canvas.offsetLeft + b.x * rect.width}px`;
    this.textFrame.style.top = `${this.canvas.offsetTop + b.y * rect.height}px`;
    this.textFrame.style.width = `${b.w * rect.width}px`;
    this.textFrame.style.height = `${b.h * rect.height}px`;
  }
  down(e) {
    if (!this.image.complete || !this.image.naturalWidth) return;
    if (!e.isPrimary) return;
    this.commitText();
    const p = this.point(e);
    if (this.tool === "text") {
      e.preventDefault();
      const border = this.borderHit(p);
      if (border) {
        this.startBoxGesture(e, border.index, border.handle);
        return;
      }
      const i = this.hit(p);
      if (i >= 0) {
        this.selected = i;
        this.openText(i);
      } else {
        this.selected = -1;
        this.textPoint = p;
        this.openText(-1);
      }
      return;
    }
    e.preventDefault();
    this.canvas.setPointerCapture(e.pointerId);
    const before = this.copy();
    this.selected = -1;
    this.gesture = { type: this.tool, before, pointerId: e.pointerId };
    if (this.tool === "erase") {
      this.erase(p);
      return;
    }
    this.current = {
      type: "stroke",
      color: this.el("color").value,
      width: Number(this.el("width").value) / 800,
      opacity: this.tool === "highlight" ? 0.25 : 1,
      points: [p],
    };
    this.draw();
  }
  move(e) {
    if (!this.gesture) {
      if (this.tool === "text") {
        const p = this.point(e), border = this.borderHit(p);
        this.canvas.style.cursor = border
          ? (border.handle ? `${border.handle}-resize` : "move")
          : (this.hit(p) >= 0 ? "text" : "crosshair");
      }
      return;
    }
    if (e.pointerId !== this.gesture.pointerId) return;
    const p = this.point(e),
      g = this.gesture;
    if (g.type === "drag" || g.type === "resize") {
      const mark = this.marks[g.index], b = g.box;
      if (g.type === "drag") {
        mark.x = Math.max(0, Math.min(1 - b.w, b.x + p[0] - g.start[0]));
        mark.y = Math.max(0, Math.min(1 - b.h, b.y + p[1] - g.start[1]));
      } else {
        let left = b.x, right = Math.min(1, b.x + b.w),
          top = b.y, bottom = Math.min(1, b.y + b.h);
        const minWidth = Math.min(0.025, b.w), minHeight = Math.min(0.025, b.h);
        if (g.handle.includes("w")) left = Math.max(0, Math.min(right - minWidth, p[0]));
        if (g.handle.includes("e")) right = Math.min(1, Math.max(left + minWidth, p[0]));
        if (g.handle.includes("n")) top = Math.max(0, Math.min(bottom - minHeight, p[1]));
        if (g.handle.includes("s")) bottom = Math.min(1, Math.max(top + minHeight, p[1]));
        mark.x = left;
        mark.y = top;
        mark.boxWidth = right - left;
        mark.boxHeight = bottom - top;
      }
      this.draw();
      return;
    }
    if (g.type === "erase") {
      this.erase(p);
      return;
    }
    const last = this.current.points.at(-1);
    if (Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.0008) {
      this.current.points.push(p);
      this.draw();
    }
  }
  finish() {
    if (!this.gesture) return;
    const before = this.gesture.before;
    if (this.current) {
      this.marks.push(this.current);
      this.current = null;
    }
    this.gesture = null;
    this.syncFields();
    if (JSON.stringify(before) !== JSON.stringify(this.marks))
      this.change(before);
    else this.draw();
  }
  erase(p) {
    this.marks = this.marks.filter((m) => {
      if (m.type === "text") {
        const b = this.box(m);
        return !(
          p[0] >= b.x &&
          p[0] <= b.x + b.w &&
          p[1] >= b.y &&
          p[1] <= b.y + b.h
        );
      }
      const v = [p[0], (p[1] * this.canvas.height) / this.canvas.width],
        pts = m.points.map((q) => [
          q[0],
          (q[1] * this.canvas.height) / this.canvas.width,
        ]);
      return !pts.some((b, i) => {
        const a = i ? pts[i - 1] : b,
          dx = b[0] - a[0],
          dy = b[1] - a[1],
          t =
            dx || dy
              ? Math.max(
                  0,
                  Math.min(
                    1,
                    ((v[0] - a[0]) * dx + (v[1] - a[1]) * dy) /
                      (dx * dx + dy * dy),
                  ),
                )
              : 0;
        return (
          Math.hypot(v[0] - a[0] - t * dx, v[1] - a[1] - t * dy) <
          m.width / 2 + 0.012
        );
      });
    });
    this.draw();
  }
  openText(index) {
    this.editBefore = this.copy();
    this.editing = index;
    this.selected = index;
    this.composing = false;
    const x = Math.min(0.975, this.textPoint?.[0] || 0),
      y = Math.min(0.98, this.textPoint?.[1] || 0);
    this.textDraft = index >= 0 ? null : {
      type: "text", x, y, text: "",
      color: this.el("color").value,
      size: Math.max(0.005, Math.min(0.15, Number(this.el("font").value || 18) / 800)),
      width: 0.001, opacity: 1,
      boxWidth: Math.min(0.3, 1 - x), boxHeight: Math.min(0.12, 1 - y),
    };
    this.syncFields();
    this.textArea.value = index >= 0 ? this.marks[index].text : "";
    this.textArea.hidden = false;
    this.layoutTextInput();
    this.draw();
    this.textArea.focus({ preventScroll: true });
  }
  layoutTextInput(grow = false) {
    if (this.editing === null) return;
    const mark = this.editing >= 0 ? this.marks[this.editing] : this.textDraft;
    if (!mark) return;
    const b = this.box(mark), rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const style = this.textArea.style;
    style.left = `${this.canvas.offsetLeft + b.x * rect.width}px`;
    style.top = `${this.canvas.offsetTop + b.y * rect.height}px`;
    style.width = `${b.w * rect.width}px`;
    style.height = `${b.h * rect.height}px`;
    style.fontSize = `${mark.size * rect.width}px`;
    style.color = mark.color;
    if (grow) {
      // Let multiline input grow within the page instead of scrolling inside a popup.
      const height = Math.min((1 - b.y) * rect.height,
        Math.max(b.h * rect.height, this.textArea.scrollHeight));
      if (height > b.h * rect.height + 0.5) {
        mark.boxHeight = height / rect.height;
        style.height = `${height}px`;
      }
    }
  }
  readText() {
    if (this.editing === null) return;
    const text = this.textArea.value.slice(0, 10000);
    if (this.textArea.value !== text) this.textArea.value = text;
    if (this.editing < 0) {
      if (!text.trim()) return;
      this.marks.push(this.textDraft);
      this.editing = this.selected = this.marks.length - 1;
      this.textDraft = null;
    }
    const mark = this.marks[this.editing];
    if (mark.text === text) return;
    mark.text = text;
    this.layoutTextInput(true);
    this.publish();
  }
  commitText() {
    if (this.editing === null) return;
    this.readText();
    const before = this.editBefore;
    let removed = false;
    if (this.editing >= 0 && !this.marks[this.editing].text.trim()) {
      this.marks.splice(this.editing, 1);
      this.selected = -1;
      removed = true;
    }
    this.editing = null;
    this.textDraft = null;
    this.editBefore = null;
    this.composing = false;
    this.textArea.hidden = true;
    if (JSON.stringify(before) !== JSON.stringify(this.marks)) this.remember(before);
    if (removed) this.publish();
    else this.draw();
  }
  syncFields() {
    const m = this.marks[this.selected];
    if (m?.type === "text") {
      this.el("color").value = m.color;
      this.el("font").value = Math.round(m.size * 800);
    }
  }
  updateSelected(values) {
    const mark = this.editing === -1 ? this.textDraft : this.marks[this.selected];
    if (mark?.type !== "text") return;
    const before = this.copy();
    Object.assign(mark, values);
    this.layoutTextInput(true);
    if (this.editing === -1) return;
    if (this.editing !== null) this.publish();
    else this.change(before);
  }
  remember(before) {
    this.undo.push(before);
    if (this.undo.length > 40) this.undo.shift();
    this.redo = [];
  }
  change(before) {
    this.remember(before);
    this.publish();
  }
  publish() {
    const revision =
      globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    this.revision = revision;
    this.lastSent = revision;
    this.pending = true;
    const payload = { pageKey: this.pageKey, revision, marks: this.copy() };
    this.status.textContent = "";
    this.saveChain = this.saveChain
      .catch(() => {})
      .then(() => {
        const result = this.onChange(payload);
        if (result && typeof result.then === "function")
          return result.then(() => this.ack(revision));
      })
      .catch((error) => {
        this.status.textContent = "저장 실패: " + error.message;
        throw error;
      });
    this.draw();
  }
  ack(revision) {
    if (revision === this.lastSent) {
      this.pending = false;
      this.status.textContent = "";
    }
  }
  flush() {
    this.finish();
    this.commitText();
    return this.saveChain;
  }
  lines(text, width) {
    const lines = [];
    for (const paragraph of text.split("\n")) {
      let row = "";
      for (const char of paragraph) {
        if (row && this.ctx.measureText(row + char).width > width) {
          lines.push(row);
          row = char;
        } else row += char;
      }
      lines.push(row);
    }
    return lines;
  }
  draw() {
    if (!this.image.complete || !this.image.naturalWidth) return;
    const c = this.ctx,
      W = this.canvas.width,
      H = this.canvas.height;
    c.clearRect(0, 0, W, H);
    c.drawImage(this.image, 0, 0);
    const draw = (m) => {
      c.save();
      c.globalAlpha = m.opacity;
      c.strokeStyle = c.fillStyle = m.color;
      c.lineCap = c.lineJoin = "round";
      if (m.type === "stroke") {
        c.lineWidth = m.width * W;
        c.beginPath();
        const p = m.points[0];
        c.moveTo(p[0] * W, p[1] * H);
        m.points.slice(1).forEach((p) => c.lineTo(p[0] * W, p[1] * H));
        if (m.points.length === 1) {
          c.arc(p[0] * W, p[1] * H, c.lineWidth / 2, 0, Math.PI * 2);
          c.fill();
        } else c.stroke();
      } else {
        const b = this.box(m);
        c.font = `${m.size * W}px sans-serif`;
        c.textBaseline = "top";
        c.beginPath();
        c.rect(b.x * W, b.y * H, b.w * W, b.h * H);
        c.clip();
        this.lines(m.text, b.w * W).forEach((line, i) =>
          c.fillText(line, b.x * W, b.y * H + i * m.size * W * 1.35),
        );
      }
      c.restore();
    };
    this.marks.forEach((mark, index) => {
      if (this.editing === null || index !== this.editing) draw(mark);
    });
    this.layoutTextInput();
    this.layoutTextFrame();
    if (this.current) draw(this.current);
    if (this.tool === "text") {
      c.save();
      c.strokeStyle = "#8ba8d4";
      c.lineWidth = 1;
      c.setLineDash([4, 4]);
      this.marks.forEach((mark, index) => {
        if (mark.type !== "text" || index === this.selected) return;
        const b = this.box(mark);
        c.strokeRect(b.x * W, b.y * H, b.w * W, b.h * H);
      });
      c.restore();
    }
    const textChanged = this.editing !== null &&
      JSON.stringify(this.editBefore) !== JSON.stringify(this.marks);
    this.el("undo").disabled = !this.undo.length && !textChanged;
    this.el("redo").disabled = !this.redo.length || textChanged;
    this.el("delete").disabled = this.selected < 0;
  }
  destroy() {
    this.commitText();
    this.resizeObserver.disconnect();
    this.root.innerHTML = "";
  }
}
