// 录 W2 演示 GIF：自转 -> 关闭航班图层 -> 重开 -> 点地震飞抵。
// 需要本机安装 ffmpeg（webm -> gif）。首次需 npx playwright install chromium。
// 用法：node web/benchmarks/record-demo.mjs
//   可选 BASE_URL（默认 http://localhost:8090）、OUT（默认 ../../docs/assets/demo.gif）
import { execFileSync } from "node:child_process";
import { mkdir, readdir, rm, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const base = process.env.BASE_URL ?? "http://localhost:8090";
const here = dirname(fileURLToPath(import.meta.url));
const tmpDir = join(here, "results", "demo-webm");
const outGif = process.env.OUT ? resolve(process.env.OUT) : join(here, "..", "..", "docs", "assets", "demo.gif");

await rm(tmpDir, { recursive: true, force: true });
await mkdir(tmpDir, { recursive: true });

const browser = await chromium.launch({ headless: false });
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: tmpDir, size: { width: 1280, height: 800 } },
});
const page = await ctx.newPage();
page.on("console", (m) => m.type() === "error" && console.error("[page]", m.text()));

await page.goto(base, { waitUntil: "load" });

// 等点铺满地球（HUD 点数 > 3000），否则录出来是空地球
await page
  .waitForFunction(
    () => {
      const t = document.querySelector(".hud")?.textContent ?? "";
      const m = t.match(/([\d,]+)\s*点/);
      return m !== null && parseInt(m[1].replace(/,/g, ""), 10) > 3000;
    },
    null,
    { timeout: 40_000, polling: 500 },
  )
  .catch(() => console.warn("WARN HUD 点数等待超时，继续录制（画面可能是空地球）"));

const readState = () =>
  page.evaluate(() => ({
    points: document.querySelector(".hud")?.textContent?.match(/([\d,]+)\s*点/)?.[1] ?? null,
    openskyOn: document.querySelector(".toggles .toggle.opensky")?.classList.contains("on") ?? null,
  }));

// 1) 自转观察
await page.waitForTimeout(5000);

// 2) 关闭航班图层（input 视觉隐藏，点 label）
const flightToggle = page.locator(".toggles .toggle.opensky");
await flightToggle.click({ timeout: 10_000 });
await page.waitForTimeout(3000);
const off = await readState();
console.log("航班已关闭:", off);
if (off.openskyOn !== false) console.warn("WARN 航班图层未关闭，检查选择器");

// 3) 重开航班图层
await flightToggle.click({ timeout: 10_000 });
await page.waitForTimeout(3000);
const on = await readState();
console.log("航班已重开:", on);
if (on.openskyOn !== true) console.warn("WARN 航班图层未重开，检查选择器");

// 4) 点第一条地震飞过去（用 DOM 派发，避开面板遮挡）
const clicked = await page.evaluate(() => {
  const span = document.querySelector(".qtitle");
  const li = span?.closest("li");
  if (!li) return false;
  li.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
  return true;
});
console.log("已点击地震:", clicked);
await page.waitForTimeout(9000);

// 必须先关闭上下文，Playwright 才会把 webm 落盘
await ctx.close();
await browser.close();

const files = (await readdir(tmpDir)).filter((f) => f.endsWith(".webm"));
if (!files.length) throw new Error(`没有录到 webm：${tmpDir}`);
const webm = join(tmpDir, files[0]);

// webm -> GIF：10fps / 800px / 96 色，控制在 10MB 内
const ff = process.env.FFMPEG ?? "ffmpeg";
const palette = join(tmpDir, "palette.png");
try {
  execFileSync(ff, ["-y", "-i", webm, "-vf", "fps=10,scale=800:-1:flags=lanczos,palettegen=max_colors=96:stats_mode=diff", palette], {
    stdio: "inherit",
  });
  await mkdir(dirname(outGif), { recursive: true });
  execFileSync(
    ff,
    [
      "-y",
      "-i", webm,
      "-i", palette,
      "-lavfi",
      "fps=10,scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
      outGif,
    ],
    { stdio: "inherit" },
  );
} catch (err) {
  console.error(`\nffmpeg 失败（是否已安装并加入 PATH？）：${err.message}`);
  console.error(`webm 保留在：${webm}`);
  process.exit(1);
}

const { size } = await stat(outGif);
const mb = size / 1024 / 1024;
console.log(`\n${outGif}  ${mb.toFixed(2)} MB`);
if (mb > 10) console.warn("WARN 超过 10MB，调低 fps/scale 后重录");
await rm(tmpDir, { recursive: true, force: true });