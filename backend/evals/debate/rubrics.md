# Debate evaluation rubrics (Phase 1)

These back the automated metrics in `youvsmany.evals.metrics` and the 5-seed
suite in `youvsmany.evals.run_seeds` (blueprint §11.2, §12).

| Metric | Definition | Good | Why it matters |
|---|---|---|---|
| **Contention uniqueness** | `1 − mean pairwise similarity` of challenger objections, with the shared proposition words removed | higher | Proves challengers differ in *substance*, not just name (blueprint §4.2). |
| **Repetition** | mean of each turn's max similarity to any earlier turn | lower | The moderator's repetition rule should keep the debate moving (§4.5). |
| **Persona adherence** | fraction of turns inside the speaker's declared word-length range | higher | Private notes set a response style each agent should hold (§4.3). |
| **Duration in target** | locked dialogue lands in 60–120 s | true | MVP episode length (§3.3). |
| **Approved (exit criterion)** | LOCKED, 12–24 turns, unique stable turn IDs, scene cues present, ≥3 highlight candidates | true | Phase 1 exit criterion (§11.2). |

## Multi-agent vs single-agent baseline (§4.8)

The suite runs the same topic/length through the multi-agent pipeline and a
single-agent baseline (one model writes the whole script in one pass, no private
information, no moderator control). The multi-agent system should win on
uniqueness, repetition and persona adherence.

Numbers produced by the **mock** provider are deterministic stand-ins; the same
harness scores real `qwen3.7-plus` output unchanged by setting `YVM_PROVIDER=qwen`.
