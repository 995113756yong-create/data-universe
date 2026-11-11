// 运行模式：实时（连网关 /ws）或回放（读静态回放包）。静态部署（npm run build:static）只有回放。
const params = new URLSearchParams(location.search);

export const IS_STATIC = import.meta.env.VITE_STATIC === "1";
export const IS_REPLAY = IS_STATIC || params.has("replay");
export const REPLAY_ID = params.get("replay") || null;
export const REPLAY_ROOT = `${import.meta.env.BASE_URL}replay/`;
