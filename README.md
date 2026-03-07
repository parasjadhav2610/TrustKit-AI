# TrustKit AI

**Real-time voice-and-vision AI copilot for rental property tours.** TrustKit watches a virtual tour (live or prerecorded) and flags inconsistencies between what is shown and what the listing promises.

---

## Prerequisites

Make sure the following are installed on your machine before getting started:

| Tool | Version | Check |
|------|---------|-------|
| **Node.js** | 18+ | `node -v` |
| **Python** | 3.9+ | `python --version` |
| **FFmpeg** | any | `ffmpeg -version` |

---

## Backend Setup (FastAPI)

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create a Python virtual environment
python -m venv venv

# 3. Activate the virtual environment
# macOS / Linux:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create a .env file for your API key
echo "GEMINI_API_KEY=your_key_here" > .env

# 6. Start the server
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

## Project Structure

```
trustkit-ai/
├── frontend/          # Vite + React (TypeScript) + Tailwind CSS
│   └── src/
│       ├── App.tsx
│       └── components/
│           ├── LiveCopilot.tsx
│           ├── DeepScan.tsx
│           └── AlertPanel.tsx
├── backend/           # FastAPI + Python
│   ├── main.py
│   ├── requirements.txt
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
└── TRUSTKIT_HACKATHON_PLAN.md
```