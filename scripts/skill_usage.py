#!/usr/bin/env python3
"""How often each skill was used lately, counted from Claude Code's own history on this machine.

    python scripts/skill_usage.py [--days 30] [--projects DIR] [--json]

Reads the session files under ~/.claude/projects (read-only) and counts two things per skill: the model calling the
Skill tool, and the user typing /<skill>. Only the skill name and the time are kept; no prompt text is stored or
printed, and nothing leaves the machine. A skill that came in with a plugin is counted under its plain name
("shipwright-iterate:iterate" counts for "iterate").
Prints {"days": n, "sessions": n, "usage": {skill: count}}. If there is no history, usage is empty: the view then
makes no suggestion and the user picks. Exit codes: 0 done; 2 the projects folder is not readable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SLASH = re.compile(r"<command-name>/?([A-Za-z0-9_.:-]+)</command-name>")


def plain(name: str) -> str:
    return name.rsplit(":", 1)[-1].strip().lower()


def when(stamp) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def hits(line: str) -> list[str]:
    """The skill names used in one line of a session file."""
    if '"Skill"' not in line and "<command-name>" not in line:
        return []
    try:
        row = json.loads(line)
    except ValueError:
        return []
    out = []
    content = (row.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
            name = (block.get("input") or {}).get("skill")
            if isinstance(name, str) and name:
                out.append(plain(name))
        elif isinstance(block, dict) and block.get("type") == "text" and row.get("type") == "user":
            out += [plain(m) for m in SLASH.findall(str(block.get("text", "")))]
    if isinstance(content, str) and row.get("type") == "user":
        out += [plain(m) for m in SLASH.findall(content)]
    return out


def usage(projects: Path, days: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    counts: dict[str, int] = {}
    sessions = 0
    for f in projects.glob("*/*.jsonl"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) < since:
                continue  # untouched since before the window
            seen = False
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    names = hits(line)
                    if not names:
                        continue
                    try:
                        at = when(json.loads(line).get("timestamp"))
                    except ValueError:
                        continue
                    if at is None or at < since:
                        continue
                    seen = True
                    for n in names:
                        counts[n] = counts.get(n, 0) + 1
            sessions += seen
        except OSError:
            continue
    return {"days": days, "sessions": sessions, "usage": dict(sorted(counts.items(), key=lambda kv: -kv[1]))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    a = ap.parse_args()
    if not a.projects.is_dir():
        print(f"no history found at {a.projects}", file=sys.stderr)
        return 2
    print(json.dumps(usage(a.projects, a.days)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
