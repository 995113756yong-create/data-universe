import Globe from "globe.gl";
import * as THREE from "three";
import { activeAlerts, alertText, SEVERITY_COLOR } from "../alerts";
import { clock } from "../clock";
import type { AlertItem, Highlight, Layer } from "../protocol";
import type { FlightPacket, PointPacket, QuakeItem } from "../stream/decode";
import { FpsMeter } from "../hud/fps";
import { toXYZ, jitter } from "./coords";
import { FlightLayer } from "./FlightLayer";
import { RingPoints } from "./RingPoints";
import { createStars } from "./stars";
import { DEFAULT_JITTER_DEG, REGION_JITTER_DEG, STYLE } from "./style";

type GlobeInstance = InstanceType<typeof Globe>;
interface OrbitLike { autoRotate: boolean; autoRotateSpeed: number; addEventListener?: (t: string, f: () => void) => void }

// BASE_URL：静态部署到子路径（GitHub Pages）时也能找到贴图
const TEXTURE_URL = `${import.meta.env.BASE_URL}textures/earth-night.jpg`;

interface RingMarker { lat: number; lng: number; color: string; maxR: number; period: number }
interface LabelMarker { lat: number; lng: number; text: string; kind: "answer" | "alert" }

function hexRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function labelElement(d: LabelMarker): HTMLElement {
  const el = document.createElement("div");
  el.className = `globe-label ${d.kind}`;
  el.textContent = d.text;
  return el;
}

/** 命令式渲染引擎（不经过 React，避免高频数据触发重渲染） */
export class UniverseEngine {
  readonly globe: GlobeInstance;
  readonly wiki: RingPoints;
  readonly quakes: RingPoints;
  readonly flights: FlightLayer;
  readonly meter = new FpsMeter();
  coordsOk = true;
  private baseMs = clock.now(); // 着色器时间 = (clock.now() - baseMs) 秒；回放时切到虚拟时间
  private alertRings: RingMarker[] = [];
  private answerRings: RingMarker[] = [];
  private alertLabels: LabelMarker[] = [];
  private answerLabels: LabelMarker[] = [];
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
    // 告警与 AI 高亮：数量少（几十个以内），直接用 globe.gl 内置的 rings / html 图层
    this.globe
      .ringsData([])
      .ringLat((d: object) => (d as RingMarker).lat)
      .ringLng((d: object) => (d as RingMarker).lng)
      .ringAltitude(0.004)
      .ringColor((d: object) => {
        const [r, g, b] = hexRgb((d as RingMarker).color);
        return (t: number) => `rgba(${r},${g},${b},${(1 - t).toFixed(3)})`;
      })
      .ringMaxRadius((d: object) => (d as RingMarker).maxR)
      .ringPropagationSpeed(3)
      .ringRepeatPeriod((d: object) => (d as RingMarker).period)
      .htmlElementsData([])
      .htmlLat((d: object) => (d as LabelMarker).lat)
      .htmlLng((d: object) => (d as LabelMarker).lng)
      .htmlAltitude(0.01)
      .htmlElement((d: object) => labelElement(d as LabelMarker));
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
    return (clock.now() - this.baseMs) / 1000;
  }

  /** 回放开始时把时间基准设到回放区间附近，保证着色器里的 float32 时间精度 */
  setTimeBase(ms: number) {
    this.baseMs = ms;
    this.reset();
  }

  /** 清空所有图层（回放拖动进度时调用） */
  reset() {
    this.wiki.clear();
    this.quakes.clear();
    this.flights.clear();
    this.seenQuakes.clear();
    this.setAlerts([]);
    this.setHighlights([]);
  }

  private loop = (now: number) => {
    this.meter.frame(now);
    const t = this.timeS;
    this.wiki.tick(t);
    this.quakes.tick(t);
    if (now - this.lastFlightUpdate > 250) {
      this.flights.update(clock.now());
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
    const now = clock.now();
    for (const q of items) {
      if (this.seenQuakes.has(q.id)) continue;
      this.seenQuakes.add(q.id);
      const size = 8 + Math.max(0, q.mag) * 6;
      this.quakes.add(q.lat, q.lng, STYLE.usgs.altitude, size, t - Math.max(0, (now - q.eventMs) / 1000));
    }
  }

  upsertFlights(pk: FlightPacket) {
    this.flights.upsert(pk, clock.now());
  }

  setVisible(layer: Layer, v: boolean) {
    if (layer === "wiki") this.wiki.visible = v;
    else if (layer === "usgs") this.quakes.visible = v;
    else this.flights.visible = v;
  }

  /** 最近 1 小时、有坐标的告警在地球上画脉冲环，严重程度决定颜色和大小 */
  setAlerts(items: AlertItem[]) {
    const active = activeAlerts(items, clock.now());
    this.alertRings = active.map((a) => ({
      lat: a.lat!,
      lng: a.lng!,
      color: SEVERITY_COLOR[a.severity],
      maxR: a.severity === "critical" ? 9 : a.severity === "high" ? 7 : 5,
      period: 1400,
    }));
    this.alertLabels = active
      .filter((a) => a.severity !== "medium")
      .slice(0, 8)
      .map((a) => ({ lat: a.lat!, lng: a.lng!, text: alertText(a), kind: "alert" as const }));
    this.applyMarkers();
  }

  /** AI 回答里的位置：青色脉冲 + 文字标签 */
  setHighlights(items: Highlight[]) {
    this.answerRings = items.map((h) => ({ lat: h.lat, lng: h.lng, color: "#7df9ff", maxR: 5, period: 900 }));
    this.answerLabels = items.map((h) => ({ lat: h.lat, lng: h.lng, text: h.label, kind: "answer" as const }));
    this.applyMarkers();
    if (items.length) {
      const lat = items.reduce((s, h) => s + h.lat, 0) / items.length;
      const lng = items.reduce((s, h) => s + h.lng, 0) / items.length;
      const spread = Math.max(...items.map((h) => Math.abs(h.lat - lat) + Math.abs(h.lng - lng)), 0);
      this.flyTo(lat, lng, Math.min(2.8, 1.2 + spread / 60));
    }
  }

  private applyMarkers() {
    this.globe.ringsData([...this.alertRings, ...this.answerRings]);
    this.globe.htmlElementsData([...this.alertLabels, ...this.answerLabels]);
  }

  flyTo(lat: number, lng: number, altitude = 1.4) {
    this.controls.autoRotate = false;
    this.globe.pointOfView({ lat, lng, altitude }, 1500);
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
