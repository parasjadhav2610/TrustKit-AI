/**
 * LiveCopilot — Real-time webcam streaming component.
 *
 * 1. Requests webcam access via getUserMedia.
 * 2. Displays the live feed in a <video> element.
 * 3. Captures frames on a hidden <canvas> and sends them as base64
 *    over a WebSocket to ws://localhost:8000/ws/live.
 * 4. Receives alert JSON from the backend and passes them to AlertPanel.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import AlertPanel, { type Alert } from "./AlertPanel";

const WS_URL = "ws://localhost:8000/ws/live";
const FRAME_INTERVAL_MS = 1000; // send one frame per second

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

    // ── Capture a frame from the video → base64 string ───────────
    const captureFrame = useCallback((): string | null => {
        const video = videoRef.current;
        const canvas = canvasRef.current;
        if (!video || !canvas) return null;

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) return null;

        ctx.drawImage(video, 0, 0);
        // Return the raw base64 payload (strip the data-url prefix)
        return canvas.toDataURL("image/jpeg", 0.6).split(",")[1];
    }, []);

    // ── Start pipeline ───────────────────────────────────────────
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
            wsRef.current = ws;

            ws.onopen = () => {
                setStatus("Live — analysing frames");
                setRunning(true);

                // Start frame capture loop
                intervalRef.current = window.setInterval(() => {
                    const frame = captureFrame();
                    if (frame && ws.readyState === WebSocket.OPEN) {
                        ws.send(frame);
                    }
                }, FRAME_INTERVAL_MS);
            };

            ws.onmessage = (event) => {
                try {
                    const data: Alert = JSON.parse(event.data);
                    setAlerts((prev) => [data, ...prev]);
                    setTrustScore(data.trust_score);
                } catch {
                    console.warn("Failed to parse WS message", event.data);
                }
            };

            ws.onerror = () => setStatus("WebSocket error");
            ws.onclose = () => setStatus("Disconnected");
        } catch (err) {
            console.error(err);
            setStatus("Camera access denied");
        }
    }, [captureFrame]);

    // ── Stop pipeline ────────────────────────────────────────────
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
