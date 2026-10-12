// Typed access to the engine API. Everything here is real backend state;
// nothing is fabricated client-side.
import { useEffect, useRef, useState } from "react";

export type Num = number | null;

export interface LatencySummary { count: number; p50: Num; p95: Num; p99: Num; max: Num; mean: Num; partial?: boolean }

export interface VenueHealth {
  connections_up: number; connections_total: number; instruments: number; usable: number;
  status_counts: Record<string, number>; late_connections: number[]; last_frame_age_ms: Num;
  frames: number; reconnects: number; metadata_ok: boolean; note: string;
  clock_offset?: { offset_ms: number; uncertainty_ms: number } | null;
}

export interface Health {
  status: "OK" | "DEGRADED" | "DOWN" | "STARTING"; reasons: string[]; data_source: string; execution_mode: string;
  paper_banner: string; uptime_s: number; connections_up: number; connections_total: number;
  instruments_total: number; instruments_usable: number; venues: Record<string, VenueHealth>;
  reference: string; reference_status: string; frames: number; frames_per_s: number;
}

export interface RefQuote { bid: Num; ask: Num; mid: Num; spread_bps: Num; status: string; book_age_ms: Num; exchange_time_ms: Num }

export interface Overview {
  type?: string; data_source: string; execution_mode: string; health: Health; reference: Record<string, RefQuote>;
  latency_us: Record<string, LatencySummary>; version: string;
  cross_exchange?: TrackerStats & { pairs: number }; triangular?: TrackerStats & { routes: number };
  anomalies?: { counts: Record<string, number>; active: number }; patterns?: { counts: Record<string, number> };
  paper?: { equity_usd: number; pnl_usd: number; realized_usd: number; unrealized_usd: number; fees_usd: number;
            total_exposure_usd: number; halted: boolean; counters: Record<string, number> };
}

export interface TrackerStats {
  open: number; opened_total: number; closed_kept: number; valid_transitions: number; rejected_transitions: number;
  ever_valid_closed: number; executed_closed: number; median_lifetime_ms: Num;
}

export type Row = Record<string, unknown>;

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

/** Poll a JSON endpoint; keeps the last good value and reports errors. */
export function usePoll<T>(path: string | null, ms: number): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    let ctl = new AbortController();
    const tick = async () => {
      ctl.abort();
      ctl = new AbortController();
      try {
        const d = await getJSON<T>(path, ctl.signal);
        if (alive) { setData(d); setError(null); }
      } catch (e) {
        if (alive && !(e instanceof DOMException && e.name === "AbortError")) setError(String(e));
      }
    };
    tick();
    const id = window.setInterval(tick, ms);
    return () => { alive = false; ctl.abort(); window.clearInterval(id); };
  }, [path, ms]);
  return { data, error };
}

/** Live overview pushed by the engine every summary interval (WebSocket). */
export function useOverviewStream(): { overview: Overview | null; connected: boolean; lastAt: number } {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastAt, setLastAt] = useState(0);
  const retry = useRef(0);
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    const open = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/stream`);
      ws.onopen = () => { setConnected(true); retry.current = 0; };
      ws.onmessage = (ev) => { setOverview(JSON.parse(ev.data) as Overview); setLastAt(Date.now()); };
      ws.onclose = () => {
        setConnected(false);
        if (closed) return;
        const delay = Math.min(10_000, 500 * 2 ** retry.current++) * (0.5 + Math.random() / 2);
        timer = window.setTimeout(open, delay);
      };
    };
    open();
    return () => { closed = true; window.clearTimeout(timer); ws?.close(); };
  }, []);
  return { overview, connected, lastAt };
}

export const fmt = {
  num(v: unknown, d = 2): string {
    return typeof v === "number" && Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: Math.min(d, 2) }) : "—";
  },
  px(v: unknown): string {
    if (typeof v !== "number" || !Number.isFinite(v)) return "—";
    const d = v >= 1000 ? 2 : v >= 1 ? 4 : v >= 0.01 ? 6 : 8;
    return v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: Math.min(d, 2) });
  },
  usd(v: unknown): string {
    return typeof v === "number" && Number.isFinite(v) ? v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }) : "—";
  },
  bps(v: unknown): string { return typeof v === "number" && Number.isFinite(v) ? `${v.toFixed(2)} bps` : "—"; },
  ms(v: unknown): string { return typeof v === "number" && Number.isFinite(v) ? (v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v.toFixed(0)} ms`) : "—"; },
  us(v: unknown): string { return typeof v === "number" && Number.isFinite(v) ? (v >= 1000 ? `${(v / 1000).toFixed(2)} ms` : `${v.toFixed(0)} µs`) : "—"; },
  time(ns: unknown): string { return typeof ns === "number" ? new Date(ns / 1e6).toLocaleTimeString() : "—"; },
};
