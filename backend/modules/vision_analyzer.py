"""TrustKit AI — Vision Analyzer Module.

Analyzes a single video frame using Gemini Vision to identify:
- room type
- visible objects
- view from windows/doors
- overall condition

Currently returns **mock data** so the frontend can be developed
in parallel.
"""


def analyze_frame(frame: bytes) -> dict:
    """Analyze a single video frame using Gemini Vision.

    Args:
        frame: Raw byte-buffer of a single decoded video frame
               (e.g. JPEG or raw pixel data).

    Returns:
        A dict describing the scene observed in the frame:
            - room_type (str): The type of room detected.
            - objects (list[str]): Notable objects visible in the frame.
            - view (str): What is visible through windows/doors.
            - condition (str): Overall condition assessment.

    Note:
        Currently returns mock data matching the example in the
        architecture document.  Real implementation will encode the
        frame and send it to the Gemini Vision API.
    """
    # TODO: Implement real Gemini Vision API call
    return {
        "room_type": "living room",
        "objects": ["sofa", "lamp", "window"],
        "view": "brick wall",
        "condition": "good",
    }
