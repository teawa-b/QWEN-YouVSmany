"""Run >=5 seeds and compare multi-agent vs single-agent baseline (blueprint 11.2)."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass

from youvsmany.adapters.factory import build_provider
from youvsmany.agents import orchestrator
from youvsmany.agents.baseline import run_baseline
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import Stance, TopicKind
from youvsmany.evals.metrics import DebateMetrics, score_episode


@dataclass
class SeedResult:
    seed: int
    multi: DebateMetrics
    baseline: DebateMetrics
    approved: bool


def run_suite(
    topic: str = "Pineapple belongs on pizza",
    *,
    seeds: int = 5,
    suggested_tags: list[str] | None = None,
    topic_kind: TopicKind = TopicKind.OPINION,
) -> list[SeedResult]:
    provider = build_provider()
    results: list[SeedResult] = []
    for seed in range(seeds):
        brief = ShowBrief(
            topic=topic,
            protagonist_position=Stance.FOR,
            topic_kind=topic_kind,
            seed=seed,
        )
        ep = orchestrator.run_full(brief, provider=provider, suggested_tags=suggested_tags)
        base = run_baseline(brief, provider=provider)
        results.append(
            SeedResult(
                seed=seed,
                multi=score_episode(ep),
                baseline=score_episode(base),
                approved=ep.approved,
            )
        )
    return results


def summarize(results: list[SeedResult]) -> dict:
    def mean(values):
        return round(statistics.mean(values), 4)

    multi = [r.multi for r in results]
    base = [r.baseline for r in results]
    return {
        "seeds": len(results),
        "approved_rate": mean([1.0 if r.approved else 0.0 for r in results]),
        "multi_agent": {
            "contention_uniqueness": mean([m.contention_uniqueness for m in multi]),
            "repetition": mean([m.repetition for m in multi]),
            "persona_adherence": mean([m.persona_adherence for m in multi]),
            "duration_s": mean([m.duration_s for m in multi]),
            "duration_in_target_rate": mean([1.0 if m.duration_in_target else 0.0 for m in multi]),
        },
        "single_agent_baseline": {
            "contention_uniqueness": mean([m.contention_uniqueness for m in base]),
            "repetition": mean([m.repetition for m in base]),
            "persona_adherence": mean([m.persona_adherence for m in base]),
        },
    }


def main() -> None:
    results = run_suite()
    summary = summarize(results)
    print(json.dumps(summary, indent=2))
    print("\nper-seed:")
    for r in results:
        print(
            f"  seed {r.seed}: approved={r.approved} "
            f"uniq={r.multi.contention_uniqueness} rep={r.multi.repetition} "
            f"persona={r.multi.persona_adherence} dur={r.multi.duration_s}s "
            f"| baseline uniq={r.baseline.contention_uniqueness} rep={r.baseline.repetition}"
        )


if __name__ == "__main__":
    main()
