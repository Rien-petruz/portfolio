import { useState } from "react";
import { fmt, usePoll, type Row } from "../api";
import { Card, ErrorNote, Pill, Signed, Stat } from "./Bits";
import { Table, type Column } from "./Table";

interface PaperResp {
  mode: string; banner: string; initialized: boolean; daily_pnl_usd: number | null;
  portfolio: (Row & { positions: Row[]; exposure_by_venue_usd: Record<string, number> }) | null;
  risk: { halted: boolean; halt_reason: string; health_blocked: boolean; decisions: Record<string, number>;
          reject_reasons: Record<string, number>; limits: Record<string, unknown> };
  counters: Record<string, number>; open_orders: Row[]; recent_orders: Row[]; recent_fills: Row[]; recent_executions: Row[];
}

export function PaperView() {
  const { data, error } = usePoll<PaperResp>("/api/paper", 1000);
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState("");
  const control = async (path: string) => {
    const r = await fetch(path, { method: "POST", headers: { "X-Control-Token": token } });
    setMsg(r.ok ? "done" : `HTTP ${r.status}: ${(await r.json().catch(() => ({}))).detail ?? ""}`);
  };
  const p = data?.portfolio;
  const orderCols: Column<Row>[] = [
    { key: "created_wall_ns", label: "Created", render: (r) => fmt.time(r.created_wall_ns) },
    { key: "strategy", label: "Strategy" }, { key: "leg", label: "Leg" },
    { key: "key", label: "Instrument", render: (r) => <span className="mono">{String(r.key)}</span> },
    { key: "side", label: "Side" }, { key: "type", label: "Type", render: (r) => `${r.type}/${r.tif}` },
    { key: "qty", label: "Qty", align: "right", render: (r) => fmt.num(r.qty, 6) },
    { key: "limit_price", label: "Limit", align: "right", render: (r) => fmt.px(r.limit_price) },
    { key: "filled_qty", label: "Filled", align: "right", render: (r) => fmt.num(r.filled_qty, 6) },
    { key: "avg_price", label: "Avg px", align: "right", render: (r) => fmt.px(r.avg_price) },
    { key: "slippage_bps", label: "Slippage", align: "right", render: (r) => <Signed v={r.slippage_bps} unit="bps" /> },
    { key: "latency_ms", label: "Latency", align: "right", render: (r) => fmt.ms(r.latency_ms) },
    { key: "status", label: "Status", render: (r) => <span><Pill value={r.status} title={String(r.reject_reason ?? "")} />{r.estimate ? <span className="tag" title="top-of-book estimate">est.</span> : null}</span> },
  ];
  const fillCols: Column<Row>[] = [
    { key: "wall_ns", label: "Time", render: (r) => fmt.time(r.wall_ns) },
    { key: "key", label: "Instrument", render: (r) => <span className="mono">{String(r.key)}</span> },
    { key: "side", label: "Side" },
    { key: "price", label: "Price", align: "right", render: (r) => fmt.px(r.price) },
    { key: "qty", label: "Qty", align: "right", render: (r) => fmt.num(r.qty, 6) },
    { key: "fee_quote", label: "Fee", align: "right", render: (r) => fmt.num(r.fee_quote, 6) },
    { key: "liquidity", label: "Model", render: (r) => <span title={r.estimate ? "estimate: hidden liquidity/queue unknown" : "walked local L2 book"}>{String(r.liquidity)}{r.estimate ? " (est.)" : ""}</span> },
  ];
  const execCols: Column<Row>[] = [
    { key: "strategy", label: "Strategy" },
    { key: "route_id", label: "Route", render: (r) => <span className="mono">{String(r.route_id)}</span> },
    { key: "status", label: "Outcome", render: (r) => <Pill value={r.status} /> },
    { key: "expected_profit_usd", label: "Expected", align: "right", render: (r) => <Signed v={r.expected_profit_usd} unit="usd" /> },
    { key: "pnl_usd", label: "Simulated P&L", align: "right", title: "mark-to-market of all asset flows (incl. unhedged legs)",
      render: (r) => <span title={`quote cash flow ${fmt.usd(r.quote_cashflow_usd)}`}><Signed v={r.pnl_usd} unit="usd" /></span> },
    { key: "simulated_slippage_bps", label: "Slippage (est → sim)", align: "right",
      render: (r) => `${fmt.num(r.expected_slippage_bps, 2)} → ${fmt.num(r.simulated_slippage_bps, 2)}` },
    { key: "duration_ms", label: "Duration", align: "right", render: (r) => fmt.ms(r.duration_ms) },
  ];
  const posCols: Column<Row>[] = [
    { key: "venue", label: "Venue" }, { key: "asset", label: "Asset" },
    { key: "qty", label: "Balance", align: "right", render: (r) => fmt.num(r.qty, 6) },
    { key: "reserved", label: "Reserved", align: "right", render: (r) => fmt.num(r.reserved, 6) },
    { key: "position", label: "Position vs start", align: "right", render: (r) => fmt.num(r.position, 6) },
    { key: "mark_usd", label: "Mark", align: "right", render: (r) => fmt.px(r.mark_usd) },
    { key: "value_usd", label: "Value", align: "right", render: (r) => fmt.usd(r.value_usd) },
    { key: "unrealized_usd", label: "Unrealized", align: "right", render: (r) => <Signed v={r.unrealized_usd} unit="usd" /> },
  ];
  return (
    <div className="grid">
      <ErrorNote error={error} />
      <div className="paper-warning">All balances, orders, fills and P&amp;L below are <strong>SIMULATED</strong>. Paper results are not evidence of live profitability.</div>
      <div className="stats-row">
        <Stat label="Equity (virtual)" value={fmt.usd(p?.equity_usd)} sub={`start ${fmt.usd(p?.initial_equity_usd)} + funding ${fmt.usd(p?.funding_usd)}`} />
        <Stat label="P&L" value={<Signed v={p?.pnl_usd} unit="usd" />} sub={<>realized <Signed v={p?.realized_usd} unit="usd" /> · unrealized <Signed v={p?.unrealized_usd} unit="usd" /></>} />
        <Stat label="Daily P&L" value={<Signed v={data?.daily_pnl_usd} unit="usd" />} sub={`fees ${fmt.usd(p?.fees_usd)}`} />
        <Stat label="Exposure" value={fmt.usd(p?.total_exposure_usd)} sub={Object.entries(p?.exposure_by_venue_usd ?? {}).map(([v, x]) => `${v} ${fmt.usd(x)}`).join(" · ")} />
        <Stat label="Risk" value={data?.risk.halted ? <Pill value="HALTED" /> : <Pill value="OK" />}
              sub={data?.risk.halted ? data.risk.halt_reason : `${data?.risk.decisions.accepted ?? 0} accepted · ${data?.risk.decisions.rejected ?? 0} rejected`}
              tone={data?.risk.halted ? "bad" : undefined} />
      </div>
      <Card title="Simulation controls" actions={
        <div className="filters">
          <input type="password" placeholder="control token" value={token} onChange={(e) => setToken(e.target.value)} />
          <button className="danger" onClick={() => control("/api/paper/emergency-stop?reason=dashboard")}>Emergency stop (simulation)</button>
          <button onClick={() => control("/api/paper/resume")}>Resume</button>
          <span className="muted">{msg}</span>
        </div>}>
        <div className="kv">{Object.entries(data?.risk.reject_reasons ?? {}).map(([k, n]) => <span key={k} className="tag">{k}: {n}</span>)}</div>
      </Card>
      <Card title="Simulated executions"><Table rows={data?.recent_executions ?? []} columns={execCols} rowKey={(r, i) => `${r.parent_id}-${i}`} empty="No simulated executions yet" /></Card>
      <div className="two-col">
        <Card title="Open / recent simulated orders"><Table rows={[...(data?.open_orders ?? []), ...(data?.recent_orders ?? [])].slice(0, 200)} columns={orderCols} rowKey={(r, i) => `${r.client_id}-${i}`} initialSort={{ key: "created_wall_ns", desc: true }} /></Card>
        <Card title="Simulated fills"><Table rows={data?.recent_fills ?? []} columns={fillCols} rowKey={(r) => String(r.fill_id)} initialSort={{ key: "wall_ns", desc: true }} /></Card>
      </div>
      <Card title="Virtual balances and positions"><Table rows={p?.positions ?? []} columns={posCols} rowKey={(r) => `${r.venue}-${r.asset}`} initialSort={{ key: "value_usd", desc: true }} /></Card>
    </div>
  );
}
