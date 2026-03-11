# TrustKit AI

**Real-time voice-and-vision AI copilot for rental property tours.** TrustKit acts as your personal fraud investigator, watching virtual tours live alongside you and chatting over a full-duplex voice connection to flag inconsistencies between what is shown on screen and what the listing promises.

---

## Key Features

1. **Live Copilot (WebRTC & WebSockets)** 
   - Streams your webcam feed live to the backend at optimized framerates.
   - Run simultaneous OpenCV forensic analysis (blur, lighting anomalies) and Vertex AI Vision inference.
   - The AI agent dynamically interrupts and warns you if it spots red flags.
2. **Deep Scan Voice Agent (Full-Duplex Conversational AI)**
   - Speak naturally to the AI during the post-tour summary using the Web Audio API and Google Cloud TTS. 
   - Real-time client-side transcription (Web Speech API) alongside high-fidelity TTS audio playback (en-US-Journey-F).
   - Interrupt the AI mid-sentence just like a real phone call.
3. **Auto-Zillow Verification**
   - Automatically scrapes real estate platforms (Zillow, Redfin) using the provided address to corroborate facts like price, square footage, and property amenities.
4. **Agent Reasoner Pipeline**
   - Combines the user’s claims, the Zillow external facts, and the live vision analysis into a single unified trust score and assessment via Gemini 2.5 Flash.

---

## Prerequisites

Make sure the following are installed on your machine before getting started:

| Tool | Version | Check |
|------|---------|-------|
| **Node.js** | 18+ | `node -v` |
| **Python** | 3.10+ | `python --version` |

---

## Backend Setup (FastAPI & Google Cloud)

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a Python virtual environment
python -m venv venv

# macOS / Linux:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env file
echo "GEMINI_API_KEY=your_key_here" > .env
```
*(Note: For Google Vertex AI Vision and Cloud TTS, you must have `gcloud` CLI installed, run `gcloud auth application-default login`, and ensure the necessary APIs are enabled on your GCP project space).*

```bash
# 5. Start the server
python main.py
```

The API will be live at **http://localhost:8000** and interactive docs at **http://localhost:8000/docs**.

---

## Frontend Setup (Vite + React)

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install dependencies
npm install

# 3. Start the Vite dev server
npm run dev
```

The UI will be live at **http://localhost:5173**.

---

## Project Structure & Architecture

```
trustkit-ai/
├── frontend/          # Vite + React (TypeScript) + Tailwind CSS
│   └── src/
│       ├── App.tsx
│       └── components/
│           ├── LiveCopilot.tsx      # WebSocket frame streaming & Alert Panel
│           ├── DeepScan.tsx         # File upload & Full-duplex voice chat
│           └── AlertPanel.tsx       # UI for trust score & AI warnings
├── backend/           # FastAPI + Python
│   ├── main.py        # Async WebSocket router (ws/live, ws/voice)
│   ├── requirements.txt
│   ├── routes/
│   │   └── deep_scan.py    # Legacy file-post endpoint
│   ├── modules/
│   │   ├── frame_extractor.py       # Converts videos/streams to frames
│   │   ├── vision_analyzer.py       # Vertex AI Gemini Vision pipeline
│   │   ├── metadata_analyzer.py     # Live OpenCV forensic scoring
│   │   ├── agent_reasoner.py        # Trust score and alert generation
│   │   ├── tts_engine.py            # Google Cloud Text-to-Speech integration
│   │   ├── listing_scraper.py       # Zillow/Redfin auto-scraper
│   │   └── voice_agent.py           # Gemini 2.5 real-time voice chat pipeline
│   └── .env
└── ARCHITECTURE.md    # Detailed system architecture notes
```