import Globe from "globe.gl";
import * as THREE from "three";
import type { Layer } from "../protocol";
import type { FlightPacket, PointPacket, QuakeItem } from "../stream/decode";
import { FpsMeter } from "../hud/fps";
import { toXYZ, jitter } from "./coords";
import { FlightLayer } from "./FlightLayer";
import { RingPoints } from "./RingPoints";
import { createStars } from "./stars";
import { DEFAULT_JITTER_DEG, REGION_JITTER_DEG, STYLE } from "./style";

type GlobeInstance = InstanceType<typeof Globe>;
interface OrbitLike { autoRotate: boolean; autoRotateSpeed: number; addEventListener?: (t: string, f: () => void) => void }

const TEXTURE_URL = "/textures/earth-night.jpg";

/** 命令式渲染引擎（不经过 React，避免高频数据触发重渲染） */
export class UniverseEngine {
  readonly globe: GlobeInstance;
  readonly wiki: RingPoints;
  readonly quakes: RingPoints;
  readonly flights: FlightLayer;
  readonly meter = new FpsMeter();
  coordsOk = true;
  private readonly t0 = performance.now();
  private raf = 0;
  private lastFlightUpdate = 0;
  private readonly seenQuakes = new Set<string>();
  private resumeRotateTimer = 0;
  private readonly onResize = () => this.resize();

  constructor(private readonly el: HTMLElement) {
    this.globe = new Globe(el, {
      animateIn: false,
      rendererConfig: { antialias: true, powerPreference: "high-performance" },
    });
    this.globe
      .backgroundColor(STYLE.background)
      .showAtmosphere(true)
      .atmosphereColor(STYLE.atmosphere)
      .atmosphereAltitude(STYLE.atmosphereAltitude)
      .width(el.clientWidth)
      .height(el.clientHeight);
    this.globe.pointOfView({ lat: 25, lng: 105, altitude: 2.5 }, 0);
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = STYLE.autoRotateSpeed;

    this.wiki = new RingPoints(STYLE.wiki.capacity, STYLE.wiki.color, STYLE.wiki.lifeS, "flash");
    this.quakes = new RingPoints(STYLE.usgs.capacity, STYLE.usgs.color, STYLE.usgs.lifeS, "ripple");
    this.flights = new FlightLayer();
    const scene = this.globe.scene();
    scene.add(createStars(), this.flights.object, this.wiki.object, this.quakes.object);

    // 调试入口：控制台可查看 __DU_ENGINE__.wiki.object.visible 等
    (window as unknown as { __DU_ENGINE__: UniverseEngine }).__DU_ENGINE__ = this;
    this.checkCoords();
    void this.loadTexture();
    window.addEventListener("resize", this.onResize);
    this.loop(performance.now());
  }

  private get controls(): OrbitLike {
    return this.globe.controls() as unknown as OrbitLike;
  }

  /** 自检：我们的经纬度换算必须与 globe.gl 完全一致，否则点会画错位置 */
  private checkCoords() {
    const g = this.globe.getCoords(30, 60, 0.01) as { x: number; y: number; z: number };
    const m = toXYZ(30, 60, 0.01);
    const err = Math.hypot(g.x - m[0], g.y - m[1], g.z - m[2]);
    if (!(err < 0.01)) {
      this.coordsOk = false;
      console.error("[DU] 坐标换算与 globe.getCoords 不一致", { globe: g, ours: m, err });
    }
  }

  private async loadTexture() {
    try {
      const r = await fetch(TEXTURE_URL, { method: "HEAD" });
      if (r.ok && (r.headers.get("content-type") ?? "").startsWith("image")) {
        this.globe.globeImageUrl(TEXTURE_URL);
        return;
      }
    } catch {
      /* 走降级 */
    }
    const mat = this.globe.globeMaterial() as THREE.MeshPhongMaterial;
    mat.color = new THREE.Color(STYLE.fallbackGlobeColor);
    console.warn("[DU] 未找到地球贴图，使用纯色降级。执行 npm run textures 下载");
  }

  get timeS() {
    return (performance.now() - this.t0) / 1000;
  }

  private loop = (now: number) => {
    this.meter.frame(now);
    const t = (now - this.t0) / 1000;
    this.wiki.tick(t);
    this.quakes.tick(t);
    if (now - this.lastFlightUpdate > 250) {
      this.flights.update(Date.now());
      this.lastFlightUpdate = now;
    }
    this.raf = requestAnimationFrame(this.loop);
  };

  addWiki(pk: PointPacket) {
    const t = this.timeS;
    for (let i = 0; i < pk.n; i++) {
      const r = REGION_JITTER_DEG[pk.region[i]] ?? DEFAULT_JITTER_DEG;
      const [la, lo] = jitter(pk.lat[i], pk.lng[i], pk.seed[i], r);
      const size = 2.5 + Math.min(5, Math.log10(1 + pk.weight[i]) * 1.6);
      this.wiki.add(la, lo, STYLE.wiki.altitude, size, t - pk.ageS[i]);
    }
  }

  addQuakes(items: QuakeItem[]) {
    const t = this.timeS;
    const now = Date.now();
    for (const q of items) {
      if (this.seenQuakes.has(q.id)) continue;
      this.seenQuakes.add(q.id);
      const size = 8 + Math.max(0, q.mag) * 6;
      this.quakes.add(q.lat, q.lng, STYLE.usgs.altitude, size, t - Math.max(0, (now - q.eventMs) / 1000));
    }
  }

  upsertFlights(pk: FlightPacket) {
    this.flights.upsert(pk, Date.now());
  }

  setVisible(layer: Layer, v: boolean) {
    if (layer === "wiki") this.wiki.visible = v;
    else if (layer === "usgs") this.quakes.visible = v;
    else this.flights.visible = v;
  }

  flyTo(lat: number, lng: number) {
    this.controls.autoRotate = false;
    this.globe.pointOfView({ lat, lng, altitude: 1.4 }, 1500);
    window.clearTimeout(this.resumeRotateTimer);
    this.resumeRotateTimer = window.setTimeout(() => (this.controls.autoRotate = true), 15000);
  }

  counts() {
    const t = this.timeS;
    return { wiki: this.wiki.alive(t), usgs: this.quakes.alive(t), opensky: this.flights.count };
  }

  resize() {
    this.globe.width(this.el.clientWidth).height(this.el.clientHeight);
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    window.removeEventListener("resize", this.onResize);
    window.clearTimeout(this.resumeRotateTimer);
    this.globe.pauseAnimation();
    this.globe.renderer().dispose();
    this.el.innerHTML = "";
  }
}

// 面板（地震列表点击飞过去）需要访问引擎
let current: UniverseEngine | null = null;
export const engineRegistry = {
  get: () => current,
  set: (e: UniverseEngine | null) => (current = e),
};
