// FPS 压测：打开 ?bench=1，等页面写出 window.__DU_BENCH__，结果写入 benchmarks/results/
// 必须有界面运行（headless 浏览器多数走软件渲染，帧率不代表真实 GPU）。
// 用法：BASE_URL=http://localhost:8090 npm run bench   （首次需 npx playwright install chromium）
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const base = process.env.BASE_URL ?? "http://localhost:8090";
const outDir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "benchmarks", "results");

const browser = await chromium.launch({ headless: false });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on("console", (m) => m.type() === "error" && console.error("[page]", m.text()));
await page.goto(`${base}/?bench=1`);
await page.waitForFunction(() => window.__DU_BENCH__, null, { timeout: 120_000, polling: 1000 });
const result = await page.evaluate(() => window.__DU_BENCH__);
const gpu = await page.evaluate(() => {
  const gl = document.createElement("canvas").getContext("webgl");
  const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "unknown";
});
await browser.close();

const record = { ...result, gpu, base_url: base, measured_at: new Date().toISOString() };
await mkdir(outDir, { recursive: true });
const file = join(outDir, `fps-${record.measured_at.replace(/[:.]/g, "-")}.json`);
await writeFile(file, JSON.stringify(record, null, 2));
console.log(JSON.stringify(record, null, 2));
console.log(`\n${result.pass ? "PASS" : "FAIL"}  avg ${result.fps} fps, 1% low ${result.low1} fps -> ${file}`);
if (/SwiftShader|llvmpipe|Software/i.test(gpu)) console.warn("WARN 当前是软件渲染，结果无效，请在有 GPU 的环境运行");
process.exit(result.pass ? 0 : 1);
