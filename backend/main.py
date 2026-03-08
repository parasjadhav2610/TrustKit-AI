"""TrustKit AI — FastAPI Backend Entry Point.

Initializes the FastAPI application with:
- CORS middleware (all origins allowed for local hackathon testing)
- WebSocket endpoint at /ws/live for the Live Copilot pipeline
- REST router for the Deep Scan pipeline (POST /deep-scan)
"""

import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from routes.deep_scan import router as deep_scan_router
from modules.frame_extractor import extract_from_stream
from modules.vision_analyzer import analyze_frame
from modules.agent_reasoner import reason

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
    version="0.1.0",
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
# WebSocket — Live Copilot
# ---------------------------------------------------------------------------


from starlette.websockets import WebSocketState
import json

@app.websocket("/ws/live")
async def live_copilot(websocket: WebSocket):
    """WebSocket endpoint for the Live Copilot pipeline and Two-Way Chat.

    Flow:
        1. Frontend streams video frame data (binary) over WebSocket,
           OR sends chat messages (text/json).
        2. If binary: Backend analyzes frames and sends an alert JSON back.
        3. If text: Backend treats it as a post-call chat message,
           and uses the conversational agent to reply.
    """
    await websocket.accept()
    # To store contextual assessment for post-call chat
    last_assessment = {}
    
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            # Receive any type of message
            message = await websocket.receive()
            
            if "bytes" in message:
                # --- Video Stream Pipeline ---
                data = message["bytes"]
                frames = extract_from_stream(data)
                vision_result = analyze_frame(frames[0]) if frames else {}
                alert = reason(vision_data=vision_result)
                
                # Store it for the chat context later
                last_assessment = alert
                
                # --- Audio Pipeline ---
                if alert.get("alert"):
                    alert["audio_data"] = generate_warning_audio(alert)

                await websocket.send_text(json.dumps(alert))
                
            elif "text" in message:
                # --- Two-Way Chat Pipeline (Post-call or in-call) ---
                text_data = message["text"]
                try:
                    payload = json.loads(text_data)
                    user_message = payload.get("text", "")
                    
                    if user_message:
                        from modules.tts_engine import generate_chat_response, generate_warning_audio
                        
                        # Use Gemini to generate conversational response based on the last assessment
                        text_response = generate_chat_response(user_message, context=last_assessment)
                        
                        # Generate audio from the response text
                        audio_base64 = generate_warning_audio(text_response)
                        
                        response_payload = {
                            "type": "chat_reply",
                            "message": text_response,
                            "audio_data": audio_base64
                        }
                        await websocket.send_text(json.dumps(response_payload))
                except json.JSONDecodeError:
                    print("Received text that was not valid JSON.")
                    
    except WebSocketDisconnect:
        print("Client disconnected from /ws/live")


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
