"""
Stage 2.2 & 2.3 Automated Contract Tests:
- ProgressBus pub/sub, late-subscriber replay, bounded queue drop, and cleanup
- Thread-safe cross-thread publishing via loop.call_soon_threadsafe
- Solver per-spread on_progress callback across all 3 variations
- GET /api/jobs/{job_id}/stream SSE endpoint (monotonic progress, themes_ready skeleton covers, 404 on unknown job)
"""

import asyncio
import json
import threading
import uuid
import pytest
from app.progress import ProgressBus, progress_bus
from app.schemas.photobook import PhotoMeta
from app.engine.solver import generate_photobook_variations_engine
from app.db.session_store import SessionStore


def _make_photo(idx: int, ts: float) -> PhotoMeta:
    return PhotoMeta(
        id=f"p_sse_{idx}",
        filename=f"photo_{idx}.jpg",
        url=f"/uploads/thumbnails/photo_{idx}.jpg",
        preview_url=f"/uploads/thumbnails/photo_{idx}.jpg",
        thumbnail_url=f"/uploads/thumbnails/photo_{idx}.jpg",
        width=1600,
        height=1200,
        aspect_ratio=1.3333,
        timestamp_epoch=ts,
        hero_score=float(50 + (idx % 45)),
        score=round((50 + (idx % 45)) / 100.0, 4),
        layout_role="FULL_PAGE_HERO" if idx % 4 == 0 else "STANDARD_FRAME",
        is_event_cover_hero=(idx % 5 == 0),
        is_hero_candidate=(idx % 5 == 0),
        shell_phash=f"{idx:016x}",
        core_phash=f"{(idx * 3):016x}",
        dominant_colors=["#2C3E50", "#ECF0F1", "#7F8C8D"],
    )


def test_progress_bus_two_subscribers_and_late_replay_and_cleanup():
    bus = ProgressBus()
    job_id = "job_unit_1"

    async def run():
        sub1_events = []
        sub2_events = []

        async def consume(target_list):
            async for ev in bus.subscribe(job_id):
                target_list.append(ev)

        t1 = asyncio.create_task(consume(sub1_events))
        t2 = asyncio.create_task(consume(sub2_events))
        await asyncio.sleep(0.01)

        bus.publish(job_id, {"progress": 25, "status": "processing"})

        # Late subscriber connecting mid-job gets the last event replayed immediately
        late_events = []
        t_late = asyncio.create_task(consume(late_events))
        await asyncio.sleep(0.01)
        assert len(late_events) == 1
        assert late_events[0]["progress"] == 25

        # Terminal event closes all 3 subscribers and cleans up internal state
        bus.publish(job_id, {"progress": 100, "status": "completed"})
        await asyncio.gather(t1, t2, t_late)

        assert [e["progress"] for e in sub1_events] == [25, 100]
        assert [e["progress"] for e in sub2_events] == [25, 100]
        assert [e["progress"] for e in late_events] == [25, 100]
        assert job_id not in bus._subs
        assert job_id not in bus._last

    asyncio.run(run())


def test_progress_bus_full_queue_drops_without_raising():
    bus = ProgressBus()
    job_id = "job_overflow"

    async def run():
        agen = bus.subscribe(job_id)
        # Prime generator so queue is registered
        first_task = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0.01)

        # Publish 50 events without draining (maxsize is 32)
        for i in range(1, 51):
            bus.publish(job_id, {"progress": i, "status": "processing"})
        bus.publish(job_id, {"progress": 100, "status": "completed"})

        first_ev = await first_task
        assert first_ev["progress"] == 1
        await agen.aclose()
        assert job_id not in bus._subs

    asyncio.run(run())


def test_progress_bus_publish_threadsafe_from_worker_thread():
    bus = ProgressBus()
    job_id = "job_thread"

    async def run():
        loop = asyncio.get_running_loop()
        received = []

        async def reader():
            async for ev in bus.subscribe(job_id):
                received.append(ev)

        task = asyncio.create_task(reader())
        await asyncio.sleep(0.01)

        def worker():
            bus.publish_threadsafe(loop, job_id, {"progress": 55, "status": "processing"})
            bus.publish_threadsafe(loop, job_id, {"progress": 100, "status": "completed"})

        th = threading.Thread(target=worker)
        th.start()
        th.join()

        await task
        assert [e["progress"] for e in received] == [55, 100]
        assert job_id not in bus._subs

    asyncio.run(run())


def test_solver_on_progress_callback_emits_events_across_variations():
    base_ts = 1_700_000_000.0
    photos = [_make_photo(i, base_ts + i * 60) for i in range(12)]
    ai_batch = {
        "primary_theme": "Warm",
        "variations": [
            {"variation_title": "V1", "theme_name": "Warm", "cover_title": "T1", "cover_subtitle": "S1", "captions": ["C1"]},
            {"variation_title": "V2", "theme_name": "Elegant", "cover_title": "T2", "cover_subtitle": "S2", "captions": ["C2"]},
            {"variation_title": "V3", "theme_name": "Minimal", "cover_title": "T3", "cover_subtitle": "S3", "captions": ["C3"]},
        ],
    }

    calls = []
    variations = generate_photobook_variations_engine(
        photos=photos,
        ai_batch_result=ai_batch,
        on_progress=lambda idx, total, var_idx: calls.append((idx, total, var_idx)),
    )

    assert len(variations) == 3
    assert len(calls) == sum(len(v.spreads) for v in variations)
    assert {var_idx for _, _, var_idx in calls} == {0, 1, 2}


def test_sse_stream_endpoint_emits_themes_ready_and_monotonic_progress_to_100(client):
    session_id = f"sess_sse_{uuid.uuid4().hex[:8]}"
    SessionStore.create_session(session_id, expected_photo_count=12)
    base_ts = 1_700_000_000.0
    photos = [_make_photo(i, base_ts + i * 60) for i in range(12)]
    SessionStore.save_photos_batch(photos, session_id=session_id)

    gen_res = client.post(
        "/api/generate-async",
        json={
            "photo_ids": [p.id for p in photos],
            "user_prompt": "Coastal family holiday",
            "session_id": session_id,
            "custom_title": "Summer Tides",
            "include_text": True,
        },
    )
    assert gen_res.status_code == 202
    job_id = gen_res.json()["job_id"]

    with client.stream("GET", f"/api/jobs/{job_id}/stream") as stream_res:
        assert stream_res.status_code == 200
        assert "text/event-stream" in stream_res.headers.get("content-type", "")

        events = []
        for line in stream_res.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    assert len(events) >= 1
    progresses = [e["progress"] for e in events]
    assert progresses == sorted(progresses), f"Progress was not monotonic: {progresses}"
    assert events[-1]["progress"] == 100
    assert events[-1]["status"] == "completed"
    assert events[-1].get("themes") is not None
    assert len(events[-1]["themes"]) == 3
    assert all(t["cover_title"] == "SUMMER TIDES" for t in events[-1]["themes"])
    assert job_id not in progress_bus._subs


def test_sse_stream_404_for_unknown_job(client):
    res = client.get("/api/jobs/job_does_not_exist_999/stream")
    assert res.status_code == 404
