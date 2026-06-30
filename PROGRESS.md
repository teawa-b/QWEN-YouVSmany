# You Vs Many — Build Progress

A living tracker of which implementation phase we're in and how many remain.
Phases follow the project blueprint (chapter 11). Update this as each exit
criterion is met.

> **Stack decisions (override the blueprint where noted):**
> - **Renderer: Three.js** (not Unity). The scene contract is renderer-neutral, so
>   nothing in the pipeline binds to a specific engine.
> - **Premade studio sets (glTF/GLB), not procedural.** The Stage Director picks
>   one of a small library of art-directed sets; Three.js *loads* the set rather
>   than building a stage at runtime. Character marks are fit to the cast inside
>   each set's stage bounds.
> - **Voice/TTS: a Qwen Cloud TTS model** (via DashScope), assembled into the
>   master audio timeline before any 3D/video work.

## Phase status

**8 phases total (Phase 0 → Phase 7). 2 complete, currently in Phase 2 → 5 phases remain after this one.**

| Phase | Name | Target dates | Status |
|------:|------|--------------|--------|
| 0 | Foundation & scope lock | 24 Jun | ✅ Done |
| 1 | Debate intelligence | 25–27 Jun | ✅ Done |
| 2 | Audio, stage & capture | 28–30 Jun | 🔨 **In progress** |
| 3 | Still conversion & identity | 1–2 Jul | ⬜ Not started |
| 4 | Video transformation A/B | 2–4 Jul | ⬜ Not started |
| 5 | Continuity loop & shorts | 4–6 Jul | ⬜ Not started |
| 6 | Integration & evaluation | 6–7 Jul | ⬜ Not started |
| 7 | Submission assets & code freeze | 7–8 Jul | ⬜ Not started |

Legend: ✅ done · 🔨 in progress · ⬜ not started

## Phase 2 — Audio, stage & capture (current)

**Objective:** a publishable base episode (Three.js + real TTS audio) before
relying on generative video. Exit criterion: a complete base 3D episode that
could be submitted as a fallback.

Sub-tasks:
- [x] Renderer-neutral **scene contract** schema (§5.2) — per-segment time, speaker,
      dialogue, emotion, camera, blocking, animation tag, cast, visual priority,
      short-candidate flag.
- [x] **Stage director** adapter: LOCKED transcript → `SceneManifest`
      (stage layout, camera anchors, animation grammar, master audio timeline).
- [x] **Animation grammar** mapping (§5.4) — the six reusable states.
- [x] **TTS adapter** interface + offline mock (deterministic durations) so the
      timeline builds without network; **Qwen Cloud TTS** adapter for live audio.
- [x] **Premade scene-template registry** — deterministic set selection, cast
      bound to marks inside the set, manifest references the `.glb` asset.
- [x] Placeholder `.glb` studio sets generated (`frontend/assets/scenes/` —
      simple primitive geometry, real loadable binaries, sized to stage bounds).
      Swap-in-place for final art later; no code changes needed.
- [ ] Confirm the exact Qwen Cloud TTS model id + voice ids (currently env-driven,
      defaults to `qwen-tts`).
- [ ] **Three.js scene player** that loads the chosen premade set and drives it
      from the manifest (marks, camera cuts, visemes from the master audio).
- [ ] **Capture**: full base edit, per-segment shot clips, hero stills.
- [ ] **Tests**: speaker timing, camera correctness, 9:16 crop safety,
      deterministic replay from the manifest.

## What's done (Phase 1 recap)

- Multi-agent debate engine: brief → safety gate → cast → private notes →
  director plan → debate state machine → LOCKED transcript → highlights.
- Cast is **1 protagonist + N challengers** (no moderator voice); the
  "voted-out" gavel and closing handoff render as non-spoken captions.
- Each duel is a real multi-pass back-and-forth, depth scaled to the turn budget.
- 5-seed eval with contention-uniqueness / repetition / persona / duration metrics
  vs a single-agent baseline.
