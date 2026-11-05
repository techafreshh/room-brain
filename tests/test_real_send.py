"""Real-send execution paths: Gmail/Linear payloads, ids, dry-run."""

import asyncio
import base64
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx


def _fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return tmp.name


def _cleanup_db(path):
    for candidate in (path, path + "-journal", path + "-wal",
                      path + "-shm"):
        try:
            os.unlink(candidate)
        except OSError:
            pass


class _StubServer:
    """Threaded localhost HTTP stub recording POSTs and replying canned JSON."""

    def __init__(self, handler_cls):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01},
            daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()
            self._thread.join(timeout=5)

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self._server.server_address[1]


def _gmail_handler():
    class Handler(BaseHTTPRequestHandler):
        posts = []

        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                body = {}
            Handler.posts.append({
                "path": self.path,
                "headers": dict(self.headers),
                "json": body if isinstance(body, dict) else {},
            })
            payload = json.dumps(
                {"id": "msg-1", "threadId": "thread-1"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    Handler.posts = []
    return Handler


def _linear_handler():
    class Handler(BaseHTTPRequestHandler):
        posts = []

        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                body = {}
            Handler.posts.append({
                "path": self.path,
                "headers": dict(self.headers),
                "json": body if isinstance(body, dict) else {},
            })
            payload = json.dumps({"data": {"issueCreate": {
                "success": True,
                "issue": {"id": "1", "identifier": "LIN-123",
                          "title": "t",
                          "url": "http://example.test/LIN-123"},
            }}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    Handler.posts = []
    return Handler


class _StrictClient:
    """httpx.Client stand-in failing the test if any HTTP is attempted."""

    constructions = []

    def __init__(self, *args, **kwargs):
        _StrictClient.constructions.append({"args": args, "kwargs": kwargs})

    def post(self, *args, **kwargs):
        raise AssertionError("no HTTP expected in dry-run path")

    def get(self, *args, **kwargs):
        raise AssertionError("no HTTP expected in dry-run path")

    def close(self):
        pass


class TestGmailSend(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {
            "GMAIL_OAUTH_TOKEN": "tok-123",
            "GMAIL_API_BASE_URL": "",
            "LINEAR_API_KEY": "",
        })
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_payload_shape_and_id_return(self):
        from actions.gmail_action import send_draft

        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["headers"] = dict(request.headers)
            seen["json"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200, json={"id": "msg-1", "threadId": "thread-1"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        draft = {"topic": "launch plan", "body": "hello world"}
        self.assertEqual(send_draft(draft, client=client), "msg-1")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"],
                         "/gmail/v1/users/me/messages/send")
        lowered = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertEqual(lowered.get("authorization"), "Bearer tok-123")
        self.assertIn("raw", seen["json"])
        mime = base64.urlsafe_b64decode(
            seen["json"]["raw"].encode("ascii")).decode("utf-8")
        self.assertIn("launch plan", mime)
        self.assertIn("hello world", mime)

    def test_missing_key_makes_zero_calls(self):
        from actions.gmail_action import send_draft

        with mock.patch.dict(os.environ, {"GMAIL_OAUTH_TOKEN": ""}):
            with mock.patch("httpx.Client", _StrictClient):
                _StrictClient.constructions.clear()
                self.assertFalse(
                    send_draft({"topic": "t", "body": "b"}))
                self.assertEqual(_StrictClient.constructions, [])


class TestLinearCreate(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {
            "LINEAR_API_KEY": "lin-key",
            "LINEAR_API_URL": "http://stub.test/graphql",
            "LINEAR_TEAM_ID": "",
            "GMAIL_OAUTH_TOKEN": "",
        })
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_identifier_return(self):
        from actions.linear_action import create_issue

        seen = {}

        def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["headers"] = dict(request.headers)
            seen["json"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"data": {"issueCreate": {
                "success": True,
                "issue": {"id": "1", "identifier": "LIN-123",
                          "title": "login bug",
                          "url": "http://example.test/LIN-123"},
            }}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        draft = {"topic": "login bug", "body": "traceback here"}
        self.assertEqual(create_issue(draft, client=client), "LIN-123")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"], "/graphql")
        lowered = {k.lower(): v for k, v in seen["headers"].items()}
        self.assertEqual(lowered.get("authorization"), "lin-key")
        self.assertIn("issueCreate", seen["json"].get("query", ""))
        variables = seen["json"].get("variables", {})
        self.assertEqual(variables.get("input", {}).get("title"),
                         "login bug")
        self.assertIn("traceback here",
                      variables.get("input", {}).get("description", ""))

    def test_errors_array_is_falsy(self):
        from actions.linear_action import create_issue

        def handler(request):
            return httpx.Response(
                200, json={"errors": [{"message": "boom"}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.assertFalse(
            create_issue({"topic": "t", "body": "b"}, client=client))

    def test_missing_key_makes_zero_calls(self):
        from actions.linear_action import create_issue

        with mock.patch.dict(os.environ, {"LINEAR_API_KEY": ""}):
            with mock.patch("httpx.Client", _StrictClient):
                _StrictClient.constructions.clear()
                self.assertFalse(
                    create_issue({"topic": "t", "body": "b"}))
                self.assertEqual(_StrictClient.constructions, [])


class TestGateRealSend(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()
        self.sent = tempfile.mkdtemp()

    def tearDown(self):
        _cleanup_db(self.db)

    def _ctx(self, sender, room="r1"):
        return {"room": room, "sender": sender, "requester": sender,
                "db_path": self.db}

    def test_gmail_approve_sends_and_archives(self):
        from actions.gate import dispatch_gate

        handler_cls = _gmail_handler()
        with _StubServer(handler_cls) as stub:
            with mock.patch.dict(os.environ, {
                "ROOMBRAIN_DB": self.db,
                "ROOMBRAIN_SENT_DIR": self.sent,
                "GMAIL_OAUTH_TOKEN": "tok-123",
                "GMAIL_API_BASE_URL": stub.url,
                "LINEAR_API_KEY": "",
            }):
                reply = dispatch_gate("draft", ["email", "launch plan"],
                                      self._ctx("alice"))
                self.assertIn("d1", reply)
                reply = dispatch_gate("approve", [], self._ctx("alice"))
                self.assertIn("sent", reply)
                self.assertIn("msg-1", reply)
                self.assertEqual(len(handler_cls.posts), 1)
                post = handler_cls.posts[0]
                self.assertTrue(
                    post["path"].endswith("/gmail/v1/users/me/messages/send"))
                lowered = {k.lower(): v
                           for k, v in post["headers"].items()}
                self.assertEqual(lowered.get("authorization"),
                                 "Bearer tok-123")
                mime = base64.urlsafe_b64decode(
                    post["json"]["raw"].encode("ascii")).decode("utf-8")
                self.assertIn("launch plan", mime)
                path = os.path.join(self.sent, "d1.md")
                self.assertTrue(os.path.exists(path))
                with open(path, encoding="utf-8") as handle:
                    archived = handle.read()
                self.assertIn("msg-1", archived)
                self.assertIn("sent", archived)

    def test_linear_approve_embeds_identifier(self):
        from actions.gate import dispatch_gate

        handler_cls = _linear_handler()
        with _StubServer(handler_cls) as stub:
            with mock.patch.dict(os.environ, {
                "ROOMBRAIN_DB": self.db,
                "ROOMBRAIN_SENT_DIR": self.sent,
                "GMAIL_OAUTH_TOKEN": "",
                "LINEAR_API_KEY": "lin-key",
                "LINEAR_API_URL": stub.url + "/graphql",
                "LINEAR_TEAM_ID": "",
            }):
                reply = dispatch_gate("draft", ["linear", "login bug"],
                                      self._ctx("alice"))
                self.assertIn("d1", reply)
                reply = dispatch_gate("approve", [], self._ctx("alice"))
                self.assertIn("sent", reply)
                self.assertIn("LIN-123", reply)
                self.assertEqual(len(handler_cls.posts), 1)
                self.assertIn("issueCreate",
                              json.dumps(handler_cls.posts[0]["json"]))
                path = os.path.join(self.sent, "d1.md")
                self.assertTrue(os.path.exists(path))
                with open(path, encoding="utf-8") as handle:
                    archived = handle.read()
                self.assertIn("LIN-123", archived)

    def test_keyless_approve_makes_zero_calls(self):
        from actions.gate import dispatch_gate

        gmail_cls = _gmail_handler()
        linear_cls = _linear_handler()
        with _StubServer(gmail_cls) as gmail_stub, \
                _StubServer(linear_cls) as linear_stub:
            with mock.patch.dict(os.environ, {
                "ROOMBRAIN_DB": self.db,
                "ROOMBRAIN_SENT_DIR": self.sent,
                "GMAIL_OAUTH_TOKEN": "",
                "GMAIL_API_BASE_URL": gmail_stub.url,
                "LINEAR_API_KEY": "",
                "LINEAR_API_URL": linear_stub.url + "/graphql",
                "LINEAR_TEAM_ID": "",
            }):
                with mock.patch("httpx.Client", _StrictClient):
                    _StrictClient.constructions.clear()
                    dispatch_gate("draft", ["email", "quiet topic"],
                                  self._ctx("alice"))
                    reply = dispatch_gate("approve", [],
                                          self._ctx("alice"))
                    self.assertIn("approval recorded; send skipped", reply)
                    self.assertTrue(os.path.exists(
                        os.path.join(self.sent, "d1.md")))
                    self.assertEqual(gmail_cls.posts, [])
                    self.assertEqual(linear_cls.posts, [])
                    self.assertEqual(_StrictClient.constructions, [])


class _FakeServer:
    """One-connection-script fake Switch capturing post_message replies."""

    def __init__(self, script):
        self.script = script
        self._server = None

    async def __aenter__(self):
        from websockets.asyncio.server import serve

        server = self

        async def handler(ws):
            await server.script(server, ws)

        self._server = await serve(
            handler, "127.0.0.1", 0, ping_interval=None)
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


class TestLinearApproveLoop(unittest.IsolatedAsyncioTestCase):
    async def test_approve_posts_identifier_within_5s(self):
        from roombrain.agent.protocol import run_forever

        db = _fresh_db()
        sent = tempfile.mkdtemp()
        handler_cls = _linear_handler()
        try:
            with _StubServer(handler_cls) as stub:
                with mock.patch.dict(os.environ, {
                    "ROOMBRAIN_DB": db,
                    "ROOMBRAIN_SENT_DIR": sent,
                    "GMAIL_OAUTH_TOKEN": "",
                    "LINEAR_API_KEY": "lin-key",
                    "LINEAR_API_URL": stub.url + "/graphql",
                    "LINEAR_TEAM_ID": "",
                }):
                    from actions.gate import dispatch_gate

                    dispatch_gate(
                        "draft", ["linear", "login bug"],
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
                            "payload": {"addressed": True,
                                        "body": "!approve",
                                        "room_id": "r1",
                                        "sender": "alice"},
                            "sequence": 1,
                        }))
                        await ws.wait_closed()

                    replies = []

                    def fake_post_message(server, agent_id, api_key,
                                          connection_id, room_id, text,
                                          client=None):
                        replies.append(text)
                        return "ok"

                    started = time.monotonic()
                    async with _FakeServer(script) as fake:
                        with mock.patch(
                            "roombrain.agent.ops.post_message",
                            fake_post_message,
                        ):
                            task = asyncio.create_task(run_forever(
                                fake.url, "x", "sek", "r1",
                                connection_id="conn-x",
                            ))
                            try:
                                deadline = time.monotonic() + 5
                                while time.monotonic() < deadline:
                                    if replies:
                                        break
                                    await asyncio.sleep(0.02)
                                elapsed = time.monotonic() - started
                                self.assertLess(
                                    elapsed, 5,
                                    "reply must land within 5s")
                                self.assertEqual(
                                    len(replies), 1, "expected one reply")
                                self.assertIn("sent", replies[0])
                                self.assertIn("LIN-123", replies[0])
                                self.assertEqual(len(handler_cls.posts), 1)
                                await asyncio.sleep(0.3)
                                self.assertEqual(len(replies), 1)
                            finally:
                                await _stop(task)
        finally:
            _cleanup_db(db)


if __name__ == "__main__":
    unittest.main()
