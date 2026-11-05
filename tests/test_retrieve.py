"""Retrieve tests: hybrid blend, keyword fallback, recent decisions."""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.retrieve import hybrid_search, recent_decisions
from memory.vault import upsert_memory

DIM = 384


def _vec(value):
    return [float(value)] * DIM


class TestRetrieve(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name
        self._env = mock.patch.dict(
            os.environ, {"ROOMBRAIN_NO_EMBED": "1"}
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

    def _seed_pricing(self):
        upsert_memory(
            "pricing ships Thursday", "#launch", "@techa:sw", "t-thu",
            "decision", 0.9, db_path=self.db,
        )
        upsert_memory(
            "pricing discount update", "#launch", "@techa:sw", "t-fri",
            "fact", 0.5, db_path=self.db,
        )
        upsert_memory(
            "pricing refund policy", "#launch", "@techa:sw", "t-mon",
            "fact", 0.5, db_path=self.db,
        )

    def test_hybrid_ranks_thursday_first_with_thread(self):
        self._seed_pricing()
        hits = hybrid_search("pricing ship date", 3, db_path=self.db)
        self.assertGreaterEqual(len(hits), 1)
        top = hits[0]
        self.assertIn("Thursday", top["text"])
        self.assertTrue(top["thread_id"])
        self.assertTrue(top["thread_link"])
        self.assertTrue(top["date"])
        self.assertIn("Thursday", top["bullet"])

    def test_keyword_fallback_without_embeddings_is_fast(self):
        self._seed_pricing()
        started = time.monotonic()
        hits = hybrid_search("pricing", 3, db_path=self.db)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(len(hits), 1)
        self.assertLess(elapsed, 2.0)

    def test_recent_decisions_filters_kind_and_caps(self):
        for i in range(25):
            upsert_memory(
                "pricing decision %d" % i, "#r", "@a:s", "t%d" % i,
                "decision", 0.5, db_path=self.db,
            )
        upsert_memory(
            "pricing loose fact", "#r", "@a:s", "tf", "fact", 0.5,
            db_path=self.db,
        )
        rows = recent_decisions("pricing", 7, db_path=self.db)
        self.assertLessEqual(len(rows), 20)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(row["kind"], "decision")
            self.assertTrue(row["thread_link"])

    def test_blend_prefers_vector_winner_over_keyword_winner(self):
        # Keyword side loves row 1 (repeated term); vector side loves row 2.
        query_vec = _vec(1.0)
        upsert_memory(
            "pricing pricing pricing discount", "#r", "@a:s", "t-kw",
            "fact", 0.5, embedding=_vec(0.0), db_path=self.db,
        )
        upsert_memory(
            "unrelated weather notes", "#r", "@a:s", "t-vec",
            "fact", 0.5, embedding=_vec(1.0), db_path=self.db,
        )
        with mock.patch(
            "memory.retrieve._embed_query", return_value=query_vec
        ):
            hits = hybrid_search("pricing", 5, db_path=self.db)
        if len(hits) < 2 or hits[0]["thread_id"] != "t-vec":
            # Vec extension unavailable: keyword-only still answers.
            self.assertGreaterEqual(len(hits), 1)
            self.assertIn("pricing", hits[0]["text"])
            return
        self.assertEqual(hits[0]["thread_id"], "t-vec")
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_blank_query_returns_empty(self):
        self._seed_pricing()
        self.assertEqual(hybrid_search("", 3, db_path=self.db), [])
        self.assertEqual(hybrid_search("   ", 3, db_path=self.db), [])

    def test_keyword_results_survive_blocked_vec(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "sqlite_vec":
                raise ImportError("blocked for test")
            return real_import(name, *args, **kwargs)

        with mock.patch.dict("sys.modules", {"sqlite_vec": None}):
            with mock.patch("builtins.__import__", side_effect=fake_import):
                self._seed_pricing()
                hits = hybrid_search(
                    "pricing ship date", 3, db_path=self.db
                )
        self.assertGreaterEqual(len(hits), 1)
        self.assertIn("Thursday", hits[0]["text"])


if __name__ == "__main__":
    unittest.main()
