# Groundwork: product message and launch copy

## One-line explanation

Groundwork gives MCP-compatible AI assistants a searchable map of a codebase, with answers grounded in file and line references.

## Who it helps

- Developers joining a project they did not build.
- Maintainers answering questions about a large or unfamiliar codebase.
- Teams that want local code indexing and source-backed AI answers.

## What the VS Code extension does

The extension indexes the open workspace on the developer's machine and shows indexing status in a dedicated Groundwork sidebar. The user connects their preferred AI assistant to Groundwork MCP separately; the extension does not silently configure or send code to a hosted AI service.

## Product promise

Ask a code question. Get an answer tied to the repository's actual files, then open those files and check the evidence.

Avoid claims that Groundwork prevents hallucinations, guarantees correctness, saves a fixed amount of time or tokens, or works with every AI assistant. Those need measured evidence or tested integrations first.

## X / Twitter launch post

Joining a codebase and asking “where does this happen?” shouldn’t mean grepping the whole repo by hand.

Groundwork MCP builds a local, searchable map of your project so an MCP-connected AI assistant can answer with file and line references.

Now available for VS Code: [Marketplace link]

Your source stays on your machine in local mode.

## LinkedIn launch post

AI coding assistants are more useful when they can point to the code behind an answer.

I built Groundwork MCP to help developers explore unfamiliar codebases. It indexes a local workspace, then gives MCP-compatible AI assistants tools to search files, symbols, imports, and call relationships with source references.

The new VS Code extension adds a Groundwork sidebar, automatic workspace indexing, visible progress, and a quick-start guide. The extension indexes locally; connecting an AI assistant is a separate, explicit setup step.

Groundwork MCP is now available in the VS Code Marketplace: [Marketplace link]

I’d value feedback on the first-run experience and the codebase questions you’d want it to answer.

## Short demo script

1. Open a project in VS Code and click the Groundwork icon in the Activity Bar.
2. Show the indexing status and the completed file count.
3. In an MCP-connected assistant, ask: “Find where this project configures logging. Cite the exact file and lines, and explain the call path.”
4. Open the cited file and show how the answer maps to the source.

## Launch links

- VS Code Marketplace: https://marketplace.visualstudio.com/items?itemName=groundwork-mcp.groundwork-mcp
- GitHub: https://github.com/ARYANRAJ1121/groundwork-mcp
- PyPI: https://pypi.org/project/groundwork-mcp/
