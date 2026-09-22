import os

import uvicorn

if __name__ == "__main__":
    # Defaults reproduce the old dev behaviour minus the reload watcher, which
    # must be off under a process supervisor: it spawns a second process and
    # restarts the app whenever anything under the tree is touched, including
    # the SQLite WAL and the uploads directory the app writes to itself.
    host = os.getenv("PIXOVO_HOST", "0.0.0.0")
    port = int(os.getenv("PIXOVO_PORT", "8000"))
    reload = os.getenv("PIXOVO_RELOAD", "0") == "1"

    print(f"[Pixovo Template Engine Backend] Starting FastAPI server on http://{host}:{port} ...")
    # Single worker, deliberately: the rate limiter, the TTL caches and the
    # BackgroundTasks job runner are all in-process state (see
    # app/upload_policy.py). Adding workers silently breaks all three.
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
