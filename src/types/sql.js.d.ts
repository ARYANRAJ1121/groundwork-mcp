/**
 * Type declarations for sql.js
 *
 * sql.js doesn't ship its own .d.ts in all versions.
 * This provides the minimal types we actually use.
 */
declare module 'sql.js' {
  interface SqlJsStatic {
    Database: new (data?: ArrayLike<number> | Buffer | null) => Database;
  }

  interface Database {
    run(sql: string, params?: unknown[]): Database;
    exec(sql: string): QueryExecResult[];
    prepare(sql: string): Statement;
    export(): Uint8Array;
    close(): void;
  }

  interface Statement {
    bind(params?: unknown[]): boolean;
    step(): boolean;
    getAsObject(params?: Record<string, unknown>): Record<string, unknown>;
    free(): boolean;
    reset(): void;
  }

  interface QueryExecResult {
    columns: string[];
    values: unknown[][];
  }

  export type { Database, Statement, QueryExecResult, SqlJsStatic };

  export default function initSqlJs(config?: Record<string, unknown>): Promise<SqlJsStatic>;
}
