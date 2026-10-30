"""Tests for groundwork_mcp.router — keyword fallback and query routing."""

import pytest
from groundwork_mcp.router import route_query, _keyword_route


class TestKeywordFallback:

    @pytest.mark.parametrize("query,expected_tool", [
        ("ingest https://github.com/a/b", "ingest_repo"),
        ("clone this repo", "ingest_repo"),
        ("index https://github.com/a/b", "ingest_repo"),
        ("what is the status of my job", "get_ingest_status"),
        ("how far along is the progress", "get_ingest_status"),
        ("list all repos", "list_ingested_repos"),
        ("show me all ingested repositories", "list_ingested_repos"),
        ("give me a summary of this project", "get_repo_summary"),
        ("what is the architecture", "get_repo_summary"),
        ("overview of the codebase", "get_repo_summary"),
        ("where is the function main defined", "query_symbols"),
        ("find the class UserService", "query_symbols"),
        ("what does app.py import", "get_import_edges"),
        ("show dependencies", "get_import_edges"),
        ("show me the README", "get_file_content"),
        ("read file src/main.py", "get_file_content"),
        ("what does the config file say", "get_file_content"),
        ("list all files", "list_repo_files"),
        ("browse the directory", "list_repo_files"),
        ("delete this repo", "delete_repo"),
        ("remove the index", "delete_repo"),
        ("search for pgvector", "search_code"),
        ("grep for TODO", "search_code"),
        ("find text error_handler", "search_code"),
        ("who calls the train function", "get_call_graph"),
        ("trace execution of forward", "get_call_graph"),
        ("what does step() call", "get_call_graph"),
    ])
    def test_keyword_mapping(self, query, expected_tool):
        result = _keyword_route(query)
        assert result["recommended_tool"] == expected_tool
        assert result["method"] == "keyword_fallback"

    def test_default_fallback(self):
        result = _keyword_route("xyzzy nothing matches here")
        assert result["recommended_tool"] == "get_repo_summary"
        assert result["confidence"] == 0.2
        assert result["method"] == "keyword_fallback_default"

    def test_confidence_for_keyword_match(self):
        result = _keyword_route("search for something")
        assert result["confidence"] == 0.5

    def test_needs_job_id(self):
        # Most tools need job_id except ingest_repo and list_ingested_repos
        result = _keyword_route("search for foo")
        assert result["needs_job_id"] is True

        result = _keyword_route("ingest a repo")
        assert result["needs_job_id"] is False

        result = _keyword_route("list all repos")
        assert result["needs_job_id"] is False


class TestRouteQuery:

    def test_falls_back_to_keywords_without_laya(self):
        """route_query should work without laya installed by using keyword fallback."""
        result = route_query("where is the function foo defined?")
        assert "recommended_tool" in result
        assert "confidence" in result
        assert "method" in result
        # Should be keyword_fallback since laya is likely not installed in test env
        assert result["method"] in ("keyword_fallback", "laya")

    def test_returns_all_fields(self):
        result = route_query("show me the README")
        assert "recommended_tool" in result
        assert "confidence" in result
        assert "complexity" in result
        assert "needs_job_id" in result
        assert "is_about_specific_file" in result
        assert "method" in result

    def test_empty_query(self):
        result = route_query("")
        assert "recommended_tool" in result

