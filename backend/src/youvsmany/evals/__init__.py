"""Debate evaluation (blueprint 11.2, 12).

Scores a locked transcript on contention uniqueness, repetition, persona
adherence and duration, and compares the multi-agent system against the
single-agent baseline."""

from youvsmany.evals.metrics import DebateMetrics, score_episode

__all__ = ["DebateMetrics", "score_episode"]
