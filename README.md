# Groundwork MCP

<div align="center">

**Reverse-engineer any GitHub repository directly inside your AI assistant.**

Clone → Parse → Index → Query. Fully local. Zero cost. No cloud.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.4+-green?style=flat-square)](https://github.com/jlowin/fastmcp)
[![SQLite](https://img.shields.io/badge/Database-SQLite-orange?style=flat-square)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

Groundwork is a production-grade MCP server that lets Claude (or any MCP-compatible AI) deeply understand a codebase — not by guessing from training data, but by **cloning the repo, parsing every file with a real AST parser, and building a local queryable knowledge base of symbols, imports, file content, and structure.**

Ask Claude:
- *"What is this project about?"* → reads the actual `README.md`
- *"Where is `DQNPricingAgent` defined?"* → returns file + line number + signature
- *"What does `rag_agent.py` import?"* → returns the real import graph
- *"Search for all uses of `pgvector`"* → full-text search across all files
- *"List all Python files in the agents/ directory"* → directory-grouped file tree
- *"Delete the ECHO repo index"* → removes it cleanly from the database

Claude answers from the **local SQLite index**, never from hallucination.

---

## How It Works

```
GitHub Repo URL
      │
      ▼
 git clone --depth 1          ← shallow clone, 3× retry with backoff
      │
      ▼
  The Sieve                   ← strips binaries, lock files, node_modules,
      │                          hidden dirs, oversized files, etc.
      ▼
  tree-sitter Parser           ← real AST extraction for JS / TS / TSX / Python
      │                        ← raw text storage for MD / JSON / YAML / TOML
      ▼
  SQLite (local, WAL mode)     ← jobs · parsed_files · symbols · edges
      │                          32MB cache · auto-migration · cascade deletes
      ▼
  10 MCP Tools                 ← Claude queries the index, never guesses
      │
      ▼
  Auto-cleanup                 ← clone directory removed after parse (disk efficient)
```

---

## Tools

| # | Tool | What it does |
|---|------|-------------|
| 1 | `ingest_repo` | Clone + index a repo. Returns `job_id` immediately, runs in background. |
| 2 | `get_ingest_status` | Poll job progress: `queued → cloning → sieving → parsing → complete` |
| 3 | `list_ingested_repos` | List all indexed repos with job IDs — resume across sessions |
| 4 | `get_repo_summary` | High-level map: languages, symbol counts, most-imported files, external deps |
| 5 | `query_symbols` | Search functions, classes, types by name / type / file — returns real signatures |
| 6 | `get_import_edges` | Import graph for a file — outgoing, incoming, or both |
| 7 | `get_file_content` | Read any indexed file — README, Python source, config, YAML — full text |
| 8 | `list_repo_files` | Directory-grouped file listing with language, size, line count |
| 9 | `delete_repo` | Permanently remove a repo and all its data from the index |
| 10 | `search_code` | Full-text search across all indexed file content — finds strings, comments, values |

---

## Supported Languages

| Language | Extensions | Symbols | Import Edges | Raw Content |
|----------|-----------|:-------:|:------------:|:-----------:|
| TypeScript | `.ts`, `.tsx` | ✅ | ✅ | ✅ |
| JavaScript | `.js`, `.mjs`, `.cjs` | ✅ | ✅ | ✅ |
| Python | `.py` | ✅ | ✅ | ✅ |
| Markdown | `.md`, `.mdx` | — | — | ✅ |
| JSON | `.json` | — | — | ✅ |
| YAML | `.yaml`, `.yml` | — | — | ✅ |
| TOML | `.toml` | — | — | ✅ |

All source files store **raw UTF-8 content** (up to 500KB per file), so `get_file_content` and `search_code` work across every file type.

---

## Installation

### Prerequisites

- **Python 3.11+**
- **uv** — [install](https://docs.astral.sh/uv/getting-started/installation/)
- **git** on your PATH

### Setup

```bash
# 1. Clone
git clone https://github.com/ARYANRAJ1121/groundwork-mcp.git
cd groundwork-mcp

# 2. Install dependencies
uv sync

# 3. Verify
uv run python -c "from groundwork_mcp.server import mcp; print('OK')"
```

---

## Claude Desktop Configuration

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`  
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "groundwork": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "C:\\path\\to\\groundwork-mcp",
        "groundwork-mcp"
      ]
    }
  }
}
```

Restart Claude Desktop. Groundwork appears under **Integrations**.

---

## Usage Example

```
You:    Ingest https://github.com/ARYANRAJ1121/ECHO

Claude: [ingest_repo]        Job started: abc-123. Polling...
        [get_ingest_status]  Parsing 28/34 files (82%)...
        [get_ingest_status]  Complete — 34 files, ~74K tokens. Commit df87f2d7.

You:    What is this project about?

Claude: [get_file_content → README.md]
        ECHO is a multi-agent pricing simulation where AI agents compete
        in a simulated market. The project studies whether agents develop
        collusive pricing behavior...

You:    List all files in the agents directory.

Claude: [list_repo_files → path_filter=agents]
        agents/
          dqn_agent.py      python   187 lines   8KB
          heuristic_agent.py python  142 lines   5KB
          llm_agent.py      python   201 lines   9KB
          rag_agent.py      python   218 lines  10KB
          rl_agent.py       python   163 lines   7KB

You:    Where is DQNPricingAgent defined?

Claude: [query_symbols → name=DQNPricingAgent]
        [class] DQNPricingAgent
                agents/dqn_agent.py:12–187
                → class DQNPricingAgent(BasePricingAgent):

You:    Search for pgvector across all files.

Claude: [search_code → query=pgvector]
        6 result(s) for 'pgvector':
          docker-compose.yml
            L14:   POSTGRES_EXTENSIONS: pgvector
          agents/rag_agent.py
            L8:    from pgvector.psycopg2 import register_vector
            L47:   self.cursor.execute("CREATE EXTENSION IF NOT EXISTS pgvector")
```

---

## Configuration

Control behaviour via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `GROUNDWORK_DATA_DIR` | `~/.groundwork` | Where the SQLite DB and repos are stored |
| `GROUNDWORK_MAX_FILES` | `10000` | Max files per repo |
| `GROUNDWORK_MAX_REPO_MB` | `500` | Max total repo size |
| `GROUNDWORK_MAX_FILE_KB` | `512` | Max single file size |
| `GROUNDWORK_CLONE_TIMEOUT` | `120` | Git clone timeout in seconds |

---

## Data Storage

```
~/.groundwork/
  groundwork.db      # SQLite — all jobs, files, symbols, edges
  repos/             # Temporary clone dirs (auto-deleted after parse)
```

### Schema

| Table | Contains |
|-------|---------|
| `jobs` | One row per repo — status, progress, commit SHA, timestamps |
| `parsed_files` | Every indexed file — language, line count, raw content, AST |
| `symbols` | Functions, classes, methods, types — with file, line, signature |
| `edges` | Import/dependency edges between files and external modules |

---

## Production Features

- **Retry logic** — git clone retries 3× with exponential backoff (1s, 2s) on transient failures
- **Concurrency limit** — max 2 ingestion jobs run simultaneously via asyncio semaphore
- **Auto-cleanup** — clone directory deleted after parse; all data lives in SQLite
- **Auto-migration** — new columns added to existing databases on startup, no manual steps
- **WAL mode** — SQLite Write-Ahead Logging for concurrent reads during writes
- **Never hallucinate** — MCP instructions explicitly forbid Claude from answering from memory
- **No credentials stored** — HTTPS public repos only; git never prompts for auth
- **Binary detection** — skips images, executables, and non-text files automatically

---

## Security

- **HTTPS GitHub URLs only** — SSH and non-GitHub URLs are rejected at validation
- **Shallow clone** — `--depth 1 --no-tags`, no history fetched
- **File size limits** — configurable caps on total repo size and individual files
- **No stdin** — git runs with `stdin=DEVNULL`, `GIT_TERMINAL_PROMPT=0`
- **Public repos only** — no credential management, no token storage

---

## Stack

| Layer | Library | Why |
|-------|---------|-----|
| MCP | `fastmcp` | Cleanest Python MCP framework — `@mcp.tool()` decorators |
| Parsing | `tree-sitter` (native Python) | Real AST — no WASM, no compilation, no regex hacks |
| Database | `sqlite3` (built-in) | Zero extra deps — WAL mode, migrations, cascade deletes |
| Git | `subprocess` + system git | Native timeout support on all platforms including Windows |

---

## Roadmap

- [ ] `get_call_graph` — trace function calls across files
- [ ] Support for Go, Rust, Java grammars
- [ ] Private repo support (personal access token)
- [ ] Re-ingest on new commit detection
- [ ] FTS5 virtual table for faster full-text search

---

## License

MIT — [LICENSE](LICENSE)
