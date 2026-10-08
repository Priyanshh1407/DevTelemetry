import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Bot, CheckCircle, Info, Loader2, Terminal } from "lucide-react";

import { getJSON } from "../api";

// Everything on this page comes from the API: the coaching guide (/api/runbook-tasks) and the
// engineer's latest numbers (/api/engineer/{id}/details). No placeholder metrics.

const SEVERITY = {
    critical: { label: "Critical", text: "text-error", border: "border-error", note: "Bottom two on the team today." },
    moderate: { label: "Moderate", text: "text-tertiary", border: "border-tertiary", note: "Middle of the team today." },
    low: { label: "Low", text: "text-primary", border: "border-primary", note: "Among the team's top five today." },
};

const AREAS = [
    { key: "cache", label: "Prompt caching", max: 40 },
    { key: "model_mix", label: "Model choice", max: 30 },
    { key: "discipline", label: "Context management", max: 30 },
];

const FALLBACK_REASONS = {
    rate_limited: "the AI provider's rate limit was reached",
    unavailable: "the AI provider is unavailable",
    invalid_output: "the AI reply failed validation twice",
};

function weakestArea(breakdown) {
    if (!breakdown) return null;
    return AREAS.reduce((a, b) => (b.max - breakdown[b.key] > a.max - breakdown[a.key] ? b : a));
}

function Header() {
    return (
        <header className="sticky top-0 z-50 bg-background/90 backdrop-blur-md border-b border-outline-variant h-16 flex items-center">
            <div className="flex justify-between items-center w-full px-6 md:px-10 max-w-[1200px] mx-auto">
                <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                    <ArrowLeft size={18} className="text-on-surface-variant" />
                    <Terminal size={22} className="text-primary" />
                    <span className="text-xl font-bold text-primary">DevTelemetry</span>
                </Link>
                <span className="font-mono text-xs text-on-surface-variant tracking-widest uppercase">Coaching runbook</span>
            </div>
        </header>
    );
}

function Stat({ label, value, sub, testId }) {
    return (
        <div className="glass-card rounded-xl p-5 border border-outline-variant">
            <p className="font-mono text-[11px] uppercase tracking-widest text-on-surface-variant mb-2">{label}</p>
            <p className="text-2xl font-black text-on-surface" data-testid={testId}>{value}</p>
            {sub && <p className="text-xs text-on-surface-variant mt-1">{sub}</p>}
        </div>
    );
}

function SourceNote({ source, cached }) {
    if (source === "ai" || source === "ai_repaired") {
        return (
            <p className="flex items-center gap-2 font-mono text-xs text-on-surface-variant">
                <Bot size={14} className="text-primary" />
                AI-generated from your metrics{cached ? " (served from the stored guide)" : ""}. Every number is checked against your data.
            </p>
        );
    }
    return (
        <p className="flex items-center gap-2 font-mono text-xs text-on-surface-variant">
            <Info size={14} className="text-tertiary" />
            Rule-based guide built from your sub-scores, because {FALLBACK_REASONS[source] || "AI coaching is not available"}.
        </p>
    );
}

export default function Runbook() {
    const { severity, userId } = useParams();
    const [guide, setGuide] = useState(null);
    const [details, setDetails] = useState(null);
    const [done, setDone] = useState({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        // The guide is what the page is for; the engineer's numbers are context (optional).
        const guideRequest = getJSON(`/api/runbook-tasks/${severity}/${userId}`);
        const detailsRequest = getJSON(`/api/engineer/${userId}/details`).catch(() => null);
        guideRequest
            .then(async (data) => {
                const info = await detailsRequest;
                if (cancelled) return;
                // source "none": the API has no usage for this engineer, so there is nothing to coach.
                if (data.source === "none") setError("No usage data for this engineer.");
                else { setGuide(data); setDetails(info); }
            })
            .catch((err) => { if (!cancelled) setError(err.message); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [severity, userId]);

    const theme = SEVERITY[severity] || SEVERITY.moderate;

    if (loading) {
        return (
            <div className="min-h-screen bg-background text-on-surface flex flex-col">
                <Header />
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                    <Loader2 size={48} className="text-primary animate-spin" />
                    <p className="font-mono text-sm text-on-surface-variant tracking-widest uppercase">Preparing the coaching guide…</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="min-h-screen bg-background text-on-surface flex flex-col">
                <Header />
                <div role="alert" className="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
                    <AlertTriangle size={40} className="text-error" />
                    <p className="text-lg font-bold">Couldn't load this runbook.</p>
                    <p className="font-mono text-sm text-on-surface-variant">{error}</p>
                </div>
            </div>
        );
    }

    const latest = details?.latest;
    const breakdown = latest?.score_breakdown;
    const weakest = weakestArea(breakdown);
    const completed = guide.tasks.filter((_, i) => done[i]).length;

    return (
        <div className="min-h-screen bg-background text-on-surface flex flex-col">
            <Header />
            <main className="px-6 md:px-10 py-10 max-w-[1200px] w-full mx-auto flex-1 space-y-8">
                <section className={`rounded-xl border-2 ${theme.border} p-8 bg-surface-container`}>
                    <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border ${theme.border} mb-4`}>
                        <AlertTriangle size={14} className={theme.text} />
                        <span className={`font-mono text-xs uppercase ${theme.text}`}>Severity: {theme.label}</span>
                    </div>
                    <h1 className="text-4xl font-bold mb-1">{details?.name || "Coaching runbook"}</h1>
                    <p className="text-on-surface-variant mb-4">
                        {details?.current_rank ? `Rank #${details.current_rank} · ` : ""}{theme.note}
                    </p>
                    {guide.headline && <p className="text-xl text-on-surface mb-4">{guide.headline}</p>}
                    <SourceNote source={guide.source} cached={guide.cached} />
                </section>

                {latest && (
                    <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <Stat label="Efficiency score" value={latest.efficiency_score} sub="out of 100, latest day" />
                        <Stat label="Biggest opportunity" testId="weakest" value={weakest ? weakest.label : "—"}
                              sub={weakest ? `${(weakest.max - breakdown[weakest.key]).toFixed(1)} of ${weakest.max} points lost` : null} />
                        <Stat label="Estimated cost" value={`$${latest.estimated_cost_usd.toFixed(2)}`} sub="latest day, list prices" />
                    </section>
                )}

                <section className="glass-card rounded-xl overflow-hidden border border-outline-variant">
                    <div className="border-b border-outline-variant bg-surface-container-high px-6 py-4 flex justify-between items-center">
                        <h2 className="text-xl font-bold">Your coaching guide</h2>
                        <span className={`font-mono text-xs ${theme.text}`}>{completed}/{guide.tasks.length} done</span>
                    </div>
                    <ul className="p-4 space-y-3">
                        {guide.tasks.map((task, i) => (
                            <li key={i}>
                                <label className="flex items-start gap-4 p-4 rounded-lg bg-surface border border-outline-variant hover:bg-surface-container-high cursor-pointer transition-colors">
                                    <input type="checkbox" checked={!!done[i]} className="mt-1 w-5 h-5"
                                           onChange={() => setDone({ ...done, [i]: !done[i] })} />
                                    <span className="flex flex-col">
                                        <span className={`font-bold ${done[i] ? "line-through opacity-50" : ""}`}>{task.title}</span>
                                        <span className={`text-sm text-on-surface-variant ${done[i] ? "opacity-50" : ""}`}>{task.desc}</span>
                                    </span>
                                    {done[i] && <CheckCircle size={18} className="ml-auto text-primary shrink-0" />}
                                </label>
                            </li>
                        ))}
                    </ul>
                    <p className="px-6 pb-4 font-mono text-[11px] text-on-surface-variant">
                        Ticks are for your own tracking in this tab; the score changes when your usage does.
                    </p>
                </section>
            </main>
        </div>
    );
}
