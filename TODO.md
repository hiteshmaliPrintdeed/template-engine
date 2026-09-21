# 📌 Pixovo v3.9 — Future Action Plan & Technical TODOs

This document outlines the high-priority engineering tasks, optimizations, and production hardening steps to be implemented in subsequent phases.

---

## 🧹 1. Clean-up & Removal of Developer/Debug Functionalities

Before rolling out to production end-users, strip out internal development inspection views and mock fallback data:

- [ ] **Remove Boilerplate Inspector Tab:**
  - Remove `BoilerplateInspector.jsx` and its navigation trigger in `ToolbarHeader.jsx`.
  - Disable raw template JSON inspection endpoints (`/api/templates`, `/api/palettes`, `/api/categories`) from public access.
- [ ] **Gate Diagnostic Telemetry Dashboard (`SystemStatsDashboard.jsx`):**
  - Restrict `/api/stats` and `SystemStatsDashboard.jsx` behind an admin authentication route (e.g. `/admin/stats` or basic auth header) rather than exposing server internals on the main UI toolbar.
- [ ] **Purge Hardcoded Mock Sample Photos:**
  - Remove mock placeholder fallback photos (e.g., `sample_1`, `sample_2`, `sample3.jpg` in `main.py` and `solver.py`) and replace with explicit user validation errors (`"No valid surviving photos uploaded to generate album"`).
- [ ] **Remove Scratch & Verification Code:**
  - Clean up legacy root directories (`Filter/`, `Template_Engine_under_dev/`, `backend/verify_*.py`).

---

## ☁️ 2. Direct-to-S3 / Cloud Storage Optimization

Eliminate server disk I/O and network bandwidth bottlenecks by switching to direct cloud storage.
**Shipped — see [`docs/S3_SETUP.md`](docs/S3_SETUP.md).** Off by default
(`PIXOVO_STORAGE=local`); enabling it is a config change, not a deploy.

- [x] **S3 Pre-Signed Upload Handshake:**
  - `POST /api/uploads/presign` + `POST /api/uploads/confirm`. Presigned **POST**
    rather than PUT, because only a POST policy can carry a
    `content-length-range` condition — a presigned PUT's `Content-Length` is
    client-supplied, so signing it enforces nothing.
  - `App.jsx` uploads 300 DPI originals browser-to-bucket via
    `utils/uploadTransport.js`. The client does not decide how to upload, it
    asks: presign answers `mode: "proxy"` when direct upload is off, so
    rollback needs no client deploy.
  - 512px thumbnails deliberately still POST to `/api/photobook/ingest` and are
    written to the bucket by the backend. The Phase-1 filter engine has to
    decode those bytes anyway, so routing them via the bucket would add a
    download per photo on the request path for nothing.
- [ ] **S3 Event-Driven Webhooks / Lambda Thumbnail Resizing (Optional):**
  - Trigger automated image validation and EXIF metadata extraction via AWS Lambda / Cloud Functions on S3 upload events.
- [x] **Serving images from the bucket:**
  - `/uploads/{key}` 307-redirects to a short-lived presigned GET; the bucket
    stays private with Block Public Access on.
  - `url_for()` returns the same durable `/uploads/{key}` string in both modes,
    so **nothing persisted changes** and switching modes needs no data
    migration. This is deliberate: those strings live in four columns of
    `photos`, are embedded in `jobs.variations_json` by the solver, and are
    read back out by `dsa_solver.reshuffle_single_spread_engine()` — an
    expiring URL in any of those places would rot.
- [ ] **CloudFront in front of the bucket:**
  - Now a change to the media route only, since `url_for()` already returns a
    stable relative path. No data migration required.
- [ ] **Retention sweep (blocks unbounded bucket growth):**
  - `StorageBackend.delete_prefix()` and `LocalObjectCache.invalidate_prefix()`
    exist and are tested but have no production caller, and
    `sessions.status = 'expired'` is read in two places and never written.
    Until this lands, the bucket lifecycle rule in `docs/S3_SETUP.md` is the
    only thing bounding growth.
- [ ] **Orphan reconciler:**
  - `photos.presigned_at` is recorded so a sweep can find rows with
    `original_synced = 0 AND presigned_at < now - 15min`, `head()` the
    deterministic key, and confirm server-side.

---

## 🖨️ 3. Print Engine Research & Upgrades (300 DPI Vector PDF)

Enhance commercial print quality, color management, and bleed accuracy:

- [ ] **CMYK Color Space Support & ICC Profiles:**
  - Add CMYK color conversion (`PDF/X-1a` or `PDF/X-4` standard) with embedded ICC color profiles (e.g. *FOGRA39* or *GRACoL*) for commercial offset and digital presses.
- [ ] **Face & Salience-Aware Smart Cropping in PDF:**
  - Integrate lightweight face bounding boxes into `pdf_exporter.py` so that photo slot cropping never clips heads or faces when aspect ratios don't match the slot.
- [ ] **Page-by-Page Streaming PDF Compilation:**
  - Modify `pdf_exporter.py` to stream pages onto disk incrementally rather than buffering all 100+ uncompressed bitmaps in server RAM simultaneously.
- [ ] **Print Lab Webhook Integration:**
  - Implement automated order submission to commercial print-on-demand APIs (e.g., Prodigi, Gelato, or local fulfillment labs).

---

## 🧠 4. AI & Layout Solver Optimizations

Enhance intelligence while keeping token costs low and latency under 2 seconds:

- [ ] **Activate 2-Tier Hierarchical AI Macro-Clustering:**
  - When re-enabling Gemini API, activate the structured cluster summary flow documented in `story_ai.py` (sending 10–15 chapter summaries instead of 1,000 photo prompts).
- [ ] **Dynamic Multi-Photo Spreads (4–6 Photos per Page):**
  - Expand `dsa_solver.py` page packing algorithm to support dynamic collage layouts with 4, 5, and 6 photos per page.
- [ ] **User Slot Drag-and-Drop Reordering:**
  - Implement interactive canvas photo swaps in `SpreadViewer.jsx` allowing users to swap photos between slots or spreads interactively.

---

## 🔒 5. Production Hardening & Security

- [ ] **Migrate Persistent Storage to PostgreSQL & Redis:**
  - Upgrade from SQLite WAL mode to managed PostgreSQL (Amazon RDS) and Redis for distributed horizontally-scaled worker clusters.
- [ ] **IP-Based Rate Limiting & Auth:**
  - Implement `slowapi` rate limiting on upload and layout generation routes to protect against Denial of Service (DoS).
- [ ] **Automated Upload Cleanup Job:**
  - Set a 24-hour retention TTL on temporary session files and exported PDFs to prevent storage bloat.
