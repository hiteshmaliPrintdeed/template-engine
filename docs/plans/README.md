# Pixovo Implementation Plans

Detailed, executable plans for each stage of [`ROADMAP.md`](../../ROADMAP.md).

## Target

| Requirement | Value |
|---|---|
| Photos per user | 1,000 |
| Concurrent users | 20 |
| Peak photos in flight | 20,000 |
| Sessions | Isolated, no auth this milestone |
| Storage | Local disk, behind a swappable interface |
| Output | 3 genuinely distinct albums, real hero covers, print-ready PDF |
## Architecture & Resilience Specifications

* **Comprehensive Failsafes & Fallbacks:** [`FAILSAFE_AND_FALLBACK_SPEC.md`](../FAILSAFE_AND_FALLBACK_SPEC.md) — Detailed resilience and failure mitigation across client downsampling, network transport, filtering, AI themes, layout solving, storage, and print PDF compilation.
* **Milestone 1 Completion Roadmap:** [`ROADMAP.md`](../../ROADMAP.md)

## Stage index

### Milestone 1 — Engine: correct output under real load (~16–20 days)

| # | Plan | Days | Depends on |
|---|---|---|---|
| 1.1 | [Session continuity & chunked ingest](M1-1.1-session-continuity.md) | 2–3 | — |
| 1.2 | [Restore the data contract](M1-1.2-data-contract.md) | 3–4 | 1.1 |
| 1.3 | [Storage offload](M1-1.3-storage-offload.md) | 2 | 1.1 |
| 1.4 | [Unblock the server](M1-1.4-server-unblock.md) | 2 | 1.3 |
| 1.5 | [Covers & distinct variations](M1-1.5-covers-variations.md) | 3–4 | 1.2 |
| 1.6 | [Fail honestly](M1-1.6-fail-honestly.md) | 0.5 | — |
| 1.7 | [Prove the load target](M1-1.7-load-proof.md) | 3–4 | all above |

### Milestone 2 — Frontend: transitionless & fast (~9–12 days)

| # | Plan | Days | Depends on |
|---|---|---|---|
| 2.1 | [Worker-based downsampling](M2-2.1-worker-downsampling.md) | 2–3 | 1.1 |
| 2.2 | [SSE progress](M2-2.2-sse-progress.md) | 2 | 1.1, 1.7 |
| 2.3 | [Perceived instant](M2-2.3-perceived-instant.md) | 3–4 | 1.2, 2.2 |
| 2.4 | [Interaction polish](M2-2.4-interaction-polish.md) | 2–3 | 2.3 |

### Milestone 3 — Studio, Motion & Repository Polish (~8–9 days)

| # | Plan | Days | Depends on |
|---|---|---|---|
| 3.1 | [Cleanup & de-cluttering](M3-3.1-cleanup-declutter.md) | 1 | — |
| 3.2 | [Guided Story Studio & Gemini title engine](M3-3.2-guided-story-studio.md) | 4–5 | 3.1 |
| 3.3 | [Motion system, verification & repository cleanup](M3-3.3-motion-verification-cleanup.md) | 3 | 3.2 |

## Dependency graph

```
1.1 session continuity ──┬── 1.2 data contract ──── 1.5 covers ──┐
   (BLOCKER)             │                                       │
                         ├── 1.3 storage ──── 1.4 unblock ───────┼── 1.7 load proof
                         │                                       │
                         └── 2.1 worker downsampling             │
                                                                 │
1.6 fail honestly ───────────────────────────────────────────────┘
   (independent, MUST land before 1.7)

1.7 ──── 2.2 SSE ──── 2.3 perceived instant ──── 2.4 polish

3.1 cleanup ──── 3.2 guided story studio ──── 3.3 motion & verification
```

**1.1 is the hard blocker.** Nothing else can be built or load-tested until upload stops being one monolithic request under a session ID minted per-request.

**1.6 is independent but gates 1.7.** The fake-book fallback masks exactly the failures the load test exists to find. It is half a day — do it early, in any spare slot.

## The two findings that drive Milestone 1

**Finding A — the pipeline uploads ~8 GB in a single request.**
`buildDualPayload()` packs every thumbnail *and* every full-resolution original into one `FormData`, POSTed as one request. At 1,000 photos it exhausts browser memory before reaching the network. Originals are then uploaded a *second* time by the background sync. Plans 1.1 and 1.3.

**Finding B — the filter engine's output is discarded at one boundary.**
`process_single_photo` computes `hero_score`, `shell_phash`, `core_phash`, `taken_at`, GPS, `blur_score`, `face_count`. Ingest step 6 builds `PhotoMeta` from only id/filename/urls/dimensions. Clustering, chaptering, and hero selection are therefore all running on null inputs — the album is upload-order with themed palettes. Plan 1.2, which unblocks 1.5.

## How to use these plans

Each plan carries the same eight sections:

1. **Objective** — one paragraph
2. **Current state** — what the code does today, with `file:line`
3. **Target state** — what it should do
4. **Tasks** — ordered, with code sketches
5. **Files touched** — complete change list
6. **Test plan** — what proves it works
7. **Exit criteria** — the gate, measurable
8. **Risks & rollback**

Work a stage top to bottom. Do not start the next stage until the current one's exit criteria are met and its tests are green — the load test in 1.7 is only meaningful if every stage before it actually held.

## Load test results

Measured numbers and the capacity figure: [LOAD-RESULTS.md](LOAD-RESULTS.md).

## Status

| Stage | Status | Owner | Notes |
|---|---|---|---|
| 1.1 | **Done** | | 13 tests green in `backend/tests/`. Also fixed a `NameError` in `get_job()` and made `DB_PATH` env-overridable for test isolation. |
| 1.2 | **Done** | | 26 tests green. Chaptering now splits on real time gaps (`time=2 gps=0 cap=0`). Two plan corrections: `layout_role` values are `DOUBLE_PAGE_HERO`/`FULL_PAGE_HERO`/`STANDARD_FRAME`, and `taken_at` must be gated on `date_source` — see notes below. |
| 1.3 | **Done** | | 44 tests green. `StorageBackend` seam + traversal guard; originals off ingest; survivors-only demand-driven upload with placement prioritisation; 409 export gate; disk guards. Also fixed PDF resolver cross-session `rglob`. |
| 1.4 | **Done** | | 56 tests green. Loop stays responsive: 2.8ms worst-case `/health` across 147 samples during CPU work. Nested pools removed (`finalise_batch` split out), `cv2.setNumThreads(1)`, TTLCache-bounded stores, thread-local SQLite connection, `/health` + `/ready`. |
| 1.5 | **Done** | | 72 tests green. `cover_photos: List[CoverPhoto]` + backend-owned `cover_style`; hero-ranked non-overlapping selection with aspect affinity; per-variation pacing (`spread counts [10, 15, 8]`, 3/3 distinct structures); `BookCarousel3D` consumes real photo lists. Golden + determinism tests. |
| 1.6 | **Done** | | The fake-photobook fallback lived inside `process_async_job`, which 1.4 rewrote — removing it there avoided rewriting the same function twice. Jobs with no photos now fail honestly. Remaining 1.6 items (placeholder paths in `solver.py`/`pdf_exporter.py`, `ensure_sample_placeholders`) still open. |
| 1.7 | **Done** | | 98 tests green. Synthetic corpus (contract verified against every filter gate), load harness, CI. **20 users PASS, /health p99 1.8ms.** Threads beat processes. Found + fixed a face-detector thread-safety crash. See [LOAD-RESULTS.md](LOAD-RESULTS.md). |
| 2.1 | **Done** | | OffscreenCanvas Web Worker pool (`downsample.worker.js` + `WorkerPool`), zero-dependency JPEG APP1 EXIF/GPS parser (`exif.js`), main-thread fallback, hoisted downsampler ref, and 60-tile bounded preview grid. |
| 2.2 | **Done** | | `ProgressBus` pub/sub (`backend/app/progress.py`), `GET /api/jobs/{job_id}/stream` SSE endpoint, per-spread solver `on_progress` callback, `useJobProgress` client hook with 2s polling fallback and unmount cleanup, and zero `setInterval` in `App.jsx`. |
| 2.3 | **Done** | | `PhotoFrame` component (reserved `aspectRatio` + `dominant_colors` gradient placeholder), optimistic local blob previews reconciled with server curation states (`pending`/`kept`/`rejected`), early `themes_ready` skeleton covers, 3-spread virtualization buffer + low-priority prefetch, and GPU-composited step transitions. |
| 2.4 | **Done** | | Non-blocking `ToastProvider` + `useToast` (`role="status"`, `aria-live="polite"`), zero `alert()` dialogs, `CapacityGate` queue panel with auto-retry on `503 at_capacity`, GPU-composited `.carousel-card` with `will-change` only on `.hero`, ARIA `radiogroup` + roving `tabIndex` keyboard navigation, and live `document.title` progress. |
| 3.1 | **Done** | | Removed `BoilerplateInspector`, `SystemStatsDashboard`, `EmotionThemeSelector`, duplicate spread shuffle button, and all emojis across UI & backend. |
| 3.2 | **Done** | | Guided Story Studio configurator, `/api/chat/suggest-titles` with session caching, `include_text` gating across both `solver.py` caption branches and `dsa_solver.py` spread reshuffle, and session-persisted reshuffle preferences. |
| 3.3 | **Done** | | Stage-mapped 4-stage AI Synthesis Loader bound to real `jobProgress` checkpoints (20/45/70/100), `--px-*` luxury design token system, `test_stage_3_2_studio_contract.py` green, and repository cleanup completed. |
