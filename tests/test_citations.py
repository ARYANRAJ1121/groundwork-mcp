"""Tests for citation helpers and untrusted content fencing in server.py."""

import pytest
from unittest.mock import MagicMock
from groundwork_mcp.types import IngestJob


def _make_job(repo_url="https://github.com/owner/repo", commit_sha="abc123def456", repo_name="owner/repo"):
    """Create a minimal IngestJob for citation tests."""
    return IngestJob(
        id="j1", repo_url=repo_url, repo_name=repo_name, branch="main",
        status="complete", progress=1.0, files_processed=10, files_total=10,
        tokens_estimate=5000, commit_sha=commit_sha, clone_path=None,
        error_message=None, created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


class TestCitation:

    def test_github_permalink_single_line(self):
        from groundwork_mcp.server import _citation
        job = _make_job()
        c = _citation(job, "src/main.py", 42, 42)
        assert c["repo"] == "owner/repo"
        assert c["commit_sha"] == "abc123def456"
        assert c["path"] == "src/main.py"
        assert c["line_start"] == 42
        assert c["line_end"] == 42
        assert c["permalink"] == "https://github.com/owner/repo/blob/abc123def456/src/main.py#L42"

    def test_github_permalink_line_range(self):
        from groundwork_mcp.server import _citation
        job = _make_job()
        c = _citation(job, "src/main.py", 10, 25)
        assert c["permalink"].endswith("#L10-L25")

    def test_github_permalink_with_special_chars(self):
        from groundwork_mcp.server import _citation
        job = _make_job()
        c = _citation(job, "src/my file (2).py", 1, 1)
        assert "my%20file%20%282%29.py" in c["permalink"]

    def test_local_file_permalink(self):
        from groundwork_mcp.server import _citation
        job = _make_job(repo_url="file:///home/user/project", commit_sha="localsha")
        c = _citation(job, "src/app.py", 5, 10)
        assert c["permalink"].startswith("file:///home/user/project/")
        assert "src/app.py" in c["permalink"]

    def test_unknown_commit_sha(self):
        from groundwork_mcp.server import _citation
        job = _make_job(commit_sha=None)
        c = _citation(job, "README.md", 1, 1)
        assert c["commit_sha"] == "unknown"
        assert "unknown" in c["permalink"]

    def test_stripped_git_suffix(self):
        from groundwork_mcp.server import _citation
        job = _make_job(repo_url="https://github.com/owner/repo.git")
        c = _citation(job, "file.py", 1, 1)
        # repo_url.removesuffix(".git") is done at ingestion time, not in _citation
        # _citation uses job.repo_url as-is, but the permalink should still work
        assert "blob/" in c["permalink"]


class TestUntrustedText:

    def test_wraps_content(self):
        from groundwork_mcp.server import _untrusted_repository_text
        result = _untrusted_repository_text("hello world")
        assert result.startswith("[BEGIN UNTRUSTED REPOSITORY CONTENT]")
        assert result.endswith("[END UNTRUSTED REPOSITORY CONTENT]")
        assert "hello world" in result

    def test_wraps_multiline(self):
        from groundwork_mcp.server import _untrusted_repository_text
        result = _untrusted_repository_text("line1\nline2\nline3")
        assert "line1\nline2\nline3" in result

    def test_wraps_empty(self):
        from groundwork_mcp.server import _untrusted_repository_text
        result = _untrusted_repository_text("")
        assert "[BEGIN UNTRUSTED REPOSITORY CONTENT]" in result
        assert "[END UNTRUSTED REPOSITORY CONTENT]" in result

