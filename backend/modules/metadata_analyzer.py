"""TrustKit AI — Live Frame Forensics Analyzer.

Performs real-time cybersecurity forensics on live webcam frames
received over the WebSocket pipeline. Instead of inspecting static
file metadata (EXIF), this module applies computer-vision heuristics
to detect manipulation indicators in the live stream.

Checks performed:
- **Blur detection** — Laplacian variance. Scammers often use blurred
  virtual cameras or screen-sharing artifacts to hide fake backgrounds.
- **Brightness analysis** — Mean grayscale intensity. Artificially
  darkened streams can be used to obscure details.

Libraries:
- OpenCV (cv2)
- NumPy
"""

from __future__ import annotations

from typing import Any, Dict, List

import cv2  # type: ignore[import-untyped]
import numpy as np  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_BLUR_THRESHOLD = 50.0       # Laplacian variance below this → suspect
_DARKNESS_THRESHOLD = 40.0   # Mean brightness below this → suspect


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


def analyze_live_frame(frame_bytes: bytes) -> dict:
    """Analyze a single live video frame for forensic red flags.

    Args:
        frame_bytes: Raw binary payload from the WebSocket
                     (JPEG-encoded image bytes).

    Returns:
        A dict containing:
            - blur_score (float): Laplacian variance (higher = sharper).
            - brightness (float): Mean grayscale intensity (0–255).
            - suspicious_flags (list[str]): Human-readable flag strings.
            - valid (bool): Whether the frame could be decoded.
    """
    suspicious_flags: List[str] = []

    # --- Decode bytes → OpenCV image ---
    try:
        np_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    except Exception:
        img = None

    if img is None:
        return {
            "blur_score": 0.0,
            "brightness": 0.0,
            "suspicious_flags": ["frame_decode_failed"],
            "valid": False,
        }

    # --- Convert to grayscale ---
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # --- Blur detection (Laplacian variance) ---
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(laplacian.var())

    if blur_score < _BLUR_THRESHOLD:
        suspicious_flags.append("suspiciously_blurry_or_low_quality_stream")

    # --- Brightness detection ---
    brightness = float(np.mean(gray))

    if brightness < _DARKNESS_THRESHOLD:
        suspicious_flags.append("artificially_darkened_environment")

    # Manual rounding to 2 decimal places (avoids Pyre2 round() overload bug)
    rounded_blur: float = int(blur_score * 100) / 100.0
    rounded_brightness: float = int(brightness * 100) / 100.0

    return {
        "blur_score": rounded_blur,
        "brightness": rounded_brightness,
        "suspicious_flags": suspicious_flags,
        "valid": True,
    }


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------
# main.py can import either name:
#   from modules.metadata_analyzer import analyze_live_frame
#   from modules.metadata_analyzer import analyze_metadata

def analyze_metadata(frame_bytes: bytes) -> dict:
    """Backward-compatible alias for analyze_live_frame.

    Accepts raw frame bytes (not a file path) and returns the
    forensic analysis dict.
    """
    return analyze_live_frame(frame_bytes)
