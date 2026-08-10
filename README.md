# Groundwork MCP

<div align="center">

**Reverse-engineer any GitHub repository directly inside your AI assistant.**

Clone → Parse → Index → Query. Fully local. Zero cost. No cloud.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.4+-green?style=flat-square)](https://github.com/jlowin/fastmcp)
[![License](https://img.shields.io/badge/License-MIT-gray?style=flat-square)](LICENSE)

</div>

---

Groundwork is an MCP server that lets Claude (or any MCP-compatible AI) deeply understand a codebase by ingesting it locally — not by searching the web or reading raw text, but by **parsing the actual AST** and building a queryable knowledge base of symbols, imports, and file structure.

Ask Claude:
- *"What does `rag_agent.py` import?"*
- *"Where is `DQNPricingAgent` defined and what methods does it have?"*
- *"Show me the README for this repo."*
- *"What's the dependency graph between the agent files?"*

Claude answers from the **local index**, not from hallucination.

---

## How It Works

```
GitHub Repo URL
      │
      ▼
 git clone --depth 1          ← shallow clone, no history
      │
      ▼
  The Sieve                   ← strips binaries, lock files, node_modules, etc.
      │
      ▼
  tree-sitter Parser           ← AST extraction for JS / TS / Python
      │                        ← raw text storage for MD / JSON / YAML / TOML
      ▼
  SQLite (local)               ← jobs · parsed_files · symbols · edges
      │
      ▼
  7 MCP Tools                  ← Claude queries the index, never guesses
```

---

## Tools

| Tool | What it does |
|------|-------------|
| `ingest_repo` | Clone + index a repo. Returns `job_id` immediately, runs in background. |
| `get_ingest_status` | Poll job progress: `queued → cloning → sieving → parsing → complete` |
| `list_ingested_repos` | List all indexed repos with job IDs (resume across sessions) |
| `get_repo_summary` | High-level map: languages, symbol types, most-imported files, external deps |
| `query_symbols` | Search for functions, classes, types by name / type / file (partial match) |
| `get_import_edges` | Get import edges for a file — outgoing, incoming, or both |
| `get_file_content` | Read any indexed file — README, config, source, YAML — full text |

---

## Supported Languages

| Language | Extensions | Symbols | Edges | File Content |
|----------|-----------|---------|-------|-------------|
| TypeScript | `.ts`, `.tsx` | ✅ | ✅ | — |
| JavaScript | `.js`, `.mjs`, `.cjs` | ✅ | ✅ | — |
| Python | `.py` | ✅ | ✅ | — |
| Markdown | `.md`, `.mdx` | — | — | ✅ |
| JSON | `.json` | — | — | ✅ |
| YAML | `.yaml`, `.yml` | — | — | ✅ |
| TOML | `.toml` | — | — | ✅ |

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
uv run groundwork-mcp --help
```

---

## Claude Desktop Configuration

Edit your Claude Desktop config:

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

Restart Claude Desktop. Groundwork will appear under **Connectors → Desktop → Local dev**.

---

## Usage

```
You:    Ingest https://github.com/ARYANRAJ1121/ECHO

Claude: [ingest_repo] Job started: abc-123. Polling...
        [get_ingest_status] Parsing 28/34 files (82%)...
        [get_ingest_status] Complete — 34 files, ~74K tokens. Commit df87f2d7.

You:    What is this project about?

Claude: [get_file_content → README.md] ...reads actual README...
        ECHO is a multi-agent pricing simulation that...

You:    Where is DQNPricingAgent defined?

Claude: [query_symbols → name=DQNPricingAgent]
        [class] DQNPricingAgent @ agents/dqn_agent.py:12–187

You:    What does dqn_agent.py import?

Claude: [get_import_edges → dqn_agent.py, outgoing]
        agents/dqn_agent.py → <external: numpy>
        agents/dqn_agent.py → <external: torch>
        agents/dqn_agent.py → market/engine.py
```

---

## Data Storage

```
~/.groundwork/
  groundwork.db      # SQLite — jobs, files, symbols, edges
  repos/             # Temporary clone dirs (auto-cleaned after parse)
```

Override with `GROUNDWORK_DATA_DIR=/custom/path`.

### Schema

| Table | Contains |
|-------|---------|
| `jobs` | One row per repo — status, progress, commit SHA |
| `parsed_files` | Every indexed file — language, line count, content/AST |
| `symbols` | Functions, classes, types, variables — with file + line |
| `edges` | Import/dependency edges between files |

---

## Security

- **HTTPS GitHub only** — SSH and non-GitHub URLs rejected
- **Shallow clone** — `--depth 1`, never fetches history
- **File limits** — max 10K files, 500MB per repo (configurable)
- **Binary detection** — skips images, executables, lock files
- **No credentials stored** — public repos only

---

## Stack

| Layer | Library | Why |
|-------|---------|-----|
| MCP | `fastmcp` | Cleanest Python MCP framework |
| Parsing | `tree-sitter` (native) | AST, not regex — no WASM, no compilation |
| Database | `sqlite3` (built-in) | Zero dependencies, WAL mode |
| Git | `subprocess` + system git | Reliable timeout on all platforms |

---

## Roadmap

- [ ] `search_code` — full-text search across all file contents
- [ ] `get_call_graph` — trace function calls across files
- [ ] Support for Go, Rust, Java grammars
- [ ] Private repo support (via personal access token)
- [ ] Re-ingest on new commit detection

---

## License

MIT — [LICENSE](LICENSE)
