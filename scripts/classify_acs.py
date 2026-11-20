#!/usr/bin/env python3
"""Sort the acceptance criteria of a draft into what can be checked how, and list what must be asked.

    python scripts/classify_acs.py <trace.json> [--out classified.json] [--grill grill.json]

Deterministic and conservative. Each AC gets one class, by the first rule that fits:
  ask        the sentence waits for a person (ask, confirm, approval, "his go", wait for)
  command    a literal outgoing command in the text (`gh pr merge`, `git push`, `npm publish`, an upload with curl):
             neither a judgement nor code to write. It stays one line in the skill; a test checks the call's arguments
  mechanic   something a script can measure: a named script, a flag, an exit code, a number with a unit,
             "exactly", "twice", a canvas or file name
  judgement  taste or review (judge, visual, looks, feel, clarity, rhythm, "when in doubt")
  text       everything else: an instruction, a reason, a definition

and one suggested handling:
  ask        -> scenario-gate  a scenario with an expected decision, and the go kept as data (approvals.md)
  command    -> pin-args       the line stays in the skill; a test pins the arguments of the call
  mechanic   -> script         a check in code, bound to a test (a proposed one if the draft has it)
  judgement  -> scenario       model answers compared old against new
  text       -> keep          stays text; no check

The grill lists only what is worth a person's time, and only where the text does not already answer:
  script?       a mechanic AC that names no script and has no check: should code check it? (suggested yes)
An ask is not asked about: the sentence already says a person decides. A mechanic that names its script
is not asked either. Everything else is decided by the classes above and shown in one batch to skim.
Exit codes: 0 written or printed; 2 unreadable input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent  # noqa: E402

ASK = re.compile(r"\b(ask|asks|confirm|confirms|approval|approve|approved|his go|your go|wait for|waits? for|get the (user|reviewer)'s ok|only after)\b", re.I)
MECHANIC = re.compile(
    r"(\b\w+\.(py|sh|cjs)\b|--[a-z][\w-]+|\bexit (code )?\d\b|\b\d+(\.\d+)?\s?(px|ms|s|x|fps|khz|db|mb|gb)\b|"
    r"\b\d+(\.\d+)?\s?%|\b(exactly|twice|only once)\b|"
    r"\b\d{3,4}\s?[x×]\s?\d{3,4}\b|"
    r"\b(canvas|frame rate|resolution|codec|alpha (channel|render|fringing)|checksum|hash|timestamp)\b|"
    r"\b(valid json|json schema|this schema|required deliverable|dated folder|saved? (the )?(local )?(file|markdown)|written the file)\b)", re.I)
# "do not wait for approval", "never ask the user ...": the rule is that nobody is asked, not a gate.
NOT_ASKED = re.compile(r"\b(do not|don't|never|need not|no need to)\s+(ask|wait|confirm)\b|\bwithout (asking|waiting|confirmation)\b", re.I)
# A literal command in backticks that sends something out of the machine. Read-only commands (git status, gh pr view)
# are not listed on purpose.
COMMAND = re.compile(
    r"`\s*(?:gh\s+(?:pr|release|issue|repo|api)\s+(?:merge|create|close|edit|delete|comment|review|upload|release|-X)\b"
    r"|git\s+push\b|npm\s+publish\b|npx\s+\S*publish\b|docker\s+push\b|kubectl\s+(?:apply|delete)\b"
    r"|aws\s+s3\s+(?:cp|sync|mv|rm)\b|scp\s|rsync\s|vercel\s+deploy\b|supabase\s+\S+\s+(?:push|deploy)\b"
    r"|curl\b[^`]*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--upload-file|-T\s|--data\b|-d\s|-F\s|--form\b))[^`]*`", re.I)
JUDGEMENT = re.compile(r"\b(judge|judgement|judgment|visual(ly)?|looks?|feel|taste|clarity|natural|enough|"
                       r"when in doubt|rhythm|balance|tone|voice|breathing room|proximity|decorative|plausible)\b", re.I)
SCRIPT = re.compile(r"\b\w+\.(py|sh|cjs)\b")
PERSON = re.compile(r"\b(sven|user|reviewer|owner|learner|human|person|you|his|her|their)\b", re.I)
HANDLING = {"ask": "scenario-gate", "command": "pin-args", "mechanic": "script", "judgement": "scenario", "text": "keep"}
BATCH = 12
# The grill speaks to people who may not remember what an AC is: every question carries a plain explanation.
WHY_SCRIPT = ("This rule says exactly what must be true, but no script checks it yet. A rule that only stands in the "
              "text is a request {agent} can skip under pressure; a script that checks it cannot be skipped. "
              "Say yes if the rule can be measured (a size, a flag, a count, a name). Say no if it is taste or a "
              "decision, then it stays as text or becomes a scenario.")


def as_list(check) -> list[dict]:
    """A check is None, one check or a list of checks; anything that is not a dict is ignored."""
    items = [] if check is None else check if isinstance(check, list) else [check]
    return [c for c in items if isinstance(c, dict)]


def classify(text: str) -> str:
    if ASK.search(text) and not NOT_ASKED.search(text):
        return "ask"
    if COMMAND.search(text):
        return "command"
    if MECHANIC.search(text):
        return "mechanic"
    if JUDGEMENT.search(text):
        return "judgement"
    return "text"


def load(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema_version", 1) != 1:
            raise ValueError(f"schema_version {doc['schema_version']!r}; this version reads 1")
        if not isinstance(doc.get("requirements"), list):
            raise ValueError("no requirements list")
        for r in doc["requirements"]:
            if not isinstance(r, dict) or not isinstance(r.get("acs"), list):
                raise ValueError("a requirement has no acs list")
            for a in r["acs"]:
                if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not isinstance(a.get("text"), str):
                    raise ValueError("an AC needs a text id and a text sentence")
        return doc
    except (OSError, ValueError, AttributeError) as e:
        raise ValueError(f"cannot read {path}: {e}") from None


def run(doc: dict) -> tuple[dict, dict]:
    """The classified document, and the grill: batches of questions with a suggested answer."""
    questions = []
    counts = {k: 0 for k in HANDLING}
    doc.setdefault("schema_version", 1)
    for r in doc["requirements"]:
        for a in r["acs"]:
            a["class"] = classify(a["text"])
            a["handling"] = HANDLING[a["class"]]
            counts[a["class"]] += 1
            has_real_check = any(not c.get("proposed") for c in as_list(a.get("check")))
            decided = bool(a.get("decision"))  # answered in an earlier run: do not ask twice
            if a["class"] == "mechanic" and not has_real_check and not decided and not SCRIPT.search(a["text"]):
                # measurable, but no script is named and no check exists: the one thing worth a person's answer
                questions.append({"ac": a["id"], "kind": "script?", "text": a["text"],
                                  "why": agent.say(WHY_SCRIPT), "suggest": "yes: check this in code and bind a test"})
    batches = [questions[i:i + BATCH] for i in range(0, len(questions), BATCH)]
    doc["classes"] = counts
    return doc, {"subject": doc.get("subject", ""), "counts": counts, "questions": len(questions), "batches": batches}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trace", type=Path)
    ap.add_argument("--out", type=Path, help="write the classified trace here (default: print the counts only)")
    ap.add_argument("--grill", type=Path, help="write the questions here")
    a = ap.parse_args()
    try:
        doc = load(a.trace)
    except ValueError as e:
        print(f"classify_acs: {e}", file=sys.stderr)
        return 2
    doc, grill = run(doc)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.grill:
        a.grill.parent.mkdir(parents=True, exist_ok=True)
        a.grill.write_text(json.dumps(grill, ensure_ascii=False, indent=1), encoding="utf-8")
    c = grill["counts"]
    print(f"{sum(c.values())} ACs: " + ", ".join(f"{k} {v}" for k, v in c.items())
          + f"; {grill['questions']} question{'s' if grill['questions'] != 1 else ''} for the grill in {len(grill['batches'])} batch(es)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
