import fs from "node:fs/promises";
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { launchBrowser } from "./lib/browser.mjs";
import { findFfmpeg, retimeDir } from "./retime_package.mjs";
import { finalizeEpisode } from "./finalize_episode.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

function arg(name, fallback = "") {
  const eq = `--${name}=`;
  const hit = process.argv.find((x) => x.startsWith(eq));
  if (hit) return hit.slice(eq.length);
  const idx = process.argv.indexOf(`--${name}`);
  if (idx >= 0 && process.argv[idx + 1]) return process.argv[idx + 1];
  return fallback;
}

const config = {
  url: arg("url", process.env.YVM_FRONTEND_URL || "http://127.0.0.1:5173"),
  api: arg("api", process.env.YVM_API_BASE || "http://127.0.0.1:8000").replace(/\/$/, ""),
  outDir: resolveInsideRepo(arg("out", "output/submission/latest")),
  topic: arg("topic", "Pineapple belongs on pizza"),
  stance: arg("stance", "for"),
  kind: arg("kind", "opinion"),
  challengers: Number(arg("challengers", "3")),
  seed: Number(arg("seed", "0")),
  duration: Number(arg("duration", "90")),
  tags: arg("tags", "texture,tradition,culinary-innovation")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean),
  width: Number(arg("width", "540")),
  height: Number(arg("height", "960")),
  fps: Number(arg("fps", "24")),
  durationScale: Number(arg("duration-scale", "1")),
  limit: Number(arg("limit", "0")),
  stills: Number(arg("stills", "6")),
  segmentCapMs: Number(arg("segment-cap-ms", "0")),
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
      ? path.join(
          process.env.USERPROFILE,
          ".cache",
          "codex-runtimes",
          "codex-primary-runtime",
          "dependencies",
          "node",
          "node_modules",
        )
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
    console.error("Playwright is required for packaging.");
    console.error("Set YVM_NODE_MODULES to a node_modules folder that contains Playwright.");
    console.error(error.message);
    process.exit(1);
  }
}

function dataUrlToBuffer(dataUrl) {
  const base64 = dataUrl.split(",", 2)[1];
  return Buffer.from(base64, "base64");
}

function resolveInsideRepo(target) {
  const resolved = path.resolve(REPO_ROOT, target);
  const rel = path.relative(REPO_ROOT, resolved);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`Output path must stay inside the repo: ${target}`);
  }
  return resolved;
}

async function writeJson(file, data) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, JSON.stringify(data, null, 2));
}

async function writeDataUrl(file, dataUrl) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, dataUrlToBuffer(dataUrl));
}

async function runEpisode() {
  const body = {
    brief: {
      topic: config.topic,
      protagonist_position: config.stance,
      target_duration_s: config.duration,
      num_challengers: config.challengers,
      topic_kind: config.kind,
      seed: config.seed,
    },
    suggested_tags: config.tags,
  };
  const res = await fetch(`${config.api}/episodes/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `episode run failed (${res.status})`);
  if (!data.scene?.segments?.length) throw new Error("episode response has no scene manifest");
  return data;
}

function relative(file) {
  return path.relative(config.outDir, file).replaceAll("\\", "/");
}

function safeName(value) {
  return String(value).replace(/[^a-z0-9_-]+/gi, "_").replace(/^_+|_+$/g, "").toLowerCase();
}

function topSegments(episode, limit = 6) {
  const hero = (episode.scene?.segments || []).filter((s) => s.short_candidate);
  const nonCaption = (episode.scene?.segments || []).filter((s) => s.speaker_id !== "caption");
  const seen = new Set();
  return [...hero, ...nonCaption]
    .filter((s) => {
      if (seen.has(s.segment_id)) return false;
      seen.add(s.segment_id);
      return true;
    })
    .slice(0, limit);
}

function shortGroups(episode) {
  const segments = episode.scene?.segments || [];
  const groups = [];
  for (const highlight of episode.highlights || []) {
    const start = Number(String(highlight.start_turn_id || "").match(/\d+/)?.[0] ?? -1);
    const end = Number(String(highlight.end_turn_id || "").match(/\d+/)?.[0] ?? start);
    const picked = segments.filter((s) => {
      const ix = Number(String(s.segment_id || "").match(/\d+/)?.[0] ?? -1);
      return ix >= Math.min(start, end) && ix <= Math.max(start, end) && s.speaker_id !== "caption";
    });
    if (picked.length) groups.push({ highlight, segments: picked.slice(0, 4) });
  }
  if (!groups.length) {
    groups.push({ highlight: { label: "best_exchange", score: 0 }, segments: topSegments(episode, 3) });
  }
  return groups.slice(0, 3);
}

async function setupPlayer(page, episode, options = {}) {
  await page.goto(config.url, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.YVM3D?.show, null, { timeout: 20000 });
  await page.evaluate(
    ({ width, height }) => {
      document.body.innerHTML = `<div id="stage3d"></div>`;
      document.body.style.margin = "0";
      document.body.style.background = "#000";
      const host = document.getElementById("stage3d");
      host.style.width = `${width}px`;
      host.style.height = `${height}px`;
    },
    { width: config.width, height: config.height },
  );
  await page.evaluate(
    ({ episode, width, height, options }) => {
      const colors = {
        protagonist: 0xf0997b,
        challenger_1: 0x5dcaa5,
        challenger_2: 0xd4537e,
        challenger_3: 0xefbf4f,
        challenger_4: 0x85b7eb,
        challenger_5: 0xefbf4f,
      };
      window.YVM3D.show(
        {
          scene: episode.scene,
          cast: episode.cast,
          apiBase: "",
          colorFor(id) {
            if (colors[id]) return colors[id];
            const ix = episode.cast.findIndex((c) => c.character_id === id);
            return [0xf0997b, 0x5dcaa5, 0xd4537e, 0xefbf4f, 0x85b7eb][Math.max(0, ix) % 5];
          },
          nameFor(id) {
            return episode.cast.find((c) => c.character_id === id)?.display_name || id;
          },
        },
        {
          aspectRatio: width / height,
          captureSize: { width, height },
          hideControls: true,
          hideOverlays: Boolean(options.hideOverlays),
          manualRender: true,
          pixelRatio: 1,
          showCropGuide: false,
        },
      );
    },
    { episode, width: config.width, height: config.height, options },
  );
  await page.waitForFunction(() => window.__YVM3D_DEBUG?.ready, null, { timeout: 30000 });
}

async function renderStill(page, segment, file) {
  const dataUrl = await page.evaluate(
    async ({ segment, fps }) => {
      const player = window.__YVM3D_DEBUG;
      const shot = player._shot(segment);
      player.camDesiredPos = shot.pos;
      player.camDesiredTarget = shot.tgt;
      player.camera.position.copy(shot.pos);
      player.controls.target.copy(shot.tgt);
      player.playing = segment.speaker_id !== "caption";
      player.activeId = segment.speaker_id === "caption" ? null : segment.speaker_id;
      player._setSpeaking(segment);
      for (let i = 0; i < 18; i += 1) player.renderReferenceFrame(1 / fps);
      return player.renderer.domElement.toDataURL("image/png");
    },
    { segment, fps: config.fps },
  );
  await writeDataUrl(file, dataUrl);
}

async function recordSegments(page, segments, file, { overlay = true } = {}) {
  const dataUrl = await page.evaluate(
    async ({ segments, fps, durationScale, segmentCapMs, overlay }) => {
      const player = window.__YVM3D_DEBUG;
      const canvas = player.renderer.domElement;
      const stream = canvas.captureStream(fps);
      const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
        ? "video/webm;codecs=vp9"
        : "video/webm";
      const chunks = [];
      const recorder = new MediaRecorder(stream, {
        mimeType,
        videoBitsPerSecond: 6_000_000,
      });
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      const stopped = new Promise((resolve) => {
        recorder.onstop = resolve;
      });
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

      function frameSegment(segment) {
        const shot = player._shot(segment);
        player.camDesiredPos = shot.pos;
        player.camDesiredTarget = shot.tgt;
        player.camera.position.copy(shot.pos);
        player.controls.target.copy(shot.tgt);
        player.playing = segment.speaker_id !== "caption";
        player.activeId = segment.speaker_id === "caption" ? null : segment.speaker_id;
        if (overlay) player._setSpeaking(segment);
        else player._setLowerThird(null);
      }

      recorder.start();
      for (const segment of segments) {
        frameSegment(segment);
        const rawMs = Math.max(650, (segment.end_s - segment.start_s) * 1000 * durationScale);
        const durationMs = segmentCapMs > 0 ? Math.min(rawMs, segmentCapMs) : rawMs;
        const frames = Math.max(1, Math.round((durationMs / 1000) * fps));
        for (let i = 0; i < frames; i += 1) {
          player.renderReferenceFrame(1 / fps);
          await delay(1000 / fps);
        }
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
    },
    {
      segments,
      fps: config.fps,
      durationScale: config.durationScale,
      segmentCapMs: config.segmentCapMs,
      overlay,
    },
  );
  await writeDataUrl(file, dataUrl);
}

function htmlPage(episode, pkg) {
  const poster = pkg.hero_stills[0]?.file || "";
  const posterAttr = poster ? ` poster="${poster}"` : "";
  const stillCards = pkg.hero_stills
    .map((item) => `<figure><img src="${item.file}" alt="${item.segment_id}"><figcaption>${item.segment_id}</figcaption></figure>`)
    .join("");
  const shortCards = pkg.shorts
    .map((item) => `<article><video src="${item.file}"${posterAttr} controls muted playsinline></video><h3>${item.label}</h3><p>${item.segment_ids.join(", ")}</p></article>`)
    .join("");
  return `<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>You Vs Many Package - ${escapeHtml(episode.topic)}</title>
<style>
body{margin:0;background:#080a0f;color:#eef2f8;font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1120px;margin:0 auto;padding:34px 22px 60px}
h1{margin:0 0 6px;font-size:34px;letter-spacing:.02em} h2{margin:30px 0 12px;font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#8f9aad}
.meta{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 24px}.meta span{border:1px solid #263040;background:#121722;border-radius:999px;padding:6px 10px;color:#bac4d4}
.hero{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:18px;align-items:start}.hero video{width:100%;aspect-ratio:9/16;background:#000;border:1px solid #263040;border-radius:8px}
.panel{border:1px solid #263040;background:#121722;border-radius:8px;padding:16px} pre{white-space:pre-wrap;color:#b8c4d8;margin:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}figure,article{margin:0;border:1px solid #263040;background:#121722;border-radius:8px;overflow:hidden}img,article video{width:100%;display:block;aspect-ratio:9/16;object-fit:cover;background:#000}figcaption,article h3,article p{margin:8px 10px;color:#cbd5e1}article p{font-size:12px;color:#8894a8}
a{color:#95adff}@media(max-width:760px){.hero{grid-template-columns:1fr}}
</style>
<main>
  <h1>You Vs Many</h1>
  <div class="meta">
    <span>${escapeHtml(episode.topic)}</span>
    <span>${episode.state}</span>
    <span>${episode.duration_s}s</span>
    <span>${episode.cast.length} speakers</span>
  </div>
  <section class="hero">
    <video src="${pkg.final_episode?.file || pkg.base_edit.file}"${posterAttr} controls muted playsinline></video>
    <div class="panel">
      <h2>Package Contents</h2>
      <pre>${escapeHtml(JSON.stringify(pkg.summary, null, 2))}</pre>
    </div>
  </section>
  <h2>Hero Stills</h2>
  <div class="grid">${stillCards}</div>
  <h2>Short Candidates</h2>
  <div class="grid">${shortCards}</div>
</main>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"]/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[ch]);
}

async function main() {
  const episode = await runEpisode();
  const selectedSegments = config.limit > 0
    ? episode.scene.segments.slice(0, config.limit)
    : episode.scene.segments;
  const out = config.outDir;
  await fs.rm(out, { recursive: true, force: true });
  await fs.mkdir(out, { recursive: true });
  await writeJson(path.join(out, "episode.json"), episode);
  await writeJson(path.join(out, "scene_manifest.json"), episode.scene);
  await writeJson(path.join(out, "metrics.json"), episode.metrics || {});

  const browser = await launchBrowser(playwright);
  const page = await browser.newPage({
    viewport: { width: config.width + 80, height: config.height + 80 },
    deviceScaleFactor: 1,
  });
  await setupPlayer(page, episode);

  const assets = {
    version: 1,
    generated_at: new Date().toISOString(),
    topic: episode.topic,
    episode_id: episode.episode_id,
    source_api: config.api,
    capture: {
      width: config.width,
      height: config.height,
      fps: config.fps,
      duration_scale: config.durationScale,
      segment_limit: config.limit,
    },
    base_edit: null,
    segment_clips: [],
    hero_stills: [],
    shorts: [],
    summary: {},
  };

  const baseFile = path.join(out, "base_edit.webm");
  await recordSegments(page, selectedSegments, baseFile);
  assets.base_edit = { file: relative(baseFile), segment_count: selectedSegments.length };

  const captureSegments = selectedSegments.filter((s) => s.speaker_id !== "caption");
  for (const segment of captureSegments) {
    const file = path.join(out, "segments", `${safeName(segment.segment_id)}.webm`);
    await recordSegments(page, [segment], file);
    assets.segment_clips.push({
      segment_id: segment.segment_id,
      speaker_id: segment.speaker_id,
      file: relative(file),
      duration_s: Math.round((segment.end_s - segment.start_s) * 1000) / 1000,
    });
  }

  for (const segment of topSegments(episode, config.stills)) {
    const file = path.join(out, "hero_stills", `${safeName(segment.segment_id)}.png`);
    await renderStill(page, segment, file);
    assets.hero_stills.push({
      segment_id: segment.segment_id,
      speaker_id: segment.speaker_id,
      file: relative(file),
      short_candidate: Boolean(segment.short_candidate),
    });
  }

  let shortIndex = 0;
  for (const group of shortGroups(episode)) {
    const file = path.join(out, "shorts", `short_${String(shortIndex + 1).padStart(2, "0")}.webm`);
    await recordSegments(page, group.segments, file);
    assets.shorts.push({
      label: group.highlight.label || `short_${shortIndex + 1}`,
      score: group.highlight.score ?? null,
      segment_ids: group.segments.map((s) => s.segment_id),
      file: relative(file),
    });
    shortIndex += 1;
  }

  await browser.close();

  // MediaRecorder stamps frames in wall-clock time while the capture loop
  // advances the player by exactly 1/fps per frame, so the raw WebMs play in
  // slow motion. Retime them to normal-speed MP4s when ffmpeg is available.
  const ffmpeg = findFfmpeg();
  if (ffmpeg) {
    const retimed = await retimeDir(out, { fps: config.fps, ffmpeg });
    const swap = (entry) => {
      const mp4 = retimed.get(path.join(out, entry.file));
      if (mp4) {
        entry.raw_file = entry.file;
        entry.file = relative(mp4);
      }
    };
    swap(assets.base_edit);
    assets.segment_clips.forEach(swap);
    assets.shorts.forEach(swap);
    assets.capture.retimed = true;
    // Burn timed speaker captions into the retimed base edit — the captions
    // live in the page DOM during capture, so the raw video has none.
    const finalFile = await finalizeEpisode(out, { ffmpeg });
    assets.final_episode = { file: relative(finalFile), captions: "captions.ass" };
  } else {
    assets.capture.retimed = false;
    console.warn(
      "ffmpeg not found — captured WebM files keep wall-clock (slow) timing; " +
      "set YVM_FFMPEG_PATH or install ffmpeg, then run: npm run retime:package -- --dir=" +
      path.relative(REPO_ROOT, out),
    );
  }

  assets.summary = {
    state: episode.state,
    approved: episode.approved,
    turns: episode.turns.length,
    duration_s: episode.duration_s,
    metrics: episode.metrics,
    base_edit: assets.base_edit.file,
    segment_clips: assets.segment_clips.length,
    hero_stills: assets.hero_stills.length,
    shorts: assets.shorts.length,
    realistic_refs: "frontend/assets/reference/realistic-v1",
  };
  await writeJson(path.join(out, "package_manifest.json"), assets);
  await fs.writeFile(path.join(out, "index.html"), htmlPage(episode, assets));
  console.log(JSON.stringify({ ok: true, out: path.relative(REPO_ROOT, out).replaceAll("\\", "/"), summary: assets.summary }, null, 2));
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
