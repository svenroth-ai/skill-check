"""Tests for scripts/serve.py. Run: python -m unittest discover -s tests"""
import contextlib
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import serve  # noqa: E402


class Serve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        out = Path(self.tmp.name)
        (out / "classify").mkdir()
        (out / "check.json").write_text(json.dumps({"skills": []}), encoding="utf-8")
        (out / "classify" / "x.inventory.json").write_text(json.dumps({"skill": "x", "sections": []}), encoding="utf-8")
        self.server = serve.ExclusiveServer(("127.0.0.1", 0), serve.make_handler(out))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("GET", path, skip_host=True)
        c.putheader("Host", host or f"localhost:{self.port}")
        c.endheaders()
        r = c.getresponse()
        return r.status, r.read()

    def test_routes(self):
        self.assertEqual(self.get("/api/scan")[0], 200)
        status, body = self.get("/api/classified")
        self.assertEqual((status, list(json.loads(body))), (200, ["x"]))
        self.assertEqual(self.get("/nope")[0], 404)

    def scan_with(self, *names):
        sk = lambda n: {"skill": n, "findings": [], "tokens_estimate": 100, "reference_tokens_estimate": 0,  # noqa: E731
                        "scripts": 0, "rule_like_lines": 0}
        (Path(self.tmp.name) / "check.json").write_text(json.dumps({"skills": [sk(n) for n in names]}), encoding="utf-8")

    def test_view_route_speaks_plain_words_and_knows_only_scanned_skills(self):
        self.scan_with("demo")
        status, body = self.get("/api/view")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["next"]["label"], "Choose a skill")
        status, body = self.get("/api/view?skill=demo")
        self.assertEqual(json.loads(body)["selected"]["name"], "demo")
        self.assertEqual(self.get("/api/view?skill=nope")[0], 404)
        self.assertEqual(self.get("/api/view?skill=..%2F..%2Fx")[0], 404)

    def test_view_route_reads_the_proof_of_the_chosen_skill_only(self):
        self.scan_with("demo", "other")
        out = Path(self.tmp.name)
        for name, proof in (("demo", {"total": 4, "passing": 2, "failing": 0, "gap": 2, "other": 0}),
                            ("other", {"total": 1, "passing": 1, "failing": 0, "gap": 0, "other": 0})):
            (out / "baseline" / name).mkdir(parents=True)
            (out / "baseline" / name / "status.json").write_text(json.dumps(proof), encoding="utf-8")
        real = serve.view_model.installed_harden
        serve.view_model.installed_harden = lambda *a, **k: True
        try:
            label = lambda s: json.loads(self.get(f"/api/view?skill={s}")[1])["next"]["label"]  # noqa: E731
            self.assertEqual(label("demo"), "Prove the 2 open requirements")
            self.assertEqual(label("other"), "Keep it safe")
        finally:
            serve.view_model.installed_harden = real

    def test_view_route_survives_bad_files_with_a_sentence(self):
        out = Path(self.tmp.name)
        self.scan_with("demo")
        (out / "baseline" / "demo").mkdir(parents=True)
        (out / "baseline" / "demo" / "status.json").write_text('{"total": 3}', encoding="utf-8")
        status, body = self.get("/api/view?skill=demo")
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["selected"]["proof"])
        for bad in ('{"nope": 1}', "[]", '{"skills": "x"}'):
            (out / "check.json").write_text(bad, encoding="utf-8")
            status, body = self.get("/api/view")
            self.assertEqual(status, 500)
            self.assertIn(b"check_skills.py", body)

    def test_view_route_without_a_scan_says_what_to_run(self):
        (Path(self.tmp.name) / "check.json").unlink()
        status, body = self.get("/api/view")
        self.assertEqual(status, 404)
        self.assertIn(b"check_skills.py", body)

    def test_path_traversal_is_not_a_route(self):
        self.assertEqual(self.get("/../scripts/serve.py")[0], 404)
        self.assertEqual(self.get("/api/scan/../../README.md")[0], 404)

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self.get("/api/scan", host="evil.example")[0], 403)
        self.assertEqual(self.get("/api/scan", host=f"127.0.0.1:{self.port}")[0], 200)

    def test_second_server_on_the_same_port_fails(self):
        with self.assertRaises(OSError):
            serve.ExclusiveServer(("127.0.0.1", self.port), serve.make_handler(Path(self.tmp.name)))


class Binding(unittest.TestCase):
    def test_main_starts_the_server_through_make_server(self):
        calls = []

        def fake(port, out, *_a):
            calls.append(port)
            raise OSError("stop here")

        def never(*_a, **_k):  # a main that skips make_server must fail here, not start a real server
            raise OSError("main built its own server")

        real, argv, raw = serve.make_server, sys.argv, serve.ExclusiveServer
        serve.make_server, serve.ExclusiveServer, sys.argv = fake, never, ["serve.py", "--port", "4999"]
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(serve.main(), 2)
        finally:
            serve.make_server, serve.ExclusiveServer, sys.argv = real, raw, argv
        self.assertEqual(calls, [4999])

    def test_bind_host_is_loopback(self):
        self.assertEqual(serve.BIND_HOST, "127.0.0.1")

    def test_server_binds_to_loopback_only(self):
        with tempfile.TemporaryDirectory() as t:
            server = serve.make_server(0, Path(t))
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()
