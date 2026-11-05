"""WebSocket tests: URL fencing, tolerant frames, pong/reconnect/takeover loop."""

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from roombrain.agent.events import (
    advance_cursor,
    frame_get,
    is_taken_over,
    message_body,
    parse_connection_state,
    parse_frame,
)
from roombrain.agent.protocol import (
    build_ws_url,
    load_or_create_connection_id,
)
from roombrain.cli import build_parser, cmd_run


def _parse_query(path):
    return parse_qs(urlparse(path).query)


class TestBuildWsUrl(unittest.TestCase):
    def test_first_open_carries_id_and_rooms_only(self):
        url = build_ws_url(
            "http://127.0.0.1:8000", "a1", "conn-1", "room1"
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "ws")
        self.assertEqual(parsed.path, "/agents/a1/connection/ws")
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("connection_id"), ["conn-1"])
        self.assertEqual(query.get("rooms"), ["room1"])
        self.assertNotIn("start_from", query)
        self.assertNotIn("expected_generation", query)

    def test_reconnect_adds_fencing_params(self):
        url = build_ws_url(
            "http://127.0.0.1:8000/",
            "a1",
            "conn-1",
            "room1",
            start_from=25,
            expected_generation=7,
        )
        query = _parse_query(url)
        self.assertEqual(query.get("connection_id"), ["conn-1"])
        self.assertEqual(query.get("start_from"), ["25"])
        self.assertEqual(query.get("expected_generation"), ["7"])

    def test_https_maps_to_wss(self):
        url = build_ws_url("https://switch.test/", "a1", "c", "r")
        self.assertTrue(url.startswith("wss://switch.test/agents/a1/"))

    def test_rooms_list_joins_with_comma(self):
        query = _parse_query(
            build_ws_url("http://h", "a1", "c", ["r1", "r2"])
        )
        self.assertEqual(query.get("rooms"), ["r1,r2"])


class TestFrames(unittest.TestCase):
    def test_frame_get_top_level_first(self):
        frame = {"cursor": 10, "payload": {"cursor": 99}}
        self.assertEqual(frame_get(frame, "cursor"), 10)

    def test_frame_get_payload_nested(self):
        frame = {"type": "x", "payload": {"sequence": 25}}
        self.assertEqual(frame_get(frame, "sequence"), 25)

    def test_frame_get_data_and_state_nested(self):
        self.assertEqual(frame_get({"data": {"seq": 3}}, "seq"), 3)
        self.assertEqual(frame_get({"state": {"cursor": 4}}, "cursor"), 4)

    def test_frame_get_missing_or_not_dict(self):
        self.assertIsNone(frame_get({"type": "ping"}, "sequence"))
        self.assertIsNone(frame_get("nope", "sequence"))
        self.assertIsNone(frame_get(None, "sequence"))

    def test_parse_frame_garbage_yields_empty(self):
        self.assertEqual(parse_frame("{bad json"), {})
        self.assertEqual(parse_frame("[1, 2]"), {})
        self.assertEqual(parse_frame(None), {})

    def test_advance_cursor_only_forward(self):
        self.assertEqual(advance_cursor(10, {"sequence": 25}), 25)
        self.assertEqual(advance_cursor(25, {"sequence": 12}), 25)
        self.assertEqual(advance_cursor(25, {"seq": 25}), 25)
        self.assertEqual(advance_cursor(10, {"cursor": 9}), 10)
        self.assertEqual(advance_cursor(10, {"type": "ping"}), 10)

    def test_advance_cursor_ignores_bools(self):
        self.assertEqual(advance_cursor(0, {"sequence": True}), 0)
        self.assertEqual(advance_cursor(5, {"addressed": True}), 5)

    def test_taken_over_and_state_parsing(self):
        self.assertTrue(is_taken_over({"type": "evicted", "code": "taken_over"}))
        self.assertTrue(
            is_taken_over({"payload": {"code": "taken_over"}, "type": "evicted"})
        )
        self.assertFalse(is_taken_over({"type": "evicted", "code": "moved"}))
        self.assertFalse(is_taken_over({"type": "ping"}))
        state = parse_connection_state(
            {"type": "connection_state", "generation": 7, "cursor": 10}
        )
        self.assertEqual((state.generation, state.cursor), (7, 10))
        self.assertIsNone(
            parse_connection_state({"type": "connection_state", "cursor": 10})
        )
        self.assertIsNone(parse_connection_state({"type": "ping"}))

    def test_message_body_only_when_addressed(self):
        frame = {"type": "message", "addressed": True, "body": "hello"}
        self.assertEqual(message_body(frame), "hello")
        self.assertIsNone(
            message_body({"type": "message", "body": "hello"})
        )
        self.assertIsNone(message_body({"type": "ping"}))


class TestConnectionId(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_file = os.path.join(self.tmp.name, ".env")

    def tearDown(self):
        self.tmp.cleanup()

    def test_generates_persists_and_reuses(self):
        first = load_or_create_connection_id(self.env_file)
        self.assertTrue(first)
        again = load_or_create_connection_id(self.env_file)
        self.assertEqual(first, again)
        with open(self.env_file, encoding="utf-8") as handle:
            self.assertIn("ROOMBRAIN_CONNECTION_ID=%s" % first, handle.read())

    def test_falls_back_to_environment(self):
        with mock.patch.dict(
            os.environ, {"ROOMBRAIN_CONNECTION_ID": "env-conn"}, clear=False
        ):
            self.assertEqual(
                load_or_create_connection_id(self.env_file), "env-conn"
            )
        self.assertFalse(os.path.exists(self.env_file))


class TestCmdRun(unittest.TestCase):
    def test_run_help_lists_new_flags(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout):
            with self.assertRaises(SystemExit) as raised:
                build_parser().parse_args(["run", "--help"])
        self.assertEqual(raised.exception.code, 0)
        text = stdout.getvalue()
        for flag in ("--server", "--rooms", "--env-file", "--echo"):
            self.assertIn(flag, text)

    def test_run_parser_defaults(self):
        args = build_parser().parse_args(["run"])
        self.assertTrue(hasattr(args, "server"))
        self.assertTrue(hasattr(args, "rooms"))
        self.assertTrue(hasattr(args, "env_file"))

    def test_run_missing_credentials_returns_2(self):
        tmp = tempfile.TemporaryDirectory()
        env_file = os.path.join(tmp.name, ".env")
        args = build_parser().parse_args(
            ["run", "--server", "http://127.0.0.1:9", "--env-file", env_file]
        )
        clean = {
            k: v for k, v in os.environ.items()
            if not k.startswith("ROOMBRAIN_")
        }
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, clean, clear=True), mock.patch.object(
            sys, "stderr", stderr
        ):
            code = cmd_run(args)
        tmp.cleanup()
        self.assertEqual(code, 2)
        self.assertIn("ROOMBRAIN_AGENT_ID", stderr.getvalue())


class _FakeServer:
    """One-connection-script fake Switch recording every handshake path."""

    def __init__(self, script):
        self.script = script
        self.paths = []
        self.auth = []
        self.events = []  # ("pong", raw) / ("open", path)
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


class TestWebsocketLoop(unittest.IsolatedAsyncioTestCase):
    async def test_pong_replies_with_state_cursor(self):
        from roombrain.agent.protocol import run_forever

        server = self
        server.pong_raw = None
        server.ping_at = 0.0

        async def script(fake, ws):
            await ws.send(json.dumps({
                "type": "connection_state",
                "connection_id": "conn-ping",
                "agent_id": "a1",
                "generation": 7,
                "cursor": 10,
                "rooms": ["room1"],
            }))
            server.ping_at = time.monotonic()
            await ws.send(json.dumps({"type": "ping"}))
            server.pong_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            await ws.close()

        async with _FakeServer(script) as fake:
            task = asyncio.create_task(run_forever(
                fake.url, "a1", "sek", "room1",
                connection_id="conn-ping",
            ))
            try:
                deadline = time.monotonic() + 5
                while server.pong_raw is None and time.monotonic() < deadline:
                    await asyncio.sleep(0.02)
                self.assertIsNotNone(server.pong_raw, "no pong received")
                pong = json.loads(server.pong_raw)
                self.assertEqual(pong, {"type": "pong", "cursor": 10})
                self.assertLess(
                    time.monotonic() - server.ping_at, 1.0,
                    "pong arrived too late",
                )
                self.assertEqual(fake.auth[0], "Bearer sek")
                query = _parse_query(fake.paths[0])
                self.assertEqual(query.get("connection_id"), ["conn-ping"])
                self.assertEqual(query.get("rooms"), ["room1"])
            finally:
                await _stop(task)

    async def test_reconnect_fences_after_1012(self):
        from roombrain.agent.protocol import run_forever

        opens = {"n": 0}

        async def script(fake, ws):
            opens["n"] += 1
            if opens["n"] == 1:
                await ws.send(json.dumps({
                    "type": "connection_state",
                    "connection_id": "conn-fence",
                    "agent_id": "a1",
                    "generation": 7,
                    "cursor": 10,
                }))
                for seq in list(range(11, 26)) + [12]:
                    await ws.send(json.dumps({
                        "type": "message", "sequence": seq,
                    }))
                await ws.close(code=1012)
                await ws.wait_closed()
            else:
                await ws.send(json.dumps({
                    "type": "connection_state",
                    "connection_id": "conn-fence",
                    "agent_id": "a1",
                    "generation": 7,
                    "cursor": 25,
                }))
                await ws.wait_closed()

        async with _FakeServer(script) as fake:
            task = asyncio.create_task(run_forever(
                fake.url, "a1", "sek", "room1",
                connection_id="conn-fence",
            ))
            try:
                deadline = time.monotonic() + 5
                while len(fake.paths) < 2 and time.monotonic() < deadline:
                    await asyncio.sleep(0.02)
                self.assertGreaterEqual(len(fake.paths), 2)
                query = _parse_query(fake.paths[1])
                self.assertEqual(query.get("connection_id"), ["conn-fence"])
                self.assertEqual(query.get("start_from"), ["25"])
                self.assertEqual(query.get("expected_generation"), ["7"])
            finally:
                await _stop(task)

    async def test_addressed_message_prints_to_stdout(self):
        from roombrain.agent.protocol import run_forever

        async def script(fake, ws):
            await ws.send(json.dumps({
                "type": "connection_state",
                "connection_id": "conn-msg",
                "agent_id": "a1",
                "generation": 7,
                "cursor": 10,
            }))
            await ws.send(json.dumps({
                "type": "message", "addressed": True,
                "body": "!ping", "room_id": "room1",
                "sequence": 11,
            }))
            await ws.send(json.dumps({
                "type": "message", "addressed": True,
                "body": "hello-room", "sequence": 12,
            }))
            await ws.send(json.dumps({
                "type": "message", "sequence": 13,
            }))
            await ws.wait_closed()

        async with _FakeServer(script) as fake:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                task = asyncio.create_task(run_forever(
                    fake.url, "a1", "sek", "room1",
                    connection_id="conn-msg",
                ))
                try:
                    deadline = time.monotonic() + 5
                    while "!ping" not in buf.getvalue():
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                    self.assertIn("!ping", buf.getvalue())
                    self.assertNotIn("hello-room", buf.getvalue())
                finally:
                    await _stop(task)

    async def test_taken_over_exits_3_without_reconnect(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env_file = os.path.join(tmp.name, ".env")
        opened = []

        async def script(fake, ws):
            opened.append(ws.request.path)
            await ws.send(json.dumps({
                "type": "connection_state",
                "connection_id": "conn-over",
                "agent_id": "a1",
                "generation": 7,
                "cursor": 10,
            }))
            await ws.send(json.dumps({
                "type": "evicted", "code": "taken_over",
            }))
            await ws.wait_closed()

        async with _FakeServer(script) as fake:
            child_env = dict(os.environ)
            child_env["PYTHONPATH"] = repo_root
            child_env["ROOMBRAIN_AGENT_ID"] = "a1"
            child_env["ROOMBRAIN_API_KEY"] = "sek"
            started = time.monotonic()
            proc = subprocess.Popen(
                [sys.executable, "-m", "roombrain", "run",
                 "--server", fake.url, "--rooms", "room1",
                 "--env-file", env_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                cwd=tmp.name,
            )
            try:
                code = None
                elapsed = None
                deadline = started + 2.0
                while time.monotonic() < deadline:
                    code = proc.poll()
                    if code is not None:
                        elapsed = time.monotonic() - started
                        break
                    await asyncio.sleep(0.02)
                self.assertIsNotNone(code, "child did not exit within 2s")
                self.assertEqual(code, 3, "expected exit code 3 on taken_over")
                self.assertLess(elapsed, 2.0)
                try:
                    proc.communicate(timeout=5)
                except Exception:
                    pass
            finally:
                if proc.poll() is None:
                    proc.kill()
            count_at_exit = len(opened)
            await asyncio.sleep(5)
            self.assertEqual(
                len(opened), count_at_exit,
                "agent must never reconnect after taken_over",
            )


if __name__ == "__main__":
    unittest.main()
