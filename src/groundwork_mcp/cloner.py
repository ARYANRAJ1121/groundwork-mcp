"""Groundwork MCP — safe, commit-pinned GitHub tarball downloader."""

import os
import json
import shutil
import stat
import tarfile
import sys
import urllib.request
import urllib.error
import urllib.parse
import io
from pathlib import Path

from . import config
from .security import validate_repo_url, extract_repo_name
from .types import CloneResult


def clone_repo(repo_url: str, job_id: str, branch: str | None = None) -> CloneResult:
    """
    Download and safely unpack a GitHub source archive at an exact commit.
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

    owner, repo = repo_name.split("/", 1)
    headers = _github_headers()
    api = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=config.CLONE_TIMEOUT_SECONDS) as response:
            metadata = json.load(response)
        ref = branch or metadata["default_branch"]
        commit_sha = _resolve_commit(api, ref, headers)
        archive_url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{commit_sha}"
        with urllib.request.urlopen(urllib.request.Request(archive_url, headers=headers), timeout=config.CLONE_TIMEOUT_SECONDS) as response:
            archive = response.read(config.MAX_REPO_SIZE_MB * 1024 * 1024 + 1)
            if len(archive) > config.MAX_REPO_SIZE_MB * 1024 * 1024:
                raise RuntimeError(f"Compressed repository archive exceeds {config.MAX_REPO_SIZE_MB}MB")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 422):
            raise ValueError(f"Repository or branch not found or is private: {repo_url}") from exc
        raise RuntimeError(f"GitHub download failed (HTTP {exc.code})") from exc
    except TimeoutError as exc:
        raise TimeoutError(f"GitHub tarball download timed out after {config.CLONE_TIMEOUT_SECONDS}s") from exc

    clone_path.mkdir(parents=True, exist_ok=True)
    # Extract each member under a single stripped archive root; reject links/traversal.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        members = tf.getmembers()
        if len(members) > config.MAX_FILE_COUNT * 4:
            raise RuntimeError("Repository archive contains too many entries")
        if sum(m.size for m in members if m.isfile()) > config.MAX_REPO_SIZE_MB * 1024 * 1024:
            raise RuntimeError(f"Repository exceeds size limit ({config.MAX_REPO_SIZE_MB}MB)")
        if any(m.isfile() and m.size > config.MAX_SINGLE_FILE_KB * 1024 for m in members):
            # Oversized files are normally skipped by the sieve, so leave them out here too.
            members = [m for m in members if not (m.isfile() and m.size > config.MAX_SINGLE_FILE_KB * 1024)]
        roots = {m.name.split("/", 1)[0] for m in members if m.name}
        if len(roots) != 1:
            raise RuntimeError("Unexpected GitHub archive structure")
        for member in members:
            relative = member.name.split("/", 1)[-1]
            if not relative:
                continue
            target = (clone_path / relative).resolve()
            if not target.is_relative_to(clone_path.resolve()) or not (member.isdir() or member.isfile()):
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(member)
                if source:
                    with source, target.open("wb") as out:
                        shutil.copyfileobj(source, out)

    _log(f"Clone complete: {repo_name} @ {commit_sha[:8]}")
    return CloneResult(
        clone_path=str(clone_path),
        commit_sha=commit_sha,
        repo_name=repo_name,
    )


def resolve_remote_commit(repo_url: str, branch: str | None = None) -> str:
    """Resolve the current branch tip using the GitHub API."""
    owner, repo = extract_repo_name(repo_url).split("/", 1)
    api = f"https://api.github.com/repos/{owner}/{repo}"
    headers = _github_headers()
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=config.CLONE_TIMEOUT_SECONDS) as response:
            metadata = json.load(response)
        return _resolve_commit(api, branch or metadata["default_branch"], headers)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 422):
            raise ValueError(f"Repository or branch not found or is private: {repo_url}") from exc
        raise RuntimeError(f"GitHub API failed (HTTP {exc.code})") from exc


def _resolve_commit(api: str, ref: str, headers: dict[str, str]) -> str:
    with urllib.request.urlopen(urllib.request.Request(
        f"{api}/commits/{urllib.parse.quote(ref, safe='')}", headers=headers
    ), timeout=config.CLONE_TIMEOUT_SECONDS) as response:
        return json.load(response)["sha"]


def _github_headers() -> dict[str, str]:
    headers = {"User-Agent": "groundwork-mcp", "Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return headers


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
