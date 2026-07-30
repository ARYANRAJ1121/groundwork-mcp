/**
 * Groundwork MCP Server — SQLite Job Store
 *
 * Uses better-sqlite3 for synchronous, high-performance SQLite operations.
 * All persistent state lives here: jobs, parsed files, symbols, dependency edges.
 *
 * Zero-cost: file-based SQLite, no Postgres, no hosted DB.
 */

import Database from 'better-sqlite3';
import type { Database as DatabaseType } from 'better-sqlite3';
import { config } from '../utils/config.js';
import { logger } from '../utils/logger.js';
import type {
  IngestJob,
  JobStatus,
  ParsedFile,
  SymbolRecord,
  EdgeRecord,
} from '../core/types.js';

// ─── Database Singleton ──────────────────────────────────────────────────────

let db: DatabaseType | null = null;

/**
 * Initialize the SQLite database, create tables if they don't exist.
 * Must be called once at server startup.
 */
export function initDatabase(): DatabaseType {
  if (db) return db;

  logger.info(`Initializing SQLite database at: ${config.dbPath}`);

  db = new Database(config.dbPath);

  // Enable WAL mode for better concurrent read performance
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  // Create all tables
  db.exec(SCHEMA);

  logger.info('Database initialized successfully');
  return db;
}

/**
 * Get the database instance. Throws if not initialized.
 */
export function getDatabase(): DatabaseType {
  if (!db) {
    throw new Error('Database not initialized. Call initDatabase() first.');
  }
  return db;
}

/**
 * Close the database connection gracefully.
 */
export function closeDatabase(): void {
  if (db) {
    db.close();
    db = null;
    logger.info('Database connection closed');
  }
}

// ─── Schema ──────────────────────────────────────────────────────────────────

const SCHEMA = `
  -- Job tracking
  CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    branch TEXT NOT NULL DEFAULT 'main',
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    files_processed INTEGER NOT NULL DEFAULT 0,
    files_total INTEGER NOT NULL DEFAULT 0,
    tokens_estimate INTEGER NOT NULL DEFAULT 0,
    commit_sha TEXT,
    clone_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  -- Parsed file records (per-file AST metadata)
  CREATE TABLE IF NOT EXISTS parsed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    language TEXT NOT NULL,
    line_count INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    ast_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(job_id, file_path)
  );

  -- Symbol index (functions, classes, methods, variables, exports)
  CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT,
    created_at TEXT NOT NULL
  );

  -- Import/dependency edges (the dependency graph)
  CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    target_file TEXT,
    target_module TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'import',
    created_at TEXT NOT NULL
  );

  -- Indexes for query performance
  CREATE INDEX IF NOT EXISTS idx_parsed_files_job ON parsed_files(job_id);
  CREATE INDEX IF NOT EXISTS idx_symbols_job ON symbols(job_id);
  CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(job_id, symbol_name);
  CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(job_id, file_path);
  CREATE INDEX IF NOT EXISTS idx_edges_job ON edges(job_id);
  CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(job_id, source_file);
  CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(job_id, target_file);
`;

// ─── Job Operations ──────────────────────────────────────────────────────────

/**
 * Create a new ingest job record.
 */
export function createJob(
  id: string,
  repoUrl: string,
  repoName: string,
  branch: string,
): IngestJob {
  const now = new Date().toISOString();
  const database = getDatabase();

  const stmt = database.prepare(`
    INSERT INTO jobs (id, repo_url, repo_name, branch, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, 'queued', ?, ?)
  `);

  stmt.run(id, repoUrl, repoName, branch, now, now);

  logger.info(`Created job ${id} for ${repoName}`);

  return {
    id,
    repo_url: repoUrl,
    repo_name: repoName,
    branch,
    status: 'queued',
    progress: 0,
    files_processed: 0,
    files_total: 0,
    tokens_estimate: 0,
    commit_sha: null,
    clone_path: null,
    error_message: null,
    created_at: now,
    updated_at: now,
  };
}

/**
 * Update a job's status and optional progress fields.
 */
export function updateJobStatus(
  id: string,
  updates: {
    status?: JobStatus;
    progress?: number;
    files_processed?: number;
    files_total?: number;
    tokens_estimate?: number;
    commit_sha?: string;
    clone_path?: string;
    error_message?: string;
  },
): void {
  const database = getDatabase();
  const now = new Date().toISOString();

  const fields: string[] = ['updated_at = ?'];
  const values: unknown[] = [now];

  if (updates.status !== undefined) {
    fields.push('status = ?');
    values.push(updates.status);
  }
  if (updates.progress !== undefined) {
    fields.push('progress = ?');
    values.push(updates.progress);
  }
  if (updates.files_processed !== undefined) {
    fields.push('files_processed = ?');
    values.push(updates.files_processed);
  }
  if (updates.files_total !== undefined) {
    fields.push('files_total = ?');
    values.push(updates.files_total);
  }
  if (updates.tokens_estimate !== undefined) {
    fields.push('tokens_estimate = ?');
    values.push(updates.tokens_estimate);
  }
  if (updates.commit_sha !== undefined) {
    fields.push('commit_sha = ?');
    values.push(updates.commit_sha);
  }
  if (updates.clone_path !== undefined) {
    fields.push('clone_path = ?');
    values.push(updates.clone_path);
  }
  if (updates.error_message !== undefined) {
    fields.push('error_message = ?');
    values.push(updates.error_message);
  }

  values.push(id);

  const stmt = database.prepare(
    `UPDATE jobs SET ${fields.join(', ')} WHERE id = ?`
  );
  stmt.run(...values);
}

/**
 * Get a job by ID.
 */
export function getJob(id: string): IngestJob | null {
  const database = getDatabase();
  const row = database.prepare('SELECT * FROM jobs WHERE id = ?').get(id) as IngestJob | undefined;
  return row ?? null;
}

/**
 * List all jobs, ordered by creation date (newest first).
 */
export function listJobs(): IngestJob[] {
  const database = getDatabase();
  return database
    .prepare('SELECT * FROM jobs ORDER BY created_at DESC')
    .all() as IngestJob[];
}

// ─── Parsed File Operations ──────────────────────────────────────────────────

/**
 * Insert a parsed file record. Uses REPLACE to handle re-ingestion.
 */
export function insertParsedFile(jobId: string, file: ParsedFile): void {
  const database = getDatabase();
  const now = new Date().toISOString();

  const stmt = database.prepare(`
    INSERT OR REPLACE INTO parsed_files (job_id, file_path, language, line_count, size_bytes, ast_json, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  stmt.run(jobId, file.filePath, file.language, file.lineCount, file.sizeBytes, file.astJson, now);
}

/**
 * Batch-insert symbols for a job. Wrapped in a transaction for performance.
 */
export function insertSymbols(jobId: string, symbols: SymbolRecord[]): void {
  if (symbols.length === 0) return;

  const database = getDatabase();
  const now = new Date().toISOString();

  const stmt = database.prepare(`
    INSERT INTO symbols (job_id, file_path, symbol_name, symbol_type, start_line, end_line, signature, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const insertMany = database.transaction((syms: SymbolRecord[]) => {
    for (const s of syms) {
      stmt.run(jobId, s.filePath, s.symbolName, s.symbolType, s.startLine, s.endLine, s.signature, now);
    }
  });

  insertMany(symbols);
}

/**
 * Batch-insert edges for a job. Wrapped in a transaction for performance.
 */
export function insertEdges(jobId: string, edges: EdgeRecord[]): void {
  if (edges.length === 0) return;

  const database = getDatabase();
  const now = new Date().toISOString();

  const stmt = database.prepare(`
    INSERT INTO edges (job_id, source_file, target_file, target_module, edge_type, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
  `);

  const insertMany = database.transaction((edgeList: EdgeRecord[]) => {
    for (const e of edgeList) {
      stmt.run(jobId, e.sourceFile, e.targetFile, e.targetModule, e.edgeType, now);
    }
  });

  insertMany(edges);
}

/**
 * Get all parsed files for a job.
 */
export function getJobFiles(jobId: string): ParsedFile[] {
  const database = getDatabase();
  const rows = database
    .prepare('SELECT file_path, language, line_count, size_bytes, ast_json FROM parsed_files WHERE job_id = ?')
    .all(jobId) as Array<{
      file_path: string;
      language: string;
      line_count: number;
      size_bytes: number;
      ast_json: string | null;
    }>;

  return rows.map(r => ({
    filePath: r.file_path,
    language: r.language as ParsedFile['language'],
    lineCount: r.line_count,
    sizeBytes: r.size_bytes,
    astJson: r.ast_json,
  }));
}

/**
 * Get all symbols for a job.
 */
export function getJobSymbols(jobId: string): SymbolRecord[] {
  const database = getDatabase();
  const rows = database
    .prepare('SELECT file_path, symbol_name, symbol_type, start_line, end_line, signature FROM symbols WHERE job_id = ?')
    .all(jobId) as Array<{
      file_path: string;
      symbol_name: string;
      symbol_type: string;
      start_line: number;
      end_line: number;
      signature: string | null;
    }>;

  return rows.map(r => ({
    filePath: r.file_path,
    symbolName: r.symbol_name,
    symbolType: r.symbol_type as SymbolRecord['symbolType'],
    startLine: r.start_line,
    endLine: r.end_line,
    signature: r.signature,
  }));
}

/**
 * Get all edges for a job.
 */
export function getJobEdges(jobId: string): EdgeRecord[] {
  const database = getDatabase();
  const rows = database
    .prepare('SELECT source_file, target_file, target_module, edge_type FROM edges WHERE job_id = ?')
    .all(jobId) as Array<{
      source_file: string;
      target_file: string | null;
      target_module: string;
      edge_type: string;
    }>;

  return rows.map(r => ({
    sourceFile: r.source_file,
    targetFile: r.target_file,
    targetModule: r.target_module,
    edgeType: r.edge_type as EdgeRecord['edgeType'],
  }));
}

/**
 * Delete all data for a job (cascade deletes parsed_files, symbols, edges).
 */
export function deleteJob(jobId: string): void {
  const database = getDatabase();
  database.prepare('DELETE FROM jobs WHERE id = ?').run(jobId);
  logger.info(`Deleted job ${jobId} and all associated data`);
}
