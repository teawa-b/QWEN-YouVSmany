// Retime captured package videos to their intended clock.
//
// The capture loop in package_episode.mjs advances the 3D player by exactly
// 1/fps of *player* time per rendered frame, but MediaRecorder stamps frames
// in wall-clock time — headless rendering overhead makes the raw WebM play in
// slow motion. Because every frame is exactly 1/fps apart in player time, the
// fix is exact: restamp frame N to N/fps seconds and encode a normal-speed
// H.264 MP4 next to each WebM.
//
// Used automatically at the end of `npm run package:episode` when ffmpeg is
// available, or standalone on an existing package directory:
//
//   npm run retime:package -- --dir=output/submission/latest [--fps=24]
//
// ffmpeg discovery: YVM_FFMPEG_PATH env var first, then `ffmpeg` on PATH.
import fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

export function findFfmpeg() {
  const candidates = [process.env.YVM_FFMPEG_PATH, "ffmpeg"].filter(Boolean);
  for (const candidate of candidates) {
    try {
      const probe = spawnSync(candidate, ["-version"], { stdio: "ignore" });
      if (probe.status === 0) return candidate;
    } catch {}
  }
  return null;
}

async function listWebm(dir) {
  try {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    return entries
      .filter((e) => e.isFile() && e.name.endsWith(".webm"))
      .map((e) => path.join(dir, e.name));
  } catch {
    return [];
  }
}

function retimeOne(ffmpeg, input, fps) {
  const output = input.replace(/\.webm$/, ".mp4");
  const result = spawnSync(
    ffmpeg,
    [
      "-y",
      "-loglevel", "error",
      "-i", input,
      // Restamp frame N to N/fps seconds (exact player-clock timing).
      "-vf", `setpts=N/(${fps}*TB)`,
      "-r", String(fps),
      "-an",
      "-c:v", "libx264",
      "-preset", "medium",
      "-crf", "20",
      "-pix_fmt", "yuv420p",
      "-movflags", "+faststart",
      output,
    ],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(`ffmpeg retime failed for ${input}: ${result.stderr || result.status}`);
  }
  return output;
}

/**
 * Retime every captured WebM in a package directory (base edit, segment
 * clips, shorts). Returns Map<absolute webm path, absolute mp4 path>.
 */
export async function retimeDir(outDir, { fps = 24, ffmpeg = findFfmpeg() } = {}) {
  if (!ffmpeg) throw new Error("ffmpeg not found (set YVM_FFMPEG_PATH or add ffmpeg to PATH)");
  const inputs = [
    ...(await listWebm(outDir)),
    ...(await listWebm(path.join(outDir, "segments"))),
    ...(await listWebm(path.join(outDir, "shorts"))),
  ];
  const retimed = new Map();
  for (const input of inputs) {
    retimed.set(input, retimeOne(ffmpeg, input, fps));
    console.log(`  retimed ${path.relative(outDir, input)} -> ${path.relative(outDir, retimed.get(input))}`);
  }
  return retimed;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const arg = (name, fallback) => {
    const hit = process.argv.find((x) => x.startsWith(`--${name}=`));
    return hit ? hit.slice(name.length + 3) : fallback;
  };
  const dir = path.resolve(REPO_ROOT, arg("dir", "output/submission/latest"));
  const fps = Number(arg("fps", "24"));
  retimeDir(dir, { fps })
    .then((map) => console.log(`Done: ${map.size} videos retimed in ${path.relative(REPO_ROOT, dir)}`))
    .catch((err) => {
      console.error(err.message || err);
      process.exit(1);
    });
}
