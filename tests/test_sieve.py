"""Tests for groundwork_mcp.sieve — file filtering and directory traversal."""

import pytest
from pathlib import Path
from groundwork_mcp.sieve import sieve_repo


class TestSieveRepo:

    def test_includes_supported_files(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert "src/app.py" in paths
        assert "src/utils.py" in paths
        assert "index.js" in paths
        assert "README.md" in paths
        assert "package.json" in paths

    def test_skips_node_modules(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert not any("node_modules" in p for p in paths)

    def test_skips_pycache(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert not any("__pycache__" in p for p in paths)

    def test_skips_hidden_dirs(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert not any(".hidden" in p for p in paths)

    def test_skips_lock_files(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert "package-lock.json" not in paths

    def test_skips_empty_files(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert "empty.py" not in paths

    def test_skips_binary_files(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = {f.relative_path for f in result.files}
        assert "image.png" not in paths

    def test_skips_oversized_files(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        monkeypatch.setattr("groundwork_mcp.config.MAX_SINGLE_FILE_KB", 0)  # 0 KB = all files oversized
        result = sieve_repo(str(mini_repo))
        # All files should be skipped as oversized
        assert result.total_files == 0

    def test_files_sorted(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        paths = [f.relative_path for f in result.files]
        assert paths == sorted(paths)

    def test_correct_languages(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        lang_map = {f.relative_path: f.language for f in result.files}
        assert lang_map.get("src/app.py") == "python"
        assert lang_map.get("index.js") == "javascript"
        assert lang_map.get("README.md") == "markdown"
        assert lang_map.get("package.json") == "json"

    def test_skipped_counts(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        assert result.skipped_files > 0
        assert len(result.skipped_reasons) > 0

    def test_repo_too_many_files_raises(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 1)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        with pytest.raises(RuntimeError, match="file limit"):
            sieve_repo(str(mini_repo))

    def test_total_size_bytes(self, mini_repo, monkeypatch):
        monkeypatch.setattr("groundwork_mcp.config.MAX_FILE_COUNT", 10000)
        monkeypatch.setattr("groundwork_mcp.config.MAX_REPO_SIZE_MB", 500)
        result = sieve_repo(str(mini_repo))
        assert result.total_size_bytes > 0
        assert result.total_size_bytes == sum(f.size_bytes for f in result.files)

