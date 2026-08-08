"""Groundwork MCP — Git cloner (gitpython shallow clone)."""

import sys
from pathlib import Path
import git
from . import config
from .security import validate_repo_url, extract_repo_name
from .types import CloneResult


def clone_repo(repo_url: str, job_id: str, branch: str | None = None) -> CloneResult:
    """
    Shallow-clone a GitHub repo into an isolated job directory.
    Uses depth=1 to minimize disk and network usage.
    """
    valid, error = validate_repo_url(repo_url)
    if not valid:
        raise ValueError(f"Invalid repo URL: {error}")

    repo_name = extract_repo_name(repo_url)
    clone_path = config.REPOS_DIR / job_id

    # Remove any stale clone
    if clone_path.exists():
        import shutil
        shutil.rmtree(clone_path)

    _log(f"Cloning {repo_url} (branch: {branch or 'default'}) → {clone_path}")

    clone_kwargs: dict = {
        "depth": 1,
        "single_branch": True,
        "kill_after_timeout": config.CLONE_TIMEOUT_SECONDS,
    }
    if branch:
        clone_kwargs["branch"] = branch

    try:
        repo = git.Repo.clone_from(repo_url, str(clone_path), **clone_kwargs)
        commit_sha = repo.head.commit.hexsha
        _log(f"Clone complete: {repo_name} @ {commit_sha[:8]}")
        return CloneResult(
            clone_path=str(clone_path),
            commit_sha=commit_sha,
            repo_name=repo_name,
        )
    except git.exc.GitCommandError as e:
        # Clean up failed clone
        if clone_path.exists():
            import shutil
            shutil.rmtree(clone_path)
        msg = str(e)
        if "timeout" in msg.lower():
            raise TimeoutError(
                f"Clone timed out after {config.CLONE_TIMEOUT_SECONDS}s. "
                "Repository may be too large."
            )
        if "not found" in msg.lower() or "repository" in msg.lower():
            raise ValueError(
                f"Repository not found: {repo_url}. "
                "Ensure the URL is correct and the repo is public."
            )
        raise RuntimeError(f"Clone failed: {msg}")


def remove_clone(job_id: str) -> None:
    """Remove a cloned repository from disk."""
    import shutil
    clone_path = config.REPOS_DIR / job_id
    if clone_path.exists():
        shutil.rmtree(clone_path)
        _log(f"Removed clone: {clone_path}")


def _log(msg: str) -> None:
    print(f"[cloner] {msg}", file=sys.stderr)
