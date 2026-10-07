import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Siren } from "lucide-react";
import { getJSON } from "../api";

// Spend anomalies (UPG-07): days that cost far more than that engineer's own normal for the
// same day type, from GET /api/anomalies (median/MAD detector, evaluated in docs/anomalies.md).
const DAYS = 14;
const usd = (x) => `$${x.toFixed(2)}`;

export default function AnomaliesCard() {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        getJSON(`/api/anomalies?days=${DAYS}`).then(setData).catch((e) => setError(e.message));
    }, []);

    const anomalies = Array.isArray(data?.anomalies) ? data.anomalies : [];

    return (
        <section className="glass-card rounded-xl p-6 flex flex-col gap-3">
            <div className="flex justify-between items-start">
                <div>
                    <h2 className="text-lg font-bold text-on-surface">Spend anomalies</h2>
                    <p className="text-sm text-on-surface-variant mt-0.5">
                        Days far above that engineer's usual cost (last {DAYS} days)
                    </p>
                </div>
                <Siren size={22} className="text-tertiary/60" />
            </div>

            {error && <p className="font-mono text-xs text-error">Couldn't load anomalies: {error}</p>}
            {!error && !data && <p className="font-mono text-xs text-on-surface-variant">Loading...</p>}
            {data && anomalies.length === 0 && (
                <p className="text-sm text-on-surface-variant">No unusual spend in the last {DAYS} days.</p>
            )}
            {anomalies.length > 0 && (
                <ul className="flex flex-col divide-y divide-outline-variant/30">
                    {anomalies.map((a) => (
                        <li key={`${a.user_id}-${a.date}`} className="py-2 flex flex-col gap-0.5">
                            <div className="flex justify-between items-baseline gap-3">
                                <Link to={`/engineer/${a.user_id}`} className="font-bold text-sm text-on-surface hover:underline">
                                    {a.name}
                                </Link>
                                <span className="font-mono text-xs text-on-surface-variant">{a.date}</span>
                            </div>
                            <p className="text-xs text-on-surface-variant">
                                <span className="font-mono text-rose-500">{usd(a.cost_usd)}</span>
                                {" "}(usually {usd(a.baseline_median_usd)}) · likely {a.driver_label}
                            </p>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}
