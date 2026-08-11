"""Groundwork MCP — Git cloner (subprocess, works reliably on Windows)."""

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .security import validate_repo_url, extract_repo_name
from .types import CloneResult


def clone_repo(repo_url: str, job_id: str, branch: str | None = None) -> CloneResult:
    """
    Shallow-clone a GitHub repo into an isolated job directory.
    Uses subprocess directly for reliable cross-platform timeout support.
    """
    valid, error = validate_repo_url(repo_url)
    if not valid:
        raise ValueError(f"Invalid repo URL: {error}")

    repo_name = extract_repo_name(repo_url)
    clone_path = config.REPOS_DIR / job_id

    # Remove any stale clone
    if clone_path.exists():
        _rmtree(clone_path)

    _log(f"Cloning {repo_url} (branch: {branch or 'default'}) → {clone_path}")

    # Build git clone command
    cmd = [
        "git", "clone",
        "--depth", "1",
        "--single-branch",
        "--no-tags",
    ]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, str(clone_path)]

    # Prevent git from hanging on credential prompts for public repos
    git_env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",   # Never prompt for credentials
        "GIT_ASKPASS": "echo",         # Return empty string if asked for password
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
    }

    max_attempts = 3
    last_error: Exception = RuntimeError("Unknown error")

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            wait = 2 ** (attempt - 2)  # 1s, 2s
            _log(f"Retry {attempt}/{max_attempts} in {wait}s...")
            time.sleep(wait)

        try:
            result = subprocess.run(
                cmd,
                timeout=config.CLONE_TIMEOUT_SECONDS,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env=git_env,
            )
        except subprocess.TimeoutExpired:
            if clone_path.exists():
                _rmtree(clone_path)
            raise TimeoutError(
                f"Clone timed out after {config.CLONE_TIMEOUT_SECONDS}s. "
                "Repository may be too large or network is slow."
            )
        except FileNotFoundError:
            raise RuntimeError(
                "git not found on PATH. Install git: https://git-scm.com/downloads"
            )

        if result.returncode == 0:
            break

        stderr = result.stderr.lower()
        # Non-retryable: repo not found, bad URL
        if "not found" in stderr or "does not exist" in stderr or "repository" in stderr:
            if clone_path.exists():
                _rmtree(clone_path)
            raise ValueError(
                f"Repository not found: {repo_url}. "
                "Ensure the URL is correct and the repo is public."
            )

        last_error = RuntimeError(f"Clone failed (exit {result.returncode}): {result.stderr.strip()}")
        _log(f"Attempt {attempt} failed: {result.stderr.strip()[:100]}")
        if clone_path.exists():
            _rmtree(clone_path)
    else:
        raise last_error

    # Get the HEAD commit SHA
    try:
        sha_result = subprocess.run(
            ["git", "-C", str(clone_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        commit_sha = sha_result.stdout.strip() or "unknown"
    except Exception:
        commit_sha = "unknown"

    _log(f"Clone complete: {repo_name} @ {commit_sha[:8]}")
    return CloneResult(
        clone_path=str(clone_path),
        commit_sha=commit_sha,
        repo_name=repo_name,
    )


def remove_clone(job_id: str) -> None:
    """Remove a cloned repository from disk."""
    clone_path = config.REPOS_DIR / job_id
    if clone_path.exists():
        _rmtree(clone_path)
        _log(f"Removed clone: {clone_path}")


def _rmtree(path: Path) -> None:
    """
    Cross-platform rmtree that handles Windows read-only files.
    Git marks some objects as read-only; shutil.rmtree fails without this.
    """
    def _on_error(func, path, exc_info):
        # Make read-only files writable and retry
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass  # Best effort

    shutil.rmtree(str(path), onerror=_on_error)


def _log(msg: str) -> None:
    print(f"[cloner] {msg}", file=sys.stderr)
