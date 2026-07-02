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
  delayMs: Number(arg("delay-ms", "33000")),
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
      "confident male-presenting debate contestant, early 30s, clean modern styling, deep teal suit jacket over a dark shirt, calm focused expression",
  },
  challenger_1: {
    slot: "second_speaker",
    label: "Second Speaker",
    seed: 411101,
    description:
      "female-presenting debate contestant, late 20s, composed and sharp, deep red tailored blazer over a black top, expressive but controlled presence",
  },
  challenger_2: {
    slot: "third_speaker",
    label: "Third Speaker",
    seed: 411201,
    description:
      "male-presenting debate contestant, mid 30s, analytical and intense, burgundy tailored jacket over a charcoal shirt, direct steady posture",
  },
  challenger_3: {
    slot: "fourth_speaker",
    label: "Fourth Speaker",
    seed: 411301,
    description:
      "female-presenting debate contestant, early 30s, poised and skeptical, rust-red tailored jacket over a dark top, cinematic debate-show presence",
  },
};

const shotDescriptions = {
  intro_wide: "vertical establishing shot of the whole debate table and panel in a cinematic studio",
  intro_table: "vertical table-level opening shot with the debate desk leading the eye into the room",
  intro_panel: "vertical opening shot of the opposing speaker bench in a premium studio debate set",
  close: "tight vertical upper-body speaking reference, head and shoulders prominent",
  medium: "vertical medium upper-body speaking reference, chest and arms visible, table edge in foreground",
  profile: "vertical side profile speaking reference, cinematic panel-discussion angle",
  over_table: "vertical over-table speaking reference with depth across the debate desk",
};

function imageDataUrl(file) {
  return fs.readFile(file).then((buf) => `data:image/png;base64,${buf.toString("base64")}`);
}

function stableSeed(shot) {
  const profile = speakerProfiles[shot.speakerId] || speakerProfiles.protagonist;
  const shotOffset = [...String(shot.group + shot.id)].reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
  return profile.seed + shotOffset;
}

function promptFor(shot) {
  const profile = speakerProfiles[shot.speakerId] || speakerProfiles.protagonist;
  const isIntro = shot.group === "intro";
  const shotText = shotDescriptions[shot.id] || shotDescriptions[shot.shot] || "vertical cinematic debate-show reference";
  const identityLine = isIntro
    ? "Use the input image as the exact composition reference for the debate room, seating layout, table geometry and camera angle."
    : "Use image 1 as the locked identity/style reference for the person, and image 2 as the exact pose, framing, camera angle and table composition reference.";

  return [
    identityLine,
    `Create a realistic 9:16 cinematic live-action frame for a premium AI debate show.`,
    `Subject: ${profile.description}.`,
    `Shot: ${shotText}.`,
    "Preserve the same speaker slot, seating position, body orientation, table placement, lighting direction and camera perspective from the source reference.",
    "Keep the character visually consistent across all outputs for this speaker: same face structure, outfit color family, hairstyle silhouette, body type and overall identity.",
    "Make it photorealistic: real human proportions, natural skin, realistic fabric, cinematic studio lighting, polished broadcast set, shallow but usable depth of field.",
    "No captions, no subtitles, no lower thirds, no text, no logos, no watermark, no UI elements.",
  ].join(" ");
}

function negativePrompt() {
  return [
    "cartoon",
    "3d render",
    "toy",
    "plastic",
    "robot",
    "mannequin",
    "helmet",
    "faceless",
    "extra limbs",
    "distorted hands",
    "text",
    "caption",
    "subtitle",
    "logo",
    "watermark",
    "cropped head",
    "out of frame subject",
  ].join(", ");
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
        prompt_extend: true,
        negative_prompt: negativePrompt(),
      },
    }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`Qwen request failed ${response.status}: ${JSON.stringify(data)}`);
  }
  return data;
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

async function main() {
  const sourceManifestPath = path.join(config.sourceDir, "manifest.json");
  const sourceManifest = JSON.parse(await fs.readFile(sourceManifestPath, "utf8"));
  const shots = config.limit > 0 ? sourceManifest.shots.slice(0, config.limit) : sourceManifest.shots;

  await fs.mkdir(config.outDir, { recursive: true });

  const plan = [];
  for (const shot of shots) {
    const sourceStarter = path.join(config.sourceDir, shot.starter);
    const identityShot = sourceManifest.shots.find(
      (candidate) => candidate.speakerId === shot.speakerId && candidate.id === "close",
    );
    const identityStarter = identityShot ? path.join(config.sourceDir, identityShot.starter) : sourceStarter;
    const relDir = path.dirname(shot.starter);
    const outputRel = path.join(relDir, "realistic.png").replaceAll("\\", "/");
    const outputFile = path.join(config.outDir, outputRel);
    const seed = stableSeed(shot);
    const prompt = promptFor(shot);
    plan.push({ shot, sourceStarter, identityStarter, outputRel, outputFile, seed, prompt });
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

  if (!config.apiKey && !config.dryRun) {
    throw new Error("Missing DASHSCOPE_API_KEY or QWEN_API_KEY. Add one to the environment or backend/.env, or run with --dry-run.");
  }

  for (let index = 0; index < plan.length; index += 1) {
    const item = plan[index];
    const exists = await fs.stat(item.outputFile).then(() => true).catch(() => false);
    if (exists && !config.overwrite) {
      console.log(`skip existing ${item.outputRel}`);
      manifest.shots.push({ ...item.shot, realistic: item.outputRel, seed: item.seed, prompt: item.prompt, status: "existing" });
      continue;
    }

    if (config.dryRun) {
      console.log(`[dry-run] ${item.outputRel}`);
      manifest.shots.push({ ...item.shot, realistic: item.outputRel, seed: item.seed, prompt: item.prompt, status: "planned" });
      continue;
    }

    const inputImages = item.identityStarter === item.sourceStarter
      ? [await imageDataUrl(item.sourceStarter)]
      : [await imageDataUrl(item.identityStarter), await imageDataUrl(item.sourceStarter)];

    console.log(`generate ${item.outputRel}`);
    const finished = await requestEdit({ inputImages, prompt: item.prompt, seed: item.seed });
    const urls = outputUrls(finished);
    if (!urls.length) throw new Error(`No output URL for ${item.outputRel}: ${JSON.stringify(finished)}`);
    await download(urls[0], item.outputFile);

    manifest.shots.push({
      ...item.shot,
      realistic: item.outputRel,
      seed: item.seed,
      prompt: item.prompt,
      status: "generated",
    });

    if (index < plan.length - 1 && config.delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, config.delayMs));
    }
  }

  await fs.writeFile(path.join(config.outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log(`${config.dryRun ? "planned" : "generated"} ${manifest.shots.length} realistic references in ${config.outDir}`);
}

await main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
