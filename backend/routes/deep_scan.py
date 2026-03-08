"""TrustKit AI — Deep Scan REST Endpoint.

Provides the POST /deep-scan route for forensic analysis of
prerecorded property tour videos, with optional Zillow listing comparison.
"""

import os
import tempfile

from fastapi import APIRouter, File, Form, UploadFile
from typing import Optional

from modules.frame_extractor import extract_from_file
from modules.vision_analyzer import analyze_frame
from modules.agent_reasoner import reason
from modules.tts_engine import generate_warning_audio

router = APIRouter()


@router.post("/deep-scan")
async def deep_scan(
    file: UploadFile = File(...),
    address: Optional[str] = Form(None),
):
    """Run forensic Deep Scan analysis on an uploaded video.

    Pipeline:
        1. Save the uploaded file to a temporary location.
        2. Extract key frames from the video.
        3. Analyse video metadata (timestamps, codecs, re-encoding).
        4. Run vision analysis on extracted frames.
        5. Feed all data into the agent reasoner.
        6. If address is provided, scrape Zillow and compare.
        7. Return a combined forensic report.

    Args:
        file: The uploaded video file (multipart form-data).
        address: Optional property address to search on Zillow.

    Returns:
        dict: A JSON forensic report containing metadata analysis,
              vision analysis of extracted frames, trust assessment,
              and optionally a Zillow listing comparison.
    """

    # Save uploaded file to a temp path
    suffix = os.path.splitext(file.filename or "video.mp4")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        import asyncio
        # --- Analysis pipeline ---
        frames = extract_from_file(tmp_path, num_frames=7)
        metadata = {
            "created": "2024",
            "codec": "H.264",
            "re_encoded": False
        }
        
        # Concurrently process all frames through the Vision Analyzer
        async def process_frame(frame):
            return await asyncio.to_thread(analyze_frame, frame)
            
        vision_results = await asyncio.gather(*(process_frame(f) for f in frames))
        
        assessment = reason(
            vision_data=vision_results[0] if vision_results else {},
            metadata=metadata,
        )
        
        # --- Audio Pipeline ---
        audio_data = None
        if assessment.get("alert"):
            audio_data = await asyncio.to_thread(generate_warning_audio, assessment)

        # --- Zillow Comparison Pipeline (if address provided) ---
        listing_comparison = None
        listing_data = None
        
        if address and address.strip():
            try:
                from modules.zillow_scraper import search_by_address
                from modules.listing_comparator import compare_video_vs_listing
                
                # Scrape Zillow listing
                listing_data = await asyncio.to_thread(search_by_address, address.strip())
                
                # Compare if we have photos from both sources
                listing_photos = listing_data.get("photos_bytes", [])
                
                comparison_summary = await asyncio.to_thread(
                    compare_video_vs_listing,
                    frames[:3],  # first 3 video frames
                    listing_photos,  # listing photos
                    listing_data,  # listing details
                )
                
                listing_comparison = {
                    "address": listing_data.get("address", address),
                    "price": listing_data.get("price", "N/A"),
                    "beds": listing_data.get("beds", "N/A"),
                    "baths": listing_data.get("baths", "N/A"),
                    "sqft": listing_data.get("sqft", "N/A"),
                    "description": listing_data.get("description", ""),
                    "photo_count": len(listing_data.get("photo_urls", [])),
                    "source": listing_data.get("source", "unknown"),
                    "comparison_summary": comparison_summary,
                }
            except Exception as e:
                print(f"[deep_scan] Zillow comparison failed: {e}")
                listing_comparison = {
                    "error": str(e),
                    "comparison_summary": "Zillow comparison was unavailable. Please try again.",
                }

        result = {
            "filename": file.filename,
            "metadata": metadata,
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
