"""Tests for groundwork_mcp.security — URL validation, binary detection, repo limits."""

import pytest
from pathlib import Path
from groundwork_mcp.security import validate_repo_url, extract_repo_name, is_binary_file, check_repo_limits


# ── validate_repo_url ────────────────────────────────────────────────────────


class TestValidateRepoUrl:

    @pytest.mark.parametrize("url", [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/",
        "https://github.com/My-Org/my_repo",
        "https://github.com/user123/repo.js",
    ])
    def test_valid_urls(self, url):
        valid, error = validate_repo_url(url)
        assert valid is True
        assert error == ""

    @pytest.mark.parametrize("url,reason", [
        ("git@github.com:owner/repo.git", "SSH"),
        ("git://github.com/owner/repo", "git://"),
        ("http://github.com/owner/repo", "HTTP not HTTPS"),
        ("https://gitlab.com/owner/repo", "non-GitHub host"),
        ("https://github.com/owner", "missing repo segment"),
        ("https://github.com/", "empty path"),
        ("ftp://github.com/owner/repo", "wrong scheme"),
    ])
    def test_invalid_urls(self, url, reason):
        valid, error = validate_repo_url(url)
        assert valid is False, f"Should reject: {reason}"
        assert len(error) > 0


# ── extract_repo_name ────────────────────────────────────────────────────────


class TestExtractRepoName:

    def test_basic(self):
        assert extract_repo_name("https://github.com/owner/repo") == "owner/repo"

    def test_trailing_slash(self):
        assert extract_repo_name("https://github.com/owner/repo/") == "owner/repo"

    def test_git_suffix(self):
        assert extract_repo_name("https://github.com/owner/repo.git") == "owner/repo"

    def test_whitespace(self):
        assert extract_repo_name("  https://github.com/owner/repo  ") == "owner/repo"

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            extract_repo_name("https://github.com/")


# ── is_binary_file ───────────────────────────────────────────────────────────


class TestIsBinaryFile:

    def test_text_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("Hello, world!", encoding="utf-8")
        assert is_binary_file(f) is False

    def test_binary_file(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"header\x00\x01\x02\x03rest")
        assert is_binary_file(f) is True

    def test_unreadable_file(self, tmp_path):
        f = tmp_path / "nope.txt"
        # File doesn't exist → OSError → returns True
        assert is_binary_file(f) is True

    def test_pure_utf8(self, tmp_path):
        f = tmp_path / "unicode.txt"
        f.write_text("Héllö wörld 日本語", encoding="utf-8")
        assert is_binary_file(f) is False


# ── check_repo_limits ────────────────────────────────────────────────────────


class TestCheckRepoLimits:

    def test_within_limits(self, tmp_path, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 100)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 100)
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.py").write_text("y = 2")
        ok, err = check_repo_limits(tmp_path)
        assert ok is True
        assert err == ""

    def test_too_many_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 2)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 100)
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x = 1")
        ok, err = check_repo_limits(tmp_path)
        assert ok is False
        assert "file limit" in err.lower() or "exceeds" in err.lower()

    def test_too_large(self, tmp_path, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 0)  # 0 MB limit
        (tmp_path / "big.txt").write_text("a" * 2000)
        ok, err = check_repo_limits(tmp_path)
        assert ok is False
        assert "size limit" in err.lower() or "exceeds" in err.lower()

