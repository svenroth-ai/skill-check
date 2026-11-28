#!/usr/bin/env python3
"""What a skill is for, in the words its owner agreed to: the intent of the skill (read only, except the verbs below).

    python skill_intent.py <skill folder>                          print the intent as JSON (written, or derived)
    python skill_intent.py write   <skill folder> --file F.json    save a proposal written by Skill Upgrade
    python skill_intent.py confirm <skill folder> --keep-non-goals NG-1,NG-3 | none
    python skill_intent.py diff    <skill folder>                  what changed since the owner confirmed it
    python skill_intent.py assign  <skill folder> --trace trace.json [--set AC-1.2=CAP-3|ALL ...]

The intent has four levels, the owner owns the first three and the AI the last:
  purpose       what the skill does and for whom, at most 80 words
  non-goals     what the skill must never do, at most 5; the owner keeps only the ones they tick
  capabilities  what the skill can do, 1 to 5, each one sentence of at most 30 words
  scenarios     "you ask X, the skill does Y, you get Z", 1 to 5, each naming the capabilities it uses
  instructions  the rules in trace.json; each gets one capability, or ALL for a rule for everything (`assign`)

Every element is an "assumption" until the owner confirms it. `confirm` keeps a copy of the confirmed text and its
fingerprint; a later `write` keeps "confirmed" only where the text is unchanged, and `diff` lists old against new.
Without baseline/intent.json the intent is derived from SKILL.md: its description is the purpose, its sections are
the capabilities, its "never" sentences the non-goals. Nothing here runs a skill's code.
Exit codes: 0 done (diff: nothing changed); 1 diff: something changed; 2 bad input; 3 refused (see the message).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

PURPOSE_WORDS = 80
CAP_WORDS = 30
MAX_CAPS = 5
MAX_SCENARIOS = 5
MAX_NON_GOALS = 5
MAX_TEXT = 320
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "it", "this", "that", "with", "as",
        "be", "not", "no", "never", "always", "must", "do", "does", "if", "then", "when", "before", "after", "from", "by",
        "at", "has", "have", "you", "your", "all", "any", "its", "can", "will", "each", "one", "skill", "user", "claude",
        "use", "uses", "using", "into", "only", "out", "get", "gets", "via", "per", "but", "than", "which", "what"}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _path(skill: Path) -> Path:
    return skill / "baseline" / "intent.json"


def plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\\([^\w\s])", r"\1", s)
    s = re.sub(r"[*`_]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def cut(s: str, n: int = MAX_TEXT) -> str:
    if len(s) <= n:
        return s
    head = s[:n]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1] if end > n // 2 else head.rstrip(" ,;:") + "..."


def nwords(s: str) -> int:
    return len(s.split())


def words(s: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z][a-z0-9-]{2,}", s.lower().replace("_", " ")):
        w = w.strip("-")
        if w.endswith("s") and len(w) > 4:
            w = w[:-1]
        if w and w not in STOP:
            out.add(w)
    return out


# ---------- derived from SKILL.md, when nothing is written ----------

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
    para, items, code = [], [], False
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
        elif not items:
            para.append(plain(t))
    return cut(" ".join(para) if para else " ".join(items[:2]))


NEVER = re.compile(r"(?:^|(?<=[.!?]\s))((?:Never|Do not|Don't|Must not)\b[^.!?\n]{8,160}[.!?]?)", re.M)


def derive(skill: Path) -> dict:
    meta, body = front(_read(skill / "SKILL.md"))
    sections, cur, name = [], [], None
    level = 2 if re.search(r"^## ", body, re.M) else 1
    mark = "#" * level + " "
    code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            code = not code
        if line.startswith(mark) and not code:
            if name:
                sections.append((name, cur))
            name, cur = plain(line[len(mark):]), []
        elif name is not None:
            cur.append(line)
    if name:
        sections.append((name, cur))
    caps = [{"name": n, "text": t} for n, t in ((n, first_words(ls)) for n, ls in sections) if t][:MAX_CAPS]
    seen, nongoals = set(), []
    for m in NEVER.finditer(re.sub(r"```.*?```", "", body, flags=re.S)):
        t = plain(m.group(1)).rstrip(".!?") + "."
        if t.lower() not in seen:
            seen.add(t.lower())
            nongoals.append(t)
    doc = number({"purpose": cut(plain(meta.get("description", ""))), "non_goals": nongoals[:MAX_NON_GOALS],
                  "capabilities": caps, "scenarios": []})
    doc["source"] = "derived"
    return doc


# ---------- written by Skill Upgrade ----------

def keep_ids(items: list[dict], prev: list[dict], prefix: str, keys, used: tuple = ()) -> None:
    """Give each item the id of the earlier element it matches, else the next free number, so an id never moves to
    another element when the list is reordered, shortened or grown. The first key is matched for all items before the
    next key is tried, so a text match can never take an id that another item keeps by name. `used` are ids seen
    before (also ones dropped since): a new element never gets one of them."""
    taken, nums = set(), [0]
    for i in [p.get("id", "") for p in prev] + list(used):
        try:
            nums.append(int(str(i).rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            pass
    for key in keys:
        for it in items:
            if "id" in it:
                continue
            hit = next((p["id"] for p in prev if p.get("id") not in taken and key(p) and key(p) == key(it)), None)
            if hit:
                it["id"] = hit
                taken.add(hit)
    nxt = max(nums) + 1
    for it in items:
        if "id" not in it:
            it["id"] = f"{prefix}-{nxt}"
            nxt += 1


def number(raw: dict, old: dict | None = None) -> dict:
    """Ids by code, never by hand: NG-n, CAP-n, SCN-n, kept from the earlier version where an element is the same.
    A scenario names its capabilities by name or by id."""
    old = old or {}
    caps = [{"name": plain(str(c.get("name", ""))), "text": plain(str(c.get("text", ""))), "status": "assumption"}
            for c in raw.get("capabilities") or [] if isinstance(c, dict)]
    keep_ids(caps, old.get("capabilities") or [], "CAP", (lambda c: c.get("name", "").lower(), lambda c: c.get("text")))
    by = {c["id"].lower(): c["id"] for c in caps} | {c["name"].lower(): c["id"] for c in caps}
    scns = []
    for s in raw.get("scenarios") or []:
        s = s if isinstance(s, dict) else {"text": s}
        names = [str(x).strip().lower() for x in s.get("caps") or []]
        scns.append({"text": plain(str(s.get("text", ""))), "caps": list(dict.fromkeys(by[x] for x in names if x in by)),
                     "unknown": [x for x in names if x not in by], "status": "assumption"})
    keep_ids(scns, old.get("scenarios") or [], "SCN", (lambda s: s.get("text"),))
    ngs = [{"text": plain(str(t.get("text", "") if isinstance(t, dict) else t)), "status": "assumption"}
           for t in raw.get("non_goals") or [] if isinstance(t, (dict, str))]
    keep_ids(ngs, old.get("non_goals") or [], "NG", (lambda n: n.get("text"),),
             used=tuple((old.get("snapshot") or {}).get("non_goals", {})) + tuple(old.get("dropped_non_goals", [])))
    return {"purpose": plain(str(raw.get("purpose", ""))), "purpose_status": "assumption",
            "non_goals": ngs, "capabilities": caps, "scenarios": scns}


def problems(doc: dict) -> list[str]:
    """What a proposal breaks. Empty when it can be saved."""
    out = []
    if not doc["purpose"]:
        out.append('"purpose" is missing')
    elif nwords(doc["purpose"]) > PURPOSE_WORDS:
        out.append(f"the purpose has {nwords(doc['purpose'])} words; at most {PURPOSE_WORDS}")
    if not 1 <= len(doc["capabilities"]) <= MAX_CAPS:
        out.append(f"{len(doc['capabilities'])} capabilities; between 1 and {MAX_CAPS}")
    for c in doc["capabilities"]:
        if not c["name"] or not c["text"]:
            out.append(f"{c['id']} needs a name and a text")
        elif nwords(c["text"]) > CAP_WORDS:
            out.append(f"{c['id']} ({c['name']}) has {nwords(c['text'])} words; at most {CAP_WORDS}")
    if len({c["name"].lower() for c in doc["capabilities"]}) < len(doc["capabilities"]):
        out.append("two capabilities have the same name")
    if not 1 <= len(doc["scenarios"]) <= MAX_SCENARIOS:
        out.append(f"{len(doc['scenarios'])} scenarios; between 1 and {MAX_SCENARIOS}")
    for s in doc["scenarios"]:
        if not s["text"]:
            out.append(f"{s['id']} has no text")
        if s.get("unknown"):
            out.append(f"{s['id']} names a capability that does not exist: {', '.join(s['unknown'])}")
        elif not s["caps"]:
            out.append(f"{s['id']} names no capability (use their names in \"caps\")")
    if len(doc["non_goals"]) > MAX_NON_GOALS:
        out.append(f"{len(doc['non_goals'])} non-goals; at most {MAX_NON_GOALS}")
    if any(not n["text"] for n in doc["non_goals"]):
        out.append("a non-goal has no text")
    return out


def snapshot(doc: dict) -> dict:
    return {"purpose": doc["purpose"],
            "non_goals": {n["id"]: n["text"] for n in doc["non_goals"]},
            "capabilities": {c["id"]: f"{c['name']}: {c['text']}" for c in doc["capabilities"]},
            "scenarios": {s["id"]: s["text"] for s in doc["scenarios"]}}


def fingerprint(snap: dict) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def load(skill: Path) -> dict | None:
    try:
        doc = json.loads(_path(skill).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("capabilities"), list):
        return None
    return doc


def intent(skill: Path) -> dict:
    doc = load(skill)
    if doc is None:
        return derive(skill)
    doc["source"] = "written"
    doc["confirmed"] = is_confirmed(doc)
    doc.pop("snapshot", None)
    return doc


def is_confirmed(doc: dict | None) -> bool:
    """True only when the description as it stands now is exactly what the owner confirmed: nothing changed, added,
    removed or renumbered since."""
    fp = (doc or {}).get("fingerprint")
    return bool(fp) and fingerprint(snapshot(doc)) == fp


def write(skill: Path, raw: object) -> tuple[int, str]:
    if not isinstance(raw, dict):
        return 2, "the proposal must be a JSON object"
    old = load(skill) or {}
    doc = number(raw, old)
    bad = problems(doc)
    if bad:
        return 3, "Not saved: " + "; ".join(bad) + "."
    for s in doc["scenarios"]:
        s.pop("unknown", None)
    snap = old.get("snapshot") or {}
    if snap:  # what the owner confirmed stays confirmed while its words are the same
        if doc["purpose"] == snap.get("purpose"):
            doc["purpose_status"] = "confirmed"
        mine = snapshot(doc)
        for k in ("non_goals", "capabilities", "scenarios"):
            for x in doc[k]:
                if mine[k][x["id"]] in snap.get(k, {}).values():
                    x["status"] = "confirmed"
        doc["snapshot"], doc["confirmed_at"], doc["fingerprint"] = snap, old.get("confirmed_at"), old.get("fingerprint")
    if old.get("dropped_non_goals"):
        doc["dropped_non_goals"] = old["dropped_non_goals"]
    p = _path(skill)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    c, s, n = len(doc["capabilities"]), len(doc["scenarios"]), len(doc["non_goals"])
    msg = f"intent saved: {c} capabilities, {s} scenarios, {n} non-goals"
    if snap and not is_confirmed(doc):
        msg += ". It differs from what the owner confirmed: show old against new (skill_intent.py diff) and confirm again"
    trace = skill / "baseline" / "trace.json"
    if trace.is_file():  # the instructions follow the description at once
        code, more = assign(skill, trace, {})
        msg += "\n" + more
        if code:
            return code, msg + "\nThe description is saved, but the instructions could not be tied to it."
    return 0, msg


def confirm(skill: Path, keep: str) -> tuple[int, str]:
    doc = load(skill)
    if doc is None:
        return 2, "There is no proposal yet: write one first."
    ids = {n["id"] for n in doc.get("non_goals", [])}
    want = set() if keep.strip().lower() == "none" else {k.strip().upper() for k in keep.split(",") if k.strip()}
    if not want and keep.strip().lower() != "none":
        return 2, "name the non-goals to keep (NG-1,NG-3), or none"
    if want - ids:
        return 2, f"no such non-goal: {', '.join(sorted(want - ids))}"
    doc["dropped_non_goals"] = sorted(set(doc.get("dropped_non_goals", [])) | (ids - want))
    doc["non_goals"] = [n for n in doc.get("non_goals", []) if n["id"] in want]
    doc["purpose_status"] = "confirmed"
    for k in ("non_goals", "capabilities", "scenarios"):
        for x in doc.get(k, []):
            x["status"] = "confirmed"
    doc["snapshot"] = snapshot(doc)
    doc["fingerprint"] = fingerprint(doc["snapshot"])
    doc["confirmed_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _path(skill).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0, (f"confirmed: {len(doc['capabilities'])} capabilities, {len(doc['scenarios'])} scenarios, "
               f"{len(doc['non_goals'])} non-goals kept (stand {doc['fingerprint'][:6]})")


def changes(skill: Path) -> list[dict]:
    """Old against new for every element that differs from what the owner confirmed. Empty when nothing changed,
    or when nothing was confirmed yet."""
    doc = load(skill)
    snap = (doc or {}).get("snapshot")
    if not doc or not snap:
        return []
    now = snapshot(doc)
    out = []
    if now["purpose"] != snap.get("purpose"):
        out.append({"id": "purpose", "old": snap.get("purpose", ""), "new": now["purpose"]})
    for k in ("non_goals", "capabilities", "scenarios"):  # by text, so a new order is no change
        old, new = snap.get(k, {}), now[k]
        gone = [(i, t) for i, t in old.items() if t not in new.values()]
        came = [(i, t) for i, t in new.items() if t not in old.values()]
        for n in range(max(len(gone), len(came))):
            o, c = gone[n] if n < len(gone) else (None, None), came[n] if n < len(came) else (None, None)
            out.append({"id": c[0] or o[0], "old": o[1], "new": c[1]})
    return out


# ---------- every instruction to one capability ----------

ALL = "ALL"  # a rule for everything the skill does (its language, where it saves), not for one capability
ALL_NAME = "For everything it does"


def assign(skill: Path, trace: Path, manual: dict[str, str]) -> tuple[int, str]:
    """Each instruction to the capability its words point to clearly; else to the capability its part of the skill
    points to; else to ALL. A rare word counts more than a word many capabilities share. A choice by hand stays."""
    doc = load(skill)
    try:
        tr = json.loads(trace.read_text(encoding="utf-8"))
        reqs = tr["requirements"]
    except (OSError, ValueError, KeyError, TypeError):
        return 2, f"cannot read {trace}"
    if not doc or not doc.get("capabilities"):
        return 2, "There is no intent yet: write one first."
    caps = doc["capabilities"]
    ids = {c["id"] for c in caps} | {ALL}
    bad = {v for v in manual.values() if v not in ids}
    if bad:
        return 2, f"no such capability: {', '.join(sorted(bad))}"
    known = {a["id"] for r in reqs for a in r.get("acs", [])}
    if set(manual) - known:
        return 2, f"no such instruction: {', '.join(sorted(set(manual) - known))}"
    common = words(doc.get("purpose", ""))  # a scenario word the purpose also has is about the whole skill
    vocab = {c["id"]: words(c["name"] + " " + c["text"]) | (words(" ".join(
        s["text"] for s in doc.get("scenarios", []) if c["id"] in s.get("caps", []))) - common) for c in caps}
    names = {c["id"]: words(c["name"]) for c in caps}
    df: dict[str, int] = {}
    for v in vocab.values():
        for w in v:
            df[w] = df.get(w, 0) + 1
    n_caps = len(caps)

    def weight(ws: set[str]) -> float:
        # a word every capability has tells nothing; a word only one has tells the most
        return sum(1 / df[w] for w in ws if df.get(w, n_caps) < n_caps or n_caps == 1)

    def best(text: str, heading: str, need: float = 1.5) -> str | None:
        w, h = words(text), words(heading)
        # the part's heading counts double only when it is the capability's name ("Reference images"), not when
        # they share a word ("Quick Reference")
        score = {cid: weight(w & v) + weight(h & v) + (2 * weight(h & names[cid]) if h and (h <= names[cid] or names[cid] <= h) else 0)
                 for cid, v in vocab.items()}
        ranked = sorted(score.values(), reverse=True)
        top, second = ranked[0], ranked[1] if len(ranked) > 1 else 0.0
        if top < need or top < 1.5 * second:  # more than one rare word (or the part's own name), and clearly ahead
            return None
        return max(score, key=score.get)

    for r in reqs:
        acs = r.get("acs", [])
        part = best("", r.get("text", ""), need=1.0)  # a part's heading is a strong hint: one rare word is enough
        for a in acs:
            if a["id"] in manual:
                a["cap"], a["cap_by"] = manual[a["id"]], "hand"
            elif a.get("cap_by") != "hand" or a.get("cap") not in ids:  # a hand choice for a gone capability is redone
                own = best(a.get("text", ""), r.get("text", ""))
                a["cap"], a["cap_by"] = (own, "words") if own else (part, "part") if part else (ALL, "all")
    trace.write_text(json.dumps(tr, ensure_ascii=False, indent=1), encoding="utf-8")
    acs = [a for r in reqs for a in r.get("acs", [])]
    general = [a for a in acs if a["cap"] == ALL]
    msg = (f"{len(acs) - len(general)} of {len(acs)} instructions tied to one capability, {len(general)} for everything "
           "it does. Read the list; where one is wrong, run again with --set <AC id>=<CAP id or ALL>:")
    label = {c["id"]: c["name"] for c in caps} | {ALL: ALL_NAME}
    for cid in [c["id"] for c in caps] + [ALL]:
        mine = [a for a in acs if a["cap"] == cid]
        if mine:
            msg += f"\n{cid} {label[cid]}:\n" + "\n".join(f"  - {a['id']}: {cut(a.get('text', ''), 100)}" for a in mine)
    return 0, msg


def by_capability(skill: Path, trace: dict, statuses: dict, holds=("mechanic", "command")) -> list[dict] | None:
    """Per capability of the written intent, and one row for the rules for everything: its instructions held by a
    passing test, kept as text, or still open. The row for everything is left out when it holds nothing."""
    doc = load(skill)
    if not doc or not isinstance(trace, dict):
        return None
    if not any(a.get("cap") for r in trace.get("requirements", []) for a in r.get("acs", [])):
        return None  # not tied yet: no count is better than a wrong "written text only"
    rows = {c["id"]: {"id": c["id"], "name": c["name"], "text": c["text"], "status": c.get("status", "assumption"),
                      "tests": 0, "prose": 0, "open": 0, "total": 0} for c in doc["capabilities"]}
    rows[ALL] = {"id": ALL, "name": ALL_NAME, "text": "Rules that hold for all of the above.", "status": "",
                 "tests": 0, "prose": 0, "open": 0, "total": 0}
    for r in trace.get("requirements", []):
        for a in r.get("acs", []):
            row = rows.get(a.get("cap"))
            if not row:
                continue
            st = statuses.get(a.get("id"))
            kind = "tests" if st == "passing" else "prose" if st == "text" or a.get("class") not in holds else "open"
            row[kind] += 1
            row["total"] += 1
    return [r for r in rows.values() if r["id"] != ALL or r["total"]]


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    usage = __doc__.split("\n\n")[1]
    if not a or not (Path(a[1] if a[0] in ("write", "confirm", "diff", "assign") and len(a) > 1 else a[0]) / "SKILL.md").is_file():
        print(usage)
        return 2
    verb = a[0] if a[0] in ("write", "confirm", "diff", "assign") else "show"
    skill = Path(a[0] if verb == "show" else a[1])
    rest = a[1:] if verb == "show" else a[2:]
    if verb == "show" and not rest:
        print(json.dumps(intent(skill), ensure_ascii=False))
        return 0
    if verb == "write" and len(rest) == 2 and rest[0] == "--file":
        try:
            raw = json.loads(Path(rest[1]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("the file is not valid JSON")
            return 2
        code, msg = write(skill, raw)
    elif verb == "confirm" and len(rest) == 2 and rest[0] == "--keep-non-goals":
        code, msg = confirm(skill, rest[1])
    elif verb == "diff" and not rest:
        ch = changes(skill)
        for c in ch:
            print(f"{c['id']}: {c['old'] or '(new)'}  ->  {c['new'] or '(removed)'}")
        return 1 if ch else 0
    elif verb == "assign" and len(rest) >= 2 and rest[0] == "--trace":
        manual, it = {}, iter(rest[2:])
        for x in it:
            if x != "--set":
                print(usage)
                return 2
            k, _, v = next(it, "").partition("=")
            manual[k.strip()] = v.strip().upper()
        code, msg = assign(skill, Path(rest[1]), manual)
    else:
        print(usage)
        return 2
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
