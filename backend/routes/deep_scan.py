"""TrustKit AI — Deep Scan REST Endpoint.

Provides the POST /deep-scan route for forensic analysis of
prerecorded property tour videos, with optional Zillow listing comparison.
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
from modules.tts_engine import generate_warning_audio

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

    # Auto-scrape listing if address is provided
    scraped_listing_data = {}
    if address:
        print(f"[deep-scan] 🔍 Auto-scraping listing for: {address}")
        from modules.scraper import SearchAgent, UniversalParser
        
        # Run search and parse in a thread because Playwright/HTTP requests are blocking
        def _scrape():
            agent = SearchAgent(max_results=10)
            urls = agent.find(query=address)
            if not urls:
                return {"found": False, "error": "No listings found online."}
                
            parser = UniversalParser(headless=True)
            for result in urls:
                parsed = parser.parse(result["url"])
                if parsed:
                    return {"found": True, "listing": parsed.to_dict()}
            return {"found": False, "error": "Failed to parse listing pages."}

        scraped = await asyncio.to_thread(_scrape)
        
        if scraped.get("found") and scraped.get("listing"):
            scraped_listing_data = scraped["listing"]
            listing_details = scraped_listing_data.get("details", {})
            scraped_desc = scraped_listing_data.get("description", "")
            
            scraped_parts = []
            if scraped_listing_data.get("price") is not None:
                scraped_parts.append(f"Price: {scraped_listing_data['price_raw']}")
            if listing_details.get("bedrooms") is not None:
                scraped_parts.append(f"{listing_details['bedrooms']} bed")
            if listing_details.get("bathrooms") is not None:
                scraped_parts.append(f"{listing_details['bathrooms']} bath")
            if listing_details.get("sqft") is not None:
                scraped_parts.append(f"{listing_details['sqft']} sqft")
                
            scraped_header = " · ".join(scraped_parts) + ". " if scraped_parts else ""
            full_desc = scraped_header + scraped_desc
            description = (description + " " + full_desc).strip() if description else full_desc
            print(f"[deep-scan] ✓ Listing data found from {scraped_listing_data.get('source_site')}, enriched listing claims")
        else:
            print(f"[deep-scan] ⚠️  Listing scrape failed: {scraped.get('error', 'unknown')}")

    parts = []
    # Drop the repetitive Address prefix from the generic claims string
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

        # --- Agent Reasoner (Baseline fallback, overwritten by comparator if there is address data) ---
        assessment = await asyncio.to_thread(
            evaluate_trust,
            combined_payload,
            listing_claims,
        )

        # --- Listing Comparison & Final Assessment ---
        listing_comparison = None
        
        if address and scraped_listing_data:
            from modules.comparator import compare_scraped_and_vision
            
            # --- Write to fallback cache file as requested by the user ---
            import re
            
            # Create a safe filename from the address
            safe_address = re.sub(r'[^a-zA-Z0-9_\-]', '_', address).strip('_')
            cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", "scraper_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_filepath = os.path.join(cache_dir, f"{safe_address}.json")
            
            with open(cache_filepath, "w", encoding="utf-8") as f:
                json.dump(scraped_listing_data, f, indent=4)
                
            print(f"[deep-scan] Saved scraper output to failsafe cache: {cache_filepath}")
            
            print("[deep-scan] Running detailed comparison from JSON file exclusively...")
            comp_result = await asyncio.to_thread(
                compare_scraped_and_vision,
                {},  # INTENTIONALLY PASS EMPTY DICT TO FORCE FILE LOAD
                vision_results,
                listing_claims,
                cache_filepath  # Pass the path to the comparator
            )
            
            # Use the more comprehensive comparator output instead!
            assessment = {
                "alert": comp_result["alert"],
                "message": comp_result["message"],
                "trust_score": comp_result["trust_score"],
            }
            
            listing_details = scraped_listing_data.get("details", {})
            addr_obj = scraped_listing_data.get("address", {})
            addr_str = addr_obj.get("full", address) if isinstance(addr_obj, dict) else str(addr_obj)
            
            # Format comparison for frontend
            listing_comparison = {
                "address": addr_str,
                "price": scraped_listing_data.get("price_raw", "N/A"),
                "beds": str(listing_details.get("bedrooms", "N/A")),
                "baths": str(listing_details.get("bathrooms", "N/A")),
                "sqft": str(listing_details.get("sqft", "N/A")),
                "description": scraped_listing_data.get("description", ""),
                "photo_count": len(scraped_listing_data.get("images", [])),
                "source": scraped_listing_data.get("source_site", "unknown"),
                "comparison_summary": comp_result["comparison_summary"],
            }
        elif address:
            listing_comparison = {
                "error": "Listing data was unavailable.",
                "comparison_summary": "Scraper was unable to find this listing online to perform a comparison.",
            }
        
        # --- Audio Pipeline ---
        audio_data = None
        if assessment.get("alert"):
            audio_data = await asyncio.to_thread(generate_warning_audio, assessment)



        print(f"[deep-scan] Assessment: score={assessment.get('trust_score')}, "
              f"alert={assessment.get('alert')}")

        result = {
            "filename": file.filename,
            "listing_claims": listing_claims,
            "forensics": forensics_results,
            "vision_analysis": vision_results,
            "assessment": assessment,
            "audio_data": audio_data,
        }
        
        if listing_comparison:
            result["listing_comparison"] = listing_comparison
            
        return result
        
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
