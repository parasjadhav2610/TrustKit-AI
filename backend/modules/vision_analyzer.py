"""TrustKit AI — Vision Analyzer Module.

Analyzes video frames using Vertex AI (Gemini) to identify:
- room type
- visible objects
- view from windows/doors
- overall condition
- suspicious elements

Uses google-cloud-aiplatform with Vertex AI Gemini models.
Authentication is handled via GOOGLE_APPLICATION_CREDENTIALS env var.
Falls back to mock data if Vertex AI is not configured.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Vertex AI initialisation (lazy)
# ---------------------------------------------------------------------------

_model = None
_initialised = False


def _get_model():
    """Lazily initialise Vertex AI and return the GenerativeModel.

    Reads GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION from env.
    Authentication is handled automatically via the
    GOOGLE_APPLICATION_CREDENTIALS environment variable.

    Returns:
        A ``vertexai.generative_models.GenerativeModel`` instance,
        or ``None`` if the required env vars are missing.
    """
    global _model, _initialised

    if _initialised:
        return _model

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not project:
        print("[vision_analyzer] GOOGLE_CLOUD_PROJECT not set — using mock fallback")
        _initialised = True
        return None

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(project=project, location=location)
        _model = GenerativeModel("gemini-2.5-flash")
        _initialised = True
        print(f"[vision_analyzer] Vertex AI initialised (project={project}, location={location})")
        return _model
    except Exception as exc:
        print(f"[vision_analyzer] Vertex AI init failed: {exc}")
        _initialised = True
        return None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_VISION_PROMPT = """\
You are a Fraud Detection Vision Agent for TrustKit, a rental property \
trust verification platform. Your job is to analyze images from property \
tours and detect any inconsistencies, signs of fraud, or suspicious elements.

Analyze this image from a rental property tour and return a JSON object \
with EXACTLY this schema:

{
  "room_type": "string — type of room (e.g. living room, bedroom, kitchen, bathroom, hallway, exterior)",
  "objects": ["string — notable objects visible (furniture, appliances, fixtures, etc.)"],
  "view": "string — what is visible through windows/doors (e.g. park, street, brick wall, trees, none visible)",
  "condition": "string — overall condition: excellent, good, fair, poor, or bad",
  "suspicious_elements": ["string — anything that looks edited, inconsistent, staged, or potentially fraudulent"]
}

Be thorough when checking for suspicious elements. Look for:
- Signs of photo/video editing (warped edges, inconsistent lighting, cloning artifacts)
- Staging indicators (price tags, showroom-like setups)
- Inconsistencies between the room and claimed property type
- Unusual or out-of-place items
- Signs the image may be old or from a different property

If nothing is suspicious, return an empty array for suspicious_elements.
Return ONLY the JSON object, no extra text.
"""


# ---------------------------------------------------------------------------
# Core analyzer class
# ---------------------------------------------------------------------------


class VisionAnalyzer:
    """
    Analyzes extracted frames using Vertex AI Gemini Vision.

    Falls back to mock observations if Vertex AI is not configured
    or the API call fails.
    """

    def __init__(self) -> None:
        pass



    def analyze_frame_bytes(self, frame_bytes: bytes, frame_index: int = 0) -> dict:
        """
        Analyze a single frame from raw bytes using Vertex AI Gemini.

        This is the primary method used by the live pipeline and deep scan.

        Args:
            frame_bytes: Raw JPEG-encoded frame bytes.
            frame_index: Optional index of this frame.

        Returns:
            A dict with keys: room_type, objects, view, condition,
            suspicious_elements, description.
        """
        model = _get_model()

        if model is not None and frame_bytes:
            try:
                from vertexai.generative_models import Part

                image_part = Part.from_data(data=frame_bytes, mime_type="image/jpeg")
                response = model.generate_content(
                    [_VISION_PROMPT, image_part],
                    generation_config={"response_mime_type": "application/json"},
                )
                parsed = _parse_response(response.text)
                if parsed:
                    return {
                        "room_type": parsed.get("room_type", "unknown"),
                        "objects": parsed.get("objects", []),
                        "view": parsed.get("view", "unknown"),
                        "condition": parsed.get("condition", "unknown"),
                        "suspicious_elements": parsed.get("suspicious_elements", []),
                        "description": f"{parsed.get('room_type', 'room')} — {parsed.get('condition', 'unknown')} condition",
                    }
            except Exception as exc:
                print(f"[vision_analyzer] Gemini call failed: {exc}")

        # Fallback mock
        return {
            "room_type": "living room",
            "objects": ["wall", "window", "floor"],
            "view": "unknown",
            "condition": "good",
            "suspicious_elements": [],
            "description": "Indoor apartment scene with possible furniture",
        }




# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def _parse_response(text: str) -> Optional[dict]:
    """Parse the Gemini response text into a dict.

    Strips markdown code fences if present and parses JSON.

    Returns:
        Parsed dict or None if parsing fails.
    """
    try:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Backward-compatible convenience function
# ---------------------------------------------------------------------------
# Preserves the original module API so that existing imports in
# main.py and deep_scan.py continue to work without changes:
#   from modules.vision_analyzer import analyze_frame

_default_analyzer = VisionAnalyzer()


def analyze_frame(frame: bytes) -> dict:
    """Analyze a single video frame using Vertex AI Gemini Vision.

    Backward-compatible wrapper — calls Gemini when Vertex AI is
    configured, otherwise returns mock data.

    Args:
        frame: Raw byte-buffer of a single decoded video frame
               (e.g. JPEG-encoded bytes).

    Returns:
        A dict describing the scene observed in the frame:
            - room_type (str)
            - objects (list[str])
            - view (str)
            - condition (str)
            - suspicious_elements (list[str])
            - description (str)
    """
    return _default_analyzer.analyze_frame_bytes(frame)
