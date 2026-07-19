# Architecture — 30-second AI showrunner

```
ShowBrief ─▶ Topic Producer ─▶ [safety/factuality gate] ─▶ (SourceBrief if factual)
                 │
                 ▼  create_episode()  state: BRIEFED
          Character Builder ─▶ Cast (1 protagonist + 2 challengers)
                 │              each challenger: distinct contention_tag (substance)
                 ▼  prepare_episode()  state: PREPARING
          Private notes (per performer, hidden)  +  Director round plan
                 │
                 ▼  run_debate()  — director-driven state machine
   OPENING ─▶ CONTENTIONS ─▶ RAPID_REBUTTAL ─▶ CLOSING ─▶ LOCKED
        director control: next speaker · repetition kill · dominance cap · disputed question
        room crossfire: one shared claim card · rotating challenger follow-ups (no per-duel voted-out resets)
        memory: rolling summary · unresolved claims · speaker stats (compact context only)
                 │
                 ▼  lock_episode()  state: LOCKED
          Clip Curator ─▶ highlight candidates (weighted, diversified)
                 │
                 ▼  stage_episode()  — Phase 2
          Stage Director ─▶ SceneManifest (renderer-neutral, Three.js)
                 │           stage layout · camera anchors · animation grammar
                 │           master audio timeline (Qwen Cloud TTS, mock offline)
                 ▼
          Episode manifest (versioned JSON)  ──▶  Phase 3+ (stills, video, media)
```

## Why the structure

- **Schema at every handoff.** Each stage validates its input against a Pydantic
  contract, so a malformed model response is rejected before it reaches the next
  stage (`adapters/base.complete_structured`).
- **Cheap before expensive.** The safety gate and source brief run first; nothing
  generative happens for a disallowed topic.
- **Provider-agnostic.** Agents depend only on the `Provider` protocol. The mock
  and Qwen backends are interchangeable, so the pipeline is testable offline and
  identical in shape to the production path.
- **Locked transcript is the spine.** Timings, turn IDs and scene cues are frozen
  at LOCK; every downstream asset will inherit them.

## State machine

| State | What happens | Exit |
|---|---|---|
| BRIEFED | topic, safety, cast count, runtime fixed | fields validate |
| PREPARING | private notes + round plan | contentions unique & covered |
| OPENING | protagonist hooks the viewer and states the shared claim | one claim card lands |
| CONTENTIONS | both challengers pressure the claim, the lead answers, then one follow-up pair lands | seven-beat budget reached |
| RAPID_REBUTTAL | pass-through safety state; only repairs an unexpectedly short run | six-turn floor |
| CLOSING | protagonist closing line | target duration reached |
| LOCKED | transcript, timecodes, cues, highlights versioned | gate approves |
```

The product contract is enforced at every boundary: `ShowBrief` accepts only
20–30 seconds and at most two challengers; dialogue is capped to 10 words per
beat; the scene director stops at 30 seconds; the video API accepts at most
seven segments; and both HappyHorse and Wan stitches receive a final FFmpeg
`-t 30` guard.
