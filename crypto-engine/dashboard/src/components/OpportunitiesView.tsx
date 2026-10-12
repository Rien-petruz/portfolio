import { fmt, usePoll, type Row } from "../api";
import { Card, ErrorNote, Pill, Signed, Stat } from "./Bits";
import { Table, type Column } from "./Table";

interface Resp {
  pairs?: number; routes?: number; evaluations: number; quick_rejects?: number;
  tracker: Record<string, number | null>; open: Row[]; recent_closed: Row[]; scanner: Row[];
}

const cur = (r: Row) => (r.current ?? r) as Row;
const reasons = (r: Row) => ((cur(r).reasons as string[]) ?? []).join(", ");

export function CrossExchangeView() {
  const { data, error } = usePoll<Resp>("/api/opportunities?strategy=cross_exchange&limit=300", 1000);
  const cols: Column<Row>[] = [
    { key: "base", label: "Asset", value: (r) => r.base, render: (r) => <strong>{String(r.base)}</strong> },
    { key: "route", label: "Buy → Sell", value: (r) => r.route_id,
      render: (r) => <span className="mono">{String(r.buy_key)} → {String(r.sell_key)}</span> },
    { key: "buy_ask", label: "Buy ask", align: "right", render: (r) => fmt.px(r.buy_ask) },
    { key: "sell_bid", label: "Sell bid", align: "right", render: (r) => fmt.px(r.sell_bid) },
    { key: "gross_bps", label: "Gross", align: "right", render: (r) => <Signed v={r.gross_bps} unit="bps" /> },
    { key: "fee_bps", label: "Fees", align: "right", render: (r) => fmt.bps(r.fee_bps) },
    { key: "conversion_bps", label: "Conv.", align: "right", title: "conversion spread + fee (different quote currencies)",
      render: (r) => (r.conversion ? fmt.bps(r.conversion_bps) : <span className="muted">same ccy</span>) },
    { key: "slippage_bps", label: "Slippage", align: "right", render: (r) => fmt.bps(r.slippage_bps) },
    { key: "net_bps", label: "Net", align: "right", render: (r) => <Signed v={r.net_bps} unit="bps" /> },
    { key: "quote_age_ms", label: "Age", align: "right", render: (r) => fmt.ms(r.quote_age_ms) },
    { key: "recv_skew_ms", label: "Skew", align: "right", title: "receive-time skew between legs (± delivery-lag uncertainty)",
      render: (r) => <span title={`event skew: ${r.event_skew_ms ?? "n/a"} · uncertainty ±${fmt.num(r.skew_uncertainty_ms, 1)} ms`}>{fmt.ms(r.recv_skew_ms)}</span> },
    { key: "liquidity_usd", label: "Liquidity", align: "right", render: (r) => fmt.usd(r.liquidity_usd) },
    { key: "qty", label: "Exec. size", align: "right", render: (r) => <span title={`limited by ${r.size_limited_by}`}>{fmt.num(r.qty, 6)}</span> },
    { key: "expected_profit_usd", label: "Exp. P&L", align: "right", render: (r) => <Signed v={r.expected_profit_usd} unit="usd" /> },
    { key: "status", label: "Status", render: (r) => <Pill value={r.status} title={reasons(r)} /> },
  ];
  const scanner = (data?.scanner ?? []).filter((r) => typeof r.buy_ask === "number");
  const epCols: Column<Row>[] = [
    { key: "route_id", label: "Route", render: (r) => <span className="mono">{String(r.route_id)}</span> },
    { key: "status", label: "Status", render: (r) => <Pill value={r.status} title={reasons(r)} /> },
    { key: "peak_net_bps", label: "Peak net", align: "right", render: (r) => <Signed v={r.peak_net_bps} unit="bps" /> },
    { key: "lifetime_ms", label: "Lifetime", align: "right", render: (r) => fmt.ms(r.lifetime_ms) },
    { key: "updates", label: "Updates", align: "right" },
    { key: "execution", label: "Simulated execution", value: (r) => (r.execution as Row | null)?.status,
      render: (r) => { const e = r.execution as Row | null; return e ? <span><Pill value={e.status} /> {e.pnl_usd !== undefined ? <Signed v={e.pnl_usd} unit="usd" /> : null}</span> : <span className="muted">—</span>; } },
    { key: "close_reason", label: "Closed", render: (r) => String(r.close_reason || "open") },
  ];
  return (
    <div className="grid">
      <ErrorNote error={error} />
      <div className="stats-row">
        <Stat label="Pairs monitored" value={data?.pairs ?? "—"} sub="verified mappings only" />
        <Stat label="Open candidates" value={data?.tracker.open ?? "—"} />
        <Stat label="Candidates (total)" value={data?.tracker.opened_total ?? "—"} sub={`${data?.evaluations ?? 0} full evaluations`} />
        <Stat label="Median lifetime" value={fmt.ms(data?.tracker.median_lifetime_ms)} />
      </div>
      <Card title="Cross-exchange scanner (executable bid/ask, all costs)">
        <Table rows={scanner} columns={cols} rowKey={(r) => String(r.route_id)} initialSort={{ key: "net_bps", desc: true }} maxRows={200}
               rowClass={(r) => (r.status === "VALID" ? "highlight" : undefined)} />
      </Card>
      <div className="two-col">
        <Card title="Open opportunity episodes"><Table rows={data?.open ?? []} columns={epCols} rowKey={(r) => String(r.episode_id)} empty="No open candidates" /></Card>
        <Card title="Recently closed"><Table rows={data?.recent_closed ?? []} columns={epCols} rowKey={(r) => String(r.episode_id)} empty="None yet" /></Card>
      </div>
    </div>
  );
}

export function TriangularView() {
  const { data, error } = usePoll<Resp>("/api/opportunities?strategy=triangular&limit=200", 1500);
  const cols: Column<Row>[] = [
    { key: "route_id", label: "Route", render: (r) => <span className="mono">{String(r.route_id)}</span> },
    { key: "path", label: "Legs", value: (r) => (r.path as string[]).join(" "), render: (r) => (r.path as string[]).join(" → ") },
    { key: "gross_bps", label: "Gross", align: "right", render: (r) => <Signed v={r.gross_bps} unit="bps" /> },
    { key: "theoretical_net_bps", label: "Theoretical net", align: "right", title: "fees, no rounding/minimums", render: (r) => <Signed v={r.theoretical_net_bps} unit="bps" /> },
    { key: "net_bps", label: "Executable net", align: "right", title: "rounded to steps at max feasible capital", render: (r) => <Signed v={r.net_bps} unit="bps" /> },
    { key: "start_capital", label: "Start capital", align: "right", render: (r) => `${fmt.num(r.start_capital, 4)} ${r.start_asset}` },
    { key: "expected_profit_usd", label: "Exp. P&L", align: "right", render: (r) => <Signed v={r.expected_profit_usd} unit="usd" /> },
    { key: "recv_skew_ms", label: "Skew", align: "right", render: (r) => fmt.ms(r.recv_skew_ms) },
    { key: "status", label: "Status", render: (r) => <Pill value={r.status} title={((r.reasons as string[]) ?? []).join(", ")} /> },
  ];
  return (
    <div className="grid">
      <ErrorNote error={error} />
      <div className="stats-row">
        <Stat label="Routes" value={data?.routes ?? "—"} />
        <Stat label="Open candidates" value={data?.tracker.open ?? "—"} />
        <Stat label="Candidates (total)" value={data?.tracker.opened_total ?? "—"} />
        <Stat label="Pre-screened (no edge)" value={data?.quick_rejects ?? "—"} />
      </div>
      <Card title="Triangular routes (gross-positive evaluations)">
        <Table rows={data?.scanner ?? []} columns={cols} rowKey={(r) => String(r.route_id)} initialSort={{ key: "net_bps", desc: true }}
               empty="No gross-positive route evaluated yet" />
      </Card>
    </div>
  );
}
