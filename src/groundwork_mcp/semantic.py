"""Optional local Ollama embeddings layered on top of the SQLite keyword index."""

import json
import math
import urllib.request

from . import config, database

_CHUNK_LINES = 60
_CHUNK_OVERLAP = 10
_EMBED_BATCH_SIZE = 32


def _embed(texts: list[str]) -> list[list[float]]:
    payload = json.dumps({"model": config.EMBEDDING_MODEL, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{config.OLLAMA_HOST}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
    except Exception as exc:
        raise RuntimeError(
            f"Could not request embeddings from Ollama at {config.OLLAMA_HOST}. "
            f"Start Ollama and install '{config.EMBEDDING_MODEL}' with "
            f"'ollama pull {config.EMBEDDING_MODEL}'. Details: {exc}"
        ) from exc
    vectors = result.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError("Ollama returned an invalid embedding response.")
    return vectors


def _make_chunks(sources: list[dict]) -> list[dict]:
    chunks = []
    stride = _CHUNK_LINES - _CHUNK_OVERLAP
    for source in sources:
        lines = (source["raw_content"] or "").splitlines()
        for start in range(0, len(lines), stride):
            body = lines[start : start + _CHUNK_LINES]
            if not any(line.strip() for line in body):
                continue
            chunks.append({
                "file_path": source["file_path"],
                "start_line": start + 1,
                "end_line": start + len(body),
                "content": "\n".join(body),
            })
    return chunks


def index_job(job_id: str) -> int:
    """Create or replace all semantic chunks for a completed repository snapshot."""
    chunks = _make_chunks(database.get_semantic_sources(job_id))
    vectors = []
    texts = [f"File: {chunk['file_path']}\n{chunk['content']}" for chunk in chunks]
    for offset in range(0, len(texts), _EMBED_BATCH_SIZE):
        vectors.extend(_embed(texts[offset : offset + _EMBED_BATCH_SIZE]))
    for chunk, vector in zip(chunks, vectors):
        chunk["embedding_json"] = json.dumps(vector, separators=(",", ":"))
    database.replace_semantic_chunks(job_id, config.EMBEDDING_MODEL, chunks)
    return len(chunks)


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def search(job_id: str, query: str, limit: int = 20) -> list[dict]:
    """Return cosine-ranked chunks. Indexing is explicit through index_job()."""
    rows = database.get_semantic_chunks(job_id, config.EMBEDDING_MODEL)
    if not rows:
        return []
    query_vector = _embed([query])[0]
    ranked = []
    for row in rows:
        try:
            vector = json.loads(row["embedding_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        ranked.append({
            "file_path": row["file_path"],
            "line": row["start_line"],
            "line_end": row["end_line"],
            "snippet": row["content"],
            "rank": _cosine(query_vector, vector),
            "retrieval": "semantic",
        })
    return sorted(ranked, key=lambda item: (-item["rank"], item["file_path"], item["line"]))[:limit]

