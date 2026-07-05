"""CLI: run a full debate and print/lock the transcript.

  python -m youvsmany.cli --topic "Pineapple belongs on pizza" --seed 0
"""

from __future__ import annotations

import argparse
import json

from youvsmany.adapters.factory import build_provider
from youvsmany.agents import orchestrator
from youvsmany.config import get_settings
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import Stance, TopicKind
from youvsmany.evals.metrics import score_episode
from youvsmany.store import EpisodeStore


def main() -> None:
    p = argparse.ArgumentParser(description="You Vs Many debate runner")
    p.add_argument("--topic", default="Pineapple belongs on pizza")
    p.add_argument("--stance", choices=[s.value for s in Stance], default="for")
    p.add_argument("--duration", type=int, default=90)
    p.add_argument("--challengers", type=int, default=3)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--factual", action="store_true", help="treat topic as factual (source brief)")
    p.add_argument("--tags", nargs="*", default=None, help="suggested contention tags")
    p.add_argument("--save", action="store_true", help="persist to the run store")
    p.add_argument("--json", action="store_true", help="print the full episode JSON")
    args = p.parse_args()

    brief = ShowBrief(
        topic=args.topic,
        protagonist_position=Stance(args.stance),
        target_duration_s=args.duration,
        num_challengers=args.challengers,
        topic_kind=TopicKind.FACTUAL if args.factual else TopicKind.OPINION,
        seed=args.seed,
    )
    provider = build_provider()
    ep = orchestrator.run_full(brief, provider=provider, suggested_tags=args.tags)

    if args.json:
        print(ep.model_dump_json(indent=2))
        return

    print(f"Episode {ep.episode_id}  [{ep.run_report.provider}:{ep.run_report.model}]")
    print(f"Topic: {ep.brief.topic}  | state={ep.state.value}  approved={ep.approved}")
    print(f"Cast: {', '.join(f'{c.display_name}({c.contention_tag})' for c in ep.cast.all_speakers())}")
    print("-" * 72)
    for t in ep.transcript.turns:
        print(f"[{t.turn_id} {t.start_s:6.1f}s {t.state.value:14s} {t.scene_cue:16s}] "
              f"{t.speaker_name}: {t.text}")
    print("-" * 72)
    print(f"Duration: {ep.transcript.total_duration_s}s   Turns: {len(ep.transcript.turns)}")
    print(f"Highlights ({len(ep.highlights)}):")
    for h in ep.highlights:
        print(f"  {h.start_turn_id}->{h.end_turn_id} {h.duration_s:.1f}s "
              f"tag={h.contention_tag} score={h.score.total}")

    sm = ep.scene_manifest
    if sm is not None:
        print("-" * 72)
        print(f"Scene manifest: {len(sm.segments)} segments · {len(sm.audio)} audio cues · "
              f"{sm.total_duration_s}s · 9:16 safe={sm.crop_safe_9x16}")
        print(f"Voices: {', '.join(f'{k}={v}' for k, v in sm.voice_map.items())}")
        for s in sm.segments:
            print(f"  [{s.segment_id} {s.start_s:6.1f}-{s.end_s:6.1f}s "
                  f"{s.camera.shot.value:17s} {s.animation_tag.value:14s} "
                  f"{s.visual_priority.value:8s}] {s.speaker_id}")
    print("Metrics:", json.dumps(score_episode(ep).model_dump(), indent=2))

    if args.save:
        path = EpisodeStore(get_settings().run_dir).save(ep)
        print(f"saved -> {path}")


if __name__ == "__main__":
    main()
