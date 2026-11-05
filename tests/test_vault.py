"""Vault tests: upsert/count, schema provenance, persistence, degraded search."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.vault import count_memories, search_memories, upsert_memory


class TestVault(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db = tmp.name

    def tearDown(self):
        try:
            os.unlink(self.db)
        except OSError:
            pass
        for suffix in ("-journal", "-wal", "-shm"):
            try:
                os.unlink(self.db + suffix)
            except OSError:
                pass

    def test_fresh_upsert_then_count_equals_1(self):
        row_id = upsert_memory(
            "pricing ships Thursday", "#launch", "@techa:sw", "t1", "decision", 0.9,
            db_path=self.db,
        )
        self.assertIsInstance(row_id, int)
        self.assertGreater(row_id, 0)
        self.assertEqual(count_memories(db_path=self.db), 1)

    def test_schema_has_provenance_columns(self):
        upsert_memory("hello", "#r", "@a:s", "t", "fact", 0.5, db_path=self.db)
        conn = sqlite3.connect(self.db)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
        finally:
            conn.close()
        for col in ("room", "actor", "thread_id", "timestamp", "kind"):
            self.assertIn(col, cols)

    def test_two_upserts_persist_across_connections(self):
        upsert_memory("one", "#r", "@a:s", "t1", "decision", 0.5, db_path=self.db)
        upsert_memory("two", "#r", "@a:s", "t2", "decision", 0.6, db_path=self.db)
        # Fresh connection, no shared state.
        self.assertEqual(count_memories(db_path=self.db), 2)

    def test_keyword_search_without_embeddings_or_vec(self):
        with mock.patch.dict("sys.modules", {"sqlite_vec": None}):
            # Force the vec import to fail: loader sees None as unimportable.
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "sqlite_vec":
                    raise ImportError("blocked for test")
                return real_import(name, *args, **kwargs)

            with mock.patch("builtins.__import__", side_effect=fake_import):
                upsert_memory(
                    "pricing ships Thursday", "#launch", "@techa:sw", "t1",
                    "decision", 0.9, db_path=self.db,
                )
                hits = search_memories("pricing", db_path=self.db)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit["text"], "pricing ships Thursday")
        self.assertEqual(hit["room"], "#launch")
        self.assertEqual(hit["actor"], "@techa:sw")
        self.assertEqual(hit["thread_id"], "t1")

    def test_upsert_returns_positive_int_id(self):
        first = upsert_memory("a", "#r", "@a:s", "t", "fact", 0.1, db_path=self.db)
        second = upsert_memory("b", "#r", "@a:s", "t", "fact", 0.2, db_path=self.db)
        self.assertGreater(second, first)


if __name__ == "__main__":
    unittest.main()
