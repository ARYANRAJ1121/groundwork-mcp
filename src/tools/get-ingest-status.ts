/**
 * Groundwork MCP — Tool: get_ingest_status
 *
 * Returns the current status and progress of an ingestion job.
 * Clients poll this after calling ingest_repo.
 */

import { z } from 'zod';
import { getJob } from '../store/database.js';
import { logger } from '../utils/logger.js';

// ─── Input Schema ─────────────────────────────────────────────────────────────

export const getIngestStatusSchema = {
  job_id: z
    .string()
    .uuid()
    .describe('The job_id returned by ingest_repo'),
};

// ─── Handler ──────────────────────────────────────────────────────────────────

export async function handleGetIngestStatus(args: {
  job_id: string;
}): Promise<{ content: Array<{ type: 'text'; text: string }> }> {
  const { job_id } = args;

  const job = getJob(job_id);

  if (!job) {
    return {
      content: [{
        type: 'text',
        text: JSON.stringify({
          error: `Job not found: ${job_id}`,
          hint: 'Use list_ingested_repos() to see all known job IDs.',
        }, null, 2),
      }],
    };
  }

  const progressPct = Math.round(job.progress * 100);

  const response: Record<string, unknown> = {
    job_id: job.id,
    repo_name: job.repo_name,
    repo_url: job.repo_url,
    branch: job.branch,
    status: job.status,
    progress_pct: progressPct,
    files_processed: job.files_processed,
    files_total: job.files_total,
    tokens_estimate: job.tokens_estimate,
    started_at: job.created_at,
    updated_at: job.updated_at,
  };

  if (job.commit_sha) response.commit_sha = job.commit_sha;
  if (job.error_message) response.error = job.error_message;

  // Add a human-readable status message
  const statusMessages: Record<string, string> = {
    queued: 'Job is queued and will start shortly.',
    cloning: `Cloning repository from GitHub...`,
    sieving: 'Filtering source files...',
    parsing: `Parsing source files — ${job.files_processed}/${job.files_total} done (${progressPct}%)`,
    complete: `Ingestion complete — ${job.files_processed} files, ~${job.tokens_estimate.toLocaleString()} tokens indexed.`,
    failed: `Ingestion failed: ${job.error_message}`,
  };
  response.message = statusMessages[job.status] || job.status;

  return {
    content: [{
      type: 'text',
      text: JSON.stringify(response, null, 2),
    }],
  };
}
