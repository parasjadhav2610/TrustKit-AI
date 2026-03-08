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

from modules.tts_engine import generate_warning_audio

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


from starlette.websockets import WebSocketState
import json

@app.websocket("/ws/live")
async def live_copilot(websocket: WebSocket):
    """WebSocket endpoint for the Live Copilot pipeline and Two-Way Chat.

    Flow per frame:
        1. Receive binary JPEG frame data over WebSocket,
           OR sends chat messages (text/json).
        2. If binary: Backend analyzes frames with Vertex AI and sends an alert JSON back.
        3. If text: Backend treats it as a post-call chat message,
           and uses the conversational agent to reply.
           
    Error resilience:
        - Each frame is processed in its own try/except. If Vertex AI
          throws a 429 / 500 / timeout, or OpenCV fails to decode,
          a safe fallback JSON is returned and the loop continues.
        - Synchronous SDK calls are wrapped in asyncio.to_thread()
          so they do not block the async event loop.
    """
    await websocket.accept()
    print("[ws/live] Client connected")

    # To store contextual assessment for post-call chat
    last_assessment = {}
    
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            # Receive any type of message
            message = await websocket.receive()
            
            if "bytes" in message:
                # ── 1. Receive binary JPEG frame ──────────────────────
                frame_bytes = message["bytes"]

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

                    # Store it for the chat context later
                    last_assessment = alert

                    # ── Audio Pipeline ──
                    if alert.get("alert"):
                        alert["audio_data"] = await asyncio.to_thread(
                            generate_warning_audio, alert
                        )

                    # ── 6. Send result back to frontend ──────────────
                    await websocket.send_json(alert)

                except Exception as frame_exc:
                    # Per-frame error — do NOT close the WebSocket
                    print(f"[ws/live] Frame error: {frame_exc}")
                    traceback.print_exc()
                    await websocket.send_json(_FALLBACK_ALERT)

            elif "text" in message:
                # --- Two-Way Chat Pipeline (Post-call or in-call) ---
                text_data = message["text"]
                try:
                    payload = json.loads(text_data)
                    user_message = payload.get("text", "")
                    
                    if user_message:
                        from modules.tts_engine import generate_chat_response, generate_warning_audio
                        
                        # Use Gemini to generate conversational response based on the last assessment
                        text_response = await asyncio.to_thread(
                            generate_chat_response, user_message, last_assessment
                        )
                        
                        # Generate audio from the response text
                        audio_base64 = await asyncio.to_thread(
                            generate_warning_audio, text_response
                        )
                        
                        response_payload = {
                            "type": "chat_reply",
                            "message": text_response,
                            "audio_data": audio_base64
                        }
                        await websocket.send_json(response_payload)
                except json.JSONDecodeError:
                    print("Received text that was not valid JSON.")
                    
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
