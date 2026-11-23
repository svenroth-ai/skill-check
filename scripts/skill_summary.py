#!/usr/bin/env python3
"""What a skill does, in a short abstract and a few words per section (read only, except `write`).

    python skill_summary.py <skill folder>                       print the summary as JSON
    python skill_summary.py write <skill folder> --file F.json   save a summary written by Skill Upgrade

If Skill Upgrade has written `baseline/summary.json` ({"abstract": "...", "sections": [{"name": "...", "text": "..."}]})
that is shown. Without it the summary is derived from the skill's own SKILL.md: its description is the abstract and
the first sentences of each section are the details. Nothing here runs a skill's code.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_ABSTRACT = 320
MAX_TEXT = 320


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\\([^\w\s])", r"\1", s)
    s = re.sub(r"[*`_]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def cut(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    head = s[:n]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1] if end > n // 2 else head.rstrip(" ,;:") + "..."


def front(text: str) -> tuple[dict, str]:
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() in ("name", "description"):
            meta[k.strip()] = v.strip().strip("\"'")
    return meta, text[m.end():]


def first_words(lines: list[str]) -> str:
    """The first sentences of a section's first prose paragraph, or of its first list items."""
    para, items = [], []
    code = False
    for line in lines:
        t = line.strip()
        if t.startswith("```"):
            code = not code
            continue
        if t.startswith("#"):
            if para or items:
                break
            continue
        if code or not t or t.startswith(("|", ">", "---")):
            if para:
                break
            continue
        m = re.match(r"([-*+]|\d+[.)])\s+(.*)", t)
        if m:
            items.append(plain(m.group(2)))
            continue
        if not items:
            para.append(plain(t))
    text = " ".join(para) if para else " ".join(items[:2])
    return cut(text, MAX_TEXT)


def derive(skill: Path) -> dict:
    meta, body = front(_read(skill / "SKILL.md"))
    abstract = cut(plain(meta.get("description", "")), MAX_ABSTRACT)
    sections, cur, name = [], [], None
    level = 2 if re.search(r"^## ", body, re.M) else 1
    mark = "#" * level + " "
    for line in body.splitlines():
        if line.startswith(mark):
            if name:
                sections.append((name, cur))
            name, cur = plain(line[len(mark):]), []
        elif name is not None:
            cur.append(line)
    if name:
        sections.append((name, cur))
    out = [{"name": n, "text": first_words(ls)} for n, ls in sections]
    return {"abstract": abstract, "sections": [s for s in out if s["text"]], "source": "derived"}


def clean(data: object) -> dict | None:
    if not isinstance(data, dict) or not isinstance(data.get("abstract"), str):
        return None
    secs = [{"name": str(s["name"]).strip(), "text": str(s["text"]).strip()}
            for s in data.get("sections", []) if isinstance(s, dict) and s.get("name") and s.get("text")]
    if not data["abstract"].strip() or not secs:
        return None
    return {"abstract": data["abstract"].strip(), "sections": secs, "source": "written"}


def summary(skill: Path) -> dict:
    try:
        written = clean(json.loads((skill / "baseline" / "summary.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        written = None
    return written or derive(skill)


def write(skill: Path, data: object) -> tuple[bool, str]:
    ok = clean(data)
    if ok is None:
        return False, 'the summary needs an "abstract" and a list "sections" of {"name", "text"}'
    p = skill / "baseline" / "summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"abstract": ok["abstract"], "sections": ok["sections"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return True, f"summary saved: {len(ok['sections'])} sections"


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if a[:1] == ["write"] and len(a) == 4 and a[2] == "--file":
        try:
            data = json.loads(Path(a[3]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("the file is not valid JSON")
            return 2
        ok, msg = write(Path(a[1]), data)
        print(msg)
        return 0 if ok else 3
    if len(a) != 1 or not (Path(a[0]) / "SKILL.md").is_file():
        print("usage: skill_summary.py <skill folder> | write <skill folder> --file F.json")
        return 2
    print(json.dumps(summary(Path(a[0])), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
