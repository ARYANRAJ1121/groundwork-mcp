# Groundwork MCP

> **MCP server that clones, parses, and builds a citation-grounded knowledge base from any GitHub repository — zero-cost, fully local, no cloud dependencies.**

Groundwork lets any MCP-compatible client (Claude Desktop, Cursor, Antigravity, etc.) connect to a GitHub repository and:

- **Clone + analyze** it with AST-grounded parsing (tree-sitter, not raw text guessing)
- **Extract symbols & dependency edges** (functions, classes, imports) across JS/TS/Python
- **Build a persistent SQLite knowledge base** per repository that survives across sessions
- **Return job IDs** immediately — ingestion runs async, you poll for progress

---

## Zero-Cost Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Runtime | Node.js / TypeScript | MCP SDK is TypeScript-first |
| Parsing | `web-tree-sitter` (WASM) | Local AST, no API calls, no native build tools |
| Database | `sql.js` (WASM SQLite) | Zero `node-gyp`, works on all OSes |
| Git | `simple-git` | Wraps system `git`, shallow clones |
| MCP | `@modelcontextprotocol/sdk` | Official SDK |

No paid services. No cloud. No Docker (yet). Runs entirely on your machine.

---

## Tools

### `ingest_repo(repo_url, branch?)`

Clone a public GitHub repository and build a knowledge base from it.

- Validates the URL (HTTPS GitHub only)
- Returns a `job_id` **immediately** — ingestion runs in the background
- Poll `get_ingest_status` to track progress

```json
{
  "job_id": "e9cb40be-48c9-4161-9148-3837384cbdca",
  "status": "queued",
  "repo_name": "sindresorhus/is",
  "message": "Ingestion started. Poll get_ingest_status(...) to track progress."
}
```

### `get_ingest_status(job_id)`

Check the live status and progress of an ingestion job.

```json
{
  "job_id": "e9cb40be-...",
  "repo_name": "sindresorhus/is",
  "status": "complete",
  "progress_pct": 100,
  "files_processed": 11,
  "files_total": 11,
  "tokens_estimate": 66367,
  "commit_sha": "7821031c..."
}
```

Status values: `queued` → `cloning` → `sieving` → `parsing` → `complete` | `failed`

### `list_ingested_repos()`

List all repositories ingested in the current knowledge base. Useful for resuming sessions.

```json
{
  "total": 3,
  "complete": 2,
  "in_progress": 1,
  "repos": [...]
}
```

---

## Installation

### Prerequisites

- **Node.js** ≥ 18 (`node --version`)
- **git** on your PATH (`git --version`)

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/ARYANRAJ1121/groundwork-mcp.git
cd groundwork-mcp

# 2. Install dependencies (no native build tools needed)
npm install

# 3. Download WASM grammar files
npx tsx scripts/download-grammars.ts

# 4. Build
npm run build

# 5. Verify it starts
node build/index.js
# You should see: [INFO] Groundwork MCP Server running on stdio
# Press Ctrl+C to stop
```

---

## MCP Client Configuration

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or  
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "groundwork": {
      "command": "node",
      "args": ["C:/absolute/path/to/groundwork-mcp/build/index.js"]
    }
  }
}
```

Restart Claude Desktop after saving. You should see Groundwork in the tools panel.

### Antigravity IDE

Add to your MCP server configuration:

```json
{
  "name": "groundwork",
  "command": "node",
  "args": ["C:/absolute/path/to/groundwork-mcp/build/index.js"]
}
```

### Cursor / Other MCP Clients

Any client that supports the MCP stdio transport will work. Point `command` to `node` and `args` to the absolute path of `build/index.js`.

---

## Usage

Once connected, talk to your AI client naturally:

```
You: Ingest https://github.com/fastapi/fastapi for me

Claude: [calls ingest_repo] Job started: abc-123. Let me check progress...
        [calls get_ingest_status] Status: parsing (47/89 files, 34%)...
        [calls get_ingest_status] Complete! 89 files, 312K tokens indexed.

        FastAPI has been ingested. I can now answer questions about:
        - File structure and module organization
        - Function signatures and class hierarchies
        - Import dependencies and dependency graph
        - Specific symbols and where they're defined
```

---

## Data Storage

By default, Groundwork stores data at:

```
~/.groundwork/
  groundwork.db      # SQLite database (jobs, files, symbols, edges)
  repos/             # Temporary clone directories (cleaned after ingestion)
```

Override with environment variables:

```bash
GROUNDWORK_DATA_DIR=/custom/path node build/index.js
```

### SQLite Schema

| Table | Contains |
|-------|---------|
| `jobs` | Job status, progress, metadata per repo |
| `parsed_files` | Every parsed source file with AST JSON |
| `symbols` | Functions, classes, types extracted per file |
| `edges` | Import/dependency edges between files |

---

## Security

- **HTTPS only** — SSH and non-GitHub URLs are rejected
- **Shallow clones** — `--depth 1`, never fetches full history
- **File caps** — max 10,000 files and 500MB per repo (configurable)
- **Binary detection** — images, executables, and lock files are skipped
- **Sandboxed** — clones go into an isolated per-job directory

---

## Supported Languages

| Language | Extension(s) | Symbols | Edges |
|----------|-------------|---------|-------|
| TypeScript | `.ts` | ✅ | ✅ |
| TypeScript JSX | `.tsx` | ✅ | ✅ |
| JavaScript | `.js`, `.mjs`, `.cjs` | ✅ | ✅ |
| Python | `.py` | ✅ | ✅ |
| JSON | `.json` | — | — |
| Markdown | `.md` | — | — |
| YAML | `.yaml`, `.yml` | — | — |
| TOML | `.toml` | — | — |

---

## Development

```bash
# Type-check without building
npx tsc --noEmit

# Run integration test against a real repo
npx tsx scripts/test-ingest.ts

# Copy WASM grammars (after npm install)
npx tsx scripts/download-grammars.ts
```

---

## Roadmap

- [ ] **v0.2** — `query_repo` tool: semantic search over parsed symbols
- [ ] **v0.2** — `get_file` tool: return file content with symbol annotations
- [ ] **v0.3** — Build-prompt roadmap generation (reconstruct project from scratch)
- [ ] **v0.3** — LanceDB vector embeddings for semantic similarity search
- [ ] **v1.0** — Docker packaging for fully isolated execution

---

## License

MIT — see [LICENSE](LICENSE)
