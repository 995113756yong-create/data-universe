import { LAYERS, type Layer } from "../protocol";
import { store, useStore } from "../store";

const LABEL: Record<Layer, string> = { wiki: "维基编辑", usgs: "地震", opensky: "航班" };

export function LayerToggles() {
  const layers = useStore((s) => s.layers);
  const counts = useStore((s) => s.counts);
  return (
    <div className="toggles">
      {LAYERS.map((l) => (
        <label key={l} className={`toggle ${l} ${layers[l] ? "on" : ""}`}>
          <input
            type="checkbox"
            checked={layers[l]}
            onChange={(e) => store.set({ layers: { ...layers, [l]: e.target.checked } })}
          />
          <span className="swatch" />
          {LABEL[l]}
          <span className="muted">{counts[l].toLocaleString()}</span>
        </label>
      ))}
    </div>
  );
}
