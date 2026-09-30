"""
Face detection at ingest.

The regression these guard: filter_engine.detect_faces used asdict() without
importing it. Every photo WITH a face raised NameError, a bare except turned it
into "0 faces", and so face detection silently reported zero for every photo --
disabling hero scoring, the junk exemption and people-aware captions.
"""

import statistics
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.engine.filter.face_detector.face_detector import FaceDetectionResult, FacePosition
from app.engine.filter.filter_engine import Phase1FilterEngine

# Local uploads are gitignored; tests on real photos skip without them.
REAL_SESSION = Path(__file__).resolve().parent.parent / "app/uploads/thumbnails/sess_sgWm5C-lTPk0oGPD6_fOxKQT6OwKfy5M"
REAL_FACE_PHOTO = REAL_SESSION / "px_01wnjab0t_mumjrtnq_thumb.jpg"   # a group of three, measured


@pytest.fixture(scope="module")
def engine():
    return Phase1FilterEngine()


def _face(face_id=0, conf=0.9):
    return FacePosition(
        face_id=face_id, confidence=conf, box_normalized=(0.4, 0.3, 0.2, 0.25),
        box_pixels=(200, 100, 100, 90), center_normalized=(0.5, 0.42), center_pixels=(256, 145),
        horizontal_position="center", vertical_position="center", grid_region_3x3="center",
        area_percentage=5.0, dominance="major", pose_orientation="facing_front",
    )


class StubDetector:
    def __init__(self, faces=None, raise_exc=None):
        self.faces = faces or []
        self.raise_exc = raise_exc

    def detect_image(self, img):
        if self.raise_exc:
            raise self.raise_exc
        return FaceDetectionResult(
            image_path=None, image_size=(512, 341), face_count=len(self.faces),
            major_face_count=sum(1 for f in self.faces if f.dominance == "major"),
            minor_face_count=0, composition="group_small", backend_used="stub",
            faces=self.faces, primary_face=self.faces[0] if self.faces else None,
        )


def blank_image():
    return np.full((341, 512, 3), 128, dtype=np.uint8)


def test_wrapper_reports_the_faces_the_detector_found(engine, monkeypatch):
    # Exactly the path that raised NameError: a result WITH faces, serialised.
    monkeypatch.setattr(engine, "face_detector", StubDetector([_face(0), _face(1, 0.7)]))
    count, major, fx, fy, quality, details = engine.detect_faces(blank_image())
    assert (count, major) == (2, 2)
    assert (fx, fy) == (0.5, 0.42)
    assert quality == 0.8
    assert details["backend_used"] == "stub" and len(details["faces"]) == 2


def test_detector_errors_are_counted_and_degrade_to_no_faces(engine, monkeypatch):
    monkeypatch.setattr(engine, "face_detector", StubDetector(raise_exc=RuntimeError("model gone")))
    monkeypatch.setattr(engine, "face_errors", {})
    assert engine.detect_faces(blank_image())[:2] == (0, 0)
    assert engine.detect_faces(blank_image())[:2] == (0, 0)
    assert engine.face_errors == {"RuntimeError": 2}


def test_image_without_faces_reports_none_and_no_error(engine):
    before = dict(engine.face_errors)
    gradient = np.tile(np.linspace(0, 255, 512, dtype=np.uint8), (341, 1))
    assert engine.detect_faces(cv2.cvtColor(gradient, cv2.COLOR_GRAY2BGR))[:2] == (0, 0)
    assert engine.face_errors == before


def test_haar_is_not_a_routine_fallback(engine, monkeypatch):
    # With an ML backend loaded, a no-face photo must not also pay for Haar
    # (20-380 ms each on real uploads, and it found nothing extra).
    det = engine.face_detector
    if det is None or (det._mp_tasks_detector is None and det._yunet_path is None):
        pytest.skip("no ML face backend available in this environment")
    called = []
    monkeypatch.setattr(det, "_detect_opencv_haar", lambda img: called.append(1) or [])
    det.detect_image(blank_image())
    assert called == []


@pytest.mark.skipif(not REAL_FACE_PHOTO.exists(), reason="local uploads not present")
def test_real_detector_finds_faces_in_a_group_photo(engine):
    count, major, *_rest, details = engine.detect_faces(cv2.imread(str(REAL_FACE_PHOTO)))
    assert count >= 1
    assert details["backend_used"] in ("mediapipe_tasks", "opencv_yunet", "mediapipe_legacy", "opencv_haar")


@pytest.mark.skipif(not REAL_SESSION.exists(), reason="local uploads not present")
def test_scan_results_are_json_serialisable():
    # Scan results travel in the ingest response. Once faces were detected at
    # all, YuNet's numpy.float32 keypoints reached FastAPI's encoder and every
    # ingest request with a face failed with a 500.
    import json

    from app.engine.filter.filter_engine import scan_photo

    with_faces = 0
    for f in sorted(REAL_SESSION.iterdir())[:30]:
        result = scan_photo(str(f), f.stem)
        json.dumps(result, allow_nan=False)   # raises on numpy types
        with_faces += bool(result.get("face_count"))
    assert with_faces > 0, "the check must include photos with faces"


@pytest.mark.skipif(not REAL_SESSION.exists(), reason="local uploads not present")
def test_detection_stays_fast(engine):
    # A gross-slowdown guard, not a benchmark: measured ~6 ms median on 512 px
    # thumbnails; the bound leaves an order of magnitude for slow CI machines.
    times = []
    for f in sorted(REAL_SESSION.iterdir())[:20]:
        img = cv2.imread(str(f))
        start = time.perf_counter()
        engine.detect_faces(img)
        times.append((time.perf_counter() - start) * 1000)
    assert statistics.median(times) < 60, f"median {statistics.median(times):.1f} ms per photo"
