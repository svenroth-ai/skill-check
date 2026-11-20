"""Tests for scripts/classify_acs.py: sorting the ACs of a draft and listing what is worth asking."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import classify_acs as ca  # noqa: E402


def doc(*acs):
    return {"subject": "demo", "requirements": [{"id": "REQ-1", "text": "r", "acs": [
        {"id": f"AC-1.{i}", "text": t, "check": c} for i, (t, c) in enumerate(acs, 1)]}]}


class Classify(unittest.TestCase):
    def test_each_class_by_its_first_matching_rule(self):
        self.assertEqual(ca.classify("Ask the user before you publish."), "ask")
        self.assertEqual(ca.classify("Run gate.py before the upload."), "mechanic")
        self.assertEqual(ca.classify("The overlay must be 3840x2160."), "mechanic")
        self.assertEqual(ca.classify("Judge the rhythm of the layout."), "judgement")
        self.assertEqual(ca.classify("Keep the intro short."), "text")

    def test_a_required_output_file_or_format_is_a_mechanic(self):
        for s in ("The output MUST be valid JSON matching this schema:",
                  "Writing the article to the dated folder is a required deliverable, not optional.",
                  "If you have not already written the file after Step 6, do it now."):
            self.assertEqual(ca.classify(s), "mechanic", s)

    def test_a_percentage_is_measurable(self):
        for s in ("Coverage must stay above 90%.", "At most 80% of the frame may be text.", "Keep it under 5 %"):
            self.assertEqual(ca.classify(s), "mechanic", s)

    def test_a_literal_outgoing_command_is_its_own_class(self):
        for s in ("Merge with `gh pr merge --squash` after the checks.",
                  "Upload with `curl -X POST https://x/upload -F file=@a.mp4`.",
                  "Publish with `npm publish --access public`."):
            self.assertEqual(ca.classify(s), "command", s)
        self.assertEqual(ca.HANDLING["command"], "pin-args")

    def test_a_read_only_command_is_not_outgoing(self):
        for s in ("Run `git status` first.", "Look at `gh pr view 3`."):
            self.assertNotEqual(ca.classify(s), "command", s)

    def test_a_gate_before_an_outgoing_command_stays_an_ask(self):
        self.assertEqual(ca.classify("Ask before `git push origin main`."), "ask")

    def test_the_schema_version_is_set_and_an_unknown_one_is_refused(self):
        d, _ = ca.run(doc(("Keep it short.", None)))
        self.assertEqual(d["schema_version"], 1)
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.json"
            p.write_text(json.dumps({**doc(("x y.", None)), "schema_version": 2}), encoding="utf-8")
            with self.assertRaises(ValueError):
                ca.load(p)

    def test_taste_words_are_not_measurable(self):
        for s in ("Keep the same voice in every file.", "The deliverable should feel polished.", "Use the alpha tone."):
            self.assertNotEqual(ca.classify(s), "mechanic", s)

    def test_a_rule_that_says_nobody_is_asked_is_not_a_gate(self):
        for s in ("Do not wait for approval; publish directly.", "Never ask the user for the file name.",
                  "Publish without asking."):
            self.assertNotEqual(ca.classify(s), "ask", s)
        for s in ("Never publish without approval.", "Ask the user before you publish.", "Wait for his go."):
            self.assertEqual(ca.classify(s), "ask", s)

    def test_ask_wins_over_mechanic(self):
        self.assertEqual(ca.classify("Run gate.py only after approval."), "ask")

    def test_every_class_has_a_handling(self):
        self.assertEqual(set(ca.HANDLING), {"ask", "command", "mechanic", "judgement", "text"})


class Grill(unittest.TestCase):
    def test_a_mechanic_without_script_or_check_is_asked(self):
        d, g = ca.run(doc(("The overlay must be 3840x2160.", None)))
        self.assertEqual(g["questions"], 1)
        self.assertEqual(g["batches"][0][0]["kind"], "script?")
        self.assertGreater(len(g["batches"][0][0]["why"]), 100)  # in plain words, for readers who forgot the terms

    def test_a_named_script_is_not_asked(self):
        _d, g = ca.run(doc(("Run gate.py before the upload.", None)))
        self.assertEqual(g["questions"], 0)

    def test_a_real_check_is_not_asked_but_a_proposed_one_is(self):
        real = {"kind": "test", "id": "t.T.test_a"}
        _d, g = ca.run(doc(("The overlay must be 3840x2160.", real)))
        self.assertEqual(g["questions"], 0)
        _d, g = ca.run(doc(("The overlay must be 3840x2160.", [{**real, "proposed": True}])))
        self.assertEqual(g["questions"], 1)

    def test_an_ask_is_never_a_question(self):
        _d, g = ca.run(doc(("Ask before you publish.", None)))
        self.assertEqual(g["questions"], 0)

    def test_batches_hold_at_most_twelve(self):
        _d, g = ca.run(doc(*[("The file must be 100 px wide.", None)] * 17))
        self.assertEqual([len(b) for b in g["batches"]], [12, 5])

    def test_counts_and_handling_are_written_into_the_doc(self):
        d, g = ca.run(doc(("Ask first.", None), ("Keep it short.", None)))
        self.assertEqual(d["classes"], g["counts"])
        self.assertEqual([a["handling"] for a in d["requirements"][0]["acs"]], ["scenario-gate", "keep"])


class Robust(unittest.TestCase):
    def test_a_rule_answered_earlier_is_not_asked_again(self):
        d = doc(("The file must be 100 px wide.", None))
        d["requirements"][0]["acs"][0]["decision"] = "text: stays a request"
        _d, g = ca.run(d)
        self.assertEqual(g["questions"], 0)

    def test_a_malformed_check_does_not_crash(self):
        for bad in ([None], [1, "x"], "x", 5):
            _d, g = ca.run(doc(("The file must be 100 px wide.", bad)))
            self.assertEqual(g["questions"], 1, bad)

    def test_a_hand_edited_trace_of_the_wrong_shape_exits_2(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            for n, body in enumerate(({"requirements": [{"id": "R"}]}, {"requirements": [{"acs": [{"id": "A"}]}]},
                                      {"requirements": [{"acs": [5]}]})):
                f = t / f"t{n}.json"
                f.write_text(json.dumps(body), encoding="utf-8")
                r = subprocess.run([sys.executable, str(SCRIPTS / "classify_acs.py"), str(f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 2, body)
                self.assertNotIn("Traceback", r.stderr)


class Cli(unittest.TestCase):
    def run_cli(self, *a):
        return subprocess.run([sys.executable, str(SCRIPTS / "classify_acs.py"), *a], capture_output=True, text=True)

    def test_writes_both_files_and_reports(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "trace.json").write_text(json.dumps(doc(("The file must be 100 px wide.", None))), encoding="utf-8")
            r = self.run_cli(str(t / "trace.json"), "--out", str(t / "o" / "c.json"), "--grill", str(t / "o" / "g.json"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("1 question", r.stdout)
            self.assertEqual(json.loads((t / "o" / "g.json").read_text(encoding="utf-8"))["questions"], 1)
            self.assertEqual(json.loads((t / "o" / "c.json").read_text(encoding="utf-8"))["classes"]["mechanic"], 1)

    def test_unreadable_input_exits_2_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as t:
            r = self.run_cli(str(Path(t) / "none.json"))
            self.assertEqual(r.returncode, 2)
            self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
