"""Tests for groundwork_mcp.pipeline — pipeline helpers and error handling."""

import hashlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from groundwork_mcp.types import SievedFile


class TestLocalSnapshotSha:

    def test_deterministic(self, tmp_path):
        from groundwork_mcp.pipeline import _local_snapshot_sha

        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")

        files = [
            SievedFile("a.py", str(tmp_path / "a.py"), "python", 6),
            SievedFile("b.py", str(tmp_path / "b.py"), "python", 6),
        ]

        sha1 = _local_snapshot_sha(files)
        sha2 = _local_snapshot_sha(files)
        assert sha1 == sha2
        assert len(sha1) == 64  # SHA-256 hex

    def test_changes_with_content(self, tmp_path):
        from groundwork_mcp.pipeline import _local_snapshot_sha

        f = tmp_path / "a.py"
        f.write_text("x = 1\n", encoding="utf-8")
        files = [SievedFile("a.py", str(f), "python", 6)]

        sha1 = _local_snapshot_sha(files)

        f.write_text("x = 2\n", encoding="utf-8")
        sha2 = _local_snapshot_sha(files)

        assert sha1 != sha2

    def test_order_independent(self, tmp_path):
        """Files are sorted by relative_path, so order of input shouldn't matter."""
        from groundwork_mcp.pipeline import _local_snapshot_sha

        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")

        files_ab = [
            SievedFile("a.py", str(tmp_path / "a.py"), "python", 6),
            SievedFile("b.py", str(tmp_path / "b.py"), "python", 6),
        ]
        files_ba = [
            SievedFile("b.py", str(tmp_path / "b.py"), "python", 6),
            SievedFile("a.py", str(tmp_path / "a.py"), "python", 6),
        ]

        assert _local_snapshot_sha(files_ab) == _local_snapshot_sha(files_ba)

    def test_empty_list(self):
        from groundwork_mcp.pipeline import _local_snapshot_sha
        sha = _local_snapshot_sha([])
        assert len(sha) == 64  # empty SHA-256


class TestPipelineRmtree:

    def test_removes_directory(self, tmp_path):
        from groundwork_mcp.pipeline import _rmtree

        d = tmp_path / "toremove"
        d.mkdir()
        (d / "file.txt").write_text("data")

        _rmtree(d)
        assert not d.exists()


class TestPipelineSync:

    def test_failed_clone_sets_status(self, tmp_db, monkeypatch):
        """If clone_repo raises, the job status should be 'failed'."""
        from groundwork_mcp.database import create_job, get_job
        from groundwork_mcp.pipeline import _run_pipeline_sync

        create_job("j1", "https://github.com/a/b", "a/b", "main")

        # Mock clone_repo to fail
        monkeypatch.setattr(
            "groundwork_mcp.pipeline.clone_repo",
            MagicMock(side_effect=RuntimeError("clone failed")),
        )

        _run_pipeline_sync("j1", "https://github.com/a/b", "main")

        job = get_job("j1")
        assert job.status == "failed"
        assert "clone failed" in job.error_message

    def test_failed_sieve_sets_status(self, tmp_db, monkeypatch):
        """If sieve_repo raises, the job status should be 'failed'."""
        from groundwork_mcp.database import create_job, get_job
        from groundwork_mcp.pipeline import _run_pipeline_sync
        from groundwork_mcp.types import CloneResult

        create_job("j2", "https://github.com/a/b", "a/b", "main")

        monkeypatch.setattr(
            "groundwork_mcp.pipeline.clone_repo",
            MagicMock(return_value=CloneResult(
                clone_path=str(Path("/tmp/nonexistent_clone")),
                commit_sha="abc123",
                repo_name="a/b",
            )),
        )
        monkeypatch.setattr(
            "groundwork_mcp.pipeline.sieve_repo",
            MagicMock(side_effect=RuntimeError("sieve exploded")),
        )

        _run_pipeline_sync("j2", "https://github.com/a/b", "main")

        job = get_job("j2")
        assert job.status == "failed"
        assert "sieve exploded" in job.error_message

