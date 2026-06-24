# You Vs Many — AI Debate Showrunner

A multi-agent system that prepares and stages one-versus-many debates, converts
selected 3D scenes into realistic video, validates visual accuracy, and
publishes a full episode plus short-form clips. Built for the Qwen Cloud Global
AI Hackathon (AI Showrunner track).

> **The spine:** lock the argument → lock the audio → stage the scene → approve
> the still → generate the clip → validate the result → publish the moment.
> Cheap-and-deterministic before expensive-and-generative, with a structured,
> schema-validated artifact at every handoff.

This repository currently implements **Phase 1 — Debate Intelligence**
(blueprint §11.2): the text-only multi-agent layer that produces a complete,
coherent, *measurable* debate transcript with stable turn IDs, scene cues and
highlight candidates — **no 3D or media work**. Later phases (audio/staging,
still conversion, video transform, continuity loop, packaging) slot into the
same contracts and API.

## Topics are generated, not pre-baked

The starter menu (`data/starter_topics.json`) holds **starter prompts, not
pre-generated debates**. Selecting one runs the *exact same pipeline* as a
custom topic: new cast, new private notes, new plan, new dialogue, new scene
cues, new highlights — every run (blueprint §3.4). `"Pineapple belongs on pizza"`
is only the **demo seed**. Custom/factual topics first pass a **safety +
factuality gate**, and factual ones get a fixed **source brief** before agents
argue.

## What Phase 1 builds (blueprint §11.2)

- **Pydantic contracts** — every Qwen output is schema-validated before it can
  contaminate later stages (`src/youvsmany/contracts/`).
- **Topic Producer** — cheap deterministic safety/factuality gate + source brief
  for factual topics.
- **Character Builder + private notes** — 1 protagonist + N challengers + 1
  moderator; challengers differ in *substance* (distinct contention tags); each
  performer gets a **private** strategy packet others can't see.
- **Director** — round plan (opening → 3 contentions → rapid rebuttal → closing).
- **Debate state machine** — `BRIEFED → PREPARING → OPENING → CONTENTIONS →
  RAPID_REBUTTAL → CLOSING → LOCKED`, driven by a moderator control agent that
  picks the next speaker, kills repetition, caps dominance and forces disputed
  questions.
- **Shared memory** — rolling summary, unresolved claims, speaker stats; each
  agent sees only compact, role-specific context, never the whole transcript.
- **Clip Curator** — weighted highlight scoring over turn windows, diversified
  across contentions.
- **Transcript store** — versioned JSON snapshots so any episode is reproducible
  from its manifest.
- **FastAPI** — `POST /episodes`, `/prepare`, `/debate`, `/lock`, `GET /episodes/{id}`.
- **Eval harness** — ≥5 seeds scoring contention uniqueness, repetition, persona
  adherence and duration, vs a single-agent baseline.

## Model provider

The same code path runs against the live Qwen API **or** a deterministic offline
mock, selected by `YVM_PROVIDER`:

- `mock` (default) — schema-valid, reproducible, **no network**. Lets the whole
  pipeline + evals + tests run anywhere.
- `qwen` — OpenAI-compatible Qwen Cloud client (`qwen3.7-plus`) reading
  `QWEN_API_KEY` / `QWEN_BASE_URL` from the environment.

> Secrets live in `.env` (gitignored). Never commit a real key — see
> `.env.example`.

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Run a debate (offline mock provider)
python -m youvsmany.cli --topic "Pineapple belongs on pizza" \
    --tags texture tradition culinary-innovation --seed 0

# 5-seed evaluation: multi-agent vs single-agent baseline
python -m youvsmany.evals.run_seeds

# Tests
pytest -q

# API
uvicorn youvsmany.api.main:app --reload
```

### Run against live Qwen

```bash
cp .env.example .env          # then edit:
#   YVM_PROVIDER=qwen
#   QWEN_API_KEY=sk-ws-...
#   QWEN_BASE_URL=https://.../v1   (OpenAI-compatible chat endpoint)
```

## Sample output (mock, seed 0)

`samples/episode_pineapple_seed0.json` is a full locked episode manifest. A
typical run: 15 turns, ~91 s, approved, 3 highlight candidates across the
texture / tradition / innovation contentions. The 5-seed eval shows the
multi-agent system beating the single-agent baseline on every axis (higher
contention uniqueness, lower repetition, higher persona adherence).

## Layout

```
src/youvsmany/
  contracts/   Pydantic/JSON schemas (brief, cast, plan, transcript, memory, highlights, episode)
  adapters/    provider protocol, Qwen client, deterministic mock, structured-output helper
  agents/      topic producer, character builder, director, debaters, state machine, repetition, highlights, orchestrator, baseline
  store/        versioned episode store
  evals/        debate metrics + 5-seed suite
  api/          FastAPI orchestrator
data/           starter topic prompts
evals/debate/   rubrics
samples/        example locked episode manifest
tests/          pytest suite
```

## Roadmap

Phase 2 audio/staging → Phase 3 still conversion → Phase 4 video transform A/B →
Phase 5 continuity loop + shorts → Phase 6 integration/eval → Phase 7–8
submission (blueprint §11). The locked transcript produced here is the pivotal
artifact every downstream stage inherits.

## License

MIT — see `LICENSE`.
