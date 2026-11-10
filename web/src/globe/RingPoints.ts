import * as THREE from "three";
import { toXYZ } from "./coords";
import { RingIndex } from "./ring";
import { pointFragment, pointVertex } from "./shaders";

export type PointMode = "flash" | "ripple";

/** 固定容量的点图层：新点覆盖最旧的点，按出生时间在 shader 里渐隐 */
export class RingPoints {
  readonly object: THREE.Points;
  private readonly positions: Float32Array;
  private readonly births: Float32Array;
  private readonly sizes: Float32Array;
  private readonly ring: RingIndex;
  private readonly material: THREE.ShaderMaterial;
  private dirty = false;
  private tmp = [0, 0, 0];

  constructor(capacity: number, color: [number, number, number], lifeS: number, mode: PointMode) {
    this.ring = new RingIndex(capacity);
    this.positions = new Float32Array(capacity * 3);
    this.births = new Float32Array(capacity).fill(-1e9); // 未使用的槽位视为早已死亡
    this.sizes = new Float32Array(capacity);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("aBirth", new THREE.BufferAttribute(this.births, 1).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute("aSize", new THREE.BufferAttribute(this.sizes, 1).setUsage(THREE.DynamicDrawUsage));
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 120); // 固定包围球，避免每帧重算
    this.material = new THREE.ShaderMaterial({
      vertexShader: pointVertex,
      fragmentShader: pointFragment,
      uniforms: {
        uTime: { value: 0 },
        uLife: { value: lifeS },
        uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 2) },
        uScale: { value: 350 },
        uMode: { value: mode === "flash" ? 0 : 1 },
        uColor: { value: new THREE.Color(...color) },
      },
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: THREE.AdditiveBlending,
    });
    this.object = new THREE.Points(geo, this.material);
    this.object.frustumCulled = false;
  }

  setScale(scale: number) {
    this.material.uniforms.uScale.value = scale;
  }

  add(lat: number, lng: number, relAlt: number, sizePx: number, birthS: number) {
    const i = this.ring.take();
    toXYZ(lat, lng, relAlt, this.tmp);
    this.positions[i * 3] = this.tmp[0];
    this.positions[i * 3 + 1] = this.tmp[1];
    this.positions[i * 3 + 2] = this.tmp[2];
    this.births[i] = birthS;
    this.sizes[i] = sizePx;
    this.dirty = true;
  }

  /** 每帧调用。数据有变化才上传 GPU */
  tick(timeS: number) {
    this.material.uniforms.uTime.value = timeS;
    if (this.dirty) {
      const g = this.object.geometry;
      g.attributes.position.needsUpdate = true;
      g.attributes.aBirth.needsUpdate = true;
      g.attributes.aSize.needsUpdate = true;
      this.dirty = false;
    }
  }

  /** 当前仍在生命周期内的点数（HUD 显示用，O(n)，不要每帧调用） */
  alive(timeS: number): number {
    const life = this.material.uniforms.uLife.value as number;
    let n = 0;
    for (let i = 0; i < this.ring.size; i++) {
      const age = timeS - this.births[i];
      if (age >= 0 && age <= life) n++;
    }
    return n;
  }

  set visible(v: boolean) {
    this.object.visible = v;
  }
}
