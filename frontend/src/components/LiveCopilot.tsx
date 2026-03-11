/**
 * LiveCopilot — Real-time webcam streaming component.
 *
 * 1. User enters listing details (address, description, etc.)
 * 2. Requests webcam access via getUserMedia.
 * 3. Displays the live feed in a <video> element.
 * 4. Sends listing details as the first WebSocket message (JSON text).
 * 5. Captures JPEG frames on a hidden <canvas> and sends them as
 *    binary Blobs over a WebSocket to ws://localhost:8000/ws/live
 *    at exactly 1 frame per second.
 * 6. Receives alert JSON from the backend and passes them to AlertPanel.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import AlertPanel, { type Alert } from "./AlertPanel";

const WS_URL = "ws://localhost:8000/ws/live";
const FRAME_INTERVAL_MS = 3000; // 1 frame every 3s — prevents Vertex AI queue backlog

export default function LiveCopilot() {
    const videoRef = useRef<HTMLVideoElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const intervalRef = useRef<number | null>(null);
    const streamRef = useRef<MediaStream | null>(null);

    const [running, setRunning] = useState(false);
    const [alerts, setAlerts] = useState<Alert[]>([]);
    const [trustScore, setTrustScore] = useState<number | null>(null);
    const [status, setStatus] = useState<string>("Idle");

    // ── Listing details input ─────────────────────────────────────
    const [listingAddress, setListingAddress] = useState("");
    const [listingDescription, setListingDescription] = useState("");

    // ── Capture a frame from the video → binary Blob ──────────────
    const captureAndSend = useCallback((ws: WebSocket) => {
        const video = videoRef.current;
        const canvas = canvasRef.current;
        if (!video || !canvas) return;
        if (ws.readyState !== WebSocket.OPEN) return;

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        ctx.drawImage(video, 0, 0);

        // Convert canvas to JPEG Blob and send as binary
        canvas.toBlob(
            (blob) => {
                if (blob && ws.readyState === WebSocket.OPEN) {
                    ws.send(blob);
                }
            },
            "image/jpeg",
            0.6 // quality — keeps frame size <50 KB
        );
    }, []);

    // ── Start pipeline ────────────────────────────────────────────
    const start = useCallback(async () => {
        try {
            setStatus("Requesting camera…");
            const stream = await navigator.mediaDevices.getUserMedia({
                video: true,
                audio: false,
            });
            streamRef.current = stream;

            if (videoRef.current) {
                videoRef.current.srcObject = stream;
            }

            // Open WebSocket
            setStatus("Connecting to backend…");
            const ws = new WebSocket(WS_URL);
            ws.binaryType = "arraybuffer";
            wsRef.current = ws;

            ws.onopen = () => {
                setStatus("Live — analysing frames");
                setRunning(true);

                // Send listing details as the FIRST message (JSON text)
                const config = {
                    type: "config",
                    listing_address: listingAddress.trim(),
                    listing_description: listingDescription.trim(),
                };
                ws.send(JSON.stringify(config));

                // Start frame capture loop — exactly 1 FPS
                intervalRef.current = window.setInterval(() => {
                    captureAndSend(ws);
                }, FRAME_INTERVAL_MS);
            };

            // Manage audio playback to avoid overlapping
            let currentAudio: HTMLAudioElement | null = null;

            ws.onmessage = (event) => {
                try {
                    const data: Alert = JSON.parse(event.data);

                    // Filter out fallback alerts from polluting the UI
                    if (data.message === "Analyzing next frame...") return;

                    setAlerts((prev) => [data, ...prev]);
                    setTrustScore(data.trust_score);

                    // Automatically play new incoming audio warnings
                    if (data.audio_data) {
                        // Only play if not currently speaking to avoid overlapping chaos
                        if (!currentAudio || currentAudio.ended || currentAudio.paused) {
                            currentAudio = new Audio(data.audio_data);
                            currentAudio.play().catch(console.error);
                        }
                    }
                } catch {
                    console.warn("Failed to parse WS message", event.data);
                }
            };

            ws.onerror = () => setStatus("WebSocket error");
            ws.onclose = () => {
                setStatus("Disconnected");
                setRunning(false);

                // Stop the interval if WS closes unexpectedly
                if (intervalRef.current) {
                    clearInterval(intervalRef.current);
                    intervalRef.current = null;
                }

                // Stop any audio playing
                if (currentAudio) {
                    currentAudio.pause();
                    currentAudio = null;
                }
            };
        } catch (err) {
            console.error(err);
            setStatus("Camera access denied");
        }
    }, [captureAndSend, listingAddress, listingDescription]);

    // ── Stop pipeline ─────────────────────────────────────────────
    const stop = useCallback(() => {
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
        wsRef.current?.close();
        wsRef.current = null;

        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;

        setRunning(false);
        setStatus("Stopped");
    }, []);

    // Cleanup on unmount
    useEffect(() => () => stop(), [stop]);

    return (
        <div className="space-y-6">
            {/* ── Header ─────────────────────────────────────────── */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold text-white">Live Copilot</h2>
                    <p className="mt-1 text-sm text-slate-400">{status}</p>
                </div>

                {!running ? (
                    <button
                        onClick={start}
                        className="cursor-pointer rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500"
                    >
                        Start Copilot
                    </button>
                ) : (
                    <button
                        onClick={stop}
                        className="cursor-pointer rounded-lg bg-red-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-red-500"
                    >
                        Stop
                    </button>
                )}
            </div>

            {/* ── Listing Details Input ───────────────────────────── */}
            {!running && (
                <div className="space-y-3 rounded-xl border border-slate-700 bg-slate-800/50 p-4">
                    <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
                        Listing Details
                    </h3>
                    <input
                        type="text"
                        placeholder="Listing address (e.g., 123 Main St, Apt 4B, NYC)"
                        value={listingAddress}
                        onChange={(e) => setListingAddress(e.target.value)}
                        className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none"
                    />
                    <textarea
                        placeholder="Paste the listing description or let TrustKit auto-fetch it from Zillow using the address above."
                        value={listingDescription}
                        onChange={(e) => setListingDescription(e.target.value)}
                        rows={3}
                        className="w-full rounded-lg border border-slate-600 bg-slate-900 px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:border-emerald-500 focus:outline-none resize-none"
                    />
                    <p className="text-xs text-slate-500">
                        Enter the address — TrustKit will automatically look up the listing on Zillow.
                    </p>
                </div>
            )}

            {/* ── Video + Alerts grid ────────────────────────────── */}
            <div className="grid gap-6 lg:grid-cols-3">
                {/* Video feed */}
                <div className="lg:col-span-2">
                    <div className="overflow-hidden rounded-xl border border-slate-700 bg-black">
                        <video
                            ref={videoRef}
                            autoPlay
                            muted
                            playsInline
                            className="aspect-video w-full object-cover"
                        />
                    </div>
                </div>

                {/* Alert panel */}
                <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-4">
                    <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
                        Alerts
                    </h3>
                    <AlertPanel alerts={alerts} trustScore={trustScore} />
                </div>
            </div>

            {/* Hidden canvas for frame capture */}
            <canvas ref={canvasRef} className="hidden" />
        </div>
    );
}
