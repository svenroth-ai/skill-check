"""Tests that close the gaps found by trace_check.py on baseline/skill-check/trace.json (AC-1.4 to AC-4.3, AC-5.2)."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_skills as cs  # noqa: E402
from test_scanner import make_skill  # noqa: E402

HEAD = "---\nname: s\ndescription: ok\n---\n"


def tree_hash(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class Limits(unittest.TestCase):
    def setUp(self):
        self.limits = cs.load_limits()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def found(self, d):
        return {f["limit"] for f in cs.scan_skill(d, self.limits)["findings"]}

    def test_body_at_the_line_limit_is_reported_and_below_is_not(self):
        n = self.limits["body-max-lines"]["value"]
        over = make_skill(self.root, "over", HEAD + "line\n" * n)
        under = make_skill(self.root, "under", HEAD + "line\n" * (n - 1))
        self.assertIn("body-max-lines", self.found(over))
        self.assertNotIn("body-max-lines", self.found(under))

    def test_backslash_path_is_reported_forward_slash_is_not(self):
        bad = make_skill(self.root, "bad", HEAD + "Run scripts\\go.py first.\n")
        good = make_skill(self.root, "good", HEAD + "Run scripts/go.py first.\n")
        self.assertIn("forward-slash-paths", self.found(bad))
        self.assertNotIn("forward-slash-paths", self.found(good))

    def test_long_reference_needs_a_contents_list(self):
        n = self.limits["reference-toc-threshold"]["value"] + 10
        body = "# Ref\n" + "text line\n" * n
        with_toc = "# Ref\n\n## Contents\n- a\n\n" + "text line\n" * n
        no = make_skill(self.root, "no", HEAD, {"references/r.md": body})
        yes = make_skill(self.root, "yes", HEAD, {"references/r.md": with_toc})
        self.assertIn("reference-toc-threshold", self.found(no))
        self.assertNotIn("reference-toc-threshold", self.found(yes))

    def test_limit_values_are_read_from_the_pinned_file(self):
        data = json.loads(cs.CONVENTIONS.read_text(encoding="utf-8"))
        for item in data["skill_authoring"]["limits"]:
            if item["id"] == "body-max-lines":
                item["value"] = 7
        saved = cs.CONVENTIONS
        with tempfile.TemporaryDirectory() as t:
            alt = Path(t) / "c.json"
            alt.write_text(json.dumps(data), encoding="utf-8")
            cs.CONVENTIONS = alt
            try:
                self.assertEqual(cs.load_limits()["body-max-lines"]["value"], 7)
            finally:
                cs.CONVENTIONS = saved

    def test_limit_values_come_from_the_limits_not_the_script(self):
        d = make_skill(self.root, "s", HEAD + "a\nb\nc\nd\n")
        self.assertNotIn("body-max-lines", self.found(d))
        tight = json.loads(json.dumps(self.limits))
        tight["body-max-lines"]["value"] = 3
        self.assertIn("body-max-lines", {f["limit"] for f in cs.scan_skill(d, tight)["findings"]})


class Counts(unittest.TestCase):
    def test_token_count_grows_with_the_text(self):
        with tempfile.TemporaryDirectory() as t:
            limits = cs.load_limits()
            small = cs.scan_skill(make_skill(Path(t), "a", HEAD + "word\n"), limits)
            big = cs.scan_skill(make_skill(Path(t), "b", HEAD + "word\n" * 400), limits)
        self.assertGreater(small["tokens_estimate"], 0)
        self.assertGreater(big["tokens_estimate"], small["tokens_estimate"] * 10)

    def test_descriptions_with_shared_distinctive_words_overlap(self):
        d = "Publish approved articles to Framer and LinkedIn after an explicit go"
        a = {"skill": "a", "description": d}
        b = {"skill": "b", "description": d + " today"}
        c = {"skill": "c", "description": "Generate thumbnails for videos with gradients"}
        pairs = cs.overlap([a, b, c])
        self.assertEqual([(p["a"], p["b"]) for p in pairs], [("a", "b")])


class ReadOnly(unittest.TestCase):
    def test_scan_leaves_the_skills_byte_identical(self):
        with tempfile.TemporaryDirectory() as t:
            root, out = Path(t) / "skills", Path(t) / "out"
            make_skill(root, "s", HEAD + "# T\nNever skip.\n", {"references/a.md": "# A\n", "scripts/x.py": "x=1\n"})
            before = tree_hash(root)
            r = subprocess.run([sys.executable, str(SCRIPTS / "check_skills.py"), "--root", str(root),
                                "--out", str(out), "--summary"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(tree_hash(root), before)
            self.assertTrue((out / "check.json").is_file())


if __name__ == "__main__":
    unittest.main()
