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

from routes.deep_scan import router as deep_scan_router
from modules.vision_analyzer import analyze_frame
from modules.metadata_analyzer import analyze_live_frame
from modules.agent_reasoner import evaluate_trust
from modules.listing_scraper import scrape_zillow_listing

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
# REST routers
# ---------------------------------------------------------------------------

app.include_router(deep_scan_router)



# ---------------------------------------------------------------------------
# Safe fallback — sent when any per-frame processing fails
# ---------------------------------------------------------------------------

_FALLBACK_ALERT = {
    "alert": False,
    "message": "Analyzing next frame...",
    "trust_score": 50,
}


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
    print("[ws/live] ✅ Client connected")

    frame_count = 0
    listing_claims = ""

    # To store contextual assessment for post-call chat
    last_assessment = {}
    
    try:
        # ── Wait for the config message (first message is JSON text) ──
        config_raw = await websocket.receive_text()
        try:
            config = json.loads(config_raw)
            address = config.get("listing_address", "").strip()
            description = config.get("listing_description", "").strip()

            # Auto-scrape Zillow if address is provided
            if address:
                print(f"[ws/live] 🔍 Auto-scraping Zillow for: {address}")
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
                    # Append scraped data to user-provided description
                    description = (description + " " + scraped_desc).strip() if description else scraped_desc
                    print(f"[ws/live] ✓ Zillow data found, enriched listing claims")
                else:
                    print(f"[ws/live] ⚠️  Zillow scrape failed: {scraped.get('error', 'unknown')}")

            parts = []
            if address:
                parts.append(f"Address: {address}")
            if description:
                parts.append(description)

            listing_claims = ". ".join(parts) if parts else ""
            print(f"[ws/live] 📋 Listing claims: {listing_claims or '(none provided)'}")
        except json.JSONDecodeError:
            print("[ws/live] ⚠️  First message was not valid JSON config, proceeding without claims")

        while True:
            # Receive any type of message
            message = await websocket.receive()
            
            if "bytes" in message:
                # ── 1. Receive binary JPEG frame ──────────────────────
                frame_bytes = message["bytes"]
                frame_count += 1
                print(f"\n[ws/live] ── Frame #{frame_count} ({len(frame_bytes)} bytes) ──")

                try:
                    # ── 2. OpenCV forensics (sync → thread pool) ─────
                    print(f"[ws/live]   → Running OpenCV forensics...")
                    forensics = await asyncio.to_thread(
                        analyze_live_frame, frame_bytes
                    )
                    print(f"[ws/live]   ✓ Forensics: blur={forensics.get('blur_score')}, "
                          f"brightness={forensics.get('brightness')}, "
                          f"flags={forensics.get('suspicious_flags')}")

                    # ── 3. Vertex AI Vision (sync → thread pool) ─────
                    print(f"[ws/live]   → Running Vertex AI Vision...")
                    vision_data = await asyncio.to_thread(
                        analyze_frame, frame_bytes
                    )
                    print(f"[ws/live]   ✓ Vision: room={vision_data.get('room_type')}, "
                          f"view={vision_data.get('view')}, "
                          f"condition={vision_data.get('condition')}")

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
                    print(f"[ws/live]   → Running Agent Reasoner...")
                    alert = await asyncio.to_thread(
                        evaluate_trust,
                        combined_payload,
                        listing_claims,
                    )
                    print(f"[ws/live]   ✓ Result: alert={alert.get('alert')}, "
                          f"score={alert.get('trust_score')}, "
                          f"msg={alert.get('message')}")

                    # Store it for the chat context later
                    last_assessment = alert

                    # ── Audio Pipeline ──
                    if alert.get("alert"):
                        alert["audio_data"] = await asyncio.to_thread(
                            generate_warning_audio, alert
                        )

                    # ── 6. Send result back to frontend ──────────────
                    await websocket.send_json(alert)
                    print(f"[ws/live]   ✓ Sent to frontend")

                except Exception as frame_exc:
                    # Per-frame error — do NOT close the WebSocket
                    print(f"[ws/live]   ❌ Frame #{frame_count} error: {frame_exc}")
                    traceback.print_exc()
                    await websocket.send_json(_FALLBACK_ALERT)
                    print(f"[ws/live]   → Sent fallback JSON, continuing...")

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
        print(f"[ws/live] Client disconnected after {frame_count} frames")
    except Exception as exc:
        print(f"[ws/live] ❌ Unexpected error: {exc}")
        traceback.print_exc()

@app.websocket("/ws/chat")
async def deepscan_chat(websocket: WebSocket):
    """Dedicated WebSocket endpoint for DeepScan post-analysis two-way chat.
    
    Flow:
        1. DeepScan completes the POST analysis.
        2. Frontend opens this websocket and sends a JSON payload:
           {"type": "init", "context": <assessment_dict>}
        3. Backend initializes a conversational session with that context.
        4. User sends subsequent text queries: {"text": "What about the view?"}
        5. Backend responds with the text phrase and audio output.
    """
    await websocket.accept()
    print("[ws/chat] Client connected")
    
    # Context state
    session_context = {}
    chat_history = []
    
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            message = await websocket.receive_text()
            
            try:
                payload = json.loads(message)
                
                if payload.get("type") == "init":
                    # Initial connection payload containing the full report context
                    session_context = payload.get("context", {})
                    chat_history.append({"role": "system", "content": f"Tour context: {json.dumps(session_context)}"})
                    await websocket.send_json({"type": "system", "message": "Chat session initialized."})
                    
                elif "text" in payload:
                    user_message = payload["text"]
                    
                    if user_message:
                        # Append to our local history for Context (if we were using a full ChatSession we'd pass it here)
                        # Instead, we rebuild the whole string so the _generate_chat_response sees the history
                        chat_history.append({"role": "user", "content": user_message})
                        
                        # Build a mock conversational prompt out of the history
                        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in chat_history])
                        
                        from modules.tts_engine import generate_chat_response, generate_warning_audio
                        text_response = await asyncio.to_thread(
                            generate_chat_response, history_text, session_context
                        )
                        
                        # Keep history
                        chat_history.append({"role": "agent", "content": text_response})
                        
                        # Convert to speech
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
                print("[ws/chat] Received invalid JSON.")
                
    except WebSocketDisconnect:
        print("[ws/chat] Client disconnected")
    except Exception as exc:
        print(f"[ws/chat] Unexpected error: {exc}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Health check & REST Routes
# ---------------------------------------------------------------------------

from routes.deep_scan import router as deep_scan_router
app.include_router(deep_scan_router)

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
