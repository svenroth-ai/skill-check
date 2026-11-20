"""The agent's name is set in one place (scripts/agent.py). Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import agent  # noqa: E402
import classify_acs as ca  # noqa: E402
import view_model as vm  # noqa: E402


class Names(unittest.TestCase):
    def setUp(self):
        self.old = (agent.NAME, agent.HOST)

    def tearDown(self):
        agent.NAME, agent.HOST = self.old

    def test_say_fills_both_names(self):
        agent.NAME, agent.HOST = "Codex", "Codex CLI"
        self.assertEqual(agent.say("{agent} runs in {host}"), "Codex runs in Codex CLI")

    def test_texts_a_person_reads_follow_the_name(self):
        agent.NAME = "Codex"
        skill = {"tokens_estimate": 400, "reference_tokens_estimate": 0, "scripts": 0, "rule_like_lines": 0,
                 "findings": [{"limit": "description-required", "kind": "hard"}]}
        text = " ".join(vm.describe(skill))
        self.assertIn("Codex", text)
        self.assertNotIn("Claude", text)
        doc = {"requirements": [{"id": "R", "text": "r", "acs": [{"id": "A", "text": "The width must be exactly 10 px.", "source": "s"}]}]}
        _, grill = ca.run(doc)
        self.assertNotIn("Claude", json_text(grill))

    def test_no_placeholder_is_left_in_the_view_texts(self):
        for sentence in vm.PLAIN.values():
            self.assertNotIn("{", agent.say(sentence))


def json_text(o) -> str:
    import json
    return json.dumps(o)


if __name__ == "__main__":
    unittest.main()
