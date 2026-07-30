/**
 * Groundwork MCP Server — Configuration
 *
 * All tunables are driven by environment variables with sensible defaults.
 * Nothing requires a paid SaaS signup.
 */

import { homedir } from 'node:os';
import { join } from 'node:path';
import { mkdirSync, existsSync } from 'node:fs';

export interface GroundworkConfig {
  /** Root directory for all Groundwork data (DB, cloned repos) */
  dataDir: string;
  /** Path to the SQLite database file */
  dbPath: string;
  /** Directory for cloned repositories */
  reposDir: string;
  /** Directory for WASM grammar files */
  grammarsDir: string;

  // ─── Resource Limits ────────────────────────────────────────────────
  /** Maximum total repo size in bytes (default: 500MB) */
  maxRepoSizeBytes: number;
  /** Maximum file count in a repo (default: 10,000) */
  maxFileCount: number;
  /** Maximum single file size in bytes (default: 5MB) */
  maxSingleFileSizeBytes: number;
  /** Git clone timeout in milliseconds (default: 120s) */
  cloneTimeoutMs: number;

  // ─── Supported Languages ───────────────────────────────────────────
  supportedExtensions: Record<string, string>;  // extension -> language
}

function envInt(key: string, defaultVal: number): number {
  const val = process.env[key];
  if (val === undefined) return defaultVal;
  const parsed = parseInt(val, 10);
  return isNaN(parsed) ? defaultVal : parsed;
}

function envString(key: string, defaultVal: string): string {
  return process.env[key] || defaultVal;
}

function ensureDir(dir: string): void {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

export function loadConfig(): GroundworkConfig {
  const dataDir = envString(
    'GROUNDWORK_DATA_DIR',
    join(homedir(), '.groundwork')
  );
  const reposDir = join(dataDir, 'repos');
  const dbPath = join(dataDir, 'groundwork.db');

  // Grammar files are bundled alongside the source
  // Resolved relative to the compiled JS location at runtime
  const grammarsDir = join(dataDir, 'grammars');

  // Ensure all required directories exist
  ensureDir(dataDir);
  ensureDir(reposDir);
  ensureDir(grammarsDir);

  return {
    dataDir,
    dbPath,
    reposDir,
    grammarsDir,

    maxRepoSizeBytes: envInt('GROUNDWORK_MAX_REPO_SIZE_MB', 500) * 1024 * 1024,
    maxFileCount: envInt('GROUNDWORK_MAX_FILE_COUNT', 10_000),
    maxSingleFileSizeBytes: envInt('GROUNDWORK_MAX_FILE_SIZE_MB', 5) * 1024 * 1024,
    cloneTimeoutMs: envInt('GROUNDWORK_CLONE_TIMEOUT_SEC', 120) * 1000,

    supportedExtensions: {
      // Parseable languages (tree-sitter)
      '.js': 'javascript',
      '.mjs': 'javascript',
      '.cjs': 'javascript',
      '.jsx': 'javascript',
      '.ts': 'typescript',
      '.mts': 'typescript',
      '.cts': 'typescript',
      '.tsx': 'tsx',
      '.py': 'python',
      '.pyi': 'python',

      // Config & docs (kept but not AST-parsed)
      '.json': 'json',
      '.yaml': 'yaml',
      '.yml': 'yaml',
      '.md': 'markdown',
      '.mdx': 'markdown',
      '.toml': 'toml',
      '.cfg': 'config',
      '.ini': 'config',
      '.env': 'config',
      '.env.example': 'config',
    },
  };
}

/** Languages that tree-sitter can parse (subset of supportedExtensions) */
export const PARSEABLE_LANGUAGES = new Set([
  'javascript',
  'typescript',
  'tsx',
  'python',
]);

/** Singleton config instance */
export const config = loadConfig();
