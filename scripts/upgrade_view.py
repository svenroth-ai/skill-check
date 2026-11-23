#!/usr/bin/env python3
"""What the Questions and Report pages of the view show for one skill (read only).

The facts come from the skill's own baseline folder, written by Skill Upgrade:
  trace.json    the instructions (requirements and acceptance criteria), their checks and decisions
  grill.json    the open questions, each with a plain explanation and a suggested answer
  status.json   (in the Skill Check data folder) the stage and, per criterion, the result of trace_check.py
Nothing here runs a skill's code: a result is only reported when trace_check.py wrote it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import skill_origin
import skill_score

SAFE_AC = re.compile(r"[\w.-]{1,64}")


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def questions(skill: Path) -> list[dict]:
    grill, trace = _json(skill / "baseline" / "grill.json"), _json(skill / "baseline" / "trace.json")
    if not isinstance(grill, dict) or not isinstance(trace, dict):
        return []
    done = {a["id"] for r in trace.get("requirements", []) for a in r.get("acs", [])
            if isinstance(a, dict) and (a.get("decision") or any(not c.get("proposed") for c in skill_score.ca.as_list(a.get("check"))))}
    out = []
    for batch in grill.get("batches", []):
        for q in batch:
            if isinstance(q, dict) and q.get("ac") and q["ac"] not in done:
                out.append({"ac": q["ac"], "text": q.get("text", ""), "why": q.get("why", ""),
                            "suggest": "no" if str(q.get("suggest", "")).lower().startswith("no") else "yes"})
    return out


def report(skill: Path, status: dict | None) -> dict | None:
    """Per part: instructions, enforced before (a shipped script names it) and enforced now (its check passes)."""
    trace = _json(skill / "baseline" / "trace.json")
    acs = (status or {}).get("acs")
    if not isinstance(trace, dict) or not isinstance(acs, dict):
        return None
    scripts = skill_score.shipped_scripts(skill)
    parts, T = [], {"total": 0, "hold": 0, "before": 0, "now": 0, "text": 0}
    for r in trace.get("requirements", []):
        t = h = b = n = x = 0
        for a in r.get("acs", []):
            t += 1
            holds = a.get("class") in skill_score.HOLDS
            h += holds
            b += skill_score.is_enforced(a, scripts)
            st = acs.get(a["id"])
            n += st == "passing"
            x += st == "text" or not holds
        for k, v in (("total", t), ("hold", h), ("before", b), ("now", n), ("text", x)):
            T[k] += v
        parts.append({"name": r.get("text", ""), "total": t, "hold": h, "before": b, "now": n, "text": x,
                      "status": "all" if h and n >= h else "open" if h else "text"})
    T["pct_now"] = skill_score.pct(T["now"], T["hold"])
    return {"parts": parts, "totals": T, "open_checks": sum(1 for s in acs.values() if s in ("gap", "proposed", "not-run", "failing", "dangling"))}


def control(skill: Path, status: dict | None) -> dict | None:
    """The written list, part by part, and how each line is held: a passing check ("test") or prose that stays text.
    None until the skill has been through the checks. A line without a passing check is "open"."""
    trace = _json(skill / "baseline" / "trace.json")
    acs = (status or {}).get("acs")
    if not isinstance(trace, dict) or not isinstance(acs, dict):
        return None
    parts, T = [], {"lines": 0, "tests": 0, "prose": 0, "open": 0}
    for r in trace.get("requirements", []):
        lines = []
        for a in r.get("acs", []):
            st = acs.get(a["id"])
            kind = "test" if st == "passing" else "prose" if st == "text" or a.get("class") not in skill_score.HOLDS else "open"
            lines.append({"text": a["text"], "kind": kind})
        c = {k: sum(1 for x in lines if x["kind"] == k) for k in ("test", "prose", "open")}
        T["lines"] += len(lines)
        T["tests"] += c["test"]
        T["prose"] += c["prose"]
        T["open"] += c["open"]
        parts.append({"name": r.get("text", ""), "lines": lines, "tests": c["test"], "prose": c["prose"], "open": c["open"]})
    approved = _json(skill / "baseline" / "approved.json")
    return {"parts": parts, "totals": T, "controlled_at": (status or {}).get("controlled_at") or None,
            "approved": isinstance(approved, dict)}


def stage(skill: Path, status: dict | None, open_questions: int) -> tuple[str, int]:
    """Where the upgrade stands, from the status file, corrected by what the skill's baseline folder says now:
    a question answered in the chat moves the stage on before the next status file is written."""
    st = (status or {}).get("stage") or {}
    name, n = st.get("name", "none"), st.get("open", 0)
    if name in ("none", "questions", "derived") and (skill / "baseline" / "trace.json").is_file():
        if open_questions:
            return "questions", open_questions
        if name in ("none", "questions") and (skill / "baseline" / "grill.json").is_file():
            return "binding", n
        if name == "none":
            return "derived", n
    return name, n


def read(skill: Path, status: dict | None) -> dict:
    qs = questions(skill)
    name, n = stage(skill, status, len(qs))
    return {"skill": skill.name, "stage": name, "open": n,
            "questions": qs, "report": report(skill, status), "control": control(skill, status),
            "origin": skill_origin.origin(skill)}
