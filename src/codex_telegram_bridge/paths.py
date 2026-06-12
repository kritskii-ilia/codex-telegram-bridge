from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    home: Path
    logs: Path
    jobs: Path
    voices: Path
    transcripts: Path
    reports: Path
    project_states: Path
    tmp: Path
    db: Path

    @classmethod
    def from_home(
        cls,
        home: Path,
        *,
        logs: Path | None = None,
        db: Path | None = None,
    ) -> "RuntimePaths":
        return cls(
            home=home,
            logs=logs or (home / "logs"),
            jobs=home / "jobs",
            voices=home / "voices",
            transcripts=home / "transcripts",
            reports=home / "reports",
            project_states=home / "project_states",
            tmp=home / "tmp",
            db=db or (home / "bridge.sqlite3"),
        )

    def ensure(self) -> None:
        for path in (
            self.home,
            self.logs,
            self.jobs,
            self.voices,
            self.transcripts,
            self.reports,
            self.project_states,
            self.tmp,
            self.db.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
