# Pixovo v3.9 — Developer Quickstart Guide

This guide explains how to install, configure, and boot the clean Pixovo system from Base 0.

---

## 📋 Prerequisites

* **Python:** 3.10 or 3.11+
* **Node.js:** 18.0+ / npm 9.0+

---

## 🚀 1. Backend Setup & Run

1. Open a terminal and navigate to `backend/`:
   ```bash
   cd backend
   ```

2. Create and activate a Python virtual environment:
   * **Windows (PowerShell):**
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   * **macOS / Linux:**
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. *(Optional)* Configure Environment Variables:
   ```bash
   cp .env.example .env
   ```
   `backend/.env.example` documents every variable, its default and why it
   exists. Everything is optional — an absent `.env` runs with built-in
   defaults, and a blank value means "use the default".

   The file **must** live at `backend/.env`. `app/config.py` checks there
   first; its only fallback looks *above* the repository, so a `.env` at the
   repo root is not read.

   *(If `GEMINI_API_KEY` is absent, Pixovo runs in offline/rule-based mode —
   a supported path, not a degraded one.)*

   To put photo storage in S3 instead of on local disk, see
   [`docs/S3_SETUP.md`](docs/S3_SETUP.md).

5. Start the Backend API Server:
   ```bash
   python run.py
   # Or using uvicorn directly:
   uvicorn app.main:app --reload --port 8000
   ```
   * The API server will start on **`http://localhost:8000`**.
   * Interactive OpenAPI documentation: **`http://localhost:8000/docs`**.

---

## 🎨 2. Frontend Setup & Run

1. Open a new terminal and navigate to `frontend/`:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. *(Optional)* Configure Environment Variables:
   ```bash
   cp .env.example .env
   ```
   `frontend/.env.example` covers the dev-server port, the backend proxy target
   and the allowed tunnel hostnames. All optional; defaults match the values
   previously hardcoded in `vite.config.js`.

   None of these carry the `VITE_` prefix, deliberately — Vite injects
   `VITE_`-prefixed variables into the client bundle, so a secret placed in one
   ships to the browser. These configure the dev server in Node only.

4. Start the Vite development server:
   ```bash
   npm run dev
   ```
   * The frontend app will be available on **`http://localhost:5173`**
     (override with `PIXOVO_DEV_PORT`).
   * The Vite server reverse-proxies `/api`, `/uploads` and `/exports` to
     `http://localhost:8000` (override with `PIXOVO_BACKEND_URL`). The app
     calls the API with relative paths, so this proxy is what connects the two
     in development — a production build has no proxy and must be served from
     the same origin as the API, or behind a reverse proxy that maps those
     three prefixes.

---

## 📡 3. Key API Endpoints Reference

| HTTP Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Service health status & persisted photo/job counts |
| `GET` | `/api/stats` | Real-time diagnostic telemetry, stage latencies & SQLite storage |
| `POST` | `/api/photobook/ingest` | Dual-payload ingestion (512px previews + metadata JSON) |
| `POST` | `/api/upload-originals` | Background stream for 300 DPI original print files |
| `POST` | `/api/generate-async` | Asynchronous job submission for AI themes + DSA solver (202 Accepted) |
| `GET` | `/api/jobs/{job_id}` | Polling endpoint for photobook generation status & variations |
| `POST` | `/api/spreads/reshuffle` | Dynamic single-spread reshuffle on click (~10ms) |
| `POST` | `/api/variations/reshuffle` | Regenerate 3 distinct theme variations |
| `POST` | `/api/export-pdf` | Compile 300 DPI high-resolution print PDF with 3mm bleed margins |

---

## 🔍 4. Diagnostic & Inspection Modes

* **Story Mode:** The default user journey: Upload $\rightarrow$ AI Theme Prompt $\rightarrow$ 3D Cover Carousel $\rightarrow$ Virtualized Spreads.
* **System Stats:** Click the top-bar tab **"System Stats"** to see live stage benchmark tables, timing distributions, and persistent SQLite counts.
* **Boilerplate Inspector:** Click **"Boilerplate Inspector"** to inspect registered layouts, slot coordinates, and the 20 canonical theme color swatches.
