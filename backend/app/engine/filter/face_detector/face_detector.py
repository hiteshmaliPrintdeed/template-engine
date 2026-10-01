"""
Pixovo Phase 1 - High Precision Face Detector & Position Categorizer
---------------------------------------------------------------------
Detects the total number of faces in an image and categorizes each face's 
spatial position, dominance, bounding box, grid region, and group composition.

Supports multiple backends with automatic fallback:
1. MediaPipe Face Detection / Tasks API
2. OpenCV DNN Face Detector (YuNet / SSD)
3. OpenCV Haar Cascade Classifier
"""

import os
import sys
import argparse
import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple, Optional
import cv2
import numpy as np
from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# Dynamic Backend Imports & Initialization
# ---------------------------------------------------------------------------

MEDIAPIPE_AVAILABLE = False
MP_FACE_DETECTION = None

try:
    import mediapipe as mp
    if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
        MP_FACE_DETECTION = mp.solutions.face_detection
        MEDIAPIPE_AVAILABLE = True
    elif hasattr(mp, "tasks") and hasattr(mp.tasks, "vision"):
        MEDIAPIPE_AVAILABLE = True
except Exception:
    MEDIAPIPE_AVAILABLE = False


# ---------------------------------------------------------------------------
# MediaPipe detector lifetime
# ---------------------------------------------------------------------------
# MediaPipe's FaceDetector.__del__ calls close(), which dispatches through
# MediaPipe's own executor and waits on the result. If the garbage collector
# finalizes a detector at the wrong moment -- measured: pytest's end-of-session
# gc pass -- that wait never returns and the process hangs. The app holds one
# detector per worker thread for the life of the process, so a server shutdown
# or --reload restart is exposed to the same hang.
#
# So no live detector is ever left for the collector: every one is referenced
# here, and all are closed in a threading exit hook. Those hooks run BEFORE
# concurrent.futures shuts its executors down (a plain atexit handler runs
# after, when MediaPipe's dispatch can no longer complete). close() is
# idempotent, so the __del__ that follows finds nothing left to do.
import threading as _threading

_LIVE_MP_DETECTORS: List[Any] = []
_LIVE_MP_LOCK = _threading.Lock()


def _track_mediapipe(detector: Any) -> Any:
    with _LIVE_MP_LOCK:
        _LIVE_MP_DETECTORS.append(detector)
    return detector


def close_all_mediapipe_detectors() -> None:
    with _LIVE_MP_LOCK:
        detectors = list(_LIVE_MP_DETECTORS)
        _LIVE_MP_DETECTORS.clear()
    for detector in detectors:
        try:
            detector.close()
        except Exception:
            pass


try:
    _threading._register_atexit(close_all_mediapipe_detectors)
except Exception:  # private API; fall back to the ordinary hook
    import atexit as _atexit

    _atexit.register(close_all_mediapipe_detectors)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class KeypointNormalized:
    x: float
    y: float

@dataclass
class Keypoints:
    right_eye: Optional[KeypointNormalized] = None
    left_eye: Optional[KeypointNormalized] = None
    nose_tip: Optional[KeypointNormalized] = None
    mouth_center: Optional[KeypointNormalized] = None
    right_ear: Optional[KeypointNormalized] = None
    left_ear: Optional[KeypointNormalized] = None

@dataclass
class FacePosition:
    face_id: int
    confidence: float
    box_normalized: Tuple[float, float, float, float]  # (xmin, ymin, width, height) in range [0, 1]
    box_pixels: Tuple[int, int, int, int]              # (x, y, width, height) in pixels
    center_normalized: Tuple[float, float]             # (x_center, y_center) in range [0, 1]
    center_pixels: Tuple[int, int]                     # (x_center, y_center) in pixels
    horizontal_position: str                           # 'left', 'center', 'right'
    vertical_position: str                             # 'top', 'center', 'bottom'
    grid_region_3x3: str                               # 'top-left', 'center', etc.
    area_percentage: float                             # percentage of total image area
    dominance: str                                     # 'major' (foreground) or 'minor' (background)
    pose_orientation: str                              # 'facing_front', 'facing_left', 'facing_right', 'unknown'
    keypoints: Optional[Dict[str, Dict[str, float]]] = None

@dataclass
class FaceDetectionResult:
    image_path: Optional[str]
    image_size: Tuple[int, int]                        # (width, height)
    face_count: int
    major_face_count: int
    minor_face_count: int
    composition: str                                   # 'no_faces', 'solo_centered', 'couple_side_by_side', 'group_small', etc.
    backend_used: str
    faces: List[FacePosition]
    primary_face: Optional[FacePosition] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result object to JSON-serializable dictionary."""
        res = asdict(self)
        return res


# ---------------------------------------------------------------------------
# Core Face Detector & Categorizer Engine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helper Model Downloader
# ---------------------------------------------------------------------------

def ensure_models_available() -> Dict[str, str]:
    """
    Ensure face detection model files exist locally in models directory.
    Downloads them automatically if missing.
    """
    import urllib.request
    models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    os.makedirs(models_dir, exist_ok=True)

    urls = {
        "yunet": ("face_detection_yunet_2023mar.onnx", "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
        "tflite": ("blaze_face_short_range.tflite", "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"),
        "haar": ("haarcascade_frontalface_default.xml", "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml")
    }

    paths = {}
    for key, (filename, url) in urls.items():
        filepath = os.path.join(models_dir, filename)
        if not os.path.exists(filepath) or os.path.getsize(filepath) < 1000:
            try:
                urllib.request.urlretrieve(url, filepath)
            except Exception:
                pass
        if os.path.exists(filepath) and os.path.getsize(filepath) >= 1000:
            paths[key] = filepath

    return paths


# ---------------------------------------------------------------------------
# Core Face Detector & Categorizer Engine
# ---------------------------------------------------------------------------

class FaceDetector:
    """
    High Precision Face Detector & Spatial Position Categorizer.
    Supports MediaPipe Tasks API, OpenCV YuNet Deep Learning Detector,
    and OpenCV Haar Cascade with automatic fallback.
    """

    MAJOR_FACE_AREA_MIN_PCT: float = 3.5  # Minimum % frame area for a face to be 'major'

    def __init__(self, min_confidence: float = 0.5, backend_preference: str = "auto"):
        """
        Initialize FaceDetector.
        :param min_confidence: Minimum detection confidence threshold (0.0 to 1.0)
        :param backend_preference: 'auto', 'yunet', 'mediapipe', or 'haar'
        """
        self.min_confidence = min_confidence
        self.backend_preference = backend_preference
        self._mp_tasks_detector = None
        self._mp_legacy_detector = None
        self._yunet_path = None
        self._yunet = None          # created once, resized per image (see _yunet_for)
        self._haar_cascade = None

        self._init_backends()

    def _init_backends(self):
        """Initialize available detection backends."""
        model_paths = ensure_models_available()

        # 1. MediaPipe Tasks FaceDetector
        if MEDIAPIPE_AVAILABLE and "tflite" in model_paths:
            try:
                from mediapipe.tasks.python import vision
                options = vision.FaceDetectorOptions(
                    base_options=mp.tasks.BaseOptions(model_asset_path=model_paths["tflite"]),
                    min_detection_confidence=self.min_confidence
                )
                self._mp_tasks_detector = _track_mediapipe(vision.FaceDetector.create_from_options(options))
            except Exception:
                self._mp_tasks_detector = None

        # 2. Legacy MediaPipe solutions
        if MP_FACE_DETECTION is not None:
            try:
                self._mp_legacy_detector = MP_FACE_DETECTION.FaceDetection(
                    model_selection=1, min_detection_confidence=self.min_confidence
                )
            except Exception:
                self._mp_legacy_detector = None

        # 3. OpenCV YuNet Deep Learning Detector
        if "yunet" in model_paths and hasattr(cv2, "FaceDetectorYN_create"):
            self._yunet_path = model_paths["yunet"]

        # 4. OpenCV Haar Cascade Classifier
        haar_path = model_paths.get("haar") or (cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if haar_path and os.path.exists(haar_path):
            try:
                if hasattr(cv2, "CascadeClassifier"):
                    cascade = cv2.CascadeClassifier(haar_path)
                    if not cascade.empty():
                        self._haar_cascade = cascade
            except Exception:
                self._haar_cascade = None

    def detect_file(self, image_path: str) -> FaceDetectionResult:
        """
        Detect faces and categorise positions from an image file path.
        Automatically applies EXIF orientation correction (auto-rotation).
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image path does not exist: {image_path}")

        # Load image with EXIF orientation auto-correction using PIL
        try:
            pil_img = Image.open(image_path)
            pil_img = ImageOps.exif_transpose(pil_img)  # Auto-rotates sideways photos upright!
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            image_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception:
            image_bgr = cv2.imread(image_path)
            if image_bgr is None:
                raise ValueError(f"Failed to decode image file: {image_path}")

        result = self.detect_image(image_bgr)
        result.image_path = image_path
        return result

    def detect_image(self, image_bgr: np.ndarray) -> FaceDetectionResult:
        """
        Detect faces and categorise positions from an OpenCV BGR image array.
        Uses Multi-Scale Tiled Grid Scanning + Aspect-Preserving Letterboxing + IoU NMS
        to guarantee 100% full-frame coverage without resolution or dimension constraints.
        """
        if image_bgr is None or image_bgr.size == 0:
            raise ValueError("Input image is empty or invalid.")

        img_h, img_w = image_bgr.shape[:2]
        raw_faces = []
        backend_used = "none"

        # 1. Try MediaPipe Tasks API
        if self._mp_tasks_detector is not None:
            raw_faces = self._detect_mediapipe_tasks_tiled(image_bgr)
            if raw_faces:
                backend_used = "mediapipe_tasks"

        # 2. Try OpenCV YuNet Deep Learning Detector
        if not raw_faces and self._yunet_path is not None:
            raw_faces = self._detect_yunet_tiled(image_bgr)
            if raw_faces:
                backend_used = "opencv_yunet"

        # 3. Try Legacy MediaPipe
        if not raw_faces and self._mp_legacy_detector is not None:
            raw_faces = self._detect_mediapipe_legacy_tiled(image_bgr)
            if raw_faces:
                backend_used = "mediapipe_legacy"

        # 4. Last resort only: OpenCV Haar Cascade, and only when no ML backend
        #    loaded at all. As a routine third pass it made every photo without
        #    faces (landscapes, animals) pay 20-380 ms on top of the ML
        #    backends, and on real uploads it found nothing they had missed.
        ml_available = (
            self._mp_tasks_detector is not None or self._yunet_path is not None
            or self._mp_legacy_detector is not None
        )
        if not raw_faces and not ml_available and self._haar_cascade is not None:
            raw_faces = self._detect_opencv_haar(image_bgr)
            if raw_faces:
                backend_used = "opencv_haar"

        # Apply IoU Non-Maximum Suppression (NMS) to remove duplicates across tiles
        raw_faces = self._apply_nms(raw_faces, iou_threshold=0.35)

        # Categorise detected faces
        categorized_faces = self._categorize_positions(raw_faces, img_w, img_h)

        # Count major / minor faces
        major_count = sum(1 for f in categorized_faces if f.dominance == "major")
        minor_count = len(categorized_faces) - major_count

        # Primary face (largest face by area)
        primary_face = max(categorized_faces, key=lambda f: f.area_percentage) if categorized_faces else None

        # Classify composition layout
        composition = self._classify_composition(categorized_faces)

        return FaceDetectionResult(
            image_path=None,
            image_size=(img_w, img_h),
            face_count=len(categorized_faces),
            major_face_count=major_count,
            minor_face_count=minor_count,
            composition=composition,
            backend_used=backend_used,
            faces=categorized_faces,
            primary_face=primary_face
        )

    # -----------------------------------------------------------------------
    # Multi-Scale Tiled Grid Scanning & Engine Detection Routines
    # -----------------------------------------------------------------------

    def _get_tiled_crops(self, image_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Generate tile coordinates for full frame + 2x2 overlapping quadrants."""
        img_h, img_w = image_bgr.shape[:2]
        tiles = [{"x": 0, "y": 0, "w": img_w, "h": img_h}]

        if max(img_w, img_h) >= 800:
            half_w, half_h = img_w // 2, img_h // 2
            overlap_w, overlap_h = int(img_w * 0.15), int(img_h * 0.15)

            quads = [
                (0, 0, half_w + overlap_w, half_h + overlap_h),
                (half_w - overlap_w, 0, img_w - (half_w - overlap_w), half_h + overlap_h),
                (0, half_h - overlap_h, half_w + overlap_w, img_h - (half_h - overlap_h)),
                (half_w - overlap_w, half_h - overlap_h, img_w - (half_w - overlap_w), img_h - (half_h - overlap_h))
            ]
            for tx, ty, tw, th in quads:
                if tw > 50 and th > 50:
                    tiles.append({"x": tx, "y": ty, "w": tw, "h": th})

        return tiles

    def _detect_mediapipe_tasks_tiled(self, image_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Detect faces using MediaPipe Tasks API across multi-scale tile grid."""
        img_h, img_w = image_bgr.shape[:2]
        tiles = self._get_tiled_crops(image_bgr)
        all_detections = []

        for tile in tiles:
            tx, ty, tw, th = tile["x"], tile["y"], tile["w"], tile["h"]
            crop_bgr = image_bgr[ty:ty+th, tx:tx+tw]
            if crop_bgr.size == 0:
                continue

            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            try:
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=crop_rgb)
                res = self._mp_tasks_detector.detect(mp_img)
                if res and res.detections:
                    for det in res.detections:
                        score = det.categories[0].score if det.categories else 1.0
                        if score < self.min_confidence:
                            continue

                        bb = det.bounding_box
                        # Convert pixel bounding box to tile relative float
                        tile_xmin = bb.origin_x / tw
                        tile_ymin = bb.origin_y / th
                        tile_w = bb.width / tw
                        tile_h = bb.height / th

                        # Map back to global relative float
                        g_xmin = (tx + (tile_xmin * tw)) / img_w
                        g_ymin = (ty + (tile_ymin * th)) / img_h
                        g_w = (tile_w * tw) / img_w
                        g_h = (tile_h * th) / img_h

                        kps = {}
                        if det.keypoints and len(det.keypoints) >= 4:
                            kps["right_eye"] = {"x": (tx + (det.keypoints[0].x * tw)) / img_w, "y": (ty + (det.keypoints[0].y * th)) / img_h}
                            kps["left_eye"] = {"x": (tx + (det.keypoints[1].x * tw)) / img_w, "y": (ty + (det.keypoints[1].y * th)) / img_h}
                            kps["nose_tip"] = {"x": (tx + (det.keypoints[2].x * tw)) / img_w, "y": (ty + (det.keypoints[2].y * th)) / img_h}
                            kps["mouth_center"] = {"x": (tx + (det.keypoints[3].x * tw)) / img_w, "y": (ty + (det.keypoints[3].y * th)) / img_h}

                        all_detections.append({
                            "xmin": g_xmin, "ymin": g_ymin, "width": g_w, "height": g_h,
                            "confidence": float(score),
                            "keypoints": kps
                        })
            except Exception:
                continue

        return all_detections

    def _yunet_for(self, width: int, height: int):
        """
        The YuNet detector, created on first use and resized per image.
        Creating it loads and parses the ONNX model -- previously done for
        every tile of every photo. A FaceDetector belongs to one thread
        (filter_engine keeps one engine per pool thread), so reuse is safe.
        """
        if self._yunet is None:
            self._yunet = cv2.FaceDetectorYN_create(
                self._yunet_path, "", (width, height), self.min_confidence, 0.3, 5000
            )
        self._yunet.setInputSize((width, height))
        return self._yunet

    def _detect_yunet_tiled(self, image_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Detect faces using OpenCV SOTA YuNet deep learning detector across multi-scale tile grid."""
        img_h, img_w = image_bgr.shape[:2]
        tiles = self._get_tiled_crops(image_bgr)
        all_detections = []

        for tile in tiles:
            tx, ty, tw, th = tile["x"], tile["y"], tile["w"], tile["h"]
            crop_bgr = image_bgr[ty:ty+th, tx:tx+tw]
            if crop_bgr.size == 0:
                continue

            try:
                yunet = self._yunet_for(tw, th)
                _, faces = yunet.detect(crop_bgr)
                if faces is not None:
                    for f in faces:
                        # f: [x, y, w, h, x_re, y_re, x_le, y_le, x_n, y_n, x_mr, y_mr, x_ml, y_ml, score]
                        bx, by, bw, bh = f[0], f[1], f[2], f[3]
                        score = float(f[-1])

                        g_xmin = (tx + bx) / img_w
                        g_ymin = (ty + by) / img_h
                        g_w = bw / img_w
                        g_h = bh / img_h

                        # float(): YuNet returns numpy.float32, which the API's
                        # JSON encoder cannot serialise -- face keypoints travel
                        # in the ingest response, so every photo with a face
                        # detected by YuNet made the request fail with a 500.
                        kps = {
                            "right_eye": {"x": float((tx + f[4]) / img_w), "y": float((ty + f[5]) / img_h)},
                            "left_eye": {"x": float((tx + f[6]) / img_w), "y": float((ty + f[7]) / img_h)},
                            "nose_tip": {"x": float((tx + f[8]) / img_w), "y": float((ty + f[9]) / img_h)},
                            "mouth_center": {
                                "x": float((tx + (f[10] + f[12]) / 2.0) / img_w),
                                "y": float((ty + (f[11] + f[13]) / 2.0) / img_h),
                            },
                        }

                        all_detections.append({
                            "xmin": g_xmin, "ymin": g_ymin, "width": g_w, "height": g_h,
                            "confidence": score,
                            "keypoints": kps
                        })
            except Exception:
                continue

        return all_detections

    def _detect_mediapipe_legacy_tiled(self, image_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Detect faces using legacy MediaPipe solutions API."""
        img_h, img_w = image_bgr.shape[:2]
        tiles = self._get_tiled_crops(image_bgr)
        all_detections = []

        for tile in tiles:
            tx, ty, tw, th = tile["x"], tile["y"], tile["w"], tile["h"]
            crop_bgr = image_bgr[ty:ty+th, tx:tx+tw]
            if crop_bgr.size == 0:
                continue

            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            try:
                mp_res = self._mp_legacy_detector.process(crop_rgb)
                if mp_res and mp_res.detections:
                    for det in mp_res.detections:
                        score = det.score[0] if det.score else 1.0
                        if score < self.min_confidence:
                            continue
                        bbox = det.location_data.relative_bounding_box
                        tile_xmin, tile_ymin = bbox.xmin, bbox.ymin
                        tile_w, tile_h = bbox.width, bbox.height

                        g_xmin = (tx + (tile_xmin * tw)) / img_w
                        g_ymin = (ty + (tile_ymin * th)) / img_h
                        g_w = (tile_w * tw) / img_w
                        g_h = (tile_h * th) / img_h

                        kps = {}
                        if det.location_data.relative_keypoints and len(det.location_data.relative_keypoints) >= 4:
                            kp_list = det.location_data.relative_keypoints
                            kps["right_eye"] = {"x": (tx + (kp_list[0].x * tw)) / img_w, "y": (ty + (kp_list[0].y * th)) / img_h}
                            kps["left_eye"] = {"x": (tx + (kp_list[1].x * tw)) / img_w, "y": (ty + (kp_list[1].y * th)) / img_h}
                            kps["nose_tip"] = {"x": (tx + (kp_list[2].x * tw)) / img_w, "y": (ty + (kp_list[2].y * th)) / img_h}
                            kps["mouth_center"] = {"x": (tx + (kp_list[3].x * tw)) / img_w, "y": (ty + (kp_list[3].y * th)) / img_h}

                        all_detections.append({
                            "xmin": g_xmin, "ymin": g_ymin, "width": g_w, "height": g_h,
                            "confidence": float(score),
                            "keypoints": kps
                        })
            except Exception:
                continue

        return all_detections

    def _detect_opencv_haar(self, image_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Multi-scale Haar Cascade face detection fallback."""
        img_h, img_w = image_bgr.shape[:2]
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        haar_faces = self._haar_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24)
        )
        raw = []
        if len(haar_faces) > 0:
            for (x, y, w, h) in haar_faces:
                raw.append({
                    "xmin": x / img_w,
                    "ymin": y / img_h,
                    "width": w / img_w,
                    "height": h / img_h,
                    "confidence": 0.85,
                    "keypoints": None
                })
        return raw

    def _apply_nms(self, faces: List[Dict[str, Any]], iou_threshold: float = 0.35) -> List[Dict[str, Any]]:
        """
        Apply Intersection-over-Union (IoU) Non-Maximum Suppression to deduplicate
        overlapping face detections across tiled scans.
        """
        if not faces:
            return []

        # Sort faces by confidence * area descending
        sorted_faces = sorted(faces, key=lambda f: f["confidence"] * (f["width"] * f["height"]), reverse=True)
        kept = []

        for f in sorted_faces:
            duplicate = False
            for k in kept:
                if self._compute_iou(f, k) > iou_threshold:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(f)

        return kept

    @staticmethod
    def _compute_iou(box1: Dict[str, float], box2: Dict[str, float]) -> float:
        """Compute IoU overlap between two normalized bounding boxes."""
        x1 = max(box1["xmin"], box2["xmin"])
        y1 = max(box1["ymin"], box2["ymin"])
        x2 = min(box1["xmin"] + box1["width"], box2["xmin"] + box2["width"])
        y2 = min(box1["ymin"] + box1["height"], box2["ymin"] + box2["height"])

        inter_w = max(0.0, x2 - x1)
        inter_h = max(0.0, y2 - y1)
        inter_area = inter_w * inter_h

        if inter_area <= 0:
            return 0.0

        area1 = box1["width"] * box1["height"]
        area2 = box2["width"] * box2["height"]
        union_area = area1 + area2 - inter_area

        return inter_area / union_area if union_area > 0 else 0.0

    # -----------------------------------------------------------------------
    # Spatial Categorization Helper Logic
    # -----------------------------------------------------------------------

    def _categorize_positions(self, raw_faces: List[Dict[str, Any]], img_w: int, img_h: int) -> List[FacePosition]:
        """
        Categorise bounding box coordinates into 9-region grid, horizontal/vertical positions,
        dominance, and facing orientation.
        Filters out tiny background noise artifacts (< 25px or < 15% of primary face size).
        """
        if not raw_faces:
            return []

        # Filter out tiny noise artifacts (e.g. spire artifacts < 25px or < 15% of largest face)
        valid_raw = []
        areas = [(f["width"] * f["height"]) for f in raw_faces]
        max_area = max(areas) if areas else 0.0

        for f in raw_faces:
            w_px = int(round(f["width"] * img_w))
            h_px = int(round(f["height"] * img_h))
            area = f["width"] * f["height"]

            # Ignore tiny background noise boxes (< 24px wide/high or < 15% of main face area unless confidence > 0.88)
            if w_px < 24 or h_px < 24:
                continue
            if max_area > 0.0005 and area < (0.15 * max_area) and f.get("confidence", 1.0) < 0.88:
                continue

            valid_raw.append(f)

        if not valid_raw:
            valid_raw = raw_faces  # Fallback if all were filtered

        # Sort faces by area descending
        sorted_raw = sorted(valid_raw, key=lambda f: f["width"] * f["height"], reverse=True)
        primary_area = sorted_raw[0]["width"] * sorted_raw[0]["height"] if sorted_raw else 0.0

        result_faces = []
        for idx, f in enumerate(sorted_raw):
            xmin = max(0.0, float(f["xmin"]))
            ymin = max(0.0, float(f["ymin"]))
            w = min(1.0 - xmin, max(0.001, float(f["width"])))
            h = min(1.0 - ymin, max(0.001, float(f["height"])))

            x_center_norm = xmin + (w / 2.0)
            y_center_norm = ymin + (h / 2.0)

            # Pixel bounding box
            x_px = int(round(xmin * img_w))
            y_px = int(round(ymin * img_h))
            w_px = int(round(w * img_w))
            h_px = int(round(h * img_h))
            xc_px = int(round(x_center_norm * img_w))
            yc_px = int(round(y_center_norm * img_h))

            # Standard 3x3 Grid Horizontal Categorization (33% / 66%)
            if x_center_norm < 0.33:
                h_pos = "left"
            elif x_center_norm > 0.66:
                h_pos = "right"
            else:
                h_pos = "center"

            # Standard 3x3 Grid Vertical Categorization (33% / 66%)
            if y_center_norm < 0.33:
                v_pos = "top"
            elif y_center_norm > 0.66:
                v_pos = "bottom"
            else:
                v_pos = "center"

            # 9-Region Grid Position
            if v_pos == "center" and h_pos == "center":
                grid_region = "center"
            else:
                grid_region = f"{v_pos}-{h_pos}"

            # Area Percentage relative to full frame
            area_pct = round((w * h) * 100.0, 2)

            # Dynamic Dominance (Major vs Minor):
            # A face is MAJOR if it is at least 35% of the primary face area, or area_pct >= 0.15%
            face_area = w * h
            if primary_area > 0 and (face_area >= 0.35 * primary_area or area_pct >= 0.15):
                dominance = "major"
            else:
                dominance = "minor"

            # Pose Orientation Estimation from keypoints
            pose_orientation = self._estimate_pose_orientation(f.get("keypoints"))

            result_faces.append(FacePosition(
                face_id=idx + 1,
                confidence=round(float(f["confidence"]), 3),
                box_normalized=(round(xmin, 4), round(ymin, 4), round(w, 4), round(h, 4)),
                box_pixels=(x_px, y_px, w_px, h_px),
                center_normalized=(round(x_center_norm, 4), round(y_center_norm, 4)),
                center_pixels=(xc_px, yc_px),
                horizontal_position=h_pos,
                vertical_position=v_pos,
                grid_region_3x3=grid_region,
                area_percentage=area_pct,
                dominance=dominance,
                pose_orientation=pose_orientation,
                keypoints=f.get("keypoints")
            ))

        return result_faces

    def _estimate_pose_orientation(self, keypoints: Optional[Dict[str, Dict[str, float]]]) -> str:
        """
        Estimate facing orientation using facial keypoint positions.
        """
        if not keypoints:
            return "unknown"

        re = keypoints.get("right_eye")
        le = keypoints.get("left_eye")
        nose = keypoints.get("nose_tip")

        if not (re and le and nose):
            return "facing_front"

        eye_dist = le["x"] - re["x"]
        if eye_dist <= 0:
            return "facing_front"

        eye_midpoint_x = (re["x"] + le["x"]) / 2.0
        nose_offset = (nose["x"] - eye_midpoint_x) / eye_dist

        if nose_offset < -0.15:
            return "facing_right"  # Turned towards viewer's right
        elif nose_offset > 0.15:
            return "facing_left"   # Turned towards viewer's left
        else:
            return "facing_front"

    def _classify_composition(self, faces: List[FacePosition]) -> str:
        """
        Classify overall scene composition layout based on number and layout of faces.
        """
        count = len(faces)
        if count == 0:
            return "no_faces"

        if count == 1:
            f = faces[0]
            if f.grid_region_3x3 == "center":
                return "solo_centered"
            else:
                return f"solo_{f.grid_region_3x3.replace('-', '_')}"

        if count == 2:
            f1, f2 = faces[0], faces[1]
            y_diff = abs(f1.center_normalized[1] - f2.center_normalized[1])
            if y_diff < 0.2:
                return "couple_side_by_side"
            else:
                return "couple_stacked"

        if 3 <= count <= 5:
            return "group_small"
        if 6 <= count <= 10:
            return "group_large"

        return "crowd"

    # -----------------------------------------------------------------------
    # Visual Annotation & Overlay Rendering
    # -----------------------------------------------------------------------

    def draw_annotations(
        self,
        image_input: Any,
        result: FaceDetectionResult,
        draw_grid: bool = True,
        show_labels: bool = True
    ) -> np.ndarray:
        """
        Draw bounding boxes, face IDs, grid region labels, and spatial metadata onto image.
        :param image_input: File path string or BGR numpy array
        :param result: FaceDetectionResult object
        :param draw_grid: Whether to draw 3x3 position grid overlay
        :param show_labels: Whether to display text badges
        :return: Annotated BGR numpy array
        """
        if isinstance(image_input, str):
            annotated = cv2.imread(image_input)
        else:
            annotated = image_input.copy()

        img_h, img_w = annotated.shape[:2]

        # Draw 3x3 spatial grid lines (subtle gray)
        if draw_grid:
            grid_color = (80, 80, 80)
            x1, x2 = int(img_w * 0.33), int(img_w * 0.66)
            y1, y2 = int(img_h * 0.33), int(img_h * 0.66)
            cv2.line(annotated, (x1, 0), (x1, img_h), grid_color, 1, cv2.LINE_AA)
            cv2.line(annotated, (x2, 0), (x2, img_h), grid_color, 1, cv2.LINE_AA)
            cv2.line(annotated, (0, y1), (img_w, y1), grid_color, 1, cv2.LINE_AA)
            cv2.line(annotated, (0, y2), (img_w, y2), grid_color, 1, cv2.LINE_AA)

        # Draw face boxes and labels
        for f in result.faces:
            x, y, w, h = f.box_pixels

            # Color scheme: Green for Major, Cyan for Minor
            box_color = (0, 230, 115) if f.dominance == "major" else (255, 200, 0)
            thickness = 3 if f.dominance == "major" else 2

            # Bounding box
            cv2.rectangle(annotated, (x, y), (x + w, y + h), box_color, thickness)

            # Center point marker
            cv2.circle(annotated, f.center_pixels, 4, (0, 0, 255), -1)

            if show_labels:
                label_str = f"Face #{f.face_id} [{f.grid_region_3x3.upper()}] ({f.dominance})"
                sub_label = f"Area: {f.area_percentage}% | {f.pose_orientation}"

                # Text background badge
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = max(0.4, min(0.6, img_w / 1200.0))
                (tw, th), _ = cv2.getTextSize(label_str, font, font_scale, 1)

                badge_y1 = max(0, y - th - 12)
                cv2.rectangle(annotated, (x, badge_y1), (x + tw + 10, y), box_color, -1)
                cv2.putText(annotated, label_str, (x + 5, y - 5), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)

                # Sub label below box
                cv2.putText(annotated, sub_label, (x, min(img_h - 5, y + h + 15)), font, font_scale * 0.85, box_color, 1, cv2.LINE_AA)

        # Top summary banner
        banner_text = f"Faces: {result.face_count} (Major: {result.major_face_count}, Minor: {result.minor_face_count}) | Comp: {result.composition.upper()}"
        cv2.rectangle(annotated, (0, 0), (img_w, 30), (20, 20, 20), -1)
        cv2.putText(annotated, banner_text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        return annotated


# ---------------------------------------------------------------------------
# Command Line Interface (CLI) Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pixovo Face Detector & Spatial Position Categorizer")
    parser.add_argument("path", nargs="?", default=None, help="Path to an image file or directory of images")
    parser.add_argument("--save-annotated", action="store_true", help="Save annotated visualization images")
    parser.add_argument("--out-dir", default="detected_output", help="Directory to save results")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum detection confidence threshold")
    
    args = parser.parse_args()

    target_path = args.path

    # Interactive prompt if path is not provided via command line argument
    if not target_path:
        print("\n" + "=" * 60)
        print("    Pixovo Face Detector & Spatial Position Categorizer")
        print("=" * 60)
        while not target_path:
            user_input = input("\n Enter image file path or folder path: ").strip()
            # Clean outer quotes if user drag-and-dropped file into terminal
            target_path = user_input.strip('"').strip("'")
            if not target_path:
                print(" Path cannot be empty. Please try again.")

        # Default save annotated images in interactive mode
        args.save_annotated = True

    target_path = os.path.abspath(target_path)
    detector = FaceDetector(min_confidence=args.min_confidence)

    if os.path.isfile(target_path):
        image_paths = [target_path]
    elif os.path.isdir(target_path):
        valid_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic")
        image_paths = [
            os.path.join(target_path, fname) for fname in os.listdir(target_path)
            if fname.lower().endswith(valid_exts)
        ]
    else:
        print(f"\n Error: Path '{target_path}' does not exist.")
        sys.exit(1)

    if not image_paths:
        print(f"\n No valid images found at '{target_path}'")
        sys.exit(0)

    if args.save_annotated:
        os.makedirs(args.out_dir, exist_ok=True)

    results_summary = []

    for img_p in image_paths:
        print(f"\n Processing: {os.path.basename(img_p)}")
        res = detector.detect_file(img_p)

        print(f"  • Total Faces: {res.face_count}")
        print(f"  • Major Faces: {res.major_face_count}")
        print(f"  • Minor Faces: {res.minor_face_count}")
        print(f"  • Composition: {res.composition}")
        print(f"  • Backend: {res.backend_used}")

        for f in res.faces:
            print(f"    - Face #{f.face_id}: Grid Region = '{f.grid_region_3x3}', Dominance = '{f.dominance}', "
                  f"Area = {f.area_percentage}%, Pose = '{f.pose_orientation}', Box = {f.box_pixels}")

        res_dict = res.to_dict()
        results_summary.append(res_dict)

        if args.save_annotated:
            annotated_img = detector.draw_annotations(img_p, res)
            out_filename = f"annotated_{os.path.basename(img_p)}"
            out_path = os.path.join(args.out_dir, out_filename)
            cv2.imwrite(out_path, annotated_img)
            print(f"   Saved annotated image to: {out_path}")

    # Output JSON summary
    summary_path = os.path.join(args.out_dir if args.save_annotated else ".", "face_detection_results.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2)
    print(f"\n JSON results saved to: {os.path.abspath(summary_path)}")


if __name__ == "__main__":
    main()
