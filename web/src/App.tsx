import { BenchOverlay } from "./components/BenchOverlay";
import { GlobeView } from "./components/GlobeView";
import { Hud } from "./components/Hud";
import { LayerToggles } from "./components/LayerToggles";
import { MetricsPanel } from "./components/MetricsPanel";

const bench = new URLSearchParams(location.search).has("bench");

export default function App() {
  return (
    <div className="app">
      <GlobeView bench={bench} />
      <header className="title">
        <h1>Data Universe</h1>
        <p>此刻，世界正在发生</p>
      </header>
      <LayerToggles />
      {!bench && <MetricsPanel />}
      <Hud />
      {bench && <BenchOverlay />}
    </div>
  );
}
