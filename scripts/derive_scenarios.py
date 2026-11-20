#!/usr/bin/env python3
"""Derive scenario seeds from a skill: the decision points that a rebuilt version must keep.

    python scripts/derive_scenarios.py <skill folder> [--out seeds.json]

A seed is one line of the skill that sets a rule or a gate, with its anchor (file, heading path, section
hash) so it ties back to the inventory. Seeds come from the ORIGINAL skill only: a rebuilt version is judged
against what the old one demanded, never against itself.

Kinds:
  rule  a line with must, never, always, do not, required ... (the RULE pattern of check_skills.py)
  gate  a line where the skill waits for a person or a check: "ask", "wait", "go", "approve", "confirm",
        "stop", "block", "gate", "only after", "before ... until"

The seeds are the deterministic half. Turning them into concrete inputs with an expected decision needs
judgment and is done by a reviewer (the schema of the result files is described in Skill Upgrade).
Exit codes: 0 written; 2 folder or SKILL.md missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import re

import check_skills as cs

GATE = re.compile(
    r"\b(ask|asks|wait|waits|go|approve|approved|approval|confirm|confirmed|stop|block|blocked|gate|gates|"
    r"only after|until|before)\b",
    re.I,
)
# A gate word alone is weak ("go" is also a verb). A gate seed needs a gate word AND one of these.
GATE_CONTEXT = re.compile(r"\b(sven|user|human|person|ok|yes|review|qa|check|verify|explicit|before|after)\b", re.I)
MIN_CHARS = 12  # shorter lines are labels or table scraps, not decisions


def seeds_for(skill: Path) -> list[dict]:
    md = skill / "SKILL.md"
    text = cs.read_text(md)
    fm, _body, fm_lines = cs.split_frontmatter(text)
    files = {"SKILL.md": text.lstrip("﻿").splitlines()}
    refs = skill / "references"
    if refs.is_dir():
        for p in sorted(refs.rglob("*.md")):
            files[p.relative_to(skill).as_posix()] = cs.read_text(p).splitlines()
    out = []
    for rel, lines in files.items():
        for sec in cs.sections(rel, lines, preamble_lines=fm_lines if rel == "SKILL.md" else 0, keep_text=True):
            for line in sec["lines"]:
                s = line.strip()
                if len(s) < MIN_CHARS or s.startswith("#") or s.startswith("```"):
                    continue
                kinds = []
                if cs.RULE.search(s):
                    kinds.append("rule")
                if GATE.search(s) and GATE_CONTEXT.search(s):
                    kinds.append("gate")
                for kind in kinds:
                    sid = hashlib.sha256(f"{rel}|{sec['path']}|{s}".encode("utf-8")).hexdigest()[:10]
                    out.append({"id": f"{kind[0]}-{sid}", "kind": kind, "file": rel, "path": sec["path"],
                                "section_hash": sec["hash"], "text": s})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skill", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if not (a.skill / "SKILL.md").is_file():
        print(f"{a.skill} has no SKILL.md: pass the skill folder", file=sys.stderr)
        return 2
    seeds = seeds_for(a.skill)
    doc = {"skill": a.skill.name, "seeds": seeds,
           "counts": {k: sum(1 for s in seeds if s["kind"] == k) for k in ("rule", "gate")}}
    text = json.dumps(doc, ensure_ascii=False, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(f"{len(seeds)} seeds ({doc['counts']['rule']} rule, {doc['counts']['gate']} gate) -> {a.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
