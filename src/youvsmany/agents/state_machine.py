"""Debate state machine (blueprint 4.4) driven by the moderator control agent.

BRIEFED -> PREPARING -> OPENING -> CONTENTIONS -> RAPID_REBUTTAL -> CLOSING -> LOCKED

The moderator picks the next speaker, sets a per-turn objective, kills
repetition, caps dominance and forces a disputed question when sides talk past
each other (blueprint 4.5)."""

from __future__ import annotations

from youvsmany.adapters.base import Provider
from youvsmany.agents import director
from youvsmany.agents.debaters import generate_turn
from youvsmany.agents.repetition import max_similarity
from youvsmany.agents.scene_cues import cue_for
from youvsmany.contracts.character import Cast
from youvsmany.contracts.enums import DebateState
from youvsmany.contracts.episode import Episode
from youvsmany.contracts.memory import EpisodeMemory
from youvsmany.contracts.plan import RoundPlan
from youvsmany.contracts.transcript import Transcript, Turn

REPETITION_THRESHOLD = 0.6
MAX_REGEN_PER_TURN = 2  # retry cap when a turn is repetitive


class DebateRunner:
    def __init__(self, provider: Provider, episode: Episode) -> None:
        self.provider = provider
        self.ep = episode
        self.cast: Cast = episode.cast  # type: ignore[assignment]
        self.plan: RoundPlan = episode.plan  # type: ignore[assignment]
        self.memory: EpisodeMemory = episode.memory
        self.transcript: Transcript = episode.transcript
        self.topic = episode.brief.topic
        self.seed = episode.brief.seed
        self._counter = 0

    # --- public driver -------------------------------------------------

    def run(self) -> Episode:
        self._transition(DebateState.OPENING)
        self._do_opening()
        self._transition(DebateState.CONTENTIONS)
        self._do_contentions()
        self._transition(DebateState.RAPID_REBUTTAL)
        self._do_rapid_rebuttal()
        self._transition(DebateState.CLOSING)
        self._do_closing()
        self._transition(DebateState.LOCKED)
        self.transcript.retime()
        self._reapply_timing_to_highlights_source()
        return self.ep

    # --- states --------------------------------------------------------

    def _do_opening(self) -> None:
        self._emit(self.cast.protagonist, DebateState.OPENING, self.plan.opening_objective)

    def _do_contentions(self) -> None:
        for slot in self.plan.contentions:
            challenger = self.cast.by_id(slot.challenger_id)
            self.memory.covered_contentions.append(slot.contention_tag)
            self._emit(challenger, DebateState.CONTENTIONS, slot.objective)
            self._emit(
                self.cast.protagonist,
                DebateState.CONTENTIONS,
                f"answer the {slot.contention_tag} objection directly",
            )

    def _do_rapid_rebuttal(self) -> None:
        # Short alternating exchanges; moderator forces a disputed question.
        for slot in self.plan.contentions[:2]:
            challenger = self.cast.by_id(slot.challenger_id)
            self._emit_moderator(
                director.disputed_question(slot.contention_tag, self.topic)
            )
            self._emit(challenger, DebateState.RAPID_REBUTTAL, "one sharp sentence")
            self._emit(self.cast.protagonist, DebateState.RAPID_REBUTTAL, "one sharp answer")

    def _do_closing(self) -> None:
        self._emit_moderator("invite closing statements")
        self._emit(self.cast.protagonist, DebateState.CLOSING, self.plan.closing_objective)

    # --- emission helpers ---------------------------------------------

    def _emit_moderator(self, objective: str) -> None:
        self._emit(self.cast.moderator, self.ep.state, objective)

    def _emit(self, speaker, state: DebateState, objective: str) -> None:
        # Dominance rule.
        if director.next_speaker_blocked(self.memory, speaker.character_id):
            self.ep.run_report.events.append(
                f"dominance: skipped extra consecutive turn for {speaker.character_id}"
            )
            return

        opposing_turn = self._latest_opposing_turn(speaker.character_id)
        latest_opposing = opposing_turn.text if opposing_turn else ""
        latest_opposing_tag = opposing_turn.contention_tag if opposing_turn else None
        prior_texts = [t.text for t in self.transcript.turns]

        text = ""
        for attempt in range(MAX_REGEN_PER_TURN + 1):
            text, in_tok, out_tok = generate_turn(
                self.provider,
                speaker=speaker,
                state=state,
                objective=objective,
                latest_opposing_claim=latest_opposing,
                latest_opposing_tag=latest_opposing_tag,
                topic=self.topic,
                index=self._counter,
                seed=self.seed + attempt,
            )
            self.ep.run_report.llm_calls += 1
            self.ep.run_report.input_tokens += in_tok
            self.ep.run_report.output_tokens += out_tok
            sim = max_similarity(text, prior_texts)
            if sim < REPETITION_THRESHOLD:
                break
            self.ep.run_report.retries += 1
            self.ep.run_report.events.append(
                f"repetition: regen turn for {speaker.character_id} (sim={sim})"
            )
            objective = objective + " — bring a NEW example, do not restate."

        turn = Turn(
            turn_id=f"t{self._counter:04d}",
            index=self._counter,
            state=state,
            speaker_id=speaker.character_id,
            speaker_name=speaker.display_name,
            text=text,
            contention_tag=speaker.contention_tag if speaker.role.value == "challenger" else None,
            objective=objective,
            scene_cue=cue_for(state, speaker.role),
        )
        self.transcript.turns.append(turn)
        self.memory.record(speaker.character_id, turn.word_count, f"{speaker.display_name}: {text[:60]}")
        if speaker.role.value == "challenger":
            self.memory.unresolved_claims.append(f"{speaker.contention_tag}: {text[:60]}")
        self.memory.rolling_summary = self._summarise()
        self._counter += 1

    def _latest_opposing_turn(self, speaker_id: str):
        speaker = self.cast.by_id(speaker_id)
        for turn in reversed(self.transcript.turns):
            other = self.cast.by_id(turn.speaker_id)
            if other.role.value == "moderator":
                continue
            if other.stance != speaker.stance:
                return turn
        return None

    def _summarise(self) -> str:
        tags = ", ".join(dict.fromkeys(self.memory.covered_contentions))
        return f"{len(self.transcript.turns)} turns; contentions covered: {tags or 'none yet'}."

    def _transition(self, to: DebateState) -> None:
        from youvsmany.contracts.enums import STATE_TRANSITIONS

        if to not in STATE_TRANSITIONS[self.ep.state]:
            raise ValueError(f"illegal transition {self.ep.state} -> {to}")
        self.ep.state = to
        self.ep.run_report.events.append(f"state -> {to.value}")

    def _reapply_timing_to_highlights_source(self) -> None:
        # timings already applied via retime(); placeholder hook kept for clarity
        return
