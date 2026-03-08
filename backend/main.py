"""TrustKit AI — FastAPI Backend Entry Point.

Initializes the FastAPI application with:
- CORS middleware (all origins allowed for local hackathon testing)
- WebSocket endpoint at /ws/live for the Live Copilot pipeline
- Health-check endpoint
"""

import asyncio
import json
import traceback

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from modules.vision_analyzer import analyze_frame
from modules.metadata_analyzer import analyze_live_frame
from modules.agent_reasoner import evaluate_trust

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TrustKit AI",
    description=(
        "Real-time voice-and-vision AI agent that watches virtual property "
        "tours and flags inconsistencies between what is shown and what "
        "the listing promises."
    ),
    version="0.2.0",
)

# CORS — allow everything for local hackathon development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Safe fallback — sent when any per-frame processing fails
# ---------------------------------------------------------------------------

_FALLBACK_ALERT = {
    "alert": False,
    "message": "Analyzing next frame...",
    "trust_score": 50,
}

# Mock listing claim for the demo. In a future iteration the frontend
# will send this via an initial JSON message over the WebSocket.
_DEMO_LISTING_CLAIMS = "Luxury 2-bedroom apartment with park view"

# ---------------------------------------------------------------------------
# WebSocket — Live Copilot
# ---------------------------------------------------------------------------


@app.websocket("/ws/live")
async def live_copilot(websocket: WebSocket):
    """WebSocket endpoint for the Live Copilot pipeline.

    Flow per frame:
        1. Receive binary JPEG bytes from the frontend.
        2. Run OpenCV forensics (blur / brightness analysis).
        3. Run Vertex AI Vision analysis (Gemini).
        4. Combine forensic flags + vision observations into
           a single payload.
        5. Pass combined payload to the Agent Reasoner for
           trust evaluation.
        6. Send the final alert JSON back to the frontend.

    Error resilience:
        - Each frame is processed in its own try/except. If Vertex AI
          throws a 429 / 500 / timeout, or OpenCV fails to decode,
          a safe fallback JSON is returned and the loop continues.
        - Synchronous SDK calls are wrapped in asyncio.to_thread()
          so they do not block the async event loop.
    """
    await websocket.accept()
    print("[ws/live] Client connected")

    try:
        while True:
            # ── 1. Receive binary JPEG frame ──────────────────────
            frame_bytes = await websocket.receive_bytes()

            try:
                # ── 2. OpenCV forensics (sync → thread pool) ─────
                forensics = await asyncio.to_thread(
                    analyze_live_frame, frame_bytes
                )

                # ── 3. Vertex AI Vision (sync → thread pool) ─────
                vision_data = await asyncio.to_thread(
                    analyze_frame, frame_bytes
                )

                # ── 4. Combine forensic flags + vision data ──────
                combined_payload = {
                    **vision_data,
                    "forensics": {
                        "blur_score": forensics.get("blur_score", 0),
                        "brightness": forensics.get("brightness", 0),
                    },
                }

                # Merge forensic flags into the suspicious_elements
                # list so the reasoner sees everything in one place
                forensic_flags = forensics.get("suspicious_flags", [])
                vision_suspicious = vision_data.get("suspicious_elements", [])
                combined_payload["suspicious_elements"] = (
                    vision_suspicious + forensic_flags
                )

                # ── 5. Agent Reasoner (sync → thread pool) ───────
                alert = await asyncio.to_thread(
                    evaluate_trust,
                    combined_payload,
                    _DEMO_LISTING_CLAIMS,
                )

                # ── 6. Send result back to frontend ──────────────
                await websocket.send_json(alert)

            except Exception as frame_exc:
                # Per-frame error — do NOT close the WebSocket
                print(f"[ws/live] Frame error: {frame_exc}")
                traceback.print_exc()
                await websocket.send_json(_FALLBACK_ALERT)

    except WebSocketDisconnect:
        print("[ws/live] Client disconnected")
    except Exception as exc:
        print(f"[ws/live] Unexpected error: {exc}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check():
    """Simple health-check endpoint."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point — allows `python main.py` as well as `uvicorn main:app`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
