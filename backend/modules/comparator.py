"""TrustKit AI — Listing Comparator Module.

Compares uploaded media frames against scraped listing details from scraper.py
using Gemini to produce a forensic comparison summary and a trust score.
"""

import json
import os
from typing import List, Optional

from dotenv import load_dotenv  # type: ignore

load_dotenv()

def _get_model():
    """Get the Gemini generative model (with Vertex AI -> API Key fallback)."""
    try:
        from modules.agent_reasoner import _get_model as get_reasoner_model  # type: ignore
        return get_reasoner_model()
    except Exception:
        return None

def compare_scraped_and_vision(
    scraped_listing: dict,
    vision_results: List[dict],
    user_claims: str,
    cache_filepath: Optional[str] = None
) -> dict:
    """Compare vision analysis results against the scraped listing.
    
    Args:
        scraped_listing: Dictionary from scraper.py containing listing details.
        vision_results: List of dictionaries from vision_analyzer.py for each frame.
        user_claims: Original free-text address/description submitted by the user.
        
    Returns:
        dict: A dictionary containing:
              - alert (bool)
              - message (str)
              - trust_score (int)
              - comparison_summary (str)
    """
    model = _get_model()
    
    # --- Execute User's Request: Load from Failsafe JSON Cache if available ---
    if cache_filepath and os.path.exists(cache_filepath):
        print(f"[comparator] User failsafe triggered: Reading scraper output directly from {cache_filepath}")
        try:
            with open(cache_filepath, "r", encoding="utf-8") as f:
                scraped_listing = json.load(f)
        except Exception as e:
            print(f"[comparator] Warning: Failed to load from cache {cache_filepath}: {e}")
    else:
        print("[comparator] No cache file provided or found, using memory dict.")
    
    if model is None:
        return _fallback_comparison(scraped_listing, vision_results, user_claims)
        
    # Build prompt
    prompt = _build_prompt(scraped_listing, vision_results, user_claims)
    
    try:
        response = model.generate_content(
            [prompt],
            generation_config={"response_mime_type": "application/json"},
        )
        
        text = response.text.strip()
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()
            
        result = json.loads(text)
        
        # Ensure correct types
        trust_score = max(0, min(100, int(result.get("trust_score", 50))))
        
        return {
            "alert": bool(result.get("alert", trust_score < 70)),
            "message": str(result.get("message", "Analysis complete.")),
            "trust_score": trust_score,
            "comparison_summary": str(result.get("comparison_summary", "Unable to generate summary.")),
        }
    except Exception as e:
        print(f"[comparator] Gemini comparison failed: {e}")
        return _fallback_comparison(scraped_listing, vision_results, user_claims)

def _build_prompt(scraped_listing: dict, vision_results: List[dict], user_claims: str) -> str:
    """Build the prompt for Gemini."""
    
    listing_details = scraped_listing.get("details", {})
    address_dict = scraped_listing.get("address", {})
    address_str = address_dict.get("full", "") if isinstance(address_dict, dict) else str(address_dict)
    
    prompt = f"""You are TrustKit AI, a forensic real estate fraud investigator.

You have been given two sets of data to compare:
1. VISION ANALYSIS of a video tour uploaded by a user.
2. SCRAPED LISTING DATA found online for the claimed property.

---------------------------------------------------------------------------
1. VISION ANALYSIS (from video frames)
{json.dumps(vision_results, indent=2)}

---------------------------------------------------------------------------
2. SCRAPED LISTING DATA
URL: {scraped_listing.get("listing_url", "Unknown")}
Source: {scraped_listing.get("source_site", "Unknown")}
Address: {address_str}
Price: {scraped_listing.get("price_raw", "Unknown")}
Beds: {listing_details.get("bedrooms", "Unknown")}
Baths: {listing_details.get("bathrooms", "Unknown")}
Sqft: {listing_details.get("sqft", "Unknown")}
Description: {scraped_listing.get("description", "None")}

---------------------------------------------------------------------------
3. USER CLAIMS (What the user explicitly typed in)
{user_claims if user_claims else "None provided."}

YOUR TASK:
Act as an expert investigator. Compare the vision data against the scraped listing.
Look for contradictions, missing rooms, incorrect views, or suspicious elements in the video.

CRITICAL RULES:
1. You are analyzing data extracted from a LIVE VIDEO STREAM. Do NOT use words like "photo" or "image".
2. You CANNOT visually verify a street address purely from an interior video stream. If the ONLY user claims or scraped data are addresses, you MUST NOT state "the video matches the claims". You must explicitly warn that an address alone is insufficient to verify the property identity without visual cues.
3. If the scraped property details (like single-family home vs high-rise, or 6 bedrooms vs 1 visible bedroom) completely contradict the video environment, you MUST aggressively flag the mismatch and lower the trust score.
4. You must return EXACTLY the following JSON schema:
{{
  "alert": boolean, // true if trust_score < 70 or major fraud detected
  "message": "string", // 1-sentence punchy summary of why the score was given
  "trust_score": integer, // 0 to 100
  "comparison_summary": "string" // A 5-8 line detailed summary of the consistencies and inconsistencies found. Use plain text dashes (-) for bullet points separated by newlines (\\n). DO NOT output any HTML tags like <ul> or <li> or markdown formatting.
}}

Return ONLY the JSON object, absolutely NO other text or markdown.
"""
    return prompt

def _fallback_comparison(scraped_listing: dict, vision_results: List[dict], user_claims: str) -> dict:
    """Generate a basic comparison when Gemini is unavailable."""
    score: int = 100
    alert = False
    issues = []
    
    # Check vision results for suspicious elements
    for frame in vision_results:
        suspicious = frame.get("suspicious_elements", [])
        if suspicious:
            deduction: int = len(suspicious) * 15
            score = score - deduction  # type: ignore[operator]
            issues.extend(suspicious)
            
    # VERY NAIVE comparison fallback
    if issues:
        alert = True
        msg = f"Found {len(issues)} suspicious elements in the video."
        summary = "- Warning: Potential tampering detected in video frames.\n- Recommend extreme caution."
    else:
        msg = "No major visual flags detected, but AI verification is offline."
        summary = "- Vision AI is temporarily offline.\n- No obvious red flags found in the video frames.\n- Please verify the listing manually."
        
    return {
        "alert": alert,
        "message": msg,
        "trust_score": max(0, min(100, score)),
        "comparison_summary": summary,
    }
