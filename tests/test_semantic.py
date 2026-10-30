import json
from types import SimpleNamespace

from groundwork_mcp import semantic


def test_chunks_keep_line_ranges_and_overlap():
    lines = [f"line {number}" for number in range(1, 112)]
    chunks = semantic._make_chunks([{"file_path": "src/a.py", "raw_content": "\n".join(lines)}])

    assert [(chunk["start_line"], chunk["end_line"]) for chunk in chunks] == [
        (1, 60), (51, 110), (101, 111)
    ]


def test_index_job_builds_and_persists_embeddings(monkeypatch):
    stored = {}
    monkeypatch.setattr(semantic.database, "get_semantic_sources", lambda _job: [
        {"file_path": "src/a.py", "raw_content": "def hello():\n    return 'hi'"}
    ])
    monkeypatch.setattr(semantic, "_embed", lambda texts: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(
        semantic.database,
        "replace_semantic_chunks",
        lambda job, model, chunks: stored.update(job=job, model=model, chunks=chunks),
    )

    assert semantic.index_job("job-1") == 1
    assert stored["job"] == "job-1"
    assert stored["model"] == semantic.config.EMBEDDING_MODEL
    assert json.loads(stored["chunks"][0]["embedding_json"]) == [0.1, 0.2]


def test_search_returns_cosine_ranked_semantic_chunks(monkeypatch):
    monkeypatch.setattr(semantic, "_embed", lambda _texts: [[1.0, 0.0]])
    monkeypatch.setattr(semantic.database, "get_semantic_chunks", lambda _job, _model: [
        {"file_path": "b.py", "start_line": 1, "end_line": 3, "content": "second",
         "embedding_json": "[0.0, 1.0]"},
        {"file_path": "a.py", "start_line": 5, "end_line": 8, "content": "first",
         "embedding_json": "[1.0, 0.0]"},
    ])

    results = semantic.search("job-1", "conceptual query", limit=1)

    assert len(results) == 1
    assert results[0]["file_path"] == "a.py"
    assert results[0]["line"] == 5
    assert results[0]["line_end"] == 8
    assert results[0]["rank"] == 1.0


def test_hybrid_search_fuses_keyword_and_semantic_hits(monkeypatch):
    from groundwork_mcp import server

    job = SimpleNamespace(
        id="job-1", status="complete", repo_name="owner/repo", commit_sha="abc123",
        repo_url="https://github.com/owner/repo",
    )
    monkeypatch.setattr(server, "get_job", lambda _job_id: job)
    monkeypatch.setattr(server, "search_content", lambda *_args: [
        {"file_path": "src/a.py", "language": "python", "line": 2, "snippet": "keyword match", "rank": -1.0}
    ])
    monkeypatch.setattr(server, "get_semantic_chunks", lambda *_args: [{"id": 1}])
    monkeypatch.setattr(server, "semantic_search", lambda *_args: [
        {"file_path": "src/a.py", "line": 1, "line_end": 5,
         "snippet": "semantic context", "rank": 0.9, "retrieval": "semantic"}
    ])

    result = server.search_code("job-1", "conceptual question", mode="hybrid")

    assert len(result["results"]) == 1
    hit = result["results"][0]
    assert hit["retrieval"] == "hybrid"
    assert hit["citation"]["line_start"] == 2
    assert hit["citation"]["commit_sha"] == "abc123"
    assert hit["snippet_untrusted"] is True

