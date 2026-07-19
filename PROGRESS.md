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
> - **Short-form product lock:** every episode is 1 lead + 2 challengers, at
>   most 7 beats, vertical 9:16, and never longer than 30 seconds. The ceiling
>   is enforced by the brief schema, transcript, scene timeline, render API,
>   and final FFmpeg stitch.

## 2026 AI Showrunner polish pass

- [x] Reframed the product from a debate dashboard into a one-click showrunner:
      brief -> script -> cast -> direct -> render -> download.
- [x] Replaced the equal-card neon home screen with an editorial, cinematic
      creator experience and a clear format promise.
- [x] Reduced the cast to three total voices and the story to seven beats so
      the output remains readable at short-form pace.
- [x] Added strict 30-second validation and render trimming at every boundary.
- [x] Made the final 9:16 cut the primary result, with preview, render, playback,
      and MP4 download controls in one workspace.
- [x] Replaced the production path's serial per-character/per-turn Qwen calls
      with one schema-validated showrunner pass that casts and scripts all seven
      beats together; the granular multi-agent path remains for offline evals.
- [x] Preserved a verified 23.19-second, 1080x1920 HappyHorse reviewer cut in
      the deployed Examples screen so it survives backend restarts.
- [x] Backend regression suite: **68 tests passing**.

## Phase Status

**8 phases total (Phase 0 -> Phase 7). Implementation plumbing is complete through Phase 7.**

| Phase | Name | Target dates | Status |
|------:|------|--------------|--------|
| 0 | Foundation & scope lock | 24 Jun | Done |
| 1 | Debate intelligence | 25-27 Jun | Done |
| 2 | Audio, stage & capture | 28-30 Jun | Done |
| 3 | Still conversion & identity | 1-2 Jul | Done |
| 4 | Video transformation A/B | 2-4 Jul | Done |
| 5 | Continuity loop & shorts | 4-6 Jul | Done |
| 6 | Integration & evaluation | 6-7 Jul | Done |
| 7 | Submission assets & code freeze | 7-8 Jul | Done |

## Phase 2 - Audio, Stage & Capture

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
- [x] **Backend tests**: 68 tests passing for showrunner coordination, provider
      request mode, state machine, scene contract, voice mapping, determinism,
      schemas, safety and metrics.
- [x] **9:16 reference asset bank**: starter images and silent speaking-angle
      clips for intro, main speaker, second speaker and third speaker slots
      (plus legacy fourth-speaker references), so image/video guided generation can keep characters
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
- [x] **Capture**: `npm run package:episode` creates a full deliverable bundle
      from a locked episode: base edit WebM, per-segment shot clips, hero
      stills, short candidates, episode JSON, scene manifest, metrics, package
      manifest, and a local review page.
- [x] **Visual QA tests**: `npm run visual:qa` mounts the manifest-driven
      Three.js player in a browser, verifies the studio `.glb` loaded, checks a
      nonblank 9:16-safe canvas, validates the local realistic bank, and writes
      a screenshot under `output/playwright/`.

## Phase 3 - Still Conversion & Identity

- [x] Qwen Image Edit Max realistic-reference generation is wired on the
      backend and can be run safely as resumable background jobs.
- [x] The generated realistic reference bank is persisted into
      `frontend/assets/reference/realistic-v1/` so redeploys do not wipe
      identity assets.
- [x] The frontend prefers the local realistic bank and falls back to starter
      frames or backend refs when needed.
- [x] **Canonical studio scene**: every image/video prompt embeds the same
      studio-room description (`media/studio.py`, mirrored in `index.html`
      with a sync test), so all characters and shots render in the same room.
- [x] **Persistent character roster**: 12 varied reusable panelists with
      stable seeds (`media/characters.py`). The stage director casts them
      deterministically per episode (`scene.character_refs`, gender-matched,
      seed-varied); identity images generate once via
      `POST /media/character-bank/generate` into a bank that ships in the repo
      (`characters-v1/`), so episodes reuse saved identities instead of
      generating new characters per run. Video-edit tasks anchor the face to
      the roster identity image when the bank exists.

## Phase 4 - Video Transformation

- [x] HappyHorse (`happyhorse-1.0-video-edit`) is the selected live Qwen Cloud
      route after the Wan/HappyHorse comparison work.
- [x] Backend video jobs convert WebM sources to MP4, build public media URLs,
      submit async DashScope tasks, poll, download, mux available audio, and
      stitch a conversation file with ffmpeg.
- [x] The frontend exposes live generation controls when the backend reports a
      configured Qwen key and ffmpeg.

## Phase 5 - Continuity Loop & Shorts

- [x] Segment identity is anchored by speaker-slot close references; missing
      realistic shots gracefully fall back to starter frames.
- [x] Package export emits short candidate clips from highlight windows and
      records the source segment ids in `package_manifest.json`.
- [x] **Realistic highlight shorts (cost-aware strategy)**: full-episode
      realistic generation proved too expensive per segment, so the product
      artifact is the highlight short. `POST /media/shorts/generate` renders
      only the hero (short-candidate) segments through audio-driven
      `wan2.6-i2v` at 720P — true lipsync from each speaker's roster identity
      image + CosyVoice line — hard-capped at `YVM_SHORT_SEGMENT_CAP`
      (default 3) clips per request, billed at the 5s tier when the line
      fits. Clips are stitched with native audio and burned speaker captions
      into `shorts/short.mp4`; the web app's step 5 drives it. The full
      episode remains the free 3D captioned edit. (Model shootout on the
      intl account: `wan2.2-s2v`/`emo-v1`/`wan2.7-i2v-plus` do not exist;
      `wan2.5-i2v-preview` and `wan2.6-i2v` do, with native audio lipsync —
      wan2.6 is sharper and 30fps, chosen as default.)

## Phase 6 - Integration & Evaluation

- [x] Backend test suite covers state machine, schemas, scene contract, media
      reference generation, and video-edit flow.
- [x] Browser visual QA checks 3D stage load, crop safety, realistic-bank
      availability, and media MIME types.
- [x] Package smoke run verifies locked episode generation, capture outputs,
      manifests, and the review page path.

## Phase 7 - Submission Assets & Code Freeze

- [x] `docs/submission-package.md` documents the final packaging workflow.
- [x] `npm run package:episode` writes submission-ready local artifacts under
      `output/submission/`.
- [x] README files now describe the current late-stage pipeline rather than the
      older Phase 1-only state.
- [x] Live Railway verification completed: `/health`, realistic refs, episode
      generation, HappyHorse segment generation, ffmpeg stitching, and
      `conversation.mp4` serving all pass against the hosted backend.

## What's Done (Phase 1 Recap)

- Multi-agent debate engine: brief -> safety gate -> cast -> private notes ->
  director plan -> debate state machine -> LOCKED transcript -> highlights.
- Cast is **1 protagonist + 2 challengers** (no moderator voice).
- Debate now runs as a shared-room crossfire instead of separate isolated duels.
- 5-seed eval with contention-uniqueness / repetition / persona / duration
  metrics vs a single-agent baseline.
