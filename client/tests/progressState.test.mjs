import { test } from 'node:test';
import assert from 'node:assert/strict';
import { progressState, STAGES } from '../src/components/chat/progressState.js';
test('pending stages use a running clock and terminal stages stop it', () => {
  assert.deepEqual(progressState({stage:'planning',pending:true,startedAt:100},600), {stage:'planning',pending:true,elapsed:500});
  assert.deepEqual(progressState({stage:'completed',pending:false,startedAt:100,elapsedMs:200},600), {stage:'completed',pending:false,elapsed:200});
  assert.equal(progressState({stage:'unsupported',pending:true}).pending,false);
  for (const stage of ['planning','repairing_plan','validating','publishing','unsupported']) assert.ok(STAGES[stage]);
});
test('reloaded messages restore terminal status and measured time without NaN', () => {
  assert.deepEqual(progressState({metadata:{request_stage:'incomplete',elapsed_ms:1200}}), {stage:'incomplete',pending:false,elapsed:1200});
  assert.equal(progressState({metadata:{analysis_status:'complete'}}).stage,'completed');
  assert.equal(progressState({metadata:{analysis_failed:true}}).stage,'failed');
  assert.equal(progressState({metadata:{analysis_status:'complete'}}).elapsed,undefined);
});
