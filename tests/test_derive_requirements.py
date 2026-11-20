"""Tests for scripts/derive_requirements.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import derive_requirements as dr  # noqa: E402

SKILL = """---
name: s
description: ok
---
# T
## Gate
Never ship a video without the QA file. You must run gate.py qa first and read the result
before you continue. Plain sentence that carries no rule at all.
- Ask Sven before the upload and wait for his go.
- Short note.
## Other
Always read references/a.md first.
"""
TESTS = '''import unittest
class QaTest(unittest.TestCase):
    def test_blocked_bad_result(self): pass
    def test_unrelated_thing(self): pass
'''


def make(root: Path, with_tests=True) -> Path:
    d = root / "s"
    (d / "scripts").mkdir(parents=True)
    (d / "tests").mkdir()
    (d / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (d / "scripts" / "gate.py").write_text("x = 1\n", encoding="utf-8")
    if with_tests:
        (d / "tests" / "test_gate.py").write_text(TESTS, encoding="utf-8")
    return d


class Derive(unittest.TestCase):
    def acs(self, doc):
        return [a for r in doc["requirements"] for a in r["acs"]]

    def test_an_ac_is_the_whole_sentence_not_a_wrapped_line(self):
        with tempfile.TemporaryDirectory() as t:
            doc = dr.derive(make(Path(t)))
        texts = [a["text"] for a in self.acs(doc)]
        self.assertIn("Never ship a video without the QA file.", texts)
        self.assertTrue(any(x == "You must run gate.py qa first and read the result before you continue." for x in texts))
        self.assertFalse(any("Plain sentence" in x for x in texts))

    def test_an_abbreviation_does_not_end_a_sentence(self):
        paras = dr.paragraphs(["You must write the file", "(e.g. `a.md`) and never print it."])
        got = dr.sentences_of(paras, "You must write the file", "rule")
        self.assertEqual(got, ["You must write the file (e.g. `a.md`) and never print it."])

    def test_requirements_group_by_section_and_keep_the_source(self):
        with tempfile.TemporaryDirectory() as t:
            doc = dr.derive(make(Path(t)))
        self.assertEqual([r["text"] for r in doc["requirements"]], ["Gate", "Other"])
        self.assertTrue(all(a["source"].startswith("SKILL.md: ") for a in self.acs(doc)))
        self.assertEqual(len({a["id"] for a in self.acs(doc)}), len(self.acs(doc)))

    def test_a_check_is_proposed_only_when_a_script_is_named_and_a_word_is_shared(self):
        with tempfile.TemporaryDirectory() as t:
            doc = dr.derive(make(Path(t)))
        named = next(a for a in self.acs(doc) if "gate.py" in a["text"])
        self.assertEqual([c["id"] for c in named["check"]], ["test_gate.QaTest.test_blocked_bad_result"])
        self.assertTrue(all(c["proposed"] for c in named["check"]))
        self.assertNotIn("test_gate.QaTest.test_unrelated_thing", [c["id"] for c in named["check"]])
        never = next(a for a in self.acs(doc) if a["text"].startswith("Never ship"))
        self.assertIsNone(never["check"])  # no script named: nothing guessed

    def test_without_tests_nothing_is_proposed(self):
        with tempfile.TemporaryDirectory() as t:
            doc = dr.derive(make(Path(t), with_tests=False))
        self.assertTrue(all(a["check"] is None for a in self.acs(doc)))

    def test_a_proposed_check_is_never_proof(self):
        import trace_check as tc
        with tempfile.TemporaryDirectory() as t:
            d = make(Path(t))
            doc = dr.derive(d)
            tr = Path(t) / "trace.json"
            tr.write_text(json.dumps(doc), encoding="utf-8")
            rows = tc.evaluate(tc.load(tr), d / "tests", d)
        self.assertNotIn("passing", {r["status"] for r in rows})
        self.assertIn("proposed", {r["status"] for r in rows})

    def test_cli(self):
        with tempfile.TemporaryDirectory() as t:
            d = make(Path(t))
            out = Path(t) / "o" / "trace.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "derive_requirements.py"), str(d), "--out", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["draft"])
            r = subprocess.run([sys.executable, str(SCRIPTS / "derive_requirements.py"), str(Path(t) / "none")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)

    def test_the_draft_carries_a_schema_version(self):
        with tempfile.TemporaryDirectory() as t:
            doc = dr.derive(make(Path(t)))
        self.assertEqual(doc["schema_version"], 1)

    def test_an_earlier_trace_is_never_overwritten_without_force(self):
        with tempfile.TemporaryDirectory() as t:
            d = make(Path(t))
            out = Path(t) / "trace.json"
            out.write_text('{"mine": "bindings and decisions"}', encoding="utf-8")
            cmd = [sys.executable, str(SCRIPTS / "derive_requirements.py"), str(d), "--out", str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 3)
            self.assertEqual(out.read_text(encoding="utf-8"), '{"mine": "bindings and decisions"}')
            r = subprocess.run(cmd + ["--force"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["draft"])


if __name__ == "__main__":
    unittest.main()
