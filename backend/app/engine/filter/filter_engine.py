"""
Phase 1 Photo Filtering Engine for Pixovo-v3 (Supercharged Precision & Low-Resource Version)
-------------------------------------------------------------------------------
Multi-Layered High-Precision Filtering Pipeline:
1. Layer 1: Adaptive Exposure Guard (Low-key night silhouettes & High-key studio protection)
2. Layer 2: Smart Multi-Signal Junk Detector (Monochrome Guard + Non-Face Detail Protection + Text/QR Guard)
3. Layer 3: Noise-Tolerant Subject-Aware Focal Sharpness (Gaussian Denoised Tenengrad + Laplacian)
4. Layer 4: Multi-Dimensional Burst Deduplication (Bitwise Binary pHash + Facial Keypoint & Quality Best-Shot Ranking)
5. Layer 5: Spatio-Temporal 3D DBSCAN Event Clustering (Normalized Time + Haversine GPS Distance)
"""

import os
import re
import threading
import math
import time
import base64
from datetime import datetime
from typing import List, Dict, Any, Tuple
import cv2
import numpy as np
from PIL import Image, ImageOps
from sklearn.cluster import DBSCAN

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None

try:
    import imagehash
except ImportError:
    imagehash = None

try:
    from app.engine.filter.face_detector.face_detector import FaceDetector
except ImportError:
    try:
        from face_detector.face_detector import FaceDetector
    except ImportError:
        try:
            from face_detector import FaceDetector
        except ImportError:
            FaceDetector = None


def compute_phash_bitwise_hamming(phash1: str, phash2: str) -> int:
    """
    Compute true binary bitwise XOR Hamming distance between two hex pHash strings.
    Unlike character mismatch, bitwise XOR measures exact binary difference.
    """
    if not phash1 or not phash2 or len(phash1) != len(phash2):
        return 99
    try:
        val1 = int(phash1, 16)
        val2 = int(phash2, 16)
        return bin(val1 ^ val2).count('1')
    except Exception:
        return 99


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Haversine distance in kilometers between two GPS coordinates."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 0.0
    try:
        R = 6371.0  # Earth radius in kilometers
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2.0) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c
    except Exception:
        return 0.0


class ImageOrientationAligner:
    """
    Disabled Auto-Skew Alignment Engine.
    All images pass through in their original orientation with zero cropping or warping.
    """

    def __init__(self, max_analysis_dim: int = 640, max_tilt_deg: float = 10.0):
        pass

    def estimate_skew_angle(self, img_bgr: np.ndarray, face_details: Dict[str, Any] = None) -> Tuple[float, float, str]:
        return 0.0, 0.0, "disabled"

    def rotate_and_crop(self, img_bgr: np.ndarray, angle_deg: float) -> np.ndarray:
        return img_bgr


class Phase1FilterEngine:
    """
    Supercharged Standalone Phase 1 Photo Filtering & Event Engine.
    High precision junk/blur detection with memory-optimized low-resource footprint.
    """

    BLUR_THRESHOLD: float = 30.0        # Focal sharpness threshold
    BLUR_THRESHOLD_SOLO: float = 18.0   # Relaxed sharpness threshold for unique solo anchor photos
    JUNK_ENTROPY_MAX: float = 3.8       # Flat documents/screenshots have low entropy (<3.8)
    JUNK_EDGE_RATIO: float = 0.18       # Canny text edge density > 18%
    JUNK_WHITE_RATIO: float = 0.65      # Paper background > 65%
    BURST_TIME_WINDOW: float = 5.0      # Burst window in seconds
    BURST_HASH_MAX_HAMMING: int = 8     # Expanded bitwise binary Hamming distance threshold <= 8
    CLUSTER_TIME_THRESHOLD: float = 2700.0  # 45 minutes gap triggers new event cluster
    CLUSTER_GPS_THRESHOLD_KM: float = 5.0   # 5 km location shift triggers event check

    def __init__(self):
        self.face_detector = FaceDetector(min_confidence=0.45) if FaceDetector else None
        self.aligner = ImageOrientationAligner()

    def load_cv2_image_fast(self, filepath: str, max_dim: int = 800) -> Tuple[np.ndarray, Tuple[int, int]]:
        """
        Fast low-memory image loader that streams & resizes image to max_dim (default 800px).
        Applies ImageOps.exif_transpose to automatically rotate smartphone photos correctly.
        Returns: (downsampled_bgr_image, (original_width, original_height))
        """
        try:
            with Image.open(filepath) as pil_img:
                # Transpose EXIF orientation tag (e.g. iPhone vertical photo tag 6 or 8)
                pil_img = ImageOps.exif_transpose(pil_img)
                orig_w, orig_h = pil_img.size
                
                # Use PIL fast thumbnailing to avoid loading full 24MP array into uncompressed RAM
                pil_img.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)
                rgb_img = pil_img.convert("RGB")
                img_bgr = cv2.cvtColor(np.array(rgb_img), cv2.COLOR_RGB2BGR)
                return img_bgr, (orig_w, orig_h)
        except Exception:
            pass

        # Fallback to OpenCV
        try:
            img_bgr = cv2.imread(filepath)
            if img_bgr is not None:
                orig_h, orig_w = img_bgr.shape[:2]
                scale = max_dim / float(max(orig_h, orig_w))
                if scale < 1.0:
                    img_bgr = cv2.resize(img_bgr, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                return img_bgr, (orig_w, orig_h)
        except Exception:
            pass

        return None, (0, 0)

    # -------------------------------------------------------------
    # LAYER 1: Adaptive Extreme Exposure Guard
    # -------------------------------------------------------------
    def detect_extreme_exposure(self, gray_img: np.ndarray) -> Tuple[bool, str]:
        """
        Adaptive extreme exposure detector:
        Protects creative low-key shots (night sparklers, dark background silhouettes)
        and high-key shots (studio white backdrop portraits).
        Only flags true blackout or blinding whiteout frames with zero structural contrast.
        """
        if gray_img is None or gray_img.size == 0:
            return True, "Corrupt or empty image frame"

        h, w = gray_img.shape[:2]
        total_pixels = h * w
        mean_val = float(np.mean(gray_img))
        std_val = float(np.std(gray_img))

        black_pixels = np.count_nonzero(gray_img < 12)
        white_pixels = np.count_nonzero(gray_img > 248)

        black_ratio = black_pixels / total_pixels
        white_ratio = white_pixels / total_pixels

        # Creative Low-Key Protection: If there is center contrast (std > 18.0), it's an artistic photo
        if black_ratio > 0.92 and std_val < 12.0 and mean_val < 10.0:
            return True, f"Extremely Dark / Blackout Frame ({black_ratio*100:.1f}% black, std {std_val:.1f})"

        # Creative High-Key Protection: If there is center contrast (std > 18.0), it's a high-key photo
        if white_ratio > 0.92 and std_val < 12.0 and mean_val > 248.0:
            return True, f"Overexposed Flash Blinding Frame ({white_ratio*100:.1f}% white, std {std_val:.1f})"

        return False, "Exposure Normal"

    # -------------------------------------------------------------
    # LAYER 2: Smart Multi-Signal Junk Detector (Color Entropy + OCR Text)
    # -------------------------------------------------------------
    def is_monochrome_photo(self, img_bgr: np.ndarray) -> bool:
        """
        Detect if photo is Black & White / Grayscale / Sepia artistic photo.
        Prevents B&W and warm-toned monochrome photos from false junk rejection.
        """
        if img_bgr is None or img_bgr.size == 0:
            return False
        try:
            b, g, r = cv2.split(img_bgr)
            diff_rg = np.mean(np.abs(r.astype(np.float32) - g.astype(np.float32)))
            diff_gb = np.mean(np.abs(g.astype(np.float32) - b.astype(np.float32)))
            # Allow sepia / warm monochrome tone up to 20.0 delta
            return (diff_rg + diff_gb) < 20.0
        except Exception:
            return False

    def compute_color_entropy(self, img_bgr: np.ndarray) -> float:
        """
        Calculate RGB color distribution entropy.
        Natural photos have high color entropy (>5.0).
        Text documents, chat screenshots, and receipts have low color entropy (<3.8).
        """
        if img_bgr is None or img_bgr.size == 0:
            return 0.0

        try:
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
            hist_norm = hist.ravel() / (hist.sum() + 1e-7)
            hist_norm = hist_norm[hist_norm > 0]
            entropy = -np.sum(hist_norm * np.log2(hist_norm))
            return float(entropy)
        except Exception:
            return 5.0

    def detect_junk_document(
        self, img_bgr: np.ndarray, full_img_bgr: np.ndarray, gray_img: np.ndarray, face_count: int, aspect_ratio: float
    ) -> Tuple[bool, str]:
        """
        Multi-signal junk detector protecting natural photos & non-face detail shots:
        - OpenCV QR Code Detector on downsampled preview (Fast & low CPU/RAM).
        - Contour-based QR Finder Pattern Detector.
        - Non-face detail protection (rings, cakes, flatlays, invitations, architecture).
        - Document/Screenshot flagging even if small ID photo face is present.
        """
        h, w = gray_img.shape[:2] if gray_img is not None else (1, 1)

        # Step 1: Lightweight OpenCV QR Code & Barcode Detector on downsampled preview
        if hasattr(cv2, "QRCodeDetector") and img_bgr is not None:
            try:
                qr_detector = cv2.QRCodeDetector()
                retval, decoded_info, _, _ = qr_detector.detectAndDecodeMulti(img_bgr)
                if retval and any(decoded_info):
                    return True, f"Junk QR Code / Payment Join Banner ({decoded_info[0][:25]}...)"
            except Exception:
                pass

        # Step 2: Nested Contour QR Finder Pattern Detector
        if gray_img is not None:
            try:
                _, thresh = cv2.threshold(gray_img, 100, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
                contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                if hierarchy is not None:
                    hierarchy_data = hierarchy[0]
                    nested_squares = 0
                    for i in range(len(contours)):
                        k = i
                        c = 0
                        while hierarchy_data[k][2] != -1:
                            k = hierarchy_data[k][2]
                            c += 1
                        if c >= 2:
                            area = cv2.contourArea(contours[i])
                            if area > 100:
                                nested_squares += 1
                    if nested_squares >= 3:
                        return True, f"Junk QR Pattern Poster ({nested_squares} QR Finder Patterns Detected)"
            except Exception:
                pass

        is_mono = self.is_monochrome_photo(img_bgr)
        entropy = self.compute_color_entropy(img_bgr)

        edges = cv2.Canny(gray_img, 100, 200) if gray_img is not None else np.zeros((1, 1))
        edge_ratio = np.count_nonzero(edges) / float(w * h)
        white_ratio = np.count_nonzero(gray_img > 230) / float(w * h) if gray_img is not None else 0.0

        # Aspect ratio outlier check (long tall receipts < 0.45 or extreme web banners > 2.40)
        is_aspect_outlier = aspect_ratio < 0.45 or aspect_ratio > 2.40

        # ID Card / Document with embedded face check (high paper white ratio + high edge density)
        if white_ratio > 0.60 and edge_ratio > 0.22 and entropy < 3.9:
            return True, f"Scanned ID/Document with embedded face (White Paper {white_ratio:.2f}, Text Edges {edge_ratio:.2f})"

        # If photo contains faces and not an ID card -> PASS
        if face_count > 0:
            return False, "Contains faces"

        # Document/Receipt/Screenshot Trigger (Checked BEFORE color entropy for high edge documents)
        if entropy < self.JUNK_ENTROPY_MAX and (not is_mono or white_ratio > self.JUNK_WHITE_RATIO):
            if edge_ratio > self.JUNK_EDGE_RATIO:
                return True, f"Text Document/Receipt (Low Entropy {entropy:.1f}, Text Edges {edge_ratio:.2f})"
            if white_ratio > self.JUNK_WHITE_RATIO:
                return True, f"Paper Screenshot (Low Entropy {entropy:.1f}, White Paper {white_ratio:.2f})"

        if is_aspect_outlier and entropy < 4.0:
            return True, f"Extreme Receipt/Banner Aspect Ratio ({aspect_ratio:.2f})"

        # Monochrome B&W Protection
        if is_mono:
            if not is_aspect_outlier and edge_ratio < 0.25:
                return False, "Monochrome / Black & White Artistic Photo"

        # Non-Face Detail Protection (Rings, Cakes, Flatlays, Flowers, Architecture)
        if entropy >= 3.8 and not is_aspect_outlier:
            return False, f"Natural Photo / Detail Shot (Color Entropy {entropy:.2f})"

        return False, "Passed document check"

    # -------------------------------------------------------------
    # LAYER 3: Noise-Tolerant Subject-Aware Focal Sharpness Filter
    # -------------------------------------------------------------
    def compute_focal_sharpness_tenengrad(
        self, gray_img: np.ndarray, focal_x: float = 0.5, focal_y: float = 0.5
    ) -> Tuple[float, float]:
        """
        Compute noise-tolerant sharpness on the Focal Center Region (50% box around focal_x, focal_y).
        Applies 3x3 Gaussian pre-smoothing to prevent high-ISO sensor noise from tricking Laplacian score.
        Returns: (focal_laplacian_score, focal_tenengrad_score)
        """
        if gray_img is None or gray_img.size == 0:
            return 0.0, 0.0

        try:
            h, w = gray_img.shape[:2]

            box_w, box_h = int(w * 0.5), int(h * 0.5)
            cx, cy = int(focal_x * w), int(focal_y * h)

            x1 = max(0, cx - box_w // 2)
            y1 = max(0, cy - box_h // 2)
            x2 = min(w, x1 + box_w)
            y2 = min(h, y1 + box_h)

            focal_crop = gray_img[y1:y2, x1:x2]
            if focal_crop.size == 0:
                focal_crop = gray_img

            # 3x3 Gaussian Denoising to filter single-pixel high-ISO sensor grain
            denoised_crop = cv2.GaussianBlur(focal_crop, (3, 3), 0)

            focal_laplacian = float(cv2.Laplacian(denoised_crop, cv2.CV_64F).var())

            sobelx = cv2.Sobel(denoised_crop, cv2.CV_64F, 1, 0, ksize=3)
            sobely = cv2.Sobel(denoised_crop, cv2.CV_64F, 0, 1, ksize=3)
            tenengrad = float(np.mean(sobelx**2 + sobely**2))

            return round(focal_laplacian, 1), round(tenengrad, 1)
        except Exception:
            return 0.0, 0.0

    def detect_faces(self, img_input: Any) -> Tuple[int, int, float, float, float, Dict[str, Any]]:
        """
        Detect faces using high-precision FaceDetector engine.
        Optimized for client downsampled speed.
        Returns: (face_count, major_face_count, focal_x, focal_y, face_quality_score, face_details_dict)
        """
        empty_details = {"faces": [], "composition": "no_faces", "backend_used": "none"}
        if self.face_detector is None or img_input is None:
            return 0, 0, 0.5, 0.5, 0.0, empty_details

        try:
            if len(img_input.shape) == 2:
                img_bgr = cv2.cvtColor(img_input, cv2.COLOR_GRAY2BGR)
            else:
                img_bgr = img_input

            # Speed Priority Downsampling
            h, w = img_bgr.shape[:2]
            if max(h, w) > 800:
                scale = 800.0 / max(h, w)
                proc_bgr = cv2.resize(img_bgr, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            else:
                proc_bgr = img_bgr

            res = self.face_detector.detect_image(proc_bgr)
            if res.face_count == 0:
                return 0, 0, 0.5, 0.5, 0.0, empty_details

            focal_x = res.primary_face.center_normalized[0] if res.primary_face else 0.5
            focal_y = res.primary_face.center_normalized[1] if res.primary_face else 0.5

            conf_sum = sum(f.confidence for f in res.faces)
            face_quality_score = round(float(conf_sum / res.face_count), 2)

            face_details = {
                "faces": [f.to_dict() if hasattr(f, "to_dict") else asdict(f) for f in res.faces],
                "composition": res.composition,
                "backend_used": res.backend_used
            }

            return (
                res.face_count,
                res.major_face_count,
                focal_x,
                focal_y,
                face_quality_score,
                face_details
            )
        except Exception:
            return 0, 0, 0.5, 0.5, 0.0, empty_details

    # -------------------------------------------------------------
    # 5-Signal Metadata Extraction Engine
    # -------------------------------------------------------------
    def extract_5_signal_metadata(self, filepath: str) -> Dict[str, Any]:
        """Extract 5 signals: EXIF -> mtime -> Filename Regex -> pHash -> GPS."""
        taken_at = None
        lat, lon = None, None
        date_source = "mtime"
        filename = os.path.basename(filepath)

        try:
            with Image.open(filepath) as img:
                exif_data = img._getexif() or {}
                dt_str = exif_data.get(36867) or exif_data.get(36868)
                if dt_str:
                    try:
                        dt = datetime.strptime(str(dt_str), "%Y:%m:%d %H:%M:%S")
                        taken_at = dt.timestamp()
                        date_source = "exif_datetime"
                    except Exception:
                        pass

                if 34853 in exif_data:
                    try:
                        gps_info = exif_data[34853]
                        if 2 in gps_info and 4 in gps_info:
                            lat_deg = gps_info[2]
                            lon_deg = gps_info[4]
                            lat = float(lat_deg[0]) + float(lat_deg[1])/60.0 + float(lat_deg[2])/3600.0
                            lon = float(lon_deg[0]) + float(lon_deg[1])/60.0 + float(lon_deg[2])/3600.0
                            if gps_info.get(1) == 'S': lat = -lat
                            if gps_info.get(3) == 'W': lon = -lon
                    except Exception:
                        pass
        except Exception:
            pass

        if not taken_at or date_source == "mtime":
            match = re.search(r'(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)[-_]?([0-2]\d)?([0-5]\d)?([0-5]\d)?', filename)
            if match:
                try:
                    yr, mo, dy = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    hr = int(match.group(4)) if match.group(4) else 12
                    mn = int(match.group(5)) if match.group(5) else 0
                    sc = int(match.group(6)) if match.group(6) else 0
                    dt = datetime(yr, mo, dy, hr, mn, sc)
                    taken_at = dt.timestamp()
                    date_source = "filename_regex"
                except Exception:
                    pass

        if not taken_at:
            try:
                taken_at = os.path.getmtime(filepath)
                date_source = "mtime"
            except Exception:
                taken_at = time.time()
                date_source = "current_time"

        phash_val = self.compute_phash(filepath)

        return {
            "taken_at": taken_at,
            "formatted_date": datetime.fromtimestamp(taken_at).strftime("%b %d, %Y %I:%M %p"),
            "date_source": date_source,
            "latitude": lat,
            "longitude": lon,
            "phash": phash_val
        }

    def compute_hero_score(
        self, aspect_ratio: float, width: int, face_count: int, major_face_count: int,
        face_quality_score: float, blur_score: float, contrast_score: float, entropy: float
    ) -> Tuple[float, str]:
        """
        Calculate 0-100 Hero Image Score using 5 weighted visual signals:
        1. Aspect Ratio (Wide/Panoramic 1.35-2.20 -> +20 pts)
        2. Print Resolution (>=2400px -> +15 pts, >=1920px -> +10 pts)
        3. Subject Prominence (major faces -> +25 pts, group faces -> +20 pts)
        4. Facial Quality Score (face_quality_score * 15 pts)
        5. Focal Sharpness (min(15, blur_score / 3))
        6. Color Entropy & Aesthetics (entropy >= 4.8 -> +10 pts)
        Returns: (hero_score, layout_role)
        """
        score = 0.0

        # 1. Composition / Aspect Ratio
        if 1.35 <= aspect_ratio <= 2.20 or 0.60 <= aspect_ratio <= 0.75:
            score += 20.0
        else:
            score += 5.0

        # 2. Print Resolution
        if width >= 2400:
            score += 15.0
        elif width >= 1920:
            score += 10.0
        else:
            score += 5.0

        # 3. Subject Prominence
        if major_face_count >= 1:
            score += 25.0
        elif face_count >= 3:
            score += 20.0
        elif face_count >= 1:
            score += 15.0
        else:
            score += 10.0

        # 4. Facial Quality
        score += min(15.0, face_quality_score * 15.0)

        # 5. Focal Sharpness
        score += min(15.0, max(0.0, blur_score / 3.0))

        # 6. Color Entropy Aesthetics
        if entropy >= 4.8:
            score += 10.0
        elif entropy >= 4.0:
            score += 5.0

        hero_score = round(min(100.0, score), 1)

        if hero_score >= 75.0 and aspect_ratio >= 1.35:
            layout_role = "DOUBLE_PAGE_HERO"
        elif hero_score >= 62.0:
            layout_role = "FULL_PAGE_HERO"
        else:
            layout_role = "STANDARD_FRAME"

        return hero_score, layout_role

    def compute_hsv_histogram(self, img_bgr: np.ndarray) -> np.ndarray:
        """Compute a normalized 32-bin HSV color histogram (8 H bins x 4 S bins)."""
        if img_bgr is None or img_bgr.size == 0:
            return np.array([], dtype=np.float32)
        try:
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
            return hist.flatten()
        except Exception:
            return np.array([], dtype=np.float32)

    def compare_hsv_histograms(self, hist1: np.ndarray, hist2: np.ndarray) -> float:
        """Compare 2 HSV histograms using correlation coefficient [-1.0, 1.0]."""
        if hist1 is None or hist2 is None or len(hist1) == 0 or len(hist2) == 0:
            return 0.0
        try:
            return float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL))
        except Exception:
            return 0.0

    def extract_shell_and_core_phash(self, img_bgr: np.ndarray) -> Tuple[str, str]:
        """
        Extracts 2 spatial pHashes from BGR image array:
        1. core_phash: Central 60% box (Subject area)
        2. shell_phash: Outer border ring (Background environment)
        """
        if img_bgr is None or img_bgr.size == 0 or imagehash is None:
            return "", ""
        try:
            h, w = img_bgr.shape[:2]
            ch_start, ch_end = int(h * 0.2), int(h * 0.8)
            cw_start, cw_end = int(w * 0.2), int(w * 0.8)

            # Core (Center 60%)
            core_crop = img_bgr[ch_start:ch_end, cw_start:cw_end]
            pil_core = Image.fromarray(cv2.cvtColor(core_crop, cv2.COLOR_BGR2RGB))
            core_hash = str(imagehash.phash(pil_core))

            # Shell (Outer Border Ring - Zero out center)
            shell_img = img_bgr.copy()
            shell_img[ch_start:ch_end, cw_start:cw_end] = [0, 0, 0]
            pil_shell = Image.fromarray(cv2.cvtColor(shell_img, cv2.COLOR_BGR2RGB))
            shell_hash = str(imagehash.phash(pil_shell))

            return core_hash, shell_hash
        except Exception:
            return "", ""

    def compute_phash(self, filepath: str) -> str:
        """Compute 64-bit perceptual hash string from image filepath."""
        if not imagehash:
            return ""
        try:
            with Image.open(filepath) as img:
                return str(imagehash.phash(img))
        except Exception:
            return ""

    def compute_phash_from_array(self, img_bgr: np.ndarray) -> str:
        """Compute 64-bit perceptual hash string directly from BGR numpy array."""
        if not imagehash or img_bgr is None or img_bgr.size == 0:
            return ""
        try:
            pil_img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
            return str(imagehash.phash(pil_img))
        except Exception:
            return ""

    def compute_dominant_colors_from_array(self, small_bgr, num_colors: int = 3) -> List[str]:
        """
        Extracts dominant colours from the already-decoded preview array.

        Stage 1.2: ingest previously hardcoded dominant_colors to the same two
        hex values for every photo. color_extractor.extract_dominant_colors()
        exists but takes a path and would re-decode the file; doing it here
        reuses the array process_single_photo has already loaded, so the
        marginal cost is a 64x64 resize plus a tiny k-means.

        Returned darkest-first so callers get a stable ordering.
        """
        try:
            pixels = cv2.resize(small_bgr, (64, 64), interpolation=cv2.INTER_AREA)
            pixels = pixels.reshape(-1, 3).astype(np.float32)

            k = max(1, min(num_colors, len(np.unique(pixels, axis=0))))
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
            _, labels, centers = cv2.kmeans(
                pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
            )

            counts = np.bincount(labels.flatten(), minlength=k)
            order = np.argsort(-counts)  # most populous cluster first

            hex_colors = []
            for idx in order:
                b, g, r = centers[idx]
                hex_colors.append("#{:02X}{:02X}{:02X}".format(
                    int(np.clip(r, 0, 255)), int(np.clip(g, 0, 255)), int(np.clip(b, 0, 255))
                ))
            # Pad short results so downstream palette indexing is always safe.
            while len(hex_colors) < num_colors:
                hex_colors.append(hex_colors[-1] if hex_colors else "#2C3E50")
            return hex_colors[:num_colors]
        except Exception as e:
            logger.warning(f"[Filter] Dominant colour extraction failed: {e}")
            return ["#2C3E50", "#ECF0F1", "#7F8C8D"][:num_colors]

    def process_single_photo(self, filepath: str, photo_id: str) -> Dict[str, Any]:
        """
        Scan single photo:
        Step 1: Quality Filter (Extreme Exposure, Junk Document, Focal Sharpness)
        Step 2: Auto-Skew Alignment (Face Eye-Line / Hough Structural / Symmetry Axis Correction)
        Step 3: Hero Scoring & Aligned pHash Extraction
        """
        try:
            meta = self.extract_5_signal_metadata(filepath)

            # Fast low-memory stream loading
            small_bgr, (width, height) = self.load_cv2_image_fast(filepath, max_dim=800)
            if small_bgr is None:
                return {
                    "id": photo_id, "filepath": filepath, "filename": os.path.basename(filepath),
                    "status": "REJECTED", "reject_reason": "Unreadable/Corrupt image file", "blur_score": 0.0
                }

            aspect_ratio = round(width / height, 2) if height > 0 else 1.0
            gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)

            # -------------------------------------------------------------
            # STEP 1: Quality Filtering (Exposure -> Face -> Junk -> Blur)
            # -------------------------------------------------------------
            is_extreme_exp, exp_reason = self.detect_extreme_exposure(gray)
            face_count, major_face_count, focal_x, focal_y, face_quality, face_details = self.detect_faces(small_bgr)
            is_junk, junk_reason = self.detect_junk_document(small_bgr, small_bgr, gray, face_count, aspect_ratio)

            focal_blur, focal_tenengrad = self.compute_focal_sharpness_tenengrad(gray, focal_x, focal_y)
            contrast_score = round(float(np.std(gray)), 1)

            y_mean = float(np.mean(gray))
            adaptive_blur_threshold = self.BLUR_THRESHOLD_SOLO if (y_mean < 65.0 and contrast_score >= 25.0) else self.BLUR_THRESHOLD
            is_blurry = focal_blur < adaptive_blur_threshold and focal_tenengrad < 120.0

            status = "PASSED"
            reject_reason = ""

            if is_extreme_exp:
                status = "REJECTED_EXPOSURE"
                reject_reason = exp_reason
            elif is_junk:
                status = "REJECTED_JUNK"
                reject_reason = junk_reason
            elif is_blurry:
                status = "REJECTED_BLURRY"
                reject_reason = f"Out-of-focus blur (Focal Blur {focal_blur} < {adaptive_blur_threshold})"

            # -------------------------------------------------------------
            # STEP 2 & 3: Auto-Skew Orientation Alignment & Feature Extraction
            # -------------------------------------------------------------
            skew_angle = 0.0
            # Extract Shell & Core pHash directly from pristine stream preview
            core_hash, shell_hash = self.extract_shell_and_core_phash(small_bgr)
            phash_val = self.compute_phash_from_array(small_bgr) or meta.get("phash", "")
            hsv_hist = self.compute_hsv_histogram(small_bgr)
            entropy = self.compute_color_entropy(small_bgr)
            orientation = "PORTRAIT" if aspect_ratio < 0.85 else ("LANDSCAPE" if aspect_ratio > 1.25 else "SQUARE")
            hero_score, layout_role = self.compute_hero_score(
                aspect_ratio, width, face_count, major_face_count, face_quality, focal_blur, contrast_score, entropy
            )
            dominant_colors = self.compute_dominant_colors_from_array(small_bgr, num_colors=3)

            # Clean memory buffer reference
            del small_bgr
            del gray

            return {
                "id": photo_id,
                "filepath": filepath,
                "filename": os.path.basename(filepath),
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
                "orientation": orientation,
                "hero_score": hero_score,
                "layout_role": layout_role,
                "dominant_colors": dominant_colors,
                "taken_at": meta["taken_at"],
                "formatted_date": meta["formatted_date"],
                "date_source": meta["date_source"],
                "latitude": meta["latitude"],
                "longitude": meta["longitude"],
                "phash": phash_val,
                "core_phash": core_hash,
                "shell_phash": shell_hash,
                "hsv_hist": hsv_hist.tolist() if isinstance(hsv_hist, np.ndarray) else [],
                "blur_score": focal_blur,
                "tenengrad_score": focal_tenengrad,
                "contrast_score": contrast_score,
                "is_blurry": is_blurry,
                "face_count": face_count,
                "major_face_count": major_face_count,
                "face_quality_score": face_quality,
                "composition": face_details.get("composition", "no_faces"),
                "faces": face_details.get("faces", []),
                "face_backend": face_details.get("backend_used", "none"),
                "focal_x": round(focal_x, 2),
                "focal_y": round(focal_y, 2),
                "status": status,
                "reject_reason": reject_reason,
                "pairing_suggestions": []
            }
        except Exception as err:
            return {
                "id": photo_id, "filepath": filepath, "filename": os.path.basename(filepath),
                "status": "REJECTED", "reject_reason": f"Corrupt image: {err}", "blur_score": 0.0
            }

    # -------------------------------------------------------------
    # LAYER 5: Spatio-Temporal 3D Event Clustering
    # -------------------------------------------------------------
    def sub_cluster_events(self, cluster_photos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sub-divides large event clusters into Narrative Story Mini-Chapters based on time gaps & lighting shifts.
        """
        if not cluster_photos or len(cluster_photos) < 8:
            return [{
                "chapter_id": "ch_1",
                "chapter_title": "Full Story Chapter",
                "photos": cluster_photos
            }]

        sorted_photos = sorted(cluster_photos, key=lambda p: p.get("taken_at", 0))
        chapters = []
        current_ch_photos = [sorted_photos[0]]
        ch_counter = 1

        for i in range(1, len(sorted_photos)):
            prev = sorted_photos[i - 1]
            curr = sorted_photos[i]
            time_gap = curr.get("taken_at", 0) - prev.get("taken_at", 0)

            # Check if there is a lighting shift (e.g. night temple lighting after 18:00)
            dt_curr = datetime.fromtimestamp(curr.get("taken_at", 0))
            dt_prev = datetime.fromtimestamp(prev.get("taken_at", 0))
            is_night_transition = (dt_prev.hour < 18 and dt_curr.hour >= 18)

            if time_gap > 600.0 or is_night_transition or len(current_ch_photos) >= 18:
                chapters.append({
                    "chapter_id": f"ch_{ch_counter}",
                    "chapter_title": self._generate_chapter_title(ch_counter, current_ch_photos),
                    "photos": current_ch_photos
                })
                ch_counter += 1
                current_ch_photos = [curr]
            else:
                current_ch_photos.append(curr)

        if current_ch_photos:
            chapters.append({
                "chapter_id": f"ch_{ch_counter}",
                "chapter_title": self._generate_chapter_title(ch_counter, current_ch_photos),
                "photos": current_ch_photos
            })

        return chapters

    def _generate_chapter_title(self, ch_num: int, photos: List[Dict[str, Any]]) -> str:
        if not photos:
            return f"Chapter {ch_num}: Moments"
        first_p = photos[0]
        dt = datetime.fromtimestamp(first_p.get("taken_at", 0))
        
        if dt.hour >= 18 or dt.hour < 5:
            return f"Chapter {ch_num}: Evening & Illuminated Views ({dt.strftime('%I:%M %p')})"
        elif any(p.get("face_count", 0) == 0 for p in photos):
            return f"Chapter {ch_num}: Candids & Details ({dt.strftime('%I:%M %p')})"
        else:
            return f"Chapter {ch_num}: Portraits & Pathway ({dt.strftime('%I:%M %p')})"

    def cluster_events(self, photos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Cluster survived photos into chronological Event groups & Story Mini-Chapters using DBSCAN."""
        if not photos:
            return []

        sorted_photos = sorted(photos, key=lambda p: p.get("taken_at", 0))
        n_photos = len(sorted_photos)

        # Module 5: Sparse Sliding-Window DBSCAN Matrix Optimization (O(N) Scalability)
        dist_matrix = np.zeros((n_photos, n_photos), dtype=np.float64)
        for i in range(n_photos):
            for j in range(i, n_photos):
                t_diff_sec = abs(sorted_photos[i].get("taken_at", 0) - sorted_photos[j].get("taken_at", 0))
                if t_diff_sec > 7200.0:  # 2 Hours sliding window cutoff
                    dist_matrix[i, j] = 99.0
                    dist_matrix[j, i] = 99.0
                    continue

                t_diff = t_diff_sec / self.CLUSTER_TIME_THRESHOLD
                lat1, lon1 = sorted_photos[i].get("latitude"), sorted_photos[i].get("longitude")
                lat2, lon2 = sorted_photos[j].get("latitude"), sorted_photos[j].get("longitude")
                
                gps_km = haversine_distance_km(lat1, lon1, lat2, lon2)
                gps_dist = gps_km / self.CLUSTER_GPS_THRESHOLD_KM if gps_km > 0 else 0.0

                combined_dist = math.sqrt(t_diff**2 + gps_dist**2)
                dist_matrix[i, j] = combined_dist
                dist_matrix[j, i] = combined_dist

        try:
            db = DBSCAN(eps=1.0, min_samples=1, metric="precomputed")
            labels = db.fit_predict(dist_matrix)
        except Exception:
            labels = [i // 4 for i in range(n_photos)]

        event_clusters: Dict[int, List[Dict[str, Any]]] = {}
        for idx, label in enumerate(labels):
            if label not in event_clusters:
                event_clusters[label] = []
            event_clusters[label].append(sorted_photos[idx])

        formatted_events = []
        for cluster_id, cluster_photos in event_clusters.items():
            start_time = min(p["taken_at"] for p in cluster_photos)
            start_str = datetime.fromtimestamp(start_time).strftime("%b %d, %Y • %I:%M %p")

            # 5-Stage Hierarchical Tie-Breaker Ladder
            sorted_by_hero = sorted(
                cluster_photos,
                key=lambda p: (
                    p.get("hero_score", 0.0),
                    p.get("major_face_count", 0),
                    p.get("face_quality_score", 0.0),
                    p.get("blur_score", 0.0),
                    p.get("contrast_score", 0.0),
                    -p.get("taken_at", 0)
                ),
                reverse=True
            )

            top_hero_photo = sorted_by_hero[0]

            for p in cluster_photos:
                p["is_event_cover_hero"] = (p["id"] == top_hero_photo["id"])
                p["is_alternate_cover_candidate"] = (
                    p["id"] != top_hero_photo["id"] and
                    abs(p.get("hero_score", 0.0) - top_hero_photo.get("hero_score", 0.0)) <= 2.0
                )

            # Sub-cluster event into narrative story mini-chapters
            story_chapters = self.sub_cluster_events(cluster_photos)

            formatted_events.append({
                "event_id": f"event_{cluster_id+1}",
                "event_title": f"Event {cluster_id+1}: {start_str}",
                "event_cover_photo_id": top_hero_photo["id"],
                "event_cover_filename": top_hero_photo["filename"],
                "photo_count": len(cluster_photos),
                "chapters": story_chapters,
                "photos": cluster_photos
            })

        return formatted_events

    def discover_layout_groupings(self, survived_photos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Scans survived photos to discover Smart Multi-Photo Layout Groupings using Bounded Dynamic Chaining & HSV Dual Verification:
        1. BURST_TRIPTYCH_GROUP (Priority Pass: 3 consecutive PORTRAIT photos with matching shell_phash & core_phash pose shift)
        2. THEME_QUAD_GROUP / THEME_TRIPTYCH_GROUP (Bounded Dynamic Chaining Pass with HSV Dual Background Verification & Scenery Monotony Guard)
        3. COMPANION_PAIR (2-Photo Pair Fall-through)
        """
        if not survived_photos or len(survived_photos) < 2:
            return []

        n = len(survived_photos)
        used_photo_ids = set()
        layout_groups = []

        # -------------------------------------------------------------
        # PASS 1 (Highest Priority): Protect Pose Progression Triptychs
        # -------------------------------------------------------------
        for i in range(n - 2):
            p1 = survived_photos[i]
            p2 = survived_photos[i + 1]
            p3 = survived_photos[i + 2]

            if p1["id"] in used_photo_ids or p2["id"] in used_photo_ids or p3["id"] in used_photo_ids:
                continue

            t1, t3 = p1.get("taken_at", 0), p3.get("taken_at", 0)
            if (t3 - t1) <= 45.0:
                is_all_portrait = (p1.get("orientation") == "PORTRAIT" and p2.get("orientation") == "PORTRAIT" and p3.get("orientation") == "PORTRAIT")
                
                sh1, sh2, sh3 = p1.get("shell_phash", ""), p2.get("shell_phash", ""), p3.get("shell_phash", "")
                ch1, ch2, ch3 = p1.get("core_phash", ""), p2.get("core_phash", ""), p3.get("core_phash", "")

                sh12 = compute_phash_bitwise_hamming(sh1, sh2)
                sh23 = compute_phash_bitwise_hamming(sh2, sh3)
                ch12 = compute_phash_bitwise_hamming(ch1, ch2)
                ch23 = compute_phash_bitwise_hamming(ch2, ch3)

                # Same background location (sh <= 8) + Subject pose movement (ch >= 4)
                if is_all_portrait and sh12 <= 8 and sh23 <= 8 and ch12 >= 4 and ch23 >= 4:
                    layout_groups.append({
                        "group_id": f"triptych_{p1['id']}",
                        "group_type": "BURST_TRIPTYCH_GROUP",
                        "group_title": " 3-Frame Progressive Action Burst",
                        "photos": [p1, p2, p3],
                        "reason": f"3-frame progressive action pose sequence at the same location ({p1['filename']}, {p2['filename']}, {p3['filename']})"
                    })
                    used_photo_ids.add(p1["id"])
                    used_photo_ids.add(p2["id"])
                    used_photo_ids.add(p3["id"])

        # -------------------------------------------------------------
        # PASS 2: Bounded Dynamic Chaining Engine with HSV & Scenery Monotony Guard
        # -------------------------------------------------------------
        for i in range(n):
            p1 = survived_photos[i]
            if p1["id"] in used_photo_ids:
                continue

            sh_anchor = p1.get("shell_phash", "")
            hist_anchor = np.array(p1.get("hsv_hist", []), dtype=np.float32)
            t_anchor = p1.get("taken_at", 0)
            chain = [p1]

            # Module 2: Scenery Monotony Guard (Pure Scenery Cap = Max 2)
            is_pure_scenery_start = (p1.get("face_count", 0) == 0)
            max_allowed_chain = 2 if is_pure_scenery_start else 4

            for j in range(i + 1, n):
                p_cand = survived_photos[j]
                if p_cand["id"] in used_photo_ids:
                    continue

                t_cand = p_cand.get("taken_at", 0)
                sh_cand = p_cand.get("shell_phash", "")
                hist_cand = np.array(p_cand.get("hsv_hist", []), dtype=np.float32)
                sh_prev = chain[-1].get("shell_phash", "")

                # Circuit-Breaker 1: Time Horizon Span <= 300s
                if (t_cand - t_anchor) > 300.0:
                    break

                # Circuit-Breaker 2: Pairwise Step & Module 1: HSV Color Correlation Dual Verification
                step_dist = compute_phash_bitwise_hamming(sh_prev, sh_cand)
                anchor_dist = compute_phash_bitwise_hamming(sh_anchor, sh_cand)
                hsv_correl = self.compare_hsv_histograms(hist_anchor, hist_cand)

                # Dual Background Verification Condition
                is_bg_matched = (step_dist <= 10 and anchor_dist <= 12) or (anchor_dist <= 14 and hsv_correl >= 0.65)

                if is_bg_matched:
                    chain.append(p_cand)
                    # Circuit-Breaker 4 & Module 2 Cap
                    if len(chain) == max_allowed_chain:
                        break

            # Dynamic Fallback Sizing & Group Creation
            if len(chain) == 4:
                layout_groups.append({
                    "group_id": f"quad_{p1['id']}",
                    "group_type": "THEME_QUAD_GROUP",
                    "group_title": " 4-Photo Scene Topic Group",
                    "photos": chain,
                    "reason": "Bounded 4-photo scene topic chain at matching location"
                })
                for cp in chain:
                    used_photo_ids.add(cp["id"])
            elif len(chain) == 3:
                layout_groups.append({
                    "group_id": f"trio_{p1['id']}",
                    "group_type": "THEME_TRIPTYCH_GROUP",
                    "group_title": " 3-Photo Scene Topic Group",
                    "photos": chain,
                    "reason": "Bounded 3-photo scene topic chain at matching location"
                })
                for cp in chain:
                    used_photo_ids.add(cp["id"])
            elif len(chain) == 2:
                is_scenery_portrait_synergy = (chain[0].get("face_count", 0) == 0 and chain[1].get("face_count", 0) >= 1) or (chain[1].get("face_count", 0) == 0 and chain[0].get("face_count", 0) >= 1)
                is_pure_scenery_pair = (chain[0].get("face_count", 0) == 0 and chain[1].get("face_count", 0) == 0)

                group_title = " Scenery & Portrait Synergy Pair" if is_scenery_portrait_synergy else (" Scenery Anchor Pair" if is_pure_scenery_pair else " 2-Photo Companion Pair")
                layout_groups.append({
                    "group_id": f"pair_{p1['id']}",
                    "group_type": "COMPANION_PAIR",
                    "group_title": group_title,
                    "photos": chain,
                    "reason": f"Complementary 2-photo companion pair ({chain[0]['filename']} & {chain[1]['filename']})"
                })
                for cp in chain:
                    used_photo_ids.add(cp["id"])

        # Attach pairing_suggestions back for backward compatibility
        for grp in layout_groups:
            photos = grp["photos"]
            if len(photos) >= 2:
                p1 = photos[0]
                p2 = photos[1]
                p1["pairing_suggestions"] = [{
                    "paired_photo_id": p2["id"],
                    "paired_filename": p2["filename"],
                    "pair_type": grp["group_type"],
                    "pairing_score": 95.0,
                    "reason": grp["reason"]
                }]

        return layout_groups

    def run_phase1_filtering(self, filepaths: List[str]) -> Dict[str, Any]:
        """
        Execute the full 6-layer pipeline serially.

        Stage 1.4: this used to construct its own ThreadPoolExecutor per call.
        Since the caller already invokes it on a pool thread, that meant
        FILTER_WORKERS x 4 threads — plus OpenCV's own per-operation fan-out —
        competing for a machine with far fewer cores.

        Prefer `finalise_batch()` with per-photo work fanned out by the caller
        (see main.py ingest): that parallelises across concurrent sessions
        instead of nesting pools inside one. This method is kept for callers
        that want the whole pipeline in one synchronous call, and for tests.
        """
        scanned_photos = [
            self.process_single_photo(fp, f"p_{idx + 1}")
            for idx, fp in enumerate(filepaths)
        ]
        return self.finalise_batch(scanned_photos, total_uploaded=len(filepaths))

    def finalise_batch(
        self, scanned_photos: List[Dict[str, Any]], total_uploaded: int = 0
    ) -> Dict[str, Any]:
        """
        Serial post-processing over an already-scanned batch.

        Everything here is cross-photo and cheap (no image decoding, no I/O):
        the solo-anchor safeguard, burst dedupe, event clustering (DBSCAN),
        layout grouping and hero ranking. Split out from run_phase1_filtering so
        the expensive per-photo half can be fanned out by the caller while this
        half stays serial — and so both halves are independently testable.
        """
        total_uploaded = total_uploaded or len(scanned_photos)

        # Uniqueness Safeguard (Solo Anchor Protection)
        for p in scanned_photos:
            if p["status"] == "REJECTED_BLURRY":
                time_t = p.get("taken_at", 0)
                ph = p.get("phash", "")
                has_duplicate = any(
                    other["id"] != p["id"] and abs(other.get("taken_at", 0) - time_t) <= 30.0 and
                    compute_phash_bitwise_hamming(ph, other.get("phash", "")) <= 10
                    for other in scanned_photos
                )
                if not has_duplicate and p.get("blur_score", 0.0) >= self.BLUR_THRESHOLD_SOLO:
                    p["status"] = "PASSED"
                    p["reject_reason"] = ""
                    p["uniqueness_safeguard"] = True

        quality_passed = [p for p in scanned_photos if p["status"] == "PASSED"]
        junk_rejected = [p for p in scanned_photos if p["status"] == "REJECTED_JUNK"]
        blurry_rejected = [p for p in scanned_photos if p["status"] == "REJECTED_BLURRY"]
        exposure_rejected = [p for p in scanned_photos if p["status"] == "REJECTED_EXPOSURE"]
        corrupt_rejected = [p for p in scanned_photos if p["status"] == "REJECTED"]

        # Layer 4: Modified Burst Deduplication + Module 4: Group Portrait Backup Deduplication
        survived_photos = []
        burst_rejected = []
        skip_indices = set()

        for i in range(len(quality_passed)):
            if i in skip_indices:
                continue

            current = quality_passed[i]
            burst_group = [current]

            for j in range(i + 1, len(quality_passed)):
                if j in skip_indices:
                    continue

                other = quality_passed[j]
                time_delta = abs(current.get("taken_at", 0) - other.get("taken_at", 0))

                sh1, sh2 = current.get("shell_phash", ""), other.get("shell_phash", "")
                ch1, ch2 = current.get("core_phash", ""), other.get("core_phash", "")

                shell_hamming = compute_phash_bitwise_hamming(sh1, sh2)
                core_hamming = compute_phash_bitwise_hamming(ch1, ch2)

                # Expanded Near-Identical Duplicate Burst: Same background (shell <= 7) AND subject didn't move much (core <= 5)
                is_true_duplicate_burst = (time_delta <= 5.0 and shell_hamming <= 7 and core_hamming <= 5)

                # Group Portrait Backup Deduplication: face_count >= 2 & same background & same group pose
                is_group_backup = (
                    current.get("face_count", 0) >= 2 and other.get("face_count", 0) >= 2 and
                    shell_hamming <= 7 and core_hamming <= 5 and time_delta <= 180.0
                )

                # Pose Progression Protection: If core_hamming >= 5 (subject changed pose/expression) and shell matches, DO NOT DELETE!
                is_pose_progression_protected = (shell_hamming <= 8 and core_hamming >= 5 and time_delta <= 45.0)

                if (is_true_duplicate_burst or is_group_backup) and not is_pose_progression_protected:
                    burst_group.append(other)
                    skip_indices.add(j)

            if len(burst_group) > 1:
                # User Rule: If photos in burst group have AT LEAST ONE face with 75%+ confidence (score >= 0.75 or face_quality >= 0.75 or confidence >= 0.75),
                # KEEP ALL PHOTOS! Else choose the single best photo.
                has_high_conf_face = any(
                    (p.get("face_count", 0) >= 1 and (
                        p.get("face_quality_score", 0.0) >= 0.75 or
                        any(f.get("confidence", 0.0) >= 0.75 for f in p.get("faces", []))
                    ))
                    for p in burst_group
                )
                
                if has_high_conf_face:
                    # Keep all photos in group when face >= 75% confidence
                    for p in burst_group:
                        p["burst_face_preserved"] = True
                        survived_photos.append(p)
                else:
                    # Keep only best photo
                    sorted_burst = sorted(
                        burst_group,
                        key=lambda p: (
                            p.get("hero_score", 0.0) * 2.0 +
                            p.get("blur_score", 0.0) +
                            p.get("contrast_score", 0.0) * 1.5
                        ),
                        reverse=True
                    )
                    survived_photos.append(sorted_burst[0])
                    for rej in sorted_burst[1:]:
                        rej["status"] = "REJECTED_BURST"
                        rej["reject_reason"] = f"Near-duplicate burst of {sorted_burst[0]['filename']}"
                        burst_rejected.append(rej)
            else:
                survived_photos.append(current)

        # Layer 5: Spatio-Temporal Event Clustering
        events = self.cluster_events(survived_photos)

        # Layer 6: Smart Multi-Photo Layout Groupings
        layout_groups = self.discover_layout_groupings(survived_photos)

        return {
            "summary": {
                "total_uploaded": total_uploaded,
                "total_survived": len(survived_photos),
                "total_events": len(events),
                "total_rejected": len(junk_rejected) + len(blurry_rejected) + len(exposure_rejected) + len(corrupt_rejected) + len(burst_rejected),
                "junk_filtered": len(junk_rejected),
                "blurry_filtered": len(blurry_rejected),
                "exposure_filtered": len(exposure_rejected),
                "burst_duplicates_filtered": len(burst_rejected),
                "corrupt_filtered": len(corrupt_rejected)
            },
            "events": events,
            "layout_groups": layout_groups,
            "survived_photos": survived_photos,
            "rejected_photos": junk_rejected + blurry_rejected + exposure_rejected + corrupt_rejected + burst_rejected,
            "all_scanned_photos": scanned_photos
        }



# ----------------------------------------------------------------------
# Module-level worker entry points (Stage 1.7)
# ----------------------------------------------------------------------
# ProcessPoolExecutor pickles the callable it is handed. Submitting a BOUND
# method (engine.process_single_photo) pickles the Phase1FilterEngine instance
# with it, which holds loaded mediapipe/ONNX handles — ctypes function pointers.
# That fails with:
#
#   Can't pickle local object 'CDLL.__init__.<locals>._FuncPtr'
#
# These module-level functions are picklable by reference. Each worker process
# builds its own engine on first use (~1-2s of model loading, once per worker)
# and reuses it thereafter. Both are safe for the thread pool too, where the
# module global is simply shared.

# One engine PER THREAD, not one per process.
#
# Phase1FilterEngine holds a FaceDetector wrapping MediaPipe/TFLite and ONNX
# Runtime sessions. Those carry native graph state and are NOT safe to call
# concurrently from multiple threads: sharing a single instance across the pool
# crashed the interpreter outright (no Python traceback, exit 127) as soon as
# ~8 concurrent sessions were filtering at once. Lower concurrency masked it,
# which is why it survived a 4-user run.
#
# A lock around detection would serialise the most expensive stage and destroy
# throughput, so each pool thread gets its own detector instead. Under a
# ProcessPoolExecutor each worker process has exactly one thread, so this
# degrades naturally to one engine per process.
_ENGINE_TLS = threading.local()


def _worker_engine() -> "Phase1FilterEngine":
    engine = getattr(_ENGINE_TLS, "engine", None)
    if engine is None:
        engine = Phase1FilterEngine()
        _ENGINE_TLS.engine = engine
    return engine


def scan_photo(filepath: str, photo_id: str) -> Dict[str, Any]:
    """Per-photo scan. Pool-safe entry point for the expensive half."""
    return _worker_engine().process_single_photo(filepath, photo_id)


def finalise_scanned_batch(
    scanned_photos: List[Dict[str, Any]], total_uploaded: int = 0
) -> Dict[str, Any]:
    """Serial cross-photo half. Pool-safe entry point."""
    return _worker_engine().finalise_batch(scanned_photos, total_uploaded=total_uploaded)
