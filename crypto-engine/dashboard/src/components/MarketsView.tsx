import { useState } from "react";
import { fmt, usePoll, type Row } from "../api";
import { Card, ErrorNote, Pill, Signed } from "./Bits";
import { Table, type Column } from "./Table";

interface Resp { count: number; markets: Row[] }

const n = (r: Row, k: string) => r[k] as number | null;

export function MarketsView() {
  const [venue, setVenue] = useState("");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [onlySignals, setOnlySignals] = useState(false);
  const qs = new URLSearchParams({ limit: "5000", ...(venue ? { venue } : {}), ...(status ? { status } : {}) });
  const { data, error } = usePoll<Resp>(`/api/markets?${qs}`, 1000);
  let rows = data?.markets ?? [];
  if (query) rows = rows.filter((r) => String(r.key).toLowerCase().includes(query.toLowerCase()));
  if (onlySignals) rows = rows.filter((r) => r.signal);
  const cols: Column<Row>[] = [
    { key: "key", label: "Instrument", render: (r) => <span className="mono">{String(r.key)}</span> },
    { key: "status", label: "Status", render: (r) => <Pill value={r.status} /> },
    { key: "bid", label: "Bid", align: "right", render: (r) => fmt.px(r.bid) },
    { key: "ask", label: "Ask", align: "right", render: (r) => fmt.px(r.ask) },
    { key: "mid", label: "Mid", align: "right", render: (r) => fmt.px(r.mid) },
    { key: "spread_bps", label: "Spread", align: "right", render: (r) => fmt.bps(r.spread_bps) },
    { key: "return_5s_bps", label: "5s return", align: "right", render: (r) => <Signed v={n(r, "return_5s_bps")} unit="bps" /> },
    { key: "vol_1s_bps", label: "1s vol", align: "right", render: (r) => fmt.bps(r.vol_1s_bps), title: "robust 1s volatility (1.4826 x MAD)" },
    { key: "liquidity", label: "Touch liq.", align: "right", render: (r) => fmt.num(r.liquidity, 0), title: "avg of bid and ask notional at the touch (quote ccy)" },
    { key: "touch_imbalance", label: "Imbalance", align: "right", render: (r) => fmt.num(r.depth_imbalance_10 ?? r.touch_imbalance, 2) },
    { key: "book_age_ms", label: "Data age", align: "right", render: (r) => fmt.ms(r.book_age_ms) },
    { key: "anomaly_score", label: "Anomaly", align: "right", title: "max |robust z| across windows (a score, not a probability)",
      render: (r) => { const v = n(r, "anomaly_score"); return <span className={v !== null && v >= 5 ? "warn-text" : ""}>{fmt.num(v, 1)}</span>; } },
    { key: "signal", label: "Signal", render: (r) => r.signal ? <span className="tag">{String(r.signal)}</span> : <span className="muted">—</span> },
  ];
  return (
    <Card title={`Market scanner (${rows.length})`} actions={
      <div className="filters">
        <input placeholder="filter instrument…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <select value={venue} onChange={(e) => setVenue(e.target.value)}>
          <option value="">all venues</option><option>BINANCE</option><option>COINBASE</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">any status</option><option>LIVE</option><option>QUIET</option><option>STALE</option>
          <option value="DISCONNECTED,UNINITIALIZED">not available</option><option>CROSSED</option>
        </select>
        <label><input type="checkbox" checked={onlySignals} onChange={(e) => setOnlySignals(e.target.checked)} /> with signal</label>
      </div>}>
      <ErrorNote error={error} />
      <Table rows={rows} columns={cols} rowKey={(r) => String(r.key)} initialSort={{ key: "anomaly_score", desc: true }}
             rowClass={(r) => (r.status !== "LIVE" && r.status !== "QUIET" ? "dim" : undefined)} />
    </Card>
  );
}
