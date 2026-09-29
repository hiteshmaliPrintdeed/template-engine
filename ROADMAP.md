# Pixovo — Completion Roadmap

*Priority-ordered plan. Derived from a direct read of the code on disk, not from `ARCHITECTURE.md` or `MVP_REPORT.md` — both have drifted from reality (see [Appendix A](#appendix-a--documentation-corrections)).*

**Detailed per-stage implementation plans: [`docs/plans/`](docs/plans/README.md)**

---

## Target

An MVP that competes with Mixbook-class products, demonstrated locally.

| Requirement | Target |
|---|---|
| Photos per user | 1,000 |
| Concurrent users | 20 |
| Peak photos in flight | 20,000 |
| Session model | Isolated sessions, no auth this milestone |
| Storage | Local disk, behind a swappable interface |
| Output | 3 genuinely distinct themed albums, real covers, print-ready PDF |

## Priorities, as set

1. **Milestone 1 — Engine: correct output under real load.** Everything else waits.
2. **Milestone 2 — Frontend: transitionless and fast.** The user should never see the machinery.
3. **Milestone 3 — Everything else.** Explicitly parked, not forgotten.

**M1 ≈ 16–20 days · M2 ≈ 9–12 days.**

---

## The two findings that define Milestone 1

### Finding A — The pipeline uploads ~8 GB in one request

[`buildDualPayload()`](frontend/src/utils/client_downsampler.js) packs every thumbnail **and every full-resolution original** into a single `FormData`, POSTed as one request by [`App.jsx:145`](frontend/src/App.jsx). At 1,000 photos × ~8 MB that is a **~8 GB single POST** — it exhausts browser memory before reaching the network. Originals are then uploaded a *second* time by the background sync.

Compounding it: ingest generates `session_id = uuid4().hex[:8]` **inside the handler** ([main.py:138](backend/app/main.py:138)) and takes no session parameter, so chunking as-is creates one orphaned session per chunk. Session continuity and chunking are one indivisible task.

→ Plans [1.1](docs/plans/M1-1.1-session-continuity.md), [1.3](docs/plans/M1-1.3-storage-offload.md)

### Finding B — The filter engine's output is discarded at one boundary

This is the root cause of "not giving the exact outcome we need."

`process_single_photo()` computes `hero_score`, `layout_role`, `shell_phash`, `core_phash`, `taken_at`, GPS, `blur_score`, `face_count` ([filter_engine.py:668](backend/app/engine/filter/filter_engine.py:668)), plus an explicit `event_cover_photo_id` per cluster ([:845](backend/app/engine/filter/filter_engine.py:845)).

Ingest step 6 ([main.py:230](backend/app/main.py:230)) builds `PhotoMeta` from **only** id, filename, URLs, dimensions, and a **hardcoded** `dominant_colors=["#2C3E50", "#ECF0F1"]`. Everything else is dropped.

Four systems are silently running on null inputs:

| Consumer | Needs | Receives | Result |
|---|---|---|---|
| `cluster_photos_2tier_engine` | `shell_phash`, `core_phash` | `""` → distance `99` sentinel | Spreads grouped by **array order** |
| `partition_macro_chapters` | `timestamp_epoch` | field **doesn't exist** → `0` | Chapters are **fixed-size chunks** |
| Cover selection | `hero_score` | `0.8` and `False` for all | `photos[0]` → the dummy cover |
| Colour theming | `dominant_colors` | same 2 colours for all | Dead |

The album today is **upload-order photos, chunked by count, with themed palettes**. Every algorithm is running; every one is running on nulls. One boundary fix restores all four.

→ Plan [1.2](docs/plans/M1-1.2-data-contract.md), which unblocks [1.5](docs/plans/M1-1.5-covers-variations.md)

---

# Milestone 1 — Engine

**Done when:** 20 simulated users each push 1,000 photos through upload → filter → cluster → theme → layout → export, concurrently, on one machine, without the server stalling — and each gets three visually distinct albums with real hero-selected covers.

| # | Stage | Days | Summary |
|---|---|---|---|
| [1.1](docs/plans/M1-1.1-session-continuity.md) | Session continuity & chunked ingest | 2–3 | Explicit session lifecycle; thumbnails-only chunks of 40; idempotent + resumable; session survives refresh. **`[BLOCKER]`** |
| [1.2](docs/plans/M1-1.2-data-contract.md) | Restore the data contract | 3–4 | Carry the filter engine's full output into `PhotoMeta`, persist it, read it. Restores clustering, chaptering, hero selection. |
| [1.3](docs/plans/M1-1.3-storage-offload.md) | Storage offload | 2 | Originals off the ingest path; demand-driven upload prioritised by placement; `StorageBackend` seam; disk guard. |
| [1.4](docs/plans/M1-1.4-server-unblock.md) | Unblock the server | 2 | Stop full-res decode and the layout solver running on the event loop; one correctly-sized pool; bounded caches. |
| [1.5](docs/plans/M1-1.5-covers-variations.md) | Covers & distinct variations | 3–4 | `cover_photos: List[CoverPhoto]`; hero-ranked, non-overlapping selection; per-variation pacing; golden tests. |
| [1.6](docs/plans/M1-1.6-fail-honestly.md) | Fail honestly | 0.5 | Delete the fake-photobook fallback and every placeholder path. **Must land before 1.7.** |
| [1.7](docs/plans/M1-1.7-load-proof.md) | Prove the load target | 3–4 | Synthetic corpus, 20-user harness, regression tests, CI, measured capacity number. |

### Dependency order

```
1.1 ──┬── 1.2 ──── 1.5 ──┐
      ├── 1.3 ──── 1.4 ──┼── 1.7
      └── 2.1            │
1.6 ─────────────────────┘
```

---

# Milestone 2 — Frontend

**Done when:** from drop to finished album the user never sees a frozen tab, a layout shift, a spinner without a number, or a dialog that blocks their upload.

Starts after M1's gates are green — [2.2](docs/plans/M2-2.2-sse-progress.md) and [2.3](docs/plans/M2-2.3-perceived-instant.md) consume APIs M1 creates.

| # | Stage | Days | Summary |
|---|---|---|---|
| [2.1](docs/plans/M2-2.1-worker-downsampling.md) | Worker-based downsampling | 2–3 | Web Worker pool + `OffscreenCanvas`; client EXIF/GPS extraction; fix object-URL leak and the 1,000-image grid. |
| [2.2](docs/plans/M2-2.2-sse-progress.md) | SSE progress | 2 | Replace 500 ms polling (40 req/s at target) with SSE; real per-photo progress instead of four hardcoded milestones. |
| [2.3](docs/plans/M2-2.3-perceived-instant.md) | Perceived instant | 3–4 | Render from local blobs before the server responds; colour placeholders from `dominant_colors`; skeleton covers; zero layout shift. |
| [2.4](docs/plans/M2-2.4-interaction-polish.md) | Interaction polish | 2–3 | Remove blocking `alert()`; composited carousel motion; queue/error states; keyboard + reduced-motion. |

---

# Milestone 3 — Studio, Motion & Parked Work

### Shipped in Milestone 3 ([3.1](docs/plans/M3-3.1-cleanup-declutter.md) · [3.2](docs/plans/M3-3.2-guided-story-studio.md) · [3.3](docs/plans/M3-3.3-motion-verification-cleanup.md))

- **Cleanup & De-Cluttering ([Stage 3.1](docs/plans/M3-3.1-cleanup-declutter.md)):** Removed `BoilerplateInspector` and `SystemStatsDashboard` from the toolbar, deleted unused `EmotionThemeSelector.jsx`, removed duplicate spread shuffle buttons, purged hardcoded ISKCON placeholders, and enforced a zero-emoji policy across the frontend and backend.
- **Guided Story Studio & Gemini Title Engine ([Stage 3.2](docs/plans/M3-3.2-guided-story-studio.md)):** Turned Gemini on behind `ENABLE_GEMINI_API = bool(GEMINI_API_KEY)` with a 6s timeout and single-call-per-session caching (`POST /api/chat/suggest-titles` + `SessionStore`), gated both caption sources in `solver.py` on `include_text`, and persisted content preferences across variation and spread reshuffles.
- **Motion System, Verification & Cleanup ([Stage 3.3](docs/plans/M3-3.3-motion-verification-cleanup.md)):** Replaced the flat progress bar with a 4-stage checkpoint-bound AI Synthesis Loader, applied the `--px-*` luxury design token set, added `test_stage_3_2_studio_contract.py`, and cleaned up root-level scratch files.

### Explicitly Parked

**Before real user data lands.** Purge the ~380 real photos committed to git (`.git` is 152 MB; `.gitignore` covers `backend/app/uploads/` but the files predate the rule). Add access control on top of M1's session isolation — `/uploads` is a `StaticFiles` mount with **no access check at all** ([main.py:68](backend/app/main.py:68)). Drop `"*"` from CORS and the `ngrok-free.dev` regex ([main.py:47](backend/app/main.py:47)). Rate limiting via `slowapi`.

**Before public launch.** Delete the three dead endpoints — `/api/curate-photos` and `/api/curate-and-generate` import a `MasterCurationPipeline` that exists nowhere and 500 on every call; `/api/upload-photos` is superseded. Gate `/api/stats`, `/api/templates`, `/api/palettes`, `/api/categories`. Retention sweep with a 24-h TTL.

**When one machine stops being enough.** S3 via the [1.3](docs/plans/M1-1.3-storage-offload.md) `StorageBackend` seam. Postgres + Alembic (no migration system exists today — schema is raw `CREATE TABLE IF NOT EXISTS`). Redis + a real task queue, which is what actually permits more than one uvicorn worker. Docker, CI/CD, Sentry, health probes, backups. Kill `reload=True` in [`run.py`](backend/run.py).

**Product depth.** 2-tier chapter-summary prompting for 1,000-photo sessions. 4–6 photo collage spreads — safe to attempt once [1.7](docs/plans/M1-1.7-load-proof.md)'s slot-invariant tests exist. Face-aware cropping: a commented-out `calculate_smart_crop_offset()` sits at [dsa_solver.py:289](backend/app/engine/dsa_solver.py:289) and the face detector already works. Streaming PDF compilation (currently buffers every page's bitmaps; 100+ page books will OOM). CMYK/ICC for commercial presses. Drag-and-drop slot swapping.

**Commerce.** User accounts, Prodigi/Gelato integration, Stripe, order tracking.

---

## Appendix A — Documentation corrections

Both existing docs misstate the code. Plans built on them inherit the errors.

| Claim | Source | Reality |
|---|---|---|
| Uploads chunk in batches of 50 | `MVP_REPORT.md` §2.3 | No chunking exists. One request carries everything. |
| Two broken endpoints | `MVP_REPORT.md` §4 | Three — `/api/upload-photos` is also dead. |
| `backend/venv/` is tracked | `MVP_REPORT.md` §4 | Not tracked. ~380 real user photos are. |
| Downsampling uses Web Workers | `ARCHITECTURE.md` Stage 1 | Main thread, `document.createElement('canvas')`. |
| WebP thumbnail output | `ARCHITECTURE.md` Stage 1 | JPEG. |
| EXIF GPS extraction | `ARCHITECTURE.md` Stage 1 | Not implemented. |
| Blur threshold is Laplacian < 40 | `ARCHITECTURE.md` Stage 2 | Tenengrad + Laplacian, adaptive per lighting. |

Relabel `ARCHITECTURE.md` as `docs/ARCHITECTURE-target.md` and mark it aspirational, or rewrite it to match. Drifted docs cost more than no docs.

---

## Appendix B — Sequencing rationale

**Why session continuity before chunking.** Chunking without it creates one orphaned session per chunk. One task, not two.

**Why the data contract early.** [1.5](docs/plans/M1-1.5-covers-variations.md) is unbuildable while `hero_score` is 0 for every photo, and it is the fix for the reported defect. Everything downstream of [1.2](docs/plans/M1-1.2-data-contract.md) improves at once.

**Why kill the fake-book fallback before load testing.** It fabricates a complete album whenever photo resolution fails. With it in place, the load test reports success while producing garbage — masking exactly the failures it exists to find.

**Why the cover fix is in M1, not M2.** It looks like a frontend bug and is mostly a backend schema gap. `cover_image_url: str` cannot express a 4-photo collage regardless of what the React does.

**Why M1 precedes M2.** M2's two highest-value items consume APIs M1 creates. Building them first means building them twice.

**Why the storage seam despite no cloud account.** ~1 day while there are four call sites; considerably more once originals are referenced across export, preview, and retention. S3 is the stated end state.
