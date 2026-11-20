"""Tests for scripts/skill_score.py and the /api/skills route. Run: python -m unittest discover -s tests"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import serve  # noqa: E402
import skill_score as ss  # noqa: E402

SKILL = """---
name: demo
description: A demo skill.
---
# Demo

## Upload
- You must run `check_size.py` before every upload.
- Always ask before uploading anything to the shared drive.
- The caption size must be exactly 44 px.

## Style
- You must keep the tone natural and clear.
- Never be vague.
"""


def make_skill(root: Path, name: str, body: str = SKILL, script: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    if script:
        (d / "scripts").mkdir()
        (d / "scripts" / "check_size.py").write_text("print(1)\n", encoding="utf-8")
    return d


class Score(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_add_up_and_a_shipped_script_counts_as_enforced(self):
        r = ss.score(make_skill(self.root, "demo"))
        self.assertEqual(r["total"], r["hold"] + r["text"])
        self.assertEqual(r["hold"], r["enforced"] + r["add"])
        self.assertGreaterEqual(r["enforced"], 1)  # the sentence names check_size.py and the file exists
        self.assertGreaterEqual(r["add"], 1)       # the ask gate and the exact size are not held yet
        self.assertGreaterEqual(r["text"], 1)      # the tone sentence stays text
        self.assertEqual(r["status"], "upgrade")

    def test_a_named_script_that_does_not_exist_is_not_enforced(self):
        r = ss.score(make_skill(self.root, "demo", script=False))
        self.assertEqual(r["enforced"], 0)

    def test_percentages_and_parts_follow_the_counts(self):
        r = ss.score(make_skill(self.root, "demo"))
        self.assertEqual(r["pct"]["enforced"], round(100 * r["enforced"] / r["total"]))
        self.assertEqual(sum(p["total"] for p in r["parts"]), r["total"])
        self.assertTrue(all(p["status"] in {"upgrade", "good", "text"} for p in r["parts"]))

    def test_same_skill_same_numbers(self):
        d = make_skill(self.root, "demo")
        self.assertEqual(ss.score(d), ss.score(d))

    def test_a_skill_without_rules_has_nothing_to_score(self):
        r = ss.score(make_skill(self.root, "plain", "---\nname: plain\ndescription: x\n---\n# Plain\n\nHello.\n"))
        self.assertEqual((r["total"], r["status"]), (0, "none"))
        self.assertEqual(r["pct"]["enforced"], 0)  # no division by zero

    def test_suggest_needs_enough_use_and_something_to_add(self):
        rows = [{"skill": "a", "add": 3, "pct": {"enforced": 10}}, {"skill": "b", "add": 3, "pct": {"enforced": 50}},
                {"skill": "c", "add": 0, "pct": {"enforced": 0}}]
        self.assertEqual(ss.suggest(rows, {"a": 12, "b": 20, "c": 30})["skill"], "a")  # lowest share among the used
        self.assertIsNone(ss.suggest(rows, {"a": 2, "b": 1}))                         # fewer than 3 uses: no suggestion
        self.assertIsNone(ss.suggest(rows, {"c": 30}))                                 # nothing to add


class Route(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.skills, self.out, self.proj = base / "skills", base / "out", base / "proj"
        for p in (self.out, self.proj / "p1"):
            p.mkdir(parents=True)
        make_skill(self.skills, "demo")
        (self.out / "check.json").write_text(json.dumps({"skills": []}), encoding="utf-8")
        line = json.dumps({"type": "user", "timestamp": "2999-01-01T00:00:00Z",
                           "message": {"content": "<command-name>/demo</command-name>"}})
        (self.proj / "p1" / "s.jsonl").write_text("\n".join([line] * 4) + "\n", encoding="utf-8")
        self.server = serve.ExclusiveServer(("127.0.0.1", 0), serve.make_handler(self.out, [self.skills], self.proj))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest("GET", path, skip_host=True)
        c.putheader("Host", f"localhost:{self.port}")
        c.endheaders()
        r = c.getresponse()
        return r.status, r.read()

    def test_skills_route_lists_numbers_usage_and_suggestion(self):
        status, body = self.get("/api/skills")
        d = json.loads(body)
        self.assertEqual(status, 200)
        names = [s["skill"] for s in d["skills"]]
        self.assertIn("demo", names)
        demo = d["skills"][names.index("demo")]
        self.assertEqual(demo["uses"], 4)
        self.assertNotIn("parts", demo)
        self.assertEqual(d["suggest"]["skill"], "demo")
        self.assertIn("upgrade_installed", d)

    def test_skills_route_says_where_a_skill_comes_from_and_its_level(self):
        d = json.loads(self.get("/api/skills")[1])
        demo = next(s for s in d["skills"] if s["skill"] == "demo")
        self.assertEqual(demo["origin"], {"kind": "own"})
        self.assertEqual((demo["level"], demo["upgraded"]), (1, False))  # code holds less than it could, never upgraded
        self.assertEqual(d["levels"], {"1": 1, "2": 0, "3": 0})

    def test_skill_route_has_parts_and_rejects_unknown_names(self):
        status, body = self.get("/api/skill?name=demo")
        self.assertEqual((status, json.loads(body)["skill"]), (200, "demo"))
        self.assertTrue(json.loads(body)["parts"])
        self.assertEqual(self.get("/api/skill?name=nope")[0], 404)
        self.assertEqual(self.get("/api/skill?name=..%2F..")[0], 404)


if __name__ == "__main__":
    unittest.main()
