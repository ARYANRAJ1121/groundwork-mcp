/**
 * Groundwork MCP Server — Async Ingestion Pipeline
 *
 * Orchestrates the full clone → sieve → parse → store flow for a job.
 * Runs asynchronously so ingest_repo returns immediately with a job_id.
 * Updates job status/progress in SQLite at each phase.
 *
 * Error handling: any failure marks the job as 'failed' with an error_message.
 * Never throws — all errors are captured and stored.
 */

import { cloneRepo } from './cloner.js';
import { sieveRepo } from './sieve.js';
import { parseAllFiles, initParser } from './parser.js';
import {
  updateJobStatus,
  insertParsedFile,
  insertSymbols,
  insertEdges,
  persistAfterBatch,
} from '../store/database.js';
import { logger } from '../utils/logger.js';

/**
 * Run the full ingestion pipeline for a job.
 *
 * Phases:
 *  1. cloning   — git clone (shallow)
 *  2. sieving   — filter files
 *  3. parsing   — tree-sitter AST extraction
 *  4. complete  — all data stored
 *
 * @param jobId - The job ID (must already exist in SQLite)
 * @param repoUrl - Full HTTPS GitHub URL
 * @param branch - Optional branch name
 */
export async function runIngestionPipeline(
  jobId: string,
  repoUrl: string,
  branch?: string,
): Promise<void> {
  logger.info(`[pipeline:${jobId}] Starting ingestion for ${repoUrl}`);

  // ── Phase 1: Clone ──────────────────────────────────────────────────
  try {
    updateJobStatus(jobId, { status: 'cloning', progress: 0.05 });

    const cloneResult = await cloneRepo(repoUrl, jobId, branch);

    updateJobStatus(jobId, {
      commit_sha: cloneResult.commitSha,
      clone_path: cloneResult.clonePath,
      progress: 0.2,
    });

    logger.info(`[pipeline:${jobId}] Clone done @ ${cloneResult.commitSha.substring(0, 8)}`);

    // ── Phase 2: Sieve ────────────────────────────────────────────────
    updateJobStatus(jobId, { status: 'sieving', progress: 0.25 });

    const sieveResult = sieveRepo(cloneResult.clonePath);

    updateJobStatus(jobId, {
      files_total: sieveResult.totalFiles,
      progress: 0.35,
    });

    logger.info(`[pipeline:${jobId}] Sieve done — ${sieveResult.totalFiles} files to parse`);

    // ── Phase 3: Parse ────────────────────────────────────────────────
    updateJobStatus(jobId, { status: 'parsing', progress: 0.4 });

    // Ensure tree-sitter WASM is initialized
    await initParser();

    let filesProcessed = 0;
    let totalTokens = 0;

    const parseResults = await parseAllFiles(
      sieveResult.files,
      cloneResult.clonePath,
      (processed, total, currentFile) => {
        filesProcessed = processed;
        const progress = 0.4 + (processed / total) * 0.55; // 0.4 → 0.95

        updateJobStatus(jobId, {
          files_processed: processed,
          progress: Math.min(progress, 0.95),
        });

        if (processed % 50 === 0 || processed === total) {
          logger.info(`[pipeline:${jobId}] Parsed ${processed}/${total} — ${currentFile}`);
        }
      },
    );

    // Store all results in SQLite
    for (const result of parseResults) {
      // Accumulate token estimate
      const fileTokens = result.file.astJson
        ? Math.ceil(result.file.astJson.length / 4)
        : Math.ceil(result.file.sizeBytes / 4);
      totalTokens += fileTokens;

      insertParsedFile(jobId, result.file);

      if (result.symbols.length > 0) {
        insertSymbols(jobId, result.symbols);
      }
      if (result.edges.length > 0) {
        insertEdges(jobId, result.edges);
      }
    }

    // Persist everything to disk at once
    persistAfterBatch();

    // ── Phase 4: Complete ─────────────────────────────────────────────
    updateJobStatus(jobId, {
      status: 'complete',
      progress: 1.0,
      files_processed: filesProcessed,
      tokens_estimate: totalTokens,
    });

    logger.info(
      `[pipeline:${jobId}] Complete — ` +
      `${filesProcessed} files, ~${totalTokens.toLocaleString()} tokens`
    );

  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    logger.error(`[pipeline:${jobId}] Failed: ${message}`);

    updateJobStatus(jobId, {
      status: 'failed',
      error_message: message,
    });
  }
}
