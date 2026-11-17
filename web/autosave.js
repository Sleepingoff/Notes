/* Debounce edits and serialize requests so the newest value is saved last. */
export class AutoSave {
  constructor(save, { delay = 500, onStatus = () => {}, onError = () => {} } = {}) {
    this.save = save;
    this.delay = delay;
    this.onStatus = onStatus;
    this.onError = onError;
    this.dirty = false;
    this.running = null;
    this.timer = null;
  }
  schedule() {
    this.dirty = true;
    clearTimeout(this.timer);
    this.onStatus('pending');
    this.timer = setTimeout(() => { this.flush().catch(() => {}); }, this.delay);
  }
  async cancel() {
    clearTimeout(this.timer);
    this.timer = null;
    this.dirty = false;
    try { await this.running; } catch { /* Keep the last successfully saved value. */ }
    this.dirty = false;
  }
  flush() {
    clearTimeout(this.timer);
    this.timer = null;
    if (this.running) return this.running.then(() => this.dirty ? this.flush() : undefined);
    if (!this.dirty) return Promise.resolve();
    this.running = Promise.resolve().then(async () => {
      while (this.dirty) {
        this.dirty = false;
        this.onStatus('saving');
        try {
          await this.save();
          this.onStatus(this.dirty ? 'pending' : 'saved');
        } catch (error) {
          this.dirty = true;
          this.onStatus('error', error.message);
          this.onError(error);
          throw error;
        }
      }
    }).finally(() => { this.running = null; });
    return this.running;
  }
}
