// Actual vendored functions, synthetic dependencies, no sockets or child process.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const base = new URL(process.argv.includes('--before') ? '../verification/windows10-2026-10-11/task3b-before/' : '../vendor/bb-browser/package/dist/', import.meta.url);
const cli = fs.readFileSync(new URL('cli.js', base), 'utf8');
const daemon = fs.readFileSync(new URL('daemon.js', base), 'utf8');
const slice = (text, start, end) => text.slice(text.indexOf(start), text.indexOf(end, text.indexOf(start)));
let failures = 0;
async function check(name, fn) {
  try { await fn(); console.log('PASS ' + name); }
  catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}
const discovery = slice(cli, 'async function discoverCdpPort() {', '// packages/cli/src/daemon-manager.ts');
await check('explicit CDP disconnected never falls back', async () => {
  const calls = [];
  const fn = new Function('process', 'canConnect', 'getArgValue', discovery + ';return discoverCdpPort')(
    {env: {BB_BROWSER_CDP_URL:'http://127.0.0.1:19224'}}, async (host, port) => {calls.push(port); return port === 9222;}, () => '9222');
  await assert.rejects(fn, /BB_BROWSER_CDP_URL/);
  assert.deepEqual(calls, [19224]);
});
await check('spawned daemon always no-chrome', () => {
  const declaration = cli.match(/const daemonArgs = \[daemonPath[^;]+;/)[0];
  assert.match(declaration, /"--no-chrome"/);
});
await check('daemon stale state cannot shut down or kill a PID', async () => {
  const body = slice(daemon, 'async function cleanupStaleDaemon() {', 'async function main() {');
  const fn = new Function('process', 'existsSync4', 'DAEMON_JSON', 'readStaleDaemonJson', 'isProcessAlive', 'cleanupDaemonJson', body + ';return cleanupStaleDaemon')(
    {platform:'win32', pid:5, kill:() => assert.fail('must not kill')}, () => true, 'synthetic',
    () => ({pid:123}), () => false, () => {});
  await assert.rejects(fn, /stale|existing|review/i);
});
// Execute actual main, its outer catch, and shutdown with real synthetic files.
const daemonLifecycle = slice(daemon, 'function writeDaemonJson(info) {', 'async function discoverCdpPort(host, port) {') +
  slice(daemon, 'async function cleanupStaleDaemon() {', '//# sourceMappingURL=daemon.js.map')
    .replace('main().catch', 'return main().catch');
async function withDaemonState(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bb-state-test-'));
  const state = path.join(dir, 'daemon.json');
  const original = Buffer.from('{"pid":731,"note":"synthetic foreign state"}\n');
  const effects = [];
  function run(start = async () => {}, stop = async () => {}) {
    const handlers = new Map();
    const dependencies = {
      process: {platform:'win32', pid:632, on:(sig, cb) => handlers.set(sig, cb),
        exit:code => effects.push(['exit', code]), kill:() => assert.fail('must not kill')},
      existsSync4:fs.existsSync, mkdirSync4:fs.mkdirSync, writeFileSync4:fs.writeFileSync,
      unlinkSync2:file => {effects.push(['unlink']); fs.unlinkSync(file);},
      DAEMON_DIR2:dir, DAEMON_JSON:state,
      parseOptions:() => ({noChrome:true, host:'127.0.0.1', port:19824, token:'synthetic-only',
        cdpHost:'127.0.0.1', cdpPort:19224}),
      console:{error:() => {}}, TabStateManager:class {tabCount = 0;},
      discoverCdpPort:async () => ({host:'127.0.0.1', port:19224}),
      CdpConnection:class {async connect() {} disconnect() {}},
      HttpServer:class {async start() {await start();} async stop() {await stop();}}
    };
    const done = new Function(...Object.keys(dependencies), daemonLifecycle)(...Object.values(dependencies));
    return {done, handlers};
  }
  try { await fn({state, original, effects, run}); }
  finally { fs.rmSync(dir, {recursive:true, force:true}); }
}
await check('actual outer catch preserves refused foreign state byte-for-byte', async () => {
  await withDaemonState(async ({state, original, effects, run}) => {
    fs.writeFileSync(state, original);
    await run().done;
    assert.deepEqual(effects, [['exit', 1]]);
    assert.deepEqual(fs.readFileSync(state), original);
  });
});
await check('concurrent main port failure preserves the winning state byte-for-byte', async () => {
  await withDaemonState(async ({state, effects, run}) => {
    let release;
    const gate = new Promise(resolve => {release = resolve;});
    // Both actual mains pass the initial absent-file check before either binds.
    const winner = run();
    const loser = run(async () => {await gate; throw new Error('synthetic port conflict');});
    await winner.done;
    const winningBytes = fs.readFileSync(state);
    release();
    await loser.done;
    assert.deepEqual(effects, [['exit', 1]]);
    assert.deepEqual(fs.readFileSync(state), winningBytes);
  });
});
await check('actual shutdown retains owned and replacement state byte-for-byte', async () => {
  for (const replace of [false, true]) {
    await withDaemonState(async ({state, original, effects, run}) => {
      const instance = run(async () => {}, async () => {
        if (replace) fs.writeFileSync(state, original);
      });
      await instance.done;
      const expected = replace ? original : fs.readFileSync(state);
      await instance.handlers.get('SIGTERM')();
      assert.deepEqual(effects, [['exit', 0]]);
      assert.deepEqual(fs.readFileSync(state), expected);
    });
  }
});
await check('CLI stop cannot kill or contact an unverified old PID', async () => {
  const body = slice(cli, 'async function stopDaemon() {', 'async function getDaemonStatus() {');
  const fn = new Function('process', 'cachedInfo', 'daemonReady', 'httpJson', 'existsSync2', 'DAEMON_JSON', body + ';return stopDaemon')(
    {platform:'win32'}, {pid:123}, true, async () => ({}), () => false, 'synthetic');
  await assert.rejects(fn, /review|disabled/i);
});
await check('actual CLI cleanup callers refuse stale or replaced state without unlink', async () => {
  const body = slice(cli, 'async function deleteDaemonJson() {', 'function getDaemonPath() {') +
    slice(cli, 'async function ensureDaemon() {', 'async function daemonCommand(request) {') +
    slice(cli, 'async function stopDaemon() {', 'async function getDaemonStatus() {');
  await withDaemonState(async ({state, original}) => {
    fs.writeFileSync(state, original);
    const fn = new Function('process', 'cachedInfo', 'daemonReady', 'readDaemonJson',
      'isProcessAlive', 'unlink', 'DAEMON_JSON', body + ';return {ensureDaemon,stopDaemon}')(
        {platform:'win32'}, null, false, async () => {
          fs.writeFileSync(state, original);
          return {pid:731};
        }, () => false, async file => {fs.unlinkSync(file); assert.fail('must not unlink');}, state);
    await assert.rejects(fn.ensureDaemon, /review/);
    assert.deepEqual(fs.readFileSync(state), original);
    await assert.rejects(fn.stopDaemon, /review/);
    assert.deepEqual(fs.readFileSync(state), original);
  });
});
await check('daemon fixed CDP failure refuses managed-port fallback', async () => {
  const body = slice(daemon, 'async function discoverCdpPort(host, port) {', 'function readStaleDaemonJson() {');
  const fn = new Function('process', 'fetch', 'path3', 'DAEMON_DIR2', 'readFileSync5', body + ';return discoverCdpPort')(
    {platform:'win32'}, async url => ({ok: url.includes(':9222/')}), {join:()=> 'synthetic'}, 'synthetic', () => '9222');
  await assert.rejects(() => fn('127.0.0.1', 19224), /dedicated|19224/i);
  await assert.rejects(() => fn('foreign', 9222), /dedicated|19224/i);
});
await check('actual CLI parser recognizes guarded routes with global options', () => {
  const body = slice(cli, 'function parseArgs(argv) {', 'async function main() {');
  const parse = new Function(body + ';return parseArgs')();
  for (const args of [['site','recommend'], ['--json','site','recommend'],
                      ['--jq','.','site','--days','3','recommend'],
                      ['--tab','site','site','update'], ['site','--filter','unused','update']]) {
    const parsed = parse(['node','cli',...args]);
    assert.equal(parsed.command, 'site');
    assert.ok(['recommend','update'].includes(parsed.args[0]));
  }
  for (const args of [['--openclaw','site','example/demo'], ['site','--openclaw','example/demo'],
                      ['site','example/demo','--openclaw']]) {
    assert.equal(parse(['node','cli',...args]).flags.openclaw, true);
  }
});
await check('Windows normal site route performs no implicit update work', async () => {
  const body = slice(cli, 'async function siteCommand(args, options = {}) {', '// packages/cli/src/commands/open.ts');
  const calls = [];
  const fn = new Function('process', 'siteList', 'join2', 'COMMUNITY_SITES_DIR', 'existsSync4',
    body + ';return siteCommand')({platform:'win32'}, async () => calls.push('site_list'),
    (...parts) => parts.join('/'), 'C:/Synthetic User/private/bb-state/bb-sites',
    () => {calls.push('update_filesystem_probe'); return false;});
  await fn(['list'], {json:true});
  assert.deepEqual(calls, ['site_list']);
});
await check('both site roots resolve this installation without consulting old home', () => {
  for (const [source, joinName, homeName] of [[cli, 'join2', 'homedir2'], [daemon, 'join', 'homedir']]) {
    const declaration = source.match(/var BB_DIR = [^;]+;/)[0];
    const actual = new Function('process', joinName, homeName, declaration + ';return BB_DIR')(
      {env:{BB_BROWSER_HOME:'C:/Synthetic User/private/bb-state'}}, (...parts) => parts.join('/'),
      () => {throw new Error('old home consulted');});
    assert.equal(actual, 'C:/Synthetic User/private/bb-state');
  }
});
process.exitCode = failures ? 1 : 0;
