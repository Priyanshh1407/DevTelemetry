import { Link } from "react-router-dom";
import { Terminal, LayoutDashboard } from "lucide-react";

// Only links that lead somewhere. (The original mock-up had Analytics / AI Agents / Coaching,
// NODES / SECURITY tabs, a "Deploy Agent" button and a stock avatar, none of which existed.)
export default function Navbar({ title = "Team Overview" }) {
  return (
    <header className="sticky top-0 z-50 bg-surface/90 backdrop-blur-md border-b border-outline-variant">
      <div className="flex justify-between items-center px-6 md:px-10 h-16 border-b border-outline-variant">
        <div className="flex items-center gap-8">
          <Link to="/" className="flex items-center gap-3">
            <div className="w-8 h-8 bg-primary rounded flex items-center justify-center shrink-0">
              <Terminal size={20} className="text-on-primary-container" />
            </div>
            <div>
              <p className="text-lg font-black text-primary leading-none tracking-tight">DevTelemetry</p>
              <p className="text-[10px] font-mono text-on-surface-variant tracking-widest uppercase mt-0.5">
                AI usage efficiency
              </p>
            </div>
          </Link>

          <div className="w-px h-4 bg-outline-variant hidden md:block" />

          <nav className="flex items-center gap-6">
            <Link
              to="/"
              className="flex items-center gap-1.5 text-on-surface-variant hover:text-primary transition-colors duration-200 font-mono text-xs tracking-wide"
            >
              <LayoutDashboard size={18} />
              Dashboard
            </Link>
          </nav>
        </div>
      </div>

      <div className="flex items-center px-6 md:px-10 h-14">
        <span className="text-lg font-bold text-on-surface">{title}</span>
      </div>
    </header>
  );
}
