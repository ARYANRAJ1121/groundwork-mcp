# Groundwork MCP

<div align="center">

**Reverse-engineer any GitHub repository directly inside your AI assistant.**

Ingest → Parse → Index → Query. Local-first. Source stays on your machine in local mode.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.4+-green?style=flat-square)](https://github.com/jlowin/fastmcp)
[![Laya](https://img.shields.io/badge/Router-Laya-purple?style=flat-square)](https://github.com/NandhaKishorM/laya)
[![SQLite](https://img.shields.io/badge/Database-SQLite-orange?style=flat-square)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

Groundwork is a local-first MCP server that gives Claude (or any MCP-compatible AI) cited evidence from a codebase by **indexing source files with tree-sitter and building a queryable knowledge base of symbols, imports, file content, and structure.**

Groundwork returns evidence pinned to the indexed commit so an assistant can verify what it uses:
- *"What is this project about?"* → reads the actual `README.md`
- *"Where is `DQNPricingAgent` defined?"* → returns file + line number + signature
- *"What does `rag_agent.py` import?"* → returns the real import graph
- *"Search for all uses of `pgvector`"* → full-text search across all files
- *"List all Python files in the agents/ directory"* → directory-grouped file tree
- *"Delete the ECHO repo index"* → removes it cleanly from the database

Groundwork provides source evidence with commit-pinned citations. The assistant remains responsible for interpreting that evidence correctly.

The hosted public architecture page is available at the web service root when deployed with Docker Compose. It shares index snapshots by repository and commit SHA.

---

## How It Works

```
GitHub Repo URL
      │
      ▼
  GitHub tarball API           ← commit-pinned source, no local Git required
      │
      ▼
  The Sieve                   ← strips binaries, lock files, node_modules,
      │                          hidden dirs, oversized files, etc.
      ▼
  tree-sitter language pack    ← real AST extraction for 40+ mapped languages
      │                        ← raw text retained for indexed files
      ▼
  SQLite (local, WAL mode)     ← jobs · parsed_files · FTS5 · symbols · edges
      │                          32MB cache · auto-migration · cascade deletes
      ▼
  13 MCP Tools                 ← structured, commit-pinned evidence
      │
      ▼
  Auto-cleanup                 ← clone directory removed after parse (disk efficient)
```

---

## Tools

| # | Tool | What it does |
|---|------|-------------|
| 1 | `route_query` | Smart intent router using Laya to classify natural language queries and recommend the best tool. |
| 2 | `ingest_repo` | Clone + index a repo. Returns `job_id` immediately, runs in background. |
| 3 | `get_ingest_status` | Poll job progress: `queued → cloning → sieving → parsing → complete` |
| 4 | `list_ingested_repos` | List all indexed repos with job IDs — resume across sessions |
| 5 | `get_repo_summary` | Structured commit-pinned map: languages, symbol counts, most-imported files, external deps |
| 6 | `query_symbols` | Search functions, classes, types by name / type / file — returns structured commit-pinned citations |
| 7 | `get_import_edges` | Structured import graph with source line and commit-pinned citation |
| 8 | `get_file_content` | Read a requested line range with a structured commit-pinned citation |
| 9 | `list_repo_files` | Structured file list with language, size, line count, and commit-pinned citations |
| 10 | `delete_repo` | Permanently remove a repo and all its data from the index |
| 11 | `search_code` | Ranked SQLite FTS5 search with structured citations |
| 12 | `get_call_graph` | Trace who calls a function and what a function calls |
| 13 | `ingest_local_path` | Index a local workspace without uploading its source |

---

## Supported Languages

| Language | Extensions | AST | Symbols | Raw Content |
|----------|-----------|:-------:|:------------:|:-----------:|
| JS / TS / TSX / Python | `.js`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.py` | ✅ | Existing extractors | ✅ |
| C / C++ / C# / Go / Java / Kotlin / Rust / Swift / Dart | common extensions | ✅ | — | ✅ |
| Ruby / PHP / Scala / Elixir / Haskell / OCaml / Perl / R / Lua | common extensions | ✅ | — | ✅ |
| HTML / CSS / Vue / Svelte / GraphQL / SQL / Bash / Nix / Zig / Clojure / Groovy / PowerShell | common extensions | ✅ | — | ✅ |
| Markdown / JSON / YAML / TOML / Dockerfile / Make / Terraform | common extensions and filenames | ✅ | — | ✅ |

The tree-sitter language pack provides the grammars; Groundwork maps 40+ common source/config languages and stores raw UTF-8 content up to the configured file-size limit (512KB by default). Grammars load lazily, so only languages present in a repo are needed. The first use of a grammar may download its parser library; repo source itself stays local. File reads accept 1-based `start_line` and inclusive `end_line` (0 requests EOF), return at most 200 lines per call, and include `next_start_line` when more content is available. Search, symbol, and call-graph results include repo, commit SHA, path, line span, and a permalink where source locations exist. Repository text is marked as untrusted evidence.

---

## Installation

### Fastest setup (PyPI)

Install Python 3.11+ and `uv`, then use:

```bash
uvx --from groundwork-mcp groundwork-mcp
```

Claude Code:

```bash
claude mcp add --scope user groundwork -- uvx --from groundwork-mcp groundwork-mcp
```

Cursor `mcp.json`:

```json
{
  "mcpServers": {
    "groundwork": {
      "command": "uvx",
      "args": ["--from", "groundwork-mcp", "groundwork-mcp"]
    }
  }
}
```

Claude Desktop uses the same command and args in its `mcpServers.groundwork` entry. PyPI instructions become live after a tagged release is published.

### Prerequisites

- **Python 3.11+**
- **uv** — [install](https://docs.astral.sh/uv/getting-started/installation/)
- Internet access to GitHub for remote repositories (`ingest_local_path` works offline)

### Setup

```bash
# 1. Clone
git clone https://github.com/ARYANRAJ1121/groundwork-mcp.git
cd groundwork-mcp

# 2. Install dependencies (include router for Laya)
uv sync --extra router

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
| `GROUNDWORK_ALLOW_UNAUTHENTICATED_HTTP` | `0` | Explicit local-development override for HTTP without OAuth |
| `GROUNDWORK_CLONE_TIMEOUT` | `120` | GitHub API and tarball download timeout in seconds |
| `GROUNDWORK_GITHUB_TOKEN` | unset | Optional local-mode token for private GitHub reads; never stored in SQLite |
| `GROUNDWORK_TRANSPORT` | `stdio` | `stdio` for local clients or `http` for Streamable HTTP (automatically disables local-path tools) |
| `GROUNDWORK_HTTP_HOST` | `127.0.0.1` | HTTP bind address |
| `GROUNDWORK_HTTP_PORT` | `8000` | HTTP port |
| `GROUNDWORK_OAUTH_GITHUB_CLIENT_ID` | unset | GitHub OAuth App ID for HTTP |
| `GROUNDWORK_OAUTH_GITHUB_CLIENT_SECRET` | unset | GitHub OAuth App secret |
| `GROUNDWORK_OAUTH_GITHUB_BASE_URL` | unset | Public HTTPS base URL for OAuth callbacks |
| `GROUNDWORK_OAUTH_JWT_SIGNING_KEY` | unset | Persistent random signing key for OAuth tokens |
| `GROUNDWORK_REMOTE_MODE` | `0` | Disables local paths and private server-wide tokens for shared hosting |

### Local and private repositories

Call `ingest_local_path(path)` to index a directory on the machine running Groundwork. Source stays on that machine and the SQLite index remains in `GROUNDWORK_DATA_DIR`. For private GitHub repositories, set `GROUNDWORK_GITHUB_TOKEN` to a fine-grained token with read-only Contents access before starting local mode. Tokens are sent to GitHub over HTTPS and never written to the database. Shared remote mode rejects server-wide private tokens.

### Streamable HTTP and OAuth

For a self-hosted remote MCP endpoint, register a GitHub OAuth App and set the OAuth variables above, then start with `GROUNDWORK_TRANSPORT=http`. FastMCP serves Streamable HTTP at `/mcp`. Put HTTPS/TLS in front of public deployments. The unauthenticated HTTP override is for local development only.

### Docker

Local stdio mode keeps the index in a named volume:

```bash
docker build -t groundwork-mcp .
docker run --rm -i -v groundwork-data:/data groundwork-mcp
```

Compose runs the OAuth-protected MCP endpoint and public architecture page together. Set the OAuth variables in `.env`, set the base URL to the public HTTPS MCP URL, and route TLS traffic to ports 8000 and 8080:

```bash
docker compose up -d --build
```

The public page only indexes GitHub public repos. Its shared cache is keyed by `(repository, commit SHA)`.

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
| `jobs` | One immutable repo snapshot — status, progress, commit SHA, timestamps |
| `parsed_files` | Every indexed file — language, line count, raw content, AST |
| `symbols` | Functions, classes, methods, types — with file, line, signature |
| `edges` | Import/dependency edges between files and external modules |

### Benchmark

`benchmarks/tasks.json` and its fixture repo define a repeatable paired repo-QA benchmark. The same model answers once with the complete repository (the no-Groundwork baseline) and once with Groundwork FTS-retrieved evidence. It reports answer accuracy, citation precision for both arms, and provider-reported token counts with per-task responses. Run it with:

```bash
uv sync --locked
uv run python benchmarks/run.py --model <responses-api-model>
```

Set `OPENAI_API_KEY` first. No measured benchmark result is claimed until an API-backed run is performed; raw output is written to the ignored `benchmark-results.json`.

---

## Production Features

- **Commit-pinned ingestion** — GitHub tarball download avoids local Git, deep paths, and branches moving during the fetch
- **Staleness checks** — re-ingesting checks the remote tip and creates a fresh snapshot when it changed
- **FTS5 search** — ranked full-text index with transactional synchronization to stored files
- **Isolated worker state** — one SQLite connection and parser instance per thread, with WAL mode
- **Concurrency limit** — max 2 ingestion jobs run simultaneously via asyncio semaphore
- **Auto-cleanup** — clone directory deleted after parse; all data lives in SQLite
- **Auto-migration** — new columns added to existing databases on startup, no manual steps
- **WAL mode** — SQLite Write-Ahead Logging for concurrent reads during writes
- **Untrusted source framing** — repository contents are labeled as evidence, never as model instructions
- **No credentials stored** — optional token is read from environment and never stored in SQLite
- **Binary detection** — skips images, executables, and non-text files automatically

---

## Security

- **HTTPS GitHub URLs only** — SSH and non-GitHub URLs are rejected at validation
- **Commit-pinned archive** — GitHub tarballs are downloaded at a resolved immutable commit
- **File size limits** — configurable caps on total repo size and individual files
- **No shelling out to Git** — remote ingestion uses HTTPS API/tarballs
- **Public shared index** — hosted page accepts public repos only; local mode supports private sources

---

## Stack

| Layer | Library | Why |
|-------|---------|-----|
| MCP | `fastmcp` | Cleanest Python MCP framework — `@mcp.tool()` decorators |
| Routing | `laya` | Non-autoregressive decision engine — instantly routes natural language to tools (~33ms) |
| Parsing | `tree-sitter-language-pack` | Real AST across 40+ mapped languages |
| Database | `sqlite3` (built-in) | Zero extra deps — WAL mode, migrations, cascade deletes |
| Remote source | GitHub API tarballs | Commit-pinned archives without a local Git install |

---

---

## License

MIT — [LICENSE](LICENSE)
