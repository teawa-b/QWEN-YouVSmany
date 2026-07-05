// Download the backend-generated persistent character identity bank into the
// repo so it survives Railway's ephemeral redeploys and the frontend can serve
// it directly (loadCharacterBank() prefers the local "frontend" source).
//
//   node scripts/pull_character_bank.mjs --api https://<backend>.up.railway.app
//
// Writes manifest.json + every <roster_id>/identity.png into
// frontend/assets/reference/characters-v1/.
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
const outDir = path.resolve(REPO_ROOT, arg("out", "frontend/assets/reference/characters-v1"));

async function main() {
  const manifestUrl = `${apiBase}/media/character-bank/manifest.json`;
  const res = await fetch(manifestUrl, { cache: "no-store" });
  if (!res.ok) throw new Error(`manifest fetch failed (${res.status}) from ${manifestUrl}`);
  const manifest = await res.json();

  await fs.mkdir(outDir, { recursive: true });
  const characters = manifest.characters || [];
  let pulled = 0;
  for (const entry of characters) {
    if (!entry.identity || !["generated", "existing"].includes(entry.status)) continue;
    const url = `${apiBase}/media/character-bank/files/${entry.identity}`;
    const target = path.join(outDir, entry.identity);
    const r = await fetch(url);
    if (!r.ok) {
      console.warn(`  skip ${entry.identity} (${r.status})`);
      continue;
    }
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, Buffer.from(await r.arrayBuffer()));
    pulled += 1;
    console.log(`  pulled ${entry.identity}`);
  }

  await fs.writeFile(path.join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
  console.log(`Done: ${pulled}/${characters.length} identities into ${path.relative(REPO_ROOT, outDir)}`);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
