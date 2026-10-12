import { useEffect, useState } from "react";
import { useOverviewStream } from "./api";
import { Banner } from "./components/Banner";
import { DiagnosticsView } from "./components/DiagnosticsView";
import { MarketsView } from "./components/MarketsView";
import { CrossExchangeView, TriangularView } from "./components/OpportunitiesView";
import { OverviewView } from "./components/OverviewView";
import { PaperView } from "./components/PaperView";
import { SignalsView } from "./components/SignalsView";

const TABS = [
  ["overview", "Overview"], ["markets", "Market scanner"], ["cross", "Cross-exchange"], ["triangular", "Triangular"],
  ["signals", "Patterns & anomalies"], ["paper", "Paper trading"], ["diagnostics", "Diagnostics"],
] as const;
type Tab = (typeof TABS)[number][0];

function tabFromHash(): Tab {
  const h = location.hash.replace("#", "");
  return (TABS.find(([k]) => k === h)?.[0] ?? "overview") as Tab;
}

export default function App() {
  const { overview, connected, lastAt } = useOverviewStream();
  const [tab, setTab] = useState<Tab>(tabFromHash());
  useEffect(() => {
    const on = () => setTab(tabFromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const stale = lastAt > 0 && Date.now() - lastAt > 5000;
  return (
    <div className="app">
      <Banner overview={overview} connected={connected && !stale} />
      <header className="topbar">
        <h1>Market Intelligence Engine</h1>
        <nav>
          {TABS.map(([k, label]) => (
            <a key={k} href={`#${k}`} className={tab === k ? "active" : undefined}>{label}</a>
          ))}
        </nav>
      </header>
      <main>
        {tab === "overview" && <OverviewView o={overview} />}
        {tab === "markets" && <MarketsView />}
        {tab === "cross" && <CrossExchangeView />}
        {tab === "triangular" && <TriangularView />}
        {tab === "signals" && <SignalsView />}
        {tab === "paper" && <PaperView />}
        {tab === "diagnostics" && <DiagnosticsView />}
      </main>
      <footer>v{overview?.version ?? "?"} · data source: {overview?.data_source ?? "?"} · execution: PAPER (simulated only)</footer>
    </div>
  );
}
