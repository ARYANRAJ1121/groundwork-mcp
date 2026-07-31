/**
 * Groundwork MCP Server — SQLite Job Store (sql.js / WASM)
 *
 * Uses sql.js — a pure WASM SQLite that requires zero native compilation.
 * No Visual Studio Build Tools, no node-gyp, works on every OS out of the box.
 *
 * Key difference from better-sqlite3: sql.js holds the DB in memory and
 * we manually persist to disk on writes. This is fine for our use case
 * (infrequent writes during ingestion, frequent reads during queries).
 *
 * Zero-cost: file-based SQLite, no Postgres, no hosted DB.
 */

import initSqlJs from 'sql.js';
import type { Database as SqlJsDatabase } from 'sql.js';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
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

let db: SqlJsDatabase | null = null;

/**
 * Initialize the SQLite database via sql.js (WASM).
 * Loads existing DB from disk if present, otherwise creates a new one.
 * Must be called once at server startup.
 */
export async function initDatabase(): Promise<SqlJsDatabase> {
  if (db) return db;

  logger.info(`Initializing SQLite database at: ${config.dbPath}`);

  const SQL = await initSqlJs();

  // Load existing database from disk if it exists
  if (existsSync(config.dbPath)) {
    const fileBuffer = readFileSync(config.dbPath);
    db = new SQL.Database(fileBuffer);
    logger.info('Loaded existing database from disk');
  } else {
    db = new SQL.Database();
    logger.info('Created new database');
  }

  // Enable WAL mode equivalent — not available in sql.js but we set pragma
  db.run('PRAGMA foreign_keys = ON;');

  // Create all tables
  db.run(SCHEMA);

  // Persist the initialized schema
  persistDatabase();

  logger.info('Database initialized successfully');
  return db;
}

/**
 * Get the database instance. Throws if not initialized.
 */
export function getDatabase(): SqlJsDatabase {
  if (!db) {
    throw new Error('Database not initialized. Call initDatabase() first.');
  }
  return db;
}

/**
 * Persist the in-memory database to disk.
 * Call this after any write operation.
 */
export function persistDatabase(): void {
  if (!db) return;
  const data = db.export();
  const buffer = Buffer.from(data);
  writeFileSync(config.dbPath, buffer);
}

/**
 * Close the database connection gracefully.
 */
export function closeDatabase(): void {
  if (db) {
    persistDatabase();
    db.close();
    db = null;
    logger.info('Database connection closed');
  }
}

// ─── Schema ──────────────────────────────────────────────────────────────────

const SCHEMA = `
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

  CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    target_file TEXT,
    target_module TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'import',
    created_at TEXT NOT NULL
  );

  CREATE INDEX IF NOT EXISTS idx_parsed_files_job ON parsed_files(job_id);
  CREATE INDEX IF NOT EXISTS idx_symbols_job ON symbols(job_id);
  CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(job_id, symbol_name);
  CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(job_id, file_path);
  CREATE INDEX IF NOT EXISTS idx_edges_job ON edges(job_id);
  CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(job_id, source_file);
  CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(job_id, target_file);
`;

// ─── Helper: query rows as objects ───────────────────────────────────────────

function queryAll<T>(sql: string, params: unknown[] = []): T[] {
  const database = getDatabase();
  const stmt = database.prepare(sql);
  stmt.bind(params);

  const results: T[] = [];
  while (stmt.step()) {
    const row = stmt.getAsObject();
    results.push(row as T);
  }
  stmt.free();
  return results;
}

function queryOne<T>(sql: string, params: unknown[] = []): T | null {
  const results = queryAll<T>(sql, params);
  return results.length > 0 ? results[0] : null;
}

function execute(sql: string, params: unknown[] = []): void {
  const database = getDatabase();
  database.run(sql, params);
}

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

  execute(
    `INSERT INTO jobs (id, repo_url, repo_name, branch, status, created_at, updated_at)
     VALUES (?, ?, ?, ?, 'queued', ?, ?)`,
    [id, repoUrl, repoName, branch, now, now]
  );
  persistDatabase();

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

  execute(`UPDATE jobs SET ${fields.join(', ')} WHERE id = ?`, values);
  persistDatabase();
}

/**
 * Get a job by ID.
 */
export function getJob(id: string): IngestJob | null {
  return queryOne<IngestJob>('SELECT * FROM jobs WHERE id = ?', [id]);
}

/**
 * List all jobs, ordered by creation date (newest first).
 */
export function listJobs(): IngestJob[] {
  return queryAll<IngestJob>('SELECT * FROM jobs ORDER BY created_at DESC');
}

// ─── Parsed File Operations ──────────────────────────────────────────────────

/**
 * Insert a parsed file record.
 */
export function insertParsedFile(jobId: string, file: ParsedFile): void {
  const now = new Date().toISOString();

  execute(
    `INSERT OR REPLACE INTO parsed_files (job_id, file_path, language, line_count, size_bytes, ast_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [jobId, file.filePath, file.language, file.lineCount, file.sizeBytes, file.astJson, now]
  );
}

/**
 * Batch-insert symbols for a job.
 */
export function insertSymbols(jobId: string, symbols: SymbolRecord[]): void {
  if (symbols.length === 0) return;

  const now = new Date().toISOString();

  for (const s of symbols) {
    execute(
      `INSERT INTO symbols (job_id, file_path, symbol_name, symbol_type, start_line, end_line, signature, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [jobId, s.filePath, s.symbolName, s.symbolType, s.startLine, s.endLine, s.signature, now]
    );
  }
}

/**
 * Batch-insert edges for a job.
 */
export function insertEdges(jobId: string, edges: EdgeRecord[]): void {
  if (edges.length === 0) return;

  const now = new Date().toISOString();

  for (const e of edges) {
    execute(
      `INSERT INTO edges (job_id, source_file, target_file, target_module, edge_type, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [jobId, e.sourceFile, e.targetFile, e.targetModule, e.edgeType, now]
    );
  }
}

/**
 * Persist after a batch of file inserts (call once after processing all files).
 */
export function persistAfterBatch(): void {
  persistDatabase();
}

/**
 * Get all parsed files for a job.
 */
export function getJobFiles(jobId: string): ParsedFile[] {
  const rows = queryAll<Record<string, unknown>>(
    'SELECT file_path, language, line_count, size_bytes, ast_json FROM parsed_files WHERE job_id = ?',
    [jobId]
  );

  return rows.map(r => ({
    filePath: r.file_path as string,
    language: r.language as ParsedFile['language'],
    lineCount: r.line_count as number,
    sizeBytes: r.size_bytes as number,
    astJson: r.ast_json as string | null,
  }));
}

/**
 * Get all symbols for a job.
 */
export function getJobSymbols(jobId: string): SymbolRecord[] {
  const rows = queryAll<Record<string, unknown>>(
    'SELECT file_path, symbol_name, symbol_type, start_line, end_line, signature FROM symbols WHERE job_id = ?',
    [jobId]
  );

  return rows.map(r => ({
    filePath: r.file_path as string,
    symbolName: r.symbol_name as string,
    symbolType: r.symbol_type as SymbolRecord['symbolType'],
    startLine: r.start_line as number,
    endLine: r.end_line as number,
    signature: r.signature as string | null,
  }));
}

/**
 * Get all edges for a job.
 */
export function getJobEdges(jobId: string): EdgeRecord[] {
  const rows = queryAll<Record<string, unknown>>(
    'SELECT source_file, target_file, target_module, edge_type FROM edges WHERE job_id = ?',
    [jobId]
  );

  return rows.map(r => ({
    sourceFile: r.source_file as string,
    targetFile: r.target_file as string | null,
    targetModule: r.target_module as string,
    edgeType: r.edge_type as EdgeRecord['edgeType'],
  }));
}

/**
 * Delete all data for a job (cascade deletes parsed_files, symbols, edges).
 */
export function deleteJob(jobId: string): void {
  execute('DELETE FROM edges WHERE job_id = ?', [jobId]);
  execute('DELETE FROM symbols WHERE job_id = ?', [jobId]);
  execute('DELETE FROM parsed_files WHERE job_id = ?', [jobId]);
  execute('DELETE FROM jobs WHERE id = ?', [jobId]);
  persistDatabase();
  logger.info(`Deleted job ${jobId} and all associated data`);
}
