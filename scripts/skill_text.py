#!/usr/bin/env python3
"""The text of a skill's SKILL.md, line by line, with each line marked by what code can do about it (read only).

    python scripts/skill_text.py <skill folder>

A line carries one mark: "held" (a script of the skill already checks an instruction in it), "hold" (code can hold
an instruction in it), "text" (it holds instructions that stay text), or None (no instruction in it).
The instructions are the ones skill_score.py counts, found again in the text, so the marks and the numbers agree.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify_acs as ca  # noqa: E402
import derive_requirements as dr  # noqa: E402
import skill_score as ss  # noqa: E402

MAX_BYTES = 200_000
RANK = {"held": 3, "hold": 2, "text": 1}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*`_]", "", s)).strip().lower()


def marked(skill: Path) -> dict:
    """{"file": "SKILL.md", "lines": [{"t": raw line, "m": mark or None}]}"""
    p = skill / "SKILL.md"
    try:
        raw = p.read_text(encoding="utf-8-sig")[:MAX_BYTES].splitlines()
    except OSError:
        return {"file": "SKILL.md", "lines": []}
    doc, _ = ca.run(dr.derive(skill))
    scripts = ss.shipped_scripts(skill)
    joined, spans = "", []
    for i, line in enumerate(raw):
        n = norm(line)
        spans.append((len(joined), len(joined) + len(n), i))
        joined += n + " "
    marks: list[str | None] = [None] * len(raw)
    for r in doc["requirements"]:
        for a in r["acs"]:
            if not a["source"].startswith("SKILL.md"):
                continue
            kind = "held" if ss.is_enforced(a, scripts) else "hold" if a["class"] in ss.HOLDS else "text"
            n = norm(a["text"])
            at = joined.find(n) if n else -1
            if at < 0 and len(n) > 50:
                at, n = joined.find(n[:50]), n[:50]
            if at < 0:
                continue
            for s, e, i in spans:
                if s < at + len(n) and at < e and RANK[kind] > RANK.get(marks[i] or "", 0):
                    marks[i] = kind
    return {"file": "SKILL.md", "lines": [{"t": t, "m": m} for t, m in zip(raw, marks)]}


def main() -> int:
    if len(sys.argv) != 2 or not (Path(sys.argv[1]) / "SKILL.md").is_file():
        print("usage: skill_text.py <skill folder>")
        return 2
    print(json.dumps(marked(Path(sys.argv[1])), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
