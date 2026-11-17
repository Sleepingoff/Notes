/* Region coordinates use the same 0–1000 page space as the extraction API. */
export class RegionSelector {
  constructor(svg, onChange = () => {}) {
    this.svg = svg;
    this.onChange = onChange;
    this.mode = 'problem';
    this.problem = null;
    this.images = [];
    this.gesture = null;
    svg.onpointerdown = event => {
      if (event.isPrimary === false || (event.button !== undefined && event.button !== 0)) return;
      const point = this.point(event);
      if (!point) return;
      event.preventDefault();
      svg.setPointerCapture(event.pointerId);
      this.gesture = {start: point, box: [...point, ...point]};
      this.draw();
    };
    svg.onpointermove = event => {
      if (!this.gesture) return;
      const point = this.point(event);
      if (!point) return;
      const [x, y] = this.gesture.start;
      this.gesture.box = [Math.min(x, point[0]), Math.min(y, point[1]), Math.max(x, point[0]), Math.max(y, point[1])];
      this.draw();
    };
    svg.onpointerup = () => {
      if (!this.gesture) return;
      const box = this.gesture.box;
      this.gesture = null;
      if (box[2] - box[0] > 2 && box[3] - box[1] > 2) {
        if (this.mode === 'problem') this.problem = box;
        else if (this.images.length < 16) this.images.push(box);
      }
      this.draw();this.onChange();
    };
    svg.onpointercancel = svg.onlostpointercapture = () => {this.gesture = null;this.draw();};
    this.draw();
  }
  point(event) {
    const r = this.svg.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return [Math.round(Math.max(0, Math.min(1000, (event.clientX-r.left)/r.width*1000))),
      Math.round(Math.max(0, Math.min(1000, (event.clientY-r.top)/r.height*1000)))];
  }
  clear() {this.problem = null;this.images = [];this.gesture = null;this.draw();this.onChange();}
  undoImage() {this.images.pop();this.draw();this.onChange();}
  draw() {
    const rectangle = (box, type, title) => `<g class="region-${type}"><rect x="${box[0]}" y="${box[1]}" width="${box[2]-box[0]}" height="${box[3]-box[1]}"/><text x="${box[0]+6}" y="${box[1]+24}">${title}</text></g>`;
    this.svg.innerHTML = (this.problem ? rectangle(this.problem,'problem','문제') : '') + this.images.map((box,i)=>rectangle(box,'image',`이미지 ${i+1}`)).join('') + (this.gesture ? rectangle(this.gesture.box,this.mode,'선택 중') : '');
  }
  destroy() {
    for (const name of ['onpointerdown','onpointermove','onpointerup','onpointercancel','onlostpointercapture']) this.svg[name] = null;
    this.svg.innerHTML = '';
  }
}
