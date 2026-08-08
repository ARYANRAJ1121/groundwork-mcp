/**
 * Groundwork MCP Server — Server Setup & Tool Registration
 *
 * Creates the McpServer instance and registers all tools with their
 * Zod schemas. This is the central wiring point.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { handleIngestRepo, ingestRepoSchema } from './tools/ingest-repo.js';
import { handleGetIngestStatus, getIngestStatusSchema } from './tools/get-ingest-status.js';
import { handleListIngestedRepos } from './tools/list-ingested.js';
import { handleQuerySymbols, querySymbolsSchema } from './tools/query-symbols.js';
import { handleGetImportEdges, getImportEdgesSchema } from './tools/get-import-edges.js';
import { handleGetRepoSummary, getRepoSummarySchema } from './tools/get-repo-summary.js';
import { logger } from './utils/logger.js';

/**
 * Create and configure the Groundwork MCP server.
 * All tools are registered here with full Zod schemas + descriptions.
 */
export function createServer(): McpServer {
  const server = new McpServer({
    name: 'groundwork-mcp',
    version: '0.1.0',
  });

  // ── Tool: ingest_repo ─────────────────────────────────────────────────────
  server.registerTool(
    'ingest_repo',
    {
      title: 'Ingest Repository',
      description:
        'Clone a GitHub repository and build a citation-grounded knowledge base from it. ' +
        'Returns a job_id immediately — use get_ingest_status(job_id) to track progress. ' +
        'Parses JS, TypeScript, and Python files into AST symbols and dependency edges.',
      inputSchema: ingestRepoSchema,
    },
    async (args) => handleIngestRepo(args),
  );

  // ── Tool: get_ingest_status ───────────────────────────────────────────────
  server.registerTool(
    'get_ingest_status',
    {
      title: 'Get Ingest Status',
      description:
        'Check the status and progress of a repository ingestion job. ' +
        'Poll this after calling ingest_repo until status is "complete" or "failed". ' +
        'Returns file counts, token estimates, and any error messages.',
      inputSchema: getIngestStatusSchema,
    },
    async (args) => handleGetIngestStatus(args),
  );

  // ── Tool: list_ingested_repos ─────────────────────────────────────────────
  server.registerTool(
    'list_ingested_repos',
    {
      title: 'List Ingested Repositories',
      description:
        'List all repositories that have been ingested into the knowledge base. ' +
        'Shows job IDs, status, file counts, and timestamps. ' +
        'Use the job_id from a previous session to resume chatting about a repo.',
      inputSchema: {},
    },
    async () => handleListIngestedRepos(),
  );

  // ── Tool: query_symbols ───────────────────────────────────────────────────
  server.registerTool(
    'query_symbols',
    {
      title: 'Query Symbols',
      description:
        'Search the indexed knowledge base for functions, classes, types, variables, and other symbols. ' +
        'Filter by name (partial match), symbol type, or file path. ' +
        'Use this to answer: "where is X defined?", "what functions are in file Y?", ' +
        '"list all exported types", "find all classes".',
      inputSchema: querySymbolsSchema,
    },
    async (args) => handleQuerySymbols(args),
  );

  // ── Tool: get_import_edges ────────────────────────────────────────────────
  server.registerTool(
    'get_import_edges',
    {
      title: 'Get Import Edges',
      description:
        'Return the import/dependency edges for a file or the entire repo. ' +
        'Use direction="outgoing" to see what a file imports, ' +
        '"incoming" to see what imports a file, or "both" for the full picture. ' +
        'Answers: "what does source/index.ts import?", "what depends on utils.ts?"',
      inputSchema: getImportEdgesSchema,
    },
    async (args) => handleGetImportEdges(args),
  );

  // ── Tool: get_repo_summary ────────────────────────────────────────────────
  server.registerTool(
    'get_repo_summary',
    {
      title: 'Get Repository Summary',
      description:
        'Get a high-level structural overview of an ingested repository. ' +
        'Returns: file breakdown by language, symbol type distribution, ' +
        'most-imported internal files, external dependencies, and richest files by symbol count. ' +
        'Use this first when exploring a new repo to understand its structure.',
      inputSchema: getRepoSummarySchema,
    },
    async (args) => handleGetRepoSummary(args),
  );

  logger.info('Groundwork MCP server created with 6 tools registered');
  return server;
}
