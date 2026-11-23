#!/usr/bin/env python3
"""Browser test of the Skill Check view (Playwright). Not part of the unit run: it needs a browser.

    python tests/e2e_web.py          (needs: pip install playwright; a Chromium or Edge on this machine)

It starts the real server on a free port with a small fixture (two skills, some usage) and walks the real page:
start, choose a skill, check it, upgrade it, at desktop and phone width. Exit code 0 when every step holds.
"""
from __future__ import annotations
import os

import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import serve  # noqa: E402
from test_skill_score import make_skill  # noqa: E402
from test_upgrade_view import baseline  # noqa: E402

PLAIN = "---\nname: calm\ndescription: Calm.\n---\n# Calm\n\nWrite clearly.\n"
FAILED: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILED.append(what)


def launch(p):
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**kw)
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("no browser found for Playwright: run `playwright install chromium`")


def main() -> int:
    from playwright.sync_api import sync_playwright

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    skills, out, proj = base / "skills", base / "out", base / "proj"
    (proj / "p1").mkdir(parents=True)
    out.mkdir()
    demo = make_skill(skills, "demo")
    with open(demo / "SKILL.md", "a", encoding="utf-8") as f:  # a table and nested lists, to see them drawn
        f.write("\n## Formats\n\n| Format | Ratio |\n|---|---|\n| Wide | 16:9 |\n| Tall | 9:16 |\n\n1. First step\n   - nested point\n   - another point\n2. Second step\n")
    make_skill(skills, "calm", PLAIN, script=False)
    line = json.dumps({"type": "user", "timestamp": "2999-01-01T00:00:00Z",
                       "message": {"content": "<command-name>/demo</command-name>"}})
    (proj / "p1" / "s.jsonl").write_text("\n".join([line] * 5) + "\n", encoding="utf-8")
    baseline(skills / "demo")  # a hardening in progress: one open question
    (out / "baseline" / "demo").mkdir(parents=True)
    (out / "baseline" / "demo" / "status.json").write_text(json.dumps(
        {"stage": {"name": "questions", "open": 1}, "acs": {"A1": "passing", "A2": "gap", "A3": "text"}}), encoding="utf-8")
    installed = {"v": False}
    serve.view_model.installed_harden = lambda *_a: installed["v"]  # the test must not depend on this machine
    server = serve.ExclusiveServer(("127.0.0.1", 0), serve.make_handler(out, [skills], proj))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://localhost:{server.server_address[1]}/"

    with sync_playwright() as p:
        b = launch(p)
        os.environ["USERPROFILE"] = os.environ["HOME"] = tmp.name  # marks the test sets must never land in the real home
        for label, size in (("desktop", {"width": 1280, "height": 900}), ("phone", {"width": 390, "height": 800})):
            page = b.new_page(viewport=size)
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "404" not in m.text else None)
            page.goto(url)
            check(page.locator("#v-welcome.on h2").inner_text().startswith("Because a skill is only a request"),
                  f"{label}: start page explains the problem")
            check(page.locator("#steps li.on .t").inner_text() == "Start", f"{label}: Start is the current step")
            page.click("text=Start: choose a skill")
            page.wait_for_selector("#skill-rows tr")
            names = page.locator("#skill-rows .rowlink").all_inner_texts()
            check(names == ["demo", "calm"], f"{label}: skills listed by use, got {names}")
            check("demo" in page.locator("#suggest").inner_text() and "5 times" in page.locator("#suggest").inner_text(),
                  f"{label}: the used skill is suggested with its real count")
            check(page.locator("#skill-rows tr").first.locator(".now").is_visible() or label == "phone",
                  f"{label}: numbers visible in the table")
            page.click("#skill-rows .rowlink >> nth=0")
            page.wait_for_selector("#check-body .summary")
            check(page.locator("#check-body h2").inner_text() == "demo", f"{label}: check page names the skill")
            sub = page.locator("#check-body > .sub").first.inner_text()
            check(sub.startswith("You wrote ") and "Code can hold" in sub, f"{label}: plain summary line: {sub}")
            check(page.locator("#split").get_attribute("aria-label").startswith("Of "), f"{label}: bar has a text alternative")
            check(page.locator("#check-body table.tbl tbody tr").count() >= 1, f"{label}: parts table has rows")
            check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"{label}: no horizontal scroll")
            page.click("text=Upgrade this skill")
            page.wait_for_selector("#v-upgrade.on")
            check(page.locator("#up-buy").is_visible(), f"{label}: buy page shows when Skill Upgrade is not installed")
            check(page.locator("#buy-btn").get_attribute("aria-disabled") == "true"
                  and page.locator("#buy-note").is_visible(), f"{label}: buy button is closed until a checkout link is set")
            check("demo" in page.locator("#up-first").inner_text(), f"{label}: buy page names the chosen skill")
            check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"{label}: buy page has no horizontal scroll")
            page.goto(url + "#/skill/calm")
            page.wait_for_selector("#check-body h2")
            check("nothing for code to hold" in page.locator("#check-body").inner_text(), f"{label}: a skill without instructions says so")
            page.goto(url + "#/skill/nope")
            page.wait_for_selector("#check-body")
            check("could not be read" in page.locator("#check-body").inner_text()
                  or page.locator("#check-body h2").count() == 0, f"{label}: unknown skill is handled")
            installed["v"] = True
            page.goto(url + "#/upgrade/demo")
            page.reload()
            page.wait_for_selector("#up-installed:not([hidden])")
            check(page.locator("#cmd").text_content() == "/skill-upgrade demo" and not page.locator("#up-buy").is_visible(),
                  f"{label}: with Skill Upgrade installed the page gives the command, not the buy page")
            page.wait_for_selector("#where")
            where = page.locator("#where").inner_text()
            check("in the chat" in where and page.locator("#where a").count() == 0, f"{label}: open questions are asked in the chat, the page only says so: {where!r}")
            check(page.locator("#go-chat").inner_text() == "Start", f"{label}: one Start button")
            page.goto(url + "#/ask/demo")
            page.wait_for_function("location.hash.startsWith('#/upgrade/')")
            check(True, f"{label}: the old questions page leads back to the upgrade page")
            page.goto(url + "#/skill/demo")
            page.reload()
            page.wait_for_selector("details.skill-text")
            page.click("details.skill-text summary")
            page.wait_for_selector("details.skill-text .doc .ln")
            check(page.locator("details.skill-text .doc table.doc-tbl tbody tr").count() == 2, f"{label}: a table in the skill text is drawn as a table")
            pads = page.evaluate("[...document.querySelectorAll('.doc .li')].map(e => parseInt(e.style.paddingLeft))")
            check(len(pads) >= 4 and max(pads) > min(pads), f"{label}: nested list items are indented: {pads}")
            check(page.locator("details.skill-text .doc-key").count() == 1, f"{label}: the skill text comes with its key")
            check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"{label}: skill text has no horizontal scroll")
            page.goto(url + "#/done/demo")
            page.reload()
            page.wait_for_selector("#done-body table.report")
            check("50%" in page.locator("#done-body .summary").inner_text(), f"{label}: report shows the proven share")
            check(page.locator("#done-body table.report tbody tr").count() == 3, f"{label}: report lists the parts and a total")
            check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"{label}: report page has no horizontal scroll")
            # Keep control: the skill has passed every check, so it is at Level 2
            status_file = out / "baseline" / "demo" / "status.json"
            before = status_file.read_text(encoding="utf-8")
            status_file.write_text(json.dumps({"stage": {"name": "ready", "open": 0}, "total": 3, "passing": 2, "failing": 0,
                                               "gap": 0, "text": 1, "other": 0,
                                               "acs": {"A1": "passing", "A2": "passing", "A3": "text"}}), encoding="utf-8")
            page.goto(url + "#/control")
            page.reload()
            page.wait_for_selector("#control-body table.tbl")
            check("demo" in page.locator("#control-body").inner_text() and "calm" not in page.locator("#control-body").inner_text(),
                  f"{label}: the chooser lists only upgraded skills")
            check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"{label}: chooser has no horizontal scroll")
            page.click("#control-body .rowlink")
            page.wait_for_selector("#cstart-body .ctl")
            check("Keep demo working as you improve it" in page.locator("#cstart-body h2").inner_text(), f"{label}: explanation names the skill")
            check(page.locator("#cs-ladder li.done.here .you").inner_text() == "You are here", f"{label}: the ladder marks Level 2")
            check(page.locator("#cs-ladder .cross").count() == 1 and page.locator("#cs-ladder .tick").count() == 2,
                  f"{label}: reached levels have a tick, the open one a cross")
            page.click("#cstart-body a.btn.big")
            page.wait_for_selector("#clist-body .part")
            check(page.locator("#clist-body .summary .num").nth(1).inner_text() == "2", f"{label}: list shows the tests")
            check(page.locator("#clist-body .pill:has-text('Prose instruction')").count() == 1, f"{label}: prose instruction is labelled")
            page.click("#turn-on")
            page.wait_for_selector("#turn-note", state="visible", timeout=4000)
            check(page.locator("#turn-note").is_visible(), f"{label}: turning on points to the chat")
            page.goto(url + "#/control-done/demo")
            page.reload()
            page.wait_for_selector("#cdone-body h2")
            check("not in control yet" in page.locator("#cdone-body h2").inner_text(), f"{label}: not in control until it was turned on")
            status_file.write_text(json.dumps({"stage": {"name": "ready", "open": 0}, "total": 3, "passing": 2, "failing": 0,
                                               "gap": 0, "text": 1, "other": 0, "controlled_at": "2026-11-20T10:00:00Z",
                                               "acs": {"A1": "passing", "A2": "passing", "A3": "text"}}), encoding="utf-8")
            page.reload()
            page.wait_for_selector("#cdone-body .ladder")
            check(page.locator("#cdone-body h2").inner_text() == "demo is in control", f"{label}: result page once controlled")
            check(page.locator("#cdone-body .ladder .tick").count() == 3, f"{label}: all three levels ticked at Level 3")
            check(page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"{label}: result has no horizontal scroll")
            page.goto(url + "#/")
            page.reload()
            page.wait_for_selector("#start-ladder li.done")
            check("Most of your skills are here" in page.locator("#start-ladder .you").inner_text(), f"{label}: start page marks where your skills are")
            status_file.write_text(before, encoding="utf-8")
            installed["v"] = False
            page.goto(url + "#/control")
            page.reload()
            page.wait_for_selector("#v-upgrade.on")
            check(page.locator("#up-buy").is_visible(), f"{label}: Keep control without Skill Upgrade leads to the buy page")
            page.goto(url + "#/skill/demo")
            page.wait_for_selector("#claim")
            page.click("#claim")
            page.wait_for_selector("#claim[data-mine='1']")
            page.goto(url + "#/skills")
            page.wait_for_selector("#skill-rows tr")
            row = page.locator("#skill-rows tr", has_text="demo").first.inner_text()
            check("Upgrade" not in row and "Not yours" in row, f"{label}: a skill marked not mine shows 'Not yours' in the list: {row!r}")
            page.goto(url + "#/skill/demo")
            page.wait_for_selector("#claim[data-mine='1']")
            page.click("#claim")
            page.wait_for_selector("#claim[data-mine='0']")
            check(not errors, f"{label}: no script errors {errors}")
            page.close()
        b.close()
    server.shutdown()
    tmp.cleanup()
    print(f"\n{len(FAILED)} failed" if FAILED else "\nall steps hold")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
