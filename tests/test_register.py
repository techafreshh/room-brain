"""Register tests: 200-persist, reuse-zero-POST, 409-no-overwrite."""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import httpx

from roombrain.agent.protocol import (
    RegistrationConflict,
    read_env_values,
    register_agent,
    write_env_values,
)
from roombrain.cli import build_parser, cmd_register


class TestRegister(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_file = os.path.join(self.tmp.name, ".env")

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, *extra):
        return build_parser().parse_args(
            [
                "register",
                "--server",
                "http://switch.test",
                "--token",
                "sek",
                "--name",
                "roombrain",
                "--env-file",
                self.env_file,
            ]
            + list(extra)
        )

    def _run(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
            sys, "stderr", stderr
        ):
            code = cmd_register(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_register_persists_keys_on_200(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"id": "a1", "api_key": "k1"})

        with mock.patch("httpx.Client", return_value=self._client(handler)):
            code, out, _ = self._run(self._args())
        self.assertEqual(code, 0)
        values = read_env_values(self.env_file)
        self.assertEqual(values.get("ROOMBRAIN_AGENT_ID"), "a1")
        self.assertEqual(values.get("ROOMBRAIN_API_KEY"), "k1")
        self.assertEqual(len(seen), 1)
        self.assertNotIn("k1", out)

    def test_register_reuses_without_http(self):
        write_env_values(
            self.env_file,
            {"ROOMBRAIN_AGENT_ID": "a1", "ROOMBRAIN_API_KEY": "k1"},
        )
        with mock.patch(
            "httpx.Client", side_effect=AssertionError("must not POST")
        ):
            code, out, _ = self._run(self._args())
        self.assertEqual(code, 0)
        self.assertIn("reuse", out)

    def test_register_409_reuses_without_overwrite(self):
        bodies = []
        calls = []

        def handler(request):
            calls.append(request)
            bodies.append(json.loads(request.content))
            return httpx.Response(409, json={"detail": "name taken"})

        with mock.patch("httpx.Client", return_value=self._client(handler)):
            code, out, _ = self._run(self._args())
        self.assertEqual(code, 0)
        self.assertIn("reuse", out)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("overwrite", bodies[0])
        self.assertFalse(os.path.exists(self.env_file))

    def test_register_preserves_unrelated_vars(self):
        with open(self.env_file, "w", encoding="utf-8") as handle:
            handle.write("# keep me\nOTHER=1\n")

        def handler(request):
            return httpx.Response(200, json={"id": "a1", "api_key": "k1"})

        with mock.patch("httpx.Client", return_value=self._client(handler)):
            code, _, _ = self._run(self._args())
        self.assertEqual(code, 0)
        with open(self.env_file, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertIn("# keep me", raw)
        self.assertEqual(read_env_values(self.env_file).get("OTHER"), "1")

    def test_register_agent_body_has_no_overwrite(self):
        bodies = []
        headers = []

        def handler(request):
            bodies.append(json.loads(request.content))
            headers.append(request.headers)
            return httpx.Response(200, json={"id": "a1", "api_key": "k1"})

        agent_id, api_key, reused = register_agent(
            "http://switch.test/",
            "",
            "roombrain",
            self.env_file,
            client=self._client(handler),
        )
        self.assertEqual((agent_id, api_key, reused), ("a1", "k1", False))
        body = bodies[0]
        self.assertEqual(body["name"], "roombrain")
        self.assertEqual(
            body["integration_profile"]["connection_model"], "always_on"
        )
        self.assertTrue(body["integration_profile"]["message_exchange"])
        self.assertNotIn("overwrite", body)
        self.assertNotIn("authorization", set(headers[0].keys()))

    def test_register_agent_sends_bearer_token(self):
        headers = []

        def handler(request):
            headers.append(request.headers)
            return httpx.Response(200, json={"id": "a1", "api_key": "k1"})

        register_agent(
            "http://switch.test",
            "sek",
            "roombrain",
            self.env_file,
            client=self._client(handler),
        )
        self.assertEqual(headers[0]["authorization"], "Bearer sek")

    def test_register_agent_409_raises_conflict(self):
        def handler(request):
            return httpx.Response(409, json={"detail": "name taken"})

        with self.assertRaises(RegistrationConflict):
            register_agent(
                "http://switch.test",
                "sek",
                "roombrain",
                self.env_file,
                client=self._client(handler),
            )
        self.assertFalse(os.path.exists(self.env_file))


if __name__ == "__main__":
    unittest.main()
