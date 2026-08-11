"""Groundwork MCP — SQLite database (Python built-in sqlite3)."""

import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional
from . import config
from .types import IngestJob, ParsedFile, SymbolRecord, EdgeRecord, CallRecord

# ── Connection ────────────────────────────────────────────────────────────────

_conn: Optional[sqlite3.Connection] = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _conn


def init_database() -> None:
    """Initialize SQLite connection, create tables, run migrations."""
    global _conn
    _log(f"Opening database: {config.DB_PATH}")
    _conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.execute("PRAGMA journal_mode = WAL")
    _conn.execute("PRAGMA synchronous = NORMAL")   # WAL+NORMAL = fast & safe
    _conn.execute("PRAGMA cache_size = -32000")    # 32MB page cache
    _conn.executescript(_SCHEMA)
    _migrate(_conn)
    _conn.commit()
    _log("Database ready")


def close_database() -> None:
    global _conn
    if _conn:
        _conn.commit()
        _conn.close()
        _conn = None


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

CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    caller_file TEXT NOT NULL,
    caller_function TEXT NOT NULL,
    callee_name TEXT NOT NULL,
    line INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calls_job    ON calls(job_id);
CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(job_id, callee_name);
CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(job_id, caller_function);
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


def update_job(job_id: str, **kwargs) -> None:
    kwargs["updated_at"] = _now()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    get_db().execute(f"UPDATE jobs SET {fields} WHERE id = ?", values)
    get_db().commit()


def get_job(job_id: str) -> Optional[IngestJob]:
    row = get_db().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs() -> list[IngestJob]:
    rows = get_db().execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_job(r) for r in rows]


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
        """INSERT OR REPLACE INTO parsed_files
           (job_id, file_path, language, line_count, size_bytes, ast_json, raw_content, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (job_id, f.file_path, f.language, f.line_count, f.size_bytes,
         f.ast_json, f.raw_content, now),
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
           (job_id, source_file, target_file, target_module, edge_type, created_at)
           VALUES (?,?,?,?,?,?)""",
        [(job_id, e.source_file, e.target_file, e.target_module, e.edge_type, now)
         for e in edges],
    )


def commit_batch() -> None:
    get_db().commit()


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
    rows = get_db().execute(
        "SELECT file_path, language, raw_content FROM parsed_files "
        "WHERE job_id = ? AND raw_content IS NOT NULL AND raw_content LIKE ? LIMIT 200",
        (job_id, f"%{query}%"),
    ).fetchall()

    query_lower = query.lower()
    for row in rows:
        content = row["raw_content"]
        if not content:
            continue
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            if query_lower in line.lower():
                results.append({
                    "file_path": row["file_path"],
                    "language": row["language"],
                    "line": i,
                    "snippet": line.strip(),
                })
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
