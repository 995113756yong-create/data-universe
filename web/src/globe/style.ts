// 视觉常量集中在这里。AGENTS.md 允许调整本文件的颜色/尺寸，不允许改其他渲染逻辑来"调效果"
export const STYLE = {
  background: "#02030a",
  atmosphere: "#3a8cff",
  atmosphereAltitude: 0.18,
  fallbackGlobeColor: "#0b1a33",
  wiki: { color: [0.25, 0.95, 1.0] as [number, number, number], lifeS: 600, capacity: 20000, altitude: 0.006 },
  usgs: { color: [1.0, 0.25, 0.2] as [number, number, number], lifeS: 24 * 3600, capacity: 2000, altitude: 0.008 },
  flight: {
    low: [1.0, 0.55, 0.15] as [number, number, number], // < 3000 m
    high: [1.0, 0.95, 0.55] as [number, number, number], // > 11000 m
    capacity: 20000,
    baseAltitude: 0.012,
    sizePx: 2.6,
  },
  pointScale: 350, // 默认视角下相机到屏幕中心点的距离，用于把世界尺寸换算成像素
  autoRotateSpeed: 0.35,
};

// 维基坐标是"语言 -> 国家质心"的近似值，前端按国家大小做稳定抖动，避免几千个点叠在同一像素
export const REGION_JITTER_DEG: Record<string, number> = {
  "United States": 9, Russia: 12, China: 8, Brazil: 8, Indonesia: 6, Japan: 3, Germany: 2.5,
  France: 3, Spain: 3, Italy: 2.5, Ukraine: 3, Poland: 2, Iran: 4, Turkey: 3, Vietnam: 2.5,
  Thailand: 2.5, Sweden: 3, Finland: 2.5, "South Korea": 1.2, Netherlands: 0.8, Czechia: 1,
  Hungary: 1, Israel: 0.6,
};
export const DEFAULT_JITTER_DEG = 2.5;
