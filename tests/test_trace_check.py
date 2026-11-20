"""Tests for scripts/trace_check.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import trace_check as tc  # noqa: E402

PASS_T = "def test_ok(self): pass"
FAIL_T = "def test_bad(self): self.fail('x')"


def project(root: Path, checks: dict, tests: str = PASS_T + "\n    " + FAIL_T) -> Path:
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    " + tests + "\n", encoding="utf-8")
    (root / "doc.md").write_text("must hold the gate\n", encoding="utf-8")
    acs = [{"id": k, "text": "t", "source": "s", "check": v} for k, v in checks.items()]
    trace = root / "trace.json"
    trace.write_text(json.dumps({"subject": "x", "requirements": [{"id": "R1", "text": "r", "acs": acs}]}),
                     encoding="utf-8")
    return trace


def statuses(trace: Path, root: Path) -> dict:
    rows = tc.evaluate(tc.load(trace), root / "tests", root)
    return {r["ac"]: r["status"] for r in rows}


class Status(unittest.TestCase):
    def test_every_status(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            trace = project(root, {
                "A1": {"kind": "test", "id": "test_demo.T.test_ok"},
                "A2": {"kind": "test", "id": "test_demo.T.test_bad"},
                "A3": {"kind": "test", "id": "test_demo.T.test_missing"},
                "A4": {"kind": "test", "id": "no_such_module.T.test_x"},
                "A5": None,
                "A6": {"kind": "text", "file": "doc.md", "contains": "must hold the gate"},
                "A7": {"kind": "text", "file": "doc.md", "contains": "absent"},
                "A8": {"kind": "text", "file": "nope.md", "contains": "x"},
                "A9": {"kind": "scenario", "id": "S1"},
            })
            self.assertEqual(statuses(trace, root), {
                "A1": "passing", "A2": "failing", "A3": "dangling", "A4": "dangling", "A5": "gap",
                "A6": "passing", "A7": "failing", "A8": "dangling", "A9": "not-run"})

    def test_a_skipped_test_is_not_passing(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            trace = project(root, {"A1": {"kind": "test", "id": "test_demo.T.test_skip"}},
                            "@unittest.skip('x')\n    def test_skip(self): pass")
            self.assertEqual(statuses(trace, root)["A1"], "failing")


class Honest(unittest.TestCase):
    def test_expected_failure_is_not_passing(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            trace = project(root, {"A1": {"kind": "test", "id": "test_demo.T.test_xf"}},
                            "@unittest.expectedFailure\n    def test_xf(self): self.assertEqual(1, 2)")
            self.assertEqual(statuses(trace, root)["A1"], "failing")

    def test_a_test_outside_the_tests_folder_is_dangling(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            trace = project(root, {"A1": {"kind": "test", "id": "test_far.T.test_y"}})
            far = root / "far"
            far.mkdir()
            (far / "test_far.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_y(self): pass\n", encoding="utf-8")
            sys.path.append(str(far))
            try:
                self.assertEqual(statuses(trace, root)["A1"], "dangling")
            finally:
                sys.path.remove(str(far))
                sys.modules.pop("test_far", None)

    def test_same_module_name_in_two_projects_gives_each_its_own_answer(self):
        results = []
        for body, tid in ((FAIL_T, "test_demo.T.test_bad"), (PASS_T, "test_demo.T.test_ok"), (FAIL_T, "test_demo.T.test_bad")):
            with tempfile.TemporaryDirectory() as t:
                root = Path(t)
                trace = project(root, {"A1": {"kind": "test", "id": tid}}, body)
                results.append(statuses(trace, root)["A1"])
        self.assertEqual(results, ["failing", "passing", "failing"])

    def test_a_text_check_cannot_look_outside_the_root(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "proj"
            root.mkdir()
            outside = Path(t) / "secret.txt"
            outside.write_text("hello", encoding="utf-8")
            trace = project(root, {"A1": {"kind": "text", "file": "../secret.txt", "contains": "hello"},
                                   "A2": {"kind": "text", "file": str(outside), "contains": "hello"}})
            self.assertEqual(statuses(trace, root), {"A1": "dangling", "A2": "dangling"})

    def test_malformed_input_is_a_clean_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.json"
            good_ac = {"id": "A", "text": "t", "source": "s", "check": "x"}
            for doc in ([], {"requirements": [{"id": "R", "text": "r", "acs": [good_ac]}]},
                        {"requirements": ["x"]}, {"requirements": [{"id": "R", "text": "r", "acs": ["y"]}]}):
                p.write_text(json.dumps(doc), encoding="utf-8")
                with self.assertRaises(ValueError):
                    tc.load(p)
            r = subprocess.run([sys.executable, str(SCRIPTS / "trace_check.py"), str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)

    def test_a_weird_test_id_is_dangling(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            trace = project(root, {"A1": {"kind": "test", "id": "/"}, "A2": {"kind": "test", "id": ""}})
            self.assertEqual(statuses(trace, root), {"A1": "dangling", "A2": "dangling"})

    def test_the_committed_requirements_file_is_current(self):
        repo = SCRIPTS.parent
        trace = repo / "baseline" / "skill-check" / "trace.json"
        md = repo / "baseline" / "skill-check" / "requirements.md"
        if not (trace.is_file() and md.is_file()):
            self.skipTest("the harden folder is not part of this package")
        doc = tc.load(trace)
        rows = tc.evaluate(doc, repo / "tests", repo)
        norm = lambda s: s.replace("\r\n", "\n")  # noqa: E731
        self.assertEqual(norm(md.read_text(encoding="utf-8")), norm(tc.render(doc, rows)))


class Counts(unittest.TestCase):
    def test_counts_and_the_status_file_have_the_exact_numbers(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            ok = {"kind": "test", "id": "test_demo.T.test_ok"}
            trace = project(root, {"A1": ok, "A2": {"kind": "test", "id": "test_demo.T.test_bad"},
                                   "A3": {"kind": "test", "id": "test_demo.T.test_missing"}, "A4": None,
                                   "A5": {**ok, "proposed": True}, "A6": ok})
            rows = tc.evaluate(tc.load(trace), root / "tests", root)
            want = {"total": 6, "passing": 2, "failing": 1, "gap": 1, "text": 0, "other": 2}
            self.assertEqual(tc.counts(rows), want)
            out = root / "s" / "status.json"
            r = subprocess.run([sys.executable, str(SCRIPTS / "trace_check.py"), str(trace), "--tests",
                                str(root / "tests"), "--status", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)  # one failing, one dangling
            have = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(have.pop("acs"), {"A1": "passing", "A2": "failing", "A3": "dangling", "A4": "gap",
                                               "A5": "proposed", "A6": "passing"})  # per criterion, for the report page
            self.assertEqual(have, want)

    def test_a_proposed_check_is_reported_and_never_run(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            trace = project(root, {"A1": {"kind": "test", "id": "test_demo.T.test_bad", "proposed": True}})
            self.assertEqual(statuses(trace, root)["A1"], "proposed")


class PackageTests(unittest.TestCase):
    def test_tests_that_import_their_own_package_are_found(self):
        """A skill's tests are a package: `from tests import helper` must work from any working directory."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "tests").mkdir()
            (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (root / "tests" / "helper.py").write_text("VALUE = 3", encoding="utf-8")
            body = "\n".join(["import unittest", "from tests import helper", "",
                              "class T(unittest.TestCase):",
                              "    def test_ok(self):",
                              "        self.assertEqual(helper.VALUE, 3)", ""])
            (root / "tests" / "test_pkg.py").write_text(body, encoding="utf-8")
            self.assertEqual(tc.run_test("test_pkg.T.test_ok", root / "tests"), "passing")
            self.assertFalse((root / "tests" / "__pycache__").exists())  # running the tests leaves nothing behind

    def test_an_id_that_is_not_a_test_of_the_skill_is_never_imported_or_called(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "tests").mkdir()
            (root / "tests" / "test_one.py").write_text("def test_f():" + chr(10) + "    raise SystemExit(0)" + chr(10), encoding="utf-8")
            for bad in ("sys.exit", "os.abort", "os.getcwd", "sys.exit.x", "../x.T.t", "builtins.exit.t", "test_none.T.test_a",
                        "test_one.test_f"):  # a module of the skill, but a bare function: not module.Class.test
                self.assertEqual(tc.run_test(bad, root / "tests"), "dangling", bad)

    def test_the_skills_own_tests_package_wins_over_another_installed_one_and_leaves_no_pycache(self):
        """Run in a fresh interpreter (bytecode writing on, a foreign `tests` package on PYTHONPATH)."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            other = root / "site"
            (other / "tests").mkdir(parents=True)
            (other / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (other / "tests" / "helper.py").write_text("VALUE = 99", encoding="utf-8")
            skill = root / "skill"
            (skill / "tests").mkdir(parents=True)
            (skill / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (skill / "tests" / "helper.py").write_text("VALUE = 3", encoding="utf-8")
            body = chr(10).join(["import unittest", "from tests import helper", "", "class T(unittest.TestCase):",
                                 "    def test_ok(self):", "        self.assertEqual(helper.VALUE, 3)", ""])
            (skill / "tests" / "test_pkg.py").write_text(body, encoding="utf-8")
            code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); import trace_check as tc; "
                    "print(tc.run_test('test_pkg.T.test_ok', pathlib.Path(sys.argv[2])))")
            env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
            env["PYTHONPATH"] = str(other)
            r = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(skill / "tests")], cwd=str(root),
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.stdout.strip(), "passing", r.stderr)
            self.assertFalse((skill / "tests" / "__pycache__").exists())


class Lists(unittest.TestCase):
    def test_a_list_of_checks_needs_all_of_them(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            ok, bad, miss = ({"kind": "test", "id": f"test_demo.T.{n}"} for n in ("test_ok", "test_bad", "test_nope"))
            trace = project(root, {"A1": [ok, ok], "A2": [ok, bad], "A3": [ok, miss], "A5": []})
            self.assertEqual(statuses(trace, root),
                             {"A1": "passing", "A2": "failing", "A3": "dangling", "A5": "gap"})
            bad_doc = project(Path(t) / "x", {"A1": [ok, None]}) if (Path(t) / "x").mkdir() is None else None
            with self.assertRaises(ValueError):
                tc.load(bad_doc)


class Cli(unittest.TestCase):
    def run_cli(self, trace: Path, *extra):
        return subprocess.run([sys.executable, str(SCRIPTS / "trace_check.py"), str(trace),
                               "--tests", str(trace.parent / "tests"), *extra], capture_output=True, text=True)

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as t:
            ok = project(Path(t), {"A1": {"kind": "test", "id": "test_demo.T.test_ok"}, "A2": None})
            self.assertEqual(self.run_cli(ok).returncode, 0)
            self.assertEqual(self.run_cli(ok, "--strict").returncode, 1)
        with tempfile.TemporaryDirectory() as t:
            bad = project(Path(t), {"A1": {"kind": "test", "id": "test_demo.T.test_bad"}})
            self.assertEqual(self.run_cli(bad).returncode, 1)
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "x.json").write_text("{}", encoding="utf-8")
            self.assertEqual(self.run_cli(Path(t) / "x.json").returncode, 2)

    def test_schema_rejects_duplicates_and_unknown_kind(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.json"
            ac = lambda i, c=None: {"id": i, "text": "t", "source": "s", "check": c}  # noqa: E731
            for acs in ([ac("A1"), ac("A1")], [ac("A1", {"kind": "magic"})], [{"id": "A1", "text": "t"}]):
                p.write_text(json.dumps({"requirements": [{"id": "R", "text": "r", "acs": acs}]}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    tc.load(p)

    def test_an_unknown_schema_version_is_refused_and_none_means_one(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "t.json"
            body = {"requirements": [{"id": "R", "text": "r", "acs": [{"id": "A1", "text": "t", "source": "s", "check": None}]}]}
            p.write_text(json.dumps(body), encoding="utf-8")
            tc.load(p)  # an older file without the field still loads
            p.write_text(json.dumps({**body, "schema_version": 1}), encoding="utf-8")
            tc.load(p)
            p.write_text(json.dumps({**body, "schema_version": 2}), encoding="utf-8")
            with self.assertRaises(ValueError):
                tc.load(p)

    def test_markdown_lists_status_and_gaps(self):
        with tempfile.TemporaryDirectory() as t:
            trace = project(Path(t), {"A1": {"kind": "test", "id": "test_demo.T.test_ok"}, "A2": None})
            md = Path(t) / "out.md"
            self.run_cli(trace, "--md", str(md))
            text = md.read_text(encoding="utf-8")
            self.assertIn("[passing]", text)
            self.assertIn("no check yet", text)


if __name__ == "__main__":
    unittest.main()
