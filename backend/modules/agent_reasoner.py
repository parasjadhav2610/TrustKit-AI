"""TrustKit AI — Agent Reasoner Module.

Combines multiple data sources to produce a trust assessment:
- listing claims provided by the user
- vision analysis results from Gemini Vision
- metadata forensics (for Deep Scan)

Uses Gemini generative AI to reason over the inputs and produce a
human-readable trust assessment.  Falls back to rule-based heuristics
if the API key is missing or the API call fails.
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv  # type: ignore

load_dotenv()

# ---------------------------------------------------------------------------
# Gemini client (lazy-initialised)
# ---------------------------------------------------------------------------

_model = None


def _get_model():
    """Lazily initialise and return the Gemini GenerativeModel."""
    global _model
    if _model is not None:
        return _model

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=api_key)
    _model = genai.GenerativeModel("gemini-2.0-flash")
    return _model


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are TrustKit AI, a real-estate trust analysis agent.

You will be given structured data about a property tour and must assess
whether the property is being represented honestly.

Return your answer as a JSON object with EXACTLY these keys:
- "alert"       (boolean) — true if any inconsistency or red flag is found.
- "message"     (string)  — a clear, 1-2 sentence explanation for the user.
- "trust_score" (integer) — an overall trust score from 0 to 100.
- "flags"       (list of strings) — specific red flags detected.

A score of 100 means fully trustworthy. A score below 50 is very suspicious.
Return ONLY the JSON object, no extra text.
"""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_user_prompt(
    vision_data: dict,
    listing_claims: Optional[dict],
    metadata: Optional[dict],
) -> str:
    """Build the user-facing prompt string from available data."""
    parts: list[str] = []

    parts.append("## Vision Analysis (what the camera sees)")
    parts.append(json.dumps(vision_data, indent=2))

    if listing_claims:
        parts.append("\n## Listing Claims (what the landlord promises)")
        parts.append(json.dumps(listing_claims, indent=2))

    if metadata:
        parts.append("\n## Video Metadata Forensics")
        parts.append(json.dumps(metadata, indent=2, default=str))

    parts.append("\nBased on the above, produce your trust assessment JSON.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------


def _rule_based_reason(
    vision_data: dict,
    listing_claims: Optional[dict],
    metadata: Optional[dict],
) -> dict:
    """Simple heuristic scoring when Gemini is unavailable."""
    score: int = 100
    issues: list[str] = []
    flags: list[str] = []

    # --- Listing claim vs vision mismatch ---
    if listing_claims and vision_data:
        claimed_view = (listing_claims.get("view") or "").lower()
        observed_view = (vision_data.get("view") or "").lower()
        if claimed_view and observed_view and claimed_view != observed_view:
            score -= 30
            issues.append(
                f"Listing claims '{claimed_view}' view but camera shows "
                f"'{observed_view}'."
            )
            flags.append("view_mismatch")

        claimed_room = (listing_claims.get("room_type") or "").lower()
        observed_room = (vision_data.get("room_type") or "").lower()
        if claimed_room and observed_room and claimed_room != observed_room:
            score -= 15
            issues.append(
                f"Expected '{claimed_room}' but observed '{observed_room}'."
            )
            flags.append("room_type_mismatch")

    # --- Metadata red flags ---
    if metadata:
        suspicious: list[str] = metadata.get("suspicious_flags", [])
        if isinstance(suspicious, list):
            for flag_item in suspicious:
                if flag_item == "edited_media":
                    score -= 15
                    issues.append("Media appears to have been edited with software.")
                    flags.append("edited_media")
                elif flag_item == "metadata_unavailable":
                    score -= 10  # type: ignore
                    issues.append("No metadata found — may have been stripped.")
                    flags.append("no_metadata")
                elif flag_item == "missing_creation_time":
                    score -= 5  # type: ignore
                    issues.append("Original creation timestamp is missing.")
                    flags.append("no_timestamp")

        if metadata.get("re_encoded"):
            score -= 20
            issues.append("Video has been re-encoded, which may indicate tampering.")
            flags.append("re_encoded")

        created = str(metadata.get("created_time") or metadata.get("created") or "")
        if created:
            try:
                # Try to parse year from various formats
                year = int(created[0:4]) if len(created) >= 4 else 0  # type: ignore
                current_year = datetime.now().year
                if year > 0 and current_year - year >= 2:
                    score -= 15
                    issues.append(
                        f"Media was originally created in {year}, which is "
                        f"{current_year - year} years old."
                    )
                    flags.append("outdated_media")
            except (ValueError, TypeError):
                pass

    # --- Vision condition ---
    condition = (vision_data.get("condition") or "").lower()
    if condition in ("poor", "bad", "damaged"):
        score -= 10
        issues.append(f"Property condition appears '{condition}'.")
        flags.append("poor_condition")

    score = max(0, min(100, score))
    alert = score < 80 or len(issues) > 0
    message = " ".join(issues) if issues else "No issues detected."

    return {
        "alert": alert,
        "message": message,
        "trust_score": score,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reason(
    vision_data: dict,
    listing_claims: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Produce a trust assessment by reasoning over all available data.

    Uses Gemini to compare the vision analysis, listing claims, and
    metadata forensics.  Falls back to rule-based heuristics when the
    API key is unavailable or the call fails.

    Args:
        vision_data: Scene description dict from vision_analyzer.
        listing_claims: Optional listing claims from the user.
        metadata: Optional forensic metadata dict (Deep Scan only).

    Returns:
        dict with keys: alert, message, trust_score, flags.
    """
    model = _get_model()

    if model is None:
        return _rule_based_reason(vision_data, listing_claims, metadata)

    user_prompt = _build_user_prompt(vision_data, listing_claims, metadata)

    try:
        response = model.generate_content(
            [
                {"role": "user", "parts": [_SYSTEM_PROMPT + "\n\n" + user_prompt]},
            ],
        )

        text = response.text.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)

        return {
            "alert": bool(result.get("alert", True)),
            "message": str(result.get("message", "Analysis complete.")),
            "trust_score": int(result.get("trust_score", 50)),
            "flags": list(result.get("flags", [])),
        }

    except Exception as exc:
        print(f"[agent_reasoner] Gemini call failed, using fallback: {exc}")
        return _rule_based_reason(vision_data, listing_claims, metadata)
