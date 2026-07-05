// Produce the polished final episode video from a package directory:
// burn timed, speaker-colored captions (built from scene_manifest.json)
// into the retimed base edit, writing final_episode.mp4.
//
//   npm run finalize:episode -- --dir=output/submission/latest
//
// Runs automatically at the end of `npm run package:episode` when ffmpeg is
// available. The captions live in the page DOM during capture (not on the 3D
// canvas), so the raw recording has no dialogue text — this step restores it.
import fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { findFfmpeg } from "./retime_package.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

// Mirrors the app's speaker palette (index.html): protagonist accent + the
// challenger palette, converted to ASS &HBBGGRR& at build time.
const ACCENT = "#7b97ff";
const PALETTE = ["#f0997b", "#5dcaa5", "#d4537e", "#efbf4f", "#85b7eb"];

function assColor(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => hex.slice(i, i + 2));
  return `&H${(b + g + r).toUpperCase()}&`;
}

function assTime(seconds) {
  const cs = Math.max(0, Math.round(seconds * 100));
  const h = Math.floor(cs / 360000);
  const m = Math.floor((cs % 360000) / 6000);
  const s = Math.floor((cs % 6000) / 100);
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs % 100).padStart(2, "0")}`;
}

function assEscape(text) {
  return String(text).replace(/\\/g, "\\\\").replace(/\{/g, "(").replace(/\}/g, ")").replace(/\n/g, "\\N");
}

export function buildAss(episode, scene) {
  const colorFor = {};
  let ci = 0;
  for (const c of episode.cast || []) {
    colorFor[c.character_id] = c.role === "protagonist" ? ACCENT : PALETTE[ci++ % PALETTE.length];
  }
  const nameFor = (id) =>
    (episode.cast || []).find((c) => c.character_id === id)?.display_name || id;

  const events = (scene.segments || [])
    .filter((s) => s.dialogue && s.speaker_id !== "caption")
    .map((s) => {
      const color = assColor(colorFor[s.speaker_id] || "#ffffff");
      const name = assEscape(nameFor(s.speaker_id).toUpperCase());
      const text = assEscape(s.dialogue);
      return `Dialogue: 0,${assTime(s.start_s)},${assTime(s.end_s)},Caption,,0,0,0,,{\\c${color}}${name}\\N{\\c&HFFFFFF&}${text}`;
    });

  return [
    "[Script Info]",
    "ScriptType: v4.00+",
    "PlayResX: 540",
    "PlayResY: 960",
    "WrapStyle: 0",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    // Bottom-center, generous side margins for the 9:16 frame, soft box.
    "Style: Caption,DejaVu Sans,22,&HFFFFFF&,&HFFFFFF&,&H90101318&,&H90101318&,-1,0,0,0,100,100,0,0,3,10,0,2,28,28,64,1",
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ...events,
    "",
  ].join("\n");
}

export async function finalizeEpisode(outDir, { ffmpeg = findFfmpeg() } = {}) {
  if (!ffmpeg) throw new Error("ffmpeg not found (set YVM_FFMPEG_PATH or add ffmpeg to PATH)");
  const episode = JSON.parse(await fs.readFile(path.join(outDir, "episode.json"), "utf8"));
  const scene = JSON.parse(await fs.readFile(path.join(outDir, "scene_manifest.json"), "utf8"));
  const base = ["base_edit.mp4", "base_edit.webm"].find(
    (name) => spawnSync("test", ["-f", path.join(outDir, name)]).status === 0,
  );
  if (!base) throw new Error(`no base_edit video in ${outDir}`);
  if (base.endsWith(".webm")) {
    console.warn("finalizing from raw WebM (not retimed) — run retime:package first for correct speed");
  }

  const assFile = path.join(outDir, "captions.ass");
  await fs.writeFile(assFile, buildAss(episode, scene));

  const output = path.join(outDir, "final_episode.mp4");
  // The subtitles filter parses its path argument; escape what matters.
  const assArg = assFile.replace(/\\/g, "/").replace(/:/g, "\\:").replace(/'/g, "\\'");
  const result = spawnSync(
    ffmpeg,
    [
      "-y", "-loglevel", "error",
      "-i", path.join(outDir, base),
      "-vf", `subtitles='${assArg}'`,
      "-c:v", "libx264", "-preset", "medium", "-crf", "20",
      "-pix_fmt", "yuv420p", "-movflags", "+faststart",
      output,
    ],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(`ffmpeg caption burn failed: ${result.stderr || result.status}`);
  }
  return output;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const arg = (name, fallback) => {
    const hit = process.argv.find((x) => x.startsWith(`--${name}=`));
    return hit ? hit.slice(name.length + 3) : fallback;
  };
  const dir = path.resolve(REPO_ROOT, arg("dir", "output/submission/latest"));
  finalizeEpisode(dir)
    .then((file) => console.log(`Final episode: ${path.relative(REPO_ROOT, file)}`))
    .catch((err) => {
      console.error(err.message || err);
      process.exit(1);
    });
}
