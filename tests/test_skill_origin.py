"""Tests for scripts/skill_origin.py. Run: python -m unittest discover -s tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_origin as so  # noqa: E402
from test_skill_score import make_skill  # noqa: E402


class Origin(unittest.TestCase):
    def test_a_skill_inside_the_plugin_cache_is_a_plugin_skill(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            d = make_skill(home / ".claude" / "plugins" / "cache" / "market" / "plug" / "1.0.0" / "skills", "x")
            self.assertEqual(so.origin(d, home), {"kind": "plugin", "marketplace": "market", "plugin": "plug"})
            own = make_skill(home / ".claude" / "skills", "mine")
            self.assertEqual(so.origin(own, home), {"kind": "own"})

    def test_a_link_into_the_plugin_cache_is_a_plugin_skill_too(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            real = make_skill(home / ".claude" / "plugins" / "cache" / "m" / "p" / "1" / "skills", "x")
            link = home / ".claude" / "skills" / "x"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("no permission to create links here")
            self.assertEqual(so.origin(link, home)["kind"], "plugin")

    def test_a_skill_an_installer_put_there_is_not_yours_until_you_say_so(self):
        import json
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / ".agents").mkdir()
            (home / ".agents" / ".skill-lock.json").write_text(
                json.dumps({"skills": {"gsap": {"source": "greensock/skills"}}}), encoding="utf-8")
            d = make_skill(home / ".claude" / "skills", "gsap")
            mine = make_skill(home / ".claude" / "skills", "writer")
            self.assertEqual(so.origin(d, home), {"kind": "installed", "source": "greensock/skills"})
            self.assertEqual(so.origin(mine, home), {"kind": "own"})
            synced = home / ".claude" / "skills" / "synced" / "abc"
            synced.mkdir(parents=True)
            (synced / "manifest.json").write_text(json.dumps({"skills": [{"name": "pptx"}]}), encoding="utf-8")
            pp = make_skill(home / ".claude" / "skills", "pptx")
            self.assertEqual(so.origin(pp, home), {"kind": "installed", "source": "claude.ai"})
            so.set_mark("gsap", True, home)
            self.assertEqual(so.origin(d, home), {"kind": "own"})
            so.set_mark("writer", False, home)
            self.assertEqual(so.origin(mine, home), {"kind": "foreign"})
            with self.assertRaises(ValueError):
                so.set_mark("../x", True, home)

    def test_levels(self):
        self.assertEqual(so.level({"add": 2, "hold": 3}, None), 1)
        self.assertEqual(so.level({"add": 0, "hold": 3}, None), 2)
        ok = {"acs": {"A": "passing"}, "failing": 0, "gap": 0, "other": 0}
        self.assertEqual(so.level({}, ok), 2)
        self.assertEqual(so.level({}, ok | {"controlled_at": "2026-11-20T10:00:00Z"}), 3)
        self.assertEqual(so.level({}, ok | {"gap": 1, "controlled_at": "x"}), 1)  # an open gap is never level 2 or 3


if __name__ == "__main__":
    unittest.main()
