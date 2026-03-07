"""TrustKit AI — Agent Reasoner Module.

Combines multiple data sources to produce a trust assessment:
- listing claims provided by the user
- vision analysis results from Gemini Vision
- previous observations (for the Live Copilot)
- metadata forensics (for Deep Scan)

Currently returns **mock data** so the frontend can be developed
in parallel.
"""

from typing import Optional


def reason(
    vision_data: dict,
    listing_claims: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Produce a trust assessment by reasoning over all available data.

    Args:
        vision_data: Scene description dict returned by
            ``vision_analyzer.analyze_frame()``.
        listing_claims: Optional dict of claims made in the property
            listing (e.g. ``{"view": "park"}``) provided by the user.
        metadata: Optional forensic metadata dict returned by
            ``metadata_analyzer.analyze()`` (Deep Scan only).

    Returns:
        A dict containing the trust assessment:
            - alert (bool): Whether an inconsistency was detected.
            - message (str): Human-readable explanation of the finding.
            - trust_score (int): Overall trust score from 0-100.

    Note:
        Currently returns mock data matching the example in the
        architecture document.  Real implementation will use Gemini
        Agents / reasoning to compare inputs and generate a meaningful
        trust assessment.
    """
    # TODO: Implement real reasoning with Gemini Agents / LLM
    return {
        "alert": True,
        "message": "Listing claimed park view but camera shows brick wall",
        "trust_score": 64,
    }
