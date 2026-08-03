#!/usr/bin/env node
/**
 * Groundwork MCP Server — Entry Point
 *
 * Bootstraps the server:
 *   1. Initialize SQLite database
 *   2. Create MCP server with registered tools
 *   3. Connect via stdio transport (for Claude Desktop / npx usage)
 *   4. Handle graceful shutdown
 *
 * Usage:
 *   node build/index.js         (after npm run build)
 *   npx groundwork-mcp          (published npm package)
 *
 * MCP config (claude_desktop_config.json):
 *   {
 *     "mcpServers": {
 *       "groundwork": {
 *         "command": "node",
 *         "args": ["/absolute/path/to/groundwork-mcp/build/index.js"]
 *       }
 *     }
 *   }
 */

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { initDatabase, closeDatabase } from './store/database.js';
import { createServer } from './server.js';
import { logger } from './utils/logger.js';

async function main(): Promise<void> {
  logger.info('Groundwork MCP Server starting...');

  // Initialize the SQLite database (creates tables if needed)
  await initDatabase();

  // Create the MCP server with all tools registered
  const server = createServer();

  // Connect via stdio transport (required for MCP protocol)
  // IMPORTANT: After this point, stdout is owned by the MCP transport.
  // All logging must go to stderr — never console.log after this line.
  const transport = new StdioServerTransport();
  await server.connect(transport);

  logger.info('Groundwork MCP Server running on stdio — ready for connections');

  // ── Graceful shutdown ───────────────────────────────────────────────
  const shutdown = () => {
    logger.info('Shutting down Groundwork MCP Server...');
    closeDatabase();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  // Keep the process alive
  process.on('uncaughtException', (error) => {
    logger.error('Uncaught exception:', error);
    // Don't exit — MCP servers should stay up through recoverable errors
  });

  process.on('unhandledRejection', (reason) => {
    logger.error('Unhandled rejection:', reason);
  });
}

main().catch((error) => {
  // Write to stderr — stdout is reserved for MCP transport
  process.stderr.write(`Fatal error: ${error}\n`);
  process.exit(1);
});
