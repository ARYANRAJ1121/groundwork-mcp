"""Tests for groundwork_mcp.cloner — tarball downloader helpers (no network)."""

import os
import stat
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestRmtree:

    def test_removes_readonly_files(self, tmp_path):
        """_rmtree should handle read-only files (like git objects on Windows)."""
        from groundwork_mcp.cloner import _rmtree

        d = tmp_path / "testdir"
        d.mkdir()
        f = d / "readonly.txt"
        f.write_text("data")
        f.chmod(stat.S_IREAD)  # make read-only

        _rmtree(d)
        assert not d.exists()

    def test_removes_nested_dirs(self, tmp_path):
        from groundwork_mcp.cloner import _rmtree

        d = tmp_path / "a" / "b" / "c"
        d.mkdir(parents=True)
        (d / "file.txt").write_text("hello")

        _rmtree(tmp_path / "a")
        assert not (tmp_path / "a").exists()


class TestGitHubHeaders:

    def test_no_token(self, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.GITHUB_TOKEN", "")
        from groundwork_mcp.cloner import _github_headers
        headers = _github_headers()
        assert "Authorization" not in headers
        assert "User-Agent" in headers

    def test_with_token(self, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.GITHUB_TOKEN", "ghp_test123")
        from groundwork_mcp.cloner import _github_headers
        headers = _github_headers()
        assert headers["Authorization"] == "Bearer ghp_test123"


class TestRemoveClone:

    def test_remove_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.REPOS_DIR", tmp_path)
        clone_dir = tmp_path / "job123"
        clone_dir.mkdir()
        (clone_dir / "file.txt").write_text("data")

        from groundwork_mcp.cloner import remove_clone
        remove_clone("job123")
        assert not clone_dir.exists()

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.REPOS_DIR", tmp_path)
        from groundwork_mcp.cloner import remove_clone
        remove_clone("doesnotexist")  # should not raise


class TestCloneRepoValidation:

    def test_invalid_url_raises(self, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.REPOS_DIR", Path("/tmp/repos"))
        from groundwork_mcp.cloner import clone_repo
        with pytest.raises(ValueError, match="Invalid repo URL"):
            clone_repo("git@github.com:owner/repo.git", "job1")

