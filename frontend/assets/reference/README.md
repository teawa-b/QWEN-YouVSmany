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
reference. Speaker shots also use that speaker's `close` starter as the
identity anchor so the main, second, third and fourth speaker stay consistent
across their angles.

Plan prompts without API calls:

```bash
npm run generate:realistic-refs -- --dry-run
```

Generate with Qwen Cloud:

```bash
QWEN_API_KEY=sk-... npm run generate:realistic-refs
```

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
