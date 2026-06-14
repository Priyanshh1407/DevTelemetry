import { Terminal, LayoutDashboard, Activity, Bot, Brain, Settings, Bell } from "lucide-react";

export default function Navbar() {
  const navLinks = [
    { icon: LayoutDashboard, label: "Dashboard" },
    { icon: Activity, label: "Analytics" },
    { icon: Bot, label: "AI Agents" },
    { icon: Brain, label: "Coaching" },
  ];

  const subLinks = [
    { label: "OVERVIEW", active: true },
    { label: "NODES", active: false },
    { label: "SECURITY", active: false },
  ];

  return (
    <header className="sticky top-0 z-50 bg-surface/90 backdrop-blur-md border-b border-outline-variant">
      {/* ── Top Bar ── */}
      <div className="flex justify-between items-center px-10 h-16 border-b border-outline-variant">

        {/* Left: Logo + Divider + Nav */}
        <div className="flex items-center gap-8">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-primary rounded flex items-center justify-center shrink-0">
              <Terminal size={20} className="text-on-primary-container" />
            </div>
            <div>
              <p className="text-lg font-black text-primary leading-none tracking-tight">DevTelemetry</p>
              <p className="text-[10px] font-mono text-on-surface-variant tracking-widest uppercase mt-0.5">
                Infrastructure Ops
              </p>
            </div>
          </div>

          <div className="w-px h-4 bg-outline-variant hidden md:block" />

          {/* Nav Links */}
          <nav className="hidden md:flex items-center gap-6">
            {navLinks.map(({ icon: Icon, label }) => (
              <a
                key={label}
                href="#"
                className="flex items-center gap-1.5 text-on-surface-variant hover:text-primary transition-colors duration-200 font-mono text-xs tracking-wide"
              >
                <Icon size={18} />
                {label}
              </a>
            ))}
          </nav>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-3">
          <button className="hidden lg:block bg-primary text-on-primary-container px-4 py-2 rounded-lg font-mono text-xs font-bold tracking-wide hover:opacity-90 transition-opacity cursor-pointer">
            Deploy Agent
          </button>

          <button className="p-2 text-on-surface-variant hover:text-primary transition-colors cursor-pointer">
            <Settings size={24} />
          </button>

          <button className="p-2 text-on-surface-variant hover:text-primary transition-colors relative cursor-pointer">
            <Bell size={24} />
            <span className="absolute top-2 right-2 w-2 h-2 bg-secondary-container rounded-full border-2 border-surface" />
          </button>

          <div className="w-8 h-8 rounded-full overflow-hidden border border-outline-variant shrink-0">
            <img
              src="https://lh3.googleusercontent.com/aida-public/AB6AXuDwhMLMhEiPS9ai33W4THGJHt-5Uc1rTXNZye-IjuV6FVRtJ1a1FK5P6QxgqbanBorxDKmPnB_haAQo61NdJe45QBGxLznRd-HoVWRVgFYLiJS9nJIfrpzd6VagQHT2TcOu9RUocMJ3OEnjVtirVq75AbvPODD-fIsMtJx1jIPLvPRb2QHykdRrINDuv81oOKrp3Oo2JoFPvpnMJVzXW2JmC6UhqbxanV1PPi0dwxZtSKpRnY6yzznHM8e7v7pGCTSeMPkvMw2MKw"
              alt="Profile"
              className="w-full h-full object-cover"
            />
          </div>
        </div>
      </div>

      {/* ── Sub Bar ── */}
      <div className="flex items-center px-10 h-14 gap-6">
        <span className="text-lg font-bold text-on-surface">Team Overview</span>
        <div className="w-px h-4 bg-outline-variant hidden lg:block" />
        <nav className="hidden lg:flex items-center gap-6">
          {subLinks.map(({ label, active }) => (
            <a
              key={label}
              href="#"
              className={[
                "font-mono text-xs tracking-wide transition-colors duration-200 pb-0.5",
                active
                  ? "text-primary font-bold border-b-2 border-primary"
                  : "text-on-surface-variant hover:text-primary",
              ].join(" ")}
            >
              {label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  );
}