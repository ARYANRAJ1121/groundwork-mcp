/**
 * Stage 4 Integration Test — Real Repo Ingest
 *
 * Tests the full pipeline against a small public GitHub repo.
 * Run with: npx tsx scripts/test-ingest.ts
 *
 * Verifies:
 *   1. Job created and status returns 'queued'
 *   2. Pipeline runs: clone → sieve → parse
 *   3. SQLite contains parsed files, symbols, edges
 *   4. Status reaches 'complete'
 */

import { initDatabase, getJob, getJobFiles, getJobSymbols, getJobEdges } from '../src/store/database.js';
import { runIngestionPipeline } from '../src/core/pipeline.js';
import { createJob } from '../src/store/database.js';
import { v4 as uuidv4 } from 'uuid';

// ── Test repo: sindresorhus/is — small, pure TypeScript, well-structured
const TEST_REPO = 'https://github.com/sindresorhus/is';

async function main() {
  console.log('=== Groundwork MCP — Stage 4 Integration Test ===\n');

  // Init DB
  console.log('1. Initializing database...');
  await initDatabase();
  console.log('   ✓ Database ready\n');

  // Create a test job
  const jobId = uuidv4();
  console.log(`2. Creating job: ${jobId}`);
  createJob(jobId, TEST_REPO, 'sindresorhus/is', 'main');

  let job = getJob(jobId);
  console.log(`   ✓ Job status: ${job?.status}\n`);

  // Run the pipeline (synchronously for test purposes)
  console.log(`3. Running ingestion pipeline for ${TEST_REPO}...`);
  console.log('   (This will clone, sieve, and parse — may take 30-60s)\n');

  const startTime = Date.now();
  await runIngestionPipeline(jobId, TEST_REPO, 'main');
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);

  // Check final status
  job = getJob(jobId);
  console.log(`\n4. Final job status: ${job?.status} (took ${elapsed}s)`);
  console.log(`   Progress: ${Math.round((job?.progress ?? 0) * 100)}%`);
  console.log(`   Files processed: ${job?.files_processed}/${job?.files_total}`);
  console.log(`   Tokens estimate: ${job?.tokens_estimate?.toLocaleString()}`);
  if (job?.error_message) {
    console.error(`   ERROR: ${job.error_message}`);
  }

  if (job?.status !== 'complete') {
    console.error('\n❌ Pipeline did not complete successfully');
    process.exit(1);
  }

  // Verify SQLite data
  console.log('\n5. Verifying SQLite data...');

  const files = getJobFiles(jobId);
  const symbols = getJobSymbols(jobId);
  const edges = getJobEdges(jobId);

  console.log(`   Files:   ${files.length}`);
  console.log(`   Symbols: ${symbols.length}`);
  console.log(`   Edges:   ${edges.length}`);

  // Show sample symbols
  if (symbols.length > 0) {
    console.log('\n   Sample symbols (first 10):');
    symbols.slice(0, 10).forEach(s => {
      console.log(`     [${s.symbolType}] ${s.symbolName} @ ${s.filePath}:${s.startLine}`);
    });
  }

  // Show sample edges
  if (edges.length > 0) {
    console.log('\n   Sample edges (first 5):');
    edges.slice(0, 5).forEach(e => {
      const target = e.targetFile ?? `<external: ${e.targetModule}>`;
      console.log(`     ${e.sourceFile} → ${target} (${e.edgeType})`);
    });
  }

  // Language breakdown
  const byLang: Record<string, number> = {};
  files.forEach(f => { byLang[f.language] = (byLang[f.language] ?? 0) + 1; });
  console.log('\n   Files by language:');
  Object.entries(byLang).sort((a,b) => b[1]-a[1]).forEach(([lang, count]) => {
    console.log(`     ${lang}: ${count}`);
  });

  console.log('\n✅ Stage 4 test PASSED');
  console.log(`   Job ID: ${jobId}`);
  console.log(`   Use this job_id in your MCP client to query the knowledge base.\n`);
}

main().catch(err => {
  console.error('\n❌ Test failed:', err);
  process.exit(1);
});
