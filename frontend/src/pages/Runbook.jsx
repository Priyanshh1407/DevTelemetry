import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
    ResponsiveContainer, LineChart, Line,
} from "recharts";
import {
    Search, Bell, Settings, History, Timer, Code, Zap,
    TrendingDown, TrendingUp, AlertTriangle, CheckCircle,
    Star, Users, Terminal, Play, ExternalLink, Plus,
    ArrowLeft, Coins, ArrowRight, Info, Loader2
} from "lucide-react";

import { getJSON } from "../api";

// ─── Shared Header ────────────────────────────────────────────────────────
function RunbookHeader() {
    return (
        <nav className="bg-background border-b border-outline-variant sticky top-0 z-50">
            <div className="flex justify-between items-center w-full px-6 md:px-10 max-w-[1440px] mx-auto h-16">
                <div className="flex items-center gap-6">
                    <Link to="/" className="font-display text-xl font-bold text-primary flex items-center gap-2">
                        <ArrowLeft size={18} className="text-on-surface-variant hover:text-primary transition-colors" />
                        SeverityRunbook
                    </Link>
                    <div className="hidden md:flex gap-4 ml-8">
                        {/* Removed the Dashboard link as requested */}
                        <span className="font-mono text-xs text-primary border-b-2 border-primary pb-1 py-2 tracking-wide">Runbooks</span>
                    </div>
                </div>
                <div className="flex items-center gap-4">
                    <div className="relative hidden sm:block">
                        <Search size={14} className="absolute left-2.5 top-1/2 transform -translate-y-1/2 text-on-surface-variant" />
                        <input
                            type="text"
                            placeholder="Search..."
                            className="bg-surface-container-high border border-outline-variant rounded pl-8 pr-3 py-1.5 text-sm text-on-surface focus:outline-none focus:border-primary w-48"
                        />
                    </div>
                    <button
                        onClick={() => alert("Opening New Incident Modal...")}
                        className="bg-primary text-on-primary-container font-mono text-xs font-bold px-4 py-2 rounded hover:bg-primary/90 transition-all scale-95"
                    >
                        New Incident
                    </button>
                    <div className="flex gap-2 text-on-surface-variant">
                        <button onClick={() => alert("Notifications panel")} className="p-1 hover:text-primary transition-colors"><Bell size={20} /></button>
                        <button onClick={() => alert("Settings panel")} className="p-1 hover:text-primary transition-colors"><Settings size={20} /></button>
                    </div>
                    <div className="w-8 h-8 rounded-full bg-surface-variant overflow-hidden border border-outline-variant ml-2 cursor-pointer" onClick={() => alert("User Profile")}>
                        <img src="https://lh3.googleusercontent.com/aida-public/AB6AXuBoX4OdKnDzoT8tUrdS-VqiOdL9fLezyVh4repgRZqk3sOj6Y8Nu1a_hRjnBwWEHdmkYFO0n0xI5FK-w6ZU8d5nWK1cvBVUMWUH-fkGy9c5XM8v36y-RFs2lqFAm4SOegdnECf6-VP4wUorm_TjdLwW0zIPaAWIcitF8WgXl0mxxKA6uR_H4_rEmCyn1sP1YoKj-_eY_W0vfel_1yLyfurbk7PXDlQYUeLHSnRsG5Dg-YLbXWf6SMBrxcPd9xS7zpToUnVjg7LciA" alt="Profile" className="w-full h-full object-cover" />
                    </div>
                </div>
            </div>
        </nav>
    );
}

// ─── Reusable Task List Component ─────────────────────────────────────────
function TaskList({ tasks, toggleTask, themeClass }) {
    const checkedCount = tasks.filter(t => t.checked).length;

    return (
        <div className="glass-card rounded-xl mt-4 overflow-hidden bg-surface-container-lowest border border-outline-variant">
            <div className="border-b border-outline-variant bg-surface-container-high px-6 py-4 flex justify-between items-center">
                <h2 className="text-xl font-bold text-on-surface">AI Optimization Roadmap</h2>
                <span className={`font-mono text-xs ${themeClass}`}>{checkedCount}/{tasks.length} Completed</span>
            </div>
            <ul className="divide-y divide-outline-variant">
                <div className="space-y-4">
                    {tasks.map((task) => (
                        <label key={task.id} className="flex items-center p-4 rounded-lg bg-surface-container-low border border-outline-variant hover:bg-surface-container-high cursor-pointer transition-colors group">
                            <input
                                type="checkbox"
                                checked={task.checked}
                                onChange={() => toggleTask(task.id)}
                                className="w-5 h-5 rounded border-outline-variant bg-transparent text-primary focus:ring-primary focus:ring-offset-background transition-all"
                            />
                            {/* Changed from a single span to a title and description layout */}
                            <div className="ml-4 flex flex-col">
                                <span className={`text-base font-bold text-on-surface transition-transform ${task.checked ? 'line-through opacity-50' : 'group-hover:translate-x-1'}`}>
                                    {task.title}
                                </span>
                                <span className={`text-sm text-on-surface-variant transition-transform ${task.checked ? 'opacity-50' : 'group-hover:translate-x-1'}`}>
                                    {task.desc}
                                </span>
                            </div>
                            <ArrowRight size={20} className="ml-auto text-on-surface-variant opacity-0 group-hover:opacity-100 transition-opacity" />
                        </label>
                    ))}
                </div>
            </ul>
        </div>
    );
}

// ─── Critical Layout ──────────────────────────────────────────────────────
function CriticalRunbook({ tasks, toggleTask }) {
    const navigate = useNavigate();
    const spikeData = [
        { time: '1', cost: 10 }, { time: '2', cost: 12 }, { time: '3', cost: 8 },
        { time: '4', cost: 14 }, { time: '5', cost: 10 }, { time: '6', cost: 16 },
        { time: '7', cost: 12 }, { time: '8', cost: 8 }, { time: '9', cost: 60 },
        { time: '10', cost: 70 }, { time: '11', cost: 76 }
    ];

    return (
        <div className="min-h-screen bg-background text-on-surface font-body selection:bg-primary/30 flex flex-col">
            <style>{`
        .glow-red { box-shadow: 0 0 40px rgba(147, 0, 10, 0.15); }
        .shimmer {
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.03), transparent);
          background-size: 200% 100%;
          animation: shimmer 3s infinite linear;
        }
        @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
      `}</style>

            <header className="fixed top-0 left-0 w-full z-50 bg-background/80 backdrop-blur-md border-b border-outline-variant h-16 flex items-center">
                <div className="flex justify-between items-center w-full px-10 max-w-[1440px] mx-auto h-full">
                    <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                        <Terminal size={24} className="text-primary" />
                        <span className="font-display text-xl font-bold text-primary">DevTelemetry</span>
                    </Link>
                    <div className="flex items-center gap-4">
                        <span className="font-mono text-xs text-on-surface-variant tracking-widest uppercase">Optimization Runbook</span>
                        <div className="w-2 h-2 rounded-full bg-error animate-pulse"></div>
                    </div>
                </div>
            </header>

            <main className="pt-24 pb-8 px-10 max-w-[1440px] w-full mx-auto flex-1">
                <section className="relative mb-8 p-8 rounded-xl border-2 border-error-container bg-surface-container-lowest overflow-hidden glow-red">
                    <div className="absolute inset-0 shimmer opacity-50"></div>
                    <div className="relative z-10 flex flex-col md:flex-row md:items-end justify-between gap-4">
                        <div className="max-w-2xl">
                            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-error-container/20 border border-error-container mb-2">
                                <AlertTriangle size={16} className="text-error" />
                                <span className="font-mono text-xs text-error uppercase">Severity: Critical</span>
                            </div>
                            <h1 className="font-display text-5xl text-on-surface mb-2 leading-tight font-bold">Critical Efficiency Runbook</h1>
                            <p className="text-base text-on-surface-variant max-w-xl">
                                Deployed when LLM token usage significantly outpaces code output, indicating prompt looping or lack of batching. Immediate intervention required to stabilize operational overhead.
                            </p>
                        </div>
                        <div className="flex flex-col items-start md:items-end gap-1">
                            <span className="font-mono text-xs text-on-surface-variant">Last Triggered</span>
                            <span className="font-display text-xl font-bold text-on-surface">2m 44s ago</span>
                        </div>
                    </div>
                </section>

                <section className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                    <div className="group p-4 bg-surface-container-low border border-outline-variant rounded-lg hover:border-primary transition-all duration-300">
                        <div className="flex items-center justify-between mb-4">
                            <span className="p-2 bg-primary-container/10 rounded-lg"><Timer size={20} className="text-primary-container" /></span>
                            <span className="font-mono text-xs text-on-surface-variant">System Target</span>
                        </div>
                        <h3 className="text-2xl font-bold text-on-surface mb-1">MTTR: 4h</h3>
                        <p className="text-xs text-on-surface-variant font-medium">Mean Time To Resolution</p>
                        <div className="mt-4 h-1 w-full bg-surface-container-high rounded-full overflow-hidden">
                            <div className="h-full bg-primary w-2/3 group-hover:w-3/4 transition-all duration-700"></div>
                        </div>
                    </div>
                    <div className="group p-4 bg-surface-container-low border border-outline-variant rounded-lg hover:border-secondary transition-all duration-300">
                        <div className="flex items-center justify-between mb-4">
                            <span className="p-2 bg-secondary-container/10 rounded-lg"><Code size={20} className="text-secondary-container" /></span>
                            <span className="font-mono text-xs text-on-surface-variant">Architecture</span>
                        </div>
                        <h3 className="text-2xl font-bold text-on-surface mb-1">Ratio: 1:5</h3>
                        <p className="text-xs text-on-surface-variant font-medium">Ideal Refactor Ratio</p>
                        <div className="mt-4 h-1 w-full bg-surface-container-high rounded-full overflow-hidden">
                            <div className="h-full bg-secondary w-1/2 group-hover:w-2/3 transition-all duration-700"></div>
                        </div>
                    </div>
                    <div className="group p-4 bg-surface-container-low border border-outline-variant rounded-lg hover:border-tertiary transition-all duration-300">
                        <div className="flex items-center justify-between mb-4">
                            <span className="p-2 bg-tertiary-container/10 rounded-lg"><Coins size={20} className="text-tertiary-container" /></span>
                            <span className="font-mono text-xs text-on-surface-variant">Efficiency</span>
                        </div>
                        <h3 className="text-2xl font-bold text-on-surface mb-1">&gt; 85%</h3>
                        <p className="text-xs text-on-surface-variant font-medium">Token Utilization Accuracy</p>
                        <div className="mt-4 h-1 w-full bg-surface-container-high rounded-full overflow-hidden">
                            <div className="h-full bg-tertiary w-4/5 group-hover:w-[90%] transition-all duration-700"></div>
                        </div>
                    </div>
                </section>

                <div className="flex flex-col lg:flex-row gap-6">
                    <div className="flex-1">
                        <TaskList tasks={tasks} toggleTask={toggleTask} themeClass="text-error" />
                        <div className="mt-6 p-4 bg-primary-container/10 border border-primary-container/20 rounded-lg flex items-center gap-4">
                            <Info size={24} className="text-primary-container" />
                            <p className="text-xs text-on-surface-variant font-medium">Completing 3/5 tasks will automatically downgrade severity to 'Moderate'.</p>
                        </div>
                    </div>

                    <div className="w-full lg:w-80 flex flex-col gap-6">
                        <div className="p-4 bg-surface-container border border-outline-variant rounded-xl flex flex-col gap-4">
                            <h4 className="font-mono text-xs text-on-surface-variant uppercase tracking-tighter mb-2">Active Stakeholders</h4>
                            <div className="overflow-x-auto">
                                <table className="w-full text-left border-collapse">
                                    <thead className="border-b border-outline-variant">
                                        <tr className="font-mono text-[10px] text-on-surface-variant uppercase">
                                            <th className="pb-2 font-medium">Stakeholder</th>
                                            <th className="pb-2 font-medium">Role</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-outline-variant/30">
                                        <tr>
                                            <td className="py-3"><div className="flex items-center gap-2"><img src="https://lh3.googleusercontent.com/aida-public/AB6AXuA_hMb0N3tT4RdwuWeFn5-FtxzZjFatznNiidGdEcoaJDDA8sEEKyITXsDDGxu0LmNCt8JmVWJCOx8_DBN0YDKluO6oJZOjXreSmQ-gDi8kqvaHKHgy7xh59vx8gQGupDrnYMYU4wuxd-Z_iTNfzMEo4JGEHR6DMqzuOU_4LAPIM8FtIL-JblqxOjPYeYvJYt09ubYyg5rGHZsHNaW-ueRKk8WXVhbmZn1rGLbfus3Th_2pJA4tXNpba3tNJ29vkV_IhKkurwfJww" className="w-6 h-6 rounded-full" /><span className="text-xs font-bold">Marcus V.</span></div></td>
                                            <td className="py-3 text-[11px] text-on-surface-variant">Lead Architect</td>
                                        </tr>
                                        <tr>
                                            <td className="py-3"><div className="flex items-center gap-2"><img src="https://lh3.googleusercontent.com/aida-public/AB6AXuBIAy_7Y1jHONocc7tw1Ga3rdwGqojCCtSVU74DcZ3PjjFGJn617wQwAWfQ8Z3FG7oZBPXsiWycpvIoGDPuA5tSjBXn5Hc3YsDlji5Mzg8lioXlQLkI6AAE1o1WxC8yUrJFa76ajQvWTFJHfknevTImBngpRCXN000dd-fDRco8SRyQgOe_aArJAdkalTeKL9eeSVjmALxTd60acW_74wBOmO0lRZAN1frdDefHMS3W-DTohAVMi4x3g5bGb6wPavoBr-5V_blpNA" className="w-6 h-6 rounded-full" /><span className="text-xs font-bold">Sarah L.</span></div></td>
                                            <td className="py-3 text-[11px] text-on-surface-variant">DevOps Lead</td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                            <div className="flex flex-col gap-2 mt-2">
                                <button onClick={() => alert("Executing emergency infrastructure patch...")} className="w-full py-2 bg-error text-on-error font-mono text-[11px] rounded hover:brightness-110 active:scale-[0.98] transition-all uppercase font-bold">DEPLOY EMERGENCY PATCH</button>
                                <button onClick={() => navigate("/")} className="w-full py-2 border border-outline-variant text-on-surface font-mono text-[11px] rounded hover:bg-surface-container-high active:scale-[0.98] transition-all uppercase font-bold">VIEW METRICS</button>
                            </div>
                        </div>

                        <div className="relative overflow-hidden p-4 bg-surface-container-low border-2 border-error/30 rounded-xl h-full flex flex-col gap-4">
                            <div className="absolute -right-10 -top-10 w-32 h-32 bg-error/10 rounded-full blur-3xl"></div>
                            <div className="flex justify-between items-start">
                                <div>
                                    <h4 className="font-mono text-xs text-error uppercase mb-1 tracking-wider">Cost Anomaly</h4>
                                    <div className="flex items-baseline gap-2">
                                        <p className="font-display text-3xl font-bold text-on-surface">+$1,420<span className="text-on-surface-variant text-xs font-normal ml-1">/hr</span></p>
                                    </div>
                                </div>
                                <span className="px-2 py-0.5 rounded-full bg-error text-on-error font-mono text-[10px] font-bold">CRITICAL</span>
                            </div>
                            <div className="flex-1 flex flex-col justify-end min-h-[100px]">
                                <div className="mb-2 flex justify-between items-center z-10">
                                    <span className="text-xs font-medium text-on-surface-variant">Detection History</span>
                                    <span className="flex items-center gap-1 font-mono text-[10px] text-error"><span className="w-1.5 h-1.5 rounded-full bg-error animate-ping"></span> Spike detected</span>
                                </div>
                                <div className="relative h-16 w-full z-0 -mx-2">
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={spikeData}>
                                            <Line type="monotone" dataKey="cost" stroke="#ffb4ab" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: '#ffb4ab' }} />
                                        </LineChart>
                                    </ResponsiveContainer>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </main>

            <footer className="mt-8 border-t border-outline-variant bg-background">
                <div className="w-full px-10 py-8 max-w-[1440px] mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
                    <span className="font-mono text-xs text-primary font-bold">DEvTELEMETRY_INFRA_V2</span>
                    <p className="text-sm text-on-surface-variant opacity-60">© 2026 DevTelemetry Infrastructure.</p>
                </div>
            </footer>
        </div>
    );
}

// ─── Moderate Layout ──────────────────────────────────────────────────────
function TuningRunbook({ tasks, toggleTask }) {
    return (
        <div className="flex-1 overflow-y-auto p-4 md:p-10">
            <div className="max-w-[1440px] mx-auto flex flex-col gap-8 xl:flex-row">
                <div className="flex-1 flex flex-col gap-8">
                    <div className="flex flex-col gap-2 md:flex-row md:justify-between md:items-end mb-4">
                        <div>
                            <div className="flex items-center gap-2 mb-2">
                                <span className="px-2 py-1 bg-tertiary-container/20 text-tertiary border border-tertiary-container rounded font-mono text-[10px] uppercase tracking-wider flex items-center gap-1.5">
                                    <span className="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse" /> Moderate
                                </span>
                                <span className="font-mono text-xs text-on-surface-variant">RUN-0842</span>
                            </div>
                            <h1 className="font-display text-4xl font-bold text-on-surface">Efficiency Runbook</h1>
                        </div>
                        <div className="flex items-center gap-2 text-on-surface-variant font-mono text-xs bg-surface-container-low px-3 py-1.5 rounded border border-outline-variant">
                            <History size={14} /> Last Triggered: 24m ago
                        </div>
                    </div>
                    <p className="text-base text-on-surface-variant max-w-3xl">
                        Triggered when developer efficiency metrics show a slight dip or inconsistent patterns. Proactive tuning is recommended to prevent escalation to critical status.
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        <div className="glass-card rounded-xl p-6 shadow-[0_0_20px_rgba(217,119,33,0.15)] flex flex-col justify-between min-h-[140px]">
                            <div className="flex justify-between items-start">
                                <span className="font-mono text-xs text-on-surface-variant uppercase tracking-widest">MTTR Target</span>
                                <Timer size={20} className="text-tertiary" />
                            </div>
                            <div className="mt-4">
                                <div className="text-3xl font-bold text-on-surface">&lt; 6h</div>
                                <div className="text-xs text-tertiary mt-1 flex items-center gap-1"><TrendingDown size={14} /> Current avg: 5.2h</div>
                            </div>
                        </div>
                        <div className="glass-card rounded-xl p-6 flex flex-col justify-between min-h-[140px]">
                            <div className="flex justify-between items-start">
                                <span className="font-mono text-xs text-on-surface-variant uppercase tracking-widest">Ideal Refactor Ratio</span>
                                <Code size={20} className="text-secondary" />
                            </div>
                            <div className="mt-4">
                                <div className="text-3xl font-bold text-on-surface">1:8</div>
                                <div className="text-xs text-secondary mt-1">Features to Technical Debt</div>
                            </div>
                        </div>
                        <div className="glass-card rounded-xl p-6 flex flex-col justify-between min-h-[140px]">
                            <div className="flex justify-between items-start">
                                <span className="font-mono text-xs text-on-surface-variant uppercase tracking-widest">Token Efficiency</span>
                                <Zap size={20} className="text-primary" />
                            </div>
                            <div className="mt-4">
                                <div className="text-3xl font-bold text-on-surface">&gt; 75%</div>
                                <div className="text-xs text-primary mt-1 flex items-center gap-1"><AlertTriangle size={14} /> Currently at 71%</div>
                            </div>
                        </div>
                    </div>

                    <TaskList tasks={tasks} toggleTask={toggleTask} themeClass="text-tertiary" />
                </div>

                <aside className="xl:w-80 flex flex-col gap-8">
                    <div className="glass-card rounded-xl p-6">
                        <h3 className="text-lg font-bold text-on-surface mb-6 flex items-center gap-2"><Users size={20} className="text-on-surface-variant" /> Active Stakeholders</h3>
                        <div className="flex flex-col gap-4">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-full border border-outline-variant relative">
                                    <img src="https://lh3.googleusercontent.com/aida-public/AB6AXuBx7AQu72yRLaDJo52NMkxmYxK8WHHukKa0yHmu3Rx51KcNneZlG3yDY7sGb2k8WmOd7H9rKy0RUVe3X4nUOsUUbCEeq2QiT7ki2XxECVoUCuK9TtokQVN_3pm46OJmgXR0SsvXYudAXgmuyU9kQb9e914cu4z4c4ht7f2yna6i-W0dfOCd1br7vHQwaTWrOe8e4ElGOeKjMFEPnQ52bhPKbyQROi0HI1r5omEfXskzWNiisjojQUkxOncBoTlrFQsCM8xzfygJxQ" alt="Lead" className="w-full h-full rounded-full object-cover" />
                                    <div className="absolute bottom-0 right-0 w-3 h-3 bg-tertiary rounded-full border-2 border-background" />
                                </div>
                                <div><div className="text-sm font-bold text-on-surface">Marcus Chen</div><div className="text-xs text-on-surface-variant">Lead Architect</div></div>
                            </div>
                            <button onClick={() => alert("Paging responder to this runbook...")} className="w-full mt-4 py-2 border border-outline-variant border-dashed rounded text-on-surface-variant hover:text-tertiary hover:border-current transition-colors font-mono text-xs tracking-wide flex items-center justify-center gap-2">
                                <Plus size={16} /> Page Responder
                            </button>
                        </div>
                    </div>

                    <div className="glass-card rounded-xl p-6 bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4IiBoZWlnaHQ9IjgiPgo8cmVjdCB3aWR0aD0iOCIgaGVpZ2h0PSI4IiBmaWxsPSIjMTMxMzEzIiAvPgo8cGF0aCBkPSJNMCAwTDggOFpNOCAwTDAgOFoiIHN0cm9rZT0iIzFmMWYxZiIgc3Ryb2tlLXdpZHRoPSIxIiAvPgo8L3N2Zz4=')]">
                        <h3 className="text-lg font-bold text-on-surface mb-4 flex items-center gap-2"><Terminal size={20} className="text-on-surface-variant" /> Quick Actions</h3>
                        <div className="flex flex-col gap-2">
                            <button onClick={() => alert("Clearing backend agent cache...")} className="w-full py-2 bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant rounded text-on-surface px-4 font-mono text-xs tracking-wide flex justify-between items-center transition-colors">
                                Reset Cache <Play size={14} className="text-on-surface-variant" />
                            </button>
                            <button onClick={() => alert("Opening Datadog log viewer...")} className="w-full py-2 bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant rounded text-on-surface px-4 font-mono text-xs tracking-wide flex justify-between items-center transition-colors">
                                View Logs <ExternalLink size={14} className="text-on-surface-variant" />
                            </button>
                        </div>
                    </div>
                </aside>
            </div>
        </div>
    );
}

// ─── Low/OK Layout ────────────────────────────────────────────────────────
function MaintenanceRunbook({ tasks, toggleTask }) {
    return (
        <div className="flex-1 p-4 md:p-10 w-full max-w-[1440px] mx-auto py-8">
            <header className="mb-8 relative rounded-xl p-8 shadow-[0_0_20px_rgba(74,222,128,0.05)] border border-[#4ade80]/20 bg-surface-container-low overflow-hidden">
                <div className="absolute inset-0 opacity-5 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-[#4ade80] via-transparent to-transparent pointer-events-none" />
                <div className="relative z-10">
                    <div className="flex items-center gap-3 mb-4">
                        <span className="px-2 py-1 bg-[#4ade80]/10 border border-[#4ade80]/30 rounded font-mono text-xs text-[#4ade80] uppercase tracking-widest">
                            Status: OK / Low Severity
                        </span>
                        <span className="w-2 h-2 rounded-full bg-[#4ade80] animate-pulse" />
                    </div>
                    <h1 className="font-display text-4xl font-bold text-on-background mb-4">Efficiency Maintenance Runbook</h1>
                    <p className="text-base text-on-surface-variant max-w-3xl">
                        Active during periods of peak efficiency. Focus shifts to maintaining high performance, mentorship, and documenting best practices for the rest of the team. System stability is nominal.
                    </p>
                </div>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="bg-surface-container rounded-lg p-6 border border-outline-variant hover:border-[#4ade80]/40 transition-colors group">
                    <div className="flex justify-between items-start mb-4">
                        <span className="font-mono text-xs text-on-surface-variant uppercase tracking-wider">MTTR Target</span>
                        <CheckCircle size={20} className="text-on-surface-variant group-hover:text-[#4ade80] transition-colors" />
                    </div>
                    <div className="text-3xl font-bold text-on-surface mb-1">&lt; 2h</div>
                    <div className="text-xs text-[#4ade80]">Optimal recovery window</div>
                </div>
                <div className="bg-surface-container rounded-lg p-6 border border-outline-variant hover:border-[#4ade80]/40 transition-colors group">
                    <div className="flex justify-between items-start mb-4">
                        <span className="font-mono text-xs text-on-surface-variant uppercase tracking-wider">Refactor Ratio</span>
                        <TrendingUp size={20} className="text-on-surface-variant group-hover:text-[#4ade80] transition-colors" />
                    </div>
                    <div className="text-3xl font-bold text-on-surface mb-1">1:3</div>
                    <div className="text-xs text-on-surface-variant">Feature to tech debt allocation</div>
                </div>
                <div className="bg-surface-container rounded-lg p-6 border border-outline-variant hover:border-[#4ade80]/40 transition-colors group">
                    <div className="flex justify-between items-start mb-4">
                        <span className="font-mono text-xs text-on-surface-variant uppercase tracking-wider">Efficiency</span>
                        <Star size={20} className="text-on-surface-variant group-hover:text-[#4ade80] transition-colors" />
                    </div>
                    <div className="text-3xl font-bold text-on-surface mb-1">&gt; 90%</div>
                    <div className="text-xs text-[#4ade80]">+2.4% over 30 days</div>
                </div>
            </div>

            <section className="grid grid-cols-1 md:grid-cols-12 gap-6 mb-8">
                <div className="md:col-span-8">
                    <TaskList tasks={tasks} toggleTask={toggleTask} themeClass="text-[#4ade80]" />
                </div>
                <div className="md:col-span-4 flex flex-col gap-6 mt-4">
                    <div className="bg-surface-container border border-[#4ade80]/20 shadow-[0_0_20px_rgba(74,222,128,0.05)] rounded-xl p-6">
                        <h3 className="text-lg font-bold text-on-surface mb-4">System Capacity</h3>
                        <div className="relative w-full h-32 flex items-center justify-center">
                            <svg className="w-24 h-24 transform -rotate-90" viewBox="0 0 100 100">
                                <circle cx="50" cy="50" fill="none" r="45" stroke="#353534" strokeWidth="8" />
                                <circle cx="50" cy="50" fill="none" r="45" stroke="#4ade80" strokeDasharray="282.7" strokeDashoffset="84.81" strokeWidth="8" className="transition-all duration-1000 ease-out" />
                            </svg>
                            <div className="absolute inset-0 flex flex-col items-center justify-center">
                                <span className="text-2xl font-bold text-on-surface">70%</span>
                                <span className="text-xs font-mono text-on-surface-variant mt-1">Idle</span>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <footer className="w-full py-8 border-t border-outline-variant flex flex-col md:flex-row justify-between items-center z-10 relative">
                <div className="font-mono text-xs text-primary mb-4 md:mb-0">© 2026 DevTelemetry Infrastructure. All rights reserved.</div>
            </footer>
        </div>
    );
}

// ─── Main Component Router & AI Fetcher ───────────────────────────────────
export default function Runbook() {
    const { severity, userId } = useParams();
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Ask the backend/AI generator for the specific tasks for this severity
    useEffect(() => {
        const fetchAITasks = async () => {
            try {
                const data = await getJSON(`/api/runbook-tasks/${severity}/${userId}`);

                // Map the backend tasks to include a checked state for the UI
                const interactiveTasks = data.tasks.map((t, index) => ({
                    id: index,
                    title: t.title,
                    desc: t.desc,
                    checked: false
                }));

                setTasks(interactiveTasks);
            } catch (err) {
                console.error("Failed to fetch AI tasks:", err);
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchAITasks();
    }, [severity, userId]);

    const toggleTask = (id) => {
        setTasks(tasks.map(t => t.id === id ? { ...t, checked: !t.checked } : t));
    };

    // Show a loading skeleton while the AI generates the tasks
    if (loading) {
        return (
            <div className="min-h-screen bg-background text-on-surface font-body flex flex-col">
                <RunbookHeader />
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                    <Loader2 size={48} className="text-primary animate-spin" />
                    <p className="font-mono text-sm text-on-surface-variant animate-pulse tracking-widest uppercase">
                        AI compiling {severity} runbook...
                    </p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="min-h-screen bg-background text-on-surface font-body flex flex-col">
                <RunbookHeader />
                <div role="alert" className="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
                    <AlertTriangle size={40} className="text-error" />
                    <p className="text-lg font-bold">Couldn't load this runbook.</p>
                    <p className="font-mono text-sm text-on-surface-variant">{error}</p>
                </div>
            </div>
        );
    }

    // Route to the correct layout
    if (severity === "critical") {
        return <CriticalRunbook tasks={tasks} toggleTask={toggleTask} />;
    }

    return (
        <div className="min-h-screen bg-background text-on-surface font-body flex flex-col">
            <RunbookHeader />
            {severity === "low" ? (
                <MaintenanceRunbook tasks={tasks} toggleTask={toggleTask} />
            ) : (
                <TuningRunbook tasks={tasks} toggleTask={toggleTask} />
            )}
        </div>
    );
}