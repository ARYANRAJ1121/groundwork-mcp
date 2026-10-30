"""Tests for groundwork_mcp.database — SQLite schema, CRUD, FTS5, call graph."""

import sqlite3
import threading
import pytest
from groundwork_mcp.types import ParsedFile, SymbolRecord, EdgeRecord, CallRecord


# ── Schema ────────────────────────────────────────────────────────────────────


class TestSchema:

    def test_tables_created(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        assert "jobs" in tables
        assert "parsed_files" in tables
        assert "symbols" in tables
        assert "edges" in tables
        assert "calls" in tables
        assert "parsed_files_fts" in tables
        assert "schema_migrations" in tables

    def test_wal_mode(self, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


# ── Job CRUD ──────────────────────────────────────────────────────────────────


class TestJobCRUD:

    def test_create_and_get(self, tmp_db):
        from groundwork_mcp.database import create_job, get_job
        job = create_job("j1", "https://github.com/a/b", "a/b", "main")
        assert job.id == "j1"
        assert job.status == "queued"

        fetched = get_job("j1")
        assert fetched is not None
        assert fetched.repo_name == "a/b"

    def test_get_nonexistent(self, tmp_db):
        from groundwork_mcp.database import get_job
        assert get_job("nope") is None

    def test_list_jobs(self, tmp_db):
        from groundwork_mcp.database import create_job, list_jobs
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        create_job("j2", "https://github.com/c/d", "c/d", "dev")
        jobs = list_jobs()
        assert len(jobs) == 2
        ids = {j.id for j in jobs}
        assert ids == {"j1", "j2"}

    def test_update_job(self, tmp_db):
        from groundwork_mcp.database import create_job, update_job, get_job
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        update_job("j1", status="cloning", progress=0.1, force_commit=True)
        job = get_job("j1")
        assert job.status == "cloning"
        assert job.progress == pytest.approx(0.1)

    def test_delete_job_cascade(self, tmp_db):
        from groundwork_mcp.database import (
            create_job, update_job, insert_parsed_file, insert_symbols,
            insert_edges, insert_calls, delete_job, get_job, get_db, commit_batch,
        )
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        update_job("j1", status="complete", force_commit=True)
        insert_parsed_file("j1", ParsedFile("f.py", "python", 10, 100, None, "x=1", "hash1"))
        insert_symbols("j1", [SymbolRecord("f.py", "x", "variable", 1, 1, "x=1")])
        insert_edges("j1", [EdgeRecord("f.py", None, "os", "import", 1)])
        insert_calls("j1", [CallRecord("f.py", "<module>", "foo", 1)])
        commit_batch()

        assert delete_job("j1") is True
        assert get_job("j1") is None

        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM parsed_files WHERE job_id='j1'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM symbols WHERE job_id='j1'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM edges WHERE job_id='j1'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM calls WHERE job_id='j1'").fetchone()[0] == 0

    def test_delete_nonexistent(self, tmp_db):
        from groundwork_mcp.database import delete_job
        assert delete_job("nope") is False


# ── Parsed Files (UPSERT) ────────────────────────────────────────────────────


class TestParsedFiles:

    def test_insert_and_upsert(self, tmp_db):
        from groundwork_mcp.database import create_job, insert_parsed_file, get_db, commit_batch
        create_job("j1", "https://github.com/a/b", "a/b", "main")

        f1 = ParsedFile("app.py", "python", 10, 200, '{"t":"module"}', "x=1\n", "h1")
        insert_parsed_file("j1", f1)
        commit_batch()

        row = get_db().execute(
            "SELECT raw_content FROM parsed_files WHERE job_id='j1' AND file_path='app.py'"
        ).fetchone()
        assert row[0] == "x=1\n"

        # Upsert with new content
        f2 = ParsedFile("app.py", "python", 12, 250, '{"t":"module"}', "x=2\ny=3\n", "h2")
        insert_parsed_file("j1", f2)
        commit_batch()

        row = get_db().execute(
            "SELECT raw_content, content_hash FROM parsed_files WHERE job_id='j1' AND file_path='app.py'"
        ).fetchone()
        assert row[0] == "x=2\ny=3\n"
        assert row[1] == "h2"


# ── Bulk Insert ───────────────────────────────────────────────────────────────


class TestBulkInsert:

    def test_insert_symbols(self, tmp_db):
        from groundwork_mcp.database import create_job, insert_symbols, get_db, commit_batch
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        syms = [
            SymbolRecord("f.py", "foo", "function", 1, 5, "def foo():"),
            SymbolRecord("f.py", "Bar", "class", 7, 20, "class Bar:"),
        ]
        insert_symbols("j1", syms)
        commit_batch()
        count = get_db().execute("SELECT COUNT(*) FROM symbols WHERE job_id='j1'").fetchone()[0]
        assert count == 2

    def test_insert_edges(self, tmp_db):
        from groundwork_mcp.database import create_job, insert_edges, get_db, commit_batch
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        edges = [
            EdgeRecord("a.py", "b.py", "./b", "import", 1),
            EdgeRecord("a.py", None, "os", "import", 2),
        ]
        insert_edges("j1", edges)
        commit_batch()
        count = get_db().execute("SELECT COUNT(*) FROM edges WHERE job_id='j1'").fetchone()[0]
        assert count == 2

    def test_insert_calls(self, tmp_db):
        from groundwork_mcp.database import create_job, insert_calls, get_db, commit_batch
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        calls = [
            CallRecord("f.py", "main", "foo", 3),
            CallRecord("f.py", "main", "bar", 5),
        ]
        insert_calls("j1", calls)
        commit_batch()
        count = get_db().execute("SELECT COUNT(*) FROM calls WHERE job_id='j1'").fetchone()[0]
        assert count == 2

    def test_insert_calls_empty(self, tmp_db):
        from groundwork_mcp.database import create_job, insert_calls
        create_job("j1", "https://github.com/a/b", "a/b", "main")
        insert_calls("j1", [])  # should not raise


# ── FTS5 Search ───────────────────────────────────────────────────────────────


class TestFTS5Search:

    def test_basic_search(self, sample_job):
        from groundwork_mcp.database import search_content
        results = search_content(sample_job, "hello")
        assert len(results) >= 1
        assert any(r["file_path"] == "src/main.py" for r in results)

    def test_multi_word_search(self, sample_job):
        from groundwork_mcp.database import search_content
        results = search_content(sample_job, "import os")
        assert len(results) >= 1

    def test_empty_query(self, sample_job):
        from groundwork_mcp.database import search_content
        results = search_content(sample_job, "")
        assert results == []

    def test_no_results(self, sample_job):
        from groundwork_mcp.database import search_content
        results = search_content(sample_job, "xyznonexistent123")
        assert results == []

    def test_results_have_rank(self, sample_job):
        from groundwork_mcp.database import search_content
        results = search_content(sample_job, "def")
        for r in results:
            assert "rank" in r
            assert isinstance(r["rank"], (int, float))

    def test_limit_respected(self, sample_job):
        from groundwork_mcp.database import search_content
        results = search_content(sample_job, "def", limit=1)
        assert len(results) <= 1


# ── Call Graph Queries ────────────────────────────────────────────────────────


class TestCallGraph:

    def test_get_callers(self, sample_job):
        from groundwork_mcp.database import get_callers
        callers = get_callers(sample_job, "main")
        assert len(callers) == 1
        assert callers[0]["caller_function"] == "<module>"

    def test_get_callees(self, sample_job):
        from groundwork_mcp.database import get_callees
        callees = get_callees(sample_job, "main")
        assert len(callees) == 1
        assert callees[0]["callee_name"] == "helper"

    def test_callers_empty(self, sample_job):
        from groundwork_mcp.database import get_callers
        assert get_callers(sample_job, "nonexistent_func") == []


# ── Snapshot Cache ────────────────────────────────────────────────────────────


class TestSnapshotCache:

    def test_find_completed_snapshot(self, sample_job):
        from groundwork_mcp.database import find_completed_snapshot
        found = find_completed_snapshot("https://github.com/test/repo", "abc123def456")
        assert found is not None
        assert found.id == sample_job

    def test_find_snapshot_wrong_sha(self, sample_job):
        from groundwork_mcp.database import find_completed_snapshot
        found = find_completed_snapshot("https://github.com/test/repo", "wrong_sha")
        assert found is None


# ── Token Estimate ────────────────────────────────────────────────────────────


class TestTokenEstimate:

    def test_token_estimate(self, sample_job):
        from groundwork_mcp.database import token_estimate
        tokens = token_estimate(sample_job)
        assert tokens > 0
        assert isinstance(tokens, int)


# ── Thread Safety ─────────────────────────────────────────────────────────────


class TestThreadSafety:

    def test_thread_local_connections(self, tmp_db):
        """Each thread should get its own connection."""
        from groundwork_mcp.database import get_db

        main_conn = get_db()
        thread_conn = [None]

        def worker():
            thread_conn[0] = get_db()

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # Thread-local means different connection objects
        assert thread_conn[0] is not None
        assert thread_conn[0] is not main_conn

