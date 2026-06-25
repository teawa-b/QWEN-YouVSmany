"""Simple, reliable JSON episode store.

Each save writes a versioned snapshot so any episode can be reproduced from its
manifest (blueprint: "any episode can be reproduced from its manifest"). A
managed DB is intentionally out of scope for the MVP (blueprint 11.10)."""

from __future__ import annotations

import json
from pathlib import Path

from youvsmany.contracts.episode import Episode


class EpisodeStore:
    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, episode_id: str) -> Path:
        d = self.root / episode_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, episode: Episode) -> Path:
        d = self._dir(episode.episode_id)
        # bump version on each save so snapshots are immutable
        existing = sorted(d.glob("v*.json"))
        episode.version = len(existing) + 1
        path = d / f"v{episode.version:03d}.json"
        path.write_text(episode.model_dump_json(indent=2), encoding="utf-8")
        (d / "latest.json").write_text(episode.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load_latest(self, episode_id: str) -> Episode:
        path = self.root / episode_id / "latest.json"
        return Episode.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, episode_id: str) -> bool:
        return (self.root / episode_id / "latest.json").exists()

    def list_ids(self) -> list[str]:
        return [p.name for p in self.root.iterdir() if p.is_dir()]
