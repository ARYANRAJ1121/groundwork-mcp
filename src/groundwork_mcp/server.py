"""
Groundwork MCP Server — FastMCP implementation.

10 tools:
  ingest_repo          — clone + index a GitHub repo (async, returns job_id)
  get_ingest_status    — poll job progress
  list_ingested_repos  — list all indexed repos
  get_repo_summary     — high-level map of a repo (languages, symbols, deps)
  query_symbols        — search symbols by name / type / file
  get_import_edges     — get import dependency edges for a file
  get_file_content     — read raw content of any indexed file (README, JSON, source)
  list_repo_files      — list all indexed files with language, size, line count
  delete_repo          — permanently remove a repo from the index
  search_code          — full-text search across all indexed file content
"""

import asyncio
import sys
import uuid
from typing import Optional

from fastmcp import FastMCP

from .database import (
    init_database, close_database,
    create_job, get_job, list_jobs, delete_job,
    search_content,
)
from .pipeline import run_pipeline
from .security import validate_repo_url, extract_repo_name

# ── Server ────────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="groundwork-mcp",
    instructions=(
        "Groundwork indexes GitHub repositories locally. "
        "IMPORTANT RULES:\n"
        "1. NEVER answer questions about an ingested repo from memory or training data. "
        "Always use the Groundwork tools to retrieve facts from the local index.\n"
        "2. When asked 'what is this project about?' — call get_file_content(job_id, 'README.md') first.\n"
        "3. When asked about code structure — call get_repo_summary(job_id) first.\n"
        "4. When asked where a symbol is defined — call query_symbols(job_id, name=...).\n"
        "5. When asked about imports or dependencies — call get_import_edges(job_id, file_path=...).\n"
        "Workflow: ingest_repo → get_ingest_status (poll until complete) → "
        "get_file_content / get_repo_summary / query_symbols / get_import_edges."
    ),
)

# ── Tool 1: ingest_repo ───────────────────────────────────────────────────────

@mcp.tool()
async def ingest_repo(repo_url: str, branch: str = "") -> str:
    """
    Clone a public GitHub repository and build a citation-grounded knowledge base.

    Returns a job_id immediately. Ingestion runs in the background.
    Poll get_ingest_status(job_id) to track progress.
    When status='complete', use query_symbols / get_import_edges / get_repo_summary.

    Args:
        repo_url: Full HTTPS GitHub URL — e.g. https://github.com/owner/repo
        branch: Branch to clone (leave empty for the repo's default branch)
    """
    valid, error = validate_repo_url(repo_url)
    if not valid:
        return f"Error: {error}\nHint: URL must be https://github.com/<owner>/<repo>"

    job_id = str(uuid.uuid4())
    repo_name = extract_repo_name(repo_url)
    branch_val = branch.strip() or None

    create_job(job_id, repo_url, repo_name, branch_val or "default")

    # Fire-and-forget — do not await
    asyncio.create_task(run_pipeline(job_id, repo_url, branch_val))

    return (
        f"Ingestion started!\n"
        f"  job_id:    {job_id}\n"
        f"  repo:      {repo_name}\n"
        f"  branch:    {branch_val or 'default'}\n\n"
        f"Poll get_ingest_status('{job_id}') to track progress."
    )


# ── Tool 2: get_ingest_status ─────────────────────────────────────────────────

@mcp.tool()
def get_ingest_status(job_id: str) -> str:
    """
    Check the live status and progress of a repository ingestion job.

    Status values: queued → cloning → sieving → parsing → complete | failed

    Args:
        job_id: The job_id returned by ingest_repo
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}\nUse list_ingested_repos() to see all known job IDs."

    pct = int(job.progress * 100)
    status_lines = {
        "queued":   "Queued — will start shortly.",
        "cloning":  "Cloning repository from GitHub...",
        "sieving":  "Filtering source files...",
        "parsing":  f"Parsing files — {job.files_processed}/{job.files_total} done ({pct}%)",
        "complete": f"Complete! {job.files_processed} files, ~{job.tokens_estimate:,} tokens indexed.",
        "failed":   f"Failed: {job.error_message}",
    }

    lines = [
        f"Job:      {job.id}",
        f"Repo:     {job.repo_name}  ({job.repo_url})",
        f"Status:   {job.status}",
        f"Progress: {pct}%",
        f"Files:    {job.files_processed}/{job.files_total}",
        f"Tokens:   ~{job.tokens_estimate:,}",
        f"Updated:  {job.updated_at}",
        "",
        status_lines.get(job.status, job.status),
    ]
    if job.commit_sha:
        lines.insert(3, f"Commit:   {job.commit_sha[:8]}")
    if job.error_message and job.status != "failed":
        lines.append(f"Warning:  {job.error_message}")

    return "\n".join(lines)


# ── Tool 3: list_ingested_repos ───────────────────────────────────────────────

@mcp.tool()
def list_ingested_repos() -> str:
    """
    List all repositories that have been ingested into the local knowledge base.
    Shows job IDs, status, file counts, and timestamps.
    Use the job_id from a previous session to resume exploring a repo.
    """
    jobs = list_jobs()
    if not jobs:
        return "No repositories ingested yet.\nUse ingest_repo(repo_url) to get started."

    complete = [j for j in jobs if j.status == "complete"]
    in_progress = [j for j in jobs if j.status not in ("complete", "failed")]

    lines = [
        f"Total repos: {len(jobs)}  |  Complete: {len(complete)}  |  In progress: {len(in_progress)}",
        "",
    ]
    for j in jobs:
        lines.append(
            f"[{j.status.upper():8}] {j.repo_name}"
            f"\n           job_id: {j.id}"
            f"\n           files:  {j.files_processed}  |  tokens: ~{j.tokens_estimate:,}"
            f"\n           date:   {j.created_at[:10]}"
            + (f"\n           error:  {j.error_message}" if j.error_message else "")
        )

    return "\n".join(lines)


# ── Tool 4: get_repo_summary ──────────────────────────────────────────────────

@mcp.tool()
def get_repo_summary(job_id: str) -> str:
    """
    Get a high-level structural map of an ingested repository.
    Returns: file breakdown by language, symbol type counts,
    most-imported files, external dependencies, richest files.
    Call this first when exploring a new codebase.

    Args:
        job_id: The job_id from ingest_repo or list_ingested_repos
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}"
    if job.status != "complete":
        return f"Job not complete yet (status: {job.status}). Wait for ingestion to finish."

    from .database import get_db
    db = get_db()

    # Files by language
    lang_rows = db.execute(
        "SELECT language, COUNT(*) c, SUM(line_count) l, SUM(size_bytes) b "
        "FROM parsed_files WHERE job_id=? GROUP BY language ORDER BY c DESC", (job_id,)
    ).fetchall()

    # Symbol type distribution
    sym_rows = db.execute(
        "SELECT symbol_type, COUNT(*) c FROM symbols WHERE job_id=? GROUP BY symbol_type ORDER BY c DESC",
        (job_id,)
    ).fetchall()

    # Most-imported files
    imported_rows = db.execute(
        "SELECT target_file, COUNT(*) c FROM edges WHERE job_id=? AND target_file IS NOT NULL "
        "GROUP BY target_file ORDER BY c DESC LIMIT 8", (job_id,)
    ).fetchall()

    # Top external deps
    ext_rows = db.execute(
        "SELECT target_module, COUNT(*) c FROM edges WHERE job_id=? AND target_file IS NULL "
        "GROUP BY target_module ORDER BY c DESC LIMIT 10", (job_id,)
    ).fetchall()

    # Richest files by symbol count
    rich_rows = db.execute(
        "SELECT file_path, COUNT(*) c FROM symbols WHERE job_id=? GROUP BY file_path ORDER BY c DESC LIMIT 8",
        (job_id,)
    ).fetchall()

    lines = [
        f"=== {job.repo_name} ===",
        f"Commit: {(job.commit_sha or 'unknown')[:8]}  |  Files: {job.files_processed}  |  ~{job.tokens_estimate:,} tokens",
        "",
        "── Files by language ──",
        *[f"  {r['language']:12} {r['c']:4} files  {r['l'] or 0:6,} lines  {(r['b'] or 0)//1024:4}KB" for r in lang_rows],
        "",
        "── Symbol types ──",
        *[f"  {r['symbol_type']:14} {r['c']:4}" for r in sym_rows],
        "",
    ]
    if imported_rows:
        lines += ["── Most-imported files ──",
                  *[f"  {r['target_file']}  (imported by {r['c']} files)" for r in imported_rows],
                  ""]
    if ext_rows:
        lines += ["── External dependencies ──",
                  *[f"  {r['target_module']}  ({r['c']}x)" for r in ext_rows],
                  ""]
    if rich_rows:
        lines += ["── Richest files (by symbol count) ──",
                  *[f"  {r['file_path']}  ({r['c']} symbols)" for r in rich_rows]]

    return "\n".join(lines)


# ── Tool 5: query_symbols ─────────────────────────────────────────────────────

@mcp.tool()
def query_symbols(
    job_id: str,
    name: str = "",
    symbol_type: str = "",
    file_path: str = "",
    limit: int = 50,
) -> str:
    """
    Search the indexed knowledge base for symbols (functions, classes, types, etc.).
    Supports partial name match and filtering by type or file.
    Use this to answer: 'where is X defined?', 'list all classes', 'what's in file Y?'

    Args:
        job_id:      The job_id from ingest_repo or list_ingested_repos
        name:        Symbol name to search (partial, case-insensitive)
        symbol_type: Filter by type: function | class | method | variable | interface | type_alias | enum | export
        file_path:   Filter to a specific file (partial path match)
        limit:       Max results (default 50, max 200)
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}"
    if job.status != "complete":
        return f"Job not complete (status: {job.status})"

    from .database import get_db
    db = get_db()
    limit = min(max(1, limit), 200)

    conditions = ["job_id = ?"]
    params: list = [job_id]
    if name:
        conditions.append("LOWER(symbol_name) LIKE LOWER(?)")
        params.append(f"%{name}%")
    if symbol_type:
        conditions.append("symbol_type = ?")
        params.append(symbol_type)
    if file_path:
        conditions.append("file_path LIKE ?")
        params.append(f"%{file_path}%")
    params.append(limit)

    rows = db.execute(
        f"SELECT symbol_name, symbol_type, file_path, start_line, end_line, signature "
        f"FROM symbols WHERE {' AND '.join(conditions)} ORDER BY file_path, start_line LIMIT ?",
        params,
    ).fetchall()

    if not rows:
        return f"No symbols found matching: name={name!r} type={symbol_type!r} file={file_path!r}"

    lines = [f"Found {len(rows)} symbol(s) in {job.repo_name}:", ""]
    for r in rows:
        sig = f"  → {r['signature']}" if r['signature'] else ""
        lines.append(
            f"[{r['symbol_type']:12}] {r['symbol_name']}\n"
            f"               {r['file_path']}:{r['start_line']}–{r['end_line']}{sig}"
        )

    return "\n".join(lines)


# ── Tool 6: get_import_edges ──────────────────────────────────────────────────

@mcp.tool()
def get_import_edges(
    job_id: str,
    file_path: str = "",
    direction: str = "outgoing",
) -> str:
    """
    Get import/dependency edges for a file or the entire repo.
    Direction 'outgoing': what does this file import?
    Direction 'incoming': what files import this file?
    Direction 'both':     all edges.

    Args:
        job_id:    The job_id from ingest_repo or list_ingested_repos
        file_path: File to query (partial path match). Leave empty for all files.
        direction: 'outgoing' | 'incoming' | 'both'  (default: outgoing)
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}"
    if job.status != "complete":
        return f"Job not complete (status: {job.status})"

    from .database import get_db
    db = get_db()

    rows = []
    if direction in ("outgoing", "both"):
        q = "SELECT source_file, target_file, target_module, edge_type FROM edges WHERE job_id=?"
        p: list = [job_id]
        if file_path:
            q += " AND source_file LIKE ?"
            p.append(f"%{file_path}%")
        q += " ORDER BY source_file, target_module LIMIT 500"
        rows += db.execute(q, p).fetchall()

    if direction in ("incoming", "both"):
        if not file_path:
            return "file_path is required when direction='incoming'"
        rows += db.execute(
            "SELECT source_file, target_file, target_module, edge_type FROM edges "
            "WHERE job_id=? AND target_file LIKE ? ORDER BY source_file LIMIT 500",
            (job_id, f"%{file_path}%"),
        ).fetchall()

    if not rows:
        return f"No import edges found for file_path={file_path!r} direction={direction!r}"

    # Group by source file
    by_source: dict[str, list[str]] = {}
    for r in rows:
        src = r["source_file"]
        if src not in by_source:
            by_source[src] = []
        target = r["target_file"] or f"<external: {r['target_module']}>"
        by_source[src].append(f"  → {target}  ({r['edge_type']})")

    lines = [f"Import edges in {job.repo_name}  [direction={direction}]", ""]
    for src, targets in sorted(by_source.items()):
        lines.append(src)
        lines.extend(targets)
        lines.append("")

    return "\n".join(lines)


# ── Tool 7: get_file_content ─────────────────────────────────────────────────

@mcp.tool()
def get_file_content(job_id: str, file_path: str) -> str:
    """
    Read the full content of any indexed file from the local knowledge base.
    Works for ALL file types: README.md, source code, JSON configs, YAML, TOML, etc.
    Use this to answer 'what does this file say/do?' or 'show me the README'.
    ALWAYS call this instead of fetching from GitHub.

    Args:
        job_id:    The job_id from ingest_repo or list_ingested_repos
        file_path: File path within the repo (partial match OK, e.g. 'README.md', 'src/main.py')
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}"
    if job.status != "complete":
        return f"Job not complete (status: {job.status})"

    from .database import get_db
    db = get_db()

    # Try exact match first, then partial
    row = db.execute(
        "SELECT file_path, language, line_count, size_bytes, raw_content, ast_json "
        "FROM parsed_files WHERE job_id=? AND file_path=? LIMIT 1",
        (job_id, file_path),
    ).fetchone()

    if not row:
        # Partial match
        row = db.execute(
            "SELECT file_path, language, line_count, size_bytes, raw_content, ast_json "
            "FROM parsed_files WHERE job_id=? AND file_path LIKE ? LIMIT 1",
            (job_id, f"%{file_path}%"),
        ).fetchone()

    if not row:
        # List available files to help
        files = db.execute(
            "SELECT file_path FROM parsed_files WHERE job_id=? ORDER BY file_path LIMIT 40",
            (job_id,),
        ).fetchall()
        file_list = "\n".join(f"  {r['file_path']}" for r in files)
        return (
            f"File not found: {file_path!r}\n"
            f"Available files in {job.repo_name}:\n{file_list}"
        )

    # Prefer raw_content (new index); fall back to ast_json for markdown (old index)
    content = row["raw_content"] or row["ast_json"]
    lang = row["language"]
    lines = row["line_count"]
    size = row["size_bytes"]

    if not content:
        return (
            f"File: {row['file_path']} ({lang}, {lines} lines, {size} bytes)\n"
            f"[No content stored — re-ingest the repo to populate file content]"
        )

    header = f"File: {row['file_path']} ({lang}, {lines} lines)\n" + "-" * 60 + "\n"
    return header + content


# ── Tool 8: list_repo_files ───────────────────────────────────────────────

@mcp.tool()
def list_repo_files(
    job_id: str,
    language: str = "",
    path_filter: str = "",
) -> str:
    """
    List all files indexed for a repository, with language, size, and line count.
    Use this to explore what files exist before calling get_file_content.
    Optionally filter by language (python, typescript, markdown, etc.) or path substring.

    Args:
        job_id:      The job_id from ingest_repo or list_ingested_repos
        language:    Filter by language (python | typescript | javascript | markdown | json | yaml | toml)
        path_filter: Filter to files whose path contains this string
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}"
    if job.status != "complete":
        return f"Job not complete (status: {job.status})"

    from .database import get_db
    db = get_db()

    conditions = ["job_id = ?"]
    params: list = [job_id]
    if language:
        conditions.append("language = ?")
        params.append(language)
    if path_filter:
        conditions.append("file_path LIKE ?")
        params.append(f"%{path_filter}%")

    rows = db.execute(
        f"SELECT file_path, language, line_count, size_bytes "
        f"FROM parsed_files WHERE {' AND '.join(conditions)} "
        f"ORDER BY file_path",
        params,
    ).fetchall()

    if not rows:
        return f"No files found matching language={language!r} path={path_filter!r}"

    # Group by directory
    lines = [f"{len(rows)} files in {job.repo_name}:", ""]
    current_dir = ""
    for r in rows:
        parts = r["file_path"].rsplit("/", 1)
        dir_part = parts[0] if len(parts) > 1 else "."
        if dir_part != current_dir:
            current_dir = dir_part
            lines.append(f"  {dir_part}/")
        fname = parts[-1]
        lines.append(
            f"    {fname:40}  {r['language']:12}  {r['line_count']:5} lines  {r['size_bytes']//1024 or 1}KB"
        )
    return "\n".join(lines)


# ── Tool 9: delete_repo ───────────────────────────────────────────────────

@mcp.tool()
def delete_repo(job_id: str) -> str:
    """
    Permanently delete a repository from the local knowledge base.
    Removes all indexed files, symbols, and edges for this job.
    Use this to free space or force a clean re-ingest.

    Args:
        job_id: The job_id from list_ingested_repos
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}. Use list_ingested_repos() to see all job IDs."

    deleted = delete_job(job_id)
    if deleted:
        return (
            f"Deleted: {job.repo_name} ({job_id})\n"
            f"All indexed files, symbols, and edges removed.\n"
            f"Run ingest_repo('{job.repo_url}') to re-index."
        )
    return f"Delete failed for {job_id}"


# ── Tool 10: search_code ───────────────────────────────────────────────────

@mcp.tool()
def search_code(job_id: str, query: str, limit: int = 20) -> str:
    """
    Full-text search across all indexed file content in a repository.
    Returns matching lines with file path and line number.
    Use this to find: config values, string literals, comments, variable names,
    error messages, or any text that isn't a symbol definition.

    Args:
        job_id: The job_id from ingest_repo or list_ingested_repos
        query:  Text to search for (case-insensitive)
        limit:  Max results to return (default 20, max 100)
    """
    job = get_job(job_id)
    if not job:
        return f"Job not found: {job_id}"
    if job.status != "complete":
        return f"Job not complete (status: {job.status})"

    limit = min(max(1, limit), 100)
    hits = search_content(job_id, query, limit)

    if not hits:
        return f"No results for {query!r} in {job.repo_name}"

    lines = [f"{len(hits)} result(s) for {query!r} in {job.repo_name}:", ""]
    current_file = ""
    for h in hits:
        if h["file_path"] != current_file:
            current_file = h["file_path"]
            lines.append(f"  {current_file}")
        lines.append(f"    L{h['line']:4}: {h['snippet']}")

    return "\n".join(lines)



def main() -> None:
    init_database()
    mcp.run()


if __name__ == "__main__":
    main()
