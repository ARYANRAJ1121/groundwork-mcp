"""Groundwork MCP — configuration."""

import os
from pathlib import Path

# Base data directory — override with GROUNDWORK_DATA_DIR env var
DATA_DIR = Path(os.environ.get("GROUNDWORK_DATA_DIR", Path.home() / ".groundwork"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "groundwork.db"
REPOS_DIR = DATA_DIR / "repos"
REPOS_DIR.mkdir(parents=True, exist_ok=True)

# Limits
MAX_FILE_COUNT = int(os.environ.get("GROUNDWORK_MAX_FILES", "10000"))
MAX_REPO_SIZE_MB = int(os.environ.get("GROUNDWORK_MAX_REPO_MB", "500"))
MAX_SINGLE_FILE_KB = int(os.environ.get("GROUNDWORK_MAX_FILE_KB", "512"))
CLONE_TIMEOUT_SECONDS = int(os.environ.get("GROUNDWORK_CLONE_TIMEOUT", "120"))

# File extension → language mapping
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".py": "python",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".mdx": "markdown",
    ".toml": "toml",
    ".env.example": "config", ".env.sample": "config",
}

# Directories to skip entirely
SKIP_DIRS: set[str] = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "vendor", "dist", "build", "out", "target", ".next",
    ".nuxt", "coverage", ".cache", ".parcel-cache",
    "venv", ".venv", "env", ".env", "site-packages",
    ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}

# Files to skip
SKIP_FILES: set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "uv.lock",
    "bun.lockb", "composer.lock", "Gemfile.lock",
    ".DS_Store", "Thumbs.db",
}
