"""TrustKit AI — Agent Reasoner Module.

Combines multiple data sources to produce a trust assessment:
- vision analysis results from Gemini Vision (including suspicious elements)
- listing claims provided by the user
- metadata forensics (for Deep Scan)

Uses Vertex AI (Gemini) to reason over the inputs and produce a
human-readable trust assessment.  Falls back to rule-based heuristics
if Vertex AI is not configured or the API call fails.
"""

import json
import os
import re
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Vertex AI client (lazy-initialised)
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
        print("[agent_reasoner] GOOGLE_CLOUD_PROJECT not set — using rule-based fallback")
        _initialised = True
        return None

    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(project=project, location=location)
        _model = GenerativeModel("gemini-2.5-flash")
        _initialised = True
        print(f"[agent_reasoner] Vertex AI initialised (project={project}, location={location})")
        return _model
    except Exception as exc:
        print(f"[agent_reasoner] Vertex AI init failed: {exc}. Attempting google.generativeai fallback...")
        try:
            import google.generativeai as genai
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                _model = genai.GenerativeModel("gemini-2.5-flash")
                _initialised = True
                print("[agent_reasoner] Google Generative AI initialised via API Key.")
                return _model
        except Exception as exc2:
            print(f"[agent_reasoner] Google Generative AI init failed: {exc2}")
            
        print("[agent_reasoner] All model initializations failed. Using rule-based fallback.")
        _initialised = True
        return None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Real Estate Fraud Investigator for TrustKit AI. Your job is to \
analyze property tour data and determine whether a rental listing is \
being represented honestly.

You will receive two inputs:
1. **Vision Data** — A JSON object from our Vision AI containing detected \
objects, room type, view, condition, and any suspicious elements found in \
the property tour frame.
2. **Listing Claims** — The text from the property listing that describes \
what the landlord is advertising.

Your task:
- Compare the vision data against the listing claims.
- Look for inconsistencies (e.g., listing says "park view" but vision \
shows "brick wall").
- Check for suspicious elements flagged by the Vision AI (editing \
artifacts, staging indicators, stock photos).
- Evaluate the overall trustworthiness of the listing.

Scoring rules:
- trust_score ranges from 0 (confirmed scam) to 100 (perfectly safe).
- If suspicious_elements are present, deduct 10-20 points per element \
depending on severity.
- If listing claims contradict the vision data, deduct 20-30 points.
- If the image appears to not be a real property photo, score below 30.
- Set alert to true if trust_score drops below 70 or if major \
suspicious elements are found.

Return EXACTLY this JSON schema:
{"alert": bool, "message": "string", "trust_score": int}

The "message" field must be a punchy, 1-sentence explanation of why \
the score was given. Examples:
- "Listing claims a park view, but the camera shows a brick wall."
- "Image appears to be a stock photo, not an actual property image."
- "Property matches the listing description with no red flags detected."

Return ONLY the JSON object, no extra text.
"""


# ---------------------------------------------------------------------------
# Primary API — evaluate_trust
# ---------------------------------------------------------------------------


def evaluate_trust(vision_data: dict, listing_claims: str = "") -> dict:
    """Evaluate the trustworthiness of a property listing.

    Uses Vertex AI Gemini to compare vision analysis data against
    listing claims and produce a trust assessment.

    Args:
        vision_data: Scene analysis dict returned by
            ``vision_analyzer.analyze_frame()``, including keys like
            room_type, objects, view, condition, suspicious_elements.
        listing_claims: Free-text string of the property listing
            description (e.g. "Luxury 2-bed apartment with park view").

    Returns:
        A dict with exactly:
            - alert (bool): True if trust_score < 70 or major issues.
            - message (str): 1-sentence explanation.
            - trust_score (int): 0–100 trust score.
    """
    model = _get_model()

    # --- Fallback if Vertex AI not available ---
    if model is None:
        return _rule_based_reason(vision_data, listing_claims)

    # --- Build the prompt ---
    user_prompt = (
        "## Vision Data\n"
        f"{json.dumps(vision_data, indent=2)}\n\n"
        "## Listing Claims\n"
        f"{listing_claims if listing_claims else 'No listing claims provided.'}"
    )

    try:
        response = model.generate_content(
            [_SYSTEM_PROMPT + "\n\n" + user_prompt],
            generation_config={"response_mime_type": "application/json"},
        )

        text = response.text.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)

        # Normalise and validate the output
        trust_score = max(0, min(100, int(result.get("trust_score", 50))))
        alert = bool(result.get("alert", trust_score < 70))

        return {
            "alert": alert,
            "message": str(result.get("message", "Analysis complete.")),
            "trust_score": trust_score,
        }

    except Exception as exc:
        print(f"[agent_reasoner] Vertex AI call failed, using fallback: {exc}")
        return _rule_based_reason(vision_data, listing_claims)


# ---------------------------------------------------------------------------
# Rule-based fallback (Vertex AI unavailable)
# ---------------------------------------------------------------------------


def _rule_based_reason(
    vision_data: dict,
    listing_claims: str = "",
    metadata: Optional[dict] = None,
) -> dict:
    """Simple heuristic scoring when Vertex AI is unavailable.

    Deducts points for known red-flag patterns in the vision data,
    listing claims, and metadata.
    """
    score = 100
    issues: list[str] = []

    # --- Suspicious elements from vision ---
    suspicious = vision_data.get("suspicious_elements", [])
    if suspicious:
        deduction = min(40, len(suspicious) * 15)
        score -= deduction
        issues.append(
            f"Vision AI flagged {len(suspicious)} suspicious element(s)."
        )

    # --- Listing claim vs vision mismatch ---
    if listing_claims:
        claims_lower = listing_claims.lower()
        observed_view = (vision_data.get("view") or "").lower()

        # Check common view claims
        for keyword in ["park", "ocean", "garden", "river", "lake", "city"]:
            if keyword in claims_lower and observed_view and keyword not in observed_view:
                score -= 25
                issues.append(
                    f"Listing mentions '{keyword}' but camera shows '{observed_view}'."
                )
                break

        # Check room type claims
        observed_room = (vision_data.get("room_type") or "").lower()
        if observed_room in ("null", "unknown", ""):
            score -= 20
            issues.append("Image does not appear to show a real property room.")

    # --- Metadata red flags (Deep Scan) ---
    if metadata:
        if metadata.get("re_encoded"):
            score -= 20
            issues.append(
                "Video has been re-encoded, which may indicate tampering."
            )

        created = str(metadata.get("created", ""))
        if created and created.isdigit():
            from datetime import datetime
            current_year = datetime.now().year
            if current_year - int(created) >= 2:
                score -= 15
                issues.append(
                    f"Video was created in {created} ({current_year - int(created)} years ago)."
                )

    # --- Vision condition ---
    condition = (vision_data.get("condition") or "").lower()
    if condition in ("poor", "bad", "damaged"):
        score -= 10
        issues.append(f"Property condition appears '{condition}'.")

    score = max(0, min(100, score))
    alert = score < 70 or len(issues) > 0
    message = " ".join(issues) if issues else "No issues detected."

    return {
        "alert": alert,
        "message": message,
        "trust_score": score,
    }


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------
# Preserves the original API so existing imports in main.py and
# deep_scan.py continue to work without changes:
#   from modules.agent_reasoner import reason


def reason(
    vision_data: dict,
    listing_claims: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Backward-compatible wrapper around evaluate_trust.

    Converts the old dict-based listing_claims into a string and
    delegates to evaluate_trust(). Also passes metadata for the
    rule-based fallback.

    Args:
        vision_data: Scene description dict from vision_analyzer.
        listing_claims: Optional dict of listing claims.
        metadata: Optional forensic metadata dict (Deep Scan only).

    Returns:
        A dict with: alert (bool), message (str), trust_score (int).
    """
    # Convert dict claims to a readable string
    claims_str = ""
    if listing_claims:
        claims_str = ", ".join(
            f"{k}: {v}" for k, v in listing_claims.items()
        )

    result = evaluate_trust(vision_data, claims_str)

    # If we used the fallback and have metadata, re-run with metadata
    model = _get_model()
    if model is None and metadata:
        return _rule_based_reason(vision_data, claims_str, metadata)

    return result
