"""Tests for scripts/skill_usage.py: usage is counted from the local history, and no prompt text leaves it."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import skill_usage as su  # noqa: E402

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def ts(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def call(name, days_ago=1, args="SECRET PROMPT TEXT"):
    return json.dumps({"type": "assistant", "timestamp": ts(days_ago), "message": {"content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": name, "args": args}}]}})


def slash(name, days_ago=1):
    return json.dumps({"type": "user", "timestamp": ts(days_ago), "message": {
        "content": f"<command-name>/{name}</command-name>"}})


def history(root: Path, lines):
    d = root / "proj"
    d.mkdir()
    (d / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


class Usage(unittest.TestCase):
    def count(self, lines, days=30):
        with tempfile.TemporaryDirectory() as t:
            return su.usage(history(Path(t), lines), days, NOW)

    def test_tool_calls_and_typed_commands_are_counted_under_the_plain_name(self):
        got = self.count([call("launch-video"), call("launch-video"), call("shipwright-iterate:iterate"), slash("iterate")])
        self.assertEqual(got["usage"], {"launch-video": 2, "iterate": 2})
        self.assertEqual(got["sessions"], 1)

    def test_old_uses_are_left_out(self):
        got = self.count([call("a", 5), call("a", 40), call("b", 31)])
        self.assertEqual(got["usage"], {"a": 1})

    def test_no_prompt_text_is_ever_in_the_result(self):
        self.assertNotIn("SECRET", json.dumps(self.count([call("a")])))

    def test_broken_lines_and_other_tools_are_skipped(self):
        other = json.dumps({"type": "assistant", "timestamp": ts(1), "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"skill": "x"}}]}})
        got = self.count(["{not json", other, call("a")])
        self.assertEqual(got["usage"], {"a": 1})

    def test_no_history_is_an_empty_result_not_an_error(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(su.usage(Path(t), 30, NOW), {"days": 30, "sessions": 0, "usage": {}})


class Cli(unittest.TestCase):
    def test_a_missing_folder_exits_2_cleanly(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "skill_usage.py"), "--projects", "/no/such/folder"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
