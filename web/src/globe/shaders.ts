// 点图层着色器。一个图层 = 一个 THREE.Points = 一次 draw call；渐隐/涟漪在 GPU 上算
export const pointVertex = /* glsl */ `
  attribute float aBirth;
  attribute float aSize;
  uniform float uTime;
  uniform float uLife;
  uniform float uPixelRatio;
  uniform float uScale;
  uniform float uMode;
  varying float vAge;
  varying float vAgeS;
  void main() {
    float ageS = uTime - aBirth;
    float age = ageS / uLife;
    vAge = age;
    vAgeS = ageS;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float alive = step(0.0, ageS) * step(age, 1.0);
    float pop = uMode < 0.5 ? 1.0 + 2.0 * exp(-ageS * 2.0) : 1.0;  // 维基：刚到时放大闪一下
    gl_PointSize = alive * aSize * pop * uPixelRatio * uScale / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`;

export const pointFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uMode;
  varying float vAge;
  varying float vAgeS;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c) * 2.0;
    if (d > 1.0) discard;
    float a;
    if (uMode < 0.5) {
      // 维基：亮闪 -> 迅速衰减成暗淡余辉 -> 生命周期末尾消失
      float glow = pow(1.0 - d, 2.2);
      float flash = mix(0.22, 1.0, exp(-vAgeS / 2.5));
      a = glow * flash * (1.0 - vAge);
    } else {
      // 地震：中心实点 + 向外扩散的涟漪环，越新越亮
      float phase = fract(vAgeS / 2.8);
      float ring = (1.0 - smoothstep(0.0, 0.1, abs(d - phase))) * (1.0 - phase);
      float core = 1.0 - smoothstep(0.0, 0.22, d);
      float fresh = mix(0.35, 1.0, exp(-vAgeS / 3600.0));
      a = (ring * 0.9 + core) * fresh;
    }
    gl_FragColor = vec4(uColor * a, a);
  }
`;

export const flightVertex = /* glsl */ `
  attribute vec3 aColor;
  attribute float aAlpha;
  uniform float uPixelRatio;
  uniform float uScale;
  uniform float uSize;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = step(0.001, aAlpha) * uSize * uPixelRatio * uScale / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`;

export const flightFragment = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0) discard;
    float a = (1.0 - smoothstep(0.35, 1.0, d)) * vAlpha;
    gl_FragColor = vec4(vColor * a, a);
  }
`;
