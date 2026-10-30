# Groundwork MCP for VS Code and Cursor

This extension detects the open workspace and sends its local path to Groundwork's `ingest_local_path` MCP tool. Workspace source stays on the machine running the extension and Groundwork server.

## Prerequisites

- VS Code 1.90+ or a compatible Cursor build
- `uv` available on PATH
- Groundwork available on PyPI (`uvx --from groundwork-mcp groundwork-mcp`)

On startup, the extension launches Groundwork over MCP stdio and indexes each open workspace folder. It records the returned job ID in workspace state and shows progress in the **Groundwork MCP** output channel. Use **Groundwork: Index Workspace** from the command palette to retry or index again.

To use a local checkout before the PyPI release, set `groundwork.command` and `groundwork.args` in VS Code settings. For example, set the command to `uv` and the arguments to `run`, `--project`, `C:/path/to/groundwork-mcp`, `groundwork-mcp`.

Set `groundwork.autoIndex` to `false` to disable automatic startup indexing. The command remains available for manual indexing.

## Development

```bash
npm install
npm run compile
```

Press F5 in VS Code to launch an Extension Development Host.
