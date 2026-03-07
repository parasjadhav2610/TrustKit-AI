# TrustKit AI — Hackathon Build Plan

## Project

**TrustKit AI — Live Copilot for Rental Property Tours**

TrustKit is a real-time voice-and-vision AI agent that watches a virtual property tour and flags inconsistencies between what is shown and what the listing promises.

The system also includes a **Deep Scan forensic analyzer** for prerecorded media sent via WhatsApp, email, or messaging platforms.

---

# 1. Problem

Rental scams and misleading property listings are extremely common, especially for:
- international students
- remote renters
- first-time apartment seekers

Users often attend **virtual tours or receive prerecorded videos** but cannot verify whether the media is:
- authentic
- recent
- actually from the claimed property

TrustKit solves this by acting as an **AI copilot during virtual tours**.

---

# 2. Core Features

## 1. Live Copilot (Primary Feature)

TrustKit observes a **live virtual tour stream** and analyzes frames in real time.

It compares:
- listing claims
- visual observations
- contextual inconsistencies

Then generates **real-time warnings**.

Example:
> "The listing claims a park-facing view, but the live camera currently shows a brick wall."

---

## 2. Deep Scan (Secondary Feature)

If a landlord sends a prerecorded video instead of doing a live tour, the user can upload it to TrustKit.

TrustKit performs **media forensics analysis** including:
- metadata inspection
- codec analysis
- encoding traces
- frame extraction

This helps detect **old, reused, or manipulated media**.

---

# 3. Architecture Overview

        Frontend (Vite / React)
                │
                │ WebSocket
                ▼
        Backend (FastAPI)
                │
         ┌──────┼─────────┐
         ▼      ▼         ▼
       Frame   Vision     Agent
      Extract Analyzer   Reasoner
                │
                ▼
        Google AI SDK
    (Gemini Vision / Agent)

Two pipelines exist:

### Live Pipeline
Real-time stream processing via WebSocket.

### Deep Scan Pipeline
File upload analysis via REST API.

---

# 4. Tech Stack

## Frontend
- Vite / React (TypeScript)
- Tailwind CSS
- WebRTC / getDisplayMedia() / getUserMedia()
- WebSocket streaming

## Backend
- Python
- FastAPI
- WebSocket server
- OpenCV / FFmpeg

## AI Layer
Using **Google Hackathon SDK**

Potential tools:
- Gemini Vision
- Gemini Agents
- Google AI SDK
- Antigravity AI development tools
- Cursor AI coding assistant

---

# 5. Repository Structure

trustkit-ai/
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       └── components/
│           ├── LiveCopilot.tsx
│           ├── DeepScan.tsx
│           └── AlertPanel.tsx
├── backend/
│   ├── main.py
│   ├── routes/
│   │   └── deep_scan.py
│   ├── modules/
│   │   ├── frame_extractor.py
│   │   ├── vision_analyzer.py
│   │   ├── metadata_analyzer.py
│   │   ├── agent_reasoner.py
│   │   └── tts_engine.py
│   └── utils/
│       └── helpers.py
├── sample_videos/
├── docs/
└── TRUSTKIT_HACKATHON_PLAN.md

---

# 6. Backend Modules

## frame_extractor.py
Responsible for extracting frames from:
- live video streams
- uploaded videos

Functions:
`extract_from_stream(buffer)`
`extract_from_file(video_path)`

Libraries:
- OpenCV
- FFmpeg

---

## vision_analyzer.py
Analyzes a single frame using **Gemini Vision**.

Example Output:
`{ "room_type": "living room", "objects": ["sofa","lamp","window"], "view": "brick wall", "condition": "good" }`

---

## metadata_analyzer.py
Deep Scan forensic module.

Analyzes:
- creation timestamps
- codecs
- encoding traces
- potential editing indicators

Tools:
- exiftool
- ffprobe
- python metadata parsing

Example Output:
`{ "created": "2019", "codec": "H264", "re_encoded": true }`

---

## agent_reasoner.py
Combines:
- listing claims
- vision analysis
- previous observations

Example Output:
`{ "alert": true, "message": "Listing claimed park view but camera shows brick wall", "trust_score": 64 }`

---

## tts_engine.py
Converts warnings into voice output.

Example: "Warning: The view does not match the listing description."

Libraries:
- Google TTS
- Web Speech API

---

# 7. Backend Endpoints

## WebSocket
Primary Live Copilot channel.

`/ws/live`

Flow:
`frontend stream ↓ frame extraction ↓ vision analysis ↓ agent reasoning ↓ alerts sent back to frontend`

---

## REST API
Used for Deep Scan.

`POST /deep-scan`

Flow:
`upload video ↓ extract frames ↓ metadata analysis ↓ agent reasoning ↓ return forensic report`

---

# 8. Frontend UI

Two tabs:
- Live Copilot
- Deep Scan

### Live Copilot Interface
Components:
- Start Live Copilot Button
- Listing Details Input
- Live Alerts Panel
- Trust Score Indicator

Example display:
`Live Analysis Active`
`Trust Score: 72%`
`⚠ Warning: Camera view inconsistent with listing description`

---

### Deep Scan Interface
Upload Video → Analyze

Example result:
`Media Analysis Report`
`Video creation date: 2019`
`Codec: H264`
`Re-encoded: Yes`
`Trust Score: 61%`

---

# 9. Team Responsibilities

## Cybersecurity Engineer
- metadata analyzer
- frame extraction
- Deep Scan pipeline

## AI Engineers (x2)
- Gemini Vision integration
- scene analysis
- agent reasoning logic
- trust scoring

## Optional / Shared Roles
- Frontend integration (Vite/React UI + WebSockets)
- Demo engineer → presentation + pitch

---

# 10. Development Plan

Phase 1 — Skeleton Setup (FastAPI & Vite/React)
Phase 2 — Mock Pipeline
Phase 3 — Deep Scan Module
Phase 4 — Google SDK Integration

---

# 11. Demo Plan

1. Open TrustKit UI
2. Start Live Copilot
3. Simulate virtual tour via webcam
4. AI produces warning overlay
5. Switch to Deep Scan tab
6. Upload prerecorded video
7. Run Deep Scan analysis

---

# 12. Key Innovation

TrustKit combines:
- real-time AI agents
- vision analysis
- media forensics
- scam detection

This creates a **trust layer for online housing transactions**.

---

# 13. Future Scope

- Zillow integration
- WhatsApp media scanning
- browser extension
- landlord verification
- scam reporting network

---

# 14. Hackathon Goal

Deliver a working **Live AI Copilot prototype** capable of:
- observing a live tour via browser webcam
- detecting inconsistencies
- warning users in real time