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
