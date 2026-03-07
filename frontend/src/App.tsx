import { useState } from "react";
import LiveCopilot from "./components/LiveCopilot";
import DeepScan from "./components/DeepScan";

type Tab = "live" | "deep";

export default function App() {
  const [tab, setTab] = useState<Tab>("live");

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* ── Top bar ──────────────────────────────────────────── */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-bold tracking-tight">
            <span className="text-indigo-400">Trust</span>Kit AI
          </h1>

          {/* Tab switcher */}
          <nav className="flex gap-1 rounded-lg bg-slate-800 p-1">
            <TabButton
              active={tab === "live"}
              onClick={() => setTab("live")}
              label="Live Copilot"
            />
            <TabButton
              active={tab === "deep"}
              onClick={() => setTab("deep")}
              label="Deep Scan"
            />
          </nav>
        </div>
      </header>

      {/* ── Main content ─────────────────────────────────────── */}
      <main className="mx-auto max-w-6xl px-6 py-8">
        {tab === "live" ? <LiveCopilot /> : <DeepScan />}
      </main>
    </div>
  );
}

/* ── Tab button helper ────────────────────────────────────────── */
function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`cursor-pointer rounded-md px-4 py-1.5 text-sm font-medium transition ${active
          ? "bg-indigo-600 text-white"
          : "text-slate-400 hover:text-white"
        }`}
    >
      {label}
    </button>
  );
}
