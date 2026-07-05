import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchBrowser } from "./lib/browser.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");

function arg(name, fallback) {
  const prefix = `--${name}=`;
  const hit = process.argv.find((x) => x.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

const config = {
  url: arg("url", process.env.YVM_FRONTEND_URL || "http://127.0.0.1:5173"),
  outDir: path.resolve(REPO_ROOT, arg("out", "frontend/assets/reference/vertical-v1")),
  width: Number(arg("width", "540")),
  height: Number(arg("height", "960")),
  durationMs: Number(arg("duration-ms", "1800")),
  fps: Number(arg("fps", "24")),
  limit: Number(arg("limit", "0")),
};

let playwright;
try {
  playwright = await import("playwright");
} catch (error) {
  console.error("Playwright is required for capture. Install it in the frontend env, then rerun npm run capture:refs.");
  console.error(error.message);
  process.exit(1);
}

const cast = [
  { character_id: "protagonist", display_name: "Main Speaker", role: "protagonist", stance: "for", visual_presentation: "male" },
  { character_id: "challenger_1", display_name: "Second Speaker", role: "challenger", stance: "against", visual_presentation: "female" },
  { character_id: "challenger_2", display_name: "Third Speaker", role: "challenger", stance: "against", visual_presentation: "male" },
  { character_id: "challenger_3", display_name: "Fourth Speaker", role: "challenger", stance: "against", visual_presentation: "female" },
];

const speakerSlots = [
  { slot: "main_speaker", speakerId: "protagonist" },
  { slot: "second_speaker", speakerId: "challenger_1" },
  { slot: "third_speaker", speakerId: "challenger_2" },
  { slot: "fourth_speaker", speakerId: "challenger_3" },
];

const shotPlan = [
  { group: "intro", id: "intro_wide", speakerId: "protagonist", shot: "intro_wide", speaking: false },
  { group: "intro", id: "intro_table", speakerId: "protagonist", shot: "intro_table", speaking: false },
  { group: "intro", id: "intro_panel", speakerId: "challenger_2", shot: "intro_panel", speaking: false },
  ...speakerSlots.flatMap(({ slot, speakerId }) => [
    { group: slot, id: "close", speakerId, shot: "speaker_close", speaking: true },
    { group: slot, id: "medium", speakerId, shot: "speaker_medium", speaking: true },
    { group: slot, id: "profile", speakerId, shot: "speaker_profile", speaking: true },
    { group: slot, id: "over_table", speakerId, shot: "speaker_over_table", speaking: true },
  ]),
];

const selectedShots = config.limit > 0 ? shotPlan.slice(0, config.limit) : shotPlan;

function dataUrlToBuffer(dataUrl) {
  const base64 = dataUrl.split(",", 2)[1];
  return Buffer.from(base64, "base64");
}

async function writeDataUrl(file, dataUrl) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, dataUrlToBuffer(dataUrl));
}

async function main() {
  await fs.mkdir(config.outDir, { recursive: true });

  const browser = await launchBrowser(playwright);
  const page = await browser.newPage({
    viewport: { width: config.width + 80, height: config.height + 80 },
    deviceScaleFactor: 1,
  });

  await page.goto(config.url, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.YVM3D?.show, null, { timeout: 15000 });
  await page.evaluate(({ width, height }) => {
    document.body.innerHTML = `<div id="stage3d"></div>`;
    document.body.style.margin = "0";
    document.body.style.background = "#000";
    document.getElementById("stage3d").style.width = `${width}px`;
  }, { width: config.width, height: config.height });

  await page.evaluate(({ cast, width, height }) => {
    window.YVM3D.show({
      scene: {
        scene_template: { template_id: "studio_midnight" },
        total_duration_s: 1,
        audio: [],
        segments: [{ start_s: 0, end_s: 1, speaker_id: "protagonist", dialogue: "", camera: { shot: "wide_master" } }],
      },
      cast,
      colorFor(id) {
        return ({ protagonist: 0xf0997b, challenger_1: 0x5dcaa5, challenger_2: 0xd4537e, challenger_3: 0xefbf4f })[id] || 0xffffff;
      },
      nameFor(id) {
        return (cast.find((c) => c.character_id === id)?.display_name) || id;
      },
      apiBase: "",
    }, {
      aspectRatio: 9 / 16,
      captureSize: { width, height },
      hideControls: true,
      hideOverlays: true,
      manualRender: true,
      pixelRatio: 1,
      showCropGuide: false,
    });
  }, { cast, width: config.width, height: config.height });

  await page.waitForFunction(() => window.__YVM3D_DEBUG?.ready, null, { timeout: 30000 });

  const manifest = {
    version: 1,
    format: "9:16",
    size: { width: config.width, height: config.height },
    fps: config.fps,
    duration_ms: config.durationMs,
    purpose: "starter images and silent speaker-angle clips for image/video guided generation",
    generated_at: new Date().toISOString(),
    shots: [],
  };

  for (const item of selectedShots) {
    const relDir = path.join(item.group, item.speakerId || "room", item.id);
    const pngRel = path.join(relDir, "starter.png").replaceAll("\\", "/");
    const webmRel = path.join(relDir, "clip.webm").replaceAll("\\", "/");
    const result = await page.evaluate(async ({ item, durationMs, fps }) => {
      const player = window.__YVM3D_DEBUG;
      player.setReferenceShot(item);
      for (let i = 0; i < 12; i += 1) player.renderReferenceFrame(1 / fps);
      const starter = player.renderer.domElement.toDataURL("image/png");

      const stream = player.renderer.domElement.captureStream(fps);
      const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
        ? "video/webm;codecs=vp9"
        : "video/webm";
      const chunks = [];
      const recorder = new MediaRecorder(stream, { mimeType });
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      const stopped = new Promise((resolve) => {
        recorder.onstop = resolve;
      });
      recorder.start();
      const frames = Math.ceil((durationMs / 1000) * fps);
      for (let i = 0; i < frames; i += 1) {
        player.renderReferenceFrame(1 / fps);
        await new Promise((resolve) => setTimeout(resolve, 1000 / fps));
      }
      recorder.stop();
      await stopped;
      stream.getTracks().forEach((track) => track.stop());
      const clip = new Blob(chunks, { type: mimeType });
      const clipDataUrl = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsDataURL(clip);
      });
      return { starter, clip: clipDataUrl, mimeType };
    }, { item, durationMs: config.durationMs, fps: config.fps });

    await writeDataUrl(path.join(config.outDir, pngRel), result.starter);
    await writeDataUrl(path.join(config.outDir, webmRel), result.clip);
    manifest.shots.push({
      ...item,
      starter: pngRel,
      clip: webmRel,
      mime_type: result.mimeType,
    });
    console.log(`captured ${item.group}/${item.speakerId || "room"}/${item.id}`);
  }

  await fs.writeFile(path.join(config.outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
  await browser.close();
  console.log(`reference bank written to ${config.outDir}`);
}

await main();
