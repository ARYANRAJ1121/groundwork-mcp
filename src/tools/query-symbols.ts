/**
 * Groundwork MCP — Tool: query_symbols
 *
 * Search the indexed knowledge base for symbols by name, type, or file.
 * This is the primary query tool — lets Claude answer "where is X defined?"
 * "what functions are in file Y?" etc. from the local SQLite index.
 */

import { z } from 'zod';
import { getJob } from '../store/database.js';
import { getDatabase } from '../store/database.js';

// ─── Input Schema ─────────────────────────────────────────────────────────────

export const querySymbolsSchema = {
  job_id: z
    .string()
    .uuid()
    .describe('The job_id returned by ingest_repo or list_ingested_repos'),
  name: z
    .string()
    .optional()
    .describe('Symbol name to search (supports partial match, case-insensitive)'),
  symbol_type: z
    .enum(['function', 'class', 'method', 'variable', 'export', 'interface', 'type_alias', 'enum'])
    .optional()
    .describe('Filter by symbol type'),
  file_path: z
    .string()
    .optional()
    .describe('Filter to a specific file path (partial match)'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(200)
    .default(50)
    .describe('Maximum number of results to return (default 50)'),
};

// ─── Handler ──────────────────────────────────────────────────────────────────

export async function handleQuerySymbols(args: {
  job_id: string;
  name?: string;
  symbol_type?: string;
  file_path?: string;
  limit?: number;
}): Promise<{ content: Array<{ type: 'text'; text: string }> }> {
  const { job_id, name, symbol_type, file_path, limit = 50 } = args;

  // Verify job exists and is complete
  const job = getJob(job_id);
  if (!job) {
    return errorResponse(`Job not found: ${job_id}. Use list_ingested_repos() to see available job IDs.`);
  }
  if (job.status !== 'complete') {
    return errorResponse(`Job ${job_id} is not complete yet (status: ${job.status}). Wait for ingestion to finish.`);
  }

  const db = getDatabase();

  // Build dynamic query
  const conditions: string[] = ['s.job_id = ?'];
  const params: unknown[] = [job_id];

  if (name) {
    conditions.push("LOWER(s.symbol_name) LIKE LOWER(?)");
    params.push(`%${name}%`);
  }
  if (symbol_type) {
    conditions.push('s.symbol_type = ?');
    params.push(symbol_type);
  }
  if (file_path) {
    conditions.push("s.file_path LIKE ?");
    params.push(`%${file_path}%`);
  }

  params.push(limit);

  const sql = `
    SELECT s.symbol_name, s.symbol_type, s.file_path, s.start_line, s.end_line, s.signature
    FROM symbols s
    WHERE ${conditions.join(' AND ')}
    ORDER BY s.file_path, s.start_line
    LIMIT ?
  `;

  const stmt = db.prepare(sql);
  stmt.bind(params);

  const results: Array<{
    name: string;
    type: string;
    file: string;
    line: number;
    end_line: number;
    signature?: string;
  }> = [];

  while (stmt.step()) {
    const row = stmt.getAsObject() as Record<string, unknown>;
    results.push({
      name: row.symbol_name as string,
      type: row.symbol_type as string,
      file: row.file_path as string,
      line: row.start_line as number,
      end_line: row.end_line as number,
      ...(row.signature ? { signature: row.signature as string } : {}),
    });
  }
  stmt.free();

  if (results.length === 0) {
    return {
      content: [{
        type: 'text',
        text: JSON.stringify({
          repo: job.repo_name,
          query: { name, symbol_type, file_path },
          count: 0,
          symbols: [],
          message: 'No symbols matched the query. Try a broader search or check the file path.',
        }, null, 2),
      }],
    };
  }

  return {
    content: [{
      type: 'text',
      text: JSON.stringify({
        repo: job.repo_name,
        query: { name, symbol_type, file_path },
        count: results.length,
        symbols: results,
      }, null, 2),
    }],
  };
}

function errorResponse(message: string) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify({ error: message }, null, 2) }],
  };
}
