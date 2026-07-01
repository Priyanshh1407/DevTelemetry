import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
    AreaChart, Area, BarChart, Bar, XAxis, YAxis,
    CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
    PieChart, Pie, Cell
} from "recharts";
import {
    ArrowLeft, Calendar, User, Mail, Award, AlertTriangle, CheckCircle, Info,
    Activity, Bot, BookOpen, Compass, Code, Cpu, RefreshCw, BarChart2, Coins
} from "lucide-react";
import Navbar from "../components/Navbar";

// Helper for matching severity color classes
const severityStyles = {
    low: {
        bg: "bg-[#4ade80]/10 border-[#4ade80]/30 text-[#4ade80]",
        dot: "bg-[#4ade80]"
    },
    moderate: {
        bg: "bg-tertiary/10 border-tertiary/30 text-tertiary",
        dot: "bg-tertiary"
    },
    critical: {
        bg: "bg-error/10 border-error/30 text-error",
        dot: "bg-error"
    }
};

// Custom Chart Tooltips
function ScoreTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null;
    return (
        <div className="glass-card rounded-lg px-4 py-3 font-mono text-xs text-on-surface min-w-[140px]">
            <p className="text-on-surface-variant mb-1">{label}</p>
            <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-primary" />
                <span className="text-on-surface-variant">Score:</span>
                <span className="font-bold ml-auto">{payload[0].value}</span>
            </div>
        </div>
    );
}

function CostTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null;
    return (
        <div className="glass-card rounded-lg px-4 py-3 font-mono text-xs text-on-surface min-w-[140px]">
            <p className="text-on-surface-variant mb-1">{label}</p>
            <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-secondary-container" />
                <span className="text-on-surface-variant">Cost:</span>
                <span className="font-bold ml-auto">${Number(payload[0].value).toFixed(2)}</span>
            </div>
        </div>
    );
}

export default function EngineerDetail() {
    const { userId } = useParams();
    const navigate = useNavigate();

    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchDetails = async () => {
            try {
                const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
                const res = await fetch(`${API_BASE}/api/engineer/${userId}/details`);
                if (!res.ok) {
                    throw new Error(res.status === 404 ? "Engineer not found" : "Failed to load engineer details");
                }
                const json = await res.json();
                setData(json);
            } catch (err) {
                console.error(err);
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };
        fetchDetails();
    }, [userId]);

    if (loading) {
        return (
            <div className="min-h-screen bg-background text-on-surface font-body flex flex-col">
                <Navbar />
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                    <RefreshCw size={36} className="text-primary animate-spin" />
                    <p className="font-mono text-sm text-on-surface-variant animate-pulse tracking-widest uppercase">
                        Fetching engineer analytics...
                    </p>
                </div>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="min-h-screen bg-background text-on-surface font-body flex flex-col">
                <Navbar />
                <div className="flex-1 flex flex-col items-center justify-center gap-4 max-w-md mx-auto text-center px-4">
                    <AlertTriangle size={48} className="text-error" />
                    <h2 className="text-2xl font-bold text-on-surface">Error Loading Data</h2>
                    <p className="text-sm text-on-surface-variant">{error || "Something went wrong."}</p>
                    <Link to="/" className="mt-4 px-6 py-2 bg-primary/15 hover:bg-primary/25 border border-primary/30 text-primary rounded-lg font-mono text-xs transition-all">
                        Back to Dashboard
                    </Link>
                </div>
            </div>
        );
    }

    const { name, email, current_rank, current_severity, latest, history, averages, patterns } = data;

    // Build chart-friendly history array (format date string)
    const formattedHistory = history.map(item => ({
        ...item,
        formattedDate: item.date.slice(5) // "10-24" instead of "2026-10-24"
    }));

    // Pie chart model mix data
    const pieData = [
        { name: "Sonnet", value: latest.sonnet_pct * 100, color: "#c0c1ff" },
        { name: "Haiku", value: latest.haiku_pct * 100, color: "#89ceff" },
        { name: "Opus", value: latest.opus_pct * 100, color: "#ffb783" }
    ].filter(item => item.value > 0);

    // Dynamic severity classes
    const sevClass = severityStyles[current_severity] || severityStyles.moderate;

    // Profile avatar based on name character hash
    const avatarIndex = (name.charCodeAt(0) + name.length) % 10;
    const avatarUrl = `http://googleusercontent.com/profile/picture/${avatarIndex}`;

    return (
        <div className="min-h-screen bg-background text-on-surface font-body pb-12">
            <Navbar />

            <div className="max-w-[1440px] mx-auto px-6 md:px-10 py-8 flex flex-col gap-8">

                {/* ── Back Navigation & Action Bar ── */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <button
                        onClick={() => navigate("/")}
                        className="inline-flex items-center gap-2 text-on-surface-variant hover:text-primary transition-colors font-mono text-xs tracking-wider"
                    >
                        <ArrowLeft size={16} /> BACK TO LEADERBOARD
                    </button>

                    <Link
                        to={`/runbook/${current_severity}/${userId}`}
                        className="inline-flex items-center justify-center gap-2 bg-primary text-on-primary-container px-5 py-2.5 rounded-lg font-mono text-xs font-bold hover:brightness-110 active:scale-[0.98] transition-all"
                    >
                        <BookOpen size={16} /> VIEW PERSONAL OPTIMIZATION RUNBOOK
                    </Link>
                </div>

                {/* ── Header Card & KPI Summary Row ── */}
                <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Profile Information */}
                    <div className="glass-card rounded-xl p-6 relative overflow-hidden flex flex-col justify-between col-span-1 lg:col-span-2">
                        <div
                            className="absolute inset-0 opacity-5 pointer-events-none"
                            style={{
                                backgroundImage: "radial-gradient(circle at 2px 2px, #c0c1ff 1px, transparent 0)",
                                backgroundSize: "24px 24px",
                            }}
                        />
                        <div className="flex items-start gap-4 relative z-10">
                            <img
                                src={avatarUrl}
                                alt={name}
                                className="w-16 h-16 rounded-full border border-outline-variant object-cover shrink-0"
                            />
                            <div className="flex flex-col gap-1.5">
                                <h1 className="text-2xl font-bold tracking-tight text-on-surface">{name}</h1>
                                <div className="flex items-center gap-1.5 text-on-surface-variant text-sm font-mono">
                                    <Mail size={14} /> {email}
                                </div>
                                <div className="flex flex-wrap gap-2 mt-1">
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-surface-container border border-outline-variant font-mono text-xs text-on-surface">
                                        <Award size={12} className="text-secondary" /> Rank #{current_rank}
                                    </span>
                                    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full border font-mono text-xs font-bold uppercase tracking-wider ${sevClass.bg}`}>
                                        <span className={`w-1.5 h-1.5 rounded-full ${sevClass.dot}`} /> {current_severity} severity
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div className="mt-6 border-t border-outline-variant/30 pt-4 flex justify-between items-center relative z-10">
                            <div className="flex items-baseline gap-2">
                                <span className="font-mono text-xs text-on-surface-variant uppercase tracking-wider">Latest Score:</span>
                                <span className="text-2xl font-black text-on-surface">{latest.efficiency_score}</span>
                                <span className="text-sm text-on-surface-variant">/100</span>
                            </div>
                            <div className="flex items-baseline gap-2">
                                <span className="font-mono text-xs text-on-surface-variant uppercase tracking-wider">Latest 1d Cost:</span>
                                <span className="text-2xl font-black text-on-surface">${latest.estimated_cost_usd.toFixed(2)}</span>
                            </div>
                        </div>
                    </div>

                    {/* Quick Gauge / Gauge Placeholder Container */}
                    <div className="glass-card rounded-xl p-6 flex flex-col justify-between items-center text-center">
                        <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant mb-2">
                            30-Day Efficiency Score
                        </span>

                        <div className="relative w-32 h-32 flex items-center justify-center">
                            {/* Radial Score Gauge SVG */}
                            <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
                                <circle
                                    cx="50"
                                    cy="50"
                                    fill="none"
                                    r="40"
                                    stroke="#2a2a2a"
                                    strokeWidth="8"
                                />
                                <circle
                                    cx="50"
                                    cy="50"
                                    fill="none"
                                    r="40"
                                    stroke="var(--color-primary)"
                                    strokeDasharray="251.2"
                                    strokeDashoffset={251.2 - (251.2 * averages.avg_score) / 100}
                                    strokeWidth="8"
                                    strokeLinecap="round"
                                    style={{ transition: "stroke-dashoffset 1s ease-out" }}
                                />
                            </svg>
                            <div className="absolute inset-0 flex flex-col items-center justify-center">
                                <span className="text-3xl font-black text-on-surface leading-none">{averages.avg_score}</span>
                                <span className="text-[10px] font-mono text-on-surface-variant uppercase tracking-widest mt-1">Average</span>
                            </div>
                        </div>

                        <p className="text-xs text-on-surface-variant mt-2 max-w-[200px]">
                            {averages.avg_score >= 80 ? "Excellent token stewardship and habit discipline." :
                                averages.avg_score >= 55 ? "Moderate efficiency. Personal roadmap shows areas to optimize." :
                                    "Requires prompt structure calibration and model mix adjusting."}
                        </p>
                    </div>
                </section>

                {/* ── Averages Grid (4 Cards) ── */}
                <section className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                    {/* Cache Hit Ratio */}
                    <div className="glass-card rounded-xl p-5 group">
                        <div className="flex justify-between items-start mb-2">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">Avg Cache Hit</span>
                            <Cpu size={18} className="text-primary/40 group-hover:text-primary/70 transition-colors" />
                        </div>
                        <div className="text-2xl font-bold tracking-tight text-on-surface">
                            {(averages.avg_cache_ratio * 100).toFixed(1)}%
                        </div>
                        <p className="text-[10px] text-on-surface-variant mt-1">Target is &gt;60% hit ratio</p>
                    </div>

                    {/* Daily Sessions */}
                    <div className="glass-card rounded-xl p-5 group">
                        <div className="flex justify-between items-start mb-2">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">Daily Sessions</span>
                            <Activity size={18} className="text-secondary/40 group-hover:text-secondary/70 transition-colors" />
                        </div>
                        <div className="text-2xl font-bold tracking-tight text-on-surface">
                            {averages.avg_sessions}
                        </div>
                        <p className="text-[10px] text-on-surface-variant mt-1">Simultaneous terminals active</p>
                    </div>

                    {/* Git Commits */}
                    <div className="glass-card rounded-xl p-5 group">
                        <div className="flex justify-between items-start mb-2">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">Git Commits</span>
                            <Code size={18} className="text-tertiary/40 group-hover:text-tertiary/70 transition-colors" />
                        </div>
                        <div className="text-2xl font-bold tracking-tight text-on-surface">
                            {averages.total_commits}
                        </div>
                        <p className="text-[10px] text-on-surface-variant mt-1">30-day development checkins</p>
                    </div>

                    {/* /compact Usage */}
                    <div className="glass-card rounded-xl p-5 group">
                        <div className="flex justify-between items-start mb-2">
                            <span className="font-mono text-[11px] tracking-widest uppercase text-on-surface-variant">/compact Rate</span>
                            <RefreshCw size={18} className="text-error/40 group-hover:text-error/70 transition-colors" />
                        </div>
                        <div className="text-2xl font-bold tracking-tight text-on-surface">
                            {(averages.avg_compact_ratio * 100).toFixed(1)}%
                        </div>
                        <p className="text-[10px] text-on-surface-variant mt-1">Sessions run with compact command</p>
                    </div>
                </section>

                {/* ── Main Graphs Section ── */}
                <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Score Trend (AreaChart) */}
                    <div className="glass-card rounded-xl p-6 col-span-1 lg:col-span-2 flex flex-col">
                        <div className="mb-6">
                            <h2 className="text-base font-bold text-on-surface">30-Day Efficiency Score Trend</h2>
                            <p className="text-xs text-on-surface-variant">Aggregate daily score changes</p>
                        </div>

                        <div className="w-full h-64">
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={formattedHistory} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                                    <defs>
                                        <linearGradient id="detailScoreGrad" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#c0c1ff" stopOpacity={0.25} />
                                            <stop offset="95%" stopColor="#c0c1ff" stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="0" stroke="#1c1b1b" vertical={false} />
                                    <XAxis
                                        dataKey="formattedDate"
                                        tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fill: "#908fa0" }}
                                        axisLine={false}
                                        tickLine={false}
                                    />
                                    <YAxis
                                        domain={[0, 100]}
                                        tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fill: "#908fa0" }}
                                        axisLine={false}
                                        tickLine={false}
                                    />
                                    <RechartsTooltip content={<ScoreTooltip />} cursor={{ stroke: "#464554", strokeWidth: 1 }} />
                                    <Area
                                        type="monotone"
                                        dataKey="efficiency_score"
                                        stroke="#c0c1ff"
                                        strokeWidth={2}
                                        fill="url(#detailScoreGrad)"
                                        dot={false}
                                        activeDot={{ r: 4, fill: "#c0c1ff", strokeWidth: 0 }}
                                    />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* Model Mix (Pie Chart) */}
                    <div className="glass-card rounded-xl p-6 flex flex-col justify-between">
                        <div>
                            <h2 className="text-base font-bold text-on-surface">Latest Model Mix</h2>
                            <p className="text-xs text-on-surface-variant">Distribution of token requests</p>
                        </div>

                        <div className="w-full h-44 my-2 relative flex items-center justify-center">
                            <ResponsiveContainer width="100%" height="100%">
                                <PieChart>
                                    <Pie
                                        data={pieData}
                                        cx="50%"
                                        cy="50%"
                                        innerRadius={50}
                                        outerRadius={70}
                                        paddingAngle={4}
                                        dataKey="value"
                                    >
                                        {pieData.map((entry, index) => (
                                            <Cell key={`cell-${index}`} fill={entry.color} />
                                        ))}
                                    </Pie>
                                </PieChart>
                            </ResponsiveContainer>
                        </div>

                        <div className="flex flex-col gap-2">
                            {pieData.map((item) => (
                                <div key={item.name} className="flex items-center justify-between text-xs font-mono">
                                    <div className="flex items-center gap-2">
                                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                                        <span className="text-on-surface-variant">{item.name}</span>
                                    </div>
                                    <span className="font-bold text-on-surface">{item.value.toFixed(0)}%</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </section>

                {/* ── Daily Spend Graph & Patterns (Insights) Row ── */}
                <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Cost Trend (BarChart) */}
                    <div className="glass-card rounded-xl p-6 col-span-1 lg:col-span-2 flex flex-col">
                        <div className="mb-6">
                            <h2 className="text-base font-bold text-on-surface">30-Day Estimated Cost Trend</h2>
                            <p className="text-xs text-on-surface-variant">Daily calculated spent in USD</p>
                        </div>

                        <div className="w-full h-64">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart data={formattedHistory} margin={{ top: 5, right: 5, left: -25, bottom: 0 }}>
                                    <CartesianGrid strokeDasharray="0" stroke="#1c1b1b" vertical={false} />
                                    <XAxis
                                        dataKey="formattedDate"
                                        tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fill: "#908fa0" }}
                                        axisLine={false}
                                        tickLine={false}
                                    />
                                    <YAxis
                                        tick={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fill: "#908fa0" }}
                                        axisLine={false}
                                        tickLine={false}
                                    />
                                    <RechartsTooltip content={<CostTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                                    <Bar
                                        dataKey="estimated_cost_usd"
                                        fill="#00a2e6"
                                        radius={[2, 2, 0, 0]}
                                        maxBarSize={15}
                                    />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* AI Insights & Usage Patterns */}
                    <div className="glass-card rounded-xl p-6 flex flex-col gap-4">
                        <div>
                            <h2 className="text-base font-bold text-on-surface flex items-center gap-2">
                                <Bot size={18} className="text-primary" /> AI Usage Patterns
                            </h2>
                            <p className="text-xs text-on-surface-variant mt-0.5">Automated telemetry diagnostics</p>
                        </div>

                        <div className="flex flex-col gap-4 flex-1 justify-center">
                            {patterns.map((pat, idx) => (
                                <div
                                    key={idx}
                                    className="p-4 rounded-lg bg-surface-container-low border border-outline-variant flex gap-3 hover:translate-x-1 transition-transform"
                                >
                                    <div className="p-1 rounded bg-primary/10 text-primary h-fit">
                                        <Info size={16} />
                                    </div>
                                    <div className="flex flex-col gap-1">
                                        <span className="text-xs font-bold text-on-surface uppercase tracking-wide font-mono">
                                            {pat.label}
                                        </span>
                                        <span className="text-xs text-on-surface-variant leading-relaxed">
                                            {pat.insight}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </section>

            </div>
        </div>
    );
}
