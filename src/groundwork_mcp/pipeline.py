"""Groundwork MCP — async ingestion pipeline (clone → sieve → parse → store).

Production features:
  - Global semaphore: max 2 concurrent ingestion jobs
  - Auto-cleanup: removes clone directory after parse to save disk
  - All errors captured as failed job state (never crashes the server)
"""

import asyncio
import hashlib
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .cloner import clone_repo
from .sieve import sieve_repo
from .parser import parse_all_files
from .database import (
    update_job, insert_parsed_file, insert_symbols,
    insert_edges, insert_calls, commit_batch,
    copy_unchanged_files, token_estimate,
)

# Max 2 simultaneous ingestion jobs — prevents overwhelming CPU/disk/network
_semaphore = asyncio.Semaphore(2)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="groundwork-ingest")


async def run_pipeline(job_id: str, repo_url: str, branch: str | None = None, incremental_from: str | None = None, local_path: str | None = None) -> None:
    """
    Async ingestion pipeline. Acquires the global semaphore before starting
    so at most 2 jobs run in parallel. Runs CPU-bound work in a thread pool.
    """
    async with _semaphore:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            _executor,
            _run_pipeline_sync,
            job_id, repo_url, branch, incremental_from, local_path,
        )


def _run_pipeline_sync(job_id: str, repo_url: str, branch: str | None, incremental_from: str | None = None, local_path: str | None = None) -> None:
    """Synchronous pipeline — runs in thread pool executor."""
    _log(f"[{job_id}] Starting ingestion for {repo_url}")
    clone_path: str | None = None

    try:
        # ── Phase 1: Clone ────────────────────────────────────────────
        update_job(job_id, status="cloning", progress=0.05)
        if local_path:
            clone = None
            clone_path = local_path
            commit_sha = "pending-local-snapshot"
        else:
            clone = clone_repo(repo_url, job_id, branch)
            clone_path = clone.clone_path
            commit_sha = clone.commit_sha
        update_job(job_id, clone_path=clone_path, progress=0.2)

        # ── Phase 2: Sieve ────────────────────────────────────────────
        update_job(job_id, status="sieving", progress=0.25)
        sieve = sieve_repo(clone_path)
        if local_path:
            commit_sha = _local_snapshot_sha(sieve.files)
        update_job(job_id, commit_sha=commit_sha)
        _log(f"[{job_id}] Source ready @ {commit_sha[:8]}")
        update_job(job_id, files_total=sieve.total_files, progress=0.35)
        _log(f"[{job_id}] Sieve done — {sieve.total_files} files")

        # ── Phase 3: Parse ────────────────────────────────────────────
        update_job(job_id, status="parsing", progress=0.4)
        total = sieve.total_files
        processed = 0
        total_tokens = 0

        files_to_parse = sieve.files
        reused: set[str] = set()
        if incremental_from:
            current_hashes = {
                f.relative_path: hashlib.sha256(Path(f.absolute_path).read_bytes()).hexdigest()
                for f in sieve.files
            }
            reused = copy_unchanged_files(incremental_from, job_id, current_hashes)
            files_to_parse = [f for f in sieve.files if f.relative_path not in reused]
            _log(f"[{job_id}] Reused {len(reused)} unchanged files; parsing {len(files_to_parse)} changed/new files")

        def on_progress(done: int, tot: int, current: str) -> None:
            nonlocal processed
            processed = done
            progress = 0.4 + (done / tot) * 0.55 if tot else 0.95
            if done % 25 == 0 or done == tot:
                update_job(job_id, files_processed=done + len(reused), progress=min(progress, 0.95))
            if done % 50 == 0 or done == tot:
                _log(f"[{job_id}] Parsed {done}/{tot} — {current}")

        results = parse_all_files(files_to_parse, clone_path, on_progress)

        # Store results
        for r in results:
            tokens = len(r.file.ast_json) // 4 if r.file.ast_json else r.file.size_bytes // 4
            total_tokens += tokens
            insert_parsed_file(job_id, r.file)
            if r.symbols:
                insert_symbols(job_id, r.symbols)
            if r.edges:
                insert_edges(job_id, r.edges)
            if r.calls:
                insert_calls(job_id, r.calls)

        commit_batch()

        # ── Phase 4: Complete ─────────────────────────────────────────
        update_job(job_id,
                   status="complete",
                   progress=1.0,
                   files_processed=processed + len(reused),
                   tokens_estimate=token_estimate(job_id))
        _log(f"[{job_id}] Complete — {processed + len(reused)} files, ~{token_estimate(job_id):,} tokens")

    except Exception as e:
        msg = str(e)
        _log(f"[{job_id}] Failed: {msg}")
        update_job(job_id, status="failed", error_message=msg)

    finally:
        # Always clean up the clone directory — data is in SQLite now
        if not local_path and clone_path and Path(clone_path).exists():
            try:
                _rmtree(Path(clone_path))
                _log(f"[{job_id}] Cleaned up clone dir")
            except Exception as e:
                _log(f"[{job_id}] Warning: could not clean clone dir: {e}")


def _rmtree(path: Path) -> None:
    """Windows-safe rmtree — handles git's read-only files."""
    import stat
    def _on_error(func, fpath, exc_info):
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except Exception:
            pass
    shutil.rmtree(str(path), onerror=_on_error)


def _local_snapshot_sha(files) -> str:
    """Hash all regular file paths and bytes without reading Git history."""
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda entry: entry.relative_path):
        try:
            digest.update(item.relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(Path(item.absolute_path).read_bytes())
            digest.update(b"\0")
        except OSError:
            continue
    return digest.hexdigest()


def _log(msg: str) -> None:
    print(f"[pipeline] {msg}", file=sys.stderr)
