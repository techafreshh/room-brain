"""Brief tests: compose, CLI push path, and live on-demand !brief."""

import asyncio
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("ROOMBRAIN_NO_EMBED", "1")

from brief.compose import compose_brief
from memory.vault import count_memories, upsert_memory
from roombrain.cli import main


def _yesterday_noon_iso():
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (midnight - timedelta(hours=12)).isoformat()


class _TempDb(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name
        try:
            os.unlink(self.db)
        except OSError:
            pass
        self._env = mock.patch.dict(
            os.environ,
            {"ROOMBRAIN_DB": self.db, "ROOMBRAIN_NO_EMBED": "1"},
        )
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


class TestComposeBrief(_TempDb):
    def test_seeded_yesterday_decision_appears(self):
        upsert_memory(
            "yesterday pricing locked", "#launch", "alice", "t1",
            "decision", 1.0, db_path=self.db,
            timestamp=_yesterday_noon_iso(),
        )
        out = compose_brief("r1", db_path=self.db)
        self.assertIn("Brief", out)
        self.assertIn("Decisions", out)
        self.assertIn("yesterday pricing locked", out)

    def test_empty_yesterday_reports_no_decisions(self):
        out = compose_brief("r1", db_path=self.db)
        self.assertIn("Brief", out)
        self.assertIn("Decisions", out)
        self.assertIn("No decisions", out)


class _RecordingClient:
    """Stand-in for httpx.Client capturing standalone message POSTs."""

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


class TestBriefCli(_TempDb):
    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_brief_posts_once_to_standalone_message_path(self):
        upsert_memory(
            "yesterday pricing locked", "#launch", "alice", "t1",
            "decision", 1.0, db_path=self.db,
            timestamp=_yesterday_noon_iso(),
        )
        env_file = os.path.join(tempfile.gettempdir(), "no-such-roombrain.env")
        creds = {
            "ROOMBRAIN_AGENT_ID": "x",
            "ROOMBRAIN_API_KEY": "sek",
        }
        _RecordingClient.instances.clear()
        with mock.patch.dict(os.environ, creds):
            with mock.patch("httpx.Client", _RecordingClient):
                code, out, _ = self._run([
                    "brief", "--room", "r1",
                    "--server", "http://switch.test",
                    "--env-file", env_file,
                ])
        self.assertEqual(code, 0)
        posts = [
            p for inst in _RecordingClient.instances for p in inst.posts
        ]
        self.assertEqual(len(posts), 1, "expected exactly one POST")
        post = posts[0]
        self.assertTrue(post["url"].endswith("/agents/x/message"))
        self.assertEqual(post["json"].get("room_id"), "r1")
        self.assertIn("Brief", post["json"].get("content", ""))
        lowered = {k.lower(): v for k, v in post["headers"].items()}
        self.assertEqual(lowered.get("authorization"), "Bearer sek")
        self.assertNotIn("x-switch-connection-id", lowered)

    def test_brief_without_credentials_exits_2(self):
        env_file = os.path.join(tempfile.gettempdir(), "no-such-roombrain.env")
        with mock.patch.dict(
            os.environ,
            {"ROOMBRAIN_AGENT_ID": "", "ROOMBRAIN_API_KEY": ""},
        ):
            with mock.patch(
                "roombrain.agent.ops.post_standalone_message",
                side_effect=AssertionError("must not POST"),
            ):
                code, _, err = self._run(
                    ["brief", "--room", "r1", "--env-file", env_file]
                )
        self.assertEqual(code, 2)
        self.assertIn("register", err)
        self.assertEqual(count_memories(), 0)


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


class TestBriefLoop(unittest.IsolatedAsyncioTestCase):
    async def test_live_brief_posts_once_with_decisions(self):
        from roombrain.agent.protocol import run_forever

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db = tmp.name
        upsert_memory(
            "yesterday pricing locked", "#launch", "alice", "t1",
            "decision", 1.0, db_path=db,
            timestamp=_yesterday_noon_iso(),
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
                    "payload": {"addressed": True, "body": "!brief",
                                "room_id": "r1"},
                    "sequence": 1,
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
                            if posts:
                                break
                            await asyncio.sleep(0.02)
                        self.assertEqual(len(posts), 1,
                                         "expected exactly one POST")
                        post = posts[0]
                        self.assertTrue(
                            post["url"].endswith("/agents/x/message"))
                        self.assertIn(
                            "Decisions", json.dumps(post["json"]))
                        await asyncio.sleep(0.5)
                        posts = [
                            p for inst in _RecordingClient.instances
                            for p in inst.posts
                        ]
                        self.assertEqual(len(posts), 1,
                                         "exactly one POST")
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

    async def test_unaddressed_traffic_posts_zero(self):
        from roombrain.agent.protocol import run_forever

        async def script(fake, ws):
            await ws.send(json.dumps({
                "type": "connection_state",
                "connection_id": "conn-x",
                "agent_id": "x",
                "generation": 1,
                "cursor": 0,
            }))
            await ws.send(json.dumps({
                "type": "message", "addressed": False,
                "body": "!brief", "sequence": 1,
            }))
            await ws.send(json.dumps({
                "type": "message", "addressed": True,
                "body": "hello", "sequence": 2,
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
                    await asyncio.sleep(1.0)
                    total = sum(
                        len(inst.posts)
                        for inst in _RecordingClient.instances
                    )
                    self.assertEqual(total, 0)
                finally:
                    await _stop(task)


if __name__ == "__main__":
    unittest.main()
