import { fmt, type Overview } from "../api";
import { Card, LatencyTable, Pill, Signed, Stat } from "./Bits";

export function OverviewView({ o }: { o: Overview | null }) {
  if (!o) return <div className="loading">Waiting for the engine…</div>;
  const h = o.health;
  const btc = o.reference["BINANCE:BTCUSDT"];
  return (
    <div className="grid">
      <div className="stats-row">
        <Stat label="Engine health" value={<Pill value={h.status} />}
              sub={h.reasons.length ? h.reasons.slice(0, 2).join(" · ") : `up ${fmt.num(h.uptime_s, 0)} s`} />
        <Stat label="Connections" value={`${h.connections_up}/${h.connections_total}`}
              tone={h.connections_up < h.connections_total ? "warn" : undefined} />
        <Stat label="Usable instruments" value={`${h.instruments_usable}/${h.instruments_total}`} />
        <Stat label="Throughput" value={`${fmt.num(h.frames_per_s, 0)} msg/s`} sub={`${fmt.num(h.frames, 0)} frames total`} />
        <Stat label="Paper P&L (simulated)" value={<Signed v={o.paper?.pnl_usd} unit="usd" />}
              sub={o.paper ? `equity ${fmt.usd(o.paper.equity_usd)}${o.paper.halted ? " · HALTED" : ""}` : "initialising"}
              tone={o.paper?.halted ? "bad" : undefined} />
      </div>

      <Card title="BTCUSDT reference (Binance)">
        <div className="stats-row">
          <Stat label="Bid" value={fmt.px(btc?.bid)} />
          <Stat label="Ask" value={fmt.px(btc?.ask)} />
          <Stat label="Mid" value={fmt.px(btc?.mid)} sub={fmt.bps(btc?.spread_bps) + " spread"} />
          <Stat label="Quote status" value={<Pill value={btc?.status} />} sub={`age ${fmt.ms(btc?.book_age_ms)}`} />
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Instrument</th><th className="num">Bid</th><th className="num">Ask</th><th className="num">Spread</th>
              <th>Status</th><th className="num">Age</th><th className="num">Exchange time</th></tr></thead>
            <tbody>
              {Object.entries(o.reference).map(([k, q]) => (
                <tr key={k}><td className="mono">{k}</td><td className="num">{fmt.px(q.bid)}</td><td className="num">{fmt.px(q.ask)}</td>
                  <td className="num">{fmt.bps(q.spread_bps)}</td><td><Pill value={q.status} /></td>
                  <td className="num">{fmt.ms(q.book_age_ms)}</td>
                  <td className="num">{q.exchange_time_ms ? new Date(q.exchange_time_ms).toLocaleTimeString() : <span className="muted" title="venue provides no quote timestamp">n/a</span>}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Venues">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Venue</th><th className="num">Connections</th><th className="num">Usable</th><th>Status mix</th>
              <th className="num">Last frame</th><th className="num">Reconnects</th><th>Clock offset</th><th>Metadata</th></tr></thead>
            <tbody>
              {Object.entries(h.venues).map(([v, d]) => (
                <tr key={v}>
                  <td><strong>{v}</strong></td>
                  <td className="num">{d.connections_up}/{d.connections_total}</td>
                  <td className="num">{d.usable}/{d.instruments}</td>
                  <td>{Object.entries(d.status_counts).map(([s, n]) => <span key={s} className="mix"><Pill value={s} /> {n}</span>)}</td>
                  <td className="num">{fmt.ms(d.last_frame_age_ms)}</td>
                  <td className="num">{d.reconnects}</td>
                  <td>{d.clock_offset ? `${fmt.num(d.clock_offset.offset_ms)} ± ${fmt.num(d.clock_offset.uncertainty_ms)} ms` : "—"}</td>
                  <td title={d.note}>{d.metadata_ok ? "exchange metadata" : <span className="warn-text">fallback list</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="two-col">
        <Card title="Strategies">
          <div className="stats-row">
            <Stat label="Cross-exchange open" value={o.cross_exchange?.open ?? "—"}
                  sub={`${o.cross_exchange?.pairs ?? 0} pairs · ${o.cross_exchange?.opened_total ?? 0} candidates`} />
            <Stat label="Triangular open" value={o.triangular?.open ?? "—"}
                  sub={`${o.triangular?.routes ?? 0} routes · ${o.triangular?.opened_total ?? 0} candidates`} />
            <Stat label="Active anomalies (30 s)" value={o.anomalies?.active ?? "—"} />
            <Stat label="Simulated fills" value={o.paper?.counters?.fills ?? "—"}
                  sub={o.paper ? `${o.paper.counters.filled ?? 0} filled · ${o.paper.counters.missed ?? 0} missed` : undefined} />
          </div>
        </Card>
        <Card title="Latency (last window, µs)">
          <LatencyTable rows={o.latency_us} />
        </Card>
      </div>
    </div>
  );
}
