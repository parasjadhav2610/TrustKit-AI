"""TrustKit AI — Deep Scan REST Endpoint.

Provides the POST /deep-scan route for forensic analysis of
prerecorded property tour videos.
"""

import asyncio
import json
import os
import tempfile

from fastapi import APIRouter, File, Form, UploadFile

from modules.frame_extractor import extract_from_file
from modules.metadata_analyzer import analyze_live_frame
from modules.vision_analyzer import analyze_frame
from modules.agent_reasoner import evaluate_trust

router = APIRouter()


@router.post("/deep-scan")
async def deep_scan(
    file: UploadFile = File(...),
    listing_address: str = Form(""),
    listing_description: str = Form(""),
):
    """Run forensic Deep Scan analysis on an uploaded video.

    Pipeline:
        1. Save the uploaded file to a temporary location.
        2. Extract key frames from the video.
        3. Run OpenCV forensics on each frame (blur/brightness).
        4. Run Vertex AI vision analysis on extracted frames.
        5. Combine forensic + vision data and pass to agent reasoner.
        6. Return a combined forensic report.

    Args:
        file: The uploaded video file (multipart form-data).
        listing_address: Optional property address from the user.
        listing_description: Optional listing description from the user.

    Returns:
        dict: A JSON forensic report containing forensics analysis,
              vision analysis of extracted frames, and an overall
              trust assessment from the agent reasoner.
    """

    # Build listing claims string from user input
    address = listing_address.strip()
    description = listing_description.strip()

    # Auto-scrape Zillow if address is provided
    if address:
        print(f"[deep-scan] 🔍 Auto-scraping Zillow for: {address}")
        from modules.listing_scraper import scrape_zillow_listing
        scraped = await asyncio.to_thread(scrape_zillow_listing, address)
        if scraped.get("found") and scraped.get("description"):
            scraped_parts = []
            if scraped.get("price", "N/A") != "N/A":
                scraped_parts.append(f"Price: {scraped['price']}")
            if scraped.get("bedrooms", "N/A") != "N/A":
                scraped_parts.append(f"{scraped['bedrooms']} bed")
            if scraped.get("bathrooms", "N/A") != "N/A":
                scraped_parts.append(f"{scraped['bathrooms']} bath")
            if scraped.get("sqft", "N/A") != "N/A":
                scraped_parts.append(f"{scraped['sqft']} sqft")
            scraped_header = " · ".join(scraped_parts) + ". " if scraped_parts else ""
            scraped_desc = scraped_header + scraped["description"]
            description = (description + " " + scraped_desc).strip() if description else scraped_desc
            print(f"[deep-scan] ✓ Zillow data found, enriched listing claims")
        else:
            print(f"[deep-scan] ⚠️  Zillow scrape failed: {scraped.get('error', 'unknown')}")

    parts = []
    if address:
        parts.append(f"Address: {address}")
    if description:
        parts.append(description)
    listing_claims = ". ".join(parts) if parts else ""

    print(f"[deep-scan] File: {file.filename}")
    print(f"[deep-scan] Listing claims: {listing_claims or '(none provided)'}")

    # Save uploaded file to a temp path
    suffix = os.path.splitext(file.filename or "video.mp4")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        # --- Extract frames ---
        frames = await asyncio.to_thread(extract_from_file, tmp_path)
        print(f"[deep-scan] Extracted {len(frames)} frames")

        # --- Analyze each frame (forensics + vision) ---
        vision_results = []
        forensics_results = []

        for i, frame in enumerate(frames):
            print(f"[deep-scan] Analyzing frame {i + 1}/{len(frames)}...")

            # OpenCV forensics on raw bytes
            forensics = await asyncio.to_thread(analyze_live_frame, frame)
            forensics_results.append(forensics)

            # Vertex AI vision
            vision = await asyncio.to_thread(analyze_frame, frame)
            vision_results.append(vision)

        # --- Combine first frame data for trust assessment ---
        combined_payload = {}
        if vision_results:
            combined_payload = {**vision_results[0]}

            # Merge forensic flags into suspicious_elements
            if forensics_results:
                forensic_flags = forensics_results[0].get("suspicious_flags", [])
                vision_suspicious = combined_payload.get("suspicious_elements", [])
                combined_payload["suspicious_elements"] = vision_suspicious + forensic_flags
                combined_payload["forensics"] = {
                    "blur_score": forensics_results[0].get("blur_score", 0),
                    "brightness": forensics_results[0].get("brightness", 0),
                }

        # --- Agent Reasoner ---
        assessment = await asyncio.to_thread(
            evaluate_trust,
            combined_payload,
            listing_claims,
        )

        print(f"[deep-scan] Assessment: score={assessment.get('trust_score')}, "
              f"alert={assessment.get('alert')}")

        return {
            "filename": file.filename,
            "listing_claims": listing_claims,
            "forensics": forensics_results,
            "vision_analysis": vision_results,
            "assessment": assessment,
        }
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
