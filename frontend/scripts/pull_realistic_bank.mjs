// Download the backend-generated realistic reference bank into the repo so it
// persists across Railway's ephemeral redeploys and the frontend can serve it
// directly (loadRealisticBank() prefers the local "frontend" source).
//
//   node scripts/pull_realistic_bank.mjs --api https://<backend>.up.railway.app
//
// Writes manifest.json + every realistic.png into
// frontend/assets/reference/realistic-v1/ mirroring the shot layout.
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");

function arg(name, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  if (hit) return hit.slice(name.length + 3);
  const idx = process.argv.indexOf(`--${name}`);
  if (idx >= 0 && process.argv[idx + 1]) return process.argv[idx + 1];
  return fallback;
}

const apiBase = (arg("api", process.env.YVM_API_BASE) || "").replace(/\/$/, "");
if (!apiBase) {
  console.error("Provide the backend URL: --api https://<backend>.up.railway.app (or YVM_API_BASE)");
  process.exit(1);
}
const outDir = path.resolve(REPO_ROOT, arg("out", "frontend/assets/reference/realistic-v1"));

async function main() {
  const manifestUrl = `${apiBase}/media/realistic-refs/manifest.json`;
  const res = await fetch(manifestUrl, { cache: "no-store" });
  if (!res.ok) throw new Error(`manifest fetch failed (${res.status}) from ${manifestUrl}`);
  const manifest = await res.json();

  await fs.mkdir(outDir, { recursive: true });
  const shots = manifest.shots || [];
  let pulled = 0;
  for (const shot of shots) {
    if (!shot.realistic || !["generated", "existing"].includes(shot.status)) continue;
    const url = `${apiBase}/media/realistic-refs/files/${shot.realistic}`;
    const target = path.join(outDir, shot.realistic);
    const r = await fetch(url);
    if (!r.ok) {
      console.warn(`  skip ${shot.realistic} (${r.status})`);
      continue;
    }
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, Buffer.from(await r.arrayBuffer()));
    pulled += 1;
    console.log(`  pulled ${shot.realistic}`);
  }

  await fs.writeFile(path.join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log(`Done: ${pulled}/${shots.length} images into ${path.relative(REPO_ROOT, outDir)}`);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
