import assert from 'node:assert/strict';
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';

const original = process.argv.includes('--original');
const wrapper = fs.readFileSync(original ? new URL('./bb-browser.original', import.meta.url) : '/Users/songmenglvshi/.local/bin/bb-browser', 'utf8');
const cli = fs.readFileSync(original ? new URL('./cli.original.js', import.meta.url) : '/Users/songmenglvshi/.local/share/bb-browser/0.14.2/node_modules/bb-browser/dist/cli.js', 'utf8');
const start = cli.indexOf('async function discoverCdpPort() {');
assert.ok(start >= 0, 'find installed discovery function');
const end = cli.indexOf('// packages/cli/src/daemon-manager.ts', start);
assert.ok(end > start, 'find discovery function boundary');
const discovery = cli.slice(start, end);
let failed = 0;
let passed = 0;
async function check(name, run) {
  try { await run(); passed++; console.log(`PASS ${name}`); }
  catch (error) { failed++; console.log(`FAIL ${name}: ${error.message}`); }
}

// Keep the real wrapper branches; replace only curl and the final CLI process.
function shell(args, reachable = false) {
  assert.ok(wrapper.includes('/usr/bin/curl'));
  assert.match(wrapper, /^exec .*$/m);
  const input = wrapper.replace('/usr/bin/curl', reachable ? '/usr/bin/true' : '/usr/bin/false').replace(/^exec .*$/m, 'echo CLI_REACHED');
  return spawnSync('/bin/sh', ['-s', '--', ...args], { input, encoding: 'utf8' });
}
for (const flag of ['--help', '-h', '--version', '-v']) {
  await check(`single ${flag} works without Chrome`, () => {
    const r = shell([flag]);
    assert.equal(r.status, 0);
    assert.match(r.stdout, /CLI_REACHED/);
  });
  await check(`${flag} with daemon start cannot bypass unavailable Chrome`, () => {
    const r = shell([flag, 'daemon', 'start']);
    assert.equal(r.status, 1);
    assert.equal(r.stdout, '');
  });
}
await check('normal read fails when dedicated Chrome is absent', () => {
  const r = shell(['get', 'title', '--tab', '07a1']);
  assert.equal(r.status, 1);
  assert.equal(r.stdout, '');
});
await check('normal read reaches CLI when dedicated Chrome is available', () => {
  assert.equal(shell(['get', 'title', '--tab', '07a1'], true).status, 0);
});

// Execute the actual installed function. Connection/argument dependencies have
// no network, filesystem or process side effects. Alternate port is available
// specifically to expose any unwanted fallback after explicit CDP failure.
function discover(url, available) {
  const calls = [];
  const run = new Function('process', 'canConnect', 'getArgValue', `${discovery};return discoverCdpPort;`)(
    { env: { BB_BROWSER_CDP_URL: url } },
    async (host, port) => { calls.push([host, port]); return available.includes(port); },
    () => '19333'
  );
  return { run, calls };
}
for (const url of ['http://127.0.0.1:19224', 'invalid-url', 'http://127.0.0.1']) {
  await check(`explicit unavailable/invalid CDP fails closed: ${url}`, async () => {
    const { run, calls } = discover(url, [19333]);
    await assert.rejects(run, /BB_BROWSER_CDP_URL/);
    assert.equal(calls.some(([, port]) => port === 19333), false);
  });
}
await check('reachable explicit dedicated CDP remains selected', async () => {
  const { run, calls } = discover('http://127.0.0.1:19224', [19224, 19333]);
  assert.deepEqual(await run(), { host: '127.0.0.1', port: 19224 });
  assert.deepEqual(calls, [['127.0.0.1', 19224]]);
});
await check('no explicit CDP retains upstream explicit-port behavior', async () => {
  const { run } = discover(undefined, [19333]);
  assert.deepEqual(await run(), { host: '127.0.0.1', port: 19333 });
});
console.log(`RESULT ${original ? 'original' : 'installed'}: ${passed} passed, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
