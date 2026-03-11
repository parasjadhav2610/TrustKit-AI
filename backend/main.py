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

from modules.tts_engine import generate_warning_audio, generate_chat_response

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

        processing_task = None
        
        async def process_frame(f_bytes, f_idx, current_claims):
            nonlocal last_assessment
            try:
                # ── 2. OpenCV & Vision IN PARALLEL ──────
                print(f"[ws/live]   → Running forensics & Vision concurrently...")
                forensics_task = asyncio.to_thread(analyze_live_frame, f_bytes)
                vision_task = asyncio.to_thread(analyze_frame, f_bytes)
                
                forensics, vision_data = await asyncio.gather(forensics_task, vision_task)
                
                print(f"[ws/live]   ✓ Forensics: blur={forensics.get('blur_score')}, flags={forensics.get('suspicious_flags')}")
                print(f"[ws/live]   ✓ Vision: room={vision_data.get('room_type')}, condition={vision_data.get('condition')}")

                # ── 4. Combine payload ──────
                combined_payload = {
                    **vision_data,
                    "forensics": {
                        "blur_score": forensics.get("blur_score", 0),
                        "brightness": forensics.get("brightness", 0),
                    },
                }
                combined_payload["suspicious_elements"] = (
                    vision_data.get("suspicious_elements", []) + forensics.get("suspicious_flags", [])
                )

                # ── 5. Agent Reasoner ───────
                print(f"[ws/live]   → Running Agent Reasoner...")
                alert = await asyncio.to_thread(
                    evaluate_trust,
                    combined_payload,
                    current_claims,
                )
                print(f"[ws/live]   ✓ Result: alert={alert.get('alert')}, score={alert.get('trust_score')}")

                last_assessment = alert

                # ── Audio Pipeline ──
                if alert.get("alert"):
                    alert["audio_data"] = await asyncio.to_thread(
                        generate_warning_audio, alert
                    )

                # ── 6. Send result ──────────────
                await websocket.send_json(alert)
                print(f"[ws/live]   ✓ Sent frame #{f_idx} to frontend")

            except WebSocketDisconnect:
                pass
            except Exception as frame_exc:
                print(f"[ws/live]   ❌ Frame #{f_idx} error: {frame_exc}")
                traceback.print_exc()
                try:
                    await websocket.send_json(_FALLBACK_ALERT)
                except Exception:
                    pass

        while True:
            # Receive any type of message
            message = await websocket.receive()
            
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            
            if "bytes" in message:
                if processing_task and not processing_task.done():
                    # Drop frame to prevent queue buildup and keep latency strictly real-time
                    continue
                    
                frame_bytes = message["bytes"]
                frame_count += 1
                print(f"\n[ws/live] ── Frame #{frame_count} ({len(frame_bytes)} bytes) ──")
                
                processing_task = asyncio.create_task(process_frame(frame_bytes, frame_count, listing_claims))


    except WebSocketDisconnect:
        print(f"[ws/live] Client disconnected after {frame_count} frames")
    except Exception as exc:
        print(f"[ws/live] ❌ Unexpected error: {exc}")
        traceback.print_exc()



from modules.voice_agent import stream_voice_chat

@app.websocket("/ws/voice")
async def deepscan_voice(websocket: WebSocket):
    """Full-duplex real-time voice endpoint for Deep Scan."""
    await websocket.accept()
    print("[ws/voice] 🎙️ Voice client connected")
    
    session_context = {}
    chat_history = []
    interrupt_event = asyncio.Event()
    audio_buffer = bytearray()
    
    try:
        while True:
            # Receive either binary audio chunks or JSON text commands
            message = await websocket.receive()
            
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            
            if "bytes" in message:
                audio_buffer.extend(message["bytes"])
                
            elif "text" in message:
                text_data = message["text"]
                try:
                    payload = json.loads(text_data)
                    action = payload.get("action")
                    
                    if payload.get("type") == "init":
                        session_context = payload.get("context", {})
                        chat_history = []
                        await websocket.send_json({"type": "system", "message": "Voice session initialized."})
                        
                    elif action == "interrupt":
                        print("[ws/voice] 🛑 Interrupt received!")
                        interrupt_event.set()
                        
                    elif action == "commit_audio":
                        # User stopped speaking, process the accumulated audio buffer
                        if not audio_buffer:
                            continue
                            
                        # Reset interrupt event for the new generation
                        interrupt_event.clear()
                        
                        audio_bytes = bytes(audio_buffer)
                        audio_buffer.clear() # reset buffer
                        
                        print("[ws/voice] 🧠 Thinking about audio input...")
                        
                        full_agent_response = ""
                        # Stream from vertex natively
                        async for response_chunk in stream_voice_chat(
                            audio_bytes, 
                            session_context, 
                            chat_history, 
                            interrupt_event
                        ):
                            # Send chunk back to frontend (text or audio)
                            await websocket.send_json(response_chunk)
                            if response_chunk.get("message"):
                                full_agent_response += response_chunk["message"]
                        
                        if full_agent_response:
                            chat_history.append({"role": "agent", "content": full_agent_response})
                            
                except json.JSONDecodeError:
                    print("[ws/voice] Invalid JSON received.")
                    
    except WebSocketDisconnect:
        print("[ws/voice] Client disconnected")
    except Exception as exc:
        print(f"[ws/voice] ❌ Unexpected error: {exc}")
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
