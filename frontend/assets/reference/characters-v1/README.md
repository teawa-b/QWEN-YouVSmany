# Persistent Character Identity Bank (characters-v1)

Photoreal identity portraits for the fixed character roster defined in
`backend/src/youvsmany/media/characters.py` (`CHARACTER_ROSTER`). Each roster
member gets **one** image, generated **once** with Qwen Image Edit Max, and is
then reused by every episode:

- The stage director deterministically casts roster members onto each
  episode's speakers (`scene.character_refs`, gender-matched, seed-varied), so
  no new identities are ever generated per run — the pipeline just reads
  `<roster_id>/identity.png` from this bank.
- Every generation prompt embeds the same canonical studio-room description
  (`media/studio.py` / `STUDIO_SCENE` in `index.html`), so all characters sit
  in the same room.

## Generate the bank (one-time, needs a Qwen/DashScope key on the backend)

```bash
curl -X POST https://your-backend-domain.up.railway.app/media/character-bank/generate \
  -H "Content-Type: application/json" \
  -d '{"background": true, "overwrite": false}'
# poll: GET /media/character-bank/jobs/<job_id>
```

## Persist it into the repo (survives Railway redeploys)

```bash
cd frontend
npm run pull:character-bank -- --api https://your-backend-domain.up.railway.app
```

Layout after generation:

```text
characters-v1/
  manifest.json
  atlas/identity.png
  vega/identity.png
  ...one folder per roster_id
```

A re-run with `"overwrite": false` only fills characters that are missing or
previously failed, so moderation hiccups can be retried cheaply.
