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


@app.websocket("/ws/live")
async def live_copilot(websocket: WebSocket):
    """WebSocket endpoint for the Live Copilot pipeline.

    Flow:
        1. Frontend streams video frame data (binary) over WebSocket.
        2. Backend extracts frames from the incoming buffer.
        3. Each frame is analysed by the vision analyser.
        4. The agent reasoner combines vision data with listing claims.
        5. An alert JSON is sent back to the frontend.

    The current implementation uses **mock data** so the frontend team
    can develop the UI immediately.
    """
    await websocket.accept()
    try:
        while True:
            # Receive binary frame data from the frontend
            data = await websocket.receive_bytes()

            # --- Mock pipeline ---
            frames = extract_from_stream(data)
            vision_result = analyze_frame(frames[0]) if frames else {}
            alert = reason(vision_data=vision_result)

            await websocket.send_text(json.dumps(alert))
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
