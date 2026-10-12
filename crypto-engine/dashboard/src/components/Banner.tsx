import type { Overview } from "../api";
import { Pill } from "./Bits";

/** Always-visible execution-mode and data-source banner. */
export function Banner({ overview, connected }: { overview: Overview | null; connected: boolean }) {
  const ds = overview?.data_source ?? "…";
  const status = overview?.health.status ?? "STARTING";
  return (
    <div className="banner" role="status">
      <strong className="paper-flag">PAPER TRADING ONLY</strong>
      <span className="banner-text">Simulated orders and fills. No real orders can be placed.</span>
      <span className="spacer" />
      <span className={`source source-${ds.toLowerCase()}`} title="Where market data comes from">
        DATA: {ds === "LIVE" ? "LIVE PUBLIC MARKET DATA" : ds}
      </span>
      <Pill value={status} />
      <span className={`dot ${connected ? "on" : "off"}`} title={connected ? "live stream connected" : "stream disconnected"} />
    </div>
  );
}
