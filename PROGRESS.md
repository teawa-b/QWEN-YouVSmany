# You Vs Many - Build Progress

A living tracker of which implementation phase we're in and how many remain.
Phases follow the project blueprint (chapter 11). Update this as each exit
criterion is met.

> **Stack decisions (override the blueprint where noted):**
> - **Renderer: Three.js** (not Unity). The scene contract is renderer-neutral, so
>   nothing in the pipeline binds to a specific engine.
> - **Premade studio sets (glTF/GLB), not procedural.** The Stage Director picks
>   one of a small library of art-directed sets; Three.js loads the set rather
>   than building a stage at runtime. Character marks are fit to the cast inside
>   each set's stage bounds.
> - **Voice/TTS: Qwen Cloud CosyVoice** (via DashScope), assembled into the
>   master audio timeline before any 3D/video work.

## Phase Status

**8 phases total (Phase 0 -> Phase 7). 2 complete, currently in Phase 2 -> 5 phases remain after this one.**

| Phase | Name | Target dates | Status |
|------:|------|--------------|--------|
| 0 | Foundation & scope lock | 24 Jun | Done |
| 1 | Debate intelligence | 25-27 Jun | Done |
| 2 | Audio, stage & capture | 28-30 Jun | In progress |
| 3 | Still conversion & identity | 1-2 Jul | Not started |
| 4 | Video transformation A/B | 2-4 Jul | Not started |
| 5 | Continuity loop & shorts | 4-6 Jul | Not started |
| 6 | Integration & evaluation | 6-7 Jul | Not started |
| 7 | Submission assets & code freeze | 7-8 Jul | Not started |

## Phase 2 - Audio, Stage & Capture (Current)

**Objective:** a publishable base episode (Three.js + real TTS audio) before
relying on generative video. Exit criterion: a complete base 3D episode that
could be submitted as a fallback.

Sub-tasks:
- [x] Renderer-neutral **scene contract** schema (section 5.2): per-segment time,
      speaker, dialogue, emotion, camera, blocking, animation tag, cast, visual
      priority, short-candidate flag.
- [x] **Stage director** adapter: LOCKED transcript -> `SceneManifest`
      (stage layout, camera anchors, animation grammar, master audio timeline).
- [x] **Animation grammar** mapping (section 5.4): the six reusable states.
- [x] **TTS adapter** interface + offline mock (deterministic durations), with
      live **Qwen Cloud CosyVoice** support via DashScope.
- [x] Confirmed CosyVoice model/voices: `cosyvoice-v3-plus`, `longanyang` for
      male-presenting speakers and `longanhuan` for female-presenting speakers.
- [x] **Premade scene-template registry**: deterministic set selection, cast
      bound to marks inside the set, manifest references the `.glb` asset.
- [x] Placeholder `.glb` studio sets generated in `frontend/assets/scenes/`.
      Swap-in-place for final art later; no code changes needed.
- [x] **Three.js scene player** (`frontend/scene3d.js`): drives the manifest live
      with seated Mixamo characters, camera cuts, per-segment talking animation,
      captions, a 9:16 crop guide, browser/CosyVoice audio playback, and CC0
      table/chair props.
- [x] **Male/female character split**: Y Bot is used for male-presenting
      speakers and X Bot for female-presenting speakers. Both share Mixamo's
      canonical local bone-rotation convention with the seated idle/talking
      clips (authored for Remy), so those clips replay directly on either rig;
      only the hip *position* track is rescaled (Remy's raw units run ~2x
      larger than X/Y Bot's). Their bundled "*_Joints" debug mesh is removed
      at load time (duplicate bone names otherwise make animation binding
      ambiguous), and the mixer targets the whole cloned model, not the
      SkinnedMesh alone, so it can resolve tracks by bone name.
- [x] **Dialogue flow upgrade**: one shared claim with room crossfire, rotating
      challenger follow-ups, and no repeated one-on-one voted-out segments.
- [x] **Close-up camera framing**: seated head height is measured from the
      Mixamo head bone instead of the animated bounding box (raised hands were
      inflating the target), and close shots now frame the visible upper body.
- [x] **Backend tests**: 30 tests passing for state machine, scene contract,
      voice mapping, determinism, schemas, safety and metrics.
- [x] **9:16 reference asset bank**: starter images and silent speaking-angle
      clips for intro, main speaker, second speaker, third speaker and fourth
      speaker slots, so image/video guided generation can keep characters
      consistent from scene to scene. Current bank lives at
      `frontend/assets/reference/vertical-v1/` with 19 PNG/WebM references.
- [x] **Realistic character reference bank**: Qwen Image Edit Max pass that
      converts the 9:16 starter frames into photorealistic debate-show images
      while preserving speaker identity across all angles. Generated live on
      Railway (18/19 shots; one profile angle persistently trips DashScope
      moderation on the input frame and falls back to the starter). Generation
      is parallelized by dependency tier with retry/backoff and partial-bank
      resumption; `npm run pull:realistic-refs` downloads the generated bank
      into `frontend/assets/reference/realistic-v1/` so it survives Railway's
      ephemeral redeploys and the app serves it with no backend dependency.
- [x] **HappyHorse video-edit assembly**: live Qwen Cloud generation is wired.
      The backend converts each starter clip to MP4, serves it plus the
      identity reference image as DashScope-fetchable URLs, submits per-segment
      `happyhorse-1.0-video-edit` tasks (async create -> poll, bounded
      concurrency, retry/backoff), muxes per-segment TTS audio, and stitches
      the finished segments into `conversation.mp4` with ffmpeg. Exposed at
      `/media/video-edit/*`; the web app's "Live HappyHorse generation" step
      drives it and plays the result. The local mock preview and WebM export
      remain as an offline fallback.
- [x] Drive the studio-set `.glb` itself (not just procedural/themed floor).
      The Three.js player now loads `scene_template.asset_url`, mounts the
      selected premade set, and hides the fallback floor once the set is live.
- [x] Add audio-reactive speech motion from the master audio. CosyVoice clips
      are attached to a Web Audio analyser when available; the active speaker's
      talk animation, jaw/head motion and subtle body pulse follow the live
      audio envelope, with a synthetic fallback for browser speech playback.
- [ ] **Capture**: full base edit, per-segment shot clips, hero stills.
- [x] **Visual QA tests**: `npm run visual:qa` mounts the manifest-driven
      Three.js player in a browser, verifies the studio `.glb` loaded, checks a
      nonblank 9:16-safe canvas, validates the local realistic bank, and writes
      a screenshot under `output/playwright/`.

## What's Done (Phase 1 Recap)

- Multi-agent debate engine: brief -> safety gate -> cast -> private notes ->
  director plan -> debate state machine -> LOCKED transcript -> highlights.
- Cast is **1 protagonist + N challengers** (no moderator voice).
- Debate now runs as a shared-room crossfire instead of separate isolated duels.
- 5-seed eval with contention-uniqueness / repetition / persona / duration
  metrics vs a single-agent baseline.
