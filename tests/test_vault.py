"""Vault tests: upsert/count, schema provenance, persistence, degraded search."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.vault import (
    count_memories,
    get_draft,
    get_room_owner,
    list_decisions,
    pending_draft_for_room,
    record_room_owner,
    search_memories,
    stage_draft,
    upsert_memory,
)


def _remove_path(path):
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass


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

    def test_reads_issue_no_ddl_or_commit(self):
        upsert_memory(
            "pricing ships Thursday", "#launch", "@techa:sw", "t1",
            "decision", 0.9, db_path=self.db,
        )
        record_room_owner("#launch", "@techa:sw", db_path=self.db)
        uid = stage_draft(
            "send", "topic", "body", "#launch", "@techa:sw",
            db_path=self.db,
        )
        commits = []
        connect_args = []
        real_connect = sqlite3.connect

        class _SpyConn:
            def __init__(self, inner):
                self.__dict__["_inner"] = inner

            def commit(self, *args, **kwargs):
                commits.append(1)
                return self._inner.commit(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        def _spy_connect(*args, **kwargs):
            connect_args.append((args, kwargs))
            return _SpyConn(real_connect(*args, **kwargs))

        with mock.patch("memory.vault._ensure_schema") as ensure:
            with mock.patch("sqlite3.connect", side_effect=_spy_connect):
                self.assertEqual(count_memories(db_path=self.db), 1)
                hits = search_memories("pricing", db_path=self.db)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["text"], "pricing ships Thursday")
                self.assertEqual(
                    get_room_owner("#launch", db_path=self.db), "@techa:sw"
                )
                draft = get_draft(uid, db_path=self.db)
                self.assertIsNotNone(draft)
                self.assertEqual(draft["id"], uid)
                pending = pending_draft_for_room("#launch", db_path=self.db)
                self.assertIsNotNone(pending)
                decisions = list_decisions(db_path=self.db)
                self.assertEqual(len(decisions), 1)
            ensure.assert_not_called()
            self.assertEqual(commits, [])
            self.assertTrue(connect_args)
            for _args, kwargs in connect_args:
                self.assertTrue(kwargs.get("uri"))
                self.assertIn("mode=ro", _args[0])

    def test_reads_on_missing_db_return_empties_without_creating_file(self):
        fresh = self.db + ".missing.db"
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.unlink(fresh + suffix)
            except OSError:
                pass
        self.addCleanup(_remove_path, fresh)
        self.assertEqual(count_memories(db_path=fresh), 0)
        self.assertEqual(search_memories("pricing", db_path=fresh), [])
        self.assertIsNone(get_room_owner("#launch", db_path=fresh))
        self.assertIsNone(get_draft("d1", db_path=fresh))
        self.assertIsNone(pending_draft_for_room("#launch", db_path=fresh))
        self.assertEqual(list_decisions(db_path=fresh), [])
        self.assertFalse(os.path.exists(fresh))

    def test_upsert_on_fresh_path_still_bootstraps(self):
        fresh = self.db + ".fresh.db"
        try:
            os.unlink(fresh)
        except OSError:
            pass
        self.addCleanup(_remove_path, fresh)
        row_id = upsert_memory(
            "pricing ships Thursday", "#launch", "@techa:sw", "t1",
            "decision", 0.9, db_path=fresh,
        )
        self.assertGreater(row_id, 0)
        self.assertTrue(os.path.exists(fresh))
        self.assertEqual(count_memories(db_path=fresh), 1)


if __name__ == "__main__":
    unittest.main()
