import * as THREE from "three";
import type { FlightPacket } from "../stream/decode";
import { toXYZ } from "./coords";
import { lerpLng, project } from "./deadReckoning";
import { flightFragment, flightVertex } from "./shaders";
import { STYLE } from "./style";

const MAX_EXTRAPOLATE_S = 180; // 超过 3 分钟没有新位置就不再外推，停在原地并逐渐变暗
const BLEND_MS = 2000; // 新位置到达时，用 2 秒从当前显示位置平滑过渡，避免跳点

/** 航班图层：按 icao24 原地更新（不是追加），位置用航位推算在两次轮询之间平滑移动 */
export class FlightLayer {
  readonly object: THREE.Points;
  private readonly cap: number;
  private readonly index = new Map<string, number>();
  private readonly free: number[] = [];
  private used = 0;
  // 最后一次上报
  private readonly lat: Float32Array;
  private readonly lng: Float32Array;
  private readonly hdg: Float32Array;
  private readonly vel: Float32Array;
  private readonly eventMs: Float64Array;
  // 当前显示位置与过渡起点
  private readonly dispLat: Float32Array;
  private readonly dispLng: Float32Array;
  private readonly fromLat: Float32Array;
  private readonly fromLng: Float32Array;
  private readonly blendStart: Float64Array;
  private readonly relAlt: Float32Array;
  private readonly positions: Float32Array;
  private readonly colors: Float32Array;
  private readonly alphas: Float32Array;
  private readonly material: THREE.ShaderMaterial;
  private tmp = [0, 0, 0];

  constructor(capacity = STYLE.flight.capacity, private readonly windowMs = 20 * 60 * 1000) {
    this.cap = capacity;
    const f32 = () => new Float32Array(capacity);
    this.lat = f32(); this.lng = f32(); this.hdg = f32(); this.vel = f32();
    this.eventMs = new Float64Array(capacity);
    this.dispLat = f32(); this.dispLng = f32(); this.fromLat = f32(); this.fromLng = f32();
    this.blendStart = new Float64Array(capacity);
    this.relAlt = f32();
    this.positions = new Float32Array(capacity * 3);
    this.colors = new Float32Array(capacity * 3);
    this.alphas = f32();
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("aColor", new THREE.BufferAttribute(this.colors, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("aAlpha", new THREE.BufferAttribute(this.alphas, 1).setUsage(THREE.DynamicDrawUsage));
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 120);
    this.material = new THREE.ShaderMaterial({
      vertexShader: flightVertex,
      fragmentShader: flightFragment,
      uniforms: {
        uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 2) },
        uScale: { value: STYLE.pointScale },
        uSize: { value: STYLE.flight.sizePx },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.object = new THREE.Points(geo, this.material);
    this.object.frustumCulled = false;
  }

  get count() {
    return this.index.size;
  }

  /** 清空所有飞机（回放拖动进度时用） */
  clear() {
    this.index.clear();
    this.free.length = 0;
    this.used = 0;
    this.alphas.fill(0);
    this.object.geometry.attributes.aAlpha.needsUpdate = true;
  }

  setScale(scale: number) {
    this.material.uniforms.uScale.value = scale;
  }

  upsert(pk: FlightPacket, nowMs: number) {
    for (let k = 0; k < pk.n; k++) {
      const id = pk.ids[k];
      let i = this.index.get(id);
      const isNew = i === undefined;
      if (i === undefined) {
        i = this.free.pop() ?? (this.used < this.cap ? this.used++ : -1);
        if (i < 0) continue; // 容量满：丢弃新飞机（容量按全球峰值 2 倍设置，正常不会触发）
        this.index.set(id, i);
      } else if (pk.eventMs[k] <= this.eventMs[i]) {
        continue; // 旧位置（乱序/重复）忽略
      }
      if (isNew) {
        this.dispLat[i] = pk.lat[k];
        this.dispLng[i] = pk.lng[k];
      }
      this.fromLat[i] = this.dispLat[i];
      this.fromLng[i] = this.dispLng[i];
      this.blendStart[i] = isNew ? 0 : nowMs;
      this.lat[i] = pk.lat[k];
      this.lng[i] = pk.lng[k];
      this.hdg[i] = pk.heading[k];
      this.vel[i] = pk.velocity[k];
      this.eventMs[i] = pk.eventMs[k];
      const altM = Number.isFinite(pk.altitude[k]) ? pk.altitude[k] : 0;
      const t = Math.min(1, Math.max(0, (altM - 3000) / 8000));
      this.relAlt[i] = STYLE.flight.baseAltitude + (altM / 12000) * 0.01;
      const lo = STYLE.flight.low;
      const hi = STYLE.flight.high;
      this.colors[i * 3] = lo[0] + (hi[0] - lo[0]) * t;
      this.colors[i * 3 + 1] = lo[1] + (hi[1] - lo[1]) * t;
      this.colors[i * 3 + 2] = lo[2] + (hi[2] - lo[2]) * t;
    }
    this.object.geometry.attributes.aColor.needsUpdate = true;
  }

  /** 每 ~250ms 调用一次：外推位置、淘汰离场飞机、上传 GPU */
  update(nowMs: number) {
    const remove: string[] = [];
    for (const [id, i] of this.index) {
      const ageMs = nowMs - this.eventMs[i];
      if (ageMs > this.windowMs) {
        remove.push(id);
        continue;
      }
      const dt = Math.min(Math.max(ageMs / 1000, 0), MAX_EXTRAPOLATE_S);
      const [tLat, tLng] = project(this.lat[i], this.lng[i], this.hdg[i], this.vel[i], dt);
      const k = this.blendStart[i] === 0 ? 1 : Math.min(1, (nowMs - this.blendStart[i]) / BLEND_MS);
      this.dispLat[i] = this.fromLat[i] + (tLat - this.fromLat[i]) * k;
      this.dispLng[i] = lerpLng(this.fromLng[i], tLng, k);
      toXYZ(this.dispLat[i], this.dispLng[i], this.relAlt[i], this.tmp);
      this.positions[i * 3] = this.tmp[0];
      this.positions[i * 3 + 1] = this.tmp[1];
      this.positions[i * 3 + 2] = this.tmp[2];
      this.alphas[i] = ageMs / 1000 > MAX_EXTRAPOLATE_S ? 0.35 : 0.95;
    }
    for (const id of remove) {
      const i = this.index.get(id)!;
      this.index.delete(id);
      this.alphas[i] = 0;
      this.free.push(i);
    }
    const g = this.object.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.aAlpha.needsUpdate = true;
  }

  set visible(v: boolean) {
    this.object.visible = v;
  }
}
