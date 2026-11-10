import test from 'node:test';
import assert from 'node:assert/strict';
import { requestWatchdog } from '../src/context/requestWatchdog.js';

test('stalled fetch or read expires and aborts transport', async () => {
  const watch = requestWatchdog(20);
  await assert.rejects(watch.wait(new Promise(() => {})), /deadline/);
  assert.equal(watch.signal.aborted, true);
  assert.equal(watch.expired, true);
  watch.dispose();
});

test('normal result is returned and watchdog is cleaned up', async () => {
  const watch = requestWatchdog(1000);
  assert.equal(await watch.wait(Promise.resolve('completed')), 'completed');
  watch.dispose();
  assert.equal(watch.expired, false);
});
