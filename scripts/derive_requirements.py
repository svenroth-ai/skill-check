#!/usr/bin/env python3
"""Draft the requirements of a skill from its own text: one acceptance criterion (AC) per rule or gate line.

    python scripts/derive_requirements.py <skill folder> [--out trace.json]

Deterministic. Nothing is asked and nothing is judged here. The draft has three parts:
  requirement   one per top-level section that holds at least one rule or gate line
  AC            one per such line, with its source (file and section) and the line itself as the sentence
  proposed check  if the skill has tests, the tests that share the most words with the sentence, and the
                  scripts the sentence names, are proposed with "proposed": true

A proposed check is a guess by word overlap. trace_check.py reports it as "proposed", never as "passing",
until a reviewer reads it, keeps it and removes the flag. The draft is the start of the grill, not the end:
what cannot be derived (conflicts, which rules are hard stops, thresholds) is asked afterwards.
Exit codes: 0 written or printed; 2 the folder has no SKILL.md; 3 --out exists and --force was not given.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

import derive_scenarios as ds

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "it", "this", "that", "with",
        "as", "be", "not", "no", "never", "always", "must", "do", "does", "if", "then", "when", "before", "after",
        "test", "tests", "from", "by", "at", "has", "have", "was", "were", "you", "your", "all", "any", "its"}
MAX_PROPOSED = 3
MIN_OVERLAP = 1  # a script is named AND one more word is shared


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9]{2,}", text.lower().replace("_", " ")) if w not in STOP}


def test_index(skill: Path) -> list[dict]:
    """Every unittest of the skill: {"id": "module.Class.test_x", "words": {...}, "module": "test_x"}"""
    out = []
    for f in sorted((skill / "tests").glob("test_*.py")) if (skill / "tests").is_dir() else []:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]:
                out.append({"id": f"{f.stem}.{cls.name}.{fn.name}", "module": f.stem,
                            "words": words(fn.name) | words(cls.name)})
    return out


def propose(text: str, tests: list[dict], script_stems: set[str]) -> list[dict]:
    """Only when the sentence names a script: that script's tests which share a word with the sentence.
    No script named, or no shared word: no proposal. A wrong guess is worse than none."""
    named = {s for s in script_stems if re.search(rf"(?<![A-Za-z0-9_]){re.escape(s)}(?![A-Za-z0-9_])", text)}
    if not named:
        return []
    own = {x for s in named for x in words(s)}
    w = words(text) - own
    scored = []
    for t in tests:
        if not any(s in t["module"] for s in named):
            continue
        shared = len(w & (t["words"] - own - {"test"}))
        if shared >= MIN_OVERLAP:
            scored.append((shared, t["id"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"kind": "test", "id": tid, "proposed": True} for _s, tid in scored[:MAX_PROPOSED]]


SCHEMA_VERSION = 1  # the shape of trace.json; other tools write and read it, change it only with a new number
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
SENT_END = re.compile(r"(?<=[.!?:;])\s+(?=[A-Z*(\"“])")
ABBREV = re.compile(r"(e\.g|i\.e|etc|vs|cf)\.")


def paragraphs(lines: list[str]) -> list[str]:
    """Lines joined into the units a reader sees: a bullet, a table row, a paragraph. Code fences are skipped."""
    out, cur, fence = [], [], False
    def flush():
        if cur:
            out.append(" ".join(x.strip() for x in cur))
            cur.clear()
    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            flush()
            fence = not fence
            continue
        if fence:
            continue
        if not s or s.startswith("#") or s.startswith("|"):
            flush()
            if s.startswith("|"):
                out.append(s)
            continue
        if BULLET.match(ln):
            flush()
        cur.append(ln)
    flush()
    return out


def holds(sentence: str, kind: str) -> bool:
    if kind == "rule":
        return bool(ds.cs.RULE.search(sentence))
    return bool(ds.GATE.search(sentence) and ds.GATE_CONTEXT.search(sentence))


def sentences_of(paras: list[str], line: str, kind: str) -> list[str]:
    """The sentences of the paragraph that overlap the seed line and really hold the rule or gate,
    so an AC reads as a whole thought and a line that wraps in the middle of one is not cut."""
    s = line.strip()
    for para in paras:
        at = para.find(s)
        if at < 0:
            continue
        spans, start = [], 0
        masked = ABBREV.sub(lambda m: m.group(0).replace(".", ""), para)  # same length: offsets stay valid
        for m in SENT_END.finditer(masked):
            spans.append((start, m.start()))
            start = m.end()
        spans.append((start, len(para)))
        hit = [sp for sp in spans if sp[0] < at + len(s) and sp[1] > at]
        sents = [para[a:b] for a, b in hit] or [para]
        return [x for x in sents if holds(x, kind)] or sents[:1]
    return [s]


def clean(line: str) -> str:
    s = re.sub(r"^[\s>*\-|]+", "", line)
    s = re.sub(r"[*`]", "", s).strip()
    return s[:240]


def derive(skill: Path) -> dict:
    seeds = ds.seeds_for(skill)
    tests = test_index(skill)
    stems = {p.stem for p in (skill / "scripts").glob("*.py")} if (skill / "scripts").is_dir() else set()
    paras = {}
    for s in seeds:
        if s["file"] not in paras:
            paras[s["file"]] = paragraphs((skill / s["file"]).read_text(encoding="utf-8-sig").splitlines())
    groups: dict[tuple[str, str], list[dict]] = {}
    for s in seeds:
        top = s["path"].split(" > ")[:2]
        groups.setdefault((s["file"], " > ".join(top)), []).append(s)
    reqs, seen_text = [], set()
    for n, ((file, top), items) in enumerate(groups.items(), 1):
        acs = []
        for s in items:
            for sentence in sentences_of(paras[s["file"]], s["text"], s["kind"]):
                text = clean(sentence)
                if not text or text in seen_text:
                    continue
                seen_text.add(text)
                chk = propose(text, tests, stems)
                acs.append({"id": f"AC-{n}.{len(acs) + 1}", "text": text, "source": f"{file}: {s['path']}",
                            "check": chk or None, "seed": s["id"], "seed_kind": s["kind"]})
        acs = [a for a in acs if not any(a is not b and a["text"] != b["text"] and a["text"] in b["text"] for b in acs)]
        for i, a in enumerate(acs, 1):
            a["id"] = f"AC-{n}.{i}"
        if acs:
            reqs.append({"id": f"REQ-{n}", "text": top.split(" > ")[-1] or file, "acs": acs})
    return {"schema_version": SCHEMA_VERSION, "subject": skill.name, "draft": True, "requirements": reqs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skill", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out file (the earlier bindings and decisions are lost)")
    a = ap.parse_args()
    if not (a.skill / "SKILL.md").is_file():
        print(f"{a.skill} has no SKILL.md: pass the skill folder", file=sys.stderr)
        return 2
    if a.out and a.out.exists() and not a.force:
        print(f"{a.out} exists: it holds earlier bindings and decisions, so it is not overwritten. "
              "Continue from it, or pass --force to start the draft again.", file=sys.stderr)
        return 3
    doc = derive(a.skill)
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    n = sum(len(r["acs"]) for r in doc["requirements"])
    prop = sum(1 for r in doc["requirements"] for c in r["acs"] if c["check"])
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(f"{len(doc['requirements'])} requirements, {n} ACs, {prop} with a proposed check, {n - prop} without -> {a.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
