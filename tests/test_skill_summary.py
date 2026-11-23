import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import skill_summary as ss  # noqa: E402

SKILL = """---
name: demo
description: "Makes images with the **nano** API. Four ways to do it. Use it when the user wants a picture."
---

# Demo

Intro line that is not a section.

## Usage

Always pass an output folder so images are saved there, not in the skill folder. More detail follows.

## Styles

- Infographic for diagrams
- Thumbnail for videos
- Sketchnote for notes

## Reference

| Name | What |
|---|---|
| a | b |

## Empty
"""


class Summary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self.tmp.name) / "demo"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(SKILL, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_without_a_written_summary_it_is_derived_from_the_text(self):
        s = ss.summary(self.skill)
        self.assertEqual(s["source"], "derived")
        self.assertTrue(s["abstract"].startswith("Makes images with the nano API."))
        names = [x["name"] for x in s["sections"]]
        self.assertEqual(names, ["Usage", "Styles"])  # a table-only and an empty section say nothing
        self.assertIn("output folder", s["sections"][0]["text"])
        self.assertEqual(s["sections"][1]["text"], "Infographic for diagrams Thumbnail for videos")

    def test_a_written_summary_wins(self):
        ok, _ = ss.write(self.skill, {"abstract": "It makes pictures.", "sections": [{"name": "Usage", "text": "Pass a folder."}]})
        self.assertTrue(ok)
        s = ss.summary(self.skill)
        self.assertEqual((s["source"], s["abstract"], s["sections"][0]["text"]), ("written", "It makes pictures.", "Pass a folder."))

    def test_a_bad_summary_is_refused_and_not_written(self):
        for bad in ({}, {"abstract": "x"}, {"abstract": "", "sections": [{"name": "a", "text": "b"}]}, {"abstract": "x", "sections": [{"name": "a"}]}, []):
            self.assertFalse(ss.write(self.skill, bad)[0])
        self.assertFalse((self.skill / "baseline" / "summary.json").exists())

    def test_a_broken_summary_file_falls_back_to_the_derived_one(self):
        (self.skill / "baseline").mkdir()
        (self.skill / "baseline" / "summary.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(ss.summary(self.skill)["source"], "derived")

    def test_cli_write_reports_success_and_refusal(self):
        f = Path(self.tmp.name) / "s.json"
        f.write_text(json.dumps({"abstract": "A.", "sections": [{"name": "U", "text": "T."}]}), encoding="utf-8")
        self.assertEqual(ss.main(["write", str(self.skill), "--file", str(f)]), 0)
        f.write_text("{}", encoding="utf-8")
        self.assertEqual(ss.main(["write", str(self.skill), "--file", str(f)]), 3)


if __name__ == "__main__":
    unittest.main()
