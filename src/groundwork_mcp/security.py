"""Groundwork MCP — URL validation and security guardrails."""

import re
import sys
from pathlib import Path
from . import config

# Only HTTPS GitHub URLs allowed — no SSH, no other hosts
GITHUB_URL_RE = re.compile(
    r'^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$'
)

def validate_repo_url(url: str) -> tuple[bool, str]:
    """
    Validate a GitHub repository URL.
    Returns (is_valid, error_message).
    """
    url = url.strip().rstrip("/")

    if not url.startswith("https://"):
        return False, "Only HTTPS GitHub URLs are supported (no SSH, git://, etc.)"

    if not GITHUB_URL_RE.match(url):
        return False, f"Invalid GitHub URL format. Expected: https://github.com/<owner>/<repo>"

    return True, ""


def extract_repo_name(url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL."""
    url = url.strip().rstrip("/").removesuffix(".git")
    parts = url.split("/")
    if len(parts) < 5:
        raise ValueError(f"Cannot extract repo name from URL: {url}")
    return f"{parts[-2]}/{parts[-1]}"


def is_binary_file(path: Path) -> bool:
    """
    Detect binary files by reading the first 8KB and checking for null bytes.
    Fast heuristic — same approach used by git.
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except (OSError, PermissionError):
        return True  # If we can't read it, skip it


def check_repo_limits(repo_path: Path) -> tuple[bool, str]:
    """
    Pre-check that a repo is within file count and size limits.
    Returns (within_limits, error_message).
    """
    total_files = 0
    total_size = 0
    max_size_bytes = config.MAX_REPO_SIZE_MB * 1024 * 1024

    for item in repo_path.rglob("*"):
        if not item.is_file():
            continue
        total_files += 1
        total_size += item.stat().st_size

        if total_files > config.MAX_FILE_COUNT:
            return False, (
                f"Repository exceeds file limit ({config.MAX_FILE_COUNT} files). "
                f"Use a specific branch or subdirectory."
            )
        if total_size > max_size_bytes:
            return False, (
                f"Repository exceeds size limit ({config.MAX_REPO_SIZE_MB}MB). "
                f"Use a specific branch or subdirectory."
            )

    return True, ""
