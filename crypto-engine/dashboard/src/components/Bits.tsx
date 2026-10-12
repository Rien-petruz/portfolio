import type { ReactNode } from "react";
import { fmt, type LatencySummary } from "../api";

const TONE: Record<string, string> = {
  OK: "good", LIVE: "good", VALID: "good", FILLED: "good", SYNCED: "good", CORROBORATED_MOVE: "info",
  QUIET: "muted", DEGRADED: "warn", PARTIAL: "warn", STARTING: "muted", CANDIDATE: "info", PENDING: "muted",
  STALE: "bad", DOWN: "bad", DISCONNECTED: "bad", CROSSED: "bad", REJECTED: "bad", MISSED: "warn",
  UNINITIALIZED: "muted", CANCELED: "muted", EXPIRED: "muted", ONE_SIDED: "warn", DATA_QUALITY_SUSPECT: "bad",
  UNCORROBORATED: "warn", SIMULATED: "warn", LIVE_DATA: "good", REPLAY: "info",
};

export function Pill({ value, title }: { value: unknown; title?: string }) {
  const v = String(value ?? "—");
  return <span className={`pill ${TONE[v] ?? "muted"}`} title={title}>{v.replaceAll("_", " ")}</span>;
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub !== undefined && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Card({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      <header><h2>{title}</h2>{actions}</header>
      {children}
    </section>
  );
}

export function Signed({ v, unit }: { v: unknown; unit: "bps" | "usd" }) {
  if (typeof v !== "number" || !Number.isFinite(v)) return <span className="muted">—</span>;
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "";
  return <span className={cls}>{unit === "bps" ? fmt.bps(v) : fmt.usd(v)}</span>;
}

export function LatencyTable({ rows }: { rows: Record<string, LatencySummary> }) {
  const names = Object.keys(rows).filter((k) => !k.startsWith("_")).sort();
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Stage</th><th className="num">n</th><th className="num">p50</th><th className="num">p95</th>
          <th className="num">p99</th><th className="num">max</th></tr></thead>
        <tbody>
          {names.map((n) => {
            const s = rows[n];
            return (
              <tr key={n}>
                <td className="mono">{n}{s.partial ? <span className="muted"> (partial window)</span> : null}</td>
                <td className="num">{s.count ?? 0}</td>
                <td className="num">{fmt.us(s.p50)}</td><td className="num">{fmt.us(s.p95)}</td>
                <td className="num">{fmt.us(s.p99)}</td><td className="num">{fmt.us(s.max)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <div className="error-note">Backend unavailable: {error}</div> : null;
}
