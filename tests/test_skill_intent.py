import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import skill_intent as si  # noqa: E402

SKILL = """---
name: pics
description: "Make **images** with an API. Four styles."
---
# Pics

## Infographic
Draws technical diagrams in a warm style.

Never save images in the skill folder.

## Thumbnail
- Bold YouTube thumbnails.
- Five sub-styles.

```
## not a heading
Do not read this line, it is code.
```
"""

PROPOSAL = {
    "purpose": "Makes images for blog posts and videos: diagrams, thumbnails and sketch notes, through one API.",
    "non_goals": ["It never saves images in the skill folder.", "It never posts an image anywhere."],
    "capabilities": [
        {"name": "Infographics", "text": "Draws technical diagrams and architectures in a warm, flat style."},
        {"name": "Thumbnails", "text": "Makes bold YouTube thumbnails in five sub-styles."},
    ],
    "scenarios": [
        {"text": "You ask for a diagram of your pipeline, the skill draws it, you get a PNG in your folder.",
         "caps": ["Infographics"]},
        {"text": "You ask for a thumbnail, the skill asks for a sub-style, you get one image.", "caps": ["CAP-2"]},
    ],
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self.tmp.name) / "pics"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(SKILL, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data=None):
        return si.write(self.skill, json.loads(json.dumps(data or PROPOSAL)))


class Derived(Base):
    def test_without_a_written_intent_the_skill_text_is_used(self):
        d = si.intent(self.skill)
        self.assertEqual(d["source"], "derived")
        self.assertEqual(d["purpose"], "Make images with an API. Four styles.")
        self.assertEqual([c["name"] for c in d["capabilities"]], ["Infographic", "Thumbnail"])
        self.assertEqual(d["capabilities"][1]["text"], "Bold YouTube thumbnails. Five sub-styles.")
        self.assertEqual([n["text"] for n in d["non_goals"]], ["Never save images in the skill folder."])
        self.assertTrue(all(c["status"] == "assumption" for c in d["capabilities"]))


class Write(Base):
    def test_a_proposal_is_numbered_by_code_and_stays_an_assumption(self):
        self.assertEqual(self.write()[0], 0)
        d = si.intent(self.skill)
        self.assertEqual(d["source"], "written")
        self.assertEqual([c["id"] for c in d["capabilities"]], ["CAP-1", "CAP-2"])
        self.assertEqual([s["caps"] for s in d["scenarios"]], [["CAP-1"], ["CAP-2"]])
        self.assertEqual([n["id"] for n in d["non_goals"]], ["NG-1", "NG-2"])
        self.assertFalse(d["confirmed"])

    def test_the_limits_are_held_by_code(self):
        too_long = dict(PROPOSAL, purpose="word " * 81)
        code, msg = self.write(too_long)
        self.assertEqual(code, 3)
        self.assertIn("81 words", msg)
        six = dict(PROPOSAL, capabilities=[{"name": f"C{i}", "text": "x"} for i in range(6)])
        self.assertIn("6 capabilities", self.write(six)[1])
        wordy = dict(PROPOSAL, capabilities=[{"name": "A", "text": "w " * 31}])
        self.assertIn("31 words", self.write(wordy)[1])
        lost = dict(PROPOSAL, scenarios=[{"text": "You ask, it does.", "caps": ["Nope"]}])
        self.assertIn("does not exist: nope", self.write(lost)[1])
        self.assertIn("names no capability", self.write(dict(PROPOSAL, scenarios=[{"text": "You ask.", "caps": []}]))[1])
        self.assertIn("0 scenarios", self.write(dict(PROPOSAL, scenarios=[]))[1])
        self.assertFalse((self.skill / "baseline" / "intent.json").exists())


class Confirm(Base):
    def test_only_the_ticked_non_goals_stay(self):
        self.write()
        code, msg = si.confirm(self.skill, "NG-2")
        self.assertEqual(code, 0, msg)
        d = si.intent(self.skill)
        self.assertTrue(d["confirmed"])
        self.assertEqual([(n["id"], n["text"]) for n in d["non_goals"]], [("NG-2", "It never posts an image anywhere.")])
        self.assertEqual(si.changes(self.skill), [])

    def test_none_keeps_no_non_goal_and_an_unknown_one_is_refused(self):
        self.write()
        self.assertEqual(si.confirm(self.skill, "NG-9")[0], 2)
        self.assertEqual(si.confirm(self.skill, "none")[0], 0)
        self.assertEqual(si.intent(self.skill)["non_goals"], [])

    def test_a_later_change_shows_old_against_new_and_only_that_loses_its_confirmation(self):
        self.write()
        si.confirm(self.skill, "NG-1,NG-2")
        changed = json.loads(json.dumps(PROPOSAL))
        changed["capabilities"][1]["text"] = "Makes bold YouTube thumbnails in three sub-styles."
        changed["scenarios"].reverse()  # a new order is no change
        self.write(changed)
        d = si.intent(self.skill)
        self.assertFalse(d["confirmed"])
        self.assertEqual([c["status"] for c in d["capabilities"]], ["confirmed", "assumption"])
        self.assertEqual(d["purpose_status"], "confirmed")
        ch = si.changes(self.skill)
        self.assertEqual(len(ch), 1)
        self.assertIn("five", ch[0]["old"])
        self.assertIn("three", ch[0]["new"])

    def test_a_removed_capability_is_listed(self):
        self.write()
        si.confirm(self.skill, "none")
        one = dict(PROPOSAL, non_goals=[], capabilities=PROPOSAL["capabilities"][:1],
                   scenarios=PROPOSAL["scenarios"][:1])
        self.write(one)
        ch = si.changes(self.skill)
        self.assertEqual([(c["id"], c["new"]) for c in ch], [("CAP-2", None), ("SCN-2", None)])


class Review(Base):
    """What the review of 28.11.2026 found."""

    def test_a_shorter_rewrite_after_confirm_is_not_confirmed(self):
        self.write()
        si.confirm(self.skill, "NG-1,NG-2")
        self.write(dict(PROPOSAL, non_goals=[], capabilities=PROPOSAL["capabilities"][:1], scenarios=PROPOSAL["scenarios"][:1]))
        self.assertFalse(si.intent(self.skill)["confirmed"])

    def test_ids_stay_with_their_element_when_the_order_changes(self):
        self.write()
        si.confirm(self.skill, "none")
        turned = json.loads(json.dumps(PROPOSAL))
        turned["capabilities"].reverse()
        turned["non_goals"] = []
        self.write(turned)
        d = si.intent(self.skill)
        self.assertEqual([(c["id"], c["name"]) for c in d["capabilities"]], [("CAP-2", "Thumbnails"), ("CAP-1", "Infographics")])
        self.assertTrue(d["confirmed"])  # the same description in another order
        added = json.loads(json.dumps(turned))
        added["capabilities"].append({"name": "Sketches", "text": "Draws sketch notes."})
        self.write(added)
        self.assertEqual(si.intent(self.skill)["capabilities"][-1]["id"], "CAP-3")

    def test_a_text_match_never_takes_an_id_another_keeps_by_name(self):
        self.write(dict(PROPOSAL, capabilities=[{"name": "Up", "text": "X does it."}, {"name": "Voice", "text": "Y does it."}],
                        scenarios=[{"text": "You ask.", "caps": ["Up"]}]))
        self.write(dict(PROPOSAL, capabilities=[{"name": "Voice2", "text": "X does it."}, {"name": "Up", "text": "Z does it."}],
                        scenarios=[{"text": "You ask.", "caps": ["Up"]}]))
        d = si.intent(self.skill)
        self.assertEqual({c["name"]: c["id"] for c in d["capabilities"]}, {"Up": "CAP-1", "Voice2": "CAP-3"})

    def test_a_dropped_non_goal_number_is_not_given_again(self):
        self.write()
        si.confirm(self.skill, "NG-1")
        self.write(dict(PROPOSAL, non_goals=[PROPOSAL["non_goals"][0], "It never sends mail."]))
        self.assertEqual([n["id"] for n in si.intent(self.skill)["non_goals"]], ["NG-1", "NG-3"])

    def test_an_empty_choice_of_non_goals_is_refused(self):
        self.write()
        self.assertEqual(si.confirm(self.skill, " ")[0], 2)

    def test_a_rewrite_keeps_the_fingerprint_and_ties_the_instructions_again(self):
        self.write()
        si.confirm(self.skill, "none")
        fp = json.loads((self.skill / "baseline" / "intent.json").read_text())["fingerprint"]
        t = {"schema_version": 1, "requirements": [{"id": "REQ-1", "text": "Thumbnails", "acs": [
            {"id": "AC-1.1", "text": "Keep it bold.", "cap": "CAP-9", "cap_by": "hand"}]}]}
        (self.skill / "baseline" / "trace.json").write_text(json.dumps(t), encoding="utf-8")
        code, msg = self.write(dict(PROPOSAL, non_goals=[]))
        self.assertIn("tied to one capability", msg)
        self.assertEqual(json.loads((self.skill / "baseline" / "intent.json").read_text())["fingerprint"], fp)
        a = json.loads((self.skill / "baseline" / "trace.json").read_text())["requirements"][0]["acs"][0]
        self.assertEqual(a["cap"], "CAP-2")  # the hand choice pointed to a capability that is gone

    def test_no_count_per_capability_before_the_instructions_are_tied(self):
        self.write()
        self.assertIsNone(si.by_capability(self.skill, {"requirements": [{"acs": [{"id": "A"}]}]}, {}))


class Assign(Base):
    def trace(self):
        t = {"schema_version": 1, "requirements": [
            {"id": "REQ-1", "text": "Diagrams", "acs": [
                {"id": "AC-1.1", "text": "Draw diagrams at 1920x1080."},
                {"id": "AC-1.2", "text": "Keep the margin calm."}]},
            {"id": "REQ-2", "text": "Output", "acs": [
                {"id": "AC-2.1", "text": "Pass the --dry-run flag first."}]}]}
        p = self.skill / "baseline" / "trace.json"
        p.write_text(json.dumps(t), encoding="utf-8")
        return p

    def test_instructions_go_to_a_capability_by_words_then_by_their_part(self):
        self.write()
        p = self.trace()
        code, msg = si.assign(self.skill, p, {})
        acs = {a["id"]: a for r in json.loads(p.read_text())["requirements"] for a in r["acs"]}
        self.assertEqual(acs["AC-1.1"]["cap"], "CAP-1")
        self.assertEqual(acs["AC-1.2"]["cap"], "CAP-1")  # no word of its own: goes with its part
        self.assertEqual(acs["AC-1.2"]["cap_by"], "part")
        self.assertEqual((acs["AC-2.1"]["cap"], acs["AC-2.1"]["cap_by"]), ("ALL", "all"))  # a rule for everything
        self.assertEqual(code, 0)
        self.assertIn("AC-2.1", msg)  # listed, so Claude reads it

    def test_a_word_every_capability_shares_decides_nothing(self):
        self.write(dict(PROPOSAL, capabilities=[{"name": "Diagram images", "text": "Draws image diagrams."},
                                                 {"name": "Thumbnail images", "text": "Makes image thumbnails."}],
                        scenarios=[{"text": "You ask, it draws.", "caps": ["CAP-1"]}]))
        p = self.trace()
        si.assign(self.skill, p, {})
        acs = {a["id"]: a for r in json.loads(p.read_text())["requirements"] for a in r["acs"]}
        self.assertEqual(acs["AC-2.1"]["cap"], "ALL")
        t = json.loads(p.read_text())
        t["requirements"][1]["acs"][0]["text"] = "Every image must be a PNG."
        p.write_text(json.dumps(t))
        si.assign(self.skill, p, {})
        acs = {a["id"]: a for r in json.loads(p.read_text())["requirements"] for a in r["acs"]}
        self.assertEqual(acs["AC-2.1"]["cap"], "ALL")

    def test_a_hand_choice_wins_and_stays(self):
        self.write()
        p = self.trace()
        self.assertEqual(si.assign(self.skill, p, {"AC-2.1": "CAP-2"})[0], 0)
        self.assertEqual(si.assign(self.skill, p, {})[0], 0)  # a second run keeps it
        acs = {a["id"]: a for r in json.loads(p.read_text())["requirements"] for a in r["acs"]}
        self.assertEqual((acs["AC-2.1"]["cap"], acs["AC-2.1"]["cap_by"]), ("CAP-2", "hand"))
        self.assertEqual(si.assign(self.skill, p, {"AC-2.1": "CAP-9"})[0], 2)
        self.assertEqual(si.assign(self.skill, p, {"AC-7": "CAP-1"})[0], 2)

    def test_counts_per_capability(self):
        self.write()
        p = self.trace()
        si.assign(self.skill, p, {"AC-2.1": "CAP-2"})
        tr = json.loads(p.read_text())
        for r in tr["requirements"]:
            for a in r["acs"]:
                a["class"] = "text" if a["id"] == "AC-1.2" else "mechanic"
        rows = si.by_capability(self.skill, tr, {"AC-1.1": "passing", "AC-1.2": "text", "AC-2.1": "gap"})
        self.assertEqual([(r["id"], r["tests"], r["prose"], r["open"]) for r in rows], [("CAP-1", 1, 1, 0), ("CAP-2", 0, 0, 1)])
        si.assign(self.skill, p, {"AC-2.1": "ALL"})
        tr = json.loads(p.read_text())
        for r in tr["requirements"]:
            for a in r["acs"]:
                a["class"] = "mechanic"
        rows = si.by_capability(self.skill, tr, {"AC-2.1": "passing"})
        self.assertEqual((rows[-1]["id"], rows[-1]["name"], rows[-1]["tests"]), ("ALL", "For everything it does", 1))


class Cli(Base):
    def test_verbs(self):
        f = Path(self.tmp.name) / "p.json"
        f.write_text(json.dumps(PROPOSAL), encoding="utf-8")
        self.assertEqual(si.main(["write", str(self.skill), "--file", str(f)]), 0)
        self.assertEqual(si.main(["diff", str(self.skill)]), 0)
        self.assertEqual(si.main(["confirm", str(self.skill), "--keep-non-goals", "NG-1"]), 0)
        self.assertEqual(si.main([str(self.skill)]), 0)
        self.assertEqual(si.main(["confirm", str(self.skill)]), 2)
        self.assertEqual(si.main([str(Path(self.tmp.name))]), 2)


if __name__ == "__main__":
    unittest.main()
