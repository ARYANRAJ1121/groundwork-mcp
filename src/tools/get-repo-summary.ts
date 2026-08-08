/**
 * Groundwork MCP — Tool: get_repo_summary
 *
 * Returns a high-level summary of an ingested repo:
 * file breakdown by language, top-level modules, symbol type distribution,
 * most-imported files. The "entry point" for exploring a new codebase.
 */

import { z } from 'zod';
import { getJob, getDatabase } from '../store/database.js';

// ─── Input Schema ─────────────────────────────────────────────────────────────

export const getRepoSummarySchema = {
  job_id: z
    .string()
    .uuid()
    .describe('The job_id from ingest_repo or list_ingested_repos'),
};

// ─── Handler ──────────────────────────────────────────────────────────────────

export async function handleGetRepoSummary(args: {
  job_id: string;
}): Promise<{ content: Array<{ type: 'text'; text: string }> }> {
  const { job_id } = args;

  const job = getJob(job_id);
  if (!job) {
    return errorResponse(`Job not found: ${job_id}. Use list_ingested_repos() to see available job IDs.`);
  }
  if (job.status !== 'complete') {
    return errorResponse(`Job ${job_id} is not complete (status: ${job.status}). Wait for ingestion.`);
  }

  const db = getDatabase();

  // Files by language
  const langStmt = db.prepare(
    `SELECT language, COUNT(*) as count, SUM(line_count) as lines, SUM(size_bytes) as bytes
     FROM parsed_files WHERE job_id = ? GROUP BY language ORDER BY count DESC`
  );
  langStmt.bind([job_id]);
  const byLanguage: Record<string, { files: number; lines: number; sizeKb: number }> = {};
  while (langStmt.step()) {
    const r = langStmt.getAsObject() as Record<string, unknown>;
    byLanguage[r.language as string] = {
      files: r.count as number,
      lines: r.lines as number,
      sizeKb: Math.round((r.bytes as number) / 1024),
    };
  }
  langStmt.free();

  // Symbol type distribution
  const symStmt = db.prepare(
    `SELECT symbol_type, COUNT(*) as count FROM symbols WHERE job_id = ? GROUP BY symbol_type ORDER BY count DESC`
  );
  symStmt.bind([job_id]);
  const bySymbolType: Record<string, number> = {};
  while (symStmt.step()) {
    const r = symStmt.getAsObject() as Record<string, unknown>;
    bySymbolType[r.symbol_type as string] = r.count as number;
  }
  symStmt.free();

  // Most-imported files (by incoming edge count)
  const importedStmt = db.prepare(
    `SELECT target_file, COUNT(*) as import_count
     FROM edges WHERE job_id = ? AND target_file IS NOT NULL
     GROUP BY target_file ORDER BY import_count DESC LIMIT 10`
  );
  importedStmt.bind([job_id]);
  const mostImported: Array<{ file: string; imported_by: number }> = [];
  while (importedStmt.step()) {
    const r = importedStmt.getAsObject() as Record<string, unknown>;
    mostImported.push({
      file: r.target_file as string,
      imported_by: r.import_count as number,
    });
  }
  importedStmt.free();

  // External dependencies (most common external imports)
  const extStmt = db.prepare(
    `SELECT target_module, COUNT(*) as count
     FROM edges WHERE job_id = ? AND target_file IS NULL
     GROUP BY target_module ORDER BY count DESC LIMIT 20`
  );
  extStmt.bind([job_id]);
  const externalDeps: Array<{ module: string; used_in: number }> = [];
  while (extStmt.step()) {
    const r = extStmt.getAsObject() as Record<string, unknown>;
    externalDeps.push({
      module: r.target_module as string,
      used_in: r.count as number,
    });
  }
  extStmt.free();

  // Top files by symbol count
  const topFilesStmt = db.prepare(
    `SELECT file_path, COUNT(*) as symbol_count
     FROM symbols WHERE job_id = ? GROUP BY file_path ORDER BY symbol_count DESC LIMIT 10`
  );
  topFilesStmt.bind([job_id]);
  const topFiles: Array<{ file: string; symbols: number }> = [];
  while (topFilesStmt.step()) {
    const r = topFilesStmt.getAsObject() as Record<string, unknown>;
    topFiles.push({
      file: r.file_path as string,
      symbols: r.symbol_count as number,
    });
  }
  topFilesStmt.free();

  return {
    content: [{
      type: 'text',
      text: JSON.stringify({
        repo: job.repo_name,
        repo_url: job.repo_url,
        commit_sha: job.commit_sha,
        ingested_at: job.created_at,
        totals: {
          files: job.files_processed,
          tokens_estimate: job.tokens_estimate,
        },
        by_language: byLanguage,
        by_symbol_type: bySymbolType,
        most_imported_files: mostImported,
        external_dependencies: externalDeps,
        richest_files: topFiles,
      }, null, 2),
    }],
  };
}

function errorResponse(message: string) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify({ error: message }, null, 2) }],
  };
}
