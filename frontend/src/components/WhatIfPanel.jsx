import { useEffect, useRef, useState } from "react";
import { PiggyBank } from "lucide-react";
import { getJSON } from "../api";

// What-if savings (UPG-06): the engineer's last 30 days of real tokens, re-priced by the API
// with a better cache hit ratio and/or less Opus. The sliders start at the team's top-quartile
// habits; moving one asks the API again (debounced, so dragging sends one request).
const DEBOUNCE_MS = 300;
const usd = (x) => `$${x.toFixed(2)}`;
const pct = (x) => `${(x * 100).toFixed(0)}%`;

export default function WhatIfPanel({ userId }) {
    const [result, setResult] = useState(null);
    const [targets, setTargets] = useState(null);   // {cache_hit, opus_pct}, from the sliders
    const [error, setError] = useState(null);
    const timer = useRef(null);

    // First load: the API picks the team's top-quartile targets.
    useEffect(() => {
        getJSON(`/api/engineer/${userId}/what-if`)
            .then((body) => {
                setResult(body);
                setTargets(body.targets);
            })
            .catch((e) => setError(e.message));
        return () => clearTimeout(timer.current);
    }, [userId]);

    const move = (key, value) => {
        const next = { ...targets, [key]: value };
        setTargets(next);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => {
            getJSON(`/api/engineer/${userId}/what-if?cache_hit=${next.cache_hit}&opus_pct=${next.opus_pct}`)
                .then(setResult)
                .catch((e) => setError(e.message));
        }, DEBOUNCE_MS);
    };

    return (
        <section className="glass-card rounded-xl p-6 flex flex-col gap-4">
            <div className="flex justify-between items-start">
                <div>
                    <h2 className="text-base font-bold text-on-surface">What-if savings</h2>
                    <p className="text-xs text-on-surface-variant">
                        Your last {result?.days ?? 30} days of tokens, re-priced with a better habit (per 30 days)
                    </p>
                </div>
                <PiggyBank size={20} className="text-primary/50" />
            </div>

            {error && <p className="font-mono text-xs text-error">{error}</p>}
            {!error && !result && <p className="font-mono text-xs text-on-surface-variant">Loading...</p>}
            {result && targets && (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <label className="flex flex-col gap-1 text-xs text-on-surface-variant">
                            <span>
                                Cache hit target: <b className="text-on-surface">{pct(targets.cache_hit)}</b>
                                {" "}(now {pct(result.current.cache_hit)})
                            </span>
                            <input
                                type="range" min="0" max="97" step="1" aria-label="Cache hit target"
                                value={Math.round(targets.cache_hit * 100)}
                                onChange={(e) => move("cache_hit", Number(e.target.value) / 100)}
                            />
                        </label>
                        <label className="flex flex-col gap-1 text-xs text-on-surface-variant">
                            <span>
                                Opus share at most: <b className="text-on-surface">{pct(targets.opus_pct)}</b>
                                {" "}(now {pct(result.current.opus_pct)})
                            </span>
                            <input
                                type="range" min="0" max="100" step="1" aria-label="Opus share target"
                                value={Math.round(targets.opus_pct * 100)}
                                onChange={(e) => move("opus_pct", Number(e.target.value) / 100)}
                            />
                        </label>
                    </div>

                    <div className="grid grid-cols-3 gap-3 text-center">
                        {[["Caching", result.cache], ["Model choice", result.model], ["Both", result.combined]].map(
                            ([label, lever]) => (
                                <div key={label} className="bg-surface-container-high rounded-lg p-3">
                                    <p className="font-mono text-[10px] uppercase tracking-widest text-on-surface-variant">{label}</p>
                                    <p className="text-lg font-bold text-emerald-500">{usd(lever.saving_month_usd)}</p>
                                </div>
                            ))}
                    </div>
                    <p className="text-[11px] text-on-surface-variant">
                        Now {usd(result.current_month_usd)} per 30 days. Defaults are the team's top quartile
                        ({pct(result.team_targets.cache_hit)} cache hit, {pct(result.team_targets.opus_pct)} Opus);
                        a day already better than the target is left as it was.
                    </p>
                </>
            )}
        </section>
    );
}
