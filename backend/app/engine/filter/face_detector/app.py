"""
Pixovo Face Detector - Web Backend Server
------------------------------------------
Provides a Web REST API and serves the frontend user interface for face detection.
"""

import os
import io
import sys
import json
import base64
import traceback
import urllib.parse
import email.parser
from http.server import HTTPServer, BaseHTTPRequestHandler
import cv2
import numpy as np
from PIL import Image, ImageOps

from face_detector import FaceDetector

# Global face detector instance
detector = FaceDetector(min_confidence=0.5)

PORT = int(os.environ.get("PORT", 8000))
HOST = "0.0.0.0"


def sanitize_for_json(obj):
    """
    Recursively convert NumPy data types (float32, float64, int32, int64, ndarray)
    and custom objects into native Python data types for 100% safe JSON serialization.
    """
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, np.ndarray):
        return [sanitize_for_json(x) for x in obj.tolist()]
    elif isinstance(obj, (np.generic, np.number)):
        return obj.item()
    elif hasattr(obj, "item") and callable(getattr(obj, "item")):
        try:
            return obj.item()
        except Exception:
            return str(obj)
    elif hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        return sanitize_for_json(obj.to_dict())
    return obj


def extract_file_from_multipart(body_bytes: bytes, content_type: str) -> bytes:
    """
    Extract uploaded file binary data from multipart/form-data payload 
    using standard library email parser (compatible with all Python versions).
    """
    try:
        header = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        parser = email.parser.BytesFeedParser()
        parser.feed(header + body_bytes)
        parsed_msg = parser.close()

        if parsed_msg.is_multipart():
            for part in parsed_msg.walk():
                disposition = part.get("Content-Disposition", "")
                filename = part.get_filename()
                if filename or "filename=" in disposition or "name=" in disposition:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload
        else:
            payload = parsed_msg.get_payload(decode=True)
            if payload:
                return payload
    except Exception as err:
        print(f"️ Multipart parsing warning: {err}")

    return body_bytes


class FaceDetectorHTTPHandler(BaseHTTPRequestHandler):

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200, "text/plain")

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path).path

        if parsed_path in ("/", "/index.html"):
            html_path = os.path.join(os.path.dirname(__file__), "index.html")
            if os.path.exists(html_path):
                with open(html_path, "rb") as f:
                    content = f.read()
                self._set_headers(200, "text/html; charset=utf-8")
                self.wfile.write(content)
            else:
                self._set_headers(404, "text/plain")
                self.wfile.write(b"index.html not found")
        else:
            self._set_headers(404, "text/plain")
            self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path).path

        if parsed_path == "/api/detect":
            try:
                content_type = self.headers.get("Content-Type", "")
                content_length = int(self.headers.get("Content-Length", 0))

                # Read request body
                body_bytes = b""
                if content_length > 0:
                    remaining = content_length
                    chunks = []
                    while remaining > 0:
                        chunk = self.rfile.read(min(remaining, 65536))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    body_bytes = b"".join(chunks)

                image_bytes = None

                if "application/json" in content_type:
                    data = json.loads(body_bytes.decode("utf-8", errors="ignore"))
                    b64_str = data.get("image", "")
                    if "," in b64_str:
                        b64_str = b64_str.split(",", 1)[1]
                    image_bytes = base64.b64decode(b64_str.strip())
                elif "multipart/form-data" in content_type:
                    image_bytes = extract_file_from_multipart(body_bytes, content_type)
                else:
                    image_bytes = body_bytes

                if not image_bytes:
                    self._set_headers(400, "application/json")
                    self.wfile.write(json.dumps({"success": False, "error": "No image data provided"}).encode("utf-8"))
                    return

                # Decode image with PIL EXIF transpose & OpenCV fallback
                try:
                    pil_img = Image.open(io.BytesIO(image_bytes))
                    try:
                        pil_img = ImageOps.exif_transpose(pil_img)
                    except Exception:
                        pass
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    image_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                except Exception as img_err:
                    nparr = np.frombuffer(image_bytes, np.uint8)
                    image_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if image_bgr is None:
                        raise ValueError(f"Failed to decode image file format: {img_err}")

                # Run Face Detector
                result = detector.detect_image(image_bgr)

                # Draw Annotations
                annotated_bgr = detector.draw_annotations(image_bgr, result)

                # Encode annotated image to Base64 PNG
                success, encoded_img = cv2.imencode(".png", annotated_bgr)
                if not success:
                    raise ValueError("Failed to encode annotated image.")

                b64_annotated = base64.b64encode(encoded_img.tobytes()).decode("utf-8")
                annotated_data_url = f"data:image/png;base64,{b64_annotated}"

                # Response payload
                response_payload = result.to_dict()
                response_payload["annotated_image"] = annotated_data_url
                response_payload["success"] = True

                # Sanitize numpy types to standard Python primitives
                clean_payload = sanitize_for_json(response_payload)

                self._set_headers(200, "application/json")
                self.wfile.write(json.dumps(clean_payload).encode("utf-8"))

            except Exception as e:
                print("\n Error processing image request:")
                traceback.print_exc()
                self._set_headers(500, "application/json")
                error_response = {"success": False, "error": str(e)}
                clean_error = sanitize_for_json(error_response)
                self.wfile.write(json.dumps(clean_error).encode("utf-8"))
        else:
            self._set_headers(404, "application/json")
            self.wfile.write(json.dumps({"success": False, "error": "Endpoint Not Found"}).encode("utf-8"))


def run_server():
    server_address = (HOST, PORT)
    httpd = HTTPServer(server_address, FaceDetectorHTTPHandler)
    print(f"\n==================================================")
    print(f"  Pixovo Face Detector Web Server Running!")
    print(f"  Open URL in browser: http://localhost:{PORT}")
    print(f"==================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
