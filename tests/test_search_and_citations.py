import tempfile
import unittest
import json
import io
import tarfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch
from pathlib import Path

from groundwork_mcp import config, database
from groundwork_mcp.server import (
    _citation, get_file_content, get_import_edges, get_repo_summary, ingest_repo,
    list_repo_files, search_code,
)
from groundwork_mcp.types import EdgeRecord, ParsedFile
from groundwork_mcp.pipeline import _run_pipeline_sync
from groundwork_mcp.parser import _KNOWN_LANGUAGES, _get_parser
from groundwork_mcp.server import mcp
from fastapi.testclient import TestClient
from groundwork_mcp import hosted
from benchmarks.run import citation_precision, format_repository_context
from groundwork_mcp.cloner import clone_repo


class SearchAndCitationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_repos_dir = config.REPOS_DIR
        config.DB_PATH = Path(self.temp.name) / "test.db"
        database.init_database()
        database.create_job("job", "https://github.com/acme/demo", "acme/demo", "main")
        database.update_job("job", status="complete", commit_sha="abc123def456")
        database.insert_parsed_file("job", ParsedFile(
            file_path="src/app.py", language="python", line_count=3, size_bytes=60,
            ast_json=None, raw_content="def greet():\n    return 'hello world'\n", content_hash="same",
        ))
        database.commit_batch()

    def tearDown(self):
        database.close_database()
        config.REPOS_DIR = self.old_repos_dir
        self.temp.cleanup()

    def test_fts_search_returns_line_hit(self):
        hits = database.search_content("job", "hello world", 10)
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]["file_path"], hits[0]["line"]), ("src/app.py", 2))

    def test_search_tool_brackets_repository_snippets_as_untrusted(self):
        result = search_code("job", "hello world")
        snippet = result["results"][0]["snippet"]
        self.assertTrue(snippet.startswith("[BEGIN UNTRUSTED REPOSITORY CONTENT]"))
        self.assertTrue(snippet.endswith("[END UNTRUSTED REPOSITORY CONTENT]"))
        self.assertTrue(result["results"][0]["snippet_untrusted"])

    def test_summary_and_file_list_return_structured_commit_evidence(self):
        summary = get_repo_summary("job")
        self.assertEqual(summary["commit_sha"], "abc123def456")
        self.assertEqual(summary["languages"][0]["language"], "python")
        files = list_repo_files("job")
        self.assertEqual(files["commit_sha"], "abc123def456")
        self.assertEqual(files["files"][0]["path"], "src/app.py")
        self.assertEqual(files["files"][0]["citation"]["line_start"], 1)
        self.assertIn("abc123def456", files["files"][0]["citation"]["permalink"])

    def test_citation_is_pinned_to_commit_and_lines(self):
        job = database.get_job("job")
        citation = _citation(job, "src/app.py", 2, 2)
        self.assertEqual(citation["commit_sha"], "abc123def456")
        self.assertEqual(citation["permalink"], "https://github.com/acme/demo/blob/abc123def456/src/app.py#L2")

    def test_file_read_limits_output_to_requested_lines(self):
        result = get_file_content("job", "src/app.py", 2, 2)
        self.assertEqual((result["line_start"], result["line_end"]), (2, 2))
        self.assertIn("return 'hello world'", result["content"])
        self.assertNotIn("def greet", result["content"])

    def test_file_read_paginates_large_ranges(self):
        content = "\n".join(f"line_{number}" for number in range(1, 451))
        database.insert_parsed_file("job", ParsedFile(
            file_path="large.txt", language="text", line_count=450,
            size_bytes=len(content), ast_json=None, raw_content=content,
        ))
        database.commit_batch()
        first = get_file_content("job", "large.txt")
        self.assertIn("next_start_line", first, first)
        second = get_file_content("job", "large.txt", first["next_start_line"])
        self.assertEqual((first["line_start"], first["line_end"], first["next_start_line"]), (1, 200, 201))
        self.assertEqual((second["line_start"], second["line_end"], second["next_start_line"]), (201, 400, 401))
        self.assertIn("line_200", first["content"])
        self.assertNotIn("line_201", first["content"])

    def test_import_edge_has_a_commit_pinned_line_citation(self):
        database.insert_edges("job", [EdgeRecord(
            source_file="src/app.py", target_file="src/util.py", target_module=".util",
            edge_type="import", line=7,
        )])
        database.commit_batch()
        result = get_import_edges("job", "src/app.py")
        self.assertEqual(result["results"][0]["citation"]["line_start"], 7)
        self.assertIn("abc123def456", result["results"][0]["citation"]["permalink"])

    def test_upsert_refreshes_fts_content(self):
        database.insert_parsed_file("job", ParsedFile(
            file_path="src/app.py", language="python", line_count=1, size_bytes=10,
            ast_json=None, raw_content="new_token = True\n", content_hash="new",
        ))
        database.commit_batch()
        self.assertEqual(database.search_content("job", "new_token", 10)[0]["line"], 1)
        self.assertEqual(database.search_content("job", "hello world", 10), [])

    def test_incremental_copy_reuses_only_matching_hashes(self):
        database.create_job("next", "https://github.com/acme/demo", "acme/demo", "main")
        reused = database.copy_unchanged_files("job", "next", {"src/app.py": "same"})
        self.assertEqual(reused, {"src/app.py"})
        row = database.get_db().execute(
            "SELECT content_hash FROM parsed_files WHERE job_id='next' AND file_path='src/app.py'"
        ).fetchone()
        self.assertEqual(row["content_hash"], "same")

    def test_stale_remote_commit_starts_incremental_snapshot(self):
        database.create_job("old", "https://github.com/acme/refresh", "acme/refresh", "default")
        database.update_job("old", status="complete", commit_sha="oldsha")
        from groundwork_mcp import server
        with patch.object(server, "resolve_remote_commit", return_value="newsha"), \
             patch.object(server, "run_pipeline", new=AsyncMock()) as pipeline, \
             patch.object(server.asyncio, "create_task", side_effect=lambda coroutine: coroutine.close()):
            response = __import__("asyncio").run(ingest_repo("https://github.com/acme/refresh"))
        self.assertIn("Ingestion started", response)
        self.assertEqual(pipeline.call_args.args[3], "old")
        refreshed = [job for job in database.list_jobs() if job.repo_url.endswith("/refresh")]
        self.assertEqual(len(refreshed), 2)

    def test_public_commit_key_has_single_claim(self):
        database.create_job("next", "https://github.com/acme/demo", "acme/demo", "main")
        self.assertEqual(database.claim_public_snapshot("https://github.com/acme/demo", "sha", "next"), (True, "next"))
        database.create_job("other", "https://github.com/acme/demo", "acme/demo", "main")
        self.assertEqual(database.claim_public_snapshot("https://github.com/acme/demo", "sha", "other"), (False, "next"))

    def test_tarball_ingest_pins_commit_and_rejects_unsafe_members(self):
        config.REPOS_DIR = Path(self.temp.name) / "repos"
        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            source = b"print('safe')\n"
            file_info = tarfile.TarInfo("acme-demo-abc/src/app.py")
            file_info.size = len(source)
            archive.addfile(file_info, io.BytesIO(source))

            escape = b"pwned"
            escape_info = tarfile.TarInfo("acme-demo-abc/../../outside.txt")
            escape_info.size = len(escape)
            archive.addfile(escape_info, io.BytesIO(escape))

            link_info = tarfile.TarInfo("acme-demo-abc/src/link.py")
            link_info.type = tarfile.SYMTYPE
            link_info.linkname = "../../outside.txt"
            archive.addfile(link_info)

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return self.body

        responses = [
            Response(b'{"default_branch":"main"}'),
            Response(b'{"sha":"abc123def456"}'),
            Response(archive_buffer.getvalue()),
        ]
        with patch("groundwork_mcp.cloner.urllib.request.urlopen", side_effect=responses) as urlopen:
            result = clone_repo("https://github.com/acme/demo", "job")

        root = Path(result.clone_path)
        self.assertEqual(result.commit_sha, "abc123def456")
        self.assertEqual((root / "src/app.py").read_text(encoding="utf-8"), "print('safe')\n")
        self.assertFalse((root / "src/link.py").exists())
        self.assertFalse((Path(self.temp.name) / "outside.txt").exists())
        archive_request = urlopen.call_args_list[2].args[0]
        self.assertTrue(archive_request.full_url.endswith("/tarball/abc123def456"))

    def test_language_map_and_benchmark_dataset(self):
        self.assertGreaterEqual(len(_KNOWN_LANGUAGES), 40)
        tasks = json.loads((Path(__file__).parents[1] / "benchmarks" / "tasks.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(tasks), 10)
        for task in tasks:
            lines = (Path(__file__).parents[1] / "benchmarks" / "fixtures" / task["gold_path"]).read_text(encoding="utf-8").splitlines()
            self.assertIn(task["expected_terms"][0].casefold(), lines[task["gold_line"] - 1].casefold(), task["id"])

    def test_benchmark_compares_full_repo_context_and_micro_citation_precision(self):
        fixture = Path(__file__).parents[1] / "benchmarks" / "fixtures"
        context = format_repository_context(fixture)
        self.assertIn("FILE src/config.py", context)
        self.assertIn("1: DEV_SERVER_PORT = 5174", context)
        task = {"gold_path": "src/config.py", "gold_line": 1}
        correct, count = citation_precision(
            '{"citations":[{"path":"src/config.py","line_start":1},'
            '{"path":"src/queue.py","line_start":2}]}', task
        )
        self.assertEqual((correct, count), (1, 2))

    def test_tree_sitter_parser_is_not_shared_between_worker_threads(self):
        main_parser = _get_parser("python")
        with ThreadPoolExecutor(max_workers=1) as executor:
            worker_parser = executor.submit(_get_parser, "python").result()
        self.assertIsNot(main_parser, worker_parser)

    def test_all_mapped_tree_sitter_grammars_load(self):
        unavailable = [language for language in sorted(_KNOWN_LANGUAGES) if _get_parser(language) is None]
        self.assertEqual(unavailable, [])

    def test_tool_annotations_mark_mutations(self):
        tools = {tool.name: tool for tool in __import__("asyncio").run(mcp.list_tools())}
        self.assertTrue(tools["search_code"].annotations.read_only_hint)
        self.assertTrue(tools["delete_repo"].annotations.destructive_hint)

    def test_public_web_index_reuses_same_commit_snapshot(self):
        async def complete(job_id, *_args):
            database.update_job(job_id, status="complete", commit_sha="commit-1", files_processed=2)

        with patch.object(hosted, "resolve_remote_commit", return_value="commit-1"), \
             patch.object(hosted, "run_pipeline", new=AsyncMock(side_effect=complete)), \
             patch.object(hosted, "get_repo_summary", return_value="Architecture summary"), \
             patch.object(hosted, "get_file_content", return_value={"content": "README evidence"}):
            with TestClient(hosted.app) as client:
                first = client.post("/api/architecture", json={"repo_url": "https://github.com/acme/public"})
                second = client.post("/api/architecture", json={"repo_url": "https://github.com/acme/public"})
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["cached"])
        self.assertTrue(second.json()["cached"])
        self.assertEqual(first.json()["commit_sha"], "commit-1")

    def test_local_path_pipeline_preserves_source_and_skips_git_dir(self):
        root = Path(self.temp.name) / "workspace"
        (root / ".git").mkdir(parents=True)
        (root / ".git" / "oversized-object.bin").write_bytes(b"x" * 100_000)
        (root / "app.py").write_text("def greet():\n    return 'local'\n", encoding="utf-8")
        (root / "README.md").write_text("local project\n", encoding="utf-8")
        (root / "remove.py").write_text("old_token = True\n", encoding="utf-8")
        (root / "same.md").write_text("unchanged marker\n", encoding="utf-8")
        database.create_job("local", root.as_uri(), "workspace", "local")
        _run_pipeline_sync("local", root.as_uri(), None, local_path=str(root))
        self.assertEqual(database.get_job("local").status, "complete")
        self.assertTrue((root / "app.py").exists())
        self.assertIsNotNone(database.get_db().execute(
            "SELECT 1 FROM parsed_files WHERE job_id='local' AND file_path='app.py'"
        ).fetchone())
        (root / "app.py").write_text("def greet():\n    return 'updated_local'\n", encoding="utf-8")
        (root / "remove.py").unlink()
        (root / "added.py").write_text("added_marker = True\n", encoding="utf-8")
        database.create_job("local2", root.as_uri(), "workspace", "local")
        _run_pipeline_sync("local2", root.as_uri(), None, "local", str(root))
        self.assertEqual(database.get_job("local2").status, "complete")
        self.assertEqual(database.get_job("local2").files_processed, 4)
        self.assertEqual(database.search_content("local2", "unchanged marker", 5)[0]["file_path"], "same.md")
        self.assertEqual(database.search_content("local2", "old_token", 5), [])
        self.assertIsNotNone(database.get_db().execute(
            "SELECT 1 FROM parsed_files WHERE job_id='local2' AND file_path='added.py'"
        ).fetchone())


if __name__ == "__main__":
    unittest.main()
