"""The episode aggregate — the versioned artifact handed between stages.

Phase 1 fills everything up to and including the LOCKED transcript, scene cues
and highlight candidates (blueprint 11.2 exit criterion)."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from youvsmany.contracts.brief import SafetyReport, ShowBrief, SourceBrief
from youvsmany.contracts.character import Cast
from youvsmany.contracts.enums import DebateState
from youvsmany.contracts.highlights import HighlightCandidate
from youvsmany.contracts.memory import EpisodeMemory
from youvsmany.contracts.plan import RoundPlan
from youvsmany.contracts.scene import SceneManifest
from youvsmany.contracts.transcript import Transcript


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunReport(BaseModel):
    """Lightweight provenance + cost record (blueprint Definition of Done)."""

    provider: str = "mock"
    model: str = ""
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    events: list[str] = Field(default_factory=list)


class Episode(BaseModel):
    episode_id: str
    version: int = 1
    created_at: str = Field(default_factory=_now)
    state: DebateState = DebateState.BRIEFED

    brief: ShowBrief
    safety: SafetyReport | None = None
    source_brief: SourceBrief | None = None

    cast: Cast | None = None
    plan: RoundPlan | None = None
    transcript: Transcript = Field(default_factory=Transcript)
    memory: EpisodeMemory = Field(default_factory=EpisodeMemory)
    highlights: list[HighlightCandidate] = Field(default_factory=list)

    # Phase 2: renderer-neutral staging plan + master audio timeline.
    scene_manifest: SceneManifest | None = None

    run_report: RunReport = Field(default_factory=RunReport)
    approved: bool = False
