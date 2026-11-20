#!/usr/bin/env python3
"""Turn a scan into what the right-hand view shows, in plain words, for people who are not technical.

    python scripts/view_model.py [--skill NAME] [--scan check.json] [--baseline-dir DIR]

Prints one JSON object:
  steps     the path the user walks, each with a state: done, current, later
  skills    every skill with a one-line verdict and its counts (largest problems first)
  selected  for --skill: plain sentences about that skill, and the proof status if requirements exist
  next      the ONE thing to do next: {"label", "why", "prompt", "available"}; the view shows it as a button
            and sends "prompt" into the chat. "prompt" is null when there is nothing to press: the label and
            "why" then say what is missing (no skill chosen, the hardening skill not installed, an
            unusual skill name).

The view never shows ids, hashes or file anchors; it speaks in sentences. Nothing here reads a skill's
files or changes anything: it only reads the scan result and, if present, the proof counts that
trace_check.py --status wrote. Skill names come from folder names and are untrusted: a name goes into a
prompt only when it is a plain slug.
Exit codes: 0 printed; 2 no readable scan, or the requested skill is not in it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent  # noqa: E402

DATA = Path.home() / ".shipwright" / "skill-check"
STEPS = [("scan", "Scan your skills"), ("pick", "Choose a skill"), ("harden", "Upgrade it, requirement by requirement"),
         ("keep", "Keep it safe when you change it")]
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")  # the shape Anthropic allows for a skill name
PROOF_KEYS = ("total", "passing", "failing", "gap", "other")

# One sentence per limit, written for someone who has never read the authoring guide. Hedged on purpose:
# Claude has fallbacks for several of these, so the sentences say what may go wrong, not what will.
PLAIN = {
    "name-required": "The skill has no name in its header, so it may not be listed the way you expect.",
    "name-max-length": "The name is too long.",
    "name-charset": "The name uses characters that are not allowed (only lowercase letters, numbers and hyphens).",
    "name-reserved-words": "The name contains a word that is reserved.",
    "description-required": "The skill has no description, so {agent} may not know when to use it.",
    "description-max-length": "The description is too long, so {agent} may cut it off and miss when to use the skill.",
    "no-xml-tags": "The name or description contains tag-like text that {agent} may misread.",
    "body-max-lines": "The main file is very long. A long skill is harder for {agent} to follow and costs more each time it is used.",
    "references-one-level": "A reference file points to another reference file, which {agent} may only half read.",
    "reference-toc-threshold": "A long reference file has no contents list, so {agent} may miss parts of it.",
    "forward-slash-paths": "A file path is written with backslashes, which breaks on other systems.",
}


def installed_harden(home: Path | None = None) -> bool:
    """True when the hardening skill can be started from here: a skill folder with a SKILL.md, either of
    your own or inside an installed plugin of that name. It does not check that the plugin is enabled."""
    home = home or Path.home()
    for skill, plugin in (("skill-upgrade", "skill-upgrade"), ("skill-upgrade", "shipwright-skill-upgrade"),
                          ("skill-harden", "shipwright-skill-harden")):
        if (home / ".claude" / "skills" / skill / "SKILL.md").is_file():
            return True
        cache = home / ".claude" / "plugins" / "cache"
        if cache.is_dir() and any(cache.glob(f"*/{plugin}/*/skills/{skill}/SKILL.md")):
            return True
    return False


def clean_proof(raw) -> dict | None:
    """The proof counts as written by trace_check.py --status, or None when the file is not that shape."""
    if not isinstance(raw, dict):
        return None
    if not all(isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool) and raw[k] >= 0 for k in PROOF_KEYS):
        return None
    out = {k: raw[k] for k in PROOF_KEYS}
    t = raw.get("text")
    out["text"] = t if isinstance(t, int) and not isinstance(t, bool) and t >= 0 else 0  # older files have no such key
    return out


STAGES = ("derived", "questions", "binding")


def clean_stage(raw) -> dict | None:
    """Where the hardening stands, as written by harden_state.py: only a stage that has a next step for the user."""
    if not isinstance(raw, dict):
        return None
    stage = raw.get("stage")
    if not isinstance(stage, dict) or stage.get("name") not in STAGES:
        return None
    n = stage.get("open")
    n = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0
    if n == 0 and stage["name"] != "derived":
        return None  # "answer 0 questions" is no next step
    return {"name": stage["name"], "open": n}


def thousands(n: int) -> str:
    return f"{n:,}".replace(",", "'")


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def verdict(skill: dict) -> tuple[str, str]:
    hard = sum(1 for f in skill["findings"] if f["kind"] == "hard")
    soft = len(skill["findings"]) - hard
    if hard:
        return "attention", f"{hard} {plural(hard, 'thing', 'things')} to fix" + (f", {soft} to consider" if soft else "")
    if soft:
        return "ok", f"{soft} {plural(soft, 'thing', 'things')} to consider"
    return "good", "Nothing to fix"


def words(tokens: int) -> str:
    """Tokens are jargon: say words (about three quarters of a token count), rounded."""
    w = tokens * 3 // 4
    return thousands(round(w, -1) if w >= 100 else w)


def describe(skill: dict) -> list[str]:
    out = [f"When it starts, {agent.NAME} reads about {words(skill['tokens_estimate'])} words of this skill"
           + (f", and up to {words(skill['reference_tokens_estimate'])} more if it opens the reference files." if skill["reference_tokens_estimate"] else ".")]
    n = skill["scripts"]
    if n:
        out.append(f"It has {n} {plural(n, 'script', 'scripts')}. A rule only holds when a script checks it and something makes sure the script runs.")
    else:
        out.append(f"It has no scripts, so every rule in it is a request that {agent.NAME} can skip under pressure.")
    r = skill["rule_like_lines"]
    if r:
        out.append(f"About {r} {plural(r, 'line reads', 'lines read')} like {plural(r, 'a rule', 'rules')} (must, never, always).")
    for f in skill["findings"]:
        out.append(agent.say(PLAIN.get(f["limit"], "A limit of the authoring guide is not met.")))
    return out


def next_step(scan_skills: list[dict], selected: dict | None, proof: dict | None, available: bool,
              stage: dict | None = None) -> dict:
    if selected is None:
        worst = max(scan_skills, key=lambda s: (sum(1 for f in s["findings"] if f["kind"] == "hard"), s["tokens_estimate"]),
                    default=None)
        why = "Pick the skill you rely on most. Start with one."
        if worst and SLUG.match(worst["skill"]) and any(f["kind"] == "hard" for f in worst["findings"]):
            why += f" {worst['skill']} has the most to fix."
        return {"label": "Choose a skill", "why": why, "prompt": None, "available": True}
    name = selected["skill"]
    if not SLUG.match(name):
        return {"label": "This skill's name is unusual",
                "why": "Its folder name has characters that are not allowed, so it cannot be hardened from here. Rename the folder first.",
                "prompt": None, "available": False}
    if not available:
        return {"label": "Skill Upgrade is not installed yet",
                "why": "The upgrade is done by a separate skill, Skill Upgrade. It is not on this machine yet, so there is nothing to press.",
                "prompt": None, "available": False}
    if stage:
        n = stage["open"]
        label, why = {
            "derived": ("Sort the rules", "The rules were read out of your skill. Next they are sorted by what a script can check."),
            "questions": (f"Answer {n} open {plural(n, 'question', 'questions')}",
                          "A few rules cannot be decided from the text. You answer them in one go, and each comes with a suggested answer."),
            "binding": (f"Connect {n} {plural(n, 'rule', 'rules')} to a check",
                        "These rules can be measured by a script but nothing checks them yet."),
        }[stage["name"]]
        return {"label": label, "why": why, "prompt": f'Use the skill-upgrade skill to continue on my skill "{name}".',
                "available": True}
    if proof and proof["total"] and proof["gap"] == proof["failing"] == proof["other"] == 0:
        return {"label": "Keep it safe",
                "why": ("Every requirement that a check can hold was proven at the last check"
                        + (f"; {proof['text']} {plural(proof['text'], 'rule stays', 'rules stay')} written text, as you decided" if proof["text"] else "")
                        + ". Check again after each change."),
                "prompt": f'Use the skill-upgrade skill to check my skill "{name}" against its baseline after my latest change.',
                "available": True}
    if proof and proof["total"]:
        broken, loose = proof["failing"], proof["gap"] + proof["other"]
        n = broken + loose
        parts = []
        if broken:
            parts.append(f"{broken} {plural(broken, 'check fails', 'checks fail')}")
        if loose:
            parts.append(f"{loose} {plural(loose, 'is', 'are')} not proven yet")
        return {"label": f"Prove the {n} open {plural(n, 'requirement', 'requirements')}",
                "why": f"{proof['passing']} of {proof['total']} {plural(proof['total'], 'requirement is', 'requirements are')} proven at the last check; "
                       + " and ".join(parts) + ".",
                "prompt": f'Use the skill-upgrade skill to prove the open requirements of my skill "{name}".', "available": True}
    return {"label": "Upgrade this skill",
            "why": "Turn the rules in this skill into checks that run on their own. Nothing changes until you agree.",
            "prompt": f'Use the skill-upgrade skill on my skill "{name}".', "available": True}


def build(scan: dict, selected_name: str | None = None, proof: dict | None = None, available: bool = False) -> dict:
    if not isinstance(scan, dict) or not isinstance(scan.get("skills"), list):
        raise ValueError("the scan has no skills list")
    stage = clean_stage(proof)
    proof = clean_proof(proof)
    skills = sorted(scan["skills"], key=lambda s: (-sum(1 for f in s["findings"] if f["kind"] == "hard"),
                                                  -s["tokens_estimate"]))
    selected = next((s for s in skills if s["skill"] == selected_name), None)
    if selected_name and selected is None:
        raise KeyError(selected_name)
    done = bool(selected and available and proof and proof["total"] and proof["gap"] == proof["failing"] == proof["other"] == 0)
    current = "pick" if selected is None else "keep" if done else "harden"
    order = [s[0] for s in STEPS]
    steps = [{"id": i, "label": label,
              "state": "done" if order.index(i) < order.index(current) else "current" if i == current else "later"}
             for i, label in STEPS]
    out = {"steps": steps,
           "skills": [{"name": s["skill"], "verdict": verdict(s)[0], "headline": verdict(s)[1],
                       "tokens": s["tokens_estimate"]} for s in skills],
           "selected": None,
           "next": next_step(skills, selected, proof, available, stage)}
    if selected:
        out["selected"] = {"name": selected["skill"], "verdict": verdict(selected)[1],
                           "sentences": describe(selected), "proof": proof}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skill")
    ap.add_argument("--scan", type=Path, default=DATA / "check.json")
    ap.add_argument("--baseline-dir", type=Path, default=DATA / "baseline")
    a = ap.parse_args()
    try:
        scan = json.loads(a.scan.read_text(encoding="utf-8"))
        names = {s["skill"] for s in scan["skills"]}
    except (OSError, ValueError, KeyError, TypeError):
        print(f"no readable scan at {a.scan}: run scripts/check_skills.py first", file=sys.stderr)
        return 2
    if a.skill and a.skill not in names:
        print(f"no skill {a.skill} in the scan", file=sys.stderr)
        return 2
    proof = None
    if a.skill:  # only a scanned name ever becomes part of a path
        t = a.baseline_dir / a.skill / "status.json"  # written by trace_check.py --status
        try:
            proof = json.loads(t.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            proof = None
    try:
        model = build(scan, a.skill, proof, installed_harden())
    except (KeyError, ValueError, TypeError):
        print("the scan is not in the expected shape: run scripts/check_skills.py again", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(model, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
