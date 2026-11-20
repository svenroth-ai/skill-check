#!/usr/bin/env python3
"""Where a skill comes from, and the level it has reached (read only).

    python scripts/skill_origin.py <skill folder> [--status status.json]

origin   "own"       a skill the user keeps and wrote (~/.claude/skills, or a project's .claude/skills)
         "plugin"    a skill that belongs to a plugin from a marketplace. A plugin update replaces the plugin's files,
                     so any change made there is lost: such a skill can be checked but never upgraded in place.
                     A skill folder that is a link into the plugin cache is a plugin skill too: the real path decides.
         "installed" a skill an installer put there (~/.agents/.skill-lock.json names it and its source)
         "foreign"   a skill the user marked as not theirs (~/.shipwright/skill-check/origin_marks.json)
         The user can override the guess either way: a mark "mine" makes an installed skill own again.
         Only "own" skills are ever upgraded or counted in the user's levels.
level    1 Written     the skill only says what to do (or code holds less than it could)
         2 Enforced    every instruction code can hold has a passing check (status.json: every held instruction passes)
         3 In control  Level 2, and the owner approved the written list (status.json: controlled_at)
Exit codes: 0 printed; 2 no such skill folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _json(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def set_mark(name: str, mine: bool, home: Path | None = None) -> None:
    """Remember the user's own word on whether a skill is theirs. Only a plain skill name is stored."""
    home = home or Path.home()
    if not name or "/" in name or chr(92) in name or name.startswith("."):
        raise ValueError("not a skill name")
    path = home / ".shipwright" / "skill-check" / "origin_marks.json"
    marks = _json(path)
    marks[name] = "mine" if mine else "not_mine"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marks, indent=1), encoding="utf-8")


def origin(skill: Path, home: Path | None = None) -> dict:
    home = home or Path.home()
    cache = (home / ".claude" / "plugins" / "cache").resolve()
    try:
        real = skill.resolve()
        rel = real.relative_to(cache)
    except (OSError, ValueError):
        mark = _json(home / ".shipwright" / "skill-check" / "origin_marks.json").get(skill.name)
        if mark == "mine":
            return {"kind": "own"}
        if mark == "not_mine":
            return {"kind": "foreign"}
        src = (_json(home / ".agents" / ".skill-lock.json").get("skills") or {}).get(skill.name)
        if isinstance(src, dict) and isinstance(src.get("source"), str):
            return {"kind": "installed", "source": src["source"]}
        return {"kind": "own"}
    parts = rel.parts  # <marketplace>/<plugin>/<version>/skills/<name>
    return {"kind": "plugin", "marketplace": parts[0] if parts else "", "plugin": parts[1] if len(parts) > 1 else ""}


def level(row: dict, status: dict | None) -> int:
    """row: one skill_score.score() result. status: the skill's status.json, or None when it was never upgraded."""
    if not isinstance(status, dict):
        return 1 if row.get("add", 0) > 0 or row.get("hold", 0) == 0 else 2
    acs = status.get("acs")
    upgraded = isinstance(acs, dict) and bool(acs) and status.get("failing", 1) == 0 and status.get("gap", 1) == 0 and status.get("other", 1) == 0
    if upgraded and isinstance(status.get("controlled_at"), str) and status["controlled_at"]:
        return 3
    return 2 if upgraded else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skill", type=Path)
    ap.add_argument("--status", type=Path)
    a = ap.parse_args()
    if not (a.skill / "SKILL.md").is_file():
        print(f"{a.skill} has no SKILL.md", file=sys.stderr)
        return 2
    status = None
    if a.status:
        try:
            status = json.loads(a.status.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            status = None
    print(json.dumps({"origin": origin(a.skill), "status_level": level({}, status)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
