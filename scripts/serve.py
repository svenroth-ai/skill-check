#!/usr/bin/env python3
"""Serve the Skill Check view on localhost (nothing leaves this machine; it writes only the origin marks of skills).

    python scripts/serve.py [--port 3920] [--out out]

Routes: /            the app (web/app.html)
        /concept     the concept mockup (web/index.html)
        /api/scan    the scan result (out/check.json)
        /api/view?skill=NAME  what the view shows, in plain words (scripts/view_model.py)
        /api/skills   the numbers per skill (instructions, held by code, can add, text), the suggestion and the usage
        /api/skill?name=NAME  one skill with its parts
        /api/upgrade?name=NAME  the open questions and the report of an upgraded skill (scripts/upgrade_view.py)
        /api/skilltext?name=NAME  the text of SKILL.md (scripts/skill_text.py)
        /api/about?name=NAME    what the skill does: purpose, capabilities, scenarios, non-goals (scripts/skill_intent.py)
        /api/classified  every classified inventory (out/classify/*.inventory.json), keyed by skill
Binds to 127.0.0.1 only. Exit codes: 0 stopped; 2 port in use.
"""
from __future__ import annotations

import argparse
import urllib.parse
import json
import os
import re
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_origin  # noqa: E402
import skill_score  # noqa: E402
import skill_intent  # noqa: E402
import skill_text  # noqa: E402
import skill_usage  # noqa: E402
import upgrade_view  # noqa: E402
import view_model  # noqa: E402
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}  # a page on another site must not read the scan through DNS rebinding


class ExclusiveServer(ThreadingHTTPServer):
    """On Windows the default lets a second server bind a port that is already in use. Refuse it."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


DEFAULT_ROOTS = [Path.home() / ".claude" / "skills", Path.cwd() / ".claude" / "skills"]
USAGE_DAYS = 90
_cache: dict = {}


def scored(roots: list[Path]) -> dict[str, dict]:
    """Every skill under the roots, scored. A skill is only scored again when one of its files changed."""
    out: dict[str, dict] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for d in skill_score.skill_dirs(root):
            try:
                stamp = max(p.stat().st_mtime_ns for p in d.rglob("*") if p.is_file())
            except (OSError, ValueError):
                continue
            hit = _cache.get(d)
            if not hit or hit[0] != stamp:
                try:
                    hit = (stamp, skill_score.score(d))
                except (OSError, ValueError, UnicodeDecodeError):
                    continue
                _cache[d] = hit
            out.setdefault(d.name, hit[1])  # the first root wins: your own folder before the project's
    return out


def skill_path(roots: list[Path], name: str) -> Path | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name or ""):
        return None
    return next((r / name for r in roots if (r / name / "SKILL.md").is_file()), None)


def status_of(out: Path, name: str) -> dict | None:
    try:
        d = json.loads((out / "baseline" / name / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def decorated(out: Path, roots: list[Path], name: str, row: dict) -> dict:
    """The score row plus where the skill comes from and the level it has reached."""
    d = skill_path(roots, name)
    origin = skill_origin.origin(d) if d else {"kind": "own"}
    return row | {"origin": origin, "level": skill_origin.level(row, status_of(out, name)),
                  "upgraded": status_of(out, name) is not None}


def buy_url() -> str:
    """The checkout link, set by the author in config/buy.json or SKILL_CHECK_BUY_URL. Empty until the checkout is open,
    and only an https link is ever shown."""
    url = os.environ.get("SKILL_CHECK_BUY_URL", "")
    if not url:
        try:
            url = json.loads((ROOT / "config" / "buy.json").read_text(encoding="utf-8")).get("url", "")
        except (OSError, ValueError, AttributeError):
            url = ""
    return url if isinstance(url, str) and url.startswith("https://") else ""


INTENT_TEXT = {  # what a click in the view says to the chat: fixed words, only the skill name is filled in
    "upgrade": 'Upgrade the skill "{skill}" with Skill Upgrade.',  # no leading slash: a plugin may not submit a command
    "control": 'Keep control of the skill "{skill}" with Skill Upgrade.',
}
LISTEN_SECONDS = 8  # the chat side counts as listening when it asked for work this recently


def make_handler(out: Path, roots: list[Path] | None = None, projects: Path | None = None):
    roots = DEFAULT_ROOTS if roots is None else roots
    projects = projects or Path.home() / ".claude" / "projects"
    queue: list[str] = []  # what the user asked for in the view, waiting for the chat to pick it up
    seen = {"at": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ALLOWED_HOSTS:
                return self._send(403, b"forbidden host", "text/plain; charset=utf-8")
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                return self._file(ROOT / "web" / "app.html")
            if path.startswith("/assets/"):
                name = path[len("/assets/"):]
                if not re.fullmatch(r"[\w.-]+", name) or name.startswith("."):
                    return self._send(404, b"not found", "text/plain; charset=utf-8")
                ctype = {"jpg": "image/jpeg", "png": "image/png", "svg": "image/svg+xml"}.get(name.rsplit(".", 1)[-1])
                if ctype is None:
                    return self._send(404, b"not found", "text/plain; charset=utf-8")
                return self._file(ROOT / "web" / "assets" / name, ctype)
            if path == "/concept":
                return self._file(ROOT / "web" / "index.html")
            if path == "/api/intent/status":
                return self._json({"listening": time.monotonic() - seen["at"] < LISTEN_SECONDS})
            if path == "/api/scan":
                return self._file(out / "check.json", "application/json; charset=utf-8")
            if path == "/api/view":
                return self._view(out, urllib.parse.parse_qs(query).get("skill", [None])[0])
            if path == "/api/skills":
                return self._skills()
            if path == "/api/skill":
                name = urllib.parse.parse_qs(query).get("name", [None])[0]
                row = scored(roots).get(name or "")
                if row is None:
                    return self._send(404, b"no such skill", "text/plain; charset=utf-8")
                return self._json(decorated(out, roots, name, row))
            if path == "/api/skilltext":
                d = skill_path(roots, urllib.parse.parse_qs(query).get("name", [""])[0])
                if d is None:
                    return self._send(404, b"no such skill", "text/plain; charset=utf-8")
                return self._json(skill_text.text(d))
            if path == "/api/about":
                d = skill_path(roots, urllib.parse.parse_qs(query).get("name", [""])[0])
                if d is None:
                    return self._send(404, b"no such skill", "text/plain; charset=utf-8")
                return self._json(skill_intent.intent(d))
            if path == "/api/upgrade":
                name = urllib.parse.parse_qs(query).get("name", [""])[0]
                d = skill_path(roots, name)
                if d is None:
                    return self._send(404, b"no such skill", "text/plain; charset=utf-8")
                try:
                    status = json.loads((out / "baseline" / name / "status.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    status = None
                return self._json(upgrade_view.read(d, status if isinstance(status, dict) else None))
            if path == "/api/classified":
                data = {}
                for f in sorted((out / "classify").glob("*.inventory.json")):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                        data[d["skill"]] = d
                    except (OSError, ValueError, KeyError):
                        continue
                return self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                  "application/json; charset=utf-8")
            self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            origin = urllib.parse.urlparse(self.headers.get("Origin") or "")
            same = origin.hostname in ALLOWED_HOSTS and origin.netloc == self.headers.get("Host")
            if host not in ALLOWED_HOSTS or not same:  # a page on another site must not write anything
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
            path, _, query = self.path.partition("?")
            if path == "/api/intent/take":  # the chat side asks for the next click
                seen["at"] = time.monotonic()
                return self._json({"text": queue.pop(0)} if queue else {})
            if path not in ("/api/origin", "/api/intent") or not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._send(404, b"not found", "text/plain; charset=utf-8")
            d = skill_path(roots, urllib.parse.parse_qs(query).get("name", [""])[0])
            try:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size)) if 0 < size <= 20000 else None
            except (ValueError, OSError):
                body = None
            if d is None or not isinstance(body, dict):
                return self._send(400, b"bad request", "text/plain; charset=utf-8")
            if path == "/api/intent":  # a click in the view that should go on in the chat
                action = body.get("action")
                if action not in INTENT_TEXT or skill_origin.origin(d)["kind"] != "own":
                    return self._send(400, b"bad request", "text/plain; charset=utf-8")
                if len(queue) < 5:
                    queue.append(INTENT_TEXT[action].format(skill=d.name))
                return self._json({"queued": True, "listening": time.monotonic() - seen["at"] < LISTEN_SECONDS})
            if path == "/api/origin":  # the user's own word on whether a skill is theirs
                if not isinstance(body.get("mine"), bool):
                    return self._send(400, b"bad request", "text/plain; charset=utf-8")
                if skill_origin.origin(d)["kind"] == "plugin":
                    return self._send(403, b"a plugin skill cannot be claimed", "text/plain; charset=utf-8")
                skill_origin.set_mark(d.name, body["mine"])
                return self._json({"origin": skill_origin.origin(d)})
            return self._send(404, b"not found", "text/plain; charset=utf-8")

        def _json(self, obj) -> None:
            self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _skills(self) -> None:
            rows = scored(roots)
            try:
                usage = skill_usage.usage(projects, USAGE_DAYS)["usage"] if projects.is_dir() else {}
            except OSError:
                usage = {}
            lst = [{k: v for k, v in decorated(out, roots, n, r).items() if k != "parts"} | {"uses": usage.get(n, 0)}
                   for n, r in rows.items()]
            lst.sort(key=lambda r: (-r["uses"], r["pct"]["enforced"], r["skill"]))
            own = [r for r in lst if r["origin"]["kind"] == "own"]
            levels = {k: sum(1 for r in own if r["level"] == k) for k in (1, 2, 3)}
            self._json({"days": USAGE_DAYS, "skills": lst, "levels": levels,
                        "suggest": skill_score.suggest([r for r in lst if r["origin"]["kind"] == "own"], usage),
                        "upgrade_installed": view_model.installed_harden(), "buy_url": buy_url()})

        def _view(self, out: Path, skill: str | None) -> None:
            try:
                scan = json.loads((out / "check.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return self._send(404, b"no scan yet. Run scripts/check_skills.py first.", "text/plain; charset=utf-8")
            try:
                names = {s["skill"] for s in scan["skills"]}
            except (KeyError, TypeError):
                return self._send(500, b"the scan is not in the expected shape. Run scripts/check_skills.py again.",
                                  "text/plain; charset=utf-8")
            if skill is not None and skill not in names:
                return self._send(404, b"no such skill in the scan", "text/plain; charset=utf-8")
            proof = None
            if skill:  # only a scanned skill name ever reaches a path
                try:
                    proof = json.loads((out / "baseline" / skill / "status.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    proof = None
            try:
                model = view_model.build(scan, skill, proof, view_model.installed_harden())
            except (KeyError, ValueError, TypeError):
                return self._send(500, b"the scan is not in the expected shape. Run scripts/check_skills.py again.",
                                  "text/plain; charset=utf-8")
            self._send(200, json.dumps(model, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _file(self, p: Path, ctype: str = "text/html; charset=utf-8") -> None:
            try:
                self._send(200, p.read_bytes(), ctype)
            except OSError:
                self._send(404, f"missing: {p.name}. Run scripts/check_skills.py first.".encode(),
                           "text/plain; charset=utf-8")

        def log_message(self, *_args) -> None:
            return

    return Handler


BIND_HOST = "127.0.0.1"  # never all interfaces: the scan lists the user's skills


def make_server(port: int, out: Path, roots: list[Path] | None = None, projects: Path | None = None) -> ExclusiveServer:
    return ExclusiveServer((BIND_HOST, port), make_handler(out, roots, projects))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=3920)
    ap.add_argument("--out", default=str(Path.home() / ".shipwright" / "skill-check"))
    ap.add_argument("--skills", action="append", type=Path, help="a skills folder to read (repeatable; default: yours and this project's)")
    a = ap.parse_args()
    try:
        server = make_server(a.port, Path(a.out), a.skills)
    except OSError as e:
        print(f"cannot listen on 127.0.0.1:{a.port}: {e}. Another program uses the port: pass --port with a free one.", file=sys.stderr)
        return 2
    print(f"Skill Check on http://localhost:{a.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
