import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import skill_text as st  # noqa: E402


class SkillText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = Path(self.tmp.name) / "demo"
        self.skill.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_file_comes_back_as_it_is(self):
        (self.skill / "SKILL.md").write_text("---\nname: demo\n---\n# Demo\n\n| a | b |\n", encoding="utf-8")
        d = st.text(self.skill)
        self.assertEqual(d["file"], "SKILL.md")
        self.assertEqual(d["text"], "---\nname: demo\n---\n# Demo\n\n| a | b |\n")

    def test_a_skill_without_skill_md_gives_no_text(self):
        self.assertEqual(st.text(self.skill)["text"], "")


if __name__ == "__main__":
    unittest.main()
