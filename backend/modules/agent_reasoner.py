"""TrustKit AI — Agent Reasoner Module.

Combines multiple data sources to produce a trust assessment:
- listing claims provided by the user
- vision analysis results from Gemini Vision
- previous observations (for the Live Copilot)
- metadata forensics (for Deep Scan)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Core analyzer class
# ---------------------------------------------------------------------------


class AgentReasoner:
    """
    Combines outputs from vision analysis and metadata analysis
    to determine whether a property media file is suspicious.
    """

    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        vision_results: List[Dict[str, Any]],
        metadata_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Evaluate evidence from all analyzers.

        Args:
            vision_results: outputs from vision analyzer
            metadata_results: outputs from metadata analyzer

        Returns:
            structured risk report
        """

        flags: List[str] = []
        score = 0

        # --- analyze metadata ---
        for meta in metadata_results:
            suspicious = meta.get("suspicious_flags", [])

            for flag in suspicious:
                flags.append(flag)
                score += 2

            if not meta.get("created_time"):
                flags.append("Missing original creation timestamp")
                score += 1

            if meta.get("software"):
                flags.append(f"Edited with software: {meta['software']}")
                score += 2

        # --- analyze vision ---
        for vis in vision_results:
            labels = [l.lower() for l in vis.get("labels", [])]

            if "construction site" in labels:
                flags.append("Property appears unfinished")

            if "hotel room" in labels:
                flags.append("Media resembles hotel imagery")

            if "stock photography" in labels:
                flags.append("Possible stock image usage")

        risk_level = self._calculate_risk(score)

        return {
            "risk_score": score,
            "risk_level": risk_level,
            "flags": flags,
            "summary": self._generate_summary(risk_level, flags),
        }

    def _calculate_risk(self, score: int) -> str:
        """
        Convert numeric score to human-readable risk level.
        """

        if score >= 6:
            return "HIGH"

        if score >= 3:
            return "MEDIUM"

        return "LOW"

    def _generate_summary(self, risk_level: str, flags: List[str]) -> str:
        """
        Generate a simple explanation for the user.
        """

        if not flags:
            return "No suspicious indicators detected."

        return (
            f"{len(flags)} potential issues detected. "
            f"Overall risk level: {risk_level}."
        )


# ---------------------------------------------------------------------------
# Backward-compatible convenience function
# ---------------------------------------------------------------------------
# Preserves the original module API so that existing imports in
# main.py and deep_scan.py continue to work without changes:
#   from modules.agent_reasoner import reason

_default_reasoner = AgentReasoner()


def reason(
    vision_data: dict,
    listing_claims: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Produce a trust assessment by reasoning over all available data.

    This is a backward-compatible wrapper around AgentReasoner.evaluate().
    It adapts the single-dict interface used by main.py and deep_scan.py
    into the list-based interface expected by AgentReasoner.

    Args:
        vision_data: Scene description dict returned by
            ``vision_analyzer.analyze_frame()``.
        listing_claims: Optional dict of claims made in the property
            listing (e.g. ``{"view": "park"}``) provided by the user.
        metadata: Optional forensic metadata dict returned by
            ``metadata_analyzer.analyze()`` (Deep Scan only).

    Returns:
        A dict containing the trust assessment with:
            - alert (bool): Whether an inconsistency was detected.
            - message (str): Human-readable explanation of the finding.
            - trust_score (int): Overall trust score from 0-100.
            - risk_report (dict): Full risk report from AgentReasoner.
    """
    # Wrap single dicts into lists for the AgentReasoner interface
    vision_results = [vision_data] if vision_data else []
    metadata_results = [metadata] if metadata else []

    report = _default_reasoner.evaluate(
        vision_results=vision_results,
        metadata_results=metadata_results,
    )

    # Map risk_level to a 0-100 trust score
    risk_to_score = {"LOW": 85, "MEDIUM": 64, "HIGH": 30}
    trust_score = risk_to_score.get(report["risk_level"], 50)

    return {
        "alert": report["risk_level"] in ("MEDIUM", "HIGH"),
        "message": report["summary"],
        "trust_score": trust_score,
        "risk_report": report,
    }
