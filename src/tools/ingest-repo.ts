/**
 * Groundwork MCP — Tool: ingest_repo
 *
 * Validates the URL, creates a job record, returns the job_id immediately,
 * then kicks off the async ingestion pipeline in the background.
 *
 * The MCP client polls get_ingest_status(job_id) to track progress.
 */

import { z } from 'zod';
import { v4 as uuidv4 } from 'uuid';
import { createJob } from '../store/database.js';
import { runIngestionPipeline } from '../core/pipeline.js';
import { validateRepoUrl, extractRepoName } from '../utils/security.js';
import { logger } from '../utils/logger.js';

// ─── Input Schema ─────────────────────────────────────────────────────────────

export const ingestRepoSchema = {
  repo_url: z
    .string()
    .url()
    .describe('Full HTTPS GitHub URL, e.g. https://github.com/owner/repo'),
  branch: z
    .string()
    .optional()
    .describe("Branch to clone (default: the repo's default branch)"),
};

// ─── Handler ──────────────────────────────────────────────────────────────────

export async function handleIngestRepo(args: {
  repo_url: string;
  branch?: string;
}): Promise<{ content: Array<{ type: 'text'; text: string }> }> {
  const { repo_url, branch } = args;

  // Validate the URL before creating any job record
  const validation = validateRepoUrl(repo_url);
  if (!validation.valid) {
    return {
      content: [{
        type: 'text',
        text: JSON.stringify({
          error: validation.error,
          hint: 'URL must be a public GitHub HTTPS URL: https://github.com/<owner>/<repo>',
        }, null, 2),
      }],
    };
  }

  const jobId = uuidv4();
  const repoName = extractRepoName(repo_url);

  // Create the job record synchronously — returns immediately
  createJob(jobId, repo_url, repoName, branch || 'default');

  logger.info(`ingest_repo: created job ${jobId} for ${repoName}`);

  // Kick off the pipeline asynchronously — do NOT await
  // Use setImmediate so the MCP response is sent before the pipeline starts
  setImmediate(() => {
    runIngestionPipeline(jobId, repo_url, branch).catch(err => {
      logger.error(`Pipeline error for job ${jobId}: ${err}`);
    });
  });

  return {
    content: [{
      type: 'text',
      text: JSON.stringify({
        job_id: jobId,
        status: 'queued',
        repo_name: repoName,
        message: `Ingestion started. Poll get_ingest_status("${jobId}") to track progress.`,
      }, null, 2),
    }],
  };
}
