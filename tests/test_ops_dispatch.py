"""Ops dispatch tests: parsers, header/body shape, discovery, loop."""

import asyncio
import json
import time
import unittest
from unittest import mock

import httpx

from roombrain.agent.events import message_room, parse_command
from roombrain.agent.ops import discover_ops, post_message


class TestParseCommand(unittest.TestCase):
    def test_ping_splits(self):
        self.assertEqual(parse_command("!ping"), ("ping", []))
        self.assertEqual(parse_command("  !ping  "), ("ping", []))
        self.assertEqual(
            parse_command("!ping extra args"), ("ping", ["extra", "args"])
        )

    def test_non_command_yields_none(self):
        self.assertIsNone(parse_command("hello"))
        self.assertIsNone(parse_command("ping"))
        self.assertIsNone(parse_command("hello-room"))
        self.assertIsNone(parse_command(""))
        self.assertIsNone(parse_command("!"))
        self.assertIsNone(parse_command("! foo"))
        self.assertIsNone(parse_command(None))
        self.assertIsNone(parse_command(123))

    def test_case_sensitive(self):
        name, _ = parse_command("!ping")
        self.assertEqual(name, "ping")
        other, _ = parse_command("!Ping")
        self.assertEqual(other, "Ping")
        self.assertIsNone(parse_command("ping"))


class TestMessageRoom(unittest.TestCase):
    def test_top_level_keys(self):
        self.assertEqual(message_room({"room_id": "r1"}), "r1")
        self.assertEqual(message_room({"room": "r2"}), "r2")
        self.assertEqual(message_room({"roomId": "r3"}), "r3")
        self.assertEqual(message_room({"channel": "r4"}), "r4")

    def test_nested_payload(self):
        frame = {"type": "message", "payload": {"room_id": "r9"}}
        self.assertEqual(message_room(frame), "r9")

    def test_missing_yields_none(self):
        self.assertIsNone(message_room({"type": "message"}))
        self.assertIsNone(message_room({}))


class TestDiscoverOps(unittest.TestCase):
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_parses_post_message_key(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertTrue(
                request.url.path.endswith("/agents/x/ops")
            )
            self.assertEqual(
                request.headers.get("X-Switch-Connection-Id"), "conn-1"
            )
            self.assertEqual(
                request.headers.get("Authorization"), "Bearer sek"
            )
            return httpx.Response(
                200, json={"operations": {"post_message": {"a": 1}}}
            )

        ops = discover_ops(
            "http://switch.test", "x", "sek", "conn-1",
            client=self._client(handler),
        )
        self.assertEqual(ops, {"post_message": {"a": 1}})

    def test_tolerates_missing_and_garbage(self):
        def empty(request):
            return httpx.Response(200, json={})

        def garbage(request):
            return httpx.Response(200, json=[1, 2])

        def error(request):
            return httpx.Response(500, json={})

        self.assertEqual(
            discover_ops("http://h", "x", "k", "c",
                         client=self._client(empty)),
            {},
        )
        self.assertEqual(
            discover_ops("http://h", "x", "k", "c",
                         client=self._client(garbage)),
            {},
        )
        self.assertEqual(
            discover_ops("http://h", "x", "k", "c",
                         client=self._client(error)),
            {},
        )


class TestPostMessage(unittest.TestCase):
    def test_header_and_body_shape(self):
        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["headers"] = dict(request.headers)
            seen["json"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"result": "ok"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = post_message(
            "http://switch.test/", "x", "sek", "conn-9",
            "r1", "pong", client=client,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"], "/agents/x/ops/post_message")
        lowered = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertEqual(lowered.get("x-switch-connection-id"), "conn-9")
        self.assertEqual(lowered.get("authorization"), "Bearer sek")
        body_text = json.dumps(seen["json"])
        self.assertIn("pong", body_text)
        self.assertIn("r1", body_text)


def _parse_query(path):
    return parse_qs(urlparse(path).query)


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


class TestDispatchLoop(unittest.IsolatedAsyncioTestCase):
    async def test_unaddressed_hello_yields_zero_posts(self):
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
                "body": "hello", "sequence": 1,
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

    async def test_addressed_ping_posts_once_with_header_and_pong(self):
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
                "type": "message",
                "payload": {"addressed": True, "body": "!ping",
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
                    self.assertEqual(len(posts), 1, "expected one POST")
                    post = posts[0]
                    self.assertTrue(
                        post["url"].endswith("/agents/x/ops/post_message")
                    )
                    lowered = {
                        k.lower(): v
                        for k, v in post["headers"].items()
                    }
                    self.assertIn("x-switch-connection-id", lowered)
                    self.assertEqual(
                        lowered["x-switch-connection-id"], "conn-x"
                    )
                    self.assertIn("pong", json.dumps(post["json"]))
                    await asyncio.sleep(0.5)
                    posts = [
                        p for inst in _RecordingClient.instances
                        for p in inst.posts
                    ]
                    self.assertEqual(len(posts), 1, "exactly one POST")
                finally:
                    await _stop(task)


if __name__ == "__main__":
    unittest.main()
