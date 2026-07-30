/**
 * Groundwork MCP Server — Security Utilities
 *
 * URL validation, size caps, binary detection — the guardrails that
 * prevent RCE, zip-bombs, and resource exhaustion from untrusted repos.
 */

import { statSync, readdirSync } from 'node:fs';
import { join, extname } from 'node:path';
import { config } from './config.js';
import { logger } from './logger.js';

// ─── URL Validation ──────────────────────────────────────────────────────────

const GITHUB_URL_REGEX = /^https:\/\/github\.com\/[\w.\-]+\/[\w.\-]+(\.git)?$/;

/**
 * Validates that a URL is a public GitHub HTTPS URL.
 * Rejects SSH, local paths, non-GitHub hosts, and malformed URLs.
 */
export function validateRepoUrl(url: string): { valid: boolean; error?: string } {
  if (!url || typeof url !== 'string') {
    return { valid: false, error: 'Repository URL is required' };
  }

  const trimmed = url.trim();

  // Must be HTTPS
  if (!trimmed.startsWith('https://')) {
    return { valid: false, error: 'Only HTTPS GitHub URLs are supported (no SSH, git://, or local paths)' };
  }

  // Must match GitHub pattern
  if (!GITHUB_URL_REGEX.test(trimmed)) {
    return {
      valid: false,
      error: `Invalid GitHub URL format. Expected: https://github.com/<owner>/<repo> — got: ${trimmed}`,
    };
  }

  return { valid: true };
}

/**
 * Extracts the repo name from a GitHub URL.
 * e.g. "https://github.com/expressjs/express" -> "expressjs/express"
 */
export function extractRepoName(url: string): string {
  const match = url.match(/github\.com\/([\w.\-]+\/[\w.\-]+)/);
  if (!match) throw new Error(`Cannot extract repo name from URL: ${url}`);
  return match[1].replace(/\.git$/, '');
}

// ─── Repository Size Checks ─────────────────────────────────────────────────

interface RepoLimitsResult {
  withinLimits: boolean;
  totalFiles: number;
  totalSizeBytes: number;
  error?: string;
}

/**
 * Recursively counts files and total size in a directory.
 * Enforces MAX_FILE_COUNT and MAX_REPO_SIZE caps.
 * Bails out early if either limit is exceeded.
 */
export function checkRepoLimits(dirPath: string): RepoLimitsResult {
  let totalFiles = 0;
  let totalSizeBytes = 0;

  function walk(dir: string): boolean {
    let entries: string[];
    try {
      entries = readdirSync(dir);
    } catch {
      // Permission denied or broken symlinks — skip
      return true;
    }

    for (const entry of entries) {
      // Skip .git directory entirely
      if (entry === '.git') continue;

      const fullPath = join(dir, entry);
      let stat;
      try {
        stat = statSync(fullPath);
      } catch {
        continue;  // Broken symlink or permission issue
      }

      if (stat.isDirectory()) {
        if (!walk(fullPath)) return false;
      } else if (stat.isFile()) {
        totalFiles++;
        totalSizeBytes += stat.size;

        if (totalFiles > config.maxFileCount) {
          return false;
        }
        if (totalSizeBytes > config.maxRepoSizeBytes) {
          return false;
        }
      }
    }
    return true;
  }

  const withinLimits = walk(dirPath);

  if (!withinLimits) {
    const error = totalFiles > config.maxFileCount
      ? `Repository exceeds maximum file count (${totalFiles} > ${config.maxFileCount}). Use --max-files or --exclude to scope down.`
      : `Repository exceeds maximum size (${(totalSizeBytes / 1024 / 1024).toFixed(1)}MB > ${(config.maxRepoSizeBytes / 1024 / 1024).toFixed(0)}MB). Use --exclude to scope down.`;

    logger.warn('Repo limits exceeded', { totalFiles, totalSizeBytes, error });
    return { withinLimits: false, totalFiles, totalSizeBytes, error };
  }

  return { withinLimits: true, totalFiles, totalSizeBytes };
}

// ─── Binary File Detection ───────────────────────────────────────────────────

/** Extensions that are always binary — never parse these. */
const BINARY_EXTENSIONS = new Set([
  // Images
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp', '.avif', '.tiff',
  // Audio/Video
  '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv', '.flac', '.ogg', '.webm',
  // Archives
  '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.xz', '.zst',
  // Compiled/Binary
  '.exe', '.dll', '.so', '.dylib', '.o', '.a', '.lib', '.bin', '.class', '.pyc', '.pyo',
  '.wasm', '.map',
  // Fonts
  '.woff', '.woff2', '.ttf', '.otf', '.eot',
  // Documents
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  // Database
  '.db', '.sqlite', '.sqlite3',
  // Misc binary
  '.DS_Store', '.lock',
]);

/**
 * Checks if a file is binary based on its extension.
 * This is a fast heuristic — no file content inspection needed.
 */
export function isBinaryFile(filePath: string): boolean {
  const ext = extname(filePath).toLowerCase();
  return BINARY_EXTENSIONS.has(ext);
}

// ─── Directories to Always Skip ──────────────────────────────────────────────

/** Directories that should never be traversed during sieving. */
export const SKIP_DIRECTORIES = new Set([
  '.git',
  'node_modules',
  '__pycache__',
  '.venv',
  'venv',
  'env',
  '.env',
  'vendor',
  'dist',
  'build',
  'out',
  '.next',
  '.nuxt',
  '.output',
  'coverage',
  '.nyc_output',
  '.cache',
  '.parcel-cache',
  '.turbo',
  '.svelte-kit',
  'target',          // Rust/Java
  'bin',
  'obj',             // .NET
  '.gradle',
  '.idea',
  '.vscode',
  '.settings',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  'eggs',
  '*.egg-info',
  '.tox',
  'htmlcov',
]);

// ─── Lock Files to Skip ──────────────────────────────────────────────────────

/** Lock files and generated manifests — high-entropy, low-signal. */
export const SKIP_FILES = new Set([
  'package-lock.json',
  'yarn.lock',
  'pnpm-lock.yaml',
  'poetry.lock',
  'Pipfile.lock',
  'Gemfile.lock',
  'composer.lock',
  'Cargo.lock',
  'go.sum',
  '.DS_Store',
  'Thumbs.db',
]);
