/**
 * Groundwork MCP Server — Logger
 *
 * All output goes to stderr because stdout is reserved for the MCP
 * JSON-RPC protocol. Writing to stdout would corrupt the transport.
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const LOG_COLORS: Record<LogLevel, string> = {
  debug: '\x1b[90m',  // gray
  info: '\x1b[36m',   // cyan
  warn: '\x1b[33m',   // yellow
  error: '\x1b[31m',  // red
};

const RESET = '\x1b[0m';

class Logger {
  private minLevel: number;

  constructor(level: LogLevel = 'info') {
    this.minLevel = LOG_LEVELS[level];
  }

  setLevel(level: LogLevel): void {
    this.minLevel = LOG_LEVELS[level];
  }

  private log(level: LogLevel, message: string, data?: unknown): void {
    if (LOG_LEVELS[level] < this.minLevel) return;

    const timestamp = new Date().toISOString();
    const color = LOG_COLORS[level];
    const prefix = `${color}[${timestamp}] [${level.toUpperCase()}]${RESET}`;

    if (data !== undefined) {
      const serialized = typeof data === 'string'
        ? data
        : JSON.stringify(data, null, 2);
      process.stderr.write(`${prefix} ${message} ${serialized}\n`);
    } else {
      process.stderr.write(`${prefix} ${message}\n`);
    }
  }

  debug(message: string, data?: unknown): void {
    this.log('debug', message, data);
  }

  info(message: string, data?: unknown): void {
    this.log('info', message, data);
  }

  warn(message: string, data?: unknown): void {
    this.log('warn', message, data);
  }

  error(message: string, data?: unknown): void {
    this.log('error', message, data);
  }
}

/** Singleton logger instance — all output to stderr */
export const logger = new Logger(
  (process.env.GROUNDWORK_LOG_LEVEL as LogLevel) || 'info'
);
