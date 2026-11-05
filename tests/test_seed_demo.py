"""Seed-demo tests: help flags, local seeding, synth-thread recall, live guard."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory import hybrid_search
from memory.vault import count_memories
from roombrain.cli import build_parser, main


class TestSeedDemo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name
        try:
            os.unlink(self.db)
        except OSError:
            pass
        self.tmp = tempfile.TemporaryDirectory()
        self.env_file = os.path.join(self.tmp.name, ".env")
        self._env = mock.patch.dict(
            os.environ,
            {"ROOMBRAIN_DB": self.db, "ROOMBRAIN_NO_EMBED": "1"},
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()
        try:
            os.unlink(self.db)
        except OSError:
            pass
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                os.unlink(self.db + suffix)
            except OSError:
                pass

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_mentions_live_and_local(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as ctx:
            main(["seed-demo", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        out = stdout.getvalue()
        self.assertIn("--live", out)
        self.assertIn("--local", out)

    def test_parser_accepts_both_modes(self):
        args = build_parser().parse_args(["seed-demo", "--live"])
        self.assertTrue(args.live)
        args = build_parser().parse_args(["seed-demo", "--local"])
        self.assertTrue(args.local)

    def test_local_seeds_fresh_db(self):
        code, out, _ = self._run(["seed-demo", "--local"])
        self.assertEqual(code, 0)
        self.assertIn("seeded", out)
        self.assertGreaterEqual(count_memories(), 20)

    def test_hybrid_search_returns_synth_threads(self):
        code, _, _ = self._run(["seed-demo", "--local"])
        self.assertEqual(code, 0)
        hits = hybrid_search("seeded topic", 5)
        self.assertGreaterEqual(len(hits), 3)
        synth = [h for h in hits if h["thread_id"].startswith("synth-")]
        self.assertGreaterEqual(len(synth), 3)

    def test_live_without_credentials_exits_2_and_seeds_nothing(self):
        with mock.patch.dict(
            os.environ,
            {"ROOMBRAIN_AGENT_ID": "", "ROOMBRAIN_API_KEY": ""},
        ):
            with mock.patch(
                "roombrain.agent.ops.post_message",
                side_effect=AssertionError("must not POST"),
            ):
                code, _, err = self._run(
                    ["seed-demo", "--live", "--env-file", self.env_file]
                )
        self.assertEqual(code, 2)
        self.assertIn("register", err)
        self.assertEqual(count_memories(), 0)

    def test_live_posts_each_entry_and_adopts_ids(self):
        seen = []
        counter = {"n": 0}

        def handler(request):
            counter["n"] += 1
            seen.append(request)
            body = json.loads(request.content.decode("utf-8"))
            self.assertTrue(body.get("text"))
            self.assertTrue(body.get("room_id"))
            return httpx.Response(
                200, json={"result": "msg-%d" % counter["n"]}
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        from seed.demo import seed_live

        total = seed_live(
            "http://switch.test", "a1", "sek", "conn-1", "",
            db_path=self.db, client=client,
        )
        self.assertEqual(total, 24)
        self.assertEqual(len(seen), 24)
        first = seen[0]
        self.assertEqual(first.method, "POST")
        self.assertTrue(
            first.url.path.endswith("/agents/a1/ops/post_message")
        )
        lowered = {k.lower(): v for k, v in first.headers.items()}
        self.assertEqual(lowered.get("authorization"), "Bearer sek")
        self.assertEqual(
            lowered.get("x-switch-connection-id"), "conn-1"
        )
        body_text = json.dumps(json.loads(seen[0].content.decode("utf-8")))
        self.assertIn("Decision", body_text)
        hits = hybrid_search("seeded topic", 5, db_path=self.db)
        self.assertEqual(len(hits), 5)
        self.assertTrue(all(h["thread_id"].startswith("msg-") for h in hits))
        self.assertEqual(count_memories(db_path=self.db), 24)


if __name__ == "__main__":
    unittest.main()
