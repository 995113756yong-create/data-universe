import { useEffect, useRef } from "react";
import { runBench } from "../bench/synthetic";
import { UniverseEngine, engineRegistry } from "../globe/engine";
import { LAYERS } from "../protocol";
import { store } from "../store";
import { startStream } from "../stream/client";

export function GlobeView({ bench }: { bench: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current!;
    const engine = new UniverseEngine(el);
    engineRegistry.set(engine);
    if (!engine.coordsOk) store.warn("坐标换算自检失败，点位可能错位（见浏览器控制台）");

    const stop = bench ? () => undefined : startStream(engine);
    if (bench) void runBench(engine);

    // 图层开关
    let lastLayers = store.get().layers;
    const unsub = store.subscribe(() => {
      const layers = store.get().layers;
      if (layers !== lastLayers) {
        lastLayers = layers;
        LAYERS.forEach((l) => engine.setVisible(l, layers[l]));
      }
    });

    // HUD 数据 2Hz 刷新（统计存活点数是 O(n)，不放在每帧里）
    const hud = window.setInterval(() => store.set({ fps: engine.meter.current, counts: engine.counts() }), 500);

    return () => {
      window.clearInterval(hud);
      unsub();
      stop();
      engineRegistry.set(null);
      engine.dispose();
    };
  }, [bench]);

  return <div ref={ref} className="globe" />;
}
