/**
 * DeepScan — Upload a prerecorded video for forensic analysis.
 *
 * Sends the file via POST to http://localhost:8000/deep-scan and
 * renders the metadata, vision analysis, and trust assessment
 * returned by the backend.
 */

import { useState, type ChangeEvent, type FormEvent } from "react";

const API_URL = "http://localhost:8000/deep-scan";

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

interface ScanReport {
    filename: string;
    metadata: Metadata;
    vision_analysis: VisionResult[];
    assessment: Assessment;
}

function trustColor(score: number): string {
    if (score >= 75) return "text-emerald-400";
    if (score >= 50) return "text-amber-400";
    return "text-red-400";
}

export default function DeepScan() {
    const [file, setFile] = useState<File | null>(null);
    const [report, setReport] = useState<ScanReport | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
        setFile(e.target.files?.[0] ?? null);
        setReport(null);
        setError(null);
    };

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        if (!file) return;

        setLoading(true);
        setError(null);

        try {
            const body = new FormData();
            body.append("file", file);

            const res = await fetch(API_URL, { method: "POST", body });

            if (!res.ok) throw new Error(`Server responded ${res.status}`);

            const data: ScanReport = await res.json();
            setReport(data);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setLoading(false);
        }
    };

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
                className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-700 bg-slate-800/50 p-5"
            >
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
            </form>

            {error && (
                <p className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error}
                </p>
            )}

            {/* ── Report Card ────────────────────────────────────── */}
            {report && (
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
                                </div>
                            ))}
                        </div>
                    </div>
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
