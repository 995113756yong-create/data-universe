// 下载地球夜景贴图（NASA Black Marble，来自 three-globe 示例资源）。已存在则跳过；全部失败只警告不报错（前端有纯色降级）
import { copyFile, mkdir, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const target = join(root, "public", "textures", "earth-night.jpg");
const local = join(root, "node_modules", "three-globe", "example", "img", "earth-night.jpg");
const mirrors = [
  "https://unpkg.com/three-globe/example/img/earth-night.jpg",
  "https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-night.jpg",
  "https://registry.npmmirror.com/three-globe/latest/files/example/img/earth-night.jpg",
];

async function exists(p) {
  try {
    return (await stat(p)).size > 10_000;
  } catch {
    return false;
  }
}

if (await exists(target)) process.exit(0);
await mkdir(dirname(target), { recursive: true });

if (await exists(local)) {
  await copyFile(local, target);
  console.log("[textures] copied from node_modules");
  process.exit(0);
}

for (const url of mirrors) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(30_000) });
    const type = res.headers.get("content-type") ?? "";
    if (!res.ok || !type.startsWith("image")) throw new Error(`${res.status} ${type}`);
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length < 10_000) throw new Error(`too small: ${buf.length}`);
    await writeFile(target, buf);
    console.log(`[textures] downloaded ${url} (${(buf.length / 1024).toFixed(0)} KB)`);
    process.exit(0);
  } catch (e) {
    console.warn(`[textures] ${url} failed: ${e.message}`);
  }
}
console.warn("[textures] 全部镜像失败，前端将使用纯色地球。可手动把 earth-night.jpg 放到 web/public/textures/");
