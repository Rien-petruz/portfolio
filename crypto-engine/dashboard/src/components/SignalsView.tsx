import { useState } from "react";
import { fmt, usePoll, type Row } from "../api";
import { Card, ErrorNote, Pill } from "./Bits";
import { Table, type Column } from "./Table";

interface SigResp { counts: Record<string, number>; recent: Row[]; note?: string }
interface EvalResp { horizons_s: number[]; min_sample: number; registered: number; results: Record<string, Record<string, Row>>; caveats: string[] }

const dir = (d: unknown) => (d === 1 ? "▲ long" : d === -1 ? "▼ short" : "◆ none");

export function SignalsView() {
  const [kind, setKind] = useState<"pattern" | "anomaly">("pattern");
  const { data, error } = usePoll<SigResp>(`/api/signals?kind=${kind}&limit=300`, 1500);
  const ev = usePoll<EvalResp>("/api/signals/evaluation", 5000);
  const cols: Column<Row>[] = [
    { key: "detected_wall_ns", label: "Detected", render: (r) => fmt.time(r.detected_wall_ns) },
    { key: "strategy", label: "Strategy", render: (r) => <span className="mono">{String(r.strategy)}</span> },
    { key: "key", label: "Instrument", render: (r) => <span className="mono">{String(r.key)}</span> },
    { key: "direction", label: "Direction", render: (r) => dir(r.direction) },
    { key: "strength", label: "Strength", align: "right", title: "robust z or ratio; NOT a probability",
      render: (r) => `${fmt.num(r.strength, 2)} ${r.score_kind === "ratio" ? "×" : "z"}` },
    { key: "classification", label: "Class", render: (r) => <Pill value={r.classification} /> },
    { key: "data_quality", label: "Data", render: (r) => <Pill value={r.data_quality} /> },
    { key: "explanation", label: "Explanation", render: (r) => <span className="expl">{String(r.explanation)}</span> },
    { key: "validation_status", label: "Validation", render: (r) => {
        const h = ((r.evaluation as Row)?.horizons ?? {}) as Record<string, Row>;
        const last = Object.values(h).at(-1);
        return <span><Pill value={r.validation_status} />{last && typeof last.fwd_bps === "number" ? ` ${fmt.bps(last.fwd_bps)}` : ""}</span>;
      } },
  ];
  const evalRows: Row[] = [];
  for (const [strategy, byH] of Object.entries(ev.data?.results ?? {})) {
    for (const [h, v] of Object.entries(byH)) evalRows.push({ strategy, horizon: Number(h), ...v });
  }
  const evalCols: Column<Row>[] = [
    { key: "strategy", label: "Strategy", render: (r) => <span className="mono">{String(r.strategy)}</span> },
    { key: "horizon", label: "Horizon", align: "right", render: (r) => `${r.horizon}s` },
    { key: "n", label: "n", align: "right" },
    { key: "mean_bps", label: "Mean", align: "right", render: (r) => fmt.bps(r.mean_bps) },
    { key: "se_bps", label: "SE", align: "right", render: (r) => fmt.bps(r.se_bps) },
    { key: "hit_rate", label: "Hit rate", align: "right", render: (r) => (typeof r.hit_rate === "number" ? `${(r.hit_rate * 100).toFixed(1)}%` : "—") },
    { key: "mean_net_bps", label: "Net of costs", align: "right", render: (r) => fmt.bps(r.mean_net_bps) },
    { key: "vs_baseline_t", label: "t vs baseline", align: "right", render: (r) => fmt.num(r.vs_baseline_t, 2) },
    { key: "verdict", label: "Verdict", render: (r) => <span className="expl">{String(r.verdict ?? "")}</span> },
  ];
  return (
    <div className="grid">
      <ErrorNote error={error} />
      <Card title={`${kind === "pattern" ? "Pattern monitor" : "Anomaly feed"}`} actions={
        <div className="filters">
          <select value={kind} onChange={(e) => setKind(e.target.value as "pattern" | "anomaly")}>
            <option value="pattern">patterns</option><option value="anomaly">anomalies</option>
          </select>
          <span className="muted">{Object.entries(data?.counts ?? {}).map(([k, n]) => `${k}: ${n}`).join(" · ")}</span>
        </div>}>
        <p className="note">Scores are robust z-scores or ratios describing how unusual an observation is — never probabilities of profit.</p>
        <Table rows={data?.recent ?? []} columns={cols} rowKey={(r) => String(r.signal_id)} initialSort={{ key: "detected_wall_ns", desc: true }} empty="No signals yet (baselines need warm-up)" />
      </Card>
      <Card title={`Signal evaluation vs baselines (min n = ${ev.data?.min_sample ?? 30})`}>
        <Table rows={evalRows} columns={evalCols} rowKey={(r) => `${r.strategy}-${r.horizon}`} initialSort={{ key: "n", desc: true }} empty="No evaluated signals yet" />
        <ul className="caveats">{(ev.data?.caveats ?? []).map((c) => <li key={c}>{c}</li>)}</ul>
      </Card>
    </div>
  );
}
