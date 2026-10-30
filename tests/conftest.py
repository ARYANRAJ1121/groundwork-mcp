"""Shared fixtures for groundwork-mcp tests."""

import os
import sys
import sqlite3
import pytest
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Create a temporary SQLite database and wire it into groundwork_mcp.config."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("groundwork_mcp.config.DB_PATH", db_path)
    monkeypatch.setattr("groundwork_mcp.config.REPOS_DIR", tmp_path / "repos")
    (tmp_path / "repos").mkdir()

    from groundwork_mcp.database import init_database, close_database

    init_database()
    yield db_path
    close_database()


@pytest.fixture()
def sample_job(tmp_db):
    """Create a complete job with parsed files, symbols, edges, and calls."""
    from groundwork_mcp.database import (
        create_job, update_job, insert_parsed_file,
        insert_symbols, insert_edges, insert_calls, commit_batch,
    )
    from groundwork_mcp.types import (
        ParsedFile, SymbolRecord, EdgeRecord, CallRecord,
    )

    job_id = "test-job-001"
    create_job(job_id, "https://github.com/test/repo", "test/repo", "main")
    update_job(
        job_id,
        status="complete",
        progress=1.0,
        files_processed=3,
        files_total=3,
        tokens_estimate=5000,
        commit_sha="abc123def456",
        force_commit=True,
    )

    # Insert parsed files
    insert_parsed_file(job_id, ParsedFile(
        file_path="src/main.py",
        language="python",
        line_count=50,
        size_bytes=1200,
        ast_json='{"t":"module"}',
        raw_content="import os\nimport sys\n\ndef main():\n    print('hello')\n\nclass App:\n    def run(self):\n        self.start()\n\nif __name__ == '__main__':\n    main()\n",
        content_hash="aaa111",
    ))
    insert_parsed_file(job_id, ParsedFile(
        file_path="src/utils.py",
        language="python",
        line_count=30,
        size_bytes=800,
        ast_json='{"t":"module"}',
        raw_content="def helper():\n    return 42\n\ndef format_output(data):\n    return str(data)\n",
        content_hash="bbb222",
    ))
    insert_parsed_file(job_id, ParsedFile(
        file_path="README.md",
        language="markdown",
        line_count=10,
        size_bytes=300,
        ast_json=None,
        raw_content="# Test Repo\n\nA test repository for unit tests.\n",
        content_hash="ccc333",
    ))

    # Insert symbols
    insert_symbols(job_id, [
        SymbolRecord("src/main.py", "main", "function", 4, 5, "def main():"),
        SymbolRecord("src/main.py", "App", "class", 7, 9, "class App:"),
        SymbolRecord("src/main.py", "run", "method", 8, 9, "def run(self):"),
        SymbolRecord("src/utils.py", "helper", "function", 1, 2, "def helper():"),
        SymbolRecord("src/utils.py", "format_output", "function", 4, 5, "def format_output(data):"),
    ])

    # Insert edges
    insert_edges(job_id, [
        EdgeRecord("src/main.py", None, "os", "import", 1),
        EdgeRecord("src/main.py", None, "sys", "import", 2),
        EdgeRecord("src/main.py", "src/utils.py", "./utils", "import", 3),
    ])

    # Insert calls
    insert_calls(job_id, [
        CallRecord("src/main.py", "main", "helper", 5),
        CallRecord("src/main.py", "run", "start", 9),
        CallRecord("src/main.py", "<module>", "main", 12),
    ])

    commit_batch()
    return job_id


@pytest.fixture()
def mini_repo(tmp_path):
    """Create a minimal repository directory structure for sieve/parser tests."""
    root = tmp_path / "fakerepo"
    root.mkdir()

    # Python file
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "import os\n\ndef hello():\n    print('hi')\n\nclass Greeter:\n    def greet(self):\n        hello()\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    # JS file
    (root / "index.js").write_text(
        "import { foo } from './lib';\n\nfunction main() {\n  console.log('hello');\n}\n",
        encoding="utf-8",
    )

    # Markdown
    (root / "README.md").write_text("# Fake Repo\n\nHello world.\n", encoding="utf-8")

    # JSON config
    (root / "package.json").write_text('{"name": "fakerepo", "version": "1.0.0"}\n', encoding="utf-8")

    # Directories/files to skip
    nm = root / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("module.exports = {};", encoding="utf-8")

    pycache = root / "__pycache__"
    pycache.mkdir()
    (pycache / "app.cpython-312.pyc").write_bytes(b"\x00\x00\x00\x00binary")

    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text("SECRET = 1", encoding="utf-8")

    # Binary file
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    # Empty file
    (root / "empty.py").write_text("", encoding="utf-8")

    # Lock file
    (root / "package-lock.json").write_text("{}", encoding="utf-8")

    return root

