/**
 * DeepScan — Upload a prerecorded video/image for forensic analysis.
 *
 * Features:
 * - Drag-and-drop OR file picker to upload media
 * - Listing details input (address + description)
 * - Animated progress bar during analysis
 * - Forensic + AI analysis report
 * - Full-Duplex Voice Copilot (Real-time WebM audio streaming)
 */

import { useState, useRef, useEffect, useCallback, type ChangeEvent, type FormEvent, type DragEvent } from "react";

const API_URL = "http://localhost:8000/deep-scan";
const WS_VOICE_URL = "ws://localhost:8000/ws/voice";

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

    const [report, setReport] = useState<ScanReport | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // --- Voice Call State ---
    const [voiceStatus, setVoiceStatus] = useState("Disconnected");
    const [isListening, setIsListening] = useState(false);
    const [isAgentSpeaking, setIsAgentSpeaking] = useState(false);
    const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);

    // Listing details
    const [listingStreet, setListingStreet] = useState("");
    const [listingUnit, setListingUnit] = useState("");
    const [listingLocality, setListingLocality] = useState("");
    const [listingDescription, setListingDescription] = useState("");

    // Progress tracking
    const [progress, setProgress] = useState(0);
    const [progressLabel, setProgressLabel] = useState("");

    // Drag-and-drop state
    const [isDragging, setIsDragging] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Abort controller
    const abortRef = useRef<AbortController | null>(null);

    // --- Voice Refs & Logic ---
    const wsVoiceRef = useRef<WebSocket | null>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const streamRef = useRef<MediaStream | null>(null);

    const audioQueueRef = useRef<HTMLAudioElement[]>([]);
    const currentAudioRef = useRef<HTMLAudioElement | null>(null);

    // VAD (Voice Activity Detection) Refs
    const silenceTimerRef = useRef<number | null>(null);
    const audioContextRef = useRef<AudioContext | null>(null);
    const analyserRef = useRef<AnalyserNode | null>(null);
    const isSpeakingRef = useRef<boolean>(false);
    const requestAnimationFrameRef = useRef<number | null>(null);
    const speechRecognitionRef = useRef<any>(null);
    const transcriptRef = useRef<string>("");

    const playNextAudio = useCallback(() => {
        if (audioQueueRef.current.length === 0) {
            setIsAgentSpeaking(false);
            return;
        }

        setIsAgentSpeaking(true);
        const nextAudio = audioQueueRef.current.shift();
        if (nextAudio) {
            currentAudioRef.current = nextAudio;
            nextAudio.onended = () => {
                currentAudioRef.current = null;
                playNextAudio();
            };
            nextAudio.play().catch(e => {
                console.error("Audio playback error", e);
                playNextAudio();
            });
        }
    }, []);

    const handleInterrupt = useCallback(() => {
        // Immediately halt current playback
        if (currentAudioRef.current) {
            currentAudioRef.current.pause();
            currentAudioRef.current = null;
        }
        // Clear queue
        audioQueueRef.current = [];
        setIsAgentSpeaking(false);

        // Signal backend to cancel generation
        if (wsVoiceRef.current && wsVoiceRef.current.readyState === WebSocket.OPEN) {
            wsVoiceRef.current.send(JSON.stringify({ action: "interrupt" }));
        }
    }, []);

    const endVoiceUtterance = useCallback(() => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
            mediaRecorderRef.current.stop(); // Flushes chunk and triggers onstop -> sends commit
        }
        try {
            speechRecognitionRef.current?.stop();
        } catch (e) {
            // ignore
        }
    }, []);

    const detectVolumeLoop = useCallback(() => {
        if (!analyserRef.current) return;

        const dataArray = new Float32Array(analyserRef.current.fftSize);
        analyserRef.current.getFloatTimeDomainData(dataArray);

        let sumSquares = 0.0;
        for (const amplitude of dataArray) {
            sumSquares += amplitude * amplitude;
        }
        const volume = Math.sqrt(sumSquares / dataArray.length);

        const VOLUME_THRESHOLD = 0.03;
        const SILENCE_MS = 1500;

        if (volume > VOLUME_THRESHOLD) {
            // User is actively speaking
            if (!isSpeakingRef.current) {
                isSpeakingRef.current = true;
                setIsListening(true);

                // If they interrupt the AI verbally, auto-interrupt AI speech!
                handleInterrupt();

                // Start a fresh recording chunk if not recording
                if (mediaRecorderRef.current?.state === "inactive") {
                    mediaRecorderRef.current.start();
                    try {
                        transcriptRef.current = "";
                        speechRecognitionRef.current?.start();
                    } catch (e) {
                        // ignore if already started
                    }
                }
            }
            // Clear any lingering silence timers
            if (silenceTimerRef.current) {
                clearTimeout(silenceTimerRef.current);
                silenceTimerRef.current = null;
            }
        } else {
            // Silence
            if (isSpeakingRef.current && !silenceTimerRef.current) {
                // Wait for SILENCE_MS ms before deciding utterance is over
                silenceTimerRef.current = window.setTimeout(() => {
                    isSpeakingRef.current = false;
                    setIsListening(false);
                    endVoiceUtterance();
                    silenceTimerRef.current = null;
                }, SILENCE_MS);
            }
        }

        requestAnimationFrameRef.current = requestAnimationFrame(detectVolumeLoop);
    }, [handleInterrupt, endVoiceUtterance]);

    const startCall = async () => {
        if (!report) return;

        try {
            setVoiceStatus("Requesting Mic...");
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            streamRef.current = stream;

            // Setup VAD with Web Audio API
            const audioCtx = new AudioContext();
            audioContextRef.current = audioCtx;
            const analyser = audioCtx.createAnalyser();
            analyser.minDecibels = -90;
            analyser.smoothingTimeConstant = 0.2;
            const source = audioCtx.createMediaStreamSource(stream);
            source.connect(analyser);
            analyserRef.current = analyser;

            // Setup Speech Recognition for Transcription
            const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
            if (SpeechRecognition) {
                const recognition = new SpeechRecognition();
                recognition.continuous = true;
                recognition.interimResults = true;
                recognition.onresult = (event: any) => {
                    let fullTranscript = "";
                    for (let i = 0; i < event.results.length; ++i) {
                        fullTranscript += event.results[i][0].transcript;
                    }
                    transcriptRef.current = fullTranscript;
                };
                speechRecognitionRef.current = recognition;
            }

            setVoiceStatus("Connecting...");
            const ws = new WebSocket(WS_VOICE_URL);
            ws.binaryType = "arraybuffer";
            wsVoiceRef.current = ws;

            ws.onopen = () => {
                setVoiceStatus("Call Active");
                ws.send(JSON.stringify({ type: "init", context: report }));

                const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
                mediaRecorderRef.current = mediaRecorder;

                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
                        ws.send(e.data); // Stream raw binary
                    }
                };

                mediaRecorder.onstop = () => {
                    // Send final flag marking end of this user utterance
                    if (ws.readyState === WebSocket.OPEN) {
                        const spokeTime = transcriptRef.current.trim();
                        const finalSpokenText = spokeTime ? spokeTime : "(Spoken audio sent)";
                        setChatHistory(prev => [...prev, { role: "user", text: finalSpokenText }]);
                        transcriptRef.current = "";
                        ws.send(JSON.stringify({ action: "commit_audio" }));
                    }
                };

                // Start volume detection loop
                detectVolumeLoop();
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === "chat_reply") {
                        if (data.message) {
                            setChatHistory(prev => {
                                const newHistory = [...prev];
                                const lastItem = newHistory[newHistory.length - 1];
                                if (lastItem && lastItem.role === "agent") {
                                    // Append to the last agent block continuously
                                    lastItem.text += data.message;
                                    return newHistory;
                                }
                                return [...newHistory, { role: "agent", text: data.message }];
                            });
                        }
                        if (data.audio_data) {
                            const audio = new Audio(data.audio_data);
                            audioQueueRef.current.push(audio);
                            // Auto-play next if idle
                            if (!currentAudioRef.current || currentAudioRef.current.ended || currentAudioRef.current.paused) {
                                playNextAudio();
                            }
                        }
                    } else if (data.type === "system") {
                        console.log("System:", data.message);
                    }
                } catch {
                    console.warn("Failed to parse WS voice message", event.data);
                }
            };

            ws.onerror = () => setVoiceStatus("WebSocket Error");
            ws.onclose = () => {
                stopCall();
            };

        } catch (err) {
            console.error(err);
            setVoiceStatus("Mic denied or error");
        }
    };

    const stopCall = useCallback(() => {
        if (requestAnimationFrameRef.current) cancelAnimationFrame(requestAnimationFrameRef.current);
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        if (audioContextRef.current?.state !== "closed") audioContextRef.current?.close();

        mediaRecorderRef.current?.stop();
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;

        wsVoiceRef.current?.close();

        // Stop playback
        if (currentAudioRef.current) {
            currentAudioRef.current.pause();
            currentAudioRef.current = null;
        }
        audioQueueRef.current = [];

        try {
            speechRecognitionRef.current?.stop();
        } catch (e) {
            // ignore
        }

        setVoiceStatus("Disconnected");
        setIsListening(false);
        setIsAgentSpeaking(false);
        isSpeakingRef.current = false;
    }, []);

    // ── File handling ─────────────────────────────────────────────
    const handleFile = (selectedFile: File) => {
        setFile(selectedFile);
        setReport(null);
        setError(null);
        setChatHistory([]); // Clear past chat history
        stopCall();
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

    // ── Simulated progress ────────────────────────────────────────
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

        const controller = new AbortController();
        abortRef.current = controller;

        setLoading(true);
        setError(null);
        setReport(null);

        const progressInterval = simulateProgress();

        try {
            const addressParts = [
                listingStreet.trim(),
                listingUnit.trim() ? `Unit ${listingUnit.trim()}` : "",
                listingLocality.trim()
            ].filter(Boolean);
            const combinedAddress = addressParts.join(", ");

            const body = new FormData();
            body.append("file", file);
            body.append("listing_address", combinedAddress);
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

    useEffect(() => {
        return () => stopCall();
    }, [stopCall]);

    const stopAnalysis = () => {
        abortRef.current?.abort();
    };

    // Chat UI component helpers
    const chatContainerRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
    }, [chatHistory]);

    return (
        <div className="space-y-6">
            <div>
                <h2 className="text-2xl font-bold text-white">Deep Scan</h2>
                <p className="mt-1 text-sm text-slate-400">
                    Upload a property tour video or image for forensic analysis.
                </p>
            </div>

            {/* ── Listing Details ──────────────────────────────────── */}
            <div className="space-y-4 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Listing Details
                </h3>
                
                {/* Address Fields */}
                <div className="grid gap-3 md:grid-cols-2">
                    <div className="md:col-span-2">
                        <label className="mb-1.5 block text-xs font-medium text-slate-400">Street Address</label>
                        <input
                            type="text"
                            placeholder="e.g., 195 Webster Ave"
                            value={listingStreet}
                            onChange={(e) => setListingStreet(e.target.value)}
                            className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                        />
                    </div>
                    
                    <div>
                        <label className="mb-1.5 block text-xs font-medium text-slate-400">Apt / Unit (Optional)</label>
                        <input
                            type="text"
                            placeholder="e.g., Apt 4B"
                            value={listingUnit}
                            onChange={(e) => setListingUnit(e.target.value)}
                            className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                        />
                    </div>

                    <div>
                        <label className="mb-1.5 block text-xs font-medium text-slate-400">City, State ZIP</label>
                        <input
                            type="text"
                            placeholder="e.g., Jersey City NJ"
                            value={listingLocality}
                            onChange={(e) => setListingLocality(e.target.value)}
                            className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                        />
                    </div>
                </div>

                {/* Description Area */}
                <div>
                    <label className="mb-1.5 block text-xs font-medium text-slate-400">Description or Claims</label>
                    <textarea
                        placeholder="Paste the listing description or let TrustKit auto-fetch it from online using the address above."
                        value={listingDescription}
                        onChange={(e) => setListingDescription(e.target.value)}
                        rows={3}
                        className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-indigo-500 focus:outline-none resize-none"
                    />
                    <p className="mt-2 text-xs text-slate-500">
                        Enter the address — TrustKit will automatically look up the listing on online platforms to compare claims against the live video.
                    </p>
                </div>
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
                        <p className="text-sm font-semibold text-indigo-400">Drop your file here</p>
                    </>
                ) : file ? (
                    <>
                        <p className="text-3xl mb-2">✅</p>
                        <p className="text-sm font-semibold text-emerald-400">{file.name}</p>
                    </>
                ) : (
                    <>
                        <p className="text-3xl mb-2">🎬</p>
                        <p className="text-sm font-semibold text-slate-300">Drag &amp; drop a video or image here</p>
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
                    <h3 className="text-lg font-semibold text-white">Media Analysis Report</h3>

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
                    {/* Listing Comparison (if available) */}
                    {report.listing_comparison && (
                        <div>
                            <h4 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                                Verify Against Listing
                            </h4>
                            <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-5 space-y-4">
                                {report.listing_comparison.error ? (
                                    <p className="text-sm text-red-400">{report.listing_comparison.error}</p>
                                ) : (
                                    <>
                                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                                            <div>
                                                <p className="text-slate-500 mb-1 leading-none">Price</p>
                                                <p className="text-slate-200 font-medium">{report.listing_comparison.price}</p>
                                            </div>
                                            <div>
                                                <p className="text-slate-500 mb-1 leading-none">Beds</p>
                                                <p className="text-slate-200 font-medium">{report.listing_comparison.beds}</p>
                                            </div>
                                            <div>
                                                <p className="text-slate-500 mb-1 leading-none">Baths</p>
                                                <p className="text-slate-200 font-medium">{report.listing_comparison.baths}</p>
                                            </div>
                                            <div>
                                                <p className="text-slate-500 mb-1 leading-none">Sqft</p>
                                                <p className="text-slate-200 font-medium">{report.listing_comparison.sqft}</p>
                                            </div>
                                        </div>
                                        
                                        <div className="pt-3 border-t border-slate-700 mt-4">
                                            <p className="text-xs font-medium uppercase tracking-wider text-slate-500 mb-2">
                                                AI Comparison Summary
                                            </p>
                                            <div className="text-sm text-slate-300 space-y-2 whitespace-pre-wrap">
                                                {report.listing_comparison.comparison_summary}
                                            </div>
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* ── FULL DUPLEX VOICE UI ──────────────────────────────────────── */}
            {report && (
                <div className="flex flex-col rounded-xl border border-slate-700 bg-slate-800/50 p-6 relative overflow-hidden">
                    <div className="flex items-center justify-between mb-4 bg-slate-900/40 -m-6 p-6 pb-4 border-b border-slate-700 z-10">
                        <div>
                            <div className="flex items-center gap-3">
                                <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                    TrustKit AI Phone Call
                                </h3>
                                {voiceStatus === "Call Active" && (
                                    <span className="flex h-3 w-3 relative">
                                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                        <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                                    </span>
                                )}
                            </div>
                            <p className="text-xs text-slate-400 mt-1 uppercase tracking-widest font-semibold">{voiceStatus}</p>
                        </div>

                        <div className="flex items-center gap-3">
                            {voiceStatus === "Call Active" ? (
                                <>
                                    {isAgentSpeaking && (
                                        <button
                                            onClick={handleInterrupt}
                                            className="cursor-pointer px-4 py-2 bg-red-500/10 text-red-400 font-semibold text-sm rounded-lg border border-red-500/30 hover:bg-red-500/20 transition-all flex items-center gap-2 shadow-[0_0_15px_rgba(239,68,68,0.2)]"
                                        >
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"></path></svg>
                                            Interrupt AI
                                        </button>
                                    )}
                                    <button
                                        onClick={stopCall}
                                        className="cursor-pointer px-4 py-2 bg-slate-700 text-white font-semibold text-sm rounded-lg hover:bg-slate-600 transition-all"
                                    >
                                        End Call
                                    </button>
                                </>
                            ) : (
                                <button
                                    onClick={startCall}
                                    className="cursor-pointer px-6 py-2 bg-emerald-600 text-white font-semibold text-sm rounded-lg hover:bg-emerald-500 transition-all shadow-[0_0_20px_rgba(16,185,129,0.3)] hover:shadow-[0_0_25px_rgba(16,185,129,0.5)]"
                                >
                                    Start Call
                                </button>
                            )}
                        </div>
                    </div>

                    <div ref={chatContainerRef} className="flex-1 overflow-y-auto space-y-4 pt-4 pb-20 relative z-0" style={{ height: "350px", scrollBehavior: "smooth" }}>
                        {voiceStatus !== "Call Active" && chatHistory.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
                                <div className="w-16 h-16 rounded-full bg-slate-700/50 flex items-center justify-center mb-2">
                                    <span className="text-2xl">📞</span>
                                </div>
                                <p className="text-slate-400 font-medium">Click "Start Call" to begin a full-duplex voice conversation.</p>
                                <p className="text-slate-500 text-sm max-w-sm">You can speak naturally and interrupt the AI at any time.</p>
                            </div>
                        ) : (
                            chatHistory.map((msg, i) => (
                                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                                    <div className={`max-w-[85%] rounded-2xl px-5 py-3 shadow-lg ${msg.role === 'user'
                                        ? 'bg-gradient-to-br from-indigo-500 to-indigo-600 text-white rounded-br-none'
                                        : 'bg-slate-700 text-slate-100 rounded-bl-none border border-slate-600'
                                        }`}>
                                        <div className="flex items-center gap-2 mb-1 opacity-70">
                                            <span className="text-[10px] font-bold tracking-wider uppercase">
                                                {msg.role === 'user' ? 'You' : 'TrustKit AI'}
                                            </span>
                                        </div>
                                        <p className="text-[15px] leading-relaxed break-words">{msg.text}</p>
                                    </div>
                                </div>
                            ))
                        )}
                        {/* Fake element to preserve scroll spacing for the fixed footer */}
                        <div className="h-4"></div>
                    </div>

                    {/* Microphone Visualizer Footer */}
                    {voiceStatus === "Call Active" && (
                        <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-slate-900 via-slate-900/90 to-transparent flex justify-center z-20">
                            <div className="flex items-center gap-4 bg-slate-800 border border-slate-700 rounded-full px-6 py-3 shadow-[0_0_30px_rgba(0,0,0,0.5)]">
                                <div className="w-8 h-8 rounded-full flex items-center justify-center relative bg-slate-700">
                                    <span className="text-sm relative z-10">🎤</span>
                                    {isListening && (
                                        <>
                                            <div className="absolute inset-0 rounded-full bg-indigo-500 animate-ping opacity-60"></div>
                                            <div className="absolute inset-[-4px] rounded-full bg-indigo-500/30 animate-pulse"></div>
                                        </>
                                    )}
                                </div>
                                <span className={`text-sm font-semibold transition-colors duration-300 w-24 text-center ${isListening ? 'text-indigo-400' : 'text-slate-500'}`}>
                                    {isListening ? "Listening..." : "Idle"}
                                </span>
                            </div>
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
