/**
 * Copy tree-sitter WASM grammars from node_modules into src/grammars/
 * so they get bundled when the package is published.
 *
 * Run with: npx tsx scripts/download-grammars.ts
 */

import { copyFileSync, mkdirSync, existsSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const SOURCE_DIR = join(__dirname, '..', 'node_modules', 'tree-sitter-wasms', 'out');
const DEST_DIR = join(__dirname, '..', 'src', 'grammars');

const GRAMMARS = [
  'tree-sitter-javascript.wasm',
  'tree-sitter-typescript.wasm',
  'tree-sitter-tsx.wasm',
  'tree-sitter-python.wasm',
];

function main() {
  if (!existsSync(SOURCE_DIR)) {
    console.error('Error: tree-sitter-wasms not installed. Run: npm install tree-sitter-wasms');
    process.exit(1);
  } 

  if (!existsSync(DEST_DIR)) {
    mkdirSync(DEST_DIR, { recursive: true });
    console.log(`Created: ${DEST_DIR}`);
  }

  for (const file of GRAMMARS) {
    const src = join(SOURCE_DIR, file);
    const dest = join(DEST_DIR, file);

    if (!existsSync(src)) {
      console.error(`  ✗ Not found: ${src}`);
      continue;
    }

    copyFileSync(src, dest);
    const size = Math.round(statSync(dest).size / 1024);
    console.log(`  ✓ ${file} (${size}KB)`);
  }

  console.log('\nDone! Grammars copied to:', DEST_DIR);
}

main();
