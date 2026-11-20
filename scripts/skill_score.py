#!/usr/bin/env python3
"""Count, for a skill, how many instructions code can hold and how many it holds today (read only).

    python scripts/skill_score.py <skill folder | skills root> [--usage DAYS]

An instruction is one acceptance criterion drafted from the skill's own text (derive_requirements.py), sorted by
classify_acs.py. Plain words for the view:
  can hold     the instruction can be checked by code: a measurable rule, an exact outgoing command, or a
               "wait for the user's OK" gate (class mechanic, command, ask)
  enforced     of those, the ones a script that the skill ships already checks: the sentence names a script
               file that exists in the skill (class mechanic only)
  can add      can hold minus enforced: what an upgrade would put under code
  stay text    taste, judgment, definitions: code cannot hold them (class judgement, text)
A part is one top-level section of the skill that holds at least one instruction. Numbers are derived, not judged:
the same skill always gives the same numbers. Nothing is written and nothing leaves the machine.
Exit codes: 0 printed; 2 no such skill or folder.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify_acs as ca  # noqa: E402
import derive_requirements as dr  # noqa: E402

HOLDS = {"mechanic", "command", "ask"}
SCRIPT_NAME = re.compile(r"\b([\w.-]+\.(?:py|sh|cjs|js|mjs|ts))\b")


def shipped_scripts(skill: Path) -> set[str]:
    return {p.name for p in skill.rglob("*") if p.is_file() and p.suffix in {".py", ".sh", ".cjs", ".js", ".mjs", ".ts"}
            and "node_modules" not in p.parts}


def is_enforced(ac: dict, scripts: set[str]) -> bool:
    return ac["class"] == "mechanic" and any(n in scripts for n in SCRIPT_NAME.findall(ac["text"]))


def pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


def part_line(total: int, hold: int, enforced: int) -> str:
    if hold == 0:
        return f"{total} {'instruction' if total == 1 else 'instructions'}: all need your judgment and stay text."
    if enforced >= hold:
        return f"{total} {'instruction' if total == 1 else 'instructions'}: code already holds all {hold} it can hold."
    add = hold - enforced
    return (f"{total} {'instruction' if total == 1 else 'instructions'}: code can hold {hold}, "
            f"{enforced} {'is' if enforced == 1 else 'are'} held today, {add} can be added.")


def score(skill: Path) -> dict:
    """{"skill", "total", "hold", "enforced", "add", "text", "pct": {...}, "parts": [...]}"""
    doc = dr.derive(skill)
    doc, _ = ca.run(doc)
    scripts = shipped_scripts(skill)
    parts, T = [], {"total": 0, "hold": 0, "enforced": 0}
    for r in doc["requirements"]:
        t = h = e = 0
        for a in r["acs"]:
            t += 1
            h += a["class"] in HOLDS
            e += is_enforced(a, scripts)
        T["total"] += t
        T["hold"] += h
        T["enforced"] += e
        src = r["acs"][0]["source"].split(":")[0] if r["acs"] else ""
        parts.append({"name": r["text"], "file": src, "total": t, "hold": h, "enforced": e, "add": h - e, "text": t - h,
                      "status": "upgrade" if h > e else "text" if h == 0 else "good",
                      "line": part_line(t, h, e)})
    total, hold, enf = T["total"], T["hold"], T["enforced"]
    status = "none" if total == 0 else "upgrade" if hold > enf else "good"
    return {"skill": skill.name, "total": total, "hold": hold, "enforced": enf, "add": hold - enf,
            "text": total - hold, "status": status,
            "pct": {"enforced": pct(enf, total), "hold": pct(hold, total), "add": pct(hold - enf, total),
                    "text": pct(total - hold, total)},
            "parts": parts}


def skill_dirs(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.glob("*/SKILL.md"))


def suggest(rows: list[dict], usage: dict[str, int], min_uses: int = 3) -> dict | None:
    """The skill to start with: used at least min_uses times, something to add, the lowest enforced share first,
    then the most used. None when no skill qualifies (the user then picks)."""
    cand = [r for r in rows if r["add"] > 0 and usage.get(r["skill"], 0) >= min_uses]
    if not cand:
        return None
    best = min(cand, key=lambda r: (r["pct"]["enforced"], -usage.get(r["skill"], 0), r["skill"]))
    return {"skill": best["skill"], "uses": usage.get(best["skill"], 0), "enforced_pct": best["pct"]["enforced"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=Path)
    a = ap.parse_args()
    if (a.path / "SKILL.md").is_file():
        out = score(a.path)
    elif a.path.is_dir():
        out = [score(d) for d in skill_dirs(a.path)]
    else:
        print(f"{a.path} is not a skill folder or a skills root", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
