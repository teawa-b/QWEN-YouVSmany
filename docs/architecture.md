# Architecture - 30-second AI showrunner

```text
ShowBrief -> Topic Producer -> safety/factuality gate -> SourceBrief if factual
                |
                v  create_episode(): BRIEFED
        Live Qwen Showrunner
                |  one schema-validated production call
                |  cast + two pressure angles + seven-beat script
                v  apply_draft(): PREPARING -> LOCKED
  OPENING -> CONTENTIONS -> RAPID_REBUTTAL -> CLOSING -> LOCKED
        fixed speaker grammar | distinct angles | complete 8-10 word lines
                |
                v  lock_episode()
        Clip Curator -> diversified highlight candidates
                |
                v  stage_episode()
        Stage Director -> SceneManifest (renderer-neutral, Three.js)
                |         camera anchors | animation grammar
                |         Qwen CosyVoice master audio timeline
                v
        HappyHorse video edit -> FFmpeg stitch -> vertical final cut
```

The deterministic offline path retains the granular character builder, private
strategies, director-controlled state machine, repetition guard, dominance cap
and compact per-speaker memory. It is used for regression and multi-agent
evaluation without adding twelve serial cloud calls to the creator-facing run.
Both paths hydrate the same `Cast`, `RoundPlan`, `Transcript` and
`SceneManifest` contracts.

## Why the structure

- **Schema at every handoff.** Pydantic rejects malformed model output before it
  reaches staging or media generation.
- **Cheap before expensive.** Safety and factuality checks run before Qwen,
  CosyVoice or HappyHorse work begins.
- **Fast live, inspectable offline.** Qwen coordinates cast and script in one
  production call; the mock path keeps the granular simulation testable.
- **Locked transcript is the spine.** Timings, stable IDs and scene cues freeze
  at LOCK, and every downstream asset inherits them.

## State machine

| State | What happens | Exit |
|---|---|---|
| BRIEFED | Topic, safety, cast count and runtime are fixed | Fields validate |
| PREPARING | Qwen casts the room and selects two distinct angles | Draft validates |
| OPENING | The lead hooks the viewer and lands the shared claim | Claim card lands |
| CONTENTIONS | Both challengers pressure the claim and the lead answers | Room exchange lands |
| RAPID_REBUTTAL | One direct follow-up and answer | Seven-beat budget reached |
| CLOSING | The lead closes on the unresolved core | Complete final sentence |
| LOCKED | Transcript, timecodes, cues and highlights are versioned | Gate approves |

The product contract is enforced at every boundary: `ShowBrief` accepts only
20-30 seconds and at most two challengers; every spoken beat is 8-10 words; the
scene director stops at 30 seconds; the video API accepts at most seven
segments; and HappyHorse/Wan stitches receive a final FFmpeg `-t 30` guard.
