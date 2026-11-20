#!/usr/bin/env python3
"""Check that every acceptance criterion (AC) is bound to a check that exists and passes.

    python scripts/trace_check.py baseline/<name>/trace.json [--tests tests] [--md requirements.md] [--status status.json] [--strict]

trace.json  {"subject": str, "requirements": [{"id", "text", "acs": [{"id", "text", "source", "check"}]}]}
A check is one of
  null                                   the AC has no check yet: a gap
  [check, check, ...]                    all of them must pass; the worst status wins
  any check with "proposed": true        a draft from derive_requirements.py: reported as "proposed", never run
  {"kind": "test", "id": "module.Class.test_name"}   a unittest in --tests; it is run
  {"kind": "text", "file": path, "contains": str}    the file (relative to --root, default the parent of --tests, and
                                          not outside it) holds the text
  {"kind": "scenario", "id": str}        needs model runs; reported as "not run here" until compare_runs.py --trace
                                          writes "result": {"verdict": ...}: same or improvement pass, regression fails,
                                          anything else (unstable, both-wrong) is "review": a person must look

Per AC the status is: passing, failing, dangling (the named check does not exist), proposed (a guess, not run),
not-run, review (scenario outcome a person must look at), text (no check, but decided: the rule stays written text,
not proof), gap.
Exit codes: 0 nothing failing or dangling (gaps allowed unless --strict); 1 failing or dangling, or a gap
under --strict; 2 bad input.
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import sys
import unittest
from pathlib import Path

KINDS = {"test", "text", "scenario"}


def load(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read {path}: {e}") from None
    if not isinstance(doc, dict):
        raise ValueError("trace.json must be an object")
    if doc.get("schema_version", 1) != 1:
        raise ValueError(f"trace.json has schema_version {doc['schema_version']!r}; this version reads 1")
    reqs = doc.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        raise ValueError("trace.json has no requirements list")
    seen: set[str] = set()
    for r in reqs:
        if not isinstance(r, dict) or not r.get("id") or not r.get("text") or not isinstance(r.get("acs"), list) or not r["acs"]:
            raise ValueError(f"requirement {r.get('id', '?') if isinstance(r, dict) else r!r} needs id, text and at least one AC")
        for a in r["acs"]:
            if not isinstance(a, dict):
                raise ValueError(f"an AC in {r['id']} is not an object")
            for key in ("id", "text", "source"):
                if not a.get(key):
                    raise ValueError(f"AC {a.get('id', '?')} in {r['id']} lacks '{key}'")
            if a["id"] in seen:
                raise ValueError(f"duplicate AC id {a['id']}")
            seen.add(a["id"])
            c = a.get("check")
            for one in (c if isinstance(c, list) else [c]):
                if one is None and not isinstance(c, list):
                    continue
                if not isinstance(one, dict) or one.get("kind") not in KINDS:
                    raise ValueError(f"AC {a['id']}: check.kind must be one of {sorted(KINDS)} or the check must be null")
    return doc


def run_test(test_id: str, tests_dir: Path) -> str:
    """passing | failing | dangling"""
    if not isinstance(test_id, str) or not test_id:
        return "dangling"
    parts = test_id.split(".")
    # Before anything is imported: the id must be module.Class.test and the module a file of --tests. An id
    # like "sys.exit" or "os.abort" from an untrusted trace.json must never be imported and called.
    if len(parts) < 3 or not all(p.isidentifier() for p in parts) or not (tests_dir / f"{parts[0]}.py").is_file():
        return "dangling"
    sys.dont_write_bytecode = True  # running a skill's tests must not leave __pycache__ in the skill folder
    while str(tests_dir) in sys.path:
        sys.path.remove(str(tests_dir))
    sys.path.insert(0, str(tests_dir))  # always first: a module of the same name elsewhere must not answer
    parent = str(tests_dir.resolve().parent)  # a skill's tests are a package (`from tests import _paths`)
    while parent in sys.path:
        sys.path.remove(parent)
    sys.path.insert(1, parent)  # right after tests_dir, ahead of site-packages: its own `tests` wins
    for stale in ("tests", "_paths"):
        sys.modules.pop(stale, None)
    importlib.invalidate_caches()
    sys.modules.pop(test_id.split(".")[0], None)  # nor one cached from an earlier call
    try:
        suite = unittest.TestLoader().loadTestsFromName(test_id)
        mod = sys.modules.get(test_id.split(".")[0])
        where = Path(getattr(mod, "__file__", "") or "").resolve()
        if not where.is_relative_to(tests_dir.resolve()):
            return "dangling"  # the id points at a module outside --tests
    except (ImportError, AttributeError, ValueError, TypeError, SystemExit):
        return "dangling"
    if suite.countTestCases() == 0 or any(t.__class__.__name__ == "_FailedTest" for t in _walk(suite)):
        return "dangling"
    res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return "passing" if res.wasSuccessful() and not res.skipped and not res.expectedFailures else "failing"


def _walk(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _walk(t)
        else:
            yield t


def status_of(check, tests_dir: Path, root: Path) -> str:
    """One check or a list of checks (all must pass): the worst status wins."""
    if isinstance(check, list):
        got = [status_of(c, tests_dir, root) for c in check] or ["gap"]
        for worst in ("failing", "dangling", "gap", "review", "proposed", "not-run"):
            if worst in got:
                return worst
        return "passing"
    if check is None:
        return "gap"
    if check.get("proposed"):
        return "proposed"  # a guess by word overlap: not run, not counted as proof until a reviewer removes the flag
    if check["kind"] == "test":
        return run_test(check.get("id", ""), tests_dir)
    if check["kind"] == "text":
        try:
            target = (root / check.get("file", "")).resolve()
            if not target.is_relative_to(root.resolve()):
                return "dangling"  # a text check may not look outside the repository
            text = target.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return "dangling"
        return "passing" if check.get("contains") and check["contains"] in text else "failing"
    res = check.get("result")  # written by compare_runs.py --trace after model runs of old against new
    if isinstance(res, dict):
        v = res.get("verdict")
        return "passing" if v in ("same", "improvement") else "failing" if v == "regression" else "review"
    return "not-run"


def evaluate(doc: dict, tests_dir: Path, root: Path) -> list[dict]:
    rows = []
    for r in doc["requirements"]:
        for a in r["acs"]:
            st = status_of(a.get("check"), tests_dir, root)
            if st == "gap" and str(a.get("decision", "")).lower().startswith("text"):
                st = "text"  # decided: stays a written rule, no script can hold it. Not proof, but not an open gap either
            rows.append({"req": r["id"], "ac": a["id"], "text": a["text"], "source": a["source"],
                         "check": a.get("check"), "status": st})
    return rows


def counts(rows: list[dict]) -> dict:
    """The numbers the view shows: total, passing, failing, gap (no check yet), text (decided to stay written text) and other (dangling, not-run)."""
    c = {"total": len(rows), "passing": 0, "failing": 0, "gap": 0, "text": 0, "other": 0}
    for r in rows:
        c[r["status"] if r["status"] in ("passing", "failing", "gap", "text") else "other"] += 1
    return c


def render(doc: dict, rows: list[dict]) -> str:
    by_ac = {r["ac"]: r for r in rows}
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out = [f"# Requirements: {doc.get('subject', '')}", "",
           "Status: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), ""]
    for r in doc["requirements"]:
        out += [f"## {r['id']}: {r['text']}", ""]
        for a in r["acs"]:
            row = by_ac[a["id"]]
            chk = row["check"]
            one = lambda c: f"{c['kind']}: {c.get('id') or c.get('contains', '')}"  # noqa: E731
            bound = "no check yet" if chk is None else "; ".join(one(c) for c in (chk if isinstance(chk, list) else [chk]))
            out.append(f"- **{a['id']}** [{row['status']}] {a['text']}  ")
            out.append(f"  Source: {a['source']}. Check: {bound}.")
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trace", type=Path)
    ap.add_argument("--tests", type=Path, default=Path("tests"))
    ap.add_argument("--root", type=Path, help="base for text checks (default: the folder of --tests' parent)")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--status", type=Path, help="write the counts as JSON (what the view reads)")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    try:
        doc = load(a.trace)
    except ValueError as e:
        print(f"trace_check: {e}", file=sys.stderr)
        return 2
    root = a.root or a.tests.resolve().parent
    rows = evaluate(doc, a.tests.resolve(), root)
    if a.md:
        a.md.write_text(render(doc, rows), encoding="utf-8")
    if a.status:
        a.status.parent.mkdir(parents=True, exist_ok=True)
        try:  # keep what else the file holds (the stage written by harden_state.py)
            have = json.loads(a.status.read_text(encoding="utf-8"))
            have = have if isinstance(have, dict) else {}
        except (OSError, ValueError):
            have = {}
        have.update(counts(rows))
        have["acs"] = {r["ac"]: r["status"] for r in rows}  # per criterion, for the report page
        a.status.write_text(json.dumps(have), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for r in rows:
        print(f"{r['status']:9} {r['ac']:8} {r['text']}")
    bad = [r for r in rows if r["status"] in ("failing", "dangling")]
    gaps = [r for r in rows if r["status"] == "gap"]
    print(f"\n{len(rows)} ACs: " + ", ".join(f"{s} {sum(1 for r in rows if r['status'] == s)}"
          for s in ("passing", "failing", "dangling", "proposed", "not-run", "review", "text", "gap")))
    return 1 if bad or (a.strict and gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
