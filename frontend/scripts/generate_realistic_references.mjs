// Realistic reference generation via Qwen Image Edit Max (local variant of the
// backend /media/realistic-refs/generate endpoint — keep prompts/behavior in
// sync with backend/src/youvsmany/media/reference_assets.py).
//
// Strategy:
// - Intro + per-speaker `close` shots generate first; the generated realistic
//   close image then anchors identity for that speaker's other angles.
// - Each shot is independent: moderation rejections retry once with a plain
//   fallback prompt, throttles/transients retry with backoff, and anything
//   still failing is recorded in the manifest instead of aborting the run.
// - The manifest is rewritten after every shot, so partial banks are usable
//   and re-running (without --overwrite) only fills in the missing shots.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");

function arg(name, fallback) {
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
  endpoint: arg("endpoint", process.env.QWEN_IMAGE_EDIT_URL || "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"),
  model: arg("model", "qwen-image-edit-max"),
  sourceDir: path.resolve(REPO_ROOT, arg("source", "frontend/assets/reference/vertical-v1")),
  outDir: path.resolve(REPO_ROOT, arg("out", "frontend/assets/reference/realistic-v1")),
  size: arg("size", "1080*1920"),
  delayMs: Number(arg("delay-ms", "2000")),
  limit: Number(arg("limit", "0")),
  dryRun: flag("dry-run"),
  overwrite: flag("overwrite"),
};

const speakerProfiles = {
  protagonist: {
    slot: "main_speaker",
    label: "Main Speaker",
    seed: 411001,
    description:
      "confident man in his early 30s, clean modern styling, deep teal suit jacket over a dark shirt, calm focused expression",
  },
  challenger_1: {
    slot: "second_speaker",
    label: "Second Speaker",
    seed: 411101,
    description:
      "composed woman in her late 20s, sharp confident presence, deep red tailored blazer over a black top",
  },
  challenger_2: {
    slot: "third_speaker",
    label: "Third Speaker",
    seed: 411201,
    description:
      "analytical man in his mid 30s, burgundy tailored jacket over a charcoal shirt, steady direct posture",
  },
  challenger_3: {
    slot: "fourth_speaker",
    label: "Fourth Speaker",
    seed: 411301,
    description:
      "poised woman in her early 30s, rust-red tailored jacket over a dark top, confident debate-show presence",
  },
};

const shotDescriptions = {
  intro_wide: "vertical wide view of the whole debate table and panel in a cinematic studio",
  intro_table: "vertical table-level opening view with the debate desk leading the eye into the room",
  intro_panel: "vertical opening view of the opposing speaker bench in a premium studio debate set",
  close: "tight vertical upper-body speaking view, head and shoulders prominent",
  medium: "vertical medium upper-body speaking view, chest and arms visible, table edge in foreground",
  profile: "vertical side-profile speaking view, cinematic panel-discussion angle",
  over_table: "vertical over-table speaking view with depth across the debate desk",
};

// DashScope error codes worth retrying with backoff (rate limits / transient).
const RETRYABLE_CODES = new Set([
  "Throttling",
  "Throttling.RateQuota",
  "Throttling.AllocationQuota",
  "RequestTimeOut",
  "InternalError",
  "SystemError",
  "InternalError.Algo",
]);

const dataUrlCache = new Map();
async function imageDataUrl(file) {
  if (!dataUrlCache.has(file)) {
    const buf = await fs.readFile(file);
    const mime = buf[0] === 0xff && buf[1] === 0xd8 ? "image/jpeg" : "image/png";
    dataUrlCache.set(file, `data:${mime};base64,${buf.toString("base64")}`);
  }
  return dataUrlCache.get(file);
}

function stableSeed(shot) {
  const profile = speakerProfiles[shot.speakerId] || speakerProfiles.protagonist;
  const shotOffset = [...String(shot.group + shot.id)].reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
  return profile.seed + shotOffset;
}

// The canonical studio-room description shared by every generation prompt so
// all characters and shots land in the same room. Keep byte-identical to
// backend/src/youvsmany/media/studio.py (STUDIO_SCENE).
const STUDIO_SCENE = "the same modern television debate studio: layered deep-blue backlit wall panels, a dark ceiling with a visible studio lighting rig, a long warm walnut debate desk with slim microphones, cool blue ambient light with a soft warm key light, and plain glowing screen panels with no writing on them";

function promptFor(shot) {
  const profile = speakerProfiles[shot.speakerId] || speakerProfiles.protagonist;
  const isIntro = shot.group === "intro";
  const shotText = shotDescriptions[shot.id] || shotDescriptions[shot.shot] || "vertical cinematic debate-show reference";
  const identityLine = isIntro
    ? "Use the input image as the exact composition reference for the debate room, seating layout, table geometry and camera angle."
    : "Use image 1 as the locked identity reference for the person, and image 2 as the exact pose, framing, camera angle and table composition reference.";

  return [
    identityLine,
    "Create a realistic 9:16 cinematic live-action frame for a premium televised debate show.",
    `Subject: ${profile.description}.`,
    `Environment: ${STUDIO_SCENE}.`,
    `Camera: ${shotText}.`,
    "Preserve the same speaker position, body orientation, table placement, lighting direction and camera perspective from the source reference.",
    "Keep this speaker visually consistent across every image: same facial features, hairstyle, outfit colors and overall identity.",
    "Style: photorealistic broadcast photography, natural lighting, realistic fabric and materials, gentle depth of field.",
    "No captions, no subtitles, no lower thirds, no text, no logos, no watermark.",
  ].join(" ");
}

// Deliberately plain wording used when moderation rejects the main prompt.
function fallbackPromptFor(shot) {
  if (shot.group === "intro") {
    return `Turn this image into a realistic photo of the same television debate studio. Setting: ${STUDIO_SCENE}. Keep the same composition, seating layout, table and camera angle. Vertical 9:16 framing. No text or logos.`;
  }
  return `Turn this into a realistic photo of a professional television debate speaker. Setting: ${STUDIO_SCENE}. Keep the same pose, seat position, outfit colors and camera angle as the reference images. Vertical 9:16 framing. No text or logos.`;
}

function negativePrompt() {
  return [
    "cartoon",
    "anime",
    "illustration",
    "3d render",
    "toy",
    "plastic",
    "doll",
    "low quality",
    "blurry",
    "text",
    "caption",
    "subtitle",
    "logo",
    "watermark",
  ].join(", ");
}

class QwenRequestError extends Error {
  constructor(status, code, message) {
    super(`Qwen request failed ${status} [${code}]: ${message}`);
    this.status = status;
    this.code = code;
    this.retryable = RETRYABLE_CODES.has(code) || status >= 500;
  }
}

async function requestEdit({ inputImages, prompt, seed }) {
  const response = await fetch(config.endpoint, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: config.model,
      input: {
        messages: [
          {
            role: "user",
            content: [
              ...inputImages.map((image) => ({ image })),
              { text: prompt },
            ],
          },
        ],
      },
      parameters: {
        n: 1,
        size: config.size,
        seed,
        watermark: false,
        // Off on purpose: the server-side rewritten prompt is re-run through
        // content inspection and randomly trips it.
        prompt_extend: false,
        negative_prompt: negativePrompt(),
      },
    }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new QwenRequestError(response.status, String(data.code || "Unknown"), String(data.message || JSON.stringify(data)));
  }
  return data;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Retry throttles/transients with backoff; retry moderation rejections once
// with the plain fallback prompt. Returns { result, prompt actually used }.
async function requestEditWithRetry({ inputImages, prompt, fallbackPrompt, seed, maxAttempts = 5 }) {
  let activePrompt = prompt;
  for (let attempt = 1; ; attempt += 1) {
    try {
      const result = await requestEdit({ inputImages, prompt: activePrompt, seed });
      return { result, usedPrompt: activePrompt };
    } catch (error) {
      if (error instanceof QwenRequestError && error.code === "DataInspectionFailed" && activePrompt !== fallbackPrompt) {
        console.warn(`  moderation rejected prompt — retrying with fallback wording`);
        activePrompt = fallbackPrompt;
        continue;
      }
      const retryable = error instanceof QwenRequestError ? error.retryable : true;
      if (!retryable || attempt >= maxAttempts) throw error;
      const waitMs = Math.min(2 ** attempt * 2000, 45000) + Math.random() * 1000;
      console.warn(`  retryable failure (${error.message}) — waiting ${Math.round(waitMs / 1000)}s`);
      await sleep(waitMs);
    }
  }
}

function outputUrls(result) {
  const choices = result.output?.choices || [];
  return choices
    .flatMap((choice) => choice.message?.content || [])
    .map((item) => item.image)
    .filter((url) => typeof url === "string" && /^https?:\/\//.test(url));
}

async function download(url, file) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed ${response.status} for ${url}`);
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, Buffer.from(await response.arrayBuffer()));
}

// Intros and identity-anchor close shots first, dependent angles after.
function planPriority(shot) {
  if (shot.group === "intro") return 0;
  if (shot.id === "close") return 1;
  return 2;
}

async function main() {
  const sourceManifestPath = path.join(config.sourceDir, "manifest.json");
  const sourceManifest = JSON.parse(await fs.readFile(sourceManifestPath, "utf8"));
  const selected = config.limit > 0 ? sourceManifest.shots.slice(0, config.limit) : sourceManifest.shots;
  const shots = [...selected].sort((a, b) => planPriority(a) - planPriority(b));

  await fs.mkdir(config.outDir, { recursive: true });

  const plan = [];
  for (const shot of shots) {
    const sourceStarter = path.join(config.sourceDir, shot.starter);
    const identityShot = sourceManifest.shots.find(
      (candidate) => candidate.speakerId === shot.speakerId && candidate.id === "close",
    );
    const identityStarter = identityShot ? path.join(config.sourceDir, identityShot.starter) : sourceStarter;
    const identityRealistic = identityShot
      ? path.join(config.outDir, path.dirname(identityShot.starter), "realistic.png")
      : null;
    const relDir = path.dirname(shot.starter);
    const outputRel = path.join(relDir, "realistic.png").replaceAll("\\", "/");
    const outputFile = path.join(config.outDir, outputRel);
    plan.push({
      shot,
      sourceStarter,
      identityStarter,
      identityRealistic,
      outputRel,
      outputFile,
      seed: stableSeed(shot),
      prompt: promptFor(shot),
      fallbackPrompt: fallbackPromptFor(shot),
    });
  }

  const manifest = {
    version: 1,
    source_bank: path.relative(config.outDir, config.sourceDir).replaceAll("\\", "/"),
    model: config.model,
    provider: "qwen-image-edit-max",
    format: "9:16",
    size: config.size,
    generated_at: new Date().toISOString(),
    dry_run: config.dryRun,
    shots: [],
  };

  async function flush() {
    manifest.generated_count = manifest.shots.filter((s) => s.status === "generated" || s.status === "existing").length;
    manifest.failed_count = manifest.shots.filter((s) => s.status === "failed").length;
    await fs.writeFile(path.join(config.outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
  }

  if (!config.apiKey && !config.dryRun) {
    throw new Error("Missing DASHSCOPE_API_KEY or QWEN_API_KEY. Add one to the environment or backend/.env, or run with --dry-run.");
  }

  for (let index = 0; index < plan.length; index += 1) {
    const item = plan[index];
    const exists = await fs.stat(item.outputFile).then(() => true).catch(() => false);
    if (exists && !config.overwrite) {
      console.log(`skip existing ${item.outputRel}`);
      manifest.shots.push({ ...item.shot, realistic: item.outputRel, seed: item.seed, prompt: item.prompt, status: "existing" });
      await flush();
      continue;
    }

    if (config.dryRun) {
      console.log(`[dry-run] ${item.outputRel}`);
      manifest.shots.push({ ...item.shot, realistic: item.outputRel, seed: item.seed, prompt: item.prompt, status: "planned" });
      await flush();
      continue;
    }

    // Prefer the already-generated realistic close shot as the identity
    // anchor; the plan ordering guarantees close shots run first.
    const identityRealisticExists = item.identityRealistic
      && item.identityRealistic !== item.outputFile
      && await fs.stat(item.identityRealistic).then(() => true).catch(() => false);
    const identityFile = identityRealisticExists ? item.identityRealistic : item.identityStarter;
    const inputImages = identityFile === item.sourceStarter || item.identityRealistic === item.outputFile
      ? [await imageDataUrl(item.sourceStarter)]
      : [await imageDataUrl(identityFile), await imageDataUrl(item.sourceStarter)];

    console.log(`generate ${item.outputRel}${identityRealisticExists ? " (realistic identity anchor)" : ""}`);
    try {
      const { result, usedPrompt } = await requestEditWithRetry({
        inputImages,
        prompt: item.prompt,
        fallbackPrompt: item.fallbackPrompt,
        seed: item.seed,
      });
      const urls = outputUrls(result);
      if (!urls.length) throw new Error(`No output URL in response: ${JSON.stringify(result)}`);
      await download(urls[0], item.outputFile);
      manifest.shots.push({ ...item.shot, realistic: item.outputRel, seed: item.seed, prompt: usedPrompt, status: "generated" });
    } catch (error) {
      console.error(`FAILED ${item.outputRel}: ${error.message}`);
      manifest.shots.push({ ...item.shot, seed: item.seed, prompt: item.prompt, status: "failed", error: error.message });
    }
    await flush();

    if (index < plan.length - 1 && config.delayMs > 0) {
      await sleep(config.delayMs);
    }
  }

  await flush();
  const failed = manifest.shots.filter((s) => s.status === "failed");
  console.log(`${config.dryRun ? "planned" : "generated"} ${manifest.shots.length - failed.length}/${manifest.shots.length} realistic references in ${config.outDir}`);
  if (failed.length) {
    console.log(`${failed.length} failed — re-run the same command to retry only the missing shots.`);
    process.exitCode = 2;
  }
}

await main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
