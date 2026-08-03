/**
 * Groundwork MCP Server — The Sieve
 *
 * Filters a cloned repository down to parseable, relevant source files.
 * Strips binary files, .git internals, dependency directories, lock files,
 * and anything over the size threshold — before anything touches the parser.
 *
 * This is a deterministic, no-LLM step. Pure file-system traversal.
 */

import { readdirSync, statSync } from 'node:fs';
import { join, extname, basename, relative } from 'node:path';
import { config } from '../utils/config.js';
import { logger } from '../utils/logger.js';
import {
  isBinaryFile,
  SKIP_DIRECTORIES,
  SKIP_FILES,
  checkRepoLimits,
} from '../utils/security.js';
import type { SievedFile, SieveResult, SupportedLanguage } from './types.js';

/**
 * Run the Sieve on a cloned repository directory.
 *
 * Steps:
 * 1. Check total file count and size against limits
 * 2. Recursively walk the directory tree
 * 3. Skip binary files, excluded directories, lock files, oversized files
 * 4. Keep only files with supported extensions
 * 5. Return an ordered list of files ready for parsing
 *
 * @param repoPath - Absolute path to the cloned repository root
 * @returns SieveResult with the filtered file list and statistics
 */
export function sieveRepo(repoPath: string): SieveResult {
  logger.info(`Running Sieve on: ${repoPath}`);

  // Step 1: Pre-check repo limits (fast bail on oversized repos)
  const limits = checkRepoLimits(repoPath);
  if (!limits.withinLimits) {
    throw new Error(limits.error || 'Repository exceeds size limits');
  }

  const files: SievedFile[] = [];
  let skippedFiles = 0;
  const skippedReasons: Record<string, number> = {};

  function recordSkip(reason: string): void {
    skippedFiles++;
    skippedReasons[reason] = (skippedReasons[reason] || 0) + 1;
  }

  // Step 2-4: Recursive directory walk with filtering
  function walk(dirPath: string): void {
    let entries: string[];
    try {
      entries = readdirSync(dirPath);
    } catch {
      recordSkip('unreadable_directory');
      return;
    }

    // Sort entries for deterministic ordering
    entries.sort();

    for (const entry of entries) {
      const fullPath = join(dirPath, entry);
      const relativePath = relative(repoPath, fullPath);

      let stat;
      try {
        stat = statSync(fullPath);
      } catch {
        recordSkip('unreadable_file');
        continue;
      }

      // ── Directory filtering ──────────────────────────────────────────
      if (stat.isDirectory()) {
        // Skip known noise directories
        if (SKIP_DIRECTORIES.has(entry)) {
          recordSkip(`skipped_directory:${entry}`);
          continue;
        }

        // Skip hidden directories (starting with .)
        if (entry.startsWith('.') && entry !== '.') {
          recordSkip('hidden_directory');
          continue;
        }

        // Recurse into the directory
        walk(fullPath);
        continue;
      }

      // ── File filtering ───────────────────────────────────────────────
      if (!stat.isFile()) {
        recordSkip('not_regular_file');
        continue;
      }

      const fileName = basename(entry);

      // Skip known lock/noise files
      if (SKIP_FILES.has(fileName)) {
        recordSkip('lock_file');
        continue;
      }

      // Skip hidden files
      if (fileName.startsWith('.') && fileName !== '.env.example') {
        recordSkip('hidden_file');
        continue;
      }

      // Skip binary files
      if (isBinaryFile(fullPath)) {
        recordSkip('binary_file');
        continue;
      }

      // Skip oversized files
      if (stat.size > config.maxSingleFileSizeBytes) {
        recordSkip('oversized_file');
        logger.debug(`Skipping oversized file: ${relativePath} (${(stat.size / 1024 / 1024).toFixed(1)}MB)`);
        continue;
      }

      // Skip empty files
      if (stat.size === 0) {
        recordSkip('empty_file');
        continue;
      }

      // Check if the extension is supported
      const ext = extname(fileName).toLowerCase();
      const language = config.supportedExtensions[ext];

      if (!language) {
        recordSkip('unsupported_extension');
        continue;
      }

      // ── File passes all filters — include it ─────────────────────────
      files.push({
        relativePath: relativePath.replace(/\\/g, '/'),  // Normalize to forward slashes
        absolutePath: fullPath,
        language: language as SupportedLanguage,
        sizeBytes: stat.size,
      });
    }
  }

  walk(repoPath);

  // Step 5: Sort by path for consistent ordering
  files.sort((a, b) => a.relativePath.localeCompare(b.relativePath));

  const totalSizeBytes = files.reduce((sum, f) => sum + f.sizeBytes, 0);

  logger.info(
    `Sieve complete: ${files.length} files kept, ${skippedFiles} skipped ` +
    `(${(totalSizeBytes / 1024).toFixed(0)}KB total)`
  );

  if (Object.keys(skippedReasons).length > 0) {
    logger.debug('Skip reasons:', skippedReasons);
  }

  return {
    files,
    totalFiles: files.length,
    totalSizeBytes,
    skippedFiles,
    skippedReasons,
  };
}
