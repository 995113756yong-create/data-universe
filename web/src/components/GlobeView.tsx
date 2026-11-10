import { useEffect, useRef } from "react";
import { runBench } from "../bench/synthetic";
import { UniverseEngine, engineRegistry } from "../globe/engine";
import { IS_REPLAY, REPLAY_ID, REPLAY_ROOT } from "../mode";
import { LAYERS } from "../protocol";
import { playerRegistry, ReplayPlayer } from "../replay/player";
import { store } from "../store";
import { startStream } from "../stream/client";

export function GlobeView({ bench }: { bench: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current!;
    const engine = new UniverseEngine(el);
    engineRegistry.set(engine);
    if (!engine.coordsOk) store.warn("坐标换算自检失败，点位可能错位（见浏览器控制台）");

    let stop: () => void = () => undefined;
    if (!bench && IS_REPLAY) {
      const player = new ReplayPlayer(engine, REPLAY_ROOT);
      playerRegistry.set(player);
      player.start(REPLAY_ID).catch((e: Error) => store.warn(`回放加载失败：${e.message}`));
      stop = () => {
        player.stop();
        playerRegistry.set(null);
      };
    } else if (!bench) {
      stop = startStream(engine);
    }
    // 告警脉冲只显示最近 1 小时：定期按当前（虚拟）时间刷新
    const alertTimer = window.setInterval(() => engine.setAlerts(store.get().alerts), 15000);
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
      window.clearInterval(alertTimer);
      unsub();
      stop();
      engineRegistry.set(null);
      engine.dispose();
    };
  }, [bench]);

  return <div ref={ref} className="globe" />;
}
