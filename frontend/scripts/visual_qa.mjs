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
  outDir: path.resolve(REPO_ROOT, arg("out", "output/playwright")),
  width: Number(arg("width", "960")),
  height: Number(arg("height", "540")),
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
    console.error("Playwright is required for visual QA.");
    console.error("Set YVM_NODE_MODULES to a node_modules folder that contains Playwright.");
    console.error(error.message);
    process.exit(1);
  }
}

const cast = [
  {
    character_id: "protagonist",
    display_name: "Main Speaker",
    role: "protagonist",
    stance: "for",
    visual_presentation: "male",
  },
  {
    character_id: "challenger_1",
    display_name: "Second Speaker",
    role: "challenger",
    stance: "against",
    visual_presentation: "female",
  },
  {
    character_id: "challenger_2",
    display_name: "Third Speaker",
    role: "challenger",
    stance: "against",
    visual_presentation: "male",
  },
  {
    character_id: "challenger_3",
    display_name: "Fourth Speaker",
    role: "challenger",
    stance: "against",
    visual_presentation: "female",
  },
];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  await fs.mkdir(config.outDir, { recursive: true });
  const browser = await launchBrowser(playwright);
  const page = await browser.newPage({
    viewport: { width: config.width, height: config.height },
    deviceScaleFactor: 1,
  });

  await page.goto(config.url, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.YVM3D?.show, null, { timeout: 20000 });
  await page.evaluate(() => {
    document.body.innerHTML = '<main style="width:920px;margin:0 auto"><div id="stage3d"></div></main>';
    document.body.style.margin = "0";
    document.body.style.background = "#000";
  });

  await page.evaluate((cast) => {
    window.YVM3D.show(
      {
        scene: {
          scene_template: {
            template_id: "studio_midnight",
            display_name: "Midnight Debate Studio",
            asset_url: "/assets/scenes/studio_midnight.glb",
          },
          total_duration_s: 2,
          audio: [],
          segments: [
            {
              segment_id: "seg_00",
              start_s: 0,
              end_s: 2,
              speaker_id: "protagonist",
              dialogue: "Visual QA checks the studio set, crop guide and stage framing.",
              camera: { shot: "protagonist_close" },
            },
          ],
        },
        cast,
        colorFor(id) {
          return (
            {
              protagonist: 0xf0997b,
              challenger_1: 0x5dcaa5,
              challenger_2: 0xd4537e,
              challenger_3: 0xefbf4f,
            }[id] || 0xffffff
          );
        },
        nameFor(id) {
          return cast.find((c) => c.character_id === id)?.display_name || id;
        },
        apiBase: "",
      },
      { hideControls: true, pixelRatio: 1 },
    );
  }, cast);

  await page.waitForFunction(() => window.__YVM3D_DEBUG?.ready, null, { timeout: 30000 });
  const metrics = await page.evaluate(async () => {
    const player = window.__YVM3D_DEBUG;
    player.playing = true;
    player.activeId = "protagonist";
    player.setReferenceShot({ speakerId: "protagonist", shot: "protagonist_close", speaking: true });
    for (let i = 0; i < 18; i += 1) player.renderReferenceFrame(1 / 30);

    const canvas = player.renderer.domElement;
    const probe = document.createElement("canvas");
    probe.width = canvas.width;
    probe.height = canvas.height;
    const ctx = probe.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(canvas, 0, 0);
    const image = ctx.getImageData(0, 0, probe.width, probe.height).data;
    let varied = 0;
    let centerVaried = 0;
    const cropW = Math.round(probe.height * 9 / 16);
    const cropX = Math.round((probe.width - cropW) / 2);
    for (let y = 0; y < probe.height; y += 12) {
      for (let x = 0; x < probe.width; x += 12) {
        const i = (y * probe.width + x) * 4;
        const lum = image[i] + image[i + 1] + image[i + 2];
        if (lum > 18) {
          varied += 1;
          if (x >= cropX && x <= cropX + cropW) centerVaried += 1;
        }
      }
    }
    return {
      stageSetLoaded: Boolean(player.stageSetLoaded),
      stageSetUrl: player.stageSetUrl,
      canvasWidth: probe.width,
      canvasHeight: probe.height,
      varied,
      centerVaried,
    };
  });

  assert(metrics.stageSetLoaded, "studio GLB did not load into the 3D player");
  assert(metrics.varied > 500, `3D canvas looks blank (${metrics.varied} varied samples)`);
  assert(metrics.centerVaried > 120, `9:16 crop area looks unsafe (${metrics.centerVaried} samples)`);

  const bank = await page.evaluate(async () => {
    const manifestRes = await fetch("/assets/reference/realistic-v1/manifest.json", { cache: "no-store" });
    const manifest = await manifestRes.json();
    const shots = manifest.shots || [];
    const ready = shots.filter((s) => s.realistic && ["generated", "existing"].includes(s.status));
    const first = ready[0];
    const img = new Image();
    img.src = `/assets/reference/realistic-v1/${first.realistic}`;
    await img.decode();
    const pngRes = await fetch(`/assets/reference/realistic-v1/${first.realistic}`, { cache: "no-store" });
    const webmRes = await fetch("/assets/reference/vertical-v1/main_speaker/protagonist/close/clip.webm", { cache: "no-store" });
    return {
      sourceCount: shots.length,
      readyCount: ready.length,
      failedCount: shots.filter((s) => s.status === "failed").length,
      imageWidth: img.naturalWidth,
      imageHeight: img.naturalHeight,
      pngType: pngRes.headers.get("content-type") || "",
      webmType: webmRes.headers.get("content-type") || "",
    };
  });

  assert(bank.sourceCount >= 19, `realistic bank manifest is incomplete (${bank.sourceCount})`);
  assert(bank.readyCount >= 18, `expected at least 18 realistic images, got ${bank.readyCount}`);
  assert(bank.imageWidth >= 1000 && bank.imageHeight >= 1800, `bad realistic image size ${bank.imageWidth}x${bank.imageHeight}`);
  assert(bank.pngType.includes("image/png"), `PNG served with wrong MIME type: ${bank.pngType}`);
  assert(bank.webmType.includes("video/webm"), `WebM served with wrong MIME type: ${bank.webmType}`);

  const screenshotPath = path.join(config.outDir, "visual-qa-stage.png");
  await page.locator("#stage3d .s3d-canvas").screenshot({ path: screenshotPath });
  await browser.close();

  console.log(
    JSON.stringify(
      {
        ok: true,
        stage: metrics,
        bank,
        screenshot: path.relative(REPO_ROOT, screenshotPath).replaceAll("\\", "/"),
      },
      null,
      2,
    ),
  );
}

main().catch(async (error) => {
  console.error(error.message || error);
  process.exit(1);
});
