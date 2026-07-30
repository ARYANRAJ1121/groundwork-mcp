/**
 * Groundwork MCP Server — Tree-sitter AST Parser
 *
 * Uses web-tree-sitter (WASM) to parse source files into ASTs,
 * then extracts symbols (functions, classes, methods, variables)
 * and edges (imports, exports) from the concrete syntax tree.
 *
 * This is purely static analysis — no code execution, no eval,
 * no require. The parser never runs any code from the cloned repo.
 *
 * Zero-cost: web-tree-sitter runs locally via WASM, no API calls.
 */

import Parser from 'web-tree-sitter';
import { readFileSync, existsSync, writeFileSync } from 'node:fs';
import { join, dirname, resolve, extname, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { config, PARSEABLE_LANGUAGES } from '../utils/config.js';
import { logger } from '../utils/logger.js';
import type {
  SievedFile,
  FileParseResult,
  ParsedFile,
  SymbolRecord,
  EdgeRecord,
  SymbolType,
  SupportedLanguage,
} from './types.js';

// ─── Module-level State ──────────────────────────────────────────────────────

let parserInitialized = false;
const languageParsers: Map<string, Parser> = new Map();
const languages: Map<string, Parser.Language> = new Map();

// ─── Grammar Resolution ─────────────────────────────────────────────────────

/**
 * Resolve the path to a WASM grammar file.
 * Searches in order:
 * 1. The configured grammars directory (~/.groundwork/grammars/)
 * 2. Bundled with the package (./grammars/ relative to built JS)
 * 3. node_modules/web-tree-sitter/ (fallback)
 */
function resolveGrammarPath(languageName: string): string {
  const wasmFileName = `tree-sitter-${languageName}.wasm`;

  // Check configured grammars dir first
  const configPath = join(config.grammarsDir, wasmFileName);
  if (existsSync(configPath)) return configPath;

  // Check bundled grammars (relative to this file's compiled location)
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const bundledPath = join(__dirname, '..', 'grammars', wasmFileName);
  if (existsSync(bundledPath)) return bundledPath;

  // Check project root grammars directory
  const projectPath = join(__dirname, '..', '..', 'grammars', wasmFileName);
  if (existsSync(projectPath)) return projectPath;

  throw new Error(
    `Grammar file not found: ${wasmFileName}. ` +
    `Please download it to ${config.grammarsDir}/ or run the setup script.`
  );
}

// ─── Initialization ──────────────────────────────────────────────────────────

/**
 * Initialize the web-tree-sitter WASM runtime and load language grammars.
 * Must be called once before parsing any files.
 *
 * Loads grammars for: JavaScript, TypeScript, TSX, Python
 */
export async function initParser(): Promise<void> {
  if (parserInitialized) return;

  logger.info('Initializing tree-sitter WASM parser...');

  await Parser.init();

  // Language name -> grammar file name mapping
  // TypeScript grammar covers both .ts and .tsx via separate WASM files
  const grammarMap: Record<string, string> = {
    javascript: 'javascript',
    typescript: 'typescript',
    tsx: 'tsx',
    python: 'python',
  };

  for (const [lang, grammarName] of Object.entries(grammarMap)) {
    try {
      const grammarPath = resolveGrammarPath(grammarName);
      const language = await Parser.Language.load(grammarPath);
      languages.set(lang, language);

      const parser = new Parser();
      parser.setLanguage(language);
      languageParsers.set(lang, parser);

      logger.info(`  Loaded grammar: ${lang} (${grammarPath})`);
    } catch (error) {
      logger.warn(`  Failed to load grammar for ${lang}: ${error instanceof Error ? error.message : error}`);
      // Non-fatal: we can still parse other languages
    }
  }

  parserInitialized = true;
  logger.info(`Parser initialized with ${languageParsers.size} language(s)`);
}

/**
 * Check if a language can be parsed (grammar loaded and language is parseable).
 */
export function canParse(language: string): boolean {
  return PARSEABLE_LANGUAGES.has(language) && languageParsers.has(language);
}

// ─── File Parsing ────────────────────────────────────────────────────────────

/**
 * Parse a single source file and extract symbols + edges.
 *
 * @param file - A SievedFile that passed the filter
 * @param repoRoot - Absolute path to the repository root (for import resolution)
 * @returns FileParseResult with parsed file metadata, symbols, and edges
 */
export function parseFile(file: SievedFile, repoRoot: string): FileParseResult {
  const symbols: SymbolRecord[] = [];
  const edges: EdgeRecord[] = [];

  // Read file content
  let content: string;
  try {
    content = readFileSync(file.absolutePath, 'utf-8');
  } catch (error) {
    logger.warn(`Cannot read file: ${file.relativePath}`);
    return {
      file: {
        filePath: file.relativePath,
        language: file.language,
        lineCount: 0,
        sizeBytes: file.sizeBytes,
        astJson: null,
      },
      symbols: [],
      edges: [],
    };
  }

  const lineCount = content.split('\n').length;
  // Token estimate: ~4 characters per token (rough heuristic)
  const tokenEstimate = Math.ceil(content.length / 4);

  // If this language isn't parseable with tree-sitter, return basic metadata
  if (!canParse(file.language)) {
    return {
      file: {
        filePath: file.relativePath,
        language: file.language,
        lineCount,
        sizeBytes: file.sizeBytes,
        astJson: null,
      },
      symbols: [],
      edges: [],
    };
  }

  // Parse with tree-sitter
  const parser = languageParsers.get(file.language)!;
  let tree: Parser.Tree;
  try {
    tree = parser.parse(content);
  } catch (error) {
    logger.warn(`tree-sitter parse failed for ${file.relativePath}: ${error}`);
    return {
      file: {
        filePath: file.relativePath,
        language: file.language,
        lineCount,
        sizeBytes: file.sizeBytes,
        astJson: null,
      },
      symbols: [],
      edges: [],
    };
  }

  // Extract symbols and edges based on language
  const rootNode = tree.rootNode;

  if (file.language === 'javascript' || file.language === 'typescript' || file.language === 'tsx') {
    extractJavaScriptSymbols(rootNode, file.relativePath, symbols);
    extractJavaScriptEdges(rootNode, file.relativePath, repoRoot, edges);
  } else if (file.language === 'python') {
    extractPythonSymbols(rootNode, file.relativePath, symbols);
    extractPythonEdges(rootNode, file.relativePath, repoRoot, edges);
  }

  // Build lightweight AST summary (pruned — no whitespace/comment nodes)
  const astSummary = buildASTSummary(rootNode, 3); // max depth 3 for storage

  tree.delete(); // Free WASM memory

  return {
    file: {
      filePath: file.relativePath,
      language: file.language,
      lineCount,
      sizeBytes: file.sizeBytes,
      astJson: JSON.stringify(astSummary),
    },
    symbols,
    edges,
  };
}

// ─── JavaScript/TypeScript Symbol Extraction ─────────────────────────────────

function extractJavaScriptSymbols(
  node: Parser.SyntaxNode,
  filePath: string,
  symbols: SymbolRecord[],
): void {
  const cursor = node.walk();

  function visit(): void {
    const current = cursor.currentNode;
    const type = current.type;

    switch (type) {
      // ── Function declarations ──────────────────────────────────────
      case 'function_declaration': {
        const nameNode = current.childForFieldName('name');
        if (nameNode) {
          const params = current.childForFieldName('parameters');
          symbols.push({
            filePath,
            symbolName: nameNode.text,
            symbolType: 'function',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: params ? `${nameNode.text}${params.text}` : nameNode.text,
          });
        }
        break;
      }

      // ── Arrow functions assigned to variables ──────────────────────
      case 'lexical_declaration':
      case 'variable_declaration': {
        for (let i = 0; i < current.childCount; i++) {
          const child = current.child(i);
          if (child?.type === 'variable_declarator') {
            const name = child.childForFieldName('name');
            const value = child.childForFieldName('value');
            if (name && value && (value.type === 'arrow_function' || value.type === 'function_expression')) {
              const params = value.childForFieldName('parameters');
              symbols.push({
                filePath,
                symbolName: name.text,
                symbolType: 'function',
                startLine: current.startPosition.row + 1,
                endLine: current.endPosition.row + 1,
                signature: params ? `${name.text}${params.text}` : name.text,
              });
            } else if (name && value) {
              // Regular variable/constant
              symbols.push({
                filePath,
                symbolName: name.text,
                symbolType: 'variable',
                startLine: current.startPosition.row + 1,
                endLine: current.endPosition.row + 1,
                signature: null,
              });
            }
          }
        }
        break;
      }

      // ── Class declarations ─────────────────────────────────────────
      case 'class_declaration': {
        const nameNode = current.childForFieldName('name');
        if (nameNode) {
          symbols.push({
            filePath,
            symbolName: nameNode.text,
            symbolType: 'class',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: null,
          });

          // Extract methods from class body
          const body = current.childForFieldName('body');
          if (body) {
            extractClassMethods(body, filePath, nameNode.text, symbols);
          }
        }
        break;
      }

      // ── TypeScript interfaces ──────────────────────────────────────
      case 'interface_declaration': {
        const nameNode = current.childForFieldName('name');
        if (nameNode) {
          symbols.push({
            filePath,
            symbolName: nameNode.text,
            symbolType: 'interface',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: null,
          });
        }
        break;
      }

      // ── TypeScript type aliases ────────────────────────────────────
      case 'type_alias_declaration': {
        const nameNode = current.childForFieldName('name');
        if (nameNode) {
          symbols.push({
            filePath,
            symbolName: nameNode.text,
            symbolType: 'type_alias',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: null,
          });
        }
        break;
      }

      // ── TypeScript enums ───────────────────────────────────────────
      case 'enum_declaration': {
        const nameNode = current.childForFieldName('name');
        if (nameNode) {
          symbols.push({
            filePath,
            symbolName: nameNode.text,
            symbolType: 'enum',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: null,
          });
        }
        break;
      }

      // ── Export statements (named exports) ──────────────────────────
      case 'export_statement': {
        // export default function/class — the child has the name
        // export { name1, name2 } — export specifiers
        const declaration = current.childForFieldName('declaration');
        if (declaration) {
          // export function foo() {} or export class Bar {}
          // These will be caught by their own type above when we recurse
        } else {
          // export { name1, name2 }
          for (let i = 0; i < current.childCount; i++) {
            const child = current.child(i);
            if (child?.type === 'export_clause') {
              for (let j = 0; j < child.childCount; j++) {
                const spec = child.child(j);
                if (spec?.type === 'export_specifier') {
                  const name = spec.childForFieldName('name');
                  if (name) {
                    symbols.push({
                      filePath,
                      symbolName: name.text,
                      symbolType: 'export',
                      startLine: spec.startPosition.row + 1,
                      endLine: spec.endPosition.row + 1,
                      signature: null,
                    });
                  }
                }
              }
            }
          }
        }
        break;
      }
    }

    // Recurse into children
    if (cursor.gotoFirstChild()) {
      do {
        visit();
      } while (cursor.gotoNextSibling());
      cursor.gotoParent();
    }
  }

  visit();
}

/**
 * Extract method definitions from a class body.
 */
function extractClassMethods(
  classBody: Parser.SyntaxNode,
  filePath: string,
  className: string,
  symbols: SymbolRecord[],
): void {
  for (let i = 0; i < classBody.childCount; i++) {
    const member = classBody.child(i);
    if (!member) continue;

    if (member.type === 'method_definition' || member.type === 'public_field_definition') {
      const nameNode = member.childForFieldName('name');
      if (nameNode) {
        const params = member.childForFieldName('parameters');
        symbols.push({
          filePath,
          symbolName: `${className}.${nameNode.text}`,
          symbolType: 'method',
          startLine: member.startPosition.row + 1,
          endLine: member.endPosition.row + 1,
          signature: params ? `${nameNode.text}${params.text}` : nameNode.text,
        });
      }
    }
  }
}

// ─── JavaScript/TypeScript Edge Extraction ───────────────────────────────────

function extractJavaScriptEdges(
  node: Parser.SyntaxNode,
  filePath: string,
  repoRoot: string,
  edges: EdgeRecord[],
): void {
  const cursor = node.walk();

  function visit(): void {
    const current = cursor.currentNode;

    if (current.type === 'import_statement') {
      const source = current.childForFieldName('source');
      if (source) {
        const moduleStr = source.text.replace(/['"]/g, '');
        const resolvedTarget = resolveImport(moduleStr, filePath, repoRoot);

        edges.push({
          sourceFile: filePath,
          targetFile: resolvedTarget,
          targetModule: moduleStr,
          edgeType: 'import',
        });
      }
    }

    // Dynamic imports: import('./foo')
    if (current.type === 'call_expression') {
      const fn = current.childForFieldName('function');
      if (fn?.type === 'import') {
        const args = current.childForFieldName('arguments');
        if (args && args.childCount > 0) {
          const firstArg = args.child(1); // Skip opening paren
          if (firstArg?.type === 'string') {
            const moduleStr = firstArg.text.replace(/['"]/g, '');
            const resolvedTarget = resolveImport(moduleStr, filePath, repoRoot);
            edges.push({
              sourceFile: filePath,
              targetFile: resolvedTarget,
              targetModule: moduleStr,
              edgeType: 'import',
            });
          }
        }
      }
    }

    // require() calls
    if (current.type === 'call_expression') {
      const fn = current.childForFieldName('function');
      if (fn?.text === 'require') {
        const args = current.childForFieldName('arguments');
        if (args && args.childCount > 0) {
          const firstArg = args.child(1); // Skip opening paren
          if (firstArg?.type === 'string') {
            const moduleStr = firstArg.text.replace(/['"]/g, '');
            const resolvedTarget = resolveImport(moduleStr, filePath, repoRoot);
            edges.push({
              sourceFile: filePath,
              targetFile: resolvedTarget,
              targetModule: moduleStr,
              edgeType: 'import',
            });
          }
        }
      }
    }

    // Class extends
    if (current.type === 'class_declaration' || current.type === 'class') {
      const heritage = current.childForFieldName('superclass') ||
        findChildByType(current, 'class_heritage');
      if (heritage) {
        edges.push({
          sourceFile: filePath,
          targetFile: null,
          targetModule: heritage.text,
          edgeType: 'extends',
        });
      }
    }

    if (cursor.gotoFirstChild()) {
      do {
        visit();
      } while (cursor.gotoNextSibling());
      cursor.gotoParent();
    }
  }

  visit();
}

// ─── Python Symbol Extraction ────────────────────────────────────────────────

function extractPythonSymbols(
  node: Parser.SyntaxNode,
  filePath: string,
  symbols: SymbolRecord[],
): void {
  const cursor = node.walk();

  function visit(insideClass?: string): void {
    const current = cursor.currentNode;

    switch (current.type) {
      case 'function_definition': {
        const nameNode = current.childForFieldName('name');
        const params = current.childForFieldName('parameters');
        if (nameNode) {
          const isMethod = insideClass !== undefined;
          symbols.push({
            filePath,
            symbolName: isMethod ? `${insideClass}.${nameNode.text}` : nameNode.text,
            symbolType: isMethod ? 'method' : 'function',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: params ? `${nameNode.text}${params.text}` : nameNode.text,
          });
        }
        break;
      }

      case 'class_definition': {
        const nameNode = current.childForFieldName('name');
        if (nameNode) {
          symbols.push({
            filePath,
            symbolName: nameNode.text,
            symbolType: 'class',
            startLine: current.startPosition.row + 1,
            endLine: current.endPosition.row + 1,
            signature: null,
          });

          // Extract methods — recurse into class body with class context
          const body = current.childForFieldName('body');
          if (body) {
            const innerCursor = body.walk();
            if (innerCursor.gotoFirstChild()) {
              do {
                const child = innerCursor.currentNode;
                if (child.type === 'function_definition') {
                  const methodName = child.childForFieldName('name');
                  const methodParams = child.childForFieldName('parameters');
                  if (methodName) {
                    symbols.push({
                      filePath,
                      symbolName: `${nameNode.text}.${methodName.text}`,
                      symbolType: 'method',
                      startLine: child.startPosition.row + 1,
                      endLine: child.endPosition.row + 1,
                      signature: methodParams ? `${methodName.text}${methodParams.text}` : methodName.text,
                    });
                  }
                }
              } while (innerCursor.gotoNextSibling());
            }
          }
        }
        // Don't recurse into class body again via the main visit loop
        return;
      }

      case 'assignment': {
        // Top-level assignments: x = value
        if (current.parent?.type === 'module' || current.parent?.type === 'expression_statement') {
          const left = current.childForFieldName('left');
          if (left?.type === 'identifier') {
            symbols.push({
              filePath,
              symbolName: left.text,
              symbolType: 'variable',
              startLine: current.startPosition.row + 1,
              endLine: current.endPosition.row + 1,
              signature: null,
            });
          }
        }
        break;
      }
    }

    if (cursor.gotoFirstChild()) {
      do {
        visit(insideClass);
      } while (cursor.gotoNextSibling());
      cursor.gotoParent();
    }
  }

  visit();
}

// ─── Python Edge Extraction ──────────────────────────────────────────────────

function extractPythonEdges(
  node: Parser.SyntaxNode,
  filePath: string,
  repoRoot: string,
  edges: EdgeRecord[],
): void {
  const cursor = node.walk();

  function visit(): void {
    const current = cursor.currentNode;

    // import module
    if (current.type === 'import_statement') {
      const nameNode = findChildByType(current, 'dotted_name');
      if (nameNode) {
        edges.push({
          sourceFile: filePath,
          targetFile: resolvePythonImport(nameNode.text, filePath, repoRoot),
          targetModule: nameNode.text,
          edgeType: 'import',
        });
      }
    }

    // from module import name
    if (current.type === 'import_from_statement') {
      const moduleNode = current.childForFieldName('module_name') ||
        findChildByType(current, 'dotted_name') ||
        findChildByType(current, 'relative_import');
      if (moduleNode) {
        const moduleStr = moduleNode.text;
        edges.push({
          sourceFile: filePath,
          targetFile: resolvePythonImport(moduleStr, filePath, repoRoot),
          targetModule: moduleStr,
          edgeType: 'import',
        });
      }
    }

    // Class inheritance
    if (current.type === 'class_definition') {
      const superclasses = current.childForFieldName('superclasses');
      if (superclasses) {
        for (let i = 0; i < superclasses.childCount; i++) {
          const child = superclasses.child(i);
          if (child && child.type !== ',' && child.type !== '(' && child.type !== ')') {
            edges.push({
              sourceFile: filePath,
              targetFile: null,
              targetModule: child.text,
              edgeType: 'extends',
            });
          }
        }
      }
    }

    if (cursor.gotoFirstChild()) {
      do {
        visit();
      } while (cursor.gotoNextSibling());
      cursor.gotoParent();
    }
  }

  visit();
}

// ─── Import Resolution ───────────────────────────────────────────────────────

/**
 * Resolve a JS/TS import specifier to a file path in the repo.
 * Returns null for external packages (npm modules).
 */
function resolveImport(
  importStr: string,
  fromFile: string,
  repoRoot: string,
): string | null {
  // External module (no relative path prefix)
  if (!importStr.startsWith('.') && !importStr.startsWith('/')) {
    return null;
  }

  const fromDir = dirname(fromFile);
  const candidates = [
    importStr,
    `${importStr}.ts`,
    `${importStr}.tsx`,
    `${importStr}.js`,
    `${importStr}.jsx`,
    `${importStr}/index.ts`,
    `${importStr}/index.tsx`,
    `${importStr}/index.js`,
    `${importStr}/index.jsx`,
  ];

  for (const candidate of candidates) {
    const resolved = join(fromDir, candidate).replace(/\\/g, '/');
    const absPath = join(repoRoot, resolved);
    if (existsSync(absPath)) {
      return resolved;
    }
  }

  // Could not resolve — return null (treat as external or unresolvable)
  return null;
}

/**
 * Resolve a Python import to a file path in the repo.
 * Returns null for external packages.
 */
function resolvePythonImport(
  importStr: string,
  fromFile: string,
  repoRoot: string,
): string | null {
  // Relative import (starts with .)
  if (importStr.startsWith('.')) {
    const dots = importStr.match(/^\.+/)?.[0].length || 0;
    const modulePart = importStr.slice(dots).replace(/\./g, '/');
    const fromDir = dirname(fromFile);

    let baseDir = fromDir;
    for (let i = 1; i < dots; i++) {
      baseDir = dirname(baseDir);
    }

    const candidates = [
      join(baseDir, modulePart + '.py'),
      join(baseDir, modulePart, '__init__.py'),
    ];

    for (const candidate of candidates) {
      const normalized = candidate.replace(/\\/g, '/');
      const absPath = join(repoRoot, normalized);
      if (existsSync(absPath)) {
        return normalized;
      }
    }

    return null;
  }

  // Absolute import — try to resolve as a file in the repo
  const modulePath = importStr.replace(/\./g, '/');
  const candidates = [
    `${modulePath}.py`,
    `${modulePath}/__init__.py`,
  ];

  for (const candidate of candidates) {
    const absPath = join(repoRoot, candidate);
    if (existsSync(absPath)) {
      return candidate;
    }
  }

  // External package
  return null;
}

// ─── AST Summary Builder ────────────────────────────────────────────────────

/**
 * Build a lightweight AST summary — prunes whitespace, comments,
 * and deep nesting to keep storage manageable.
 */
function buildASTSummary(node: Parser.SyntaxNode, maxDepth: number): object {
  if (maxDepth <= 0) {
    return {
      type: node.type,
      children_count: node.childCount,
      lines: `${node.startPosition.row + 1}-${node.endPosition.row + 1}`,
    };
  }

  // Skip noise nodes
  const skipTypes = new Set(['comment', 'line_comment', 'block_comment', 'whitespace', '\n', '']);

  const children: object[] = [];
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child && !skipTypes.has(child.type)) {
      children.push(buildASTSummary(child, maxDepth - 1));
    }
  }

  const result: Record<string, unknown> = {
    type: node.type,
    lines: `${node.startPosition.row + 1}-${node.endPosition.row + 1}`,
  };

  if (node.isNamed && node.childCount === 0 && node.text.length < 100) {
    result.text = node.text;
  }

  if (children.length > 0) {
    result.children = children;
  }

  return result;
}

// ─── Utility ─────────────────────────────────────────────────────────────────

function findChildByType(
  node: Parser.SyntaxNode,
  type: string,
): Parser.SyntaxNode | null {
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === type) return child;
  }
  return null;
}

// ─── Batch Parsing ───────────────────────────────────────────────────────────

/**
 * Parse all sieved files for a repository.
 *
 * @param files - Array of SievedFile objects from the Sieve
 * @param repoRoot - Absolute path to the repo root
 * @param onProgress - Callback invoked after each file (for progress tracking)
 * @returns Array of FileParseResult
 */
export async function parseAllFiles(
  files: SievedFile[],
  repoRoot: string,
  onProgress?: (processed: number, total: number, currentFile: string) => void,
): Promise<FileParseResult[]> {
  // Ensure parser is initialized
  await initParser();

  const results: FileParseResult[] = [];
  const total = files.length;

  for (let i = 0; i < total; i++) {
    const file = files[i];

    try {
      const result = parseFile(file, repoRoot);
      results.push(result);
    } catch (error) {
      logger.warn(`Error parsing ${file.relativePath}: ${error}`);
      // Return basic metadata on parse failure
      results.push({
        file: {
          filePath: file.relativePath,
          language: file.language,
          lineCount: 0,
          sizeBytes: file.sizeBytes,
          astJson: null,
        },
        symbols: [],
        edges: [],
      });
    }

    if (onProgress) {
      onProgress(i + 1, total, file.relativePath);
    }
  }

  return results;
}
