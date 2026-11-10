import * as THREE from "three";

/** 程序生成的星空（不依赖图片资源） */
export function createStars(count = 4000, seed = 42): THREE.Points {
  let s = seed;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  const pos = new Float32Array(count * 3);
  const size = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const u = rnd() * 2 - 1;
    const t = rnd() * Math.PI * 2;
    const r = 1800 + rnd() * 1500;
    const q = Math.sqrt(1 - u * u);
    pos[i * 3] = r * q * Math.cos(t);
    pos[i * 3 + 1] = r * u;
    pos[i * 3 + 2] = r * q * Math.sin(t);
    size[i] = rnd() < 0.97 ? 1 + rnd() * 1.5 : 2.5 + rnd() * 2;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
  const m = new THREE.ShaderMaterial({
    vertexShader: `attribute float aSize; void main(){ gl_PointSize = aSize; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: `void main(){ float d = length(gl_PointCoord-0.5)*2.0; if(d>1.0) discard; gl_FragColor = vec4(vec3(0.8,0.85,1.0)*(1.0-d), 1.0-d); }`,
    transparent: true,
    depthWrite: false,
  });
  const p = new THREE.Points(g, m);
  p.frustumCulled = false;
  return p;
}
