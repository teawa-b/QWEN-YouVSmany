"""End-to-end Phase 1 orchestration: brief -> prepare -> debate -> lock.

Cheap-and-deterministic before expensive-and-generative: the safety gate and
(for factual topics) the source brief run first; then cast, private notes and
plan; then the debate state machine; then highlight detection at LOCK."""

from __future__ import annotations

import uuid

from youvsmany.adapters.base import Provider
from youvsmany.adapters.factory import build_provider, build_tts_provider
from youvsmany.adapters.tts_base import TTSProvider
from youvsmany.agents import character_builder, director, stage_director, topic_producer
from youvsmany.agents.highlights import detect_highlights
from youvsmany.agents.state_machine import DebateRunner
from youvsmany.contracts.brief import ShowBrief
from youvsmany.contracts.enums import DebateState
from youvsmany.contracts.episode import Episode


class SafetyRejected(RuntimeError):
    pass


def create_episode(brief: ShowBrief, *, provider: Provider | None = None) -> Episode:
    provider = provider or build_provider()
    ep = Episode(episode_id=f"ep_{uuid.uuid4().hex[:8]}", brief=brief)
    ep.run_report.provider = provider.name
    ep.run_report.model = provider.model

    # 1. Safety / factuality gate (blueprint 3.1).
    ep.safety = topic_producer.safety_gate(brief)
    ep.run_report.events.append(f"safety: allowed={ep.safety.allowed}")
    if not ep.safety.allowed:
        raise SafetyRejected("; ".join(ep.safety.reasons))
    if ep.safety.requires_source_brief:
        sb, it, ot, r = topic_producer.build_source_brief(provider, brief, seed=brief.seed)
        ep.source_brief = sb
        _account(ep, it, ot, r, calls=1)
    return ep


def prepare_episode(
    ep: Episode, *, provider: Provider | None = None, suggested_tags: list[str] | None = None
) -> Episode:
    provider = provider or build_provider()
    _require_state(ep, DebateState.BRIEFED)
    ep.state = DebateState.PREPARING

    cast, it, ot, r = character_builder.build_cast(
        provider, ep.brief, suggested_tags=suggested_tags, seed=ep.brief.seed
    )
    ep.cast = cast
    _account(ep, it, ot, r, calls=1)

    it, ot, r = character_builder.attach_private_notes(provider, ep.brief, cast, seed=ep.brief.seed)
    _account(ep, it, ot, r, calls=len(cast.challengers) + 1)

    plan, it, ot, r = director.build_round_plan(provider, ep.brief, cast, seed=ep.brief.seed)
    ep.plan = plan
    _account(ep, it, ot, r, calls=1)
    ep.run_report.events.append("prepared cast, private notes and round plan")
    return ep


def run_debate(ep: Episode, *, provider: Provider | None = None) -> Episode:
    provider = provider or build_provider()
    _require_state(ep, DebateState.PREPARING)
    runner = DebateRunner(provider, ep)
    return runner.run()  # advances through to LOCKED


def lock_episode(ep: Episode) -> Episode:
    """Detect highlights on the frozen transcript and mark approved if the exit
    criterion is met (blueprint 11.2)."""
    if ep.state != DebateState.LOCKED:
        raise ValueError(f"cannot lock from state {ep.state}")
    ep.highlights = detect_highlights(ep.transcript, top_k=2)
    ep.approved = exit_criterion_met(ep)
    ep.run_report.events.append(
        f"locked: {len(ep.transcript.turns)} turns, {ep.transcript.total_duration_s}s, "
        f"{len(ep.highlights)} highlights, approved={ep.approved}"
    )
    return ep


def stage_episode(ep: Episode, *, tts: TTSProvider | None = None) -> Episode:
    """Phase 2: build the renderer-neutral scene manifest + master audio timeline
    from the LOCKED transcript (blueprint 5.2-5.6)."""
    if ep.state != DebateState.LOCKED:
        raise ValueError(f"cannot stage from state {ep.state}")
    tts = tts or build_tts_provider()
    ep.scene_manifest = stage_director.build_scene_manifest(ep, tts)
    ep.run_report.events.append(
        f"staged: {len(ep.scene_manifest.segments)} segments, "
        f"{ep.scene_manifest.total_duration_s}s audio timeline [{tts.name}]"
    )
    return ep


def run_full(
    brief: ShowBrief,
    *,
    provider: Provider | None = None,
    suggested_tags=None,
    tts: TTSProvider | None = None,
) -> Episode:
    provider = provider or build_provider()
    ep = create_episode(brief, provider=provider)
    prepare_episode(ep, provider=provider, suggested_tags=suggested_tags)
    run_debate(ep, provider=provider)
    lock_episode(ep)
    stage_episode(ep, tts=tts)
    return ep


def exit_criterion_met(ep: Episode) -> bool:
    """One approved short-form debate with stable turn IDs, scene cues and
    highlight candidates (blueprint 11.2 exit criterion)."""
    t = ep.transcript
    dur_ok = 20.0 <= t.total_duration_s <= 30.0
    turns_ok = 6 <= len(t.turns) <= 7
    ids_ok = len({x.turn_id for x in t.turns}) == len(t.turns) and all(x.scene_cue for x in t.turns)
    highlights_ok = len(ep.highlights) >= 2
    return dur_ok and turns_ok and ids_ok and highlights_ok


def _require_state(ep: Episode, expected: DebateState) -> None:
    if ep.state != expected:
        raise ValueError(f"expected state {expected}, got {ep.state}")


def _account(ep: Episode, it: int, ot: int, retries: int, *, calls: int) -> None:
    ep.run_report.input_tokens += it
    ep.run_report.output_tokens += ot
    ep.run_report.retries += retries
    ep.run_report.llm_calls += calls
