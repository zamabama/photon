#!/usr/bin/env python3
"""Tests for photon_watch.py. They run the real script against a local fake Worker.

    python3 test_photon_watch.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent / "photon_watch.py")
IDENTITY = "test-machine/test#lane"


def msg(mid: str, content: str = "hello", ts: str = "2026-01-01T00:00:00Z") -> dict:
    return {"id": mid, "from": "someone", "content": content, "timestamp": ts, "tags": ["t"]}


class FakeWorker:
    """Answers each GET from a script of steps; the last step repeats forever."""

    def __init__(self, steps: list):
        self.steps = steps
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                step = outer.steps[min(outer.requests, len(outer.steps) - 1)]
                outer.requests += 1
                if step == "http500":
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif step == "garbage":
                    self._body(b"<html>not json</html>")
                elif step == "truncated":
                    # Promise more than we send, then hang up: http.client.IncompleteRead.
                    self.send_response(200)
                    self.send_header("Content-Length", "1000")
                    self.end_headers()
                    self.wfile.write(b'{"mess')
                    self.wfile.flush()
                    self.close_connection = True
                else:
                    self._body(json.dumps({"messages": step}).encode())

            def _body(self, body: bytes):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def start(worker: FakeWorker, *args: str, **extra_env: str) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_SESSION_ID", "PHOTON_WATCH_ONCE")}
    env.update(BRIDGE_WORKER_URL=worker.url, BRIDGE_API_KEY="test-key",
               PHOTON_WATCH_IDENTITY=IDENTITY, PHOTON_WATCH_INTERVAL="1",
               PYTHONIOENCODING="utf-8", **extra_env)
    return subprocess.Popen([sys.executable, SCRIPT, *args], env=env, text=True,
                            encoding="utf-8", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)


def finish(proc: subprocess.Popen, timeout: float) -> tuple[int | None, str]:
    """Wait up to `timeout`; a process still running is killed and returns code None."""
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        return None, out


class Base(unittest.TestCase):
    def worker(self, steps: list) -> FakeWorker:
        w = FakeWorker(steps)
        self.addCleanup(w.close)
        return w


class OnceMode(Base):
    def test_mail_already_unread_at_start_exits_immediately(self):
        w = self.worker([[msg("a", "waiting")]])
        code, out = finish(start(w, "--once"), 5)
        self.assertEqual(code, 0, out)
        self.assertIn(f"📬 PHOTON: new message for {IDENTITY} from someone [t] — waiting", out)
        self.assertEqual(w.requests, 1)

    def test_waits_through_empty_polls_then_exits_on_mail(self):
        w = self.worker([[], [], [msg("a", "arrived")]])
        code, out = finish(start(w, "--once"), 10)
        self.assertEqual(code, 0, out)
        self.assertIn("arrived", out)
        self.assertEqual(w.requests, 3)

    def test_empty_inbox_keeps_running(self):
        w = self.worker([[]])
        code, out = finish(start(w, "--once"), 3)
        self.assertIsNone(code, out)
        self.assertNotIn("📬", out)

    def test_prints_every_unread_message_oldest_first(self):
        w = self.worker([[msg("b", "second", "2026-01-02T00:00:00Z"),
                          msg("a", "first", "2026-01-01T00:00:00Z")]])
        code, out = finish(start(w, "--once"), 5)
        self.assertEqual(code, 0, out)
        self.assertLess(out.index("first"), out.index("second"))

    def test_env_var_turns_it_on(self):
        w = self.worker([[msg("a", "by-env")]])
        code, out = finish(start(w, PHOTON_WATCH_ONCE="1"), 5)
        self.assertEqual(code, 0, out)
        self.assertIn("by-env", out)

    def test_server_error_does_not_exit(self):
        w = self.worker(["http500", [msg("a", "after-500")]])
        code, out = finish(start(w, "--once"), 6)
        self.assertEqual(code, 0, out)
        self.assertIn("after-500", out)

    def test_garbage_body_does_not_exit(self):
        w = self.worker(["garbage", [msg("a", "after-garbage")]])
        code, out = finish(start(w, "--once"), 6)
        self.assertEqual(code, 0, out)
        self.assertIn("after-garbage", out)

    def test_connection_dropped_mid_response_does_not_exit(self):
        w = self.worker(["truncated", [msg("a", "after-drop")]])
        code, out = finish(start(w, "--once"), 6)
        self.assertEqual(code, 0, out)
        self.assertIn("after-drop", out)
        self.assertNotIn("Traceback", out)

    def test_worker_down_keeps_retrying(self):
        w = self.worker([[]])
        url = w.url
        w.close()
        # Nothing is listening on this port now.
        env_worker = type("W", (), {"url": url})()
        code, out = finish(start(env_worker, "--once"), 3)
        self.assertIsNone(code, out)
        self.assertIn("cannot reach Photon", out)


class DefaultMode(Base):
    def test_backlog_is_silent_and_only_new_mail_is_announced(self):
        old = msg("old", "backlog")
        new = msg("new", "fresh", "2026-01-02T00:00:00Z")
        w = self.worker([[old], [old, new]])
        code, out = finish(start(w), 4)
        self.assertIsNone(code, f"default mode must keep running: {out}")
        self.assertNotIn("backlog", out)
        self.assertEqual(out.count("fresh"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
