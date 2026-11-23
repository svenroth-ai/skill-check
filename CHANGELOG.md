# Changelog

## Unreleased

- The parts table lists the real instructions that code can take over, instead of a count. "Open the SKILL.md" shows the whole text in a window, with every instruction marked. Table headers in the text are filled to the width of the table.
- The text of a skill is drawn with tables and nested lists, so bullets sit at the right depth.
- Read the text of a skill: on the page of each skill, "Read the text of this skill" shows its SKILL.md with every instruction marked: code can hold it, code holds it today, or it stays text.
- The Upgrade page has one Start button and shows the next step after it. The command to type is tucked away under "Start it by hand instead". Questions are asked in the chat, so the view no longer has a questions page.
- The summary card shows three numbers on one line; the legend under the bar carries the counts.
- Keep control (Level 3): fifth step in the navigation. Pages: choose an upgraded skill, explanation, the written list with its tests, result. Skill Upgrade (new step 8) saves the written list as the agreement and marks the skill as in control; its check names, in plain words, each instruction that no longer holds, and a hook runs it after every edit to the skill.
- Levels: the view reads the level of every skill (1 Written, 2 Enforced, 3 In control) and marks where your skills are on the start page and the report (tick for reached levels, cross for open ones).
- Skills from a plugin (marketplace) are recognised by their real path, shown as "From a plugin", and never upgraded or changed: Skill Upgrade refuses them and the answers route refuses.
- The agent's name is set in one place (`scripts/agent.py`, `docs/agent-names.md` lists the rest).
- Questions and Report pages in the view for a skill that Skill Upgrade is working on: the open questions with a suggested answer (answers are saved to the skill's `baseline/answers.json`, which Skill Upgrade applies instead of asking again) and the report per part (instructions, enforced before, proven now). `trace_check.py --status` now also writes the result per criterion. New routes `/api/upgrade` and `POST /api/answers` (same-origin, localhost only).
- New view (design v10): Start page that explains the problem, Choose a skill (real table, suggestion from your own use in the last 90 days), Check it (instructions in total, held by code today, can be added, stay text; parts table), and the buy page or the `/skill-upgrade` command. Numbers come from `scripts/skill_score.py` (`/api/skills`, `/api/skill`). Browser test: `tests/e2e_web.py`.
- The paid product is now Skill Upgrade (`/skill-upgrade`, plugin `shipwright-skill-upgrade`), formerly Skill Harden. Its skill description is valid YAML now (it was not, and the skill loaded with empty metadata).
- The pane hook no longer uses `setTimeout` (not available in a plugin module) and notices an older server on the port.
- `skill_usage.py`: counts how often each skill was used in the last 30 days from Claude Code's own local history (read-only; only names and times are kept, no prompt text), to suggest where to start. No history means no suggestion.
- Found by a blind end-to-end run on launch-video: `bind_ac.py` writes decisions and checks (no hand-edited JSON); a rule decided to stay text counts as `text`, not as an open gap, and no longer keeps the view from "Keep it safe"; the grill asks up to 12 questions in one batch; `pin_by_destruction.py` leaves files over 5 MB out of its copy (it refused a 668 MB skill); SKILL.md says what to do when nothing is pinned, what clears an open stage, and how to read the paths; binding.md no longer contradicts the proposed-check shape.
- `pin_by_destruction.py`: a test binding is proven by removing one rule in a copy of the skill and watching which of the skill's own tests turn red. Word overlap stays a proposal.
- `classify_acs.py`: a fourth class, `command` (a literal outgoing command such as `gh pr merge` or an upload); it stays one line in the skill and a test pins its arguments.
- `trace.json` carries `schema_version` (1); an unknown version is refused.
- `compare_runs.py --trace` writes scenario outcomes into trace.json; `trace_check.py` then reports them (same and improvement pass, regression fails, the rest is "review") instead of "not run".
- `harden_state.py`: Skill Harden says plainly when Skill Check is missing, reports what Skill Check found, and writes the stage of the hardening for the view; the one button follows the stage.
- Skill Harden step 7 proposes hooks in plain words (not built yet).
- `derive_requirements.py`: drafts the requirements of a skill from its text, one sentence per rule; a proposed check is never proof.
- Review fixes for the guided view: skill names are untrusted (never in a prompt unless a plain slug), proof files are validated, the button says when Skill Harden is missing, no raw errors in the pane, newest request wins.

- The pane is a guide: path, skill list, plain sentences, one primary button for the next step (`scripts/view_model.py`, `/api/view`).

- `packaging/`: the free and the paid product are built from one map (`split.json`); each stands alone and is tested on its own.

- `trace_check.py`: checks that every acceptance criterion is bound to a check that exists and passes; renders requirements in plain language.
- `baseline/skill-check/`: requirements and ACs of Skill Check itself, bound to tests.
- 14 new tests, closing the gaps the first trace run found. `serve.py` gets `make_server` and `BIND_HOST`.
- `docs/harden-flow.md`: first draft of the harden flow.

## 0.1.0

First release.

- Scanner: sections with anchors, token counts, authoring-limit findings, description overlap.
- Local view on 127.0.0.1:3921 and the `/skill-check` command.
- `refresh_inventory.py`: carry a classification over to an edited skill.
- Scenario check: `derive_scenarios.py` and `compare_runs.py` compare an old and a rebuilt skill.
