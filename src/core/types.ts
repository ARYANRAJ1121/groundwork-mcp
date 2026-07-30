/**
 * Groundwork MCP Server — Shared TypeScript types
 *
 * All core data structures used across the codebase.
 * No external dependencies — pure type definitions.
 */

// ─── Job Status ──────────────────────────────────────────────────────────────

export type JobStatus =
  | 'queued'
  | 'cloning'
  | 'sieving'
  | 'parsing'
  | 'complete'
  | 'failed';

// ─── Ingest Job ──────────────────────────────────────────────────────────────

export interface IngestJob {
  id: string;
  repo_url: string;
  repo_name: string;
  branch: string;
  status: JobStatus;
  progress: number;          // 0.0 – 1.0
  files_processed: number;
  files_total: number;
  tokens_estimate: number;
  commit_sha: string | null;
  clone_path: string | null;
  error_message: string | null;
  created_at: string;        // ISO 8601
  updated_at: string;        // ISO 8601
}

// ─── Sieve Output ────────────────────────────────────────────────────────────

export type SupportedLanguage =
  | 'javascript'
  | 'typescript'
  | 'tsx'
  | 'python'
  | 'json'
  | 'yaml'
  | 'markdown'
  | 'toml'
  | 'config';

/** A file that passed the Sieve filter and is ready for parsing. */
export interface SievedFile {
  /** Path relative to the repo root */
  relativePath: string;
  /** Absolute path on disk */
  absolutePath: string;
  /** Detected language from file extension */
  language: SupportedLanguage;
  /** File size in bytes */
  sizeBytes: number;
}

export interface SieveResult {
  files: SievedFile[];
  totalFiles: number;
  totalSizeBytes: number;
  skippedFiles: number;
  skippedReasons: Record<string, number>;  // reason -> count
}

// ─── Parsed File ─────────────────────────────────────────────────────────────

export interface ParsedFile {
  filePath: string;
  language: SupportedLanguage;
  lineCount: number;
  sizeBytes: number;
  /** Serialized lightweight AST (pruned, no whitespace/comments) */
  astJson: string | null;
}

// ─── Symbols ─────────────────────────────────────────────────────────────────

export type SymbolType =
  | 'function'
  | 'class'
  | 'method'
  | 'variable'
  | 'export'
  | 'interface'
  | 'type_alias'
  | 'enum';

export interface SymbolRecord {
  filePath: string;
  symbolName: string;
  symbolType: SymbolType;
  startLine: number;
  endLine: number;
  signature: string | null;
}

// ─── Edges (imports/dependencies) ────────────────────────────────────────────

export type EdgeType = 'import' | 'call' | 'extends' | 'implements';

export interface EdgeRecord {
  sourceFile: string;
  targetFile: string | null;   // null = external module
  targetModule: string;        // raw import string
  edgeType: EdgeType;
}

// ─── AST Node (lightweight representation) ───────────────────────────────────

export interface ASTNode {
  type: string;
  name: string | null;
  startLine: number;
  endLine: number;
  startColumn: number;
  endColumn: number;
  children: ASTNode[];
}

// ─── Parser Output ───────────────────────────────────────────────────────────

export interface FileParseResult {
  file: ParsedFile;
  symbols: SymbolRecord[];
  edges: EdgeRecord[];
}

// ─── Clone Result ────────────────────────────────────────────────────────────

export interface CloneResult {
  clonePath: string;
  commitSha: string;
  repoName: string;
}

// ─── Tool Response Types ─────────────────────────────────────────────────────

export interface IngestRepoResponse {
  job_id: string;
  status: JobStatus;
}

export interface IngestStatusResponse {
  job_id: string;
  repo_name: string;
  repo_url: string;
  status: JobStatus;
  progress: number;
  files_processed: number;
  files_total: number;
  tokens_estimate: number;
  error_message?: string;
  commit_sha?: string;
}

export interface ListIngestedResponse {
  repos: {
    job_id: string;
    name: string;
    repo_url: string;
    status: JobStatus;
    ingested_at: string;
    files_processed: number;
    tokens_estimate: number;
  }[];
}
