# Reference Asset Banks

Pre-rendered starter images and silent motion clips for image/video guided
generation. Banks are vertical 9:16 so they can be used directly for short-form
footage without cropping from a landscape render.

## vertical-v1

- 3 intro/establishing references.
- 4 speaking angles for each speaker slot: `close`, `medium`, `profile`,
  `over_table`.
- 4 slots: `main_speaker`, `second_speaker`, `third_speaker`,
  `fourth_speaker`.
- Each shot folder contains:
  - `starter.png`: image prompt/reference frame.
  - `clip.webm`: silent speaking or idle motion reference.
- `manifest.json` maps every slot/angle to its files.

Regenerate from the running frontend:

```bash
npm run capture:refs
```

## realistic-v1

Realistic Qwen Image Edit Max pass generated from `vertical-v1`.

Each generated image uses the matching 9:16 starter frame as the composition
reference. Generation runs in two phases: intros and each speaker's `close`
shot first, then the remaining angles. Once a speaker's realistic `close`
image exists it becomes the identity anchor for that speaker's other angles,
so consistency is locked to a generated photo instead of the stylized starter.

Robustness:

- Prompts avoid DashScope moderation false-positive terms and run with
  `prompt_extend` off; a `DataInspectionFailed` rejection retries once with a
  plain fallback prompt.
- Throttling and transient errors retry with exponential backoff, so the
  fixed inter-shot delay is small (2s) instead of 33s.
- A shot that still fails is recorded in the manifest (`status: "failed"`)
  and the run continues. The manifest is rewritten after every shot, so
  partial banks are served immediately and re-running the same command (no
  `--overwrite`) retries only the missing shots.

Plan prompts without API calls:

```bash
npm run generate:realistic-refs -- --dry-run
```

Generate with Qwen Cloud:

```bash
QWEN_API_KEY=sk-... npm run generate:realistic-refs
```

Or generate through the hosted backend, which keeps the Qwen key server-side:

```bash
curl -X POST https://your-backend-domain.up.railway.app/media/realistic-refs/generate \
  -H "Content-Type: application/json" \
  -d '{"background":true}'
```

Poll the returned `job.job_id` at
`/media/realistic-refs/jobs/{job_id}`. The generated manifest is served from
`/media/realistic-refs/manifest.json`, and images are served from
`/media/realistic-refs/files/`.

## HappyHorse video edit

The app's episode page builds a HappyHorse-style payload per conversation
segment:

- source video: the matching 9:16 speaker motion clip
- reference images: speaker identity and angle references
- model: `happyhorse-1.0-video-edit`
- output target: vertical `9:16`, `720P`/`1080P`

Local mock playback uses the checked-in WebM clips so the flow can be reviewed
without spending generation credits. A live HappyHorse call requires public or
OSS-accessible media URLs; localhost asset URLs are only for the browser mock.

Export the local mock conversation to a vertical WebM:

```bash
npm run export:mock-video
```

Dry-run a single live payload:

```bash
npm run generate:happyhorse-video -- --dry-run --video-url=https://example.com/source.mp4 --reference-image=https://example.com/speaker.png
```

Submit a real task:

```bash
QWEN_API_KEY=sk-... npm run generate:happyhorse-video -- --video-url=https://example.com/source.mp4 --reference-image=https://example.com/speaker.png --out=output/happyhorse/segment.mp4
```
