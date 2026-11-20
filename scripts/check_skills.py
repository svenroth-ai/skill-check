#!/usr/bin/env python3
"""Shipwright Skill Check, scanner (read only).

Reads every skill under --root, splits SKILL.md and references/*.md into heading sections with an
anchor (file, heading path, content hash), checks the authoring limits from the pinned conventions
file, counts rule-like lines, and measures the script share. It never writes into the skills.

    python scripts/check_skills.py --root ~/.claude/skills [--out DIR] [--json | --summary]

Results go to --out (default ~/.shipwright/skill-check). The text before the first heading of a file
(for SKILL.md including the frontmatter) is the section "(preamble)", so an edit there is noticed.
Equal heading paths in one file get " #2", " #3".

Exit codes: 0 report written; 2 the skills folder or the limits file is missing or unreadable.
Limit values are never hard-coded here: they come from config/conventions.skill_authoring.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONVENTIONS = HERE.parent / "config" / "conventions.skill_authoring.json"
# Results live in the user's data folder, not in the plugin folder (an installed plugin may be read only).
DATA = Path.home() / ".shipwright" / "skill-check"
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
# Lines that read like a rule. A first guess for the report, not a classification.
# "only" and "nur" are left out on purpose: they mostly mark conditions ("only if reel:true").
RULE = re.compile(
    r"\b(must|never|always|do not|don't|required|mandatory|critical|forbidden|"
    r"immer|nie|niemals|muss|darf nicht|pflicht)\b",
    re.I,
)
# Words nearly every skill description contains; they would make unrelated skills look alike.
STOPWORDS = {"when", "user", "users", "wants", "want", "trigger", "this", "that", "with", "from", "skill",
             "use", "using", "also", "your", "into", "than", "then", "used", "uses", "need", "needs", "like",
             "for", "and", "the", "are", "not", "any", "all", "can", "via", "per", "its", "has", "have"}
SIMILARITY_MIN = 0.25  # first guess, tuned by eye on 37 real descriptions: shows pairs worth a look
CHARS_PER_TOKEN = 4  # rough average for English prose, enough to rank skills by size


def digest(lines: list[str]) -> str:
    text = "\n".join(line.rstrip() for line in lines).strip("\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")  # utf-8-sig: a BOM is not content


def split_frontmatter(text: str) -> tuple[dict, list[str], int]:
    """Returns (fields, body lines, number of lines the frontmatter block takes, markers included)."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines, 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, lines, 0
    parts: dict[str, list[str]] = {}
    style: dict[str, str] = {}
    key = None
    for raw in lines[1:end]:
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if m and not raw.startswith((" ", "\t")):
            key, val = m.group(1), m.group(2).strip()
            if re.fullmatch(r"[>|][+-]?", val):
                style[key], parts[key] = val[0], []
            else:
                style[key], parts[key] = "plain", [val]
        elif key and not raw.strip().startswith("#"):
            parts[key].append(raw.strip())
    out: dict[str, str] = {}
    for k, ps in parts.items():
        v = ("\n" if style[k] == "|" else " ").join(p for p in ps if p).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            q, v = v[0], v[1:-1]
            v = v.replace("''", "'") if q == "'" else v.replace('\\"', '"').replace("\\\\", "\\")
        out[k] = v
    return out, lines[end + 1:], end + 1


def sections(file: str, lines: list[str], preamble_lines: int = 0, keep_text: bool = False) -> list[dict]:
    """Flat sections. A heading line runs until the next heading of any level (fenced lines are never
    headings). The text before the first heading, plus the first preamble_lines lines, is "(preamble)"."""
    out: list[dict] = []
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    pre: list[str] = list(lines[:preamble_lines])
    cur: dict | None = None
    fence: tuple[str, int] | None = None

    def close() -> None:
        if cur is not None:
            body = cur.pop("_lines")
            cur["hash"] = digest(body)
            if keep_text:
                cur["lines"] = body
            out.append(cur)

    for line in lines[preamble_lines:]:
        f = FENCE.match(line)
        if f:
            run, rest = f.group(1), f.group(2)
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and not rest.strip():
                fence = None
        h = None if fence else HEADING.match(line)
        if h:
            close()
            level, title = len(h.group(1)), h.group(2)
            stack[:] = [t for t in stack if t[0] < level] + [(level, title)]
            path = " > ".join(t for _, t in stack)
            seen[path] = seen.get(path, 0) + 1
            if seen[path] > 1:
                path += f" #{seen[path]}"
            cur = {"file": file, "path": path, "class": "unclassified", "_lines": [line]}
        elif cur is not None:
            cur["_lines"].append(line)
        else:
            pre.append(line)
    close()
    if any(line.strip() for line in pre):
        first = {"file": file, "path": "(preamble)", "class": "unclassified", "hash": digest(pre)}
        if keep_text:
            first["lines"] = pre
        out.insert(0, first)
    return out


def load_limits() -> dict:
    try:
        data = json.loads(CONVENTIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {CONVENTIONS}: {e}", file=sys.stderr)
        sys.exit(2)
    return {item["id"]: item for item in data["skill_authoring"]["limits"]}


def check_limits(limits: dict, fm: dict, body: list[str], refs: dict[str, list[str]], skill_text: str) -> list[dict]:
    found: list[dict] = []

    def add(lid: str, detail: str) -> None:
        found.append({"limit": lid, "kind": limits[lid]["kind"], "detail": detail})

    desc = fm.get("description", "")
    if not fm.get("name"):
        add("name-required", "frontmatter has no name")
    else:
        n = fm["name"]
        if len(n) > limits["name-max-length"]["value"]:
            add("name-max-length", f"{len(n)} chars")
        if not re.match(limits["name-charset"]["value"], n):
            add("name-charset", n)
        for w in limits["name-reserved-words"]["value"]:
            if w in n:
                add("name-reserved-words", w)
    if not desc:
        add("description-required", "frontmatter has no description")
    elif len(desc) > limits["description-max-length"]["value"]:
        add("description-max-length", f"{len(desc)} chars")
    if re.search(limits["no-xml-tags"]["value"], fm.get("name", "") + " " + desc):
        add("no-xml-tags", "tag-like text in name or description")
    if len(body) >= limits["body-max-lines"]["value"]:
        add("body-max-lines", f"{len(body)} lines")
    bad = re.compile(limits["forward-slash-paths"]["value"])
    if bad.search(skill_text) or any(bad.search("\n".join(v)) for v in refs.values()):
        add("forward-slash-paths", "backslash path in text")
    window = limits["reference-toc-threshold"].get("window", 40)
    for rel, lines in refs.items():
        if len(lines) > limits["reference-toc-threshold"]["value"]:
            head = "\n".join(lines[:window])
            if not re.search(r"^#+\s*(table of )?contents\b", head, re.I | re.M) and not re.search(r"\]\(#", head):
                add("reference-toc-threshold", f"{rel}: {len(lines)} lines, no contents list")
    names = {Path(r).name for r in refs}
    for rel, lines in refs.items():
        for target in re.findall(r"\(([^)#]+\.md)(?:#[^)]*)?\)", "\n".join(lines)):
            if Path(target).name in names and Path(target).name != Path(rel).name:
                add("references-one-level", f"{rel} links on to {target}")
                break
    return found


def scan_skill(d: Path, limits: dict) -> dict | None:
    md = d / "SKILL.md"
    if not md.is_file():
        return None
    text = read_text(md)
    fm, body, fm_lines = split_frontmatter(text)
    refs: dict[str, list[str]] = {}
    refdir = d / "references"
    if refdir.is_dir():
        for p in sorted(refdir.rglob("*.md")):
            refs[p.relative_to(d).as_posix()] = read_text(p).splitlines()
    all_lines = text.lstrip("﻿").splitlines()
    secs = sections("SKILL.md", all_lines, preamble_lines=fm_lines)
    for rel, lines in refs.items():
        secs += sections(rel, lines)
    scripts = []
    if (d / "scripts").is_dir():
        scripts = [p for p in (d / "scripts").rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    rules = [ln for ln in body if RULE.search(ln) and not ln.lstrip().startswith("#")]
    return {
        "skill": d.name,
        "name": fm.get("name", ""),
        "description_chars": len(fm.get("description", "")),
        "body_lines": len(body),
        "tokens_estimate": len(text) // CHARS_PER_TOKEN,
        "reference_tokens_estimate": sum(len("\n".join(v)) for v in refs.values()) // CHARS_PER_TOKEN,
        "references": len(refs),
        "scripts": len(scripts),
        "sections": len(secs),
        "rule_like_lines": len(rules),
        "findings": check_limits(limits, fm, body, refs, text),
        "inventory": secs,
        "description": fm.get("description", ""),
    }


def overlap(skills: list[dict]) -> list[dict]:
    def words(s: dict) -> set[str]:
        return {w for w in re.findall(r"[a-zäöü]{4,}", s["description"].lower()) if w not in STOPWORDS}

    ws = [(s["skill"], words(s)) for s in skills]
    pairs = []
    for i in range(len(ws)):
        for j in range(i + 1, len(ws)):
            a, b = ws[i][1], ws[j][1]
            if a and b:
                sim = len(a & b) / len(a | b)
                if sim >= SIMILARITY_MIN:
                    pairs.append({"a": ws[i][0], "b": ws[j][0], "similarity": round(sim, 2)})
    return sorted(pairs, key=lambda p: -p["similarity"])


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252 and crash on arrows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(Path.home() / ".claude" / "skills"))
    ap.add_argument("--out", default=str(DATA))
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--summary", action="store_true", help="print one JSON line with the headline numbers")
    a = ap.parse_args()
    root = Path(a.root).expanduser()
    if not root.is_dir():
        print(f"not a folder: {root}. Pass --root with the folder that holds your skills.", file=sys.stderr)
        return 2
    limits = load_limits()
    skills = [s for d in sorted(root.iterdir()) if d.is_dir() for s in [scan_skill(d, limits)] if s]
    result = {"schema": 1, "root": str(root), "skills": skills, "overlap": overlap(skills)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "check.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if a.summary:
        hard = sum(1 for s in skills for f in s["findings"] if f["kind"] == "hard")
        top = sorted(skills, key=lambda s: -s["tokens_estimate"])[:3]
        print(json.dumps({"skills": len(skills), "findings": sum(len(s["findings"]) for s in skills), "hard": hard,
                          "top": [{"skill": s["skill"], "tokens": s["tokens_estimate"]} for s in top]}))
        return 0
    if a.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"{len(skills)} skills under {root}\n")
    print(f"{'skill':32} {'lines':>6} {'~tok':>7} {'~ref tok':>8} {'scripts':>7} {'rules':>6} {'findings':>8}")
    for s in sorted(skills, key=lambda s: -s["tokens_estimate"]):
        print(f"{s['skill'][:32]:32} {s['body_lines']:>6} {s['tokens_estimate']:>7} {s['reference_tokens_estimate']:>8} "
              f"{s['scripts']:>7} {s['rule_like_lines']:>6} {len(s['findings']):>8}")
    hard_list = [(s["skill"], f) for s in skills for f in s["findings"] if f["kind"] == "hard"]
    print(f"\n{sum(len(s['findings']) for s in skills)} limit findings, {len(hard_list)} hard")
    for name, f in hard_list:
        print(f"  HARD {name}: {f['limit']} ({f['detail']})")
    if result["overlap"]:
        print("\ndescription overlap (word similarity, first guess):")
        for p in result["overlap"][:8]:
            print(f"  {p['similarity']:.2f}  {p['a']}  <->  {p['b']}")
    print(f"\nfull result: {out / 'check.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
