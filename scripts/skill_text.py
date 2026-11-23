#!/usr/bin/env python3
"""The text of a skill's SKILL.md (read only).

    python scripts/skill_text.py <skill folder>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_BYTES = 400_000


def text(skill: Path) -> dict:
    """{"file": "SKILL.md", "text": the file}"""
    try:
        body = (skill / "SKILL.md").read_text(encoding="utf-8-sig")[:MAX_BYTES]
    except OSError:
        body = ""
    return {"file": "SKILL.md", "text": body}


def main() -> int:
    if len(sys.argv) != 2 or not (Path(sys.argv[1]) / "SKILL.md").is_file():
        print("usage: skill_text.py <skill folder>")
        return 2
    print(json.dumps(text(Path(sys.argv[1])), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
