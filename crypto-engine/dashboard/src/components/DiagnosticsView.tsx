import { fmt, usePoll, type LatencySummary, type Row } from "../api";
import { Card, ErrorNote, LatencyTable, Pill } from "./Bits";
import { Table, type Column } from "./Table";

interface Diag { connections: Row[]; queues: Row[]; invalid: Record<string, number>; events: Record<string, number>;
  order_books: Record<string, Row>; errors: string[]; decoders: Record<string, Row>; audit_sink: Row; scheduler: Row;
  connect_limiters: Record<string, Row>; recycles_requested: number }

export function DiagnosticsView() {
  const { data, error } = usePoll<Diag>("/api/diagnostics", 2000);
  const lat = usePoll<Record<string, { window: LatencySummary; lifetime: LatencySummary } | unknown>>("/api/latency", 2000);
  const latWindow: Record<string, LatencySummary> = {};
  for (const [k, v] of Object.entries(lat.data ?? {})) {
    if (v && typeof v === "object" && "window" in (v as Row)) latWindow[k] = (v as { window: LatencySummary }).window;
  }
  const connCols: Column<Row>[] = [
    { key: "venue", label: "Venue" }, { key: "shard_id", label: "Conn", align: "right" },
    { key: "state", label: "State", render: (r) => <Pill value={r.connected ? "LIVE" : r.state} /> },
    { key: "symbols", label: "Instruments", align: "right" },
    { key: "last_msg_age_ms", label: "Last frame", align: "right", render: (r) => fmt.ms(r.last_msg_age_ms) },
    { key: "msgs", label: "Messages", align: "right", render: (r) => fmt.num(r.msgs, 0) },
    { key: "reconnects", label: "Reconnects", align: "right" },
    { key: "last_reconnect_ms", label: "Last reconnect", align: "right", render: (r) => fmt.ms(r.last_reconnect_ms) },
    { key: "rotations", label: "Rotations", align: "right" }, { key: "stalls", label: "Stalls", align: "right" },
    { key: "recycles", label: "Resyncs", align: "right" },
    { key: "delivery_lag_ms", label: "Delivery lag", align: "right", render: (r) => fmt.ms(r.delivery_lag_ms) },
    { key: "last_error", label: "Last error", render: (r) => <span className="expl">{String(r.last_error || "")}</span> },
  ];
  const qCols: Column<Row>[] = [
    { key: "name", label: "Queue" }, { key: "kind", label: "Policy" },
    { key: "depth", label: "Depth", align: "right" }, { key: "max_depth", label: "Max", align: "right" },
    { key: "published", label: "Published", align: "right", render: (r) => fmt.num(r.published, 0) },
    { key: "conflated", label: "Conflated", align: "right", render: (r) => fmt.num(r.conflated, 0) },
    { key: "dropped", label: "Dropped", align: "right", render: (r) => <span className={(r.dropped as number) > 0 ? "warn-text" : ""}>{fmt.num(r.dropped, 0)}</span> },
  ];
  const bookRows: Row[] = Object.entries(data?.order_books ?? {}).map(([k, v]) => ({ key: k, ...v }));
  const bookCols: Column<Row>[] = [
    { key: "key", label: "Book", render: (r) => <span className="mono">{String(r.key)}</span> },
    { key: "sync", label: "Sync", render: (r) => <Pill value={r.sync} /> },
    { key: "levels", label: "Levels", render: (r) => (r.levels as number[]).join(" / ") },
    { key: "gaps", label: "Gaps", align: "right" }, { key: "resyncs", label: "Resyncs", align: "right" },
    { key: "crossed_resets", label: "Crossed", align: "right" }, { key: "foreign_deltas", label: "Foreign deltas", align: "right" },
  ];
  return (
    <div className="grid">
      <ErrorNote error={error} />
      <Card title="Connections"><Table rows={data?.connections ?? []} columns={connCols} rowKey={(r) => `${r.venue}-${r.shard_id}`} /></Card>
      <div className="two-col">
        <Card title="Queues and overload"><Table rows={data?.queues ?? []} columns={qCols} rowKey={(r) => String(r.name)} />
          <div className="kv">
            <span className="tag">audit sink: {String(data?.audit_sink?.kind)} · queued {String(data?.audit_sink?.queued)} · dropped {String(data?.audit_sink?.dropped)}</span>
            <span className="tag">scheduler max late: {String(data?.scheduler?.max_late_ms)} ms</span>
            <span className="tag">forced resyncs: {data?.recycles_requested ?? 0}</span>
          </div>
        </Card>
        <Card title="Invalid / dropped messages">
          <div className="kv">{Object.keys(data?.invalid ?? {}).length === 0 ? <span className="muted">none</span> :
            Object.entries(data?.invalid ?? {}).map(([k, n]) => <span key={k} className="tag warn">{k}: {n}</span>)}</div>
          <h3>Events processed</h3>
          <div className="kv">{Object.entries(data?.events ?? {}).map(([k, n]) => <span key={k} className="tag">{k}: {fmt.num(n, 0)}</span>)}</div>
          <h3>Recent errors and warnings</h3>
          <ul className="errors">{(data?.errors ?? []).slice(-15).map((e, i) => <li key={i} className="mono">{e}</li>)}</ul>
        </Card>
      </div>
      <Card title="Latency distribution (last window)"><LatencyTable rows={latWindow} /></Card>
      <Card title="Local order books"><Table rows={bookRows} columns={bookCols} rowKey={(r) => String(r.key)} /></Card>
    </div>
  );
}
