"""Groundwork MCP — SQLite database (Python built-in sqlite3)."""

import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from . import config
from .types import IngestJob, ParsedFile, SymbolRecord, EdgeRecord, CallRecord

# ── Connection ────────────────────────────────────────────────────────────────

_local = threading.local()
_connections: set[sqlite3.Connection] = set()
_connections_lock = threading.Lock()
_last_commit_time: float = 0.0
_COMMIT_INTERVAL: float = 0.5  # seconds — throttle progress-only commits


def get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -32000")
        _local.conn = conn
        with _connections_lock:
            _connections.add(conn)
    return conn


def init_database() -> None:
    """Initialize SQLite connection, create tables, run migrations."""
    _log(f"Opening database: {config.DB_PATH}")
    conn = get_db()
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    _log("Database ready")


def close_database() -> None:
    with _connections_lock:
        for conn in _connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _connections.clear()
    _local.conn = None


def _log(msg: str) -> None:
    print(f"[db] {msg}", file=sys.stderr)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_total INTEGER NOT NULL DEFAULT 0,
    tokens_estimate INTEGER NOT NULL DEFAULT 0,
    commit_sha TEXT,
    clone_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parsed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    language TEXT NOT NULL,
    line_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    ast_json TEXT,
    raw_content TEXT,
    content_hash TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, file_path)
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    target_file TEXT,
    target_module TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'import',
    line INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_job   ON symbols(job_id);
CREATE INDEX IF NOT EXISTS idx_symbols_name  ON symbols(job_id, symbol_name);
CREATE INDEX IF NOT EXISTS idx_symbols_file  ON symbols(job_id, file_path);
CREATE INDEX IF NOT EXISTS idx_edges_job     ON edges(job_id);
CREATE INDEX IF NOT EXISTS idx_edges_source  ON edges(job_id, source_file);
CREATE INDEX IF NOT EXISTS idx_edges_target  ON edges(job_id, target_file);
CREATE INDEX IF NOT EXISTS idx_files_job     ON parsed_files(job_id);
CREATE INDEX IF NOT EXISTS idx_files_lang    ON parsed_files(job_id, language);
CREATE INDEX IF NOT EXISTS idx_jobs_repo_commit ON jobs(repo_url, commit_sha, status);

CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    caller_file TEXT NOT NULL,
    caller_function TEXT NOT NULL,
    callee_name TEXT NOT NULL,
    line INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS public_snapshot_cache (
    repo_url TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    PRIMARY KEY(repo_url, commit_sha)
);

CREATE TABLE IF NOT EXISTS semantic_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    model TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding_json TEXT NOT NULL,
    UNIQUE(job_id, file_path, start_line, model)
);

CREATE INDEX IF NOT EXISTS idx_calls_job    ON calls(job_id);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(job_id, callee_name);
CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(job_id, caller_function);
CREATE INDEX IF NOT EXISTS idx_semantic_job_model ON semantic_chunks(job_id, model);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Safe, additive schema migrations.
    Each migration is idempotent — safe to run on every startup.
    """
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(parsed_files)")
    }
    if "raw_content" not in columns:
        conn.execute("ALTER TABLE parsed_files ADD COLUMN raw_content TEXT")
        _log("Migration: added parsed_files.raw_content")
    if "content_hash" not in columns:
        conn.execute("ALTER TABLE parsed_files ADD COLUMN content_hash TEXT")
        _log("Migration: added parsed_files.content_hash")
    edge_columns = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
    if "line" not in edge_columns:
        conn.execute("ALTER TABLE edges ADD COLUMN line INTEGER NOT NULL DEFAULT 1")
        _log("Migration: added edges.line")

    # Add calls table if it doesn't exist
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "calls" not in tables:
        conn.executescript("""
            CREATE TABLE calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                caller_file TEXT NOT NULL,
                caller_function TEXT NOT NULL,
                callee_name TEXT NOT NULL,
                line INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_calls_job    ON calls(job_id);
            CREATE INDEX idx_calls_callee ON calls(job_id, callee_name);
            CREATE INDEX idx_calls_caller ON calls(job_id, caller_function);
        """)
        _log("Migration: created calls table")

    # FTS5 is rebuilt once during migration so existing indexes become searchable.
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS parsed_files_fts USING fts5(raw_content, content='parsed_files', content_rowid='id', tokenize='unicode61')")
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS parsed_files_ai AFTER INSERT ON parsed_files BEGIN
          INSERT INTO parsed_files_fts(rowid, raw_content) VALUES (new.id, new.raw_content);
        END;
        CREATE TRIGGER IF NOT EXISTS parsed_files_ad AFTER DELETE ON parsed_files BEGIN
          INSERT INTO parsed_files_fts(parsed_files_fts, rowid, raw_content) VALUES ('delete', old.id, old.raw_content);
        END;
        CREATE TRIGGER IF NOT EXISTS parsed_files_au AFTER UPDATE OF raw_content ON parsed_files BEGIN
          INSERT INTO parsed_files_fts(parsed_files_fts, rowid, raw_content) VALUES ('delete', old.id, old.raw_content);
          INSERT INTO parsed_files_fts(rowid, raw_content) VALUES (new.id, new.raw_content);
        END;
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    migrated = conn.execute("SELECT 1 FROM schema_migrations WHERE name='fts5-v1'").fetchone()
    if not migrated:
        conn.execute("INSERT INTO parsed_files_fts(parsed_files_fts) VALUES ('rebuild')")
        conn.execute("INSERT INTO schema_migrations(name) VALUES ('fts5-v1')")


# ── Job CRUD ──────────────────────────────────────────────────────────────────

def create_job(job_id: str, repo_url: str, repo_name: str, branch: str) -> IngestJob:
    now = _now()
    get_db().execute(
        """INSERT INTO jobs (id, repo_url, repo_name, branch, status,
           progress, files_processed, files_total, tokens_estimate,
           created_at, updated_at)
           VALUES (?,?,?,?,'queued',0,0,0,0,?,?)""",
        (job_id, repo_url, repo_name, branch, now, now),
    )
    get_db().commit()
    _log(f"Created job {job_id} for {repo_name}")
    return IngestJob(
        id=job_id, repo_url=repo_url, repo_name=repo_name, branch=branch,
        status="queued", progress=0, files_processed=0, files_total=0,
        tokens_estimate=0, commit_sha=None, clone_path=None,
        error_message=None, created_at=now, updated_at=now,
    )


def update_job(job_id: str, force_commit: bool = False, **kwargs) -> None:
    """Update job fields. Commits immediately on status changes; throttles progress-only writes."""
    if not kwargs:
        return
    kwargs["updated_at"] = _now()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    get_db().execute(f"UPDATE jobs SET {fields} WHERE id = ?", values)
    global _last_commit_time
    now = time.monotonic()
    if force_commit or "status" in kwargs or (now - _last_commit_time) >= _COMMIT_INTERVAL:
        get_db().commit()
        _last_commit_time = now


def get_job(job_id: str) -> Optional[IngestJob]:
    row = get_db().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs() -> list[IngestJob]:
    rows = get_db().execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_job(r) for r in rows]


def find_completed_snapshot(repo_url: str, commit_sha: str) -> Optional[IngestJob]:
    normalized = repo_url.removesuffix(".git").rstrip("/")
    rows = get_db().execute(
        "SELECT * FROM jobs WHERE status='complete' AND commit_sha=? ORDER BY created_at DESC",
        (commit_sha,),
    ).fetchall()
    for row in rows:
        if row["repo_url"].removesuffix(".git").rstrip("/") == normalized:
            return _row_to_job(row)
    return None


def claim_public_snapshot(repo_url: str, commit_sha: str, job_id: str) -> tuple[bool, str]:
    """Atomically claim an index key, or return the job already building it."""
    normalized = repo_url.removesuffix(".git").rstrip("/")
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        "INSERT OR IGNORE INTO public_snapshot_cache(repo_url,commit_sha,job_id) VALUES(?,?,?)",
        (normalized, commit_sha, job_id),
    )
    row = db.execute(
        "SELECT job_id FROM public_snapshot_cache WHERE repo_url=? AND commit_sha=?",
        (normalized, commit_sha),
    ).fetchone()
    current_id = row["job_id"]
    if current_id != job_id:
        current = get_job(current_id)
        if not current or current.status == "failed":
            db.execute(
                "UPDATE public_snapshot_cache SET job_id=? WHERE repo_url=? AND commit_sha=?",
                (job_id, normalized, commit_sha),
            )
            current_id = job_id
    db.commit()
    return current_id == job_id, current_id


def delete_job(job_id: str) -> bool:
    """
    Delete a job and all its data (CASCADE handles files/symbols/edges).
    Returns True if deleted, False if not found.
    """
    cur = get_db().execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    get_db().commit()
    deleted = cur.rowcount > 0
    if deleted:
        _log(f"Deleted job {job_id}")
    return deleted


def _row_to_job(row: sqlite3.Row) -> IngestJob:
    return IngestJob(
        id=row["id"], repo_url=row["repo_url"], repo_name=row["repo_name"],
        branch=row["branch"], status=row["status"], progress=row["progress"],
        files_processed=row["files_processed"], files_total=row["files_total"],
        tokens_estimate=row["tokens_estimate"], commit_sha=row["commit_sha"],
        clone_path=row["clone_path"], error_message=row["error_message"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ── Bulk Insert ───────────────────────────────────────────────────────────────

def insert_parsed_file(job_id: str, f: ParsedFile) -> None:
    now = _now()
    get_db().execute(
        """INSERT INTO parsed_files
           (job_id, file_path, language, line_count, size_bytes, ast_json, raw_content, content_hash, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(job_id, file_path) DO UPDATE SET
             language=excluded.language, line_count=excluded.line_count,
             size_bytes=excluded.size_bytes, ast_json=excluded.ast_json,
             raw_content=excluded.raw_content, content_hash=excluded.content_hash,
             created_at=excluded.created_at""",
        (job_id, f.file_path, f.language, f.line_count, f.size_bytes,
         f.ast_json, f.raw_content, f.content_hash, now),
    )


def insert_symbols(job_id: str, symbols: list[SymbolRecord]) -> None:
    now = _now()
    get_db().executemany(
        """INSERT INTO symbols
           (job_id, file_path, symbol_name, symbol_type, start_line, end_line, signature, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(job_id, s.file_path, s.symbol_name, s.symbol_type,
          s.start_line, s.end_line, s.signature, now) for s in symbols],
    )


def insert_edges(job_id: str, edges: list[EdgeRecord]) -> None:
    now = _now()
    get_db().executemany(
        """INSERT INTO edges
           (job_id, source_file, target_file, target_module, edge_type, line, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        [(job_id, e.source_file, e.target_file, e.target_module, e.edge_type, e.line, now)
         for e in edges],
    )


def commit_batch() -> None:
    get_db().commit()


def get_semantic_sources(job_id: str) -> list[dict]:
    """Return stored file contents for optional embedding generation."""
    rows = get_db().execute(
        "SELECT file_path, raw_content FROM parsed_files WHERE job_id=? AND raw_content IS NOT NULL ORDER BY file_path",
        (job_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def replace_semantic_chunks(job_id: str, model: str, chunks: list[dict]) -> None:
    """Atomically replace one job's semantic index for a specific embedding model."""
    db = get_db()
    db.execute("DELETE FROM semantic_chunks WHERE job_id=? AND model=?", (job_id, model))
    db.executemany(
        "INSERT INTO semantic_chunks(job_id,file_path,start_line,end_line,model,content,embedding_json) VALUES(?,?,?,?,?,?,?)",
        [(job_id, c["file_path"], c["start_line"], c["end_line"], model, c["content"], c["embedding_json"])
         for c in chunks],
    )
    db.commit()


def get_semantic_chunks(job_id: str, model: str) -> list[dict]:
    rows = get_db().execute(
        "SELECT file_path,start_line,end_line,content,embedding_json FROM semantic_chunks WHERE job_id=? AND model=?",
        (job_id, model),
    ).fetchall()
    return [dict(row) for row in rows]


def copy_unchanged_files(base_job_id: str, job_id: str, current_hashes: dict[str, str]) -> set[str]:
    """Copy unchanged indexed rows into a new commit snapshot and return reused paths."""
    db = get_db()
    reusable = {
        row["file_path"] for row in db.execute(
            "SELECT file_path, content_hash FROM parsed_files WHERE job_id=?", (base_job_id,)
        )
        if row["content_hash"] and current_hashes.get(row["file_path"]) == row["content_hash"]
    }
    for path in sorted(reusable):
        row = db.execute(
            "SELECT language,line_count,size_bytes,ast_json,raw_content,content_hash,created_at "
            "FROM parsed_files WHERE job_id=? AND file_path=?", (base_job_id, path)
        ).fetchone()
        db.execute(
            "INSERT INTO parsed_files(job_id,file_path,language,line_count,size_bytes,ast_json,raw_content,content_hash,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (job_id, path, row["language"], row["line_count"], row["size_bytes"],
             row["ast_json"], row["raw_content"], row["content_hash"], row["created_at"]),
        )
        db.execute(
            "INSERT INTO symbols(job_id,file_path,symbol_name,symbol_type,start_line,end_line,signature,created_at) "
            "SELECT ?,file_path,symbol_name,symbol_type,start_line,end_line,signature,created_at "
            "FROM symbols WHERE job_id=? AND file_path=?", (job_id, base_job_id, path),
        )
        db.execute(
            "INSERT INTO edges(job_id,source_file,target_file,target_module,edge_type,line,created_at) "
            "SELECT ?,source_file,target_file,target_module,edge_type,line,created_at "
            "FROM edges WHERE job_id=? AND source_file=?", (job_id, base_job_id, path),
        )
        db.execute(
            "INSERT INTO calls(job_id,caller_file,caller_function,callee_name,line,created_at) "
            "SELECT ?,caller_file,caller_function,callee_name,line,created_at "
            "FROM calls WHERE job_id=? AND caller_file=?", (job_id, base_job_id, path),
        )
    db.execute(
        "DELETE FROM edges WHERE job_id=? AND target_file IS NOT NULL "
        "AND target_file NOT IN (SELECT file_path FROM parsed_files WHERE job_id=?)",
        (job_id, job_id),
    )
    db.commit()
    return reusable


def token_estimate(job_id: str) -> int:
    row = get_db().execute(
        "SELECT COALESCE(SUM(CASE WHEN ast_json IS NOT NULL THEN length(ast_json) ELSE size_bytes END),0) AS n "
        "FROM parsed_files WHERE job_id=?", (job_id,)
    ).fetchone()
    return int(row["n"] // 4)


# ── Search ────────────────────────────────────────────────────────────────────

def search_content(
    job_id: str,
    query: str,
    limit: int = 20,
) -> list[dict]:
    """
    Full-text search across raw_content of all indexed files.
    Returns list of {file_path, language, line, snippet} dicts.
    """
    results = []
    terms = [term.replace('"', '""') for term in query.split() if term]
    if not terms:
        return results
    match_query = " AND ".join(f'"{term}"' for term in terms)
    rows = get_db().execute(
        "SELECT p.file_path, p.language, p.raw_content, bm25(parsed_files_fts) AS rank "
        "FROM parsed_files_fts JOIN parsed_files p ON p.id=parsed_files_fts.rowid "
        "WHERE parsed_files_fts MATCH ? AND p.job_id=? "
        "ORDER BY rank, p.file_path LIMIT ?",
        (match_query, job_id, max(limit * 10, limit)),
    ).fetchall()
    query_lower = query.lower()
    for row in rows:
        for i, line in enumerate((row["raw_content"] or "").splitlines(), 1):
            if query_lower in line.lower() or all(t.lower() in line.lower() for t in query.split()):
                results.append({"file_path": row["file_path"], "language": row["language"],
                                "line": i, "snippet": line.strip(), "rank": row["rank"]})
                if len(results) >= limit:
                    return results
    return results


# ── Call Graph ────────────────────────────────────────────────────────────────

def insert_calls(job_id: str, calls: list[CallRecord]) -> None:
    """Bulk insert call records for a file."""
    if not calls:
        return
    now = _now()
    get_db().executemany(
        """INSERT INTO calls
           (job_id, caller_file, caller_function, callee_name, line, created_at)
           VALUES (?,?,?,?,?,?)""",
        [(job_id, c.caller_file, c.caller_function, c.callee_name, c.line, now)
         for c in calls],
    )


def get_callers(job_id: str, function_name: str, limit: int = 50) -> list[dict]:
    """
    Find all call sites that call `function_name`.
    Returns: [{caller_file, caller_function, callee_name, line}]
    """
    rows = get_db().execute(
        """SELECT caller_file, caller_function, callee_name, line
           FROM calls
           WHERE job_id = ? AND callee_name = ?
           ORDER BY caller_file, line
           LIMIT ?""",
        (job_id, function_name, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_callees(job_id: str, function_name: str, limit: int = 50) -> list[dict]:
    """
    Find all functions called by `function_name`.
    Returns: [{caller_file, caller_function, callee_name, line}]
    """
    rows = get_db().execute(
        """SELECT caller_file, caller_function, callee_name, line
           FROM calls
           WHERE job_id = ? AND caller_function = ?
           ORDER BY line
           LIMIT ?""",
        (job_id, function_name, limit),
    ).fetchall()
    return [dict(r) for r in rows]
