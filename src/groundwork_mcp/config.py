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
GITHUB_TOKEN = os.environ.get("GROUNDWORK_GITHUB_TOKEN", "").strip()
TRANSPORT = os.environ.get("GROUNDWORK_TRANSPORT", "stdio").strip().lower()
HTTP_HOST = os.environ.get("GROUNDWORK_HTTP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("GROUNDWORK_HTTP_PORT", "8000"))
REMOTE_MODE = os.environ.get("GROUNDWORK_REMOTE_MODE", "0").lower() in {"1", "true", "yes"}
ALLOW_UNAUTHENTICATED_HTTP = os.environ.get("GROUNDWORK_ALLOW_UNAUTHENTICATED_HTTP", "0").lower() in {"1", "true", "yes"}
OAUTH_CLIENT_ID = os.environ.get("GROUNDWORK_OAUTH_GITHUB_CLIENT_ID", "").strip()
OAUTH_CLIENT_SECRET = os.environ.get("GROUNDWORK_OAUTH_GITHUB_CLIENT_SECRET", "").strip()
OAUTH_BASE_URL = os.environ.get("GROUNDWORK_OAUTH_GITHUB_BASE_URL", "").strip()
OAUTH_JWT_SIGNING_KEY = os.environ.get("GROUNDWORK_OAUTH_JWT_SIGNING_KEY", "")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
EMBEDDING_MODEL = os.environ.get("GROUNDWORK_EMBEDDING_MODEL", "nomic-embed-text").strip()

# File extension → language mapping
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".py": "python",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".mdx": "markdown", ".toml": "toml",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".cs": "csharp", ".css": "css", ".dart": "dart", ".ex": "elixir", ".exs": "elixir",
    ".go": "go", ".html": "html", ".htm": "html", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".lua": "lua", ".php": "php", ".rb": "ruby", ".rs": "rust", ".scala": "scala", ".sql": "sql",
    ".swift": "swift", ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".hs": "haskell",
    ".ml": "ocaml", ".mli": "ocaml", ".pl": "perl", ".r": "r", ".R": "r", ".vue": "vue",
    ".svelte": "svelte", ".graphql": "graphql", ".gql": "graphql", ".proto": "proto", ".cmake": "cmake",
    ".nix": "nix", ".zig": "zig", ".clj": "clojure", ".groovy": "groovy", ".ps1": "powershell",
    ".dockerfile": "dockerfile", ".tf": "hcl", ".hcl": "hcl", ".make": "make",
    ".env.example": "config", ".env.sample": "config",
}

SUPPORTED_FILENAMES: dict[str, str] = {
    "dockerfile": "dockerfile", "makefile": "make", "gnumakefile": "make",
    "justfile": "just", "cmakelists.txt": "cmake",
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
