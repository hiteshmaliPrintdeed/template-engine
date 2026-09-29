/**
 * Stage 2.1 — Bounded Web Worker Pool.
 * Caps concurrency at min(4, hardwareConcurrency) (or 1 on low-memory <= 2GB devices)
 * so parallel 4K ImageBitmap decodes never OOM the browser tab.
 */

export function getOptimalWorkerCount() {
  if (typeof navigator === 'undefined') return 2;
  if (navigator.deviceMemory && navigator.deviceMemory <= 2) return 1;
  return Math.max(1, Math.min(4, navigator.hardwareConcurrency || 2));
}

export class WorkerPool {
  constructor(workerFactory, size = getOptimalWorkerCount()) {
    this.workerFactory = workerFactory;
    this.size = Math.max(1, size);
    this.workers = Array.from({ length: this.size }, () => ({
      worker: workerFactory(),
      busy: false
    }));
    this.queue = [];
    this.terminated = false;
  }

  run(payload, transfer = []) {
    if (this.terminated) {
      return Promise.reject(new Error('WorkerPool has been terminated.'));
    }
    return new Promise((resolve, reject) => {
      this.queue.push({ payload, transfer, resolve, reject });
      this._pump();
    });
  }

  _pump() {
    if (this.terminated) return;
    const slot = this.workers.find(w => !w.busy);
    if (!slot || this.queue.length === 0) return;

    const task = this.queue.shift();
    slot.busy = true;

    const cleanup = () => {
      slot.worker.removeEventListener('message', onDone);
      slot.worker.removeEventListener('error', onError);
      slot.busy = false;
    };

    const onDone = (e) => {
      cleanup();
      if (e.data && e.data.ok) {
        task.resolve(e.data.result);
      } else {
        task.reject(new Error(e.data?.error || 'Worker task failed'));
      }
      this._pump();
    };

    const onError = (err) => {
      cleanup();
      task.reject(new Error(err?.message || 'Unhandled worker error'));
      this._pump();
    };

    slot.worker.addEventListener('message', onDone);
    slot.worker.addEventListener('error', onError);
    slot.worker.postMessage(task.payload, task.transfer);
  }

  terminate() {
    this.terminated = true;
    this.workers.forEach(w => {
      try { w.worker.terminate(); } catch (_) {}
    });
    while (this.queue.length > 0) {
      const pending = this.queue.shift();
      pending.reject(new Error('WorkerPool terminated'));
    }
  }
}

export default WorkerPool;
