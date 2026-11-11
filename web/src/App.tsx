import { AlertFeed, AlertToasts } from "./components/AlertFeed";
import { AskBox } from "./components/AskBox";
import { BenchOverlay } from "./components/BenchOverlay";
import { GlobeView } from "./components/GlobeView";
import { Hud } from "./components/Hud";
import { LayerToggles } from "./components/LayerToggles";
import { MetricsPanel } from "./components/MetricsPanel";
import { ReplayBar } from "./components/ReplayBar";
import { IS_REPLAY } from "./mode";

const bench = new URLSearchParams(location.search).has("bench");

export default function App() {
  return (
    <div className={`app ${IS_REPLAY ? "replay" : "live"}`}>
      <GlobeView bench={bench} />
      <header className="title">
        <h1>
          Data Universe <span className={`mode-badge ${IS_REPLAY ? "replay" : "live"}`}>{IS_REPLAY ? "REPLAY" : "LIVE"}</span>
        </h1>
        <p>此刻，世界正在发生</p>
      </header>
      <div className="left-col">
        <LayerToggles />
        {!bench && <AlertFeed />}
      </div>
      {!bench && <MetricsPanel />}
      {!bench && <AlertToasts />}
      {!bench && <AskBox />}
      {!bench && IS_REPLAY && <ReplayBar />}
      <Hud />
      {bench && <BenchOverlay />}
    </div>
  );
}
