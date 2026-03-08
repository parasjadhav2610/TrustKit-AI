/**
 * DeepScan — Upload a prerecorded video/image for forensic analysis.
 *
 * Features:
 * - Drag-and-drop OR file picker to upload media
 * - Listing details input (address + description)
 * - Animated progress bar during analysis
 * - Forensic + AI analysis report
 */

import { useState, useRef, useEffect, type ChangeEvent, type FormEvent, type DragEvent } from "react";


const API_URL = "http://localhost:8000/deep-scan";
const WS_URL = "ws://localhost:8000/ws/chat";

interface Forensics {
    blur_score: number;
    brightness: number;
    suspicious_flags: string[];
    valid: boolean;
}

interface VisionResult {
    room_type: string;
    objects: string[];
    view: string;
    condition: string;
    suspicious_elements?: string[];
}

interface Assessment {
    alert: boolean;
    message: string;
    trust_score: number;
}

interface ListingComparison {
    address: string;
    price: string;
    beds: string;
    baths: string;
    sqft: string;
    description: string;
    photo_count: number;
    source: string;
    comparison_summary: string;
    error?: string;
}

interface ScanReport {
    filename: string;
    listing_claims: string;
    forensics: Forensics[];
    vision_analysis: VisionResult[];
    assessment: Assessment;
    listing_comparison?: ListingComparison;
}

interface ChatMessage {
    role: "user" | "agent";
    text: string;
    audioBase64?: string;
}

function trustColor(score: number): string {
    if (score >= 75) return "text-emerald-400";
    if (score >= 50) return "text-amber-400";
    return "text-red-400";
}

function trustBg(score: number): string {
    if (score >= 75) return "bg-emerald-500/20 border-emerald-500/40";
    if (score >= 50) return "bg-amber-500/20 border-amber-500/40";
    return "bg-red-500/20 border-red-500/40";
}

// Progress stage labels
const PROGRESS_STAGES = [
    "Uploading file…",
    "Extracting frames…",
    "Running forensic analysis…",
    "Running AI vision analysis…",
    "Evaluating trust score…",
    "Generating report…",
];

export default function DeepScan() {
    const [file, setFile] = useState<File | null>(null);
    const [address, setAddress] = useState("");
    const [report, setReport] = useState<ScanReport | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // --- Chat State ---
    const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
    const [chatInput, setChatInput] = useState("");
    const [chatStatus, setChatStatus] = useState("Disconnected");
    const wsRef = useRef<WebSocket | null>(null);

    // --- Voice Recognition State ---
    const [isListening, setIsListening] = useState(false);
    const recognitionRef = useRef<any>(null);

    useEffect(() => {
        // Initialize SpeechRecognition once
        const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = true;
            recognition.lang = 'en-US';

            recognition.onstart = () => setIsListening(true);
            recognition.onend = () => setIsListening(false);
            recognition.onerror = (e: any) => {
                console.error("Speech recognition error", e);
                setIsListening(false);
            };

            recognition.onresult = (event: any) => {
                const transcript = Array.from(event.results)
                    .map((result: any) => result[0].transcript)
                    .join('');
                setChatInput(transcript);
            };

            recognitionRef.current = recognition;
        }
    }, []);

    const toggleListening = () => {
        if (!recognitionRef.current) {
            alert("Your browser does not support Speech Recognition.");
            return;
        }

        if (isListening) {
            recognitionRef.current.stop();
        } else {
            recognitionRef.current.start();
        }
    };

    // Listing details
    const [listingAddress, setListingAddress] = useState("");
    const [listingDescription, setListingDescription] = useState("");

    // Progress tracking
    const [progress, setProgress] = useState(0);
    const [progressLabel, setProgressLabel] = useState("");

    // Drag-and-drop state
    const [isDragging, setIsDragging] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Abort controller for cancelling analysis
    const abortRef = useRef<AbortController | null>(null);

    // ── File handling ─────────────────────────────────────────────
    const handleFile = (selectedFile: File) => {
        setFile(selectedFile);
        setReport(null);
        setError(null);
        setChatHistory([]); // Clear past chat history
        wsRef.current?.close(); // Close any old websocket
        if (isListening) recognitionRef.current?.stop();
    };

    const handleChatSubmit = (e: FormEvent) => {
        e.preventDefault();
        const ws = wsRef.current;
        if (!ws || chatInput.trim() === "") return;

        if (isListening) recognitionRef.current?.stop();

        // Push user message to UI immediately
        setChatHistory((prev) => [...prev, { role: "user", text: chatInput }]);

        ws.send(JSON.stringify({ text: chatInput }));
        setChatInput("");
    };

    const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
        const f = e.target.files?.[0];
        if (f) handleFile(f);
    };

    // ── Drag-and-drop handlers ────────────────────────────────────
    const handleDragEnter = (e: DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(true);
    };

    const handleDragLeave = (e: DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);
    };

    const handleDragOver = (e: DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
    };

    const handleDrop = (e: DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);

        const droppedFile = e.dataTransfer.files?.[0];
        if (droppedFile) {
            handleFile(droppedFile);
        }
    };

    // ── Simulated progress (since server doesn't stream progress) ─
    const simulateProgress = () => {
        setProgress(0);
        setProgressLabel(PROGRESS_STAGES[0]);

        let stage = 0;
        const interval = setInterval(() => {
            stage++;
            if (stage >= PROGRESS_STAGES.length) {
                clearInterval(interval);
                return;
            }
            const pct = Math.min(90, Math.round((stage / PROGRESS_STAGES.length) * 100));
            setProgress(pct);
            setProgressLabel(PROGRESS_STAGES[stage]);
        }, 2000);

        return interval;
    };

    // ── Submit ────────────────────────────────────────────────────
    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        if (!file) return;

        // Create a new AbortController for this request
        const controller = new AbortController();
        abortRef.current = controller;

        setLoading(true);
        setError(null);
        setReport(null);

        const progressInterval = simulateProgress();


        try {
            const body = new FormData();
            body.append("file", file);
            body.append("listing_address", listingAddress.trim());
            body.append("listing_description", listingDescription.trim());

            setProgress(10);
            setProgressLabel(PROGRESS_STAGES[0]);


            const res = await fetch(API_URL, {
                method: "POST",
                body,
                signal: controller.signal,
            });

            clearInterval(progressInterval);

            if (!res.ok) throw new Error(`Server responded ${res.status}`);

            setProgress(100);
            setProgressLabel("Complete!");

            const data: ScanReport = await res.json();
            setReport(data);

            // --- CONNECT WEBSOCKET CHAT POST-ANALYSIS ---
            setChatStatus("Connecting...");
            const ws = new WebSocket(WS_URL);
            wsRef.current = ws;

            ws.onopen = () => {
                setChatStatus("Connected");
                // Immediately send the context so the backend can initialize the Gemini prompt
                ws.send(JSON.stringify({
                    type: "init",
                    context: data
                }));
            };

            ws.onmessage = (event) => {
                try {
                    const wsData = JSON.parse(event.data);
                    if (wsData.type === "chat_reply") {
                        setChatHistory((prev) => [...prev, {
                            role: "agent",
                            text: wsData.message,
                            audioBase64: wsData.audio_data
                        }]);

                        // Automatically play the incoming audio response
                        if (wsData.audio_data) {
                            const audio = new Audio(wsData.audio_data);
                            audio.play().catch(console.error);
                        }
                    } else if (wsData.type === "system") {
                        console.log("System:", wsData.message);
                    }
                } catch {
                    console.warn("Failed to parse WS chat message", event.data);
                }
            };

            ws.onerror = () => setChatStatus("WebSocket Error");
            ws.onclose = () => setChatStatus("Disconnected");

        } catch (err) {
            clearInterval(progressInterval);
            if (err instanceof DOMException && err.name === "AbortError") {
                setError(null);
                setProgress(0);
                setProgressLabel("");
            } else {
                setError(err instanceof Error ? err.message : "Unknown error");
            }
        } finally {
            setLoading(false);
            abortRef.current = null;
        }
    };

    // Cleanup WebSocket on unmount
    useEffect(() => {
        return () => wsRef.current?.close();
    }, []);

    // ── Stop analysis ────────────────────────────────────────
    const stopAnalysis = () => {
        abortRef.current?.abort();
    };

    return (
        <div className="space-y-6">
            <div>
                <h2 className="text-2xl font-bold text-white">Deep Scan</h2>
                <p className="mt-1 text-sm text-slate-400">
                    Upload a property tour video or image for forensic analysis.
                </p>
            </div>

            {/* ── Listing Details ──────────────────────────────────── */}
            <div className="space-y-3 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Listing Details
                </h3>
                <input
                    type="text"
                    placeholder="Listing address (e.g., 123 Main St, Apt 4B, NYC)"
                    value={listingAddress}
                    onChange={(e) => setListingAddress(e.target.value)}
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                />
                <textarea
                    placeholder="Paste the listing description or let TrustKit auto-fetch it from Zillow using the address above."
                    value={listingDescription}
                    onChange={(e) => setListingDescription(e.target.value)}
                    rows={3}
                    className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none resize-none"
                />
                <p className="text-xs text-slate-500">
                    Enter the address — TrustKit will automatically look up the listing on Zillow.
                </p>
            </div>

            {/* ── Drop Zone + File Upload ──────────────────────────── */}
            <div
                onDragEnter={handleDragEnter}
                onDragLeave={handleDragLeave}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`relative cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-all duration-200 ${isDragging
                    ? "border-indigo-400 bg-indigo-500/10"
                    : file
                        ? "border-emerald-500/50 bg-emerald-500/5"
                        : "border-slate-600 bg-slate-800/50 hover:border-slate-500 hover:bg-slate-800/80"
                    }`}
            >
                <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/*,image/*"
                    onChange={handleFileChange}
                    className="hidden"
                />

                {isDragging ? (
                    <>
                        <p className="text-3xl mb-2">📂</p>
                        <p className="text-sm font-semibold text-indigo-400">
                            Drop your file here
                        </p>
                    </>
                ) : file ? (
                    <>
                        <p className="text-3xl mb-2">✅</p>
                        <p className="text-sm font-semibold text-emerald-400">
                            {file.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                            {(file.size / (1024 * 1024)).toFixed(1)} MB — Click or drop to replace
                        </p>
                    </>
                ) : (
                    <>
                        <p className="text-3xl mb-2">🎬</p>
                        <p className="text-sm font-semibold text-slate-300">
                            Drag &amp; drop a video or image here
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                            or click to browse files
                        </p>
                    </>
                )}
            </div>

            {/* Analyse / Stop buttons */}
            <div className="flex gap-3">
                <button
                    onClick={handleSubmit as unknown as () => void}
                    disabled={!file || loading}
                    className="flex-1 cursor-pointer rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
                >
                    {loading ? "Analysing…" : "Analyse"}
                </button>
                {loading && (
                    <button
                        onClick={stopAnalysis}
                        className="cursor-pointer rounded-lg bg-red-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-red-500"
                    >
                        Stop
                    </button>
                )}
            </div>

            {/* ── Progress Bar ─────────────────────────────────────── */}
            {loading && (
                <div className="space-y-2 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
                    <div className="flex items-center justify-between">
                        <p className="text-sm text-slate-300">{progressLabel}</p>
                        <p className="text-sm font-semibold text-indigo-400">{progress}%</p>
                    </div>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-700">
                        <div
                            className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-emerald-500 transition-all duration-700 ease-out"
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                </div>
            )}


            {error && (
                <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error}
                </p>
            )}

            {/* ── Report Card ──────────────────────────────────────── */}
            {report && (
                <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-6 space-y-6">
                    <h3 className="text-lg font-semibold text-white">
                        Media Analysis Report
                    </h3>

                    {/* Trust Score */}
                    <div className={`rounded-xl border p-5 text-center ${trustBg(report.assessment.trust_score)}`}>
                        <p className="text-sm font-medium uppercase tracking-wider text-slate-300">
                            Trust Score
                        </p>
                        <p className={`mt-1 text-5xl font-bold ${trustColor(report.assessment.trust_score)}`}>
                            {report.assessment.trust_score}%
                        </p>
                    </div>

                    {/* Listing claims used */}
                    {report.listing_claims && (
                        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
                            <p className="text-xs font-medium uppercase tracking-wider text-slate-500 mb-1">
                                Listing Claims Analyzed
                            </p>
                            <p className="text-sm text-slate-300">{report.listing_claims}</p>
                        </div>
                    )}

                    {/* Assessment message */}
                    {report.assessment.alert && (
                        <div className="flex items-start gap-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3">
                            <span className="mt-0.5 text-lg text-red-400">⚠</span>
                            <span className="text-sm text-slate-200">
                                {report.assessment.message}
                            </span>
                        </div>
                    )}

                    {/* Forensics results */}
                    {report.forensics.length > 0 && (
                        <div>
                            <h4 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                                Forensic Analysis
                            </h4>
                            <div className="grid gap-4 sm:grid-cols-3">
                                <InfoCard
                                    label="Blur Score"
                                    value={String(report.forensics[0].blur_score)}
                                />
                                <InfoCard
                                    label="Brightness"
                                    value={String(report.forensics[0].brightness)}
                                />
                                <InfoCard
                                    label="Flags"
                                    value={
                                        report.forensics[0].suspicious_flags.length > 0
                                            ? report.forensics[0].suspicious_flags.join(", ")
                                            : "None"
                                    }
                                    warn={report.forensics[0].suspicious_flags.length > 0}
                                />
                            </div>
                        </div>
                    )}

                    {/* Vision analysis for each frame */}
                    <div>
                        <h4 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                            Frame Analysis
                        </h4>
                        <div className="grid gap-4 sm:grid-cols-3">
                            {report.vision_analysis.map((v, i) => (
                                <div
                                    key={i}
                                    className="rounded-lg border border-slate-700 bg-slate-900/50 p-4 space-y-2"
                                >
                                    <p className="text-xs font-medium text-slate-500">
                                        Frame {i + 1}
                                    </p>
                                    <p className="text-sm text-slate-200">
                                        <span className="text-slate-400">Room: </span>
                                        {v.room_type}
                                    </p>
                                    <p className="text-sm text-slate-200">
                                        <span className="text-slate-400">View: </span>
                                        {v.view}
                                    </p>
                                    <p className="text-sm text-slate-200">
                                        <span className="text-slate-400">Condition: </span>
                                        {v.condition}
                                    </p>
                                    <p className="text-sm text-slate-200">
                                        <span className="text-slate-400">Objects: </span>
                                        {v.objects.join(", ")}
                                    </p>
                                    {v.suspicious_elements && v.suspicious_elements.length > 0 && (
                                        <p className="text-sm text-red-400">
                                            <span className="text-slate-400">Suspicious: </span>
                                            {v.suspicious_elements.join(", ")}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* ── Chat UI ──────────────────────────────────────── */}
            {report && (
                <div className="flex flex-col rounded-xl border border-slate-700 bg-slate-800/50 p-6">
                    <div className="mb-4">
                        <h3 className="text-lg font-semibold text-white">TrustKit AI Copilot</h3>
                        <p className="text-xs text-slate-400">Status: {chatStatus}</p>
                    </div>

                    <div className="flex-1 overflow-y-auto space-y-4 mb-4" style={{ minHeight: "300px" }}>
                        {chatHistory.length === 0 ? (
                            <p className="text-sm text-slate-500 italic text-center mt-10">Ask a question about the analysis!</p>
                        ) : (
                            chatHistory.map((msg, i) => (
                                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                    <div className={`max-w-[80%] rounded-xl px-4 py-2 ${msg.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-200'}`}>
                                        <p className="text-sm">{msg.text}</p>
                                        {msg.audioBase64 && (
                                            <audio controls src={msg.audioBase64} className="mt-2 h-8 w-full block max-w-[200px]" />
                                        )}
                                    </div>
                                </div>
                            ))
                        )}
                    </div>

                    <form onSubmit={handleChatSubmit} className="flex gap-2">
                        <input
                            type="text"
                            value={chatInput}
                            onChange={(e) => setChatInput(e.target.value)}
                            placeholder={isListening ? "Listening..." : "Ask about the property..."}
                            disabled={chatStatus !== "Connected"}
                            className="flex-1 rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none disabled:opacity-50"
                        />
                        <button
                            type="button"
                            onClick={toggleListening}
                            disabled={chatStatus !== "Connected"}
                            className={`flex items-center justify-center rounded-lg px-3 py-2 text-sm font-semibold transition ${isListening ? 'bg-red-500 text-white hover:bg-red-400 animate-pulse' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                                } disabled:opacity-50`}
                            title="Use voice input"
                        >
                            {isListening ? "⏹" : "🎤"}
                        </button>
                        <button
                            type="submit"
                            disabled={chatStatus !== "Connected" || !chatInput.trim()}
                            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
                        >
                            Send
                        </button>
                    </form>
                </div>
            )}

            {/* ── Zillow Comparison Summary ───────────────────── */}
            {report && report.listing_comparison && (
                <div className="lg:col-span-2 rounded-xl border border-slate-700 bg-slate-800/50 p-6 space-y-4">
                    <h3 className="text-lg font-semibold text-white">📊 Zillow Listing Comparison</h3>

                    {report.listing_comparison.error ? (
                        <p className="text-sm text-amber-400">{report.listing_comparison.error}</p>
                    ) : (
                        <>
                            <div className="grid gap-4 sm:grid-cols-4">
                                <InfoCard label="Address" value={report.listing_comparison.address} />
                                <InfoCard label="Price" value={report.listing_comparison.price} />
                                <InfoCard label="Beds / Baths" value={`${report.listing_comparison.beds} / ${report.listing_comparison.baths}`} />
                                <InfoCard label="Sqft" value={report.listing_comparison.sqft} />
                            </div>

                            <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-5">
                                <h4 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                                    Forensic Comparison Summary
                                </h4>
                                <div className="space-y-1">
                                    {report.listing_comparison.comparison_summary.split('\n').map((line, i) => (
                                        <p key={i} className="text-sm text-slate-300 leading-relaxed">{line}</p>
                                    ))}
                                </div>
                            </div>

                            <p className="text-xs text-slate-500">
                                Source: {report.listing_comparison.source} · {report.listing_comparison.photo_count} listing photos analyzed
                            </p>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}

/* ── Small helper component ───────────────────────────────────── */
function InfoCard({
    label,
    value,
    warn = false,
}: {
    label: string;
    value: string;
    warn?: boolean;
}) {
    return (
        <div
            className={`rounded-lg border p-4 text-center ${warn
                ? "border-amber-500/40 bg-amber-500/10"
                : "border-slate-700 bg-slate-900/50"
                }`}
        >
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                {label}
            </p>
            <p className={`mt-1 text-lg font-semibold ${warn ? "text-amber-400" : "text-slate-200"}`}>
                {value}
            </p>
        </div>
    );
}
