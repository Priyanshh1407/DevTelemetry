import { useEffect, useState } from "react";
import { GraduationCap } from "lucide-react";
import { getJSON } from "../api";

// Did the coaching work? (UPG-05) The headline is the difference-in-differences estimate from
// GET /api/coaching-impact; the naive before/after is shown only with its bias named, because
// we coach whoever had the worst day, and they look better afterwards anyway.
const DAYS = 120;

const signed = (x) => `${x > 0 ? "+" : ""}${x.toFixed(1)}`;

function verdict(did) {
    if (did.ci_low === null) return { text: "Too few coaching rounds for an interval", tone: "text-on-surface-variant" };
    if (did.ci_low > 0) return { text: "Improvement detected", tone: "text-emerald-500" };
    if (did.ci_high < 0) return { text: "Got worse after coaching", tone: "text-rose-500" };
    return { text: "No clear effect yet", tone: "text-on-surface-variant" };
}

export default function CoachingImpactCard() {
    const [impact, setImpact] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        getJSON(`/api/coaching-impact?days=${DAYS}`).then(setImpact).catch((e) => setError(e.message));
    }, []);

    const did = impact?.did;
    const hasEstimate = did && did.estimate !== null && did.estimate !== undefined;

    return (
        <section className="glass-card rounded-xl p-6 flex flex-col gap-3">
            <div className="flex justify-between items-start">
                <div>
                    <h2 className="text-lg font-bold text-on-surface">Coaching impact</h2>
                    <p className="text-sm text-on-surface-variant mt-0.5">
                        Points gained in the coached area, vs. engineers who weren't coached (last {DAYS} days)
                    </p>
                </div>
                <GraduationCap size={22} className="text-primary/50" />
            </div>

            {error && <p className="font-mono text-xs text-error">Couldn't load coaching impact: {error}</p>}
            {!error && !impact && <p className="font-mono text-xs text-on-surface-variant">Loading...</p>}
            {impact && !hasEstimate && (
                <p className="text-sm text-on-surface-variant">
                    No coaching with enough data before and after it yet. Each estimate needs a week of usage
                    on both sides of the coaching day.
                </p>
            )}
            {hasEstimate && (
                <>
                    <div className="flex items-baseline gap-3 flex-wrap">
                        <span className="text-3xl font-bold tracking-tight text-on-surface">{signed(did.estimate)}</span>
                        <span className="text-sm text-on-surface-variant">points</span>
                        {did.ci_low !== null && (
                            <span className="font-mono text-xs text-on-surface-variant">
                                95% CI {signed(did.ci_low)} to {signed(did.ci_high)}
                            </span>
                        )}
                    </div>
                    <p className={`font-mono text-xs ${verdict(did).tone}`}>{verdict(did).text}</p>
                    <p className="text-xs text-on-surface-variant">
                        From {impact.n_events} coaching events
                        {impact.n_excluded ? ` (${impact.n_excluded} without a clean week before and after were left out)` : ""}.
                    </p>
                    {impact.naive?.estimate !== null && impact.naive?.estimate !== undefined && (
                        <p className="text-xs text-on-surface-variant border-t border-outline-variant/40 pt-3">
                            <span className="font-mono">{signed(impact.naive.estimate)}</span> naive before/after
                            (biased by regression to the mean): coaching goes to whoever had the worst day, and a
                            bad day is usually followed by a better one anyway.
                        </p>
                    )}
                </>
            )}
        </section>
    );
}
