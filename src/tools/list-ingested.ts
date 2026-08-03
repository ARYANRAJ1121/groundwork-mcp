/**
 * Groundwork MCP — Tool: list_ingested_repos
 *
 * Lists all repositories that have been ingested (or are in progress).
 * Lets users resume chatting about a repo ingested in a previous session.
 */

import { z } from 'zod';
import { listJobs } from '../store/database.js';

// ─── Input Schema ─────────────────────────────────────────────────────────────

export const listIngestedReposSchema = {};  // No inputs needed

// ─── Handler ──────────────────────────────────────────────────────────────────

export async function handleListIngestedRepos(): Promise<{
  content: Array<{ type: 'text'; text: string }>;
}> {
  const jobs = listJobs();

  if (jobs.length === 0) {
    return {
      content: [{
        type: 'text',
        text: JSON.stringify({
          repos: [],
          message: 'No repositories ingested yet. Use ingest_repo(repo_url) to get started.',
        }, null, 2),
      }],
    };
  }

  const repos = jobs.map(job => ({
    job_id: job.id,
    name: job.repo_name,
    repo_url: job.repo_url,
    branch: job.branch,
    status: job.status,
    files_indexed: job.files_processed,
    tokens_estimate: job.tokens_estimate,
    ingested_at: job.created_at,
    last_updated: job.updated_at,
    ...(job.commit_sha ? { commit_sha: job.commit_sha } : {}),
    ...(job.error_message ? { error: job.error_message } : {}),
  }));

  const complete = repos.filter(r => r.status === 'complete').length;
  const inProgress = repos.filter(r =>
    ['queued', 'cloning', 'sieving', 'parsing'].includes(r.status)
  ).length;

  return {
    content: [{
      type: 'text',
      text: JSON.stringify({
        total: repos.length,
        complete,
        in_progress: inProgress,
        repos,
      }, null, 2),
    }],
  };
}
