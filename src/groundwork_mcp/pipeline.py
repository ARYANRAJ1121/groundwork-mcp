"""Groundwork MCP — async ingestion pipeline (clone → sieve → parse → store).

Production features:
  - Global semaphore: max 2 concurrent ingestion jobs
  - Auto-cleanup: removes clone directory after parse to save disk
  - All errors captured as failed job state (never crashes the server)
"""

import asyncio
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
)

# Max 2 simultaneous ingestion jobs — prevents overwhelming CPU/disk/network
_semaphore = asyncio.Semaphore(2)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="groundwork-ingest")


async def run_pipeline(job_id: str, repo_url: str, branch: str | None = None) -> None:
    """
    Async ingestion pipeline. Acquires the global semaphore before starting
    so at most 2 jobs run in parallel. Runs CPU-bound work in a thread pool.
    """
    async with _semaphore:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            _executor,
            _run_pipeline_sync,
            job_id, repo_url, branch,
        )


def _run_pipeline_sync(job_id: str, repo_url: str, branch: str | None) -> None:
    """Synchronous pipeline — runs in thread pool executor."""
    _log(f"[{job_id}] Starting ingestion for {repo_url}")
    clone_path: str | None = None

    try:
        # ── Phase 1: Clone ────────────────────────────────────────────
        update_job(job_id, status="cloning", progress=0.05)
        clone = clone_repo(repo_url, job_id, branch)
        clone_path = clone.clone_path
        update_job(job_id,
                   commit_sha=clone.commit_sha,
                   clone_path=clone.clone_path,
                   progress=0.2)
        _log(f"[{job_id}] Clone done @ {clone.commit_sha[:8]}")

        # ── Phase 2: Sieve ────────────────────────────────────────────
        update_job(job_id, status="sieving", progress=0.25)
        sieve = sieve_repo(clone.clone_path)
        update_job(job_id, files_total=sieve.total_files, progress=0.35)
        _log(f"[{job_id}] Sieve done — {sieve.total_files} files")

        # ── Phase 3: Parse ────────────────────────────────────────────
        update_job(job_id, status="parsing", progress=0.4)
        total = sieve.total_files
        processed = 0
        total_tokens = 0

        def on_progress(done: int, tot: int, current: str) -> None:
            nonlocal processed
            processed = done
            progress = 0.4 + (done / tot) * 0.55 if tot else 0.95
            update_job(job_id, files_processed=done, progress=min(progress, 0.95))
            if done % 50 == 0 or done == tot:
                _log(f"[{job_id}] Parsed {done}/{tot} — {current}")

        results = parse_all_files(sieve.files, clone.clone_path, on_progress)

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
                   files_processed=processed,
                   tokens_estimate=total_tokens)
        _log(f"[{job_id}] Complete — {processed} files, ~{total_tokens:,} tokens")

    except Exception as e:
        msg = str(e)
        _log(f"[{job_id}] Failed: {msg}")
        update_job(job_id, status="failed", error_message=msg)

    finally:
        # Always clean up the clone directory — data is in SQLite now
        if clone_path and Path(clone_path).exists():
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


def _log(msg: str) -> None:
    print(f"[pipeline] {msg}", file=sys.stderr)
