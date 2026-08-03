/**
 * Groundwork MCP Server — Git Cloner
 *
 * Clones a GitHub repository into a sandboxed local directory.
 * Uses shallow clone (--depth 1) to minimize disk and network usage.
 * Captures the HEAD commit SHA for tracking/re-ingestion.
 *
 * Zero-cost: uses system git via simple-git, no hosted service.
 */

import { simpleGit, type SimpleGit } from 'simple-git';
import { join } from 'node:path';
import { existsSync, rmSync } from 'node:fs';
import { config } from '../utils/config.js';
import { logger } from '../utils/logger.js';
import { validateRepoUrl, extractRepoName } from '../utils/security.js';
import type { CloneResult } from './types.js';

/**
 * Clone a GitHub repository into the Groundwork data directory.
 *
 * @param repoUrl - Full HTTPS GitHub URL
 * @param jobId - Unique job ID (used as clone directory name)
 * @param branch - Branch to clone (default: repo's default branch)
 * @returns CloneResult with the clone path, commit SHA, and extracted repo name
 *
 * Security measures:
 * - URL validated to be GitHub HTTPS only
 * - Shallow clone (--depth 1) to limit disk usage
 * - Timeout enforced to prevent hanging on huge repos
 * - Clone directory is isolated per-job
 */
export async function cloneRepo(
  repoUrl: string,
  jobId: string,
  branch?: string,
): Promise<CloneResult> {
  // Validate URL format
  const validation = validateRepoUrl(repoUrl);
  if (!validation.valid) {
    throw new Error(`Invalid repository URL: ${validation.error}`);
  }

  const repoName = extractRepoName(repoUrl);
  const clonePath = join(config.reposDir, jobId);

  // Clean up if a previous clone exists for this job
  if (existsSync(clonePath)) {
    logger.warn(`Removing existing clone directory: ${clonePath}`);
    rmSync(clonePath, { recursive: true, force: true });
  }

  logger.info(`Cloning ${repoUrl} (branch: ${branch || 'default'}) into ${clonePath}`);

  // Configure git with timeout
  const git: SimpleGit = simpleGit({
    timeout: {
      block: config.cloneTimeoutMs,
    },
  });

  try {
    // Build clone arguments
    const cloneArgs: string[] = [
      '--depth', '1',          // Shallow clone — one commit only
      '--single-branch',       // Don't fetch other branches
    ];

    if (branch) {
      cloneArgs.push('--branch', branch);
    }

    await git.clone(repoUrl, clonePath, cloneArgs);

    // Get the HEAD commit SHA from the cloned repo
    const clonedGit = simpleGit(clonePath);
    const log = await clonedGit.log({ maxCount: 1 });
    const commitSha = log.latest?.hash || 'unknown';

    logger.info(`Clone complete: ${repoName} @ ${commitSha.substring(0, 8)}`);

    return {
      clonePath,
      commitSha,
      repoName,
    };
  } catch (error) {
    // Clean up failed clone
    if (existsSync(clonePath)) {
      rmSync(clonePath, { recursive: true, force: true });
    }

    const message = error instanceof Error ? error.message : String(error);

    if (message.includes('timeout')) {
      throw new Error(
        `Clone timed out after ${config.cloneTimeoutMs / 1000}s. ` +
        `The repository may be too large. Try a specific branch or use --exclude.`
      );
    }

    if (message.includes('not found') || message.includes('404')) {
      throw new Error(
        `Repository not found: ${repoUrl}. ` +
        `Ensure the URL is correct and the repository is public.`
      );
    }

    throw new Error(`Failed to clone ${repoUrl}: ${message}`);
  }
}

/**
 * Remove a cloned repository from disk.
 */
export function removeClone(jobId: string): void {
  const clonePath = join(config.reposDir, jobId);
  if (existsSync(clonePath)) {
    rmSync(clonePath, { recursive: true, force: true });
    logger.info(`Removed clone directory: ${clonePath}`);
  }
}
