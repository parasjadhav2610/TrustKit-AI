/**
 * DeepScan — Upload a prerecorded video for forensic analysis.
 *
 * Sends the file via POST to http://localhost:8000/deep-scan and
 * renders the metadata, vision analysis, and trust assessment
 * returned by the backend.
 */

import { useState, useRef, useEffect, type ChangeEvent, type FormEvent } from "react";

const API_URL = "http://localhost:8000/deep-scan";
const WS_URL = "ws://localhost:8000/ws/chat";

interface Metadata {
    created: string;
    codec: string;
    re_encoded: boolean;
}

interface VisionResult {
    room_type: string;
    objects: string[];
    view: string;
    condition: string;
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
    metadata: Metadata;
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

    const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
        setFile(e.target.files?.[0] ?? null);
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

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        if (!file) return;

        setLoading(true);
        setError(null);
        setChatHistory([]);
        wsRef.current?.close();

        try {
            const body = new FormData();
            body.append("file", file);
            if (address.trim()) {
                body.append("address", address.trim());
            }

            const res = await fetch(API_URL, { method: "POST", body });

            if (!res.ok) throw new Error(`Server responded ${res.status}`);

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
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setLoading(false);
        }
    };
    
    // Cleanup WebSocket on unmount
    useEffect(() => {
        return () => wsRef.current?.close();
    }, []);

    return (
        <div className="space-y-6">
            <div>
                <h2 className="text-2xl font-bold text-white">Deep Scan</h2>
                <p className="mt-1 text-sm text-slate-400">
                    Upload a prerecorded property tour video for forensic analysis.
                </p>
            </div>

            {/* ── Upload Form ────────────────────────────────────── */}
            <form
                onSubmit={handleSubmit}
                className="space-y-4 rounded-xl border border-slate-700 bg-slate-800/50 p-5"
            >
                <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">
                        Property Address (optional — for Zillow comparison)
                    </label>
                    <input
                        type="text"
                        value={address}
                        onChange={(e) => setAddress(e.target.value)}
                        placeholder="e.g. 123 Main St, New York, NY 10001"
                        className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
                    />
                </div>
                <div className="flex flex-wrap items-center gap-4">
                    <label className="flex-1">
                        <input
                            type="file"
                            accept="video/*"
                            onChange={handleFileChange}
                            className="block w-full text-sm text-slate-300 file:mr-4 file:cursor-pointer file:rounded-lg file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-indigo-500"
                        />
                    </label>

                    <button
                        type="submit"
                        disabled={!file || loading}
                        className="cursor-pointer rounded-lg bg-indigo-600 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                        {loading ? "Analysing…" : "Analyse"}
                    </button>
                </div>
            </form>

            {error && (
                <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error}
                </p>
            )}

            {/* ── Report Card ────────────────────────────────────── */}
            {report && (
                <div className="grid gap-6 lg:grid-cols-2">
                    <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-6 space-y-6">
                        <h3 className="text-lg font-semibold text-white">
                            Media Analysis Report
                        </h3>

                        {/* Trust Score */}
                        <div className="text-center">
                            <p className="text-sm font-medium uppercase tracking-wider text-slate-400">
                                Trust Score
                            </p>
                            <p
                                className={`mt-1 text-5xl font-bold ${trustColor(
                                    report.assessment.trust_score
                                )}`}
                            >
                                {report.assessment.trust_score}%
                            </p>
                        </div>

                        {/* Metadata grid */}
                        <div className="grid gap-4 sm:grid-cols-3">
                            <InfoCard label="Creation Date" value={report.metadata.created} />
                            <InfoCard label="Codec" value={report.metadata.codec} />
                            <InfoCard
                                label="Re-encoded"
                                value={report.metadata.re_encoded ? "Yes ⚠" : "No"}
                                warn={report.metadata.re_encoded}
                            />
                        </div>

                        {/* Assessment message */}
                        {report.assessment.alert && (
                            <div className="flex items-start gap-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3">
                                <span className="mt-0.5 text-lg text-red-400">⚠</span>
                                <span className="text-sm text-slate-200">
                                    {report.assessment.message}
                                </span>
                            </div>
                        )}

                        {/* Vision analysis for each frame */}
                        <div>
                            <h4 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                                Frame Analysis
                            </h4>
                            <div className="grid gap-4 sm:grid-cols-1">
                                {report.vision_analysis.slice(0, 2).map((v, i) => (
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
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                    
                    {/* ── Chat UI ──────────────────────────────────────── */}
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
                                className={`flex items-center justify-center rounded-lg px-3 py-2 text-sm font-semibold transition ${
                                    isListening ? 'bg-red-500 text-white hover:bg-red-400 animate-pulse' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
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

                {/* ── Zillow Comparison Summary ───────────────────── */}
                {report.listing_comparison && (
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
