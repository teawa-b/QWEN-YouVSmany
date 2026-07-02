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
