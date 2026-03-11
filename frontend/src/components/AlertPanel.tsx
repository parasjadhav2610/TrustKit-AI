/**
 * AlertPanel — Displays real-time trust score and warning alerts
 * received from the Live Copilot WebSocket pipeline.
 *
 * Props:
 *   alerts  – Array of alert objects from the agent reasoner.
 *   trustScore – Latest trust score (0-100).
 */

export interface Alert {
    alert: boolean;
    message: string;
    trust_score: number;
    audio_data?: string;
}

interface AlertPanelProps {
    alerts: Alert[];
    trustScore: number | null;
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

export default function AlertPanel({ alerts, trustScore }: AlertPanelProps) {
    return (
        <div className="space-y-4">
            {/* ── Trust Score Indicator ────────────────────────────── */}
            {trustScore !== null && (
                <div
                    className={`rounded-xl border p-5 text-center ${trustBg(trustScore)}`}
                >
                    <p className="text-sm font-medium uppercase tracking-wider text-slate-300">
                        Trust Score
                    </p>
                    <p className={`mt-1 text-5xl font-bold ${trustColor(trustScore)}`}>
                        {trustScore}%
                    </p>
                </div>
            )}

            {/* ── Alert List ──────────────────────────────────────── */}
            {alerts.length === 0 ? (
                <p className="text-sm italic text-slate-500">
                    No alerts yet — start the Live Copilot to begin analysis.
                </p>
            ) : (
                <ul className="space-y-3">
                    {alerts.map((a, i) => (
                        <li
                            key={i}
                            className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${a.alert
                                ? "border-red-500/40 bg-red-500/10"
                                : "border-slate-700 bg-slate-800/60"
                                }`}
                        >
                            {a.alert && (
                                <span className="mt-0.5 text-lg text-red-400">⚠</span>
                            )}
                            <span className="text-sm text-slate-200">{a.message}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
