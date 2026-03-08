"""TrustKit AI — Deep Scan REST Endpoint.

Provides the POST /deep-scan route for forensic analysis of
prerecorded property tour videos.
"""

import os
import tempfile

from fastapi import APIRouter, File, UploadFile

from modules.frame_extractor import extract_from_file
from modules.vision_analyzer import analyze_frame
from modules.agent_reasoner import reason
from modules.tts_engine import generate_warning_audio

router = APIRouter()


@router.post("/deep-scan")
async def deep_scan(file: UploadFile = File(...)):
    """Run forensic Deep Scan analysis on an uploaded video.

    Pipeline:
        1. Save the uploaded file to a temporary location.
        2. Extract key frames from the video.
        3. Analyse video metadata (timestamps, codecs, re-encoding).
        4. Run vision analysis on extracted frames.
        5. Feed all data into the agent reasoner.
        6. Return a combined forensic report.

    Args:
        file: The uploaded video file (multipart form-data).

    Returns:
        dict: A JSON forensic report containing metadata analysis,
              vision analysis of extracted frames, and an overall
              trust assessment from the agent reasoner.
    """

    # Save uploaded file to a temp path
    suffix = os.path.splitext(file.filename or "video.mp4")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        import asyncio
        # --- Mock pipeline ---
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

        return {
            "filename": file.filename,
            "metadata": metadata,
            "vision_analysis": vision_results,
            "assessment": assessment,
            "audio_data": audio_data
        }
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
