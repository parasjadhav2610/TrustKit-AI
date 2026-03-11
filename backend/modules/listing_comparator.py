"""TrustKit AI — Listing Comparator Module.

Compares uploaded video frames against scraped Zillow listing photos
using Gemini Vision to produce a 20-line forensic comparison summary.
"""

import base64
import json
import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()


def _get_model():
    """Get the Gemini generative model (with Vertex AI -> API Key fallback)."""
    try:
        from modules.agent_reasoner import _get_model as get_reasoner_model
        return get_reasoner_model()
    except Exception:
        return None


def compare_video_vs_listing(
    video_frames: List[bytes],
    listing_photos: List[bytes],
    listing_details: dict,
) -> str:
    """Compare video frames against Zillow listing photos using Gemini Vision.
    
    Args:
        video_frames: List of JPEG-encoded bytes from the uploaded video.
        listing_photos: List of JPEG-encoded bytes from the Zillow listing.
        listing_details: Dict with keys: address, price, beds, baths, sqft, description.
    
    Returns:
        A 20-line forensic comparison summary string.
    """
    model = _get_model()
    
    if model is None:
        return _fallback_comparison(listing_details)
    
    # Build multi-modal prompt with images
    try:
        parts = _build_prompt_parts(video_frames, listing_photos, listing_details)
        response = model.generate_content(parts)
        return response.text.strip()
    except Exception as e:
        print(f"[listing_comparator] Gemini comparison failed: {e}")
        # Try with the google.generativeai format
        try:
            return _compare_with_genai(video_frames, listing_photos, listing_details)
        except Exception as e2:
            print(f"[listing_comparator] genai comparison also failed: {e2}")
            return _fallback_comparison(listing_details)


def _build_prompt_parts(
    video_frames: List[bytes],
    listing_photos: List[bytes],
    listing_details: dict,
) -> list:
    """Build the multi-modal prompt parts for Gemini."""
    
    prompt_text = f"""You are TrustKit AI, a forensic real estate fraud investigator. You have been given:

1. FRAMES FROM A VIDEO TOUR of a property (labeled "Video Frame 1", "Video Frame 2", etc.)
2. PHOTOS FROM THE ZILLOW LISTING for the same address (labeled "Listing Photo 1", "Listing Photo 2", etc.)
3. The LISTING DETAILS from Zillow.

LISTING DETAILS:
- Address: {listing_details.get('address', 'Unknown')}
- Price: {listing_details.get('price', 'N/A')}
- Beds: {listing_details.get('beds', 'N/A')}
- Baths: {listing_details.get('baths', 'N/A')}  
- Sqft: {listing_details.get('sqft', 'N/A')}
- Description: {listing_details.get('description', 'No description')}

YOUR TASK:
Compare the video tour frames with the Zillow listing photos and generate a DETAILED 20-LINE FORENSIC COMPARISON REPORT. Each line should be a complete sentence covering one specific observation.

Cover these areas:
- Do the rooms in the video match the rooms in the listing photos?
- Are the walls, floors, and fixtures consistent between the video and photos?
- Does the view from windows match between video and listing?
- Are there signs of photo editing or staging in the listing photos?
- Does the property condition in the video match what the listing claims?
- Are the number of rooms consistent with the bed/bath count listed?
- Are there any objects, furniture, or features present in one but missing in the other?
- Overall trust assessment: Is the listing honest or potentially deceptive?

FORMAT: Write exactly 20 lines. Each line should be a numbered observation (1-20).
Do NOT use markdown formatting, bullet points, or headers. Just numbered lines.
Return ONLY the 20 numbered lines, nothing else."""

    parts = [prompt_text]
    
    # Try to use google.generativeai Image format
    try:
        import google.generativeai as genai
        from PIL import Image
        import io
        
        # Add video frames
        for i, frame_bytes in enumerate(video_frames[:3]):
            parts.append(f"\n--- Video Frame {i+1} ---\n")
            img = Image.open(io.BytesIO(frame_bytes))
            parts.append(img)
        
        # Add listing photos
        for i, photo_bytes in enumerate(listing_photos[:3]):
            parts.append(f"\n--- Listing Photo {i+1} ---\n")
            img = Image.open(io.BytesIO(photo_bytes))
            parts.append(img)
            
        return parts
        
    except ImportError:
        # Fall back to Vertex AI Part format
        try:
            from vertexai.generative_models import Part
            
            for i, frame_bytes in enumerate(video_frames[:3]):
                parts.append(f"\n--- Video Frame {i+1} ---\n")
                parts.append(Part.from_data(data=frame_bytes, mime_type="image/jpeg"))

            for i, photo_bytes in enumerate(listing_photos[:3]):
                parts.append(f"\n--- Listing Photo {i+1} ---\n")
                parts.append(Part.from_data(data=photo_bytes, mime_type="image/jpeg"))
                
            return parts
        except ImportError:
            return [prompt_text]


def _compare_with_genai(
    video_frames: List[bytes],
    listing_photos: List[bytes],
    listing_details: dict,
) -> str:
    """Fallback comparison using google.generativeai SDK directly."""
    import google.generativeai as genai
    from PIL import Image
    import io
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    parts = _build_prompt_parts(video_frames, listing_photos, listing_details)
    response = model.generate_content(parts)
    return response.text.strip()


def _fallback_comparison(listing_details: dict) -> str:
    """Generate a basic comparison when Gemini is unavailable."""
    address = listing_details.get("address", "the property")
    lines = [
        f"1. Forensic comparison report for: {address}",
        f"2. Listed price: {listing_details.get('price', 'N/A')}, {listing_details.get('beds', 'N/A')} beds, {listing_details.get('baths', 'N/A')} baths.",
        "3. AI Vision comparison engine was unavailable for this analysis.",
        "4. Video frames were extracted but could not be compared against listing photos.",
        "5. Manual visual inspection of the video tour is recommended.",
        "6. Check that room layouts in the video match the floor plan described in the listing.",
        "7. Verify window views shown in the video against listing photo backgrounds.",
        "8. Look for signs of photo editing like warped edges or inconsistent lighting in listing photos.",
        "9. Compare furniture and fixture placement between video and listing photos.",
        "10. Check if wall colors and flooring materials are consistent across both sources.",
        "11. Verify that the number of rooms in the tour matches the bed/bath count.",
        "12. Look for staging indicators like price tags or showroom-like setups.",
        "13. Check if the listing photos appear to be from a different season than the video tour.",
        "14. Compare the overall property condition between the video and the listing claims.",
        "15. Inspect whether appliances shown in listing photos are present in the video.",
        "16. Check for any watermarks or stock photo indicators in the listing images.",
        "17. Verify that exterior views and building entrances match across both sources.",
        "18. Look for inconsistencies in natural lighting between the listing photos and video frames.",
        "19. A full AI-powered analysis requires API access to generate a complete trust assessment.",
        "20. RECOMMENDATION: Exercise caution and consider an in-person visit before making any decisions.",
    ]
    return "\n".join(lines)
