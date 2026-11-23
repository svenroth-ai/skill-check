import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import skill_text as st  # noqa: E402

SKILL = """---
name: demo
description: Demo.
---

# Demo

## Rules

- Always ask before uploading anything to the shared drive.
- The overlay must be exactly 3840x2160 pixels.
- You must keep the tone natural.

Some plain background text without any rule.
"""


class SkillText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self.tmp.name) / "demo"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(SKILL, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def marks(self):
        return {l["t"]: l["m"] for l in st.marked(self.skill)["lines"]}

    def test_every_line_of_the_file_comes_back_in_order(self):
        lines = [l["t"] for l in st.marked(self.skill)["lines"]]
        self.assertEqual(lines, SKILL.splitlines())

    def test_a_gate_and_an_exact_size_are_marked_as_code_can_hold(self):
        m = self.marks()
        self.assertEqual(m["- Always ask before uploading anything to the shared drive."], "hold")
        self.assertEqual(m["- The overlay must be exactly 3840x2160 pixels."], "hold")

    def test_taste_stays_text_and_plain_lines_carry_no_mark(self):
        m = self.marks()
        self.assertEqual(m["- You must keep the tone natural."], "text")
        self.assertIsNone(m["# Demo"])

    def test_a_skill_without_skill_md_gives_no_lines(self):
        (self.skill / "SKILL.md").unlink()
        self.assertEqual(st.marked(self.skill)["lines"], [])


if __name__ == "__main__":
    unittest.main()
