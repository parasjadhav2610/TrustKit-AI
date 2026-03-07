"""TrustKit AI — Vision Analyzer Module.

Analyzes video frames using a Vision AI model to identify:
- room type
- visible objects
- view from windows/doors
- overall condition

Currently uses mock logic; swap in Gemini Vision when ready.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VisionObservation:
    frame_index: int
    description: str
    objects: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "description": self.description,
            "objects": self.objects,
        }


# ---------------------------------------------------------------------------
# Core analyzer class
# ---------------------------------------------------------------------------


class VisionAnalyzer:
    """
    Analyzes extracted frames using a Vision AI model.
    """

    def __init__(self, model_name: str = "mock-vision-model"):
        self.model_name = model_name

    def analyze_frame(self, frame_path: str, frame_index: int) -> VisionObservation:
        """
        Analyze a single frame and return observations.
        """

        # --- TEMPORARY MOCK LOGIC ---
        # Replace with Gemini Vision later

        description = "Indoor apartment scene with possible furniture"
        objects = ["wall", "window", "floor"]

        return VisionObservation(
            frame_index=frame_index,
            description=description,
            objects=objects,
        )

    def analyze_frames(self, frames: List[str]) -> List[VisionObservation]:
        """
        Analyze multiple frames.
        """

        results: List[VisionObservation] = []

        for i, frame_path in enumerate(frames):
            obs = self.analyze_frame(frame_path, i)
            results.append(obs)

        return results


# ---------------------------------------------------------------------------
# Backward-compatible convenience function
# ---------------------------------------------------------------------------
# Preserves the original module API so that existing imports in
# main.py and deep_scan.py continue to work without changes:
#   from modules.vision_analyzer import analyze_frame

_default_analyzer = VisionAnalyzer()


def analyze_frame(frame: bytes) -> dict:
    """Analyze a single video frame.

    This is a backward-compatible wrapper around VisionAnalyzer.
    The existing callers in main.py and deep_scan.py pass raw frame
    bytes, so this function bridges that interface to the new class.

    Args:
        frame: Raw byte-buffer of a single decoded video frame
               (e.g. JPEG or raw pixel data).

    Returns:
        A dict describing the scene observed in the frame.
    """
    obs = _default_analyzer.analyze_frame(frame_path="<in-memory>", frame_index=0)
    return {
        "room_type": "living room",
        "objects": obs.objects,
        "view": "brick wall",
        "condition": "good",
        "description": obs.description,
    }
