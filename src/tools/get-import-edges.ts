/**
 * Groundwork MCP — Tool: get_import_edges
 *
 * Returns the import/dependency edges for a file or the entire repo.
 * Answers "what does file X import?" and "what imports file Y?"
 */

import { z } from 'zod';
import { getJob, getDatabase } from '../store/database.js';

// ─── Input Schema ─────────────────────────────────────────────────────────────

export const getImportEdgesSchema = {
  job_id: z
    .string()
    .uuid()
    .describe('The job_id from ingest_repo or list_ingested_repos'),
  file_path: z
    .string()
    .optional()
    .describe('Source file path to get edges for (partial match). Omit to get all edges.'),
  direction: z
    .enum(['outgoing', 'incoming', 'both'])
    .default('outgoing')
    .describe('"outgoing" = what this file imports. "incoming" = what imports this file. "both" = all.'),
};

// ─── Handler ──────────────────────────────────────────────────────────────────

export async function handleGetImportEdges(args: {
  job_id: string;
  file_path?: string;
  direction?: string;
}): Promise<{ content: Array<{ type: 'text'; text: string }> }> {
  const { job_id, file_path, direction = 'outgoing' } = args;

  const job = getJob(job_id);
  if (!job) {
    return errorResponse(`Job not found: ${job_id}`);
  }
  if (job.status !== 'complete') {
    return errorResponse(`Job ${job_id} is not complete (status: ${job.status})`);
  }

  const db = getDatabase();
  const edges: Array<{
    source: string;
    target: string | null;
    module: string;
    type: string;
  }> = [];

  if (direction === 'outgoing' || direction === 'both') {
    // What does this file import?
    let sql = `SELECT source_file, target_file, target_module, edge_type FROM edges WHERE job_id = ?`;
    const params: unknown[] = [job_id];
    if (file_path) {
      sql += ` AND source_file LIKE ?`;
      params.push(`%${file_path}%`);
    }
    sql += ` ORDER BY source_file, target_module LIMIT 500`;

    const stmt = db.prepare(sql);
    stmt.bind(params);
    while (stmt.step()) {
      const r = stmt.getAsObject() as Record<string, unknown>;
      edges.push({
        source: r.source_file as string,
        target: r.target_file as string | null,
        module: r.target_module as string,
        type: r.edge_type as string,
      });
    }
    stmt.free();
  }

  if (direction === 'incoming' || direction === 'both') {
    // What imports this file?
    if (!file_path) {
      return errorResponse('file_path is required for direction="incoming"');
    }
    const sql = `SELECT source_file, target_file, target_module, edge_type FROM edges WHERE job_id = ? AND target_file LIKE ? ORDER BY source_file LIMIT 500`;
    const stmt = db.prepare(sql);
    stmt.bind([job_id, `%${file_path}%`]);
    while (stmt.step()) {
      const r = stmt.getAsObject() as Record<string, unknown>;
      edges.push({
        source: r.source_file as string,
        target: r.target_file as string | null,
        module: r.target_module as string,
        type: r.edge_type as string,
      });
    }
    stmt.free();
  }

  // Group by source file for readability
  const grouped: Record<string, { imports: Array<{ target?: string; module: string; type: string }> }> = {};
  for (const e of edges) {
    if (!grouped[e.source]) grouped[e.source] = { imports: [] };
    grouped[e.source].imports.push({
      ...(e.target ? { target: e.target } : {}),
      module: e.module,
      type: e.type,
    });
  }

  return {
    content: [{
      type: 'text',
      text: JSON.stringify({
        repo: job.repo_name,
        file_path: file_path ?? '(all files)',
        direction,
        total_edges: edges.length,
        by_file: grouped,
      }, null, 2),
    }],
  };
}

function errorResponse(message: string) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify({ error: message }, null, 2) }],
  };
}
