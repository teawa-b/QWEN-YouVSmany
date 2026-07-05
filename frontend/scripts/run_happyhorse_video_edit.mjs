import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

function arg(name, fallback = "") {
  const prefix = `--${name}=`;
  const hit = process.argv.find((x) => x.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}
function flag(name) {
  return process.argv.includes(`--${name}`);
}
async function loadDotEnv(file) {
  try {
    const raw = await fs.readFile(file, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
      const [key, ...rest] = trimmed.split("=");
      if (!process.env[key]) process.env[key] = rest.join("=").replace(/^['"]|['"]$/g, "");
    }
  } catch {
    // Optional local env file.
  }
}

await loadDotEnv(path.join(REPO_ROOT, ".env"));
await loadDotEnv(path.join(REPO_ROOT, "backend", ".env"));

const config = {
  apiKey: process.env.DASHSCOPE_API_KEY || process.env.QWEN_API_KEY || "",
  baseUrl: arg("base-url", process.env.QWEN_DASHSCOPE_URL || "https://dashscope-intl.aliyuncs.com/api/v1"),
  model: arg("model", "happyhorse-1.0-video-edit"),
  videoUrl: arg("video-url"),
  referenceImages: process.argv
    .filter((x) => x.startsWith("--reference-image="))
    .map((x) => x.split("=", 2)[1])
    .filter(Boolean),
  // Default prompt mirrors happyHorsePrompt() in index.html: subject -> scene
  // (the canonical STUDIO_SCENE room, keep in sync with
  // backend/src/youvsmany/media/studio.py) -> motion -> style.
  prompt: arg("prompt", "Transform this 9:16 debate-stage source clip into a realistic live-action debate-show shot. Subject: the person from the first reference image — keep their exact face, hairstyle, outfit, seat position and body orientation. Scene: the same modern television debate studio: layered deep-blue backlit wall panels, a dark ceiling with a visible studio lighting rig, a long warm walnut debate desk with slim microphones, cool blue ambient light with a soft warm key light, and plain glowing screen panels with no writing on them. Motion: keep the original speaking gestures, camera motion, table layout and timing from the source video. Style: photorealistic broadcast footage, natural lighting, gentle depth of field. No captions, no lower thirds, no logos, no watermark, no extra text."),
  resolution: arg("resolution", "720P"),
  out: path.resolve(REPO_ROOT, arg("out", "output/happyhorse/video-edit.mp4")),
  pollMs: Number(arg("poll-ms", "10000")),
  dryRun: flag("dry-run"),
};

function payload() {
  if (!config.videoUrl) throw new Error("Missing --video-url=<public MP4/WebM URL>");
  if (config.referenceImages.length > 5) throw new Error("HappyHorse video edit supports up to 5 reference images");
  return {
    model: config.model,
    input: {
      prompt: config.prompt,
      media: [
        { type: "video", url: config.videoUrl },
        ...config.referenceImages.map((url) => ({ type: "reference_image", url })),
      ],
    },
    parameters: {
      resolution: config.resolution,
    },
  };
}

async function submit(body) {
  const response = await fetch(`${config.baseUrl}/services/aigc/video-generation/video-synthesis`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      "Content-Type": "application/json",
      "X-DashScope-Async": "enable",
    },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`HappyHorse submit failed ${response.status}: ${JSON.stringify(data)}`);
  const taskId = data.output?.task_id;
  if (!taskId) throw new Error(`No task_id returned: ${JSON.stringify(data)}`);
  return taskId;
}

async function poll(taskId) {
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, config.pollMs));
    const response = await fetch(`${config.baseUrl}/tasks/${taskId}`, {
      headers: { Authorization: `Bearer ${config.apiKey}` },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`HappyHorse poll failed ${response.status}: ${JSON.stringify(data)}`);
    const out = data.output || {};
    const status = out.task_status;
    console.log(`status ${status}`);
    if (status === "SUCCEEDED") return out.video_url;
    if (status === "FAILED" || status === "CANCELLED" || status === "CANCELED") {
      throw new Error(`HappyHorse task failed: ${JSON.stringify(out)}`);
    }
  }
}

async function download(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed ${response.status} for ${url}`);
  await fs.mkdir(path.dirname(config.out), { recursive: true });
  await fs.writeFile(config.out, Buffer.from(await response.arrayBuffer()));
}

const body = payload();
if (config.dryRun) {
  console.log(JSON.stringify(body, null, 2));
  process.exit(0);
}
if (!config.apiKey) throw new Error("Missing DASHSCOPE_API_KEY or QWEN_API_KEY");

const taskId = await submit(body);
console.log(`task ${taskId}`);
const videoUrl = await poll(taskId);
console.log(`video ${videoUrl}`);
await download(videoUrl);
console.log(`saved ${config.out}`);
