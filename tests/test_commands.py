"""Core command tests: remember / recall / decisions plus loop posts."""

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.vault import count_memories, upsert_memory
from roombrain.agent.commands import (
    dispatch_command,
    handle_decisions,
    handle_recall,
    handle_remember,
)


class TestRemember(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name

    def tearDown(self):
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_remember_confirms_and_count_plus_one(self):
        before = count_memories(db_path=self.db)
        reply = handle_remember(
            "ship Thursday", room="r1", actor="a",
            thread_id="t1", db_path=self.db,
        )
        self.assertIn("remembered", reply)
        self.assertEqual(count_memories(db_path=self.db), before + 1)

    def test_remember_blank_returns_usage(self):
        self.assertIn("usage", handle_remember("   ", db_path=self.db))
        self.assertIn("usage", handle_remember("", db_path=self.db))


class TestRecall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name
        upsert_memory(
            "pricing agreed at 9", "room1", "alice", "t99",
            "decision", 1.0, db_path=self.db,
        )

    def tearDown(self):
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_recall_bullet_carries_thread_and_term(self):
        reply = handle_recall("pricing", db_path=self.db)
        lines = [ln for ln in reply.splitlines()
                 if ln.startswith("-")]
        self.assertGreaterEqual(len(lines), 1)
        self.assertTrue(any("t99" in ln for ln in lines))
        self.assertTrue(any("pricing" in ln for ln in lines))

    def test_recall_blank_returns_usage(self):
        self.assertIn("usage", handle_recall("  ", db_path=self.db))

    def test_recall_no_hits(self):
        reply = handle_recall("zzz-no-such-term", db_path=self.db)
        self.assertIn("no memories match", reply)


class TestDecisions(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name
        upsert_memory(
            "pricing locked for launch", "room1", "alice", "t7",
            "decision", 1.0, db_path=self.db,
        )
        upsert_memory(
            "pricing rumor overheard", "room1", "bob", "t8",
            "fact", 0.5, db_path=self.db,
        )

    def tearDown(self):
        try:
            os.unlink(self.db)
        except OSError:
            pass

    def test_decisions_bullet_and_kind_filter(self):
        reply = handle_decisions("pricing", db_path=self.db)
        bullets = [ln for ln in reply.splitlines()
                   if ln.startswith("-")]
        self.assertGreaterEqual(len(bullets), 1)
        self.assertIn("pricing locked", reply)
        self.assertNotIn("rumor", reply)

    def test_decisions_empty(self):
        reply = handle_decisions("zzz-no-such-term", db_path=self.db)
        self.assertIn("no decisions", reply)


class TestDispatch(unittest.TestCase):
    def test_unknown_name_returns_none(self):
        self.assertIsNone(dispatch_command("nope", [], {}))
        self.assertIsNone(dispatch_command("Recall", ["x"], {}))
        self.assertIsNone(dispatch_command("ping", [], {}))

    def test_dispatch_remember_recall_decisions(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            ctx = {"room": "r1", "actor": "a",
                   "thread_id": "t1", "db_path": tmp.name}
            reply = dispatch_command(
                "remember", ["ship", "Thursday"], ctx)
            self.assertIn("remembered", reply)
            upsert_memory(
                "pricing deal", "room1", "alice", "t99",
                "decision", 1.0, db_path=tmp.name,
            )
            reply = dispatch_command("recall", ["pricing"], ctx)
            self.assertIn("t99", reply)
            reply = dispatch_command("decisions", ["pricing"], ctx)
            self.assertIn("-", reply)
            self.assertIsNone(dispatch_command("bogus", ["x"], ctx))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


class _FakeServer:
    """One-connection-script fake Switch."""

    def __init__(self, script):
        self.script = script

    async def __aenter__(self):
        from websockets.asyncio.server import serve

        server = self

        async def handler(ws):
            await server.script(server, ws)

        def process_request(conn, request):
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
            {"url": url, "json": json or {},
             "headers": dict(headers or {})}
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


class TestCommandLoop(unittest.IsolatedAsyncioTestCase):
    async def test_addressed_commands_post_once_each(self):
        from roombrain.agent.protocol import run_forever

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db = tmp.name
        upsert_memory(
            "pricing agreed at 9", "room1", "alice", "t99",
            "decision", 1.0, db_path=db,
        )
        old = os.environ.get("ROOMBRAIN_DB")
        os.environ["ROOMBRAIN_DB"] = db
        try:
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
                    "payload": {"addressed": False,
                                "body": "!remember ignored",
                                "room_id": "r1"},
                    "sequence": 1,
                }))
                await ws.send(json.dumps({
                    "type": "message",
                    "payload": {"addressed": True,
                                "body": "!remember ship Thursday",
                                "room_id": "r1"},
                    "sequence": 2,
                }))
                await ws.send(json.dumps({
                    "type": "message",
                    "payload": {"addressed": True,
                                "body": "!recall pricing",
                                "room_id": "r1"},
                    "sequence": 3,
                }))
                await ws.wait_closed()

            _RecordingClient.instances.clear()
            async with _FakeServer(script) as fake:
                with mock.patch("httpx.Client", _RecordingClient):
                    task = asyncio.create_task(run_forever(
                        fake.url, "x", "sek", "r1",
                        connection_id="conn-x",
                    ))
                    try:
                        deadline = time.monotonic() + 5
                        posts = []
                        while time.monotonic() < deadline:
                            posts = [
                                p for inst in _RecordingClient.instances
                                for p in inst.posts
                            ]
                            if len(posts) >= 2:
                                break
                            await asyncio.sleep(0.02)
                        self.assertEqual(len(posts), 2,
                                         "expected one POST per command")
                        bodies = [json.dumps(p["json"]) for p in posts]
                        self.assertTrue(
                            any("remembered" in b for b in bodies))
                        hit = [b for b in bodies if "t99" in b]
                        self.assertEqual(len(hit), 1)
                        self.assertIn("pricing", hit[0])
                        for post in posts:
                            self.assertTrue(
                                post["url"].endswith(
                                    "/agents/x/ops/post_message"))
                            lowered = {
                                k.lower(): v
                                for k, v in post["headers"].items()
                            }
                            self.assertEqual(
                                lowered.get("x-switch-connection-id"),
                                "conn-x",
                            )
                        await asyncio.sleep(0.5)
                        posts = [
                            p for inst in _RecordingClient.instances
                            for p in inst.posts
                        ]
                        self.assertEqual(len(posts), 2,
                                         "exactly one POST per command")
                    finally:
                        await _stop(task)
        finally:
            if old is None:
                os.environ.pop("ROOMBRAIN_DB", None)
            else:
                os.environ["ROOMBRAIN_DB"] = old
            try:
                os.unlink(db)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
