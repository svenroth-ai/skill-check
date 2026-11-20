"""The names of the AI agent and the tool it runs in, in one place.

Texts that a person reads say {agent} and {host}; say() fills them in. To support another agent (for example Codex)
change NAME and HOST here, or set SKILL_CHECK_AGENT and SKILL_CHECK_HOST. Files that are read by the agent itself
(SKILL.md and its references) and the README are written for Claude Code and are listed in docs/agent-names.md.
"""
import os

NAME = os.environ.get("SKILL_CHECK_AGENT", "Claude")
HOST = os.environ.get("SKILL_CHECK_HOST", "Claude Code")


def say(text: str) -> str:
    return text.replace("{agent}", NAME).replace("{host}", HOST)
