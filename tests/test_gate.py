"""Gate tests: stage/approve-dry-run/reject/expired/unauthorized + loop."""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone


def _fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return tmp.name


class TestGateUnits(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        self.sent = tempfile.mkdtemp()
        self._env = mock.patch.dict(os.environ, {
            "ROOMBRAIN_DB": self.db,
            "ROOMBRAIN_SENT_DIR": self.sent,
            "GMAIL_OAUTH_TOKEN": "",
            "LINEAR_API_KEY": "",
        })
        self._env.start()

    def tearDown(self):
        self._env.stop()
        try:
            os.unlink(self.db)
        except OSError:
            pass
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                os.unlink(self.db + suffix)
            except OSError:
                pass

    def _ctx(self, sender, room="r1"):
        return {"room": room, "sender": sender, "requester": sender,
                "db_path": self.db}

    def test_keyless_approve_dry_run_archives(self):
        from actions.gate import dispatch_gate
        from memory.vault import get_draft

        reply = dispatch_gate("draft", ["email", "launch plan"],
                              self._ctx("alice"))
        self.assertIn("d1", reply)
        reply = dispatch_gate("approve", [], self._ctx("alice"))
        self.assertIn("approval recorded; send skipped", reply)
        self.assertTrue(os.path.exists(os.path.join(self.sent, "d1.md")))
        self.assertEqual(get_draft("d1", db_path=self.db)["approver"],
                         "alice")

    def test_agent_sender_approve_not_authorized(self):
        from actions.gate import dispatch_gate

        dispatch_gate("draft", ["email", "topic x"], self._ctx("alice"))
        reply = dispatch_gate("approve", [], self._ctx("agent-helper"))
        self.assertIn("not authorized", reply)
        self.assertEqual(os.listdir(self.sent), [])

    def test_expired_draft_no_file(self):
        from actions.gate import handle_approve
        from memory.vault import stage_draft

        old = (datetime.now(timezone.utc)
               - timedelta(hours=25)).isoformat()
        stage_draft("email", "old news", "body", "r1", "alice", "alice",
                    db_path=self.db, created_at=old)
        reply = handle_approve("", self._ctx("alice"))
        self.assertIn("expired", reply)
        self.assertEqual(os.listdir(self.sent), [])

    def test_reject_discards_without_file(self):
        from actions.gate import dispatch_gate
        from memory.vault import get_draft

        dispatch_gate("draft", ["linear", "fix login"], self._ctx("alice"))
        reply = dispatch_gate("reject", [], self._ctx("alice"))
        self.assertIn("discarded", reply)
        self.assertEqual(os.listdir(self.sent), [])
        self.assertEqual(get_draft("d1", db_path=self.db)["status"],
                         "discarded")


class _FakeServer:
    """One-connection-script fake Switch recording handshake paths/auth."""

    def __init__(self, script):
        self.script = script
        self.paths = []
        self.auth = []
        self._server = None

    async def __aenter__(self):
        from websockets.asyncio.server import serve

        server = self

        async def handler(ws):
            await server.script(server, ws)

        def process_request(conn, request):
            server.paths.append(request.path)
            server.auth.append(request.headers.get("authorization"))
            return None

        self._server = await serve(
            handler, "127.0.0.1", 0, ping_interval=None,
            process_request=process_request,
        )
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    @property
    def port(self):
        return self._server.sockets[0].getsockname()[1]

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port


async def _stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class _RecordingClient:
    """Stand-in for httpx.Client capturing ops POSTs."""

    instances = []

    def __init__(self, *args, **kwargs):
        self.posts = []
        _RecordingClient.instances.append(self)

    def post(self, url, json=None, headers=None):
        self.posts.append(
            {"url": url, "json": json or {}, "headers": dict(headers or {})}
        )

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"result": "ok"}

        return _Resp()

    def get(self, url, headers=None):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"operations": {}}

        return _Resp()

    def close(self):
        pass


class TestGateLoop(unittest.IsolatedAsyncioTestCase):
    async def test_approve_posts_dry_run_once_within_3s(self):
        from roombrain.agent.protocol import run_forever

        db = _fresh_db()
        sent = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {
            "ROOMBRAIN_DB": db,
            "ROOMBRAIN_SENT_DIR": sent,
            "GMAIL_OAUTH_TOKEN": "",
            "LINEAR_API_KEY": "",
        }):
            from actions.gate import dispatch_gate

            dispatch_gate("draft", ["email", "loop topic"],
                          {"room": "r1", "sender": "alice",
                           "requester": "alice", "db_path": db})

            async def script(fake, ws):
                await ws.send(json.dumps({
                    "type": "connection_state",
                    "connection_id": "conn-x",
                    "agent_id": "x",
                    "generation": 1,
                    "cursor": 0,
                }))
                await ws.send(json.dumps({
                    "type": "message",
                    "payload": {"addressed": True, "body": "!approve",
                                "room_id": "r1", "sender": "alice"},
                    "sequence": 1,
                }))
                await ws.wait_closed()

            _RecordingClient.instances.clear()
            started = time.monotonic()
            async with _FakeServer(script) as fake:
                with mock.patch("httpx.Client", _RecordingClient):
                    task = asyncio.create_task(run_forever(
                        fake.url, "x", "sek", "r1",
                        connection_id="conn-x",
                    ))
                    try:
                        deadline = time.monotonic() + 3
                        posts = []
                        while time.monotonic() < deadline:
                            posts = [
                                p for inst in _RecordingClient.instances
                                for p in inst.posts
                            ]
                            if posts:
                                break
                            await asyncio.sleep(0.02)
                        elapsed = time.monotonic() - started
                        self.assertLess(elapsed, 3,
                                        "reply must land within 3s")
                        self.assertEqual(len(posts), 1, "expected one POST")
                        post = posts[0]
                        self.assertTrue(
                            post["url"].endswith(
                                "/agents/x/ops/post_message")
                        )
                        self.assertIn("approval recorded; send skipped",
                                      json.dumps(post["json"]))
                        self.assertTrue(
                            os.path.exists(os.path.join(sent, "d1.md")))
                        await asyncio.sleep(0.3)
                        posts = [
                            p for inst in _RecordingClient.instances
                            for p in inst.posts
                        ]
                        self.assertEqual(len(posts), 1, "exactly one POST")
                    finally:
                        await _stop(task)
        try:
            os.unlink(db)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
