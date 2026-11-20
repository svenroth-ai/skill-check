"""Tests for scripts/derive_scenarios.py. Run: python -m unittest discover -s tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import derive_scenarios as ds  # noqa: E402

SKILL = """---
name: s
description: ok
---
# T
Never ship a video without the QA file.
Ask Sven before the upload and wait for his go.
Plain sentence that carries no rule at all.
## Branch
Always read references/a.md first.
"""


def make(root: Path) -> Path:
    d = root / "s"
    (d / "references").mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (d / "references" / "a.md").write_text("# A\nYou must not skip the gate.\n", encoding="utf-8")
    return d


class Derive(unittest.TestCase):
    def test_rule_and_gate_seeds_with_anchors(self):
        with tempfile.TemporaryDirectory() as t:
            seeds = ds.seeds_for(make(Path(t)))
        texts = {(s["kind"], s["text"]) for s in seeds}
        self.assertIn(("rule", "Never ship a video without the QA file."), texts)
        self.assertIn(("gate", "Ask Sven before the upload and wait for his go."), texts)
        self.assertIn(("rule", "You must not skip the gate."), texts)
        self.assertFalse(any("Plain sentence" in s["text"] for s in seeds))
        self.assertTrue(all(s["section_hash"] and s["file"] and s["path"] for s in seeds))

    def test_ids_are_stable_and_unique(self):
        with tempfile.TemporaryDirectory() as t:
            d = make(Path(t))
            a, b = ds.seeds_for(d), ds.seeds_for(d)
        self.assertEqual([s["id"] for s in a], [s["id"] for s in b])
        self.assertEqual(len({s["id"] for s in a}), len(a))

    def test_cli_writes_json_and_missing_folder_exits_2(self):
        with tempfile.TemporaryDirectory() as t:
            d = make(Path(t))
            out = Path(t) / "seeds.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "derive_scenarios.py"), str(d), "--out", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertGreater(json.loads(out.read_text(encoding="utf-8"))["counts"]["rule"], 0)
            r = subprocess.run([sys.executable, str(SCRIPTS / "derive_scenarios.py"), str(Path(t) / "none")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
