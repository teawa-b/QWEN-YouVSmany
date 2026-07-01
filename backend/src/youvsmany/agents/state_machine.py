"""Debate state machine (blueprint 4.4) driven by the moderator control agent.

BRIEFED -> PREPARING -> OPENING -> CONTENTIONS -> RAPID_REBUTTAL -> CLOSING -> LOCKED

The moderator picks the next speaker, sets a per-turn objective, kills
repetition, caps dominance and forces a disputed question when sides talk past
each other. CONTENTIONS now means one shared claim with rotating room pressure,
not isolated one-on-one segments (blueprint 4.5)."""

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
from youvsmany.contracts.transcript import CAPTION_SPEAKER_ID, Transcript, Turn

REPETITION_THRESHOLD = 0.6
MAX_REGEN_PER_TURN = 2  # retry cap when a turn is repetitive
MIN_LOCKED_TURNS = 12
MAX_LOCKED_TURNS = 24


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
        """One shared claim, many challengers in the same room.

        The protagonist puts a single claim on the floor. Challengers first enter
        with distinct pressure angles, then follow up round-robin while the
        protagonist has to answer the room rather than isolated one-on-one duels.
        """
        slots = self.plan.contentions
        if not slots:
            return

        challengers = [self.cast.by_id(slot.challenger_id) for slot in slots]
        for slot in slots:
            self.memory.covered_contentions.append(slot.contention_tag)

        # 1. One shared claim card for the whole room.
        self._emit(
            self.cast.protagonist,
            DebateState.CONTENTIONS,
            director.room_claim_objective(self.topic),
            scene_cue="claim_card",
            force=True,
        )

        # 2. Opening pressure wave: every challenger attacks the same claim from
        # their own angle. Later challengers can build on the previous voice.
        previous = self.cast.protagonist
        for index, (slot, challenger) in enumerate(zip(slots, challengers)):
            if index == 0:
                objective = director.opening_pressure_objective(slot.contention_tag, self.topic)
                react_to = self.cast.protagonist
            else:
                objective = director.build_pressure_objective(
                    slot.contention_tag, previous.display_name, self.topic
                )
                react_to = previous
            self._emit(
                challenger,
                DebateState.CONTENTIONS,
                objective,
                react_to=react_to,
                greet=index == 0,
            )
            previous = challenger

        # 3. The protagonist answers the room before follow-ups begin.
        self._emit(
            self.cast.protagonist,
            DebateState.CONTENTIONS,
            director.answer_room_objective(self.topic),
            react_to=previous,
        )

        # 4. Rotating crossfire on the same claim.
        pairs = director.crossfire_pairs(len(challengers), self.plan.target_turns)
        for pair_index in range(pairs):
            slot = slots[pair_index % len(slots)]
            challenger = challengers[pair_index % len(challengers)]
            self._emit(
                challenger,
                DebateState.CONTENTIONS,
                director.follow_up_objective(slot.contention_tag, self.topic),
                react_to=self.cast.protagonist,
            )
            self._emit(
                self.cast.protagonist,
                DebateState.CONTENTIONS,
                director.answer_follow_up_objective(slot.contention_tag),
                react_to=challenger,
            )

    def _do_rapid_rebuttal(self) -> None:
        # Depth is baked into crossfire now, so this is a pass-through state.
        # Kept as a safety net: only fires if a tiny cast somehow landed under
        # the locked floor, adding one extra exchange on the last pressure angle.
        closing_turns = 2
        needed = MIN_LOCKED_TURNS - len(self.transcript.turns) - closing_turns
        if needed <= 0 or not self.plan.contentions:
            return
        slot = self.plan.contentions[-1]
        challenger = self.cast.by_id(slot.challenger_id)
        while needed > 0 and len(self.transcript.turns) + closing_turns + 2 <= MAX_LOCKED_TURNS:
            objective = director.disputed_question(slot.contention_tag, self.topic)
            self._emit(challenger, DebateState.RAPID_REBUTTAL, f"one urgent follow-up: {objective}")
            self._emit(self.cast.protagonist, DebateState.RAPID_REBUTTAL, "one sharp direct answer")
            needed -= 2

    def _do_closing(self) -> None:
        # No moderator handoff: the protagonist's closing line itself signals the
        # turn to closings, so the round ends on a single spoken beat.
        self._emit(self.cast.protagonist, DebateState.CLOSING, self.plan.closing_objective)

    # --- emission helpers ---------------------------------------------

    def _emit_caption(self, state: DebateState, text: str, *, scene_cue: str) -> None:
        """Append a non-spoken ritual caption (e.g. the voted-out gavel).

        Captions never go through a provider, the dominance cap or the
        repetition guard; they carry no debating voice, so they are excluded
        from speaker metrics and from opponent-reaction lookups."""
        turn = Turn(
            turn_id=f"t{self._counter:04d}",
            index=self._counter,
            state=state,
            speaker_id=CAPTION_SPEAKER_ID,
            speaker_name="",
            text=text,
            contention_tag=None,
            objective=None,
            scene_cue=scene_cue,
        )
        self.transcript.turns.append(turn)
        self.memory.rolling_summary = self._summarise()
        self._counter += 1

    def _emit(
        self,
        speaker,
        state: DebateState,
        objective: str,
        *,
        react_to=None,
        scene_cue: str | None = None,
        force: bool = False,
        greet: bool = False,
    ) -> None:
        # Dominance rule (skipped for forced ritual beats: claim cards, the
        # voted-out gavel and the opening/closing always land).
        if not force and director.next_speaker_blocked(self.memory, speaker.character_id):
            self.ep.run_report.events.append(
                f"dominance: skipped extra consecutive turn for {speaker.character_id}"
            )
            return

        if react_to is not None:
            # Point the speaker at a specific opponent even before they've spoken
            # (the claim card targets the challenger about to stand up; the gavel
            # names the challenger being sent back to their seat).
            react_turn = self._last_turn_of(react_to.character_id)
            latest_opposing = react_turn.text if react_turn else ""
            latest_opposing_tag = react_to.contention_tag
            latest_opposing_name = react_to.display_name
        else:
            opposing_turn = self._latest_opposing_turn(speaker.character_id)
            # Fall back to the most recent spoken turn so a speaker always has
            # something concrete to react to (keeps the exchange a back-and-forth);
            # skip ritual captions, which carry no debating voice.
            spoken = [t for t in self.transcript.turns if t.speaker_id != CAPTION_SPEAKER_ID]
            react_turn = opposing_turn or (spoken[-1] if spoken else None)
            latest_opposing = react_turn.text if react_turn else ""
            latest_opposing_tag = react_turn.contention_tag if react_turn else None
            latest_opposing_name = react_turn.speaker_name if react_turn else ""
        if greet:
            objective = "greet your opponent first, then " + objective
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
                latest_opposing_name=latest_opposing_name,
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
            scene_cue=scene_cue or cue_for(state, speaker.role),
        )
        self.transcript.turns.append(turn)
        self.memory.record(speaker.character_id, turn.word_count, f"{speaker.display_name}: {text[:60]}")
        if speaker.role.value == "challenger":
            self.memory.unresolved_claims.append(f"{speaker.contention_tag}: {text[:60]}")
        self.memory.rolling_summary = self._summarise()
        self._counter += 1

    def _last_turn_of(self, speaker_id: str):
        for turn in reversed(self.transcript.turns):
            if turn.speaker_id == speaker_id:
                return turn
        return None

    def _latest_opposing_turn(self, speaker_id: str):
        speaker = self.cast.by_id(speaker_id)
        for turn in reversed(self.transcript.turns):
            if turn.speaker_id == CAPTION_SPEAKER_ID:
                continue
            other = self.cast.by_id(turn.speaker_id)
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
