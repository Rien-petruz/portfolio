import { useState, useEffect, useRef } from "react";

const ACCENT = "#0ea5e9";
const ACCENT2 = "#06d6a0";
const DARK = "#0a0a0f";
const CARD_BG = "rgba(255,255,255,0.03)";
const GLASS = "rgba(255,255,255,0.06)";

const projects = [
  {
    title: "ProUtility FM",
    subtitle: "Facility Management Platform",
    stack: ["Laravel 10", "PHP 8.1+", "MySQL", "Blade", "SEO"],
    desc: "Production website with admin panel, custom block-based rich text editor, drag-to-reorder portfolio, full SEO implementation (Open Graph, JSON-LD, sitemap).",
    color: "#06d6a0",
    icon: "🏢"
  },
  {
    title: "AI Gold Breakout System",
    subtitle: "ML-Powered Algorithmic Trading",
    stack: ["Python", "MT5", "scikit-learn", "XGBoost", "Telegram"],
    desc: "13-file, 3,000+ line trading system with RandomForest/XGBoost signal filtering, ATR trailing stops, continuous learning loop, and real-time Telegram alerts.",
    color: "#f59e0b",
    icon: "📈"
  },
  {
    title: "SMC Trading Bot",
    subtitle: "Smart Money Concepts Engine",
    stack: ["Python", "MetaTrader 5", "Technical Analysis"],
    desc: "HTF trend detection, Order Block identification, triple-indicator confluence gate (RSI, EMA, MACD), session-aware execution with configurable blackout windows.",
    color: "#ef4444",
    icon: "🤖"
  },
  {
    title: "VidStory AI",
    subtitle: "Automated Video Generation Pipeline",
    stack: ["Python", "Streamlit", "OpenAI", "Whisper", "FFmpeg"],
    desc: "End-to-end pipeline: downloads source video, transcribes with Whisper, generates AI commentary, produces TTS narration, composites final video for YouTube.",
    color: "#8b5cf6",
    icon: "🎬"
  },
  {
    title: "Hotel Management System",
    subtitle: "Booking & Operations Platform",
    stack: ["Laravel", "MySQL", "JavaScript", "Bootstrap"],
    desc: "Web-based hotel booking platform with room inventory management, overbooking prevention, guest registration, and secure admin dashboard.",
    color: "#0ea5e9",
    icon: "🏨"
  }
];

const skills = [
  { cat: "Languages", items: "PHP, Python, JavaScript, Dart, HTML/CSS, SQL, C#" },
  { cat: "Frameworks", items: "Laravel, React, Flutter, Bootstrap, Streamlit" },
  { cat: "AI & LLM", items: "Claude, GPT-4, MCP, Whisper, Prompt Engineering" },
  { cat: "Trading", items: "MT5 API, SMC, RandomForest, XGBoost" },
  { cat: "Product", items: "Roadmaps, PRDs, Agile/Scrum, RICE, Stakeholder Mgmt" },
  { cat: "Design", items: "Figma, Adobe XD, Photoshop, Illustrator" },
];

const experience = [
  { role: "Software Developer & Product Owner", co: "Freelance", period: "Dec 2023 – Present" },
  { role: "Software Developer & Product Manager", co: "Bizad Solution & Technology", period: "Aug 2019 – Dec 2023" },
  { role: "Software Developer Intern", co: "Bizad Solution & Technology", period: "Sep 2016 – Aug 2019" },
];

function useInView(ref) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVisible(true); }, { threshold: 0.15 });
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, [ref]);
  return visible;
}

function FadeIn({ children, delay = 0, className = "" }) {
  const ref = useRef();
  const vis = useInView(ref);
  return (
    <div ref={ref} className={className} style={{
      opacity: vis ? 1 : 0,
      transform: vis ? "translateY(0)" : "translateY(40px)",
      transition: `all 0.7s cubic-bezier(0.16,1,0.3,1) ${delay}s`,
    }}>{children}</div>
  );
}

function Orb({ color, size, top, left, delay }) {
  return <div style={{
    position: "absolute", top, left, width: size, height: size,
    background: `radial-gradient(circle, ${color}22 0%, transparent 70%)`,
    borderRadius: "50%", filter: "blur(60px)", pointerEvents: "none",
    animation: `orbFloat 8s ease-in-out ${delay || 0}s infinite alternate`,
  }} />;
}

export default function Portfolio() {
  const [activeProject, setActiveProject] = useState(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [scrollY, setScrollY] = useState(0);

  useEffect(() => {
    const handleScroll = () => setScrollY(window.scrollY);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div style={{ background: DARK, minHeight: "100vh", color: "#e2e8f0", fontFamily: "'Outfit', sans-serif", overflow: "hidden", position: "relative" }}
      onMouseMove={e => setMousePos({ x: e.clientX, y: e.clientY })}>

      <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&family=Syne:wght@400;500;600;700;800&display=swap" rel="stylesheet" />

      <style>{`
        @keyframes orbFloat { 0%{transform:translate(0,0) scale(1)} 100%{transform:translate(30px,-40px) scale(1.15)} }
        @keyframes grain { 0%,100%{transform:translate(0,0)} 10%{transform:translate(-5%,-10%)} 30%{transform:translate(3%,2%)} 50%{transform:translate(-2%,8%)} 70%{transform:translate(7%,-5%)} 90%{transform:translate(-3%,3%)} }
        @keyframes shimmer { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
        @keyframes slideUp { from{opacity:0;transform:translateY(60px)} to{opacity:1;transform:translateY(0)} }
        @keyframes typewriter { from{width:0} to{width:100%} }
        @keyframes blink { 0%,100%{border-color:${ACCENT}} 50%{border-color:transparent} }
        @keyframes rotateGrad { 0%{transform:rotate(0deg)} 100%{transform:rotate(360deg)} }
        .grain::before {
          content:''; position:fixed; top:-50%; left:-50%; right:-50%; bottom:-50%;
          background:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          opacity:0.03; pointer-events:none; animation:grain 0.5s steps(1) infinite; z-index:9999;
        }
        .project-card { cursor:pointer; transition:all 0.4s cubic-bezier(0.16,1,0.3,1); }
        .project-card:hover { transform:translateY(-8px) scale(1.02); }
        .project-card:hover .card-glow { opacity:1; }
        .skill-tag { transition:all 0.3s ease; }
        .skill-tag:hover { transform:translateY(-2px); background:rgba(255,255,255,0.1); }
        .nav-link { position:relative; }
        .nav-link::after { content:''; position:absolute; bottom:-4px; left:0; width:0; height:2px; background:${ACCENT}; transition:width 0.3s ease; }
        .nav-link:hover::after { width:100%; }
        .exp-card { transition:all 0.3s ease; border-left:3px solid transparent; }
        .exp-card:hover { border-left-color:${ACCENT}; background:rgba(255,255,255,0.04); }
        .cta-btn { position:relative; overflow:hidden; }
        .cta-btn::before { content:''; position:absolute; top:0; left:-100%; width:100%; height:100%; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.15),transparent); transition:left 0.5s; }
        .cta-btn:hover::before { left:100%; }
        ::selection { background:${ACCENT}44; color:white; }
        * { scrollbar-width:thin; scrollbar-color:${ACCENT}33 transparent; }
      `}</style>

      <div className="grain" />

      {/* Floating orbs */}
      <Orb color={ACCENT} size="500px" top="-10%" left="60%" delay={0} />
      <Orb color={ACCENT2} size="400px" top="30%" left="-10%" delay={2} />
      <Orb color="#8b5cf6" size="350px" top="70%" left="70%" delay={4} />

      {/* Cursor glow */}
      <div style={{
        position: "fixed", width: 300, height: 300, borderRadius: "50%",
        background: `radial-gradient(circle, ${ACCENT}08 0%, transparent 70%)`,
        transform: `translate(${mousePos.x - 150}px, ${mousePos.y - 150}px)`,
        pointerEvents: "none", zIndex: 1, transition: "transform 0.15s ease-out",
      }} />

      {/* NAV */}
      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
        padding: "20px 40px", display: "flex", justifyContent: "space-between", alignItems: "center",
        background: scrollY > 50 ? "rgba(10,10,15,0.85)" : "transparent",
        backdropFilter: scrollY > 50 ? "blur(20px)" : "none",
        borderBottom: scrollY > 50 ? "1px solid rgba(255,255,255,0.05)" : "none",
        transition: "all 0.3s ease",
      }}>
        <div style={{ fontFamily: "Syne", fontWeight: 800, fontSize: 22, letterSpacing: -1 }}>
          <span style={{ color: ACCENT }}>P</span>
          <span style={{ color: "#e2e8f0" }}>K</span>
          <span style={{ color: ACCENT2, fontSize: 10, marginLeft: 4, verticalAlign: "super" }}>●</span>
        </div>
        <div style={{ display: "flex", gap: 32 }}>
          {["About", "Skills", "Projects", "Experience", "Contact"].map(s => (
            <a key={s} href={`#${s.toLowerCase()}`} className="nav-link"
              style={{ color: "#94a3b8", textDecoration: "none", fontSize: 14, fontWeight: 500, letterSpacing: 0.5 }}>{s}</a>
          ))}
        </div>
      </nav>

      {/* HERO */}
      <section style={{ minHeight: "100vh", display: "flex", alignItems: "center", padding: "0 8%", position: "relative" }}>
        <div style={{ maxWidth: 800, position: "relative", zIndex: 2 }}>
          <div style={{ animation: "slideUp 0.8s ease-out" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
              <div style={{ width: 40, height: 2, background: ACCENT }} />
              <span style={{ color: ACCENT, fontSize: 14, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>Available for hire</span>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: ACCENT2, animation: "pulse 2s infinite" }} />
            </div>
            <h1 style={{ fontFamily: "Syne", fontSize: "clamp(48px, 7vw, 88px)", fontWeight: 900, lineHeight: 1, margin: 0, letterSpacing: -3 }}>
              <span style={{ color: "#f8fafc" }}>Peter</span><br />
              <span style={{
                background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              }}>Kekpe</span>
            </h1>
            <p style={{ fontFamily: "Syne", fontSize: "clamp(18px, 2.5vw, 26px)", fontWeight: 500, color: "#94a3b8", margin: "24px 0 16px", lineHeight: 1.4 }}>
              Full-Stack Developer  ·  Product Manager  ·  AI Engineer
            </p>
            <p style={{ fontSize: 16, color: "#64748b", lineHeight: 1.7, maxWidth: 560, margin: "0 0 40px" }}>
              I build products end-to-end — from roadmaps and PRDs to production code. 7+ years shipping web & mobile apps, now supercharged with AI tooling and LLM integrations.
            </p>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              <a href="#projects" className="cta-btn" style={{
                padding: "14px 36px", background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT2})`,
                color: DARK, fontWeight: 700, fontSize: 15, borderRadius: 60, textDecoration: "none",
                letterSpacing: 0.5, display: "inline-block",
              }}>View My Work</a>
              <a href="#contact" className="cta-btn" style={{
                padding: "14px 36px", background: "transparent",
                border: "1.5px solid rgba(255,255,255,0.15)", color: "#e2e8f0",
                fontWeight: 600, fontSize: 15, borderRadius: 60, textDecoration: "none",
              }}>Get In Touch</a>
            </div>
          </div>
        </div>

        {/* Hero decoration */}
        <div style={{
          position: "absolute", right: "5%", top: "50%", transform: "translateY(-50%)",
          width: 400, height: 400, opacity: 0.15,
        }}>
          <div style={{
            width: "100%", height: "100%", borderRadius: "50%",
            border: `1px solid ${ACCENT}44`,
            animation: "rotateGrad 20s linear infinite",
          }}>
            <div style={{ position: "absolute", top: "20%", left: "20%", width: "60%", height: "60%", borderRadius: "50%", border: `1px solid ${ACCENT2}33` }} />
            <div style={{ position: "absolute", top: "35%", left: "35%", width: "30%", height: "30%", borderRadius: "50%", background: `${ACCENT}11` }} />
          </div>
        </div>

        {/* Scroll indicator */}
        <div style={{ position: "absolute", bottom: 40, left: "50%", transform: "translateX(-50%)", display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "#475569", letterSpacing: 2, textTransform: "uppercase" }}>Scroll</span>
          <div style={{ width: 1, height: 40, background: `linear-gradient(to bottom, ${ACCENT}, transparent)` }} />
        </div>
      </section>

      {/* ABOUT */}
      <section id="about" style={{ padding: "120px 8%", position: "relative" }}>
        <FadeIn>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 80, alignItems: "center", maxWidth: 1100, margin: "0 auto" }}>
            <div>
              <span style={{ color: ACCENT, fontSize: 13, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>About Me</span>
              <h2 style={{ fontFamily: "Syne", fontSize: 42, fontWeight: 800, margin: "12px 0 24px", lineHeight: 1.1 }}>
                Developer who thinks in <span style={{ color: ACCENT2 }}>products</span>
              </h2>
              <p style={{ color: "#94a3b8", lineHeight: 1.8, fontSize: 15 }}>
                I'm a Lagos-based full-stack developer and product manager with 7+ years of experience. I don't just write code — I define what gets built and why. From stakeholder discovery and PRDs to sprint planning and deployment, I own the full lifecycle.
              </p>
              <p style={{ color: "#94a3b8", lineHeight: 1.8, fontSize: 15, marginTop: 16 }}>
                Recently, I've been deep in AI-augmented development — using LLMs like Claude and GPT as coding partners, building MCP integrations, and creating intelligent automation systems like algorithmic trading bots with machine learning filtering.
              </p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {[
                { num: "7+", label: "Years Experience" },
                { num: "15+", label: "Projects Shipped" },
                { num: "5+", label: "Trading Bots Built" },
                { num: "3K+", label: "Lines in Largest System" },
              ].map((s, i) => (
                <FadeIn key={s.label} delay={i * 0.1}>
                  <div style={{
                    padding: 28, borderRadius: 16, background: GLASS,
                    border: "1px solid rgba(255,255,255,0.06)", textAlign: "center",
                  }}>
                    <div style={{ fontFamily: "Syne", fontSize: 36, fontWeight: 800, color: ACCENT }}>{s.num}</div>
                    <div style={{ fontSize: 13, color: "#64748b", marginTop: 4 }}>{s.label}</div>
                  </div>
                </FadeIn>
              ))}
            </div>
          </div>
        </FadeIn>
      </section>

      {/* SKILLS */}
      <section id="skills" style={{ padding: "100px 8%", position: "relative" }}>
        <FadeIn>
          <div style={{ maxWidth: 1100, margin: "0 auto" }}>
            <span style={{ color: ACCENT, fontSize: 13, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>Expertise</span>
            <h2 style={{ fontFamily: "Syne", fontSize: 42, fontWeight: 800, margin: "12px 0 48px" }}>Technical Arsenal</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20 }}>
              {skills.map((s, i) => (
                <FadeIn key={s.cat} delay={i * 0.08}>
                  <div className="skill-tag" style={{
                    padding: "24px 28px", borderRadius: 16, background: GLASS,
                    border: "1px solid rgba(255,255,255,0.06)",
                  }}>
                    <div style={{ fontSize: 13, color: ACCENT, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", marginBottom: 10 }}>{s.cat}</div>
                    <div style={{ fontSize: 14, color: "#94a3b8", lineHeight: 1.7 }}>{s.items}</div>
                  </div>
                </FadeIn>
              ))}
            </div>
          </div>
        </FadeIn>
      </section>

      {/* PROJECTS */}
      <section id="projects" style={{ padding: "100px 8%", position: "relative" }}>
        <FadeIn>
          <div style={{ maxWidth: 1100, margin: "0 auto" }}>
            <span style={{ color: ACCENT, fontSize: 13, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>Portfolio</span>
            <h2 style={{ fontFamily: "Syne", fontSize: 42, fontWeight: 800, margin: "12px 0 48px" }}>Selected Work</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              {projects.map((p, i) => (
                <FadeIn key={p.title} delay={i * 0.1}>
                  <div className="project-card"
                    onClick={() => setActiveProject(activeProject === i ? null : i)}
                    style={{
                      padding: "36px 40px", borderRadius: 20, background: GLASS,
                      border: `1px solid ${activeProject === i ? p.color + "44" : "rgba(255,255,255,0.06)"}`,
                      position: "relative", overflow: "hidden",
                    }}>
                    {/* Glow */}
                    <div className="card-glow" style={{
                      position: "absolute", top: 0, right: 0, width: 200, height: 200,
                      background: `radial-gradient(circle, ${p.color}15, transparent 70%)`,
                      opacity: 0, transition: "opacity 0.4s",
                    }} />
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", position: "relative" }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
                          <span style={{ fontSize: 28 }}>{p.icon}</span>
                          <div>
                            <h3 style={{ fontFamily: "Syne", fontSize: 22, fontWeight: 700, margin: 0, color: "#f1f5f9" }}>{p.title}</h3>
                            <span style={{ fontSize: 13, color: p.color, fontWeight: 600 }}>{p.subtitle}</span>
                          </div>
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "16px 0" }}>
                          {p.stack.map(t => (
                            <span key={t} style={{
                              padding: "4px 12px", borderRadius: 20, fontSize: 11, fontWeight: 600,
                              background: `${p.color}15`, color: p.color, letterSpacing: 0.5,
                            }}>{t}</span>
                          ))}
                        </div>
                        <div style={{
                          maxHeight: activeProject === i ? 200 : 0, overflow: "hidden",
                          transition: "max-height 0.5s cubic-bezier(0.16,1,0.3,1)",
                        }}>
                          <p style={{ fontSize: 14, color: "#94a3b8", lineHeight: 1.8, margin: "12px 0 0" }}>{p.desc}</p>
                        </div>
                      </div>
                      <div style={{
                        width: 36, height: 36, borderRadius: "50%", border: "1px solid rgba(255,255,255,0.1)",
                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                        transform: activeProject === i ? "rotate(45deg)" : "rotate(0deg)",
                        transition: "transform 0.3s ease", marginLeft: 20,
                      }}>
                        <span style={{ fontSize: 18, color: "#64748b" }}>+</span>
                      </div>
                    </div>
                  </div>
                </FadeIn>
              ))}
            </div>
          </div>
        </FadeIn>
      </section>

      {/* EXPERIENCE */}
      <section id="experience" style={{ padding: "100px 8%", position: "relative" }}>
        <FadeIn>
          <div style={{ maxWidth: 1100, margin: "0 auto" }}>
            <span style={{ color: ACCENT, fontSize: 13, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>Career</span>
            <h2 style={{ fontFamily: "Syne", fontSize: 42, fontWeight: 800, margin: "12px 0 48px" }}>Experience</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {experience.map((e, i) => (
                <FadeIn key={e.role} delay={i * 0.12}>
                  <div className="exp-card" style={{
                    padding: "28px 32px", borderRadius: 16, background: GLASS,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                      <div>
                        <h3 style={{ fontFamily: "Syne", fontSize: 18, fontWeight: 700, margin: 0, color: "#f1f5f9" }}>{e.role}</h3>
                        <span style={{ fontSize: 14, color: ACCENT2 }}>{e.co}</span>
                      </div>
                      <span style={{ fontSize: 13, color: "#64748b", fontWeight: 500, whiteSpace: "nowrap" }}>{e.period}</span>
                    </div>
                  </div>
                </FadeIn>
              ))}
            </div>
          </div>
        </FadeIn>
      </section>

      {/* CONTACT */}
      <section id="contact" style={{ padding: "120px 8% 80px", position: "relative" }}>
        <FadeIn>
          <div style={{ maxWidth: 700, margin: "0 auto", textAlign: "center" }}>
            <span style={{ color: ACCENT, fontSize: 13, fontWeight: 600, letterSpacing: 3, textTransform: "uppercase" }}>Contact</span>
            <h2 style={{ fontFamily: "Syne", fontSize: "clamp(36px, 5vw, 56px)", fontWeight: 900, margin: "12px 0 24px", lineHeight: 1.1 }}>
              Let's build something <span style={{ color: ACCENT2 }}>great</span>
            </h2>
            <p style={{ fontSize: 16, color: "#64748b", lineHeight: 1.7, marginBottom: 40 }}>
              I'm currently open to new opportunities — whether it's a full-time role, freelance project, or product collaboration. Let's talk.
            </p>
            <div style={{ display: "flex", justifyContent: "center", gap: 20, flexWrap: "wrap" }}>
              {[
                { label: "kekpepeter@gmail.com", icon: "✉" },
                { label: "+234 902 598 4606", icon: "📱" },
                { label: "github.com/Rien-petruz", icon: "⚡" },
              ].map(c => (
                <div key={c.label} style={{
                  padding: "14px 28px", borderRadius: 60, background: GLASS,
                  border: "1px solid rgba(255,255,255,0.08)", fontSize: 14, color: "#94a3b8",
                  display: "flex", alignItems: "center", gap: 10,
                }}>
                  <span>{c.icon}</span> {c.label}
                </div>
              ))}
            </div>
          </div>
        </FadeIn>

        {/* Footer */}
        <div style={{ marginTop: 100, textAlign: "center", paddingTop: 40, borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          <span style={{ fontSize: 12, color: "#334155" }}>© 2026 Peter Kekpe. Built with passion & AI.</span>
        </div>
      </section>
    </div>
  );
}
