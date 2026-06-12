from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codex_telegram_bridge.models import ProjectRecord, utc_now
from codex_telegram_bridge.store import BridgeStore


PROJECT_MARKERS = [
    ".git",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "README.md",
]


@dataclass(slots=True)
class ProjectContext:
    record: ProjectRecord
    state_summary: str


def slugify(value: str) -> str:
    simplified = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return simplified or "project"


class ProjectIndexer:
    def __init__(self, store: BridgeStore, state_dir: Path, scan_roots: list[Path]) -> None:
        self.store = store
        self.state_dir = state_dir
        self.scan_roots = scan_roots

    def reindex(self, max_depth: int = 4) -> list[ProjectRecord]:
        discovered: list[ProjectRecord] = []
        for root in self.scan_roots:
            if not root.exists():
                continue
            for current_root, dirnames, filenames in os.walk(root):
                depth = len(Path(current_root).relative_to(root).parts)
                if depth > max_depth:
                    dirnames[:] = []
                    continue
                marker_names = set(dirnames) | set(filenames)
                markers = sorted(set(PROJECT_MARKERS).intersection(marker_names))
                if not markers:
                    continue
                current_path = Path(current_root)
                key = slugify(current_path.name)
                aliases = ",".join(sorted({current_path.name, key, str(current_path)}))
                record = ProjectRecord(
                    key=key,
                    name=current_path.name,
                    root_path=str(current_path),
                    markers=",".join(markers),
                    aliases=aliases,
                    last_scanned_at=utc_now(),
                )
                self.store.upsert_project(record)
                discovered.append(record)
                dirnames[:] = [name for name in dirnames if name not in {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__"}]
        return discovered

    def ensure_index(self) -> list[ProjectRecord]:
        projects = self.store.list_projects()
        if projects:
            return projects
        return self.reindex()

    def resolve_project_hint(self, text: str) -> ProjectRecord | None:
        normalized = text.strip().lower()
        if not normalized:
            return None
        for project in self.store.list_projects():
            variants = {
                project.key.lower(),
                project.name.lower(),
                project.root_path.lower(),
                *(alias.strip().lower() for alias in project.aliases.split(",") if alias.strip()),
            }
            if any(variant and variant in normalized for variant in variants):
                return project
        return None

    def build_project_summary(self, record: ProjectRecord) -> str:
        state_path = self.state_dir / f"{record.key}.md"
        if state_path.exists():
            return state_path.read_text(encoding="utf-8")

        root = Path(record.root_path)
        readme = next((path for path in (root / "README.md", root / "README.rst", root / "readme.md") if path.exists()), None)
        readme_text = ""
        if readme:
            readme_text = readme.read_text(encoding="utf-8", errors="ignore")[:3000]

        git_status = _run_command(["git", "-C", str(root), "status", "--short"], cwd=root)
        recent_files = _run_command(["bash", "-lc", "find . -maxdepth 2 -type f | sed 's#^./##' | sort | head -n 40"], cwd=root)
        latest_commits = _run_command(["git", "-C", str(root), "log", "--oneline", "-n", "5"], cwd=root)
        summary = (
            f"# Project Memory: {record.name}\n\n"
            f"Project root: `{record.root_path}`\n\n"
            "## Known markers\n"
            f"{record.markers}\n\n"
            "## README excerpt\n"
            f"{readme_text or 'No README found.'}\n\n"
            "## Git status\n"
            f"{git_status or 'Unavailable.'}\n\n"
            "## Recent files\n"
            f"{recent_files or 'Unavailable.'}\n\n"
            "## Recent commits\n"
            f"{latest_commits or 'Unavailable.'}\n\n"
            "## Continuation Notes\n"
            "- State summary auto-generated. Replace with richer summary after successful tasks.\n"
        )
        state_path.write_text(summary, encoding="utf-8")
        return summary

    def update_project_memory(self, record: ProjectRecord, final_report: str) -> Path:
        state_path = self.state_dir / f"{record.key}.md"
        previous = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
        content = (
            f"# Project Memory: {record.name}\n\n"
            f"Updated: {utc_now()}\n\n"
            "## Latest Final Report\n"
            f"{final_report.strip()}\n\n"
            "## Previous Snapshot\n"
            f"{previous[:8000] if previous else 'No previous snapshot.'}\n"
        )
        state_path.write_text(content, encoding="utf-8")
        return state_path


def _run_command(args: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception as exc:
        return f"Command failed: {exc}"
    output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    return output.strip()[:3000]
