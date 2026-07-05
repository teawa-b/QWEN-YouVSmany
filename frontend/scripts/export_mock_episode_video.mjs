import fs from "node:fs/promises";
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { launchBrowser } from "./lib/browser.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

function arg(name, fallback = "") {
  const prefix = `--${name}=`;
  const hit = process.argv.find((x) => x.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

const config = {
  url: arg("url", process.env.YVM_FRONTEND_URL || "http://127.0.0.1:5173"),
  out: path.resolve(REPO_ROOT, arg("out", "output/happyhorse/mock-conversation.webm")),
  topic: arg("topic", "Pineapple belongs on pizza"),
  width: Number(arg("width", "540")),
  height: Number(arg("height", "960")),
  fps: Number(arg("fps", "24")),
  segmentMs: Number(arg("segment-ms", "1200")),
  limit: Number(arg("limit", "0")),
};

let playwright;
try {
  playwright = await import("playwright");
} catch (error) {
  const require = createRequire(import.meta.url);
  const candidates = [
    process.env.YVM_NODE_MODULES,
    process.env.NODE_PATH,
    process.env.NODE_REPL_NODE_MODULE_DIRS,
    process.env.USERPROFILE
      ? path.join(process.env.USERPROFILE, ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules")
      : "",
  ]
    .filter(Boolean)
    .flatMap((entry) => String(entry).split(path.delimiter))
    .filter(Boolean);

  const packageCandidates = candidates.flatMap((nodeModules) => {
    const pkgs = [path.join(nodeModules, "playwright")];
    const pnpmRoot = path.join(nodeModules, ".pnpm");
    if (existsSync(pnpmRoot)) {
      for (const dir of readdirSync(pnpmRoot, { withFileTypes: true })) {
        if (dir.isDirectory() && /^playwright@/.test(dir.name)) {
          pkgs.push(path.join(pnpmRoot, dir.name, "node_modules", "playwright"));
        }
      }
    }
    return pkgs;
  });

  for (const packagePath of packageCandidates) {
    try {
      playwright = require(packagePath);
      break;
    } catch {
      // Keep trying configured package roots.
    }
  }

  if (!playwright) {
    console.error("Playwright is required for export. Install it in the frontend env, set YVM_NODE_MODULES to a node_modules folder that contains Playwright, then rerun npm run export:mock-video.");
    console.error(error.message);
    process.exit(1);
  }
}

function dataUrlToBuffer(dataUrl) {
  const base64 = dataUrl.split(",", 2)[1];
  return Buffer.from(base64, "base64");
}

async function main() {
  const browser = await launchBrowser(playwright);
  const page = await browser.newPage({
    viewport: { width: 1280, height: 960 },
    deviceScaleFactor: 1,
  });

  await page.goto(config.url, { waitUntil: "networkidle" });
  await page.fill("#topic", config.topic);
  await page.click("#run");
  await page.waitForSelector("#hhSegments button", { timeout: 60000 });

  const dataUrl = await page.evaluate(async ({ width, height, fps, segmentMs, limit }) => {
    const sourceVideo = document.querySelector("#hhVideo");
    const buttons = [...document.querySelectorAll("#hhSegments button")];
    const selected = limit > 0 ? buttons.slice(0, limit) : buttons;
    const segments = [];

    for (const button of selected) {
      button.click();
      await new Promise((resolve) => setTimeout(resolve, 80));
      segments.push({
        src: sourceVideo.currentSrc || sourceVideo.src,
        overlay: document.querySelector("#hhOverlay")?.innerText || "",
      });
    }

    if (!segments.length) throw new Error("No HappyHorse segments found to export.");

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    const stream = canvas.captureStream(fps);
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
      ? "video/webm;codecs=vp9"
      : "video/webm";
    const chunks = [];
    const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 5_000_000 });
    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    const stopped = new Promise((resolve) => {
      recorder.onstop = resolve;
    });

    function delay(ms) {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }
    function wrapText(text, maxWidth) {
      const words = String(text).replace(/\s+/g, " ").trim().split(" ");
      const lines = [];
      let line = "";
      for (const word of words) {
        const next = line ? `${line} ${word}` : word;
        if (ctx.measureText(next).width <= maxWidth || !line) {
          line = next;
        } else {
          lines.push(line);
          line = word;
        }
      }
      if (line) lines.push(line);
      return lines.slice(0, 5);
    }
    function drawCover(video) {
      ctx.fillStyle = "#05070a";
      ctx.fillRect(0, 0, width, height);
      const vw = video.videoWidth || width;
      const vh = video.videoHeight || height;
      const scale = Math.max(width / vw, height / vh);
      const dw = vw * scale;
      const dh = vh * scale;
      ctx.drawImage(video, (width - dw) / 2, (height - dh) / 2, dw, dh);
    }
    function drawOverlay(text, index, total) {
      const pad = 24;
      const boxW = width - pad * 2;
      ctx.font = "600 24px system-ui, -apple-system, Segoe UI, sans-serif";
      const [headline = "", ...rest] = String(text).split("\n");
      ctx.font = "24px system-ui, -apple-system, Segoe UI, sans-serif";
      const body = wrapText(rest.join(" "), boxW - 28);
      const boxH = 76 + body.length * 30;
      const y = height - boxH - 30;
      ctx.fillStyle = "rgba(7, 9, 13, .78)";
      ctx.strokeStyle = "rgba(255,255,255,.16)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(pad, y, boxW, boxH, 14);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = "#ffffff";
      ctx.font = "700 24px system-ui, -apple-system, Segoe UI, sans-serif";
      ctx.fillText(headline, pad + 16, y + 34);
      ctx.fillStyle = "#c9d2e4";
      ctx.font = "22px system-ui, -apple-system, Segoe UI, sans-serif";
      body.forEach((line, i) => ctx.fillText(line, pad + 16, y + 68 + i * 30));
      ctx.fillStyle = "#7b97ff";
      ctx.font = "700 18px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.fillText(`${String(index + 1).padStart(2, "0")}/${String(total).padStart(2, "0")}`, pad + boxW - 74, y + 34);
    }
    async function loadVideo(src) {
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.src = src;
      await new Promise((resolve, reject) => {
        video.onloadeddata = resolve;
        video.onerror = () => reject(new Error(`Could not load segment video: ${src}`));
      });
      return video;
    }

    recorder.start();
    const framesPerSegment = Math.max(1, Math.round((segmentMs / 1000) * fps));
    for (let i = 0; i < segments.length; i += 1) {
      const video = await loadVideo(segments[i].src);
      await video.play().catch(() => {});
      for (let f = 0; f < framesPerSegment; f += 1) {
        if (video.ended || video.currentTime >= video.duration - 0.05) video.currentTime = 0;
        drawCover(video);
        drawOverlay(segments[i].overlay, i, segments.length);
        await delay(1000 / fps);
      }
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
    recorder.stop();
    await stopped;
    stream.getTracks().forEach((track) => track.stop());

    const blob = new Blob(chunks, { type: mimeType });
    return await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsDataURL(blob);
    });
  }, {
    width: config.width,
    height: config.height,
    fps: config.fps,
    segmentMs: config.segmentMs,
    limit: config.limit,
  });

  await fs.mkdir(path.dirname(config.out), { recursive: true });
  await fs.writeFile(config.out, dataUrlToBuffer(dataUrl));
  await browser.close();
  console.log(`saved ${config.out}`);
}

await main();
