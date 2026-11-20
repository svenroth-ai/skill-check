"""Tests for scripts/upgrade_view.py and the /api/upgrade and /api/answers routes. Run: python -m unittest discover -s tests"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import serve  # noqa: E402
import upgrade_view as uv  # noqa: E402
from test_skill_score import make_skill  # noqa: E402

TRACE = {"subject": "demo", "classes": {}, "requirements": [
    {"id": "R1", "text": "Upload", "acs": [
        {"id": "A1", "text": "You must run `check_size.py` before every upload.", "source": "SKILL.md:1", "class": "mechanic"},
        {"id": "A2", "text": "The caption size must be exactly 44 px.", "source": "SKILL.md:2", "class": "mechanic"}]},
    {"id": "R2", "text": "Style", "acs": [
        {"id": "A3", "text": "Keep the tone natural.", "source": "SKILL.md:3", "class": "judgement"}]}]}
GRILL = {"batches": [[{"ac": "A2", "kind": "script?", "text": "The caption size must be exactly 44 px.",
                       "why": "Because.", "suggest": "yes: check this in code"}]]}


def baseline(skill: Path, trace=TRACE, grill=GRILL):
    b = skill / "baseline"
    b.mkdir()
    (b / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    (b / "grill.json").write_text(json.dumps(grill), encoding="utf-8")


class View(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.skill = make_skill(Path(self.tmp.name), "demo")
        baseline(self.skill)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_questions_carry_the_suggestion_and_a_saved_answer(self):
        q = uv.questions(self.skill)
        self.assertEqual([(x["ac"], x["suggest"], x["answer"]) for x in q], [("A2", "yes", None)])
        uv.save_answers(self.skill, {"A2": "no"})
        self.assertEqual(uv.questions(self.skill)[0]["answer"], "no")

    def test_only_answers_to_open_questions_with_a_valid_choice_are_kept(self):
        kept = uv.save_answers(self.skill, {"A2": "yes", "A1": "yes", "../x": "yes", "A3": "maybe"})
        self.assertEqual(kept, {"A2": "yes"})
        self.assertEqual(json.loads((self.skill / "baseline" / "answers.json").read_text(encoding="utf-8")), {"A2": "yes"})

    def test_a_decided_question_is_no_longer_open(self):
        t = json.loads(json.dumps(TRACE))
        t["requirements"][0]["acs"][1]["decision"] = "text: stays written"
        (self.skill / "baseline" / "trace.json").write_text(json.dumps(t), encoding="utf-8")
        self.assertEqual(uv.questions(self.skill), [])

    def test_report_needs_the_per_criterion_results(self):
        self.assertIsNone(uv.report(self.skill, {"stage": {"name": "ready", "open": 0}}))
        r = uv.report(self.skill, {"acs": {"A1": "passing", "A2": "gap", "A3": "text"}})
        t = r["totals"]
        self.assertEqual((t["total"], t["hold"], t["before"], t["now"], t["text"]), (3, 2, 1, 1, 1))
        self.assertEqual(t["pct_now"], 50)
        self.assertEqual(r["open_checks"], 1)
        self.assertEqual([p["status"] for p in r["parts"]], ["open", "text"])

    def test_a_proposed_check_is_not_proven_in_the_report(self):
        r = uv.report(self.skill, {"acs": {"A1": "proposed", "A2": "proposed", "A3": "text"}})
        self.assertEqual(r["totals"]["now"], 0)


class Control(unittest.TestCase):
    def test_the_list_says_which_lines_have_a_test_and_which_are_prose(self):
        with tempfile.TemporaryDirectory() as t:
            skill = make_skill(Path(t), "demo")
            baseline(skill)
            c = uv.control(skill, {"acs": {"A1": "passing", "A2": "gap", "A3": "text"}, "controlled_at": "2026-11-20T10:00:00Z"})
            self.assertEqual(c["totals"], {"lines": 3, "tests": 1, "prose": 1, "open": 1})
            self.assertEqual([x["kind"] for x in c["parts"][0]["lines"]], ["test", "open"])
            self.assertEqual(c["controlled_at"], "2026-11-20T10:00:00Z")
            self.assertIsNone(uv.control(skill, None))


class Route(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.skills, self.out = base / "skills", base / "out"
        (self.out / "baseline" / "demo").mkdir(parents=True)
        self.skill = make_skill(self.skills, "demo")
        make_skill(self.skills, "bare")
        baseline(self.skill)
        (self.out / "baseline" / "demo" / "status.json").write_text(
            json.dumps({"stage": {"name": "questions", "open": 1}, "acs": {"A1": "passing", "A2": "gap", "A3": "text"}}),
            encoding="utf-8")
        self.server = serve.ExclusiveServer(("127.0.0.1", 0), serve.make_handler(self.out, [self.skills], base / "none"))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def req(self, method, path, body=None, host=None, origin="same", ctype="application/json"):
        host = host or f"localhost:{self.port}"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest(method, path, skip_host=True)
        c.putheader("Host", host)
        if origin:
            c.putheader("Origin", f"http://{host}" if origin == "same" else origin)
        data = json.dumps(body).encode() if body is not None else b""
        if method == "POST":
            c.putheader("Content-Type", ctype)
            c.putheader("Content-Length", str(len(data)))
        c.endheaders(data)
        r = c.getresponse()
        return r.status, r.read()

    def test_upgrade_route_returns_questions_and_report(self):
        s, b = self.req("GET", "/api/upgrade?name=demo", origin=None)
        d = json.loads(b)
        self.assertEqual((s, d["stage"], d["open"]), (200, "questions", 1))
        self.assertEqual(d["questions"][0]["ac"], "A2")
        self.assertEqual(d["report"]["totals"]["now"], 1)
        self.assertEqual(self.req("GET", "/api/upgrade?name=nope", origin=None)[0], 404)
        self.assertEqual(self.req("GET", "/api/upgrade?name=..%2Fx", origin=None)[0], 404)

    def test_a_skill_without_a_baseline_has_nothing_yet(self):
        d = json.loads(self.req("GET", "/api/upgrade?name=bare", origin=None)[1])
        self.assertEqual((d["questions"], d["report"], d["stage"]), ([], None, "none"))

    def test_answers_are_saved_for_open_questions_only(self):
        s, b = self.req("POST", "/api/answers?name=demo", {"A2": "no", "A1": "yes"})
        self.assertEqual((s, json.loads(b)["saved"]), (200, {"A2": "no"}))
        self.assertEqual(json.loads((self.skill / "baseline" / "answers.json").read_text(encoding="utf-8")), {"A2": "no"})

    def test_answers_from_another_site_or_host_are_refused(self):
        self.assertEqual(self.req("POST", "/api/answers?name=demo", {"A2": "no"}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.req("POST", "/api/answers?name=demo", {"A2": "no"}, origin=None)[0], 403)
        self.assertEqual(self.req("POST", "/api/answers?name=demo", {"A2": "no"}, host="evil.example")[0], 403)
        self.assertFalse((self.skill / "baseline" / "answers.json").exists())

    def test_bad_posts_are_refused(self):
        self.assertEqual(self.req("POST", "/api/answers?name=demo", {"A2": "no"}, ctype="text/plain")[0], 404)
        self.assertEqual(self.req("POST", "/api/answers?name=nope", {"A2": "no"})[0], 400)
        self.assertEqual(self.req("POST", "/api/answers?name=demo", ["x"])[0], 400)
        self.assertEqual(self.req("POST", "/api/answers?name=bare", {"A2": "no"})[0], 409)  # no baseline folder

    def test_a_user_can_say_a_skill_is_not_theirs_and_it_is_then_refused(self):
        from unittest import mock
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        with mock.patch("pathlib.Path.home", return_value=home):
            s, b = self.req("POST", "/api/origin?name=demo", {"mine": False})
            self.assertEqual((s, json.loads(b)["origin"]), (200, {"kind": "foreign"}))
            self.assertEqual(self.req("POST", "/api/answers?name=demo", {"A2": "no"})[0], 403)
            self.assertEqual(self.req("POST", "/api/origin?name=demo", {"mine": "yes"})[0], 400)
            self.assertEqual(json.loads(self.req("POST", "/api/origin?name=demo", {"mine": True})[1])["origin"], {"kind": "own"})
        self.assertTrue((home / ".shipwright" / "skill-check" / "origin_marks.json").is_file())

    def test_a_click_in_the_view_is_handed_to_the_chat_in_fixed_words(self):
        s, b = self.req("POST", "/api/intent?name=demo", {"action": "upgrade"})
        self.assertEqual((s, json.loads(b)), (200, {"queued": True, "listening": False}))
        self.assertEqual(self.req("POST", "/api/intent?name=demo", {"action": "rm -rf"})[0], 400)  # no free text
        self.assertEqual(self.req("POST", "/api/intent?name=nope", {"action": "upgrade"})[0], 400)
        self.assertEqual(self.req("POST", "/api/intent?name=demo", {"action": "upgrade"}, origin="http://evil.example")[0], 403)
        s, b = self.req("POST", "/api/intent/take", {})
        self.assertEqual(json.loads(b), {"text": 'Upgrade the skill "demo" with Skill Upgrade.'})
        self.assertEqual(json.loads(self.req("POST", "/api/intent/take", {})[1]), {})  # taken once
        self.assertTrue(json.loads(self.req("GET", "/api/intent/status", origin=None)[1])["listening"])  # it just asked


if __name__ == "__main__":
    unittest.main()
