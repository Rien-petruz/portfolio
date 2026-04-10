import { useState, useEffect, useRef } from "react";

const ACCENT = "#0ea5e9";
const ACCENT2 = "#06d6a0";
const DARK = "#07070f";

const projects = [
  {
    title: "ProUtility FM",
    subtitle: "Facility Management Platform",
    stack: ["Laravel 10", "PHP 8.1+", "MySQL", "Blade", "SEO"],
    desc: "Production website with admin panel, custom block-based rich text editor, drag-to-reorder portfolio, full SEO implementation (Open Graph, JSON-LD, sitemap).",
    color: "#06d6a0",
    icon: "🏢",
  },
  {
    title: "AI Gold Breakout System",
    subtitle: "ML-Powered Algorithmic Trading",
    stack: ["Python", "MT5", "scikit-learn", "XGBoost", "Telegram"],
    desc: "13-file, 3,000+ line trading system with RandomForest/XGBoost signal filtering, ATR trailing stops, continuous learning loop, and real-time Telegram alerts.",
    color: "#f59e0b",
    icon: "📈",
  },
  {
    title: "SMC Trading Bot",
    subtitle: "Smart Money Concepts Engine",
    stack: ["Python", "MetaTrader 5", "Technical Analysis"],
    desc: "HTF trend detection, Order Block identification, triple-indicator confluence gate (RSI, EMA, MACD), session-aware execution with configurable blackout windows.",
    color: "#ef4444",
    icon: "🤖",
  },
  {
    title: "VidStory AI",
    subtitle: "Automated Video Generation Pipeline",
    stack: ["Python", "Streamlit", "OpenAI", "Whisper", "FFmpeg"],
    desc: "End-to-end pipeline: downloads source video, transcribes with Whisper, generates AI commentary, produces TTS narration, composites final video for YouTube.",
    color: "#8b5cf6",
    icon: "🎬",
  },
  {
    title: "Hotel Management System",
    subtitle: "Booking & Operations Platform",
    stack: ["Laravel", "MySQL", "JavaScript", "Bootstrap"],
    desc: "Web-based hotel booking platform with room inventory management, overbooking prevention, guest registration, and secure admin dashboard.",
    color: "#0ea5e9",
    icon: "🏨",
  },
  {
    title: "Attendee Registry App",
    subtitle: "Church Event Attendance Platform",
    stack: ["React", "Express.js", "TypeScript", "PostgreSQL", "Drizzle ORM", "Tailwind CSS"],
    desc: "Full-stack monorepo app for managing church event attendance. Returning attendees are auto-recognized; monthly records are tracked without re-registration. Admin dashboard with search, filter, pagination, bulk email campaigns, CSV export, and SMTP configuration.",
    color: "#a855f7",
    icon: "📋",
  },
];

const experience = [
  { role: "Software Developer & Product Owner", co: "Freelance", period: "Dec 2023 – Present" },
  { role: "Software Developer & Product Manager", co: "Bizad Solution & Technology", period: "Aug 2019 – Dec 2023" },
  { role: "Software Developer Intern", co: "Bizad Solution & Technology", period: "Sep 2016 – Aug 2019" },
];

const skillRow1 = ["PHP", "Python", "JavaScript", "TypeScript", "Dart", "HTML/CSS", "SQL", "C#", "Laravel", "React", "Flutter", "Bootstrap"];
const skillRow2 = ["Streamlit", "Claude AI", "GPT-4", "MCP", "Whisper", "MT5 API", "XGBoost", "RandomForest", "Figma", "Adobe XD", "Photoshop", "Drizzle ORM"];

/* ── hooks ── */
function useWindowWidth() {
  const [w, setW] = useState(typeof window !== "undefined" ? window.innerWidth : 1200);
  useEffect(() => {
    const h = () => setW(window.innerWidth);
    window.addEventListener("resize", h, { passive: true });
    return () => window.removeEventListener("resize", h);
  }, []);
  return w;
}

function useInView(ref, threshold = 0.15) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVisible(true); }, { threshold });
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, [ref]);
  return visible;
}

/* ── shared components ── */
function FadeIn({ children, delay = 0, style: outerStyle = {} }) {
  const ref = useRef();
  const vis = useInView(ref);
  return (
    <div ref={ref} style={{
      opacity: vis ? 1 : 0,
      transform: vis ? "translateY(0)" : "translateY(32px)",
      transition: `opacity 0.75s cubic-bezier(0.16,1,0.3,1) ${delay}s, transform 0.75s cubic-bezier(0.16,1,0.3,1) ${delay}s`,
      ...outerStyle,
    }}>{children}</div>
  );
}

function Orb({ color, size, top, left, delay }) {
  return (
    <div style={{
      position: "absolute", top, left, width: size, height: size,
      background: `radial-gradient(circle, ${color}18 0%, transparent 70%)`,
      borderRadius: "50%", filter: "blur(80px)", pointerEvents: "none",
      animation: `orbFloat 10s ease-in-out ${delay || 0}s infinite alternate`,
    }} />
  );
}

function ScrollProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const h = () => {
      const total = document.documentElement.scrollHeight - window.innerHeight;
      setP(total > 0 ? (window.scrollY / total) * 100 : 0);
    };
    window.addEventListener("scroll", h, { passive: true });
    return () => window.removeEventListener("scroll", h);
  }, []);
  return (
    <div style={{ position: "fixed", top: 0, left: 0, right: 0, height: 2, zIndex: 9999, background: "rgba(255,255,255,0.04)" }}>
      <div style={{ height: "100%", width: `${p}%`, background: `linear-gradient(90deg, ${ACCENT}, ${ACCENT2})`, transition: "width 0.1s linear" }} />
    </div>
  );
}

function Counter({ end, suffix = "", visible }) {
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!visible) return;
    let cur = 0;
    const stepTime = Math.max(Math.floor(1200 / end), 16);
    const timer = setInterval(() => {
      cur += 1;
      setVal(cur);
      if (cur >= end) clearInterval(timer);
    }, stepTime);
    return () => clearInterval(timer);
  }, [visible, end]);
  return <>{val}{suffix}</>;
}

function Marquee({ tags, reverse = false }) {
  const tripled = [...tags, ...tags, ...tags];
  return (
    <div style={{
      overflow: "hidden",
      WebkitMaskImage: "linear-gradient(90deg, transparent 0%, black 8%, black 92%, transparent 100%)",
      maskImage: "linear-gradient(90deg, transparent 0%, black 8%, black 92%, transparent 100%)",
    }}>
      <div style={{
        display: "flex", gap: 10, width: "max-content",
        animation: `${reverse ? "marqueeR" : "marquee"} 40s linear infinite`,
      }}>
        {tripled.map((tag, i) => (
          <span key={i} style={{
            padding: "7px 20px", borderRadius: 40,
            background: "rgba(255,255,255,0.035)",
            border: "1px solid rgba(255,255,255,0.07)",
            fontSize: 13, color: "#64748b", whiteSpace: "nowrap", fontWeight: 500,
          }}>{tag}</span>
        ))}
      </div>
    </div>
  );
}

/* ── main component ── */
export default function Portfolio() {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [menuOpen, setMenuOpen] = useState(false);
  const aboutRef = useRef();
  const aboutVisible = useInView(aboutRef, 0.3);
  const w = useWindowWidth();

  const isMobile = w < 640;
  const isTablet = w >= 640 && w < 1024;
  const isDesktop = w >= 1024;

  // Close menu on resize to desktop
  useEffect(() => { if (isDesktop) setMenuOpen(false); }, [isDesktop]);

  // Close menu on nav link click
  const handleNavClick = () => setMenuOpen(false);

  const pad = isMobile ? "0 5%" : isTablet ? "0 6%" : "0 8%";
  const sectionPad = isMobile ? "72px 5%" : isTablet ? "90px 6%" : "110px 8%";

  const stats = [
    { end: 7, suffix: "+", label: "Years Experience", color: ACCENT },
    { end: 15, suffix: "+", label: "Projects Shipped", color: ACCENT2 },
    { end: 5, suffix: "+", label: "Trading Bots Built", color: "#f59e0b" },
    { end: 3, suffix: "K+", label: "Lines in Largest System", color: "#a855f7" },
  ];

  const navLinks = ["About", "Skills", "Projects", "Experience", "Contact"];

  return (
    <div
      style={{ background: DARK, minHeight: "100vh", color: "#e2e8f0", fontFamily: "'Outfit', sans-serif", overflowX: "hidden", position: "relative" }}
      onMouseMove={e => setMousePos({ x: e.clientX, y: e.clientY })}
    >
      <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&family=Syne:wght@400;500;600;700;800&display=swap" rel="stylesheet" />

      <style>{`
        @keyframes orbFloat { 0%{transform:translate(0,0) scale(1)} 100%{transform:translate(28px,-36px) scale(1.12)} }
        @keyframes grain { 0%,100%{transform:translate(0,0)} 10%{transform:translate(-5%,-10%)} 30%{transform:translate(3%,2%)} 50%{transform:translate(-2%,8%)} 70%{transform:translate(7%,-5%)} 90%{transform:translate(-3%,3%)} }
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.4;transform:scale(0.85)} }
        @keyframes slideUp { from{opacity:0;transform:translateY(56px)} to{opacity:1;transform:translateY(0)} }
        @keyframes float { 0%,100%{transform:translateY(0px)} 50%{transform:translateY(-10px)} }
        @keyframes gradShimmer { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }
        @keyframes marquee { 0%{transform:translateX(0)} 100%{transform:translateX(-33.333%)} }
        @keyframes marqueeR { 0%{transform:translateX(-33.333%)} 100%{transform:translateX(0)} }
        @keyframes menuFadeIn { from{opacity:0;transform:scale(0.97)} to{opacity:1;transform:scale(1)} }
        .grain::before {
          content:''; position:fixed; top:-50%; left:-50%; right:-50%; bottom:-50%;
          background:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          opacity:0.025; pointer-events:none; animation:grain 0.5s steps(1) infinite; z-index:9998;
        }
        .dot-grid {
          position:fixed; inset:0; pointer-events:none; z-index:0;
          background-image:radial-gradient(rgba(255,255,255,0.055) 1px, transparent 1px);
          background-size:28px 28px;
          -webkit-mask-image:radial-gradient(ellipse 75% 75% at 50% 50%, black 30%, transparent 100%);
          mask-image:radial-gradient(ellipse 75% 75% at 50% 50%, black 30%, transparent 100%);
        }
        .project-card { transition:all 0.4s cubic-bezier(0.16,1,0.3,1); }
        .project-card:hover { transform:translateY(-6px); }
        .project-card:hover .card-top-line { opacity:1 !important; }
        .project-card:hover .card-glow { opacity:1 !important; }
        .nav-link { color:#4e6080; text-decoration:none; font-size:13px; font-weight:500; padding:6px 14px; border-radius:20px; transition:all 0.2s ease; letter-spacing:0.2px; }
        .nav-link:hover { color:#e2e8f0; background:rgba(255,255,255,0.07); }
        .mobile-nav-link { display:block; color:#94a3b8; text-decoration:none; font-family:'Syne',sans-serif; font-size:clamp(28px,8vw,40px); font-weight:700; letter-spacing:-1px; transition:color 0.2s; padding:4px 0; }
        .mobile-nav-link:hover { color:#f8fafc; }
        .cta-btn { position:relative; overflow:hidden; transition:transform 0.25s ease, box-shadow 0.25s ease; }
        .cta-btn::before { content:''; position:absolute; top:0; left:-100%; width:100%; height:100%; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.18),transparent); transition:left 0.5s; }
        .cta-btn:hover::before { left:100%; }
        .cta-btn-primary:hover { transform:translateY(-2px); box-shadow:0 10px 32px rgba(14,165,233,0.35); }
        .cta-btn-ghost:hover { transform:translateY(-2px); border-color:rgba(255,255,255,0.2) !important; }
        .exp-item:hover .exp-dot { background:${ACCENT} !important; box-shadow:0 0 14px ${ACCENT}99 !important; }
        .contact-chip { transition:all 0.3s ease; }
        .contact-chip:hover { border-color:rgba(14,165,233,0.35) !important; background:rgba(14,165,233,0.06) !important; transform:translateY(-2px); }
        ::selection { background:${ACCENT}44; color:white; }
        * { scrollbar-width:thin; scrollbar-color:${ACCENT}22 transparent; }
      `}</style>

      <ScrollProgress />
      <div className="grain" />
      <div className="dot-grid" />

      {/* Orbs */}
      <Orb color={ACCENT} size={isMobile ? "300px" : "600px"} top="-12%" left="55%" delay={0} />
      <Orb color={ACCENT2} size={isMobile ? "250px" : "500px"} top="28%" left="-12%" delay={2} />
      <Orb color="#8b5cf6" size={isMobile ? "200px" : "420px"} top="68%" left="68%" delay={4} />

      {/* Cursor glow — desktop only */}
      {isDesktop && (
        <div style={{
          position: "fixed", width: 420, height: 420, borderRadius: "50%",
          background: `radial-gradient(circle, ${ACCENT}05 0%, transparent 70%)`,
          transform: `translate(${mousePos.x - 210}px, ${mousePos.y - 210}px)`,
          pointerEvents: "none", zIndex: 1, transition: "transform 0.18s ease-out",
        }} />
      )}

      {/* ── NAV ── */}
      <nav style={{
        position: "fixed", top: 18, left: "50%", transform: "translateX(-50%)",
        zIndex: 200, display: "flex", alignItems: "center",
        gap: isDesktop ? 2 : 0,
        padding: isMobile ? "6px 6px 6px 16px" : "6px 8px 6px 16px",
        background: "rgba(7,7,15,0.75)",
        backdropFilter: "blur(28px) saturate(1.4)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 60,
        boxShadow: "0 4px 40px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.04)",
        whiteSpace: "nowrap",
      }}>
        {/* Logo */}
        <div style={{
          fontFamily: "Syne", fontWeight: 800, fontSize: 16, letterSpacing: -0.5,
          paddingRight: isDesktop ? 14 : 10,
          borderRight: isDesktop ? "1px solid rgba(255,255,255,0.07)" : "none",
          marginRight: isDesktop ? 6 : 0,
        }}>
          <span style={{ color: ACCENT }}>P</span><span style={{ color: "#e2e8f0" }}>K</span>
        </div>

        {/* Desktop links */}
        {isDesktop && navLinks.map(s => (
          <a key={s} href={`#${s.toLowerCase()}`} className="nav-link">{s}</a>
        ))}

        {/* Hamburger — mobile/tablet */}
        {!isDesktop && (
          <button
            onClick={() => setMenuOpen(o => !o)}
            style={{
              background: menuOpen ? "rgba(255,255,255,0.08)" : "transparent",
              border: "none", cursor: "pointer", padding: "7px 10px",
              borderRadius: 30, display: "flex", flexDirection: "column",
              gap: 5, alignItems: "center", justifyContent: "center",
              marginLeft: 8,
            }}
            aria-label="Toggle menu"
          >
            {menuOpen ? (
              <span style={{ color: "#e2e8f0", fontSize: 18, lineHeight: 1 }}>✕</span>
            ) : (
              <>
                <span style={{ display: "block", width: 18, height: 1.5, background: "#94a3b8", borderRadius: 2 }} />
                <span style={{ display: "block", width: 14, height: 1.5, background: "#64748b", borderRadius: 2 }} />
                <span style={{ display: "block", width: 18, height: 1.5, background: "#94a3b8", borderRadius: 2 }} />
              </>
            )}
          </button>
        )}
      </nav>

      {/* Mobile full-screen menu overlay */}
      {!isDesktop && menuOpen && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 150,
          background: "rgba(7,7,15,0.97)",
          backdropFilter: "blur(24px)",
          display: "flex", flexDirection: "column",
          alignItems: "center", justifyContent: "center",
          gap: isMobile ? 28 : 24,
          animation: "menuFadeIn 0.25s cubic-bezier(0.16,1,0.3,1)",
        }}>
          {navLinks.map((s, i) => (
            <a
              key={s}
              href={`#${s.toLowerCase()}`}
              className="mobile-nav-link"
              onClick={handleNavClick}
              style={{ animationDelay: `${i * 0.05}s` }}
            >
              {s}
            </a>
          ))}
          <div style={{ marginTop: 20, display: "flex", gap: 10 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: ACCENT }} />
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: ACCENT2 }} />
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#a78bfa" }} />
          </div>
        </div>
      )}

      {/* ── HERO ── */}
      <section style={{ minHeight: "100vh", display: "flex", alignItems: "center", padding: pad, position: "relative", zIndex: 2 }}>
        <div style={{ maxWidth: 820, position: "relative", width: "100%", paddingTop: isMobile ? 80 : 0 }}>
          <div style={{ animation: "slideUp 0.9s cubic-bezier(0.16,1,0.3,1)" }}>

            {/* Availability badge */}
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 9, marginBottom: isMobile ? 24 : 36,
              padding: "8px 18px 8px 12px", borderRadius: 40,
              background: "rgba(6,214,160,0.07)", border: "1px solid rgba(6,214,160,0.18)",
              animation: "float 5s ease-in-out infinite",
            }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: ACCENT2, animation: "pulse 2s infinite", flexShrink: 0 }} />
              <span style={{ color: ACCENT2, fontSize: 13, fontWeight: 600, letterSpacing: 0.3 }}>Available for hire</span>
            </div>

            <h1 style={{
              fontFamily: "Syne",
              fontSize: isMobile ? "clamp(52px,14vw,72px)" : "clamp(52px,8.5vw,100px)",
              fontWeight: 900, lineHeight: 0.92,
              margin: `0 0 ${isMobile ? 20 : 30}px`, letterSpacing: isMobile ? -2 : -4,
            }}>
              <span style={{ color: "#f8fafc", display: "block" }}>Peter</span>
              <span style={{
                background: `linear-gradient(135deg, ${ACCENT} 0%, ${ACCENT2} 45%, #a78bfa 100%)`,
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
                backgroundSize: "200% 200%",
                animation: "gradShimmer 5s ease infinite",
                display: "block",
              }}>Kekpe</span>
            </h1>

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
              {["Full-Stack Dev", "Product Manager", "AI Engineer"].map((t, i) => (
                <span key={t} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{
                    fontFamily: "Syne",
                    fontSize: isMobile ? 14 : "clamp(14px,1.8vw,19px)",
                    fontWeight: 500, color: "#3d5166",
                  }}>{t}</span>
                  {i < 2 && <span style={{ width: 3, height: 3, borderRadius: "50%", background: "#1e3a4f", flexShrink: 0 }} />}
                </span>
              ))}
            </div>

            <p style={{ fontSize: isMobile ? 14 : 15, color: "#3d5166", lineHeight: 1.85, maxWidth: 500, margin: `0 0 ${isMobile ? 32 : 44}px` }}>
              I build products end-to-end — from roadmaps and PRDs to production code. 7+ years shipping web & mobile apps, now supercharged with AI tooling and LLM integrations.
            </p>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <a href="#projects" className="cta-btn cta-btn-primary" style={{
                padding: isMobile ? "12px 28px" : "13px 34px",
                background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
                color: DARK, fontWeight: 700, fontSize: 14, borderRadius: 60,
                textDecoration: "none", letterSpacing: 0.2,
              }}>View Work</a>
              <a href="#contact" className="cta-btn cta-btn-ghost" style={{
                padding: isMobile ? "12px 28px" : "13px 34px",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.1)", color: "#94a3b8",
                fontWeight: 600, fontSize: 14, borderRadius: 60, textDecoration: "none",
              }}>Get In Touch</a>
            </div>
          </div>
        </div>

        {/* Floating stat pills — desktop only */}
        {isDesktop && (
          <div style={{
            position: "absolute", right: "6%", top: "50%", transform: "translateY(-50%)",
            display: "flex", flexDirection: "column", gap: 12,
            animation: "slideUp 1.1s cubic-bezier(0.16,1,0.3,1)",
          }}>
            {[
              { val: "7+", label: "Years", color: ACCENT, d: 0 },
              { val: "15+", label: "Projects", color: ACCENT2, d: 1 },
              { val: "6+", label: "AI Tools", color: "#a78bfa", d: 2 },
            ].map(s => (
              <div key={s.label} style={{
                padding: "16px 22px", borderRadius: 16, textAlign: "center",
                background: "rgba(255,255,255,0.025)",
                border: "1px solid rgba(255,255,255,0.06)",
                backdropFilter: "blur(16px)",
                animation: `float ${4 + s.d}s ease-in-out ${s.d * 0.6}s infinite`,
              }}>
                <div style={{ fontFamily: "Syne", fontSize: 26, fontWeight: 800, color: s.color }}>{s.val}</div>
                <div style={{ fontSize: 10, color: "#2d4057", fontWeight: 600, letterSpacing: 1.5, textTransform: "uppercase", marginTop: 3 }}>{s.label}</div>
              </div>
            ))}
          </div>
        )}

        {/* Scroll hint */}
        <div style={{ position: "absolute", bottom: 32, left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: "#1e3347", letterSpacing: 3, textTransform: "uppercase" }}>Scroll</span>
          <div style={{ width: 1, height: 32, background: `linear-gradient(to bottom, ${ACCENT}55, transparent)` }} />
        </div>
      </section>

      {/* ── ABOUT ── */}
      <section id="about" style={{ padding: sectionPad, position: "relative", zIndex: 2 }}>
        <FadeIn>
          <div style={{
            display: "grid",
            gridTemplateColumns: isDesktop ? "1fr 1fr" : "1fr",
            gap: isDesktop ? 80 : 48,
            alignItems: "center",
            maxWidth: 1100, margin: "0 auto",
          }}>
            <div>
              <span style={{ color: ACCENT, fontSize: 11, fontWeight: 700, letterSpacing: 4, textTransform: "uppercase" }}>About Me</span>
              <h2 style={{ fontFamily: "Syne", fontSize: "clamp(28px,3.8vw,44px)", fontWeight: 800, margin: "14px 0 28px", lineHeight: 1.1 }}>
                Developer who thinks<br />in <span style={{ color: ACCENT2 }}>products</span>
              </h2>
              <p style={{ color: "#3d5166", lineHeight: 1.9, fontSize: 15, marginBottom: 16 }}>
                I'm a Lagos-based full-stack developer and product manager with 7+ years of experience. I don't just write code — I define what gets built and why. From stakeholder discovery and PRDs to sprint planning and deployment, I own the full lifecycle.
              </p>
              <p style={{ color: "#3d5166", lineHeight: 1.9, fontSize: 15 }}>
                Recently, I've been deep in AI-augmented development — using LLMs like Claude and GPT as coding partners, building MCP integrations, and creating intelligent automation systems like algorithmic trading bots with machine learning filtering.
              </p>
            </div>

            <div ref={aboutRef} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {stats.map((s, i) => (
                <FadeIn key={s.label} delay={i * 0.1}>
                  <div style={{
                    padding: isMobile ? "22px 16px" : "28px 20px",
                    borderRadius: 20, textAlign: "center",
                    background: "rgba(255,255,255,0.025)",
                    border: "1px solid rgba(255,255,255,0.06)",
                    position: "relative", overflow: "hidden",
                  }}>
                    <div style={{ position: "absolute", inset: 0, borderRadius: 20, background: `radial-gradient(circle at 50% 0%, ${s.color}0d, transparent 65%)` }} />
                    <div style={{ position: "absolute", top: 0, left: "15%", right: "15%", height: 1, background: `linear-gradient(90deg, transparent, ${s.color}40, transparent)` }} />
                    <div style={{ fontFamily: "Syne", fontSize: isMobile ? 32 : 40, fontWeight: 900, color: s.color, position: "relative", lineHeight: 1 }}>
                      <Counter end={s.end} suffix={s.suffix} visible={aboutVisible} />
                    </div>
                    <div style={{ fontSize: 10, color: "#2d4057", marginTop: 8, fontWeight: 600, letterSpacing: 0.8, textTransform: "uppercase", position: "relative" }}>{s.label}</div>
                  </div>
                </FadeIn>
              ))}
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ── SKILLS — Marquee ── */}
      <section id="skills" style={{ padding: `${isMobile ? 72 : 100}px 0`, position: "relative", zIndex: 2 }}>
        <FadeIn>
          <div style={{ maxWidth: 1100, margin: `0 auto ${isMobile ? 32 : 48}px`, padding: isMobile ? "0 5%" : isTablet ? "0 6%" : "0 8%" }}>
            <span style={{ color: ACCENT, fontSize: 11, fontWeight: 700, letterSpacing: 4, textTransform: "uppercase" }}>Expertise</span>
            <h2 style={{ fontFamily: "Syne", fontSize: "clamp(28px,3.8vw,44px)", fontWeight: 800, margin: "14px 0 0" }}>Technical Arsenal</h2>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Marquee tags={skillRow1} />
            <Marquee tags={skillRow2} reverse />
          </div>
        </FadeIn>
      </section>

      {/* ── PROJECTS — Bento / Responsive Grid ── */}
      <section id="projects" style={{ padding: sectionPad, position: "relative", zIndex: 2 }}>
        <FadeIn>
          <div style={{ maxWidth: 1100, margin: "0 auto" }}>
            <span style={{ color: ACCENT, fontSize: 11, fontWeight: 700, letterSpacing: 4, textTransform: "uppercase" }}>Portfolio</span>
            <h2 style={{ fontFamily: "Syne", fontSize: "clamp(28px,3.8vw,44px)", fontWeight: 800, margin: "14px 0 40px" }}>Selected Work</h2>
            <div style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : isTablet ? "repeat(2, 1fr)" : "repeat(3, 1fr)",
              gap: isMobile ? 12 : 14,
            }}>
              {projects.map((p, i) => {
                // Bento spans only on desktop
                const featured = isDesktop && (i === 0 || i === 3);
                return (
                  <FadeIn key={p.title} delay={isMobile ? 0 : i * 0.07} style={{ gridColumn: featured ? "span 2" : "span 1" }}>
                    <div className="project-card" style={{
                      padding: featured ? "38px 42px" : isMobile ? "24px 22px" : "28px 30px",
                      borderRadius: 20, height: "100%", boxSizing: "border-box",
                      background: "rgba(255,255,255,0.025)",
                      border: "1px solid rgba(255,255,255,0.06)",
                      position: "relative", overflow: "hidden",
                    }}>
                      <div className="card-top-line" style={{
                        position: "absolute", top: 0, left: "10%", right: "10%", height: 1,
                        background: `linear-gradient(90deg, transparent, ${p.color}55, transparent)`,
                        opacity: 0.4, transition: "opacity 0.4s",
                      }} />
                      <div className="card-glow" style={{
                        position: "absolute", top: 0, right: 0, width: "55%", height: "55%",
                        background: `radial-gradient(circle at top right, ${p.color}0f, transparent 70%)`,
                        opacity: 0.6, transition: "opacity 0.4s",
                        borderRadius: "0 20px 0 0", pointerEvents: "none",
                      }} />
                      <div style={{ position: "relative" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                          <div style={{
                            width: featured ? 48 : 38, height: featured ? 48 : 38,
                            borderRadius: 12, background: `${p.color}12`,
                            border: `1px solid ${p.color}22`,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: featured ? 24 : 18, flexShrink: 0,
                          }}>{p.icon}</div>
                          <div>
                            <h3 style={{ fontFamily: "Syne", fontSize: featured ? 21 : isMobile ? 15 : 16, fontWeight: 700, margin: 0, color: "#f1f5f9" }}>{p.title}</h3>
                            <span style={{ fontSize: 12, color: p.color, fontWeight: 600, letterSpacing: 0.2 }}>{p.subtitle}</span>
                          </div>
                        </div>
                        <p style={{ fontSize: isMobile ? 13 : 13, color: "#3a5268", lineHeight: 1.8, margin: "0 0 14px" }}>{p.desc}</p>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {p.stack.map(t => (
                            <span key={t} style={{
                              padding: "3px 10px", borderRadius: 20, fontSize: 11, fontWeight: 600,
                              background: `${p.color}10`, color: p.color, letterSpacing: 0.2,
                            }}>{t}</span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </FadeIn>
                );
              })}
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ── EXPERIENCE — Timeline ── */}
      <section id="experience" style={{ padding: sectionPad, position: "relative", zIndex: 2 }}>
        <FadeIn>
          <div style={{ maxWidth: 680, margin: "0 auto" }}>
            <span style={{ color: ACCENT, fontSize: 11, fontWeight: 700, letterSpacing: 4, textTransform: "uppercase" }}>Career</span>
            <h2 style={{ fontFamily: "Syne", fontSize: "clamp(28px,3.8vw,44px)", fontWeight: 800, margin: "14px 0 44px" }}>Experience</h2>
            <div style={{ position: "relative" }}>
              <div style={{
                position: "absolute", left: 6, top: 10, bottom: 10, width: 1,
                background: `linear-gradient(to bottom, ${ACCENT}55, ${ACCENT2}22, transparent)`,
              }} />
              <div style={{ display: "flex", flexDirection: "column", gap: isMobile ? 32 : 40 }}>
                {experience.map((e, i) => (
                  <FadeIn key={e.role} delay={i * 0.12}>
                    <div className="exp-item" style={{ display: "flex", gap: isMobile ? 20 : 28, paddingLeft: 2 }}>
                      <div style={{ flexShrink: 0, paddingTop: 5 }}>
                        <div className="exp-dot" style={{
                          width: 13, height: 13, borderRadius: "50%",
                          background: i === 0 ? ACCENT : "rgba(255,255,255,0.08)",
                          border: `2px solid ${i === 0 ? ACCENT : "rgba(255,255,255,0.12)"}`,
                          boxShadow: i === 0 ? `0 0 12px ${ACCENT}77` : "none",
                          transition: "all 0.3s ease",
                        }} />
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{
                          display: "flex",
                          flexDirection: isMobile ? "column" : "row",
                          justifyContent: "space-between",
                          alignItems: isMobile ? "flex-start" : "flex-start",
                          gap: isMobile ? 2 : 4, marginBottom: 4,
                        }}>
                          <h3 style={{ fontFamily: "Syne", fontSize: isMobile ? 15 : 17, fontWeight: 700, margin: 0, color: "#e8f0f8" }}>{e.role}</h3>
                          <span style={{ fontSize: 12, color: "#1e3347", fontWeight: 500, whiteSpace: "nowrap" }}>{e.period}</span>
                        </div>
                        <span style={{ fontSize: 13, color: ACCENT2, fontWeight: 600 }}>{e.co}</span>
                      </div>
                    </div>
                  </FadeIn>
                ))}
              </div>
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ── CONTACT ── */}
      <section id="contact" style={{ padding: sectionPad, paddingBottom: isMobile ? 60 : 80, position: "relative", zIndex: 2 }}>
        <FadeIn>
          <div style={{
            maxWidth: 780, margin: "0 auto",
            padding: isMobile ? "48px 24px" : isTablet ? "60px 40px" : "72px 56px",
            borderRadius: 28, textAlign: "center",
            background: "rgba(255,255,255,0.018)",
            border: "1px solid rgba(255,255,255,0.07)",
            position: "relative", overflow: "hidden",
          }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: 28, background: `radial-gradient(ellipse at 50% -10%, ${ACCENT}0a, transparent 60%)` }} />
            <div style={{ position: "absolute", top: 0, left: "20%", right: "20%", height: 1, background: `linear-gradient(90deg, transparent, ${ACCENT}50, transparent)` }} />

            <div style={{ position: "relative" }}>
              <span style={{ color: ACCENT, fontSize: 11, fontWeight: 700, letterSpacing: 4, textTransform: "uppercase" }}>Contact</span>
              <h2 style={{ fontFamily: "Syne", fontSize: "clamp(28px,4.5vw,52px)", fontWeight: 900, margin: "16px 0 18px", lineHeight: 1.05 }}>
                Let's build something <span style={{ color: ACCENT2 }}>great</span>
              </h2>
              <p style={{ fontSize: 15, color: "#3a5268", lineHeight: 1.8, maxWidth: 440, margin: "0 auto 36px" }}>
                Open to full-time roles, freelance projects, or product collaborations. Let's talk.
              </p>
              <div style={{ display: "flex", justifyContent: "center", gap: 10, flexWrap: "wrap" }}>
                {[
                  { label: "kekpepeter@gmail.com", icon: "✉" },
                  { label: "+234 902 598 4606", icon: "📱" },
                  { label: "github.com/Rien-petruz", icon: "⚡" },
                ].map(c => (
                  <div key={c.label} className="contact-chip" style={{
                    padding: isMobile ? "10px 16px" : "11px 22px",
                    borderRadius: 60,
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.07)",
                    fontSize: isMobile ? 12 : 13, color: "#64748b",
                    display: "flex", alignItems: "center", gap: 8,
                  }}>
                    <span>{c.icon}</span>{c.label}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </FadeIn>

        <div style={{ marginTop: 60, textAlign: "center", paddingTop: 24, borderTop: "1px solid rgba(255,255,255,0.04)" }}>
          <span style={{ fontSize: 12, color: "#151f2b" }}>© 2026 Peter Kekpe · Built with passion & AI</span>
        </div>
      </section>
    </div>
  );
}
