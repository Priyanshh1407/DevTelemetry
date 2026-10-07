import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
    AreaChart, Area, XAxis, YAxis,
    CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
} from "recharts";
import {
    Users, ChevronUp, Zap, Banknote, ChevronDown,
    Download, Settings,
    CheckCircle, Loader2, Mail, AlertTriangle
} from "lucide-react";
import Navbar from "../components/Navbar";
import CoachingImpactCard from "../components/CoachingImpactCard";
import { adminPost, getJSON, waitForDispatch } from "../api";

// ─── Custom Tooltip ────────────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null;
    return (
        <div className="glass-card rounded-lg px-4 py-3 font-mono text-xs text-on-surface min-w-[160px]">
            <p className="text-on-surface-variant mb-2">{label}</p>
            {payload.map((p) => (
                <div key={p.name} className="flex items-center gap-2 mb-1">
                    <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ background: p.color }}
                    />
                    <span className="text-on-surface-variant">
                        {p.name === "score" ? "Avg Score" : "Total Cost"}:
                    </span>
                    <span className="font-bold ml-auto">{p.value}</span>
                </div>
            ))}
        </div>
    );
}

// The schedule is saved in the admin's own IANA timezone.
const BROWSER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

// ─── Trend + activity helpers ─────────────────────────────────────────────────
// Changes smaller than this (in score points) are shown as flat.
const TREND_EPSILON = 0.05;

function describeTrend(change) {
    if (change === null || change === undefined) return { trend: "flat", trendVal: "" };
    const trend = change > TREND_EPSILON ? "up" : change < -TREND_EPSILON ? "down" : "flat";
    const sign = trend === "up" ? "+" : "";
    return { trend, trendVal: `${sign}${change.toFixed(1)}` };
}

// Map each day's tokens to a 1-4 bar height relative to the team's busiest day.
function activityBars(activity = [], teamMax = 1) {
    return activity.map((tokens) => Math.max(1, Math.ceil((tokens / teamMax) * 4)));
}

// ─── Sparkline ────────────────────────────────────────────────────────────────
const barHeights = { 1: "h-1", 2: "h-2", 3: "h-3", 4: "h-4" };

function Sparkline({ bars, faded }) {
    return (
        <div className="flex gap-0.5 h-4 items-end justify-end">
            {bars.map((b, i) => (
                <div
                    key={i}
                    className={`w-1 rounded-sm ${barHeights[b] || "h-2"} ${faded ? "bg-primary/35" : "bg-primary"}`}
                />
            ))}
        </div>
    );
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
// The leaderboard as shown, as a CSV download.
function downloadLeaderboardCsv(team) {
    const quote = (value) => (/[",\n]/.test(String(value)) ? `"${String(value).replace(/"/g, '""')}"` : value);
    const rows = [["rank", "user_id", "name", "efficiency_score", "estimated_cost_usd"],
                  ...team.map((e) => [e.rank, e.user_id, e.name, e.score, e.cost.toFixed(2)])];
    const blob = new Blob([rows.map((r) => r.map(quote).join(",")).join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "devtelemetry-leaderboard.csv";
    link.click();
    URL.revokeObjectURL(url);
}

export default function Dashboard() {
    const [hoveredRow, setHoveredRow] = useState(null);

    const [team, setTeam] = useState([]);
    const [trendData, setTrendData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);
    const navigate = useNavigate();
    // Alert Configuration State
    const [alertFreq, setAlertFreq] = useState("Weekly");
    const [alertDay, setAlertDay] = useState("Friday");
    const [alertTime, setAlertTime] = useState("17:00");
    const [alertTz, setAlertTz] = useState("UTC");
    const [isTestingAlerts, setIsTestingAlerts] = useState(false);
    const [showToast, setShowToast] = useState(false);
    const [toastMessage, setToastMessage] = useState("");

    // 2. Fetch Data on Load
    useEffect(() => {
        const fetchData = async () => {
            try {
                // Step A: Fetch all three endpoints at the same time (throws on any HTTP error)
                const [rawBoard, rawTrends, rawSettings] = await Promise.all([
                    getJSON("/api/leaderboard"),
                    getJSON("/api/trends"),
                    getJSON("/api/settings")
                ]);

                // Step C: Format Trends for the Recharts graph
                const formattedTrends = rawTrends.map(t => ({
                    day: t.date.slice(5), // Turns "2023-10-24" into "10-24"
                    score: t.avg_score,
                    cost: t.total_cost
                }));

                // Step D: Format Leaderboard for the table
                const teamMaxActivity = Math.max(1, ...rawBoard.flatMap((eng) => eng.recent_activity || []));
                const formattedBoard = rawBoard.map((eng, index) => ({
                    user_id: eng.user_id,
                    rank: index + 1,
                    name: eng.name,
                    score: eng.efficiency_score,
                    cost: eng.estimated_cost_usd,
                    spend: `$${eng.estimated_cost_usd.toFixed(2)}`,
                    // Real 7-day change from the API (was: top 3 always "up", the rest "down")
                    ...describeTrend(eng.score_change_7d),
                    // Daily prompt tokens scaled against the team's busiest day (was: Math.random())
                    bars: activityBars(eng.recent_activity, teamMaxActivity),
                    rankColor: index === 0 ? "#FFD700" : index === 1 ? "#C0C0C0" : index === 2 ? "#CD7F32" : null
                }));

                // Step E: Update all state variables
                setAlertFreq(rawSettings.frequency);
                setAlertDay(rawSettings.day);
                setAlertTime(rawSettings.time);
                setAlertTz(rawSettings.timezone || "UTC");

                setTrendData(formattedTrends);
                setTeam(formattedBoard);

            } catch (error) {
                // Previously only logged: the page then looked like a team with no data.
                console.error("Failed to fetch API data:", error);
                setLoadError(error.message);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [reloadKey]);

    // 5. Calculate live KPI stats
    const latestStats = trendData.length > 0 ? trendData[trendData.length - 1] : { score: 0, cost: 0 };
    // Real change in team spend from the previous day (was a hardcoded "-4.2%").
    const previousStats = trendData.length > 1 ? trendData[trendData.length - 2] : null;
    const spendChange = previousStats && previousStats.cost > 0
        ? ((latestStats.cost - previousStats.cost) / previousStats.cost) * 100 : null;

    if (loading) return <div className="p-10 font-mono text-primary">Loading live telemetry...</div>;

    if (loadError) {
        return (
            <div className="min-h-screen bg-background text-on-surface font-body">
                <Navbar />
                <div role="alert" className="flex flex-col items-center justify-center gap-3 px-6 py-24 text-center">
                    <AlertTriangle size={40} className="text-error" />
                    <p className="text-lg font-bold">Couldn't load team telemetry.</p>
                    <p className="font-mono text-sm text-on-surface-variant">{loadError}</p>
                    <button
                        onClick={() => {
                            setLoadError(null);
                            setLoading(true);
                            setReloadKey((k) => k + 1); // re-runs the fetch effect
                        }}
                        className="mt-2 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 px-4 py-2 rounded-lg font-mono text-xs"
                    >
                        RETRY
                    </button>
                </div>
            </div>
        );
    }

    const handleSaveSchedule = async () => {
        try {
            // Times are wall-clock in the admin's own timezone (the server used to compare against its UTC clock).
            await adminPost("/api/settings", { frequency: alertFreq, day: alertDay, time: alertTime, timezone: BROWSER_TZ });
            setAlertTz(BROWSER_TZ);
            setToastMessage("Alert schedule saved successfully.");
        } catch (e) {
            // Previously the success toast showed even when the save failed.
            console.error("Failed to save schedule:", e);
            setToastMessage(`Schedule not saved: ${e.message}`);
        }
        setShowToast(true);
        setTimeout(() => setShowToast(false), 3000);
    };

    const handleTestAlerts = async () => {
        setIsTestingAlerts(true);
        try {
            // 202: the dispatch runs server-side; poll it for the real delivery counts.
            const started = await adminPost("/api/trigger-alerts");
            const run = await waitForDispatch(started.status_url);
            setToastMessage(run.status === "success" ? run.message : `Alerts not fully sent: ${run.message}`);
        } catch (e) {
            console.error("Failed to trigger alerts:", e);
            setToastMessage(`Alerts not fully sent: ${e.message}`);
        } finally {
            setShowToast(true);
            setTimeout(() => setShowToast(false), 6000);
            setIsTestingAlerts(false);
        }
    };

    return (
        <div className="min-h-screen bg-background text-on-surface font-body">
            <Navbar />

            <div className="max-w-[1440px] mx-auto px-10 py-8 flex flex-col gap-8">

                {/* ── KPI Cards ── */}
                <section className="grid grid-cols-1 md:grid-cols-3 gap-6">

                    {/* Card 1 — Team Size */}
                    <div className="glass-card rounded-xl p-6 relative overflow-hidden group">
                        {/* dot pattern */}
                        <div
                            className="absolute inset-0 opacity-5 pointer-events-none"
                            style={{
                                backgroundImage: "radial-gradient(circle at 2px 2px, #c0c1ff 1px, transparent 0)",
                                backgroundSize: "24px 24px",
                            }}
                        />
                        <div className="flex justify-between items-start mb-2 relative z-10">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">
                                Team Size
                            </span>
                            <Users size={22} className="text-primary/40 group-hover:text-primary/70 transition-colors" />
                        </div>
                        <div className="flex items-baseline gap-2 relative z-10">
                            <span className="text-3xl font-bold tracking-tight text-on-surface">{team.length}</span>
                        </div>
                        <div className="absolute bottom-0 left-0 right-0 h-1 bg-primary/10" />
                    </div>

                    {/* Card 2 — Avg Efficiency */}
                    <div className="glass-card rounded-xl p-6 group">
                        <div className="flex justify-between items-start mb-2">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">
                                Avg Efficiency
                            </span>
                            <Zap size={22} className="text-secondary/40 group-hover:text-secondary/70 transition-colors" />
                        </div>
                        <div className="flex items-baseline gap-2 mb-4">
                            <span className="text-3xl font-bold tracking-tight text-on-surface">{latestStats.score}</span>
                            <span className="text-sm font-semibold text-on-surface-variant">/100</span>
                        </div>
                        <div className="w-full bg-surface-container-high h-1.5 rounded-full overflow-hidden">
                            <div
                                className="h-full rounded-full bg-secondary-container"
                                style={{ width: `${Math.min(latestStats.score, 100)}%`, boxShadow: "0 0 8px rgba(0,162,230,0.5)" }}
                            />
                        </div>
                    </div>

                    {/* Card 3 — Daily Spend */}
                    <div className="glass-card rounded-xl p-6 relative overflow-hidden group">
                        <div className="flex justify-between items-start mb-2">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">
                                Total Daily Spend
                            </span>
                            <Banknote size={22} className="text-tertiary/40 group-hover:text-tertiary/70 transition-colors" />
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span className="text-3xl font-bold tracking-tight text-on-surface">${latestStats.cost}</span>
                            {spendChange !== null && (
                                <span className={`flex items-center text-xs ${spendChange > 0 ? "text-rose-500" : "text-emerald-500"}`}>
                                    {spendChange > 0 ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                    {spendChange > 0 ? "+" : ""}{spendChange.toFixed(1)}% vs previous day
                                </span>
                            )}
                        </div>
                        {/* mini wave */}
                        <div className="absolute bottom-0 right-0 w-32 h-16 opacity-20 pointer-events-none">
                            <svg viewBox="0 0 100 40" className="w-full h-full">
                                <path d="M0 40 L0 30 Q 20 10 40 25 T 80 5 T 100 20 L 100 40 Z" fill="#ffb783" />
                            </svg>
                        </div>
                    </div>
                </section>

                {/* ── Trend Chart ── */}
                <section className="glass-card rounded-xl p-6">
                    <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                        <div>
                            <h2 className="text-lg font-bold text-on-surface">Trend Analysis</h2>
                            <p className="text-sm text-on-surface-variant mt-0.5">
                                30-day performance and cost correlation
                            </p>
                        </div>
                        <div className="flex gap-5">
                            {[
                                { color: "bg-primary", label: "Average Score" },
                                { color: "bg-secondary-container", label: "Total Cost" },
                            ].map(({ color, label }) => (
                                <div key={label} className="flex items-center gap-2">
                                    <span className={`w-2.5 h-2.5 rounded-full ${color}`} />
                                    <span className="font-mono text-xs text-on-surface">{label}</span>
                                </div>
                            ))}
                        </div>
                    </div>

                    <ResponsiveContainer width="100%" height={280}>
                        <AreaChart data={trendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                            <defs>
                                <linearGradient id="gradScore" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#c0c1ff" stopOpacity={0.25} />
                                    <stop offset="95%" stopColor="#c0c1ff" stopOpacity={0} />
                                </linearGradient>
                                <linearGradient id="gradCost" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#00a2e6" stopOpacity={0.15} />
                                    <stop offset="95%" stopColor="#00a2e6" stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="0" stroke="#1c1b1b" vertical={false} />
                            <XAxis
                                dataKey="day"
                                tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, fill: "#908fa0" }}
                                axisLine={false}
                                tickLine={false}
                            />
                            <YAxis
                                tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, fill: "#908fa0" }}
                                axisLine={false}
                                tickLine={false}
                            />
                            <RechartsTooltip content={<CustomTooltip />} cursor={{ stroke: "#464554", strokeWidth: 1 }} />
                            <Area
                                type="monotone"
                                dataKey="score"
                                stroke="#c0c1ff"
                                strokeWidth={2.5}
                                fill="url(#gradScore)"
                                dot={false}
                                activeDot={{ r: 4, fill: "#c0c1ff", strokeWidth: 0 }}
                            />
                            <Area
                                type="monotone"
                                dataKey="cost"
                                stroke="#00a2e6"
                                strokeWidth={2}
                                strokeDasharray="8 4"
                                fill="url(#gradCost)"
                                dot={false}
                                activeDot={{ r: 4, fill: "#00a2e6", strokeWidth: 0 }}
                            />
                        </AreaChart>
                    </ResponsiveContainer>
                </section>

                {/* ── Measured insights (Phase 8) ── */}
                <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <CoachingImpactCard />
                </section>

                {/* ── Leaderboard ── */}
                <section className="flex flex-col gap-4">
                    <div className="flex justify-between items-end">
                        <div>
                            <h2 className="text-lg font-bold text-on-surface">Team Leaderboard</h2>
                            <p className="text-sm text-on-surface-variant mt-0.5">
                                Individual performance metrics breakdown
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => downloadLeaderboardCsv(team)}
                            className="flex items-center gap-1.5 text-primary font-mono text-xs tracking-wide hover:underline cursor-pointer"
                        >
                            EXPORT CSV
                            <Download size={16} />
                        </button>
                    </div>

                    <div className="glass-card rounded-xl overflow-hidden border border-outline-variant">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="bg-[#0e0e0e] border-b border-outline-variant">
                                    {["Rank", "Name", "Efficiency Score", "Daily Spend", "Activity"].map((h, i) => (
                                        <th
                                            key={h}
                                            className={`px-4 py-3 font-mono text-[11px] tracking-widest uppercase text-on-surface-variant font-medium ${i === 4 ? "text-right" : ""}`}
                                        >
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {team.map((member, idx) => (
                                    // Find your <tr> tag and update the onClick handler to this:
                                    <tr
                                        key={member.user_id}
                                        onClick={() => navigate(`/engineer/${member.user_id}`)}
                                        className={[
                                            "transition-colors duration-150 cursor-pointer",
                                            idx < team.length - 1 ? "border-b border-outline-variant/30" : "",
                                            hoveredRow === idx ? "bg-surface-container-high" : "",
                                        ].join(" ")}
                                        onMouseEnter={() => setHoveredRow(idx)}
                                        onMouseLeave={() => setHoveredRow(null)}
                                    >
                                        {/* Rank */}
                                        <td className="px-4 py-3.5">
                                            {member.rankColor ? (
                                                <div
                                                    className="w-8 h-8 rounded flex items-center justify-center text-sm font-black"
                                                    style={{
                                                        background: `${member.rankColor}1a`,
                                                        border: `1px solid ${member.rankColor}4d`,
                                                        color: member.rankColor,
                                                    }}
                                                >
                                                    {member.rank}
                                                </div>
                                            ) : (
                                                <div className="w-8 h-8 flex items-center justify-center text-on-surface-variant font-bold text-sm">
                                                    {member.rank}
                                                </div>
                                            )}
                                        </td>

                                        {/* Name */}
                                        <td className="px-4 py-3.5">
                                            <span className="font-bold text-sm text-on-surface">{member.name}</span>
                                        </td>

                                        {/* Score */}
                                        <td className="px-4 py-3.5 font-mono text-sm text-on-surface">
                                            {member.score}{" "}
                                            <span
                                                className={`text-[10px] ${member.trend === "up"
                                                    ? "text-emerald-500"
                                                    : member.trend === "down"
                                                        ? "text-rose-500"
                                                        : "text-on-surface-variant"
                                                    }`}
                                            >
                                                {member.trendVal}
                                            </span>
                                        </td>

                                        {/* Spend */}
                                        <td className="px-4 py-3.5 font-mono text-sm text-on-surface">
                                            {member.spend}
                                        </td>

                                        {/* Activity */}
                                        <td className="px-4 py-3.5 text-right">
                                            <Sparkline bars={member.bars} faded={!member.rankColor} />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>

                {/* ── Alert Configuration ── */}
                <section className="glass-card rounded-xl p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mt-4">
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <Settings size={18} className="text-primary" />
                            <h2 className="text-lg font-bold text-on-surface">Alert Schedule</h2>
                        </div>
                        <p className="text-sm text-on-surface-variant">Configure automated runbook dispatch</p>
                    </div>

                    <div className="flex flex-wrap items-center gap-4">
                        <select
                            value={alertFreq}
                            onChange={(e) => setAlertFreq(e.target.value)}
                            className="bg-surface-container-high border border-outline-variant rounded-lg px-3 py-2 text-sm font-mono text-on-surface focus:outline-none focus:border-primary cursor-pointer"
                        >
                            <option value="Daily">Daily</option>
                            <option value="Weekly">Weekly</option>
                        </select>

                        {alertFreq === "Weekly" ? (
                            <select
                                value={alertDay}
                                onChange={(e) => setAlertDay(e.target.value)}
                                className="bg-surface-container-high border border-outline-variant rounded-lg px-3 py-2 text-sm font-mono text-on-surface focus:outline-none focus:border-primary cursor-pointer"
                            >
                                <option value="Monday">Monday</option>
                                <option value="Wednesday">Wednesday</option>
                                <option value="Friday">Friday</option>
                            </select>
                        ) : null}

                        <input
                            type="time"
                            value={alertTime}
                            onChange={(e) => setAlertTime(e.target.value)}
                            className="bg-surface-container-high border border-outline-variant rounded-lg px-3 py-2 text-sm font-mono text-on-surface focus:outline-none focus:border-primary cursor-pointer"
                        />
                        <span
                            className="font-mono text-[11px] text-on-surface-variant"
                            title={alertTz === BROWSER_TZ ? "Schedule timezone" : `Saving will switch the schedule to ${BROWSER_TZ}`}
                        >
                            {alertTz}
                        </span>

                        <button
                            onClick={handleSaveSchedule}
                            className="bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 px-4 py-2 rounded-lg font-mono text-xs tracking-wide transition-colors cursor-pointer"
                        >
                            SAVE SYNC
                        </button>
                        
                        <button
                            onClick={handleTestAlerts}
                            disabled={isTestingAlerts}
                            className="flex items-center gap-2 bg-secondary/10 hover:bg-secondary/20 text-secondary border border-secondary/30 px-4 py-2 rounded-lg font-mono text-xs tracking-wide transition-colors cursor-pointer disabled:opacity-50"
                        >
                            {isTestingAlerts ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <Mail size={14} />
                            )}
                            TEST ALERTS NOW
                        </button>
                    </div>
                </section>
            </div>
            
            {/* Toast Notification */}
            {showToast && (
                <div className="fixed bottom-20 md:bottom-10 left-1/2 transform -translate-x-1/2 z-[100] animate-in fade-in slide-in-from-bottom-4 duration-300">
                    <div className="flex items-center gap-3 bg-surface-container-highest border border-outline px-6 py-3 rounded-full shadow-lg">
                        <CheckCircle size={18} className="text-primary" />
                        <span className="font-mono text-xs text-on-surface tracking-wide">{toastMessage}</span>
                    </div>
                </div>
            )}

        </div>
    );
}