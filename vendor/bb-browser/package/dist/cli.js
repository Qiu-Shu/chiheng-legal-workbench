#!/usr/bin/env node
import {
  COMMAND_TIMEOUT,
  DAEMON_JSON,
  httpJson,
  isProcessAlive,
  readDaemonJson
} from "./chunk-ELAKRFAZ.js";
import {
  applyJq
} from "./chunk-AHGAQEFO.js";
import {
  parseOpenClawJson
} from "./chunk-FSL4RNI6.js";

// packages/cli/src/daemon-manager.ts
import { spawn as spawn2 } from "child_process";
import { unlink } from "fs/promises";
import { fileURLToPath } from "url";
import { dirname, resolve } from "path";
import { existsSync as existsSync2 } from "fs";

// packages/cli/src/cdp-discovery.ts
import { execFile, execSync, spawn } from "child_process";
import { existsSync } from "fs";
import { mkdir, readFile, writeFile } from "fs/promises";
import os from "os";
import path from "path";
var DEFAULT_CDP_PORT = 9222;
var MANAGED_BROWSER_DIR = path.join(os.homedir(), ".bb-browser", "browser");
var MANAGED_USER_DATA_DIR = path.join(MANAGED_BROWSER_DIR, "user-data");
var MANAGED_PORT_FILE = path.join(MANAGED_BROWSER_DIR, "cdp-port");
var CDP_CACHE_FILE = path.join(os.tmpdir(), "bb-browser-cdp-cache.json");
var CACHE_TTL_MS = 3e4;
function execFileAsync(command, args, timeout) {
  return new Promise((resolve2, reject) => {
    execFile(command, args, { encoding: "utf8", timeout }, (error, stdout) => {
      if (error) {
        reject(error);
        return;
      }
      resolve2(stdout.trim());
    });
  });
}
function getArgValue(flag) {
  const index = process.argv.indexOf(flag);
  if (index < 0) return void 0;
  return process.argv[index + 1];
}
async function tryOpenClaw() {
  try {
    const raw = await execFileAsync("npx", ["openclaw", "browser", "status", "--json"], 3e4);
    const parsed = parseOpenClawJson(raw);
    let result = null;
    if (parsed?.cdpUrl) {
      try {
        const url = new URL(parsed.cdpUrl);
        const port = Number(url.port);
        if (Number.isInteger(port) && port > 0) {
          result = { host: url.hostname, port };
        }
      } catch {
      }
    }
    if (!result) {
      const port = Number(parsed?.cdpPort);
      if (Number.isInteger(port) && port > 0) {
        const host = parsed?.cdpHost || "127.0.0.1";
        result = { host, port };
      }
    }
    if (result) {
      try {
        await writeFile(CDP_CACHE_FILE, JSON.stringify({ ...result, timestamp: Date.now() }), "utf8");
      } catch {
      }
    }
    return result;
  } catch {
  }
  return null;
}
async function canConnect(host, port) {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1200);
    const response = await fetch(`http://${host}:${port}/json/version`, { signal: controller.signal });
    clearTimeout(timeout);
    return response.ok;
  } catch {
    return false;
  }
}
function findBrowserExecutable() {
  if (process.platform === "darwin") {
    const candidates = [
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
      "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
      "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
      "/Applications/Arc.app/Contents/MacOS/Arc",
      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    ];
    return candidates.find((candidate) => existsSync(candidate)) ?? null;
  }
  if (process.platform === "linux") {
    const candidates = ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"];
    for (const candidate of candidates) {
      try {
        const resolved = execSync(`which ${candidate}`, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
        if (resolved) {
          return resolved;
        }
      } catch {
      }
    }
    return null;
  }
  if (process.platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA ?? "";
    const candidates = [
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      ...localAppData ? [
        `${localAppData}\\Google\\Chrome Dev\\Application\\chrome.exe`,
        `${localAppData}\\Google\\Chrome SxS\\Application\\chrome.exe`,
        `${localAppData}\\Google\\Chrome Beta\\Application\\chrome.exe`
      ] : [],
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
    ];
    return candidates.find((candidate) => existsSync(candidate)) ?? null;
  }
  return null;
}
async function launchManagedBrowser(port = DEFAULT_CDP_PORT) {
  const executable = findBrowserExecutable();
  if (!executable) {
    return null;
  }
  await mkdir(MANAGED_USER_DATA_DIR, { recursive: true });
  const defaultProfileDir = path.join(MANAGED_USER_DATA_DIR, "Default");
  const prefsPath = path.join(defaultProfileDir, "Preferences");
  await mkdir(defaultProfileDir, { recursive: true });
  try {
    let prefs = {};
    try {
      prefs = JSON.parse(await readFile(prefsPath, "utf8"));
    } catch {
    }
    if (!prefs.profile?.name || prefs.profile.name !== "bb-browser") {
      prefs.profile = { ...prefs.profile || {}, name: "bb-browser" };
      await writeFile(prefsPath, JSON.stringify(prefs), "utf8");
    }
  } catch {
  }
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${MANAGED_USER_DATA_DIR}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-features=Translate,MediaRouter",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--use-mock-keychain",
    "about:blank"
  ];
  try {
    const child = spawn(executable, args, {
      detached: true,
      stdio: "ignore"
    });
    child.unref();
  } catch {
    return null;
  }
  await mkdir(MANAGED_BROWSER_DIR, { recursive: true });
  await writeFile(MANAGED_PORT_FILE, String(port), "utf8");
  const deadline = Date.now() + 8e3;
  while (Date.now() < deadline) {
    if (await canConnect("127.0.0.1", port)) {
      return { host: "127.0.0.1", port };
    }
    await new Promise((resolve2) => setTimeout(resolve2, 250));
  }
  return null;
}
async function discoverCdpPort() {
  const envUrl = process.env.BB_BROWSER_CDP_URL;
  if (envUrl) {
    try {
      const url = new URL(envUrl);
      const port = Number(url.port);
      if (Number.isInteger(port) && port > 0 && await canConnect(url.hostname, port)) {
        return { host: url.hostname, port };
      }
    } catch {
    }
    throw new Error("BB_BROWSER_CDP_URL is invalid or unreachable; refusing browser discovery fallback.");
  }
  const explicitPort = Number.parseInt(getArgValue("--port") ?? "", 10);
  if (Number.isInteger(explicitPort) && explicitPort > 0 && await canConnect("127.0.0.1", explicitPort)) {
    return { host: "127.0.0.1", port: explicitPort };
  }
  try {
    const rawPort = await readFile(MANAGED_PORT_FILE, "utf8");
    const managedPort = Number.parseInt(rawPort.trim(), 10);
    if (Number.isInteger(managedPort) && managedPort > 0 && await canConnect("127.0.0.1", managedPort)) {
      return { host: "127.0.0.1", port: managedPort };
    }
  } catch {
  }
  try {
    const cacheRaw = await readFile(CDP_CACHE_FILE, "utf8");
    const cache = JSON.parse(cacheRaw);
    if (Date.now() - cache.timestamp < CACHE_TTL_MS && await canConnect(cache.host, cache.port)) {
      return { host: cache.host, port: cache.port };
    }
  } catch {
  }
  if (process.argv.includes("--openclaw")) {
    const viaOpenClaw = await tryOpenClaw();
    if (viaOpenClaw && await canConnect(viaOpenClaw.host, viaOpenClaw.port)) {
      return viaOpenClaw;
    }
  }
  const launched = await launchManagedBrowser();
  if (launched) {
    return launched;
  }
  if (!process.argv.includes("--openclaw")) {
    const detectedOpenClaw = await tryOpenClaw();
    if (detectedOpenClaw && await canConnect(detectedOpenClaw.host, detectedOpenClaw.port)) {
      return detectedOpenClaw;
    }
  }
  return null;
}

// packages/cli/src/daemon-manager.ts
var cachedInfo = null;
var daemonReady = false;
async function deleteDaemonJson() {
  try {
    await unlink(DAEMON_JSON);
  } catch {
  }
}
function getDaemonPath() {
  const currentFile = fileURLToPath(import.meta.url);
  const currentDir = dirname(currentFile);
  const sameDirPath = resolve(currentDir, "daemon.js");
  if (existsSync2(sameDirPath)) {
    return sameDirPath;
  }
  return resolve(currentDir, "../../daemon/dist/index.js");
}
async function ensureDaemon() {
  if (daemonReady && cachedInfo) {
    try {
      const status = await httpJson("GET", "/status", cachedInfo, void 0, 2e3);
      if (status.running && status.cdpConnected !== false) {
        return;
      }
    } catch {
    }
    daemonReady = false;
    cachedInfo = null;
  }
  let info = await readDaemonJson();
  if (info) {
    if (!isProcessAlive(info.pid)) {
      if (process.platform === "win32") throw new Error("Stale daemon state requires manual identity review.");
      await deleteDaemonJson();
      info = null;
    }
  }
  const cdpInfo = await discoverCdpPort();
  if (!cdpInfo) {
    throw new Error(
      "bb-browser: Cannot find a Chromium-based browser.\n\nPlease do one of the following:\n  1. Install Google Chrome, Edge, or Brave\n  2. Start Chrome with: google-chrome --remote-debugging-port=9222\n  3. Set BB_BROWSER_CDP_URL=http://host:port"
    );
  }
  if (info && info.cdpPort !== cdpInfo.port) {
    await stopDaemon();
    info = null;
  }
  if (info) {
    try {
      const status = await httpJson("GET", "/status", info, void 0, 2e3);
      if (status.running && status.cdpConnected !== false) {
        cachedInfo = info;
        daemonReady = true;
        return;
      }
      if (status.running && status.cdpConnected === false) {
        await stopDaemon();
        info = null;
      }
    } catch {
      await stopDaemon();
      info = null;
    }
  }
  const daemonPath = getDaemonPath();
  const daemonArgs = [daemonPath, "--no-chrome", "--cdp-host", cdpInfo.host, "--cdp-port", String(cdpInfo.port)];
  const hubUrl = process.env.BB_BROWSER_HUB_URL || process.env.PINIX_HUB_URL;
  const hubToken = process.env.BB_BROWSER_HUB_TOKEN || process.env.PINIX_HUB_TOKEN || process.env.PINIX_TOKEN;
  if (hubUrl) {
    daemonArgs.push("--hub", hubUrl);
    if (hubToken) daemonArgs.push("--hub-token", hubToken);
  }
  const child = spawn2(process.execPath, daemonArgs, {
    detached: true,
    stdio: "ignore"
  });
  child.unref();
  const deadline = Date.now() + 1e4;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    info = await readDaemonJson();
    if (!info) continue;
    try {
      const status = await httpJson("GET", "/status", info, void 0, 2e3);
      if (status.running) {
        cachedInfo = info;
        daemonReady = true;
        return;
      }
    } catch {
    }
  }
  throw new Error(
    "bb-browser: Daemon did not start in time.\n\nChrome CDP is reachable, but the daemon process failed to initialize.\nTry: bb-browser daemon status"
  );
}
async function daemonCommand(request) {
  if (!cachedInfo) {
    cachedInfo = await readDaemonJson();
  }
  if (!cachedInfo) {
    throw new Error("No daemon.json found. Is the daemon running?");
  }
  return httpJson("POST", "/command", cachedInfo, request, COMMAND_TIMEOUT);
}
async function stopDaemon() {
  if (process.platform === "win32") throw new Error("Automatic daemon stop disabled; manual identity review required.");
  const info = cachedInfo ?? await readDaemonJson();
  if (!info) return false;
  daemonReady = false;
  cachedInfo = null;
  try {
    await httpJson("POST", "/shutdown", info, void 0, 3e3);
  } catch {
  }
  const deadline = Date.now() + 5e3;
  while (Date.now() < deadline) {
    if (!existsSync2(DAEMON_JSON)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  if (isProcessAlive(info.pid)) {
    try {
      process.kill(info.pid, "SIGKILL");
    } catch {
    }
  }
  await deleteDaemonJson();
  return true;
}
async function getDaemonStatus() {
  const info = cachedInfo ?? await readDaemonJson();
  if (!info) return null;
  try {
    return await httpJson("GET", "/status", info, void 0, 2e3);
  } catch {
    return null;
  }
}
var ensureDaemonRunning = ensureDaemon;

// packages/cli/src/client.ts
var jqExpression;
function setJqExpression(expression) {
  jqExpression = expression;
}
function printJqResults(response) {
  const target = response.result ?? response;
  const results = applyJq(target, jqExpression || ".");
  for (const result of results) {
    console.log(typeof result === "string" ? result : JSON.stringify(result));
  }
  process.exit(0);
}
function handleJqResponse(response) {
  if (jqExpression) {
    printJqResults(response);
  }
}
async function sendCommand(request) {
  await ensureDaemon();
  return daemonCommand(request);
}

// packages/cli/src/history-sqlite.ts
import { copyFileSync, existsSync as existsSync3, unlinkSync } from "fs";
import { execSync as execSync2 } from "child_process";
import { homedir, tmpdir } from "os";
import { join } from "path";
function getHistoryPathCandidates() {
  const home = homedir();
  const localAppData = process.env.LOCALAPPDATA || "";
  const candidates = [
    join(home, "Library/Application Support/Google/Chrome/Default/History"),
    join(home, "Library/Application Support/Microsoft Edge/Default/History"),
    join(home, "Library/Application Support/BraveSoftware/Brave-Browser/Default/History"),
    join(home, "Library/Application Support/Arc/User Data/Default/History"),
    join(home, ".config/google-chrome/Default/History")
  ];
  if (localAppData) {
    candidates.push(
      join(localAppData, "Google/Chrome/User Data/Default/History"),
      join(localAppData, "Microsoft/Edge/User Data/Default/History")
    );
  }
  return candidates;
}
function findHistoryPath() {
  for (const historyPath of getHistoryPathCandidates()) {
    if (existsSync3(historyPath)) {
      return historyPath;
    }
  }
  return null;
}
function buildTimeWhere(days) {
  if (!days || days <= 0) {
    return "";
  }
  return `last_visit_time > (strftime('%s', 'now') - ${Math.floor(days)}*86400) * 1000000 + 11644473600000000`;
}
function runHistoryQuery(sql, mapRow) {
  const historyPath = findHistoryPath();
  if (!historyPath) {
    return [];
  }
  const tmpPath = join(tmpdir(), `bb-history-${Date.now()}-${Math.random().toString(36).slice(2)}.db`);
  try {
    copyFileSync(historyPath, tmpPath);
    const escapedTmpPath = tmpPath.replace(/"/g, '\\"');
    const escapedSql = sql.replace(/"/g, '\\"');
    const output = execSync2(`sqlite3 -separator $'\\t' "${escapedTmpPath}" "${escapedSql}"`, {
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"]
    });
    return output.split("\n").filter(Boolean).map((line) => mapRow(line.split("	"))).filter((item) => item !== null);
  } catch {
    return [];
  } finally {
    try {
      unlinkSync(tmpPath);
    } catch {
    }
  }
}
function getHistoryDomains(days) {
  const timeWhere = buildTimeWhere(days);
  const whereClause = timeWhere ? `WHERE ${timeWhere}` : "";
  const sql = `
    SELECT
      domain,
      SUM(visit_count) AS visits,
      GROUP_CONCAT(title, char(31)) AS titles
    FROM (
      SELECT
        CASE
          WHEN instr(url, '//') > 0 AND instr(substr(url, instr(url, '//') + 2), '/') > 0
            THEN substr(
              substr(url, instr(url, '//') + 2),
              1,
              instr(substr(url, instr(url, '//') + 2), '/') - 1
            )
          WHEN instr(url, '//') > 0 THEN substr(url, instr(url, '//') + 2)
          WHEN instr(url, '/') > 0 THEN substr(url, 1, instr(url, '/') - 1)
          ELSE url
        END AS domain,
        IFNULL(visit_count, 0) AS visit_count,
        REPLACE(IFNULL(title, ''), char(31), ' ') AS title
      FROM urls
      ${whereClause}
    )
    WHERE domain != ''
    GROUP BY domain
    ORDER BY visits DESC
    LIMIT 50;
  `.trim();
  return runHistoryQuery(sql, (row) => {
    if (row.length < 3) {
      return null;
    }
    const titles = row[2] ? Array.from(new Set(row[2].split(String.fromCharCode(31)).map((title) => title.trim()).filter(Boolean))).slice(0, 10) : [];
    return {
      domain: row[0] || "",
      visits: Number(row[1]) || 0,
      titles
    };
  });
}

// packages/cli/src/commands/site.ts
import { readFileSync, readdirSync, existsSync as existsSync4, mkdirSync } from "fs";
import { join as join2, relative } from "path";
import { homedir as homedir2 } from "os";
import { execSync as execSync3 } from "child_process";
var BB_DIR = process.env.BB_BROWSER_HOME || join2(homedir2(), ".bb-browser");
var LOCAL_SITES_DIR = join2(BB_DIR, "sites");
var COMMUNITY_SITES_DIR = join2(BB_DIR, "bb-sites");
var COMMUNITY_REPO = "https://github.com/epiral/bb-sites.git";
function checkCliUpdate() {
  try {
    const current = execSync3("bb-browser --version", { timeout: 3e3, stdio: ["pipe", "pipe", "pipe"] }).toString().trim();
    const latest = execSync3("npm view bb-browser version", { timeout: 5e3, stdio: ["pipe", "pipe", "pipe"] }).toString().trim();
    if (latest && current && latest !== current && latest.localeCompare(current, void 0, { numeric: true }) > 0) {
      console.log(`
\u{1F4E6} bb-browser ${latest} available (current: ${current}). Run: npm install -g bb-browser`);
    }
  } catch {
  }
}
function exitJsonError(error, extra = {}) {
  console.log(JSON.stringify({ success: false, error, ...extra }, null, 2));
  process.exit(1);
}
function parseSiteMeta(filePath, source) {
  let content;
  try {
    content = readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
  const sitesDir = source === "local" ? LOCAL_SITES_DIR : COMMUNITY_SITES_DIR;
  const relPath = relative(sitesDir, filePath);
  const defaultName = relPath.replace(/\.js$/, "").replace(/\\/g, "/");
  const metaMatch = content.match(/\/\*\s*@meta\s*\n([\s\S]*?)\*\//);
  if (metaMatch) {
    try {
      const metaJson = JSON.parse(metaMatch[1]);
      return {
        name: metaJson.name || defaultName,
        description: metaJson.description || "",
        domain: metaJson.domain || "",
        args: metaJson.args || {},
        capabilities: metaJson.capabilities,
        readOnly: metaJson.readOnly,
        example: metaJson.example,
        filePath,
        source
      };
    } catch {
    }
  }
  const meta = {
    name: defaultName,
    description: "",
    domain: "",
    args: {},
    filePath,
    source
  };
  const tagPattern = /\/\/\s*@(\w+)[ \t]+(.*)/g;
  let match;
  while ((match = tagPattern.exec(content)) !== null) {
    const [, key, value] = match;
    switch (key) {
      case "name":
        meta.name = value.trim();
        break;
      case "description":
        meta.description = value.trim();
        break;
      case "domain":
        meta.domain = value.trim();
        break;
      case "args":
        for (const arg of value.trim().split(/[,\s]+/).filter(Boolean)) {
          meta.args[arg] = { required: true };
        }
        break;
      case "example":
        meta.example = value.trim();
        break;
    }
  }
  return meta;
}
function scanSites(dir, source) {
  if (!existsSync4(dir)) return [];
  const sites = [];
  function walk(currentDir) {
    let entries;
    try {
      entries = readdirSync(currentDir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const fullPath = join2(currentDir, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith(".")) {
        walk(fullPath);
      } else if (entry.isFile() && entry.name.endsWith(".js")) {
        const meta = parseSiteMeta(fullPath, source);
        if (meta) sites.push(meta);
      }
    }
  }
  walk(dir);
  return sites;
}
function getSiteHintForDomain(url) {
  try {
    const hostname = new URL(url).hostname;
    const sites = getAllSites();
    const matched = sites.filter((s) => s.domain && (hostname === s.domain || hostname.endsWith("." + s.domain)));
    if (matched.length === 0) return null;
    const names = matched.map((s) => s.name);
    const example = matched[0].example || `bb-browser site ${names[0]}`;
    return `\u8BE5\u7F51\u7AD9\u6709 ${names.length} \u4E2A site adapter \u53EF\u76F4\u63A5\u83B7\u53D6\u6570\u636E\uFF0C\u65E0\u9700\u624B\u52A8\u64CD\u4F5C\u6D4F\u89C8\u5668\u3002\u8BD5\u8BD5: ${example}`;
  } catch {
    return null;
  }
}
function getAllSites() {
  const community = scanSites(COMMUNITY_SITES_DIR, "community");
  const local = scanSites(LOCAL_SITES_DIR, "local");
  const byName = /* @__PURE__ */ new Map();
  for (const s of community) byName.set(s.name, s);
  for (const s of local) byName.set(s.name, s);
  return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name));
}
function findLocalSiteFile(name) {
  const sites = getAllSites();
  const site = sites.find((s) => s.name === name);
  return site?.filePath ?? null;
}
async function siteList(options) {
  const resp = await sendCommand({
    method: "site_list"
  });
  if (resp.error) {
    if (options.json) {
      exitJsonError(resp.error.message || "site_list failed");
    }
    console.error(`[error] site list: ${resp.error.message || "failed"}`);
    process.exit(1);
  }
  const sites = resp.result?.sites || [];
  if (sites.length === 0) {
    if (options.json) {
      console.log("[]");
      return;
    }
    console.log("\u672A\u627E\u5230\u4EFB\u4F55 site adapter\u3002");
    console.log("  \u5B89\u88C5\u793E\u533A adapter: bb-browser site update");
    console.log(`  \u79C1\u6709 adapter \u76EE\u5F55: ${LOCAL_SITES_DIR}`);
    return;
  }
  if (options.json) {
    console.log(JSON.stringify(sites, null, 2));
    return;
  }
  const groups = /* @__PURE__ */ new Map();
  for (const s of sites) {
    const platform = s.name.split("/")[0];
    if (!groups.has(platform)) groups.set(platform, []);
    groups.get(platform).push(s);
  }
  for (const [platform, items] of groups) {
    console.log(`
${platform}/`);
    for (const s of items) {
      const cmd = s.name.split("/").slice(1).join("/");
      const src = s.source === "local" ? " (local)" : "";
      const desc = s.description ? ` - ${s.description}` : "";
      console.log(`  ${cmd.padEnd(20)}${desc}${src}`);
    }
  }
  console.log();
}
async function siteSearch(query, options) {
  const resp = await sendCommand({
    method: "site_search",
    query
  });
  if (resp.error) {
    if (options.json) {
      exitJsonError(resp.error.message || "site_search failed");
    }
    console.error(`[error] site search: ${resp.error.message || "failed"}`);
    process.exit(1);
  }
  const matches = resp.result?.sites || [];
  if (matches.length === 0) {
    if (options.json) {
      console.log("[]");
      return;
    }
    console.log(`\u672A\u627E\u5230\u5339\u914D "${query}" \u7684 adapter\u3002`);
    console.log("  \u67E5\u770B\u6240\u6709: bb-browser site list");
    return;
  }
  if (options.json) {
    console.log(JSON.stringify(matches, null, 2));
    return;
  }
  for (const s of matches) {
    const src = s.source === "local" ? " (local)" : "";
    console.log(`${s.name.padEnd(24)} ${s.description}${src}`);
  }
}
function siteUpdate(options = {}) {
  mkdirSync(BB_DIR, { recursive: true });
  const updateMode = existsSync4(join2(COMMUNITY_SITES_DIR, ".git")) ? "pull" : "clone";
  if (updateMode === "pull") {
    if (!options.json) {
      console.log("\u66F4\u65B0\u793E\u533A site adapter \u5E93...");
    }
    try {
      execSync3("git pull --ff-only", { cwd: COMMUNITY_SITES_DIR, stdio: "pipe" });
      if (!options.json) {
        console.log("\u66F4\u65B0\u5B8C\u6210\u3002");
        console.log("");
        console.log("\u{1F4A1} \u8FD0\u884C bb-browser site recommend \u770B\u770B\u54EA\u4E9B\u548C\u4F60\u7684\u6D4F\u89C8\u4E60\u60EF\u5339\u914D");
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      const manualAction = "cd ~/.bb-browser/bb-sites && git pull";
      if (options.json) {
        exitJsonError(`\u66F4\u65B0\u5931\u8D25: ${message}`, { action: manualAction, updateMode });
      }
      console.error(`\u66F4\u65B0\u5931\u8D25: ${e instanceof Error ? e.message : e}`);
      console.error("  \u624B\u52A8\u4FEE\u590D: cd ~/.bb-browser/bb-sites && git pull");
      process.exit(1);
    }
  } else {
    if (!options.json) {
      console.log(`\u514B\u9686\u793E\u533A adapter \u5E93: ${COMMUNITY_REPO}`);
    }
    try {
      execSync3(`git clone ${COMMUNITY_REPO} ${COMMUNITY_SITES_DIR}`, { stdio: "pipe" });
      if (!options.json) {
        console.log("\u514B\u9686\u5B8C\u6210\u3002");
        console.log("");
        console.log("\u{1F4A1} \u8FD0\u884C bb-browser site recommend \u770B\u770B\u54EA\u4E9B\u548C\u4F60\u7684\u6D4F\u89C8\u4E60\u60EF\u5339\u914D");
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      const manualAction = `git clone ${COMMUNITY_REPO} ~/.bb-browser/bb-sites`;
      if (options.json) {
        exitJsonError(`\u514B\u9686\u5931\u8D25: ${message}`, { action: manualAction, updateMode });
      }
      console.error(`\u514B\u9686\u5931\u8D25: ${e instanceof Error ? e.message : e}`);
      console.error(`  \u624B\u52A8\u4FEE\u590D: git clone ${COMMUNITY_REPO} ~/.bb-browser/bb-sites`);
      process.exit(1);
    }
  }
  const sites = scanSites(COMMUNITY_SITES_DIR, "community");
  if (options.json) {
    console.log(JSON.stringify({
      success: true,
      updateMode,
      communityRepo: COMMUNITY_REPO,
      communityDir: COMMUNITY_SITES_DIR,
      siteCount: sites.length
    }, null, 2));
    return;
  }
  console.log(`\u5DF2\u5B89\u88C5 ${sites.length} \u4E2A\u793E\u533A adapter\u3002`);
  console.log(`\u2B50 Like bb-browser? \u2192 bb-browser star`);
  checkCliUpdate();
}
async function siteInfo(name, options) {
  const resp = await sendCommand({
    method: "site_info",
    siteName: name
  });
  if (resp.error) {
    if (options.json) {
      exitJsonError(resp.error.message || `adapter "${name}" not found`, { action: "bb-browser site list" });
    }
    console.error(`[error] site info: ${resp.error.message || `adapter "${name}" not found`}.`);
    console.error("  Try: bb-browser site list");
    process.exit(1);
  }
  const site = resp.result;
  if (options.json) {
    console.log(JSON.stringify({
      name: site.name,
      description: site.description,
      domain: site.domain,
      args: site.args,
      example: site.example,
      readOnly: site.readOnly
    }, null, 2));
    return;
  }
  console.log(`${site.name} \u2014 ${site.description}`);
  console.log();
  console.log("\u53C2\u6570\uFF1A");
  const argEntries = Object.entries(site.args || {});
  if (argEntries.length === 0) {
    console.log("  \uFF08\u65E0\uFF09");
  } else {
    for (const [argName, argDef] of argEntries) {
      const ad = argDef;
      const requiredText = ad.required ? "\u5FC5\u586B" : "\u53EF\u9009";
      const description = ad.description || "";
      console.log(`  ${argName} (${requiredText})    ${description}`.trimEnd());
    }
  }
  console.log();
  console.log("\u793A\u4F8B\uFF1A");
  console.log(`  ${site.example || `bb-browser site ${name}`}`);
  console.log();
  console.log(`\u57DF\u540D\uFF1A${site.domain || "\uFF08\u672A\u58F0\u660E\uFF09"}`);
  console.log(`\u53EA\u8BFB\uFF1A${site.readOnly ? "\u662F" : "\u5426"}`);
}
async function siteRecommend(options) {
  const days = options.days ?? 30;
  const historyDomains = getHistoryDomains(days);
  const sites = getAllSites();
  const sitesByDomain = /* @__PURE__ */ new Map();
  for (const site of sites) {
    if (!site.domain) continue;
    const domain = site.domain.toLowerCase();
    const existing = sitesByDomain.get(domain) || [];
    existing.push(site);
    sitesByDomain.set(domain, existing);
  }
  const available = [];
  const notAvailable = [];
  for (const item of historyDomains) {
    const adapters = sitesByDomain.get(item.domain.toLowerCase());
    if (adapters && adapters.length > 0) {
      const sortedAdapters = [...adapters].sort((a, b) => a.name.localeCompare(b.name));
      available.push({
        domain: item.domain,
        visits: item.visits,
        adapterCount: sortedAdapters.length,
        adapters: sortedAdapters.map((site) => ({
          name: site.name,
          description: site.description,
          example: site.example || `bb-browser site ${site.name}`
        }))
      });
    } else if (item.visits >= 5 && item.domain && !item.domain.includes("localhost") && item.domain.includes(".")) {
      notAvailable.push(item);
    }
  }
  const jsonData = {
    days,
    available,
    not_available: notAvailable
  };
  if (options.jq) {
    handleJqResponse({ result: jsonData });
  }
  if (options.json) {
    console.log(JSON.stringify(jsonData, null, 2));
    return;
  }
  console.log(`\u57FA\u4E8E\u4F60\u6700\u8FD1 ${days} \u5929\u7684\u6D4F\u89C8\u8BB0\u5F55\uFF1A`);
  console.log();
  console.log("\u{1F3AF} \u4F60\u5E38\u7528\u8FD9\u4E9B\u7F51\u7AD9\uFF0C\u53EF\u4EE5\u76F4\u63A5\u7528\uFF1A");
  console.log();
  if (available.length === 0) {
    console.log("  \uFF08\u6682\u65E0\u5339\u914D\u7684 adapter\uFF09");
  } else {
    for (const item of available) {
      console.log(`  ${item.domain.padEnd(20)} ${item.visits} \u6B21\u8BBF\u95EE    ${item.adapterCount} \u4E2A\u547D\u4EE4`);
      console.log(`    \u8BD5\u8BD5: ${item.adapters[0]?.example || `bb-browser site ${item.adapters[0]?.name || ""}`}`);
      console.log();
    }
  }
  console.log("\u{1F4CB} \u4F60\u5E38\u7528\u4F46\u8FD8\u6CA1\u6709 adapter\uFF1A");
  console.log();
  if (notAvailable.length === 0) {
    console.log("  \uFF08\u6682\u65E0\uFF09");
  } else {
    for (const item of notAvailable) {
      console.log(`  ${item.domain.padEnd(20)} ${item.visits} \u6B21\u8BBF\u95EE`);
    }
  }
  console.log();
  console.log('\u{1F4A1} \u8DDF\u4F60\u7684 AI Agent \u8BF4 "\u628A notion.so CLI \u5316"\uFF0C\u5B83\u5C31\u80FD\u81EA\u52A8\u5B8C\u6210\u3002');
  console.log();
  console.log(`\u6240\u6709\u5206\u6790\u7EAF\u672C\u5730\u5B8C\u6210\u3002\u7528 --days 7 \u53EA\u770B\u6700\u8FD1\u4E00\u5468\u3002`);
}
async function siteRun(name, args, options) {
  if (options.openclaw) {
    const infoResp2 = await sendCommand({
      method: "site_info",
      siteName: name
    });
    const site = infoResp2.result ? infoResp2.result : null;
    if (!site) {
      if (options.json) {
        exitJsonError(`site "${name}" not found`, { action: "bb-browser site list" });
      }
      console.error(`[error] site: "${name}" not found.`);
      console.error("  Try: bb-browser site list");
      process.exit(1);
    }
    const argNames = Object.keys(site.args || {});
    const argMap2 = {};
    const positionalArgs = [];
    for (let i = 0; i < args.length; i++) {
      if (args[i].startsWith("--")) {
        const flagName = args[i].slice(2);
        if (flagName in (site.args || {}) && args[i + 1]) {
          argMap2[flagName] = args[i + 1];
          i++;
        }
      } else {
        positionalArgs.push(args[i]);
      }
    }
    let posIdx = 0;
    for (const argName of argNames) {
      if (!argMap2[argName] && posIdx < positionalArgs.length) {
        argMap2[argName] = positionalArgs[posIdx++];
      }
    }
    const siteJsPath = findLocalSiteFile(name);
    if (!siteJsPath) {
      exitJsonError(`Cannot find JS file for "${name}" locally (openclaw requires local files)`);
    }
    const jsContent = readFileSync(siteJsPath, "utf-8");
    const jsBody = jsContent.replace(/\/\*\s*@meta[\s\S]*?\*\//, "").trim();
    const argsJson = JSON.stringify(argMap2);
    const { ocGetTabs, ocFindTabByDomain, ocOpenTab, ocEvaluate } = await import("./openclaw-bridge-U2GHGPNP.js");
    let targetId;
    if (site.domain) {
      const tabs = ocGetTabs();
      const existing = ocFindTabByDomain(tabs, site.domain);
      if (existing) {
        targetId = existing.targetId;
      } else {
        targetId = ocOpenTab(`https://${site.domain}`);
        await new Promise((resolve2) => setTimeout(resolve2, 3e3));
      }
    } else {
      const tabs = ocGetTabs();
      if (tabs.length === 0) {
        throw new Error("No tabs open in OpenClaw browser");
      }
      targetId = tabs[0].targetId;
    }
    const wrappedFn = `async () => { const __fn = ${jsBody}; return await __fn(${argsJson}); }`;
    const parsed2 = ocEvaluate(targetId, wrappedFn);
    if (typeof parsed2 === "object" && parsed2 !== null && "error" in parsed2) {
      const errObj = parsed2;
      const checkText = `${errObj.error} ${errObj.hint || ""}`;
      const isAuthError = /401|403|unauthorized|forbidden|not.?logged|login.?required|sign.?in|auth/i.test(checkText);
      const loginHint = isAuthError && site.domain ? `Please log in to https://${site.domain} in your OpenClaw browser first, then retry.` : void 0;
      const hint = loginHint || errObj.hint;
      const reportHint = `If this is an adapter bug, report via: gh issue create --repo epiral/bb-sites --title "[${name}] <description>" OR: bb-browser site github/issue-create epiral/bb-sites --title "[${name}] <description>"`;
      if (options.json) {
        console.log(JSON.stringify({ error: { message: errObj.error }, hint, reportHint }));
      } else {
        console.error(`[error] site ${name}: ${errObj.error}`);
        if (hint) console.error(`  Hint: ${hint}`);
        console.error(`  Report: gh issue create --repo epiral/bb-sites --title "[${name}] ..."`);
        console.error(`     or: bb-browser site github/issue-create epiral/bb-sites --title "[${name}] ..."`);
      }
      process.exit(1);
    }
    if (options.jq) {
      const { applyJq: applyJq2 } = await import("./jq-BXSYE2V2.js");
      const expr = options.jq.replace(/^\.data\./, ".");
      const results = applyJq2(parsed2, expr);
      for (const r of results) {
        console.log(typeof r === "string" ? r : JSON.stringify(r));
      }
    } else if (options.json) {
      console.log(JSON.stringify({ result: parsed2 }));
    } else {
      console.log(JSON.stringify(parsed2, null, 2));
    }
    return;
  }
  const infoResp = await sendCommand({
    method: "site_info",
    siteName: name
  });
  const argMap = {};
  if (infoResp.result) {
    const site = infoResp.result;
    const argNames = Object.keys(site.args || {});
    const positionalArgs = [];
    for (let i = 0; i < args.length; i++) {
      if (args[i].startsWith("--")) {
        const flagName = args[i].slice(2);
        if (flagName in (site.args || {}) && args[i + 1]) {
          argMap[flagName] = args[i + 1];
          i++;
        }
      } else {
        positionalArgs.push(args[i]);
      }
    }
    let posIdx = 0;
    for (const argName of argNames) {
      if (!argMap[argName] && posIdx < positionalArgs.length) {
        argMap[argName] = positionalArgs[posIdx++];
      }
    }
  } else {
    for (let i = 0; i < args.length; i++) {
      if (args[i].startsWith("--") && args[i + 1]) {
        argMap[args[i].slice(2)] = args[i + 1];
        i++;
      }
    }
  }
  const resp = await sendCommand({
    method: "site_run",
    siteName: name,
    siteArgs: argMap,
    ...options.tabId !== void 0 ? { tabId: options.tabId } : {}
  });
  if (resp.error) {
    if (options.json) {
      console.log(JSON.stringify({ error: { message: resp.error.message || "site_run failed" } }));
    } else {
      console.error(`[error] site ${name}: ${resp.error.message || "site_run failed"}`);
    }
    process.exit(1);
  }
  const result = resp.result?.result;
  if (result === void 0 || result === null) {
    if (options.json) {
      console.log(JSON.stringify({ result: null }));
    } else {
      console.log("(no output)");
    }
    return;
  }
  let parsed;
  try {
    parsed = typeof result === "string" ? JSON.parse(result) : result;
  } catch {
    parsed = result;
  }
  if (typeof parsed === "object" && parsed !== null && "error" in parsed) {
    const errObj = parsed;
    const checkText = `${errObj.error} ${errObj.hint || ""}`;
    const isAuthError = /401|403|unauthorized|forbidden|not.?logged|login.?required|sign.?in|auth/i.test(checkText);
    const domain = infoResp.result ? infoResp.result?.domain : void 0;
    const loginHint = isAuthError && domain ? `Please log in to https://${domain} in your browser first, then retry.` : void 0;
    const hint = loginHint || errObj.hint;
    const reportHint = `If this is an adapter bug, report via: gh issue create --repo epiral/bb-sites --title "[${name}] <description>" OR: bb-browser site github/issue-create epiral/bb-sites --title "[${name}] <description>"`;
    if (options.json) {
      console.log(JSON.stringify({ error: { message: errObj.error }, hint, reportHint }));
    } else {
      console.error(`[error] site ${name}: ${errObj.error}`);
      if (hint) console.error(`  Hint: ${hint}`);
      console.error(`  Report: gh issue create --repo epiral/bb-sites --title "[${name}] ..."`);
      console.error(`     or: bb-browser site github/issue-create epiral/bb-sites --title "[${name}] ..."`);
    }
    process.exit(1);
  }
  if (options.jq) {
    const { applyJq: applyJq2 } = await import("./jq-BXSYE2V2.js");
    const expr = options.jq.replace(/^\.data\./, ".");
    const results = applyJq2(parsed, expr);
    for (const r of results) {
      console.log(typeof r === "string" ? r : JSON.stringify(r));
    }
  } else if (options.json) {
    console.log(JSON.stringify({ result: parsed }));
  } else {
    console.log(JSON.stringify(parsed, null, 2));
  }
}
async function siteCommand(args, options = {}) {
  const subCommand = args[0];
  if (!subCommand || subCommand === "--help" || subCommand === "-h") {
    console.log(`bb-browser site - \u7F51\u7AD9 CLI \u5316\uFF08\u7BA1\u7406\u548C\u8FD0\u884C site adapter\uFF09

\u7528\u6CD5:
  bb-browser site list                      \u5217\u51FA\u6240\u6709\u53EF\u7528 adapter
  bb-browser site info <name>               \u67E5\u770B adapter \u5143\u4FE1\u606F
  bb-browser site recommend                 \u57FA\u4E8E\u5386\u53F2\u8BB0\u5F55\u63A8\u8350 adapter
  bb-browser site search <query>            \u641C\u7D22 adapter
  bb-browser site <name> [args...]          \u8FD0\u884C adapter\uFF08\u7B80\u5199\uFF09
  bb-browser site run <name> [args...]      \u8FD0\u884C adapter
  bb-browser site update                    \u66F4\u65B0\u793E\u533A adapter \u5E93 (git clone/pull)

\u76EE\u5F55:
  ${LOCAL_SITES_DIR}      \u79C1\u6709 adapter\uFF08\u4F18\u5148\uFF09
  ${COMMUNITY_SITES_DIR}   \u793E\u533A adapter

\u793A\u4F8B:
  bb-browser site update
  bb-browser site list
  bb-browser site reddit/thread https://www.reddit.com/r/LocalLLaMA/comments/...
  bb-browser site twitter/user yan5xu
  bb-browser site search reddit

\u521B\u5EFA\u65B0 adapter: bb-browser guide
\u62A5\u544A\u95EE\u9898: gh issue create --repo epiral/bb-sites --title "[adapter-name] \u63CF\u8FF0"
\u8D21\u732E\u793E\u533A: https://github.com/epiral/bb-sites`);
    return;
  }
  switch (subCommand) {
    case "list":
      await siteList(options);
      break;
    case "search":
      if (!args[1]) {
        console.error("[error] site search: <query> is required.");
        console.error("  Usage: bb-browser site search <query>");
        process.exit(1);
      }
      await siteSearch(args[1], options);
      break;
    case "info":
      if (!args[1]) {
        console.error("[error] site info: <name> is required.");
        console.error("  Usage: bb-browser site info <name>");
        process.exit(1);
      }
      await siteInfo(args[1], options);
      break;
    case "recommend":
      await siteRecommend(options);
      break;
    case "update":
      siteUpdate(options);
      break;
    case "run":
      if (!args[1]) {
        console.error("[error] site run: <name> is required.");
        console.error("  Usage: bb-browser site run <name> [args...]");
        console.error("  Try: bb-browser site list");
        process.exit(1);
      }
      await siteRun(args[1], args.slice(2), options);
      break;
    default:
      if (subCommand.includes("/")) {
        await siteRun(subCommand, args.slice(1), options);
      } else {
        console.error(`[error] site: unknown subcommand "${subCommand}".`);
        console.error("  Available: list, info, recommend, search, run, update");
        console.error("  Try: bb-browser site --help");
        process.exit(1);
      }
      break;
  }
  if (process.platform !== "win32") silentUpdate();
}
function silentUpdate() {
  const gitDir = join2(COMMUNITY_SITES_DIR, ".git");
  if (!existsSync4(gitDir)) return;
  import("child_process").then(({ spawn: spawn3 }) => {
    const child = spawn3("git", ["pull", "--ff-only"], {
      cwd: COMMUNITY_SITES_DIR,
      stdio: "ignore",
      detached: true
    });
    child.unref();
  }).catch(() => {
  });
}

// packages/cli/src/commands/open.ts
async function openCommand(url, options = {}) {
  if (!url) {
    throw new Error("\u7F3A\u5C11 URL \u53C2\u6570");
  }
  await ensureDaemonRunning();
  let normalizedUrl = url;
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    normalizedUrl = "https://" + url;
  }
  const request = {
    method: "open",
    url: normalizedUrl
  };
  if (options.tab !== void 0) {
    if (options.tab === "current") {
      request.tabId = "current";
    } else {
      const tabId = parseInt(options.tab, 10);
      if (isNaN(tabId)) {
        throw new Error(`\u65E0\u6548\u7684 tabId: ${options.tab}`);
      }
      request.tabId = tabId;
    }
  }
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const tab = response.result?.tab;
      if (tab) {
        console.log(`tab: ${tab}`);
      }
      console.log(`url: ${response.result?.url ?? normalizedUrl}`);
      if (response.result?.title) {
        console.log(`title: ${response.result.title}`);
      }
      const siteHint = getSiteHintForDomain(normalizedUrl);
      if (siteHint) {
        console.log(`
hint: ${siteHint}`);
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/goto.ts
async function gotoCommand(url, options = {}) {
  if (!url) {
    throw new Error("Missing URL parameter");
  }
  await ensureDaemonRunning();
  const request = {
    method: "goto",
    url,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log(`tab: ${response.result.tab}`);
      console.log(`url: ${response.result.url}`);
    } else {
      console.error(`Error: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/snapshot.ts
async function snapshotCommand(options = {}) {
  await ensureDaemonRunning();
  const request = {
    method: "snap",
    interactive: options.interactive,
    compact: options.compact,
    maxDepth: options.maxDepth,
    selector: options.selector,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log(`\u6807\u9898: ${response.result?.title ?? "(\u65E0\u6807\u9898)"}`);
      console.log(`URL: ${response.result?.url ?? "(\u672A\u77E5)"}`);
      if (response.result?.snapshotData?.snapshot) {
        console.log("");
        console.log(response.result.snapshotData.snapshot);
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/click.ts
function parseRef(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function clickCommand(ref, options = {}) {
  if (!ref) {
    throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  }
  await ensureDaemonRunning();
  const request = {
    method: "click",
    ref: parseRef(ref),
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const role = response.result?.role ?? "element";
      const name = response.result?.name;
      if (name) {
        console.log(`\u5DF2\u70B9\u51FB: ${role} "${name}"`);
      } else {
        console.log(`\u5DF2\u70B9\u51FB: ${role}`);
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/hover.ts
function parseRef2(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function hoverCommand(ref, options = {}) {
  if (!ref) {
    throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  }
  await ensureDaemonRunning();
  const request = {
    method: "hover",
    ref: parseRef2(ref),
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const role = response.result?.role ?? "element";
      const name = response.result?.name;
      if (name) {
        console.log(`\u5DF2\u60AC\u505C: ${role} "${name}"`);
      } else {
        console.log(`\u5DF2\u60AC\u505C: ${role}`);
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/fill.ts
function parseRef3(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function fillCommand(ref, text, options = {}) {
  if (!ref) throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  if (text === void 0 || text === null) throw new Error("\u7F3A\u5C11 text \u53C2\u6570");
  await ensureDaemonRunning();
  const request = {
    method: "fill",
    ref: parseRef3(ref),
    text,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log(`\u5DF2\u586B\u5145\u5185\u5BB9: "${text}"`);
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/type.ts
function parseRef4(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function typeCommand(ref, text, options = {}) {
  if (!ref) throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  if (text === void 0 || text === null) throw new Error("\u7F3A\u5C11 text \u53C2\u6570");
  await ensureDaemonRunning();
  const request = {
    method: "type",
    ref: parseRef4(ref),
    text,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log(`\u5DF2\u8F93\u5165\u5185\u5BB9: "${text}"`);
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/close.ts
async function closeCommand(options = {}) {
  await ensureDaemonRunning();
  const request = {
    method: "close",
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const title = response.result?.title ?? "";
      if (title) {
        console.log(`\u5DF2\u5173\u95ED: "${title}"`);
      } else {
        console.log("\u5DF2\u5173\u95ED\u6807\u7B7E\u9875");
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/get.ts
function parseRef5(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function getCommand(attribute, ref, options = {}) {
  if (attribute === "text" && !ref) {
    throw new Error("get text \u9700\u8981 ref \u53C2\u6570\uFF0C\u5982: get text @5");
  }
  await ensureDaemonRunning();
  const request = {
    method: "get",
    attribute,
    ref: ref ? parseRef5(ref) : void 0,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const value = response.result?.value ?? "";
      console.log(value);
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/screenshot.ts
import fs from "fs";
import path2 from "path";
import os2 from "os";
function getDefaultPath() {
  const timestamp = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-");
  const filename = `bb-screenshot-${timestamp}.png`;
  return path2.join(os2.tmpdir(), filename);
}
function saveBase64Image(dataUrl, filePath) {
  const base64Data = dataUrl.replace(/^data:image\/png;base64,/, "");
  const buffer = Buffer.from(base64Data, "base64");
  const dir = path2.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  fs.writeFileSync(filePath, buffer);
}
async function screenshotCommand(outputPath, options = {}) {
  await ensureDaemonRunning();
  const filePath = outputPath ? path2.resolve(outputPath) : getDefaultPath();
  const request = {
    method: "screenshot",
    tabId: options.tabId,
    includeBase64: true
  };
  const response = await sendCommand(request);
  if (response.result && (response.result?.dataUrl || response.result?.path)) {
    const dataUrl = response.result.dataUrl;
    if (dataUrl) {
      saveBase64Image(dataUrl, filePath);
    }
    if (options.json) {
      console.log(JSON.stringify({
        path: filePath,
        pinixPath: response.result.path
      }, null, 2));
    } else {
      console.log(`\u622A\u56FE\u5DF2\u4FDD\u5B58: ${filePath}`);
    }
  } else {
    if (options.json) {
      console.log(JSON.stringify(response, null, 2));
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
    }
    process.exit(1);
  }
}

// packages/cli/src/commands/press.ts
function parseKey(keyString) {
  const parts = keyString.split("+");
  const modifierNames = ["Control", "Alt", "Shift", "Meta"];
  const modifiers = [];
  let key = "";
  for (const part of parts) {
    if (modifierNames.includes(part)) {
      modifiers.push(part);
    } else {
      key = part;
    }
  }
  return { key, modifiers };
}
async function pressCommand(keyString, options = {}) {
  if (!keyString) throw new Error("\u7F3A\u5C11 key \u53C2\u6570");
  await ensureDaemonRunning();
  const { key, modifiers } = parseKey(keyString);
  if (!key) throw new Error("\u65E0\u6548\u7684\u6309\u952E\u683C\u5F0F");
  const request = {
    method: "press",
    key,
    modifiers,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const displayKey = modifiers.length > 0 ? `${modifiers.join("+")}+${key}` : key;
      console.log(`\u5DF2\u6309\u4E0B: ${displayKey}`);
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/scroll.ts
var VALID_DIRECTIONS = ["up", "down", "left", "right"];
var DEFAULT_PIXELS = 300;
async function scrollCommand(direction, pixels, options = {}) {
  if (!direction) throw new Error("\u7F3A\u5C11 direction \u53C2\u6570");
  if (!VALID_DIRECTIONS.includes(direction)) {
    throw new Error(`\u65E0\u6548\u7684\u6EDA\u52A8\u65B9\u5411: ${direction}\uFF0C\u652F\u6301: ${VALID_DIRECTIONS.join(", ")}`);
  }
  let pixelValue = DEFAULT_PIXELS;
  if (pixels !== void 0) {
    pixelValue = parseInt(pixels, 10);
    if (isNaN(pixelValue) || pixelValue <= 0) {
      throw new Error(`\u65E0\u6548\u7684\u50CF\u7D20\u503C: ${pixels}`);
    }
  }
  await ensureDaemonRunning();
  const request = {
    method: "scroll",
    direction,
    pixels: pixelValue,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log(`\u5DF2\u6EDA\u52A8: ${direction} ${pixelValue}px`);
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/nav.ts
async function backCommand(options = {}) {
  await ensureDaemonRunning();
  const request = {
    method: "back",
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const url = response.result?.url ?? "";
      if (url) {
        console.log(`\u540E\u9000\u81F3: ${url}`);
      } else {
        console.log("\u5DF2\u540E\u9000");
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}
async function forwardCommand(options = {}) {
  await ensureDaemonRunning();
  const request = {
    method: "forward",
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const url = response.result?.url ?? "";
      if (url) {
        console.log(`\u524D\u8FDB\u81F3: ${url}`);
      } else {
        console.log("\u5DF2\u524D\u8FDB");
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}
async function reloadCommand(options = {}) {
  await ensureDaemonRunning();
  const request = {
    method: "reload",
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const title = response.result?.title ?? "";
      if (title) {
        console.log(`\u5DF2\u5237\u65B0: "${title}"`);
      } else {
        console.log("\u5DF2\u5237\u65B0\u9875\u9762");
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/check.ts
function parseRef6(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function checkCommand(ref, options = {}) {
  if (!ref) throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  await ensureDaemonRunning();
  const request = { method: "check", ref: parseRef6(ref), tabId: options.tabId };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log("\u5DF2\u52FE\u9009");
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}
async function uncheckCommand(ref, options = {}) {
  if (!ref) throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  await ensureDaemonRunning();
  const request = { method: "uncheck", ref: parseRef6(ref), tabId: options.tabId };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log("\u5DF2\u53D6\u6D88\u52FE\u9009");
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/select.ts
function parseRef7(ref) {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}
async function selectCommand(ref, value, options = {}) {
  if (!ref) throw new Error("\u7F3A\u5C11 ref \u53C2\u6570");
  if (value === void 0 || value === null) throw new Error("\u7F3A\u5C11 value \u53C2\u6570");
  await ensureDaemonRunning();
  const request = {
    method: "select",
    ref: parseRef7(ref),
    value,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log(`\u5DF2\u9009\u62E9: "${value}"`);
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/eval.ts
async function evalCommand(script, options = {}) {
  if (!script) throw new Error("\u7F3A\u5C11 script \u53C2\u6570");
  await ensureDaemonRunning();
  let args;
  if (options.args) {
    try {
      args = JSON.parse(options.args);
    } catch {
      throw new Error(`--args must be valid JSON: ${options.args}`);
    }
  }
  const request = {
    method: "eval",
    script,
    ...options.tabId !== void 0 ? { tabId: options.tabId } : {},
    ...options.domain ? { domain: options.domain } : {},
    ...args !== void 0 ? { args } : {}
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const result = response.result?.result;
      if (result !== void 0) {
        if (typeof result === "object" && result !== null) {
          console.log(JSON.stringify(result, null, 2));
        } else {
          console.log(result);
        }
      } else {
        console.log("undefined");
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/tab.ts
function parseTabSubcommand(args) {
  if (args.length === 0 || args[0] === "list") {
    return { action: "tab_list" };
  }
  if (args[0] === "new") {
    return { action: "tab_new", url: args[1] };
  }
  throw new Error(`\u672A\u77E5\u7684 tab \u5B50\u547D\u4EE4: ${args[0]}\u3002\u652F\u6301: list, new`);
}
function formatTabList(tabs, activeIndex) {
  const lines = [];
  lines.push(`\u6807\u7B7E\u9875\u5217\u8868\uFF08\u5171 ${tabs.length} \u4E2A\uFF0C\u5F53\u524D #${activeIndex}\uFF09\uFF1A`);
  for (const tab of tabs) {
    const prefix = tab.active ? "*" : " ";
    const title = tab.title || "(\u65E0\u6807\u9898)";
    const shortId = tab.tab || "";
    lines.push(`${prefix} [${shortId}] ${tab.url} - ${title}`);
  }
  return lines.join("\n");
}
async function tabCommand(args, options = {}) {
  await ensureDaemonRunning();
  const parsed = parseTabSubcommand(args);
  const request = {
    method: parsed.action,
    url: parsed.url
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      switch (parsed.action) {
        case "tab_list": {
          const tabs = response.result?.tabs ?? [];
          const activeIndex = response.result?.activeIndex ?? 0;
          console.log(formatTabList(tabs, activeIndex));
          break;
        }
        case "tab_new": {
          const url = response.result?.url ?? "about:blank";
          console.log(`\u5DF2\u521B\u5EFA\u65B0\u6807\u7B7E\u9875: ${url}`);
          break;
        }
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/frame.ts
async function frameCommand(selector, options = {}) {
  if (!selector) throw new Error("\u7F3A\u5C11 selector \u53C2\u6570");
  await ensureDaemonRunning();
  const request = { method: "frame", selector, tabId: options.tabId };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const frameInfo = response.result?.frameInfo;
      if (frameInfo?.url) {
        console.log(`\u5DF2\u5207\u6362\u5230 frame: ${selector} (${frameInfo.url})`);
      } else {
        console.log(`\u5DF2\u5207\u6362\u5230 frame: ${selector}`);
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}
async function frameMainCommand(options = {}) {
  await ensureDaemonRunning();
  const request = { method: "frame_main", tabId: options.tabId };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      console.log("\u5DF2\u8FD4\u56DE\u4E3B frame");
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/dialog.ts
async function dialogCommand(subCommand, promptText, options = {}) {
  if (!subCommand || !["accept", "dismiss"].includes(subCommand)) {
    throw new Error("\u8BF7\u4F7F\u7528 'dialog accept [text]' \u6216 'dialog dismiss'");
  }
  await ensureDaemonRunning();
  const request = {
    method: "dialog",
    dialogResponse: subCommand,
    promptText: subCommand === "accept" ? promptText : void 0,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response, null, 2));
  } else {
    if (response.result) {
      const dialogInfo = response.result?.dialogInfo;
      if (dialogInfo) {
        const action = subCommand === "accept" ? "\u5DF2\u63A5\u53D7" : "\u5DF2\u62D2\u7EDD";
        console.log(`${action}\u5BF9\u8BDD\u6846\uFF08${dialogInfo.type}\uFF09: "${dialogInfo.message}"`);
      } else {
        console.log("\u5BF9\u8BDD\u6846\u5DF2\u5904\u7406");
      }
    } else {
      console.error(`\u9519\u8BEF: ${response.error?.message}`);
      process.exit(1);
    }
  }
}

// packages/cli/src/commands/network.ts
async function networkCommand(subCommand, urlOrFilter, options = {}) {
  let since;
  if (subCommand === "requests" && options.since) {
    const num = parseInt(options.since, 10);
    since = !isNaN(num) && String(num) === options.since ? num : options.since;
  }
  const request = {
    method: "network",
    action: subCommand,
    url: subCommand === "route" || subCommand === "unroute" ? urlOrFilter : void 0,
    filter: subCommand === "requests" ? urlOrFilter : void 0,
    routeOptions: subCommand === "route" ? {
      abort: options.abort,
      body: options.body
    } : void 0,
    withBody: subCommand === "requests" ? options.withBody : void 0,
    excludeStatic: subCommand === "requests" ? options.excludeStatic : void 0,
    since,
    httpMethod: subCommand === "requests" ? options.method : void 0,
    status: subCommand === "requests" ? options.status : void 0,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response));
    return;
  }
  if (response.error) {
    throw new Error(response.error.message || "Network command failed");
  }
  const data = response.result;
  switch (subCommand) {
    case "requests": {
      const requests = data?.networkRequests || [];
      if (requests.length === 0) {
        console.log("\u6CA1\u6709\u7F51\u7EDC\u8BF7\u6C42\u8BB0\u5F55");
        console.log("\u63D0\u793A: \u4F7F\u7528 network requests \u4F1A\u81EA\u52A8\u5F00\u59CB\u76D1\u63A7");
      } else {
        console.log(`\u7F51\u7EDC\u8BF7\u6C42 (${requests.length} \u6761):
`);
        for (const req of requests) {
          const status = req.failed ? `FAILED (${req.failureReason})` : req.status ? `${req.status} ${req.statusText || ""}` : "pending";
          console.log(`${req.method} ${req.url}`);
          console.log(`  \u7C7B\u578B: ${req.type}, \u72B6\u6001: ${status}`);
          if (options.withBody) {
            const requestHeaderCount = req.requestHeaders ? Object.keys(req.requestHeaders).length : 0;
            const responseHeaderCount = req.responseHeaders ? Object.keys(req.responseHeaders).length : 0;
            console.log(`  \u8BF7\u6C42\u5934: ${requestHeaderCount}, \u54CD\u5E94\u5934: ${responseHeaderCount}`);
            if (req.requestBody !== void 0) {
              const preview = req.requestBody.length > 200 ? `${req.requestBody.slice(0, 200)}...` : req.requestBody;
              console.log(`  \u8BF7\u6C42\u4F53: ${preview}`);
            }
            if (req.responseBody !== void 0) {
              const preview = req.responseBody.length > 200 ? `${req.responseBody.slice(0, 200)}...` : req.responseBody;
              console.log(`  \u54CD\u5E94\u4F53: ${preview}`);
            }
            if (req.bodyError) {
              console.log(`  Body\u9519\u8BEF: ${req.bodyError}`);
            }
          }
          console.log("");
        }
      }
      break;
    }
    case "route": {
      console.log(`\u5DF2\u6DFB\u52A0\u62E6\u622A\u89C4\u5219: ${urlOrFilter}`);
      if (options.abort) {
        console.log("  \u884C\u4E3A: \u963B\u6B62\u8BF7\u6C42");
      } else if (options.body) {
        console.log("  \u884C\u4E3A: \u8FD4\u56DE mock \u6570\u636E");
      } else {
        console.log("  \u884C\u4E3A: \u7EE7\u7EED\u8BF7\u6C42");
      }
      console.log(`\u5F53\u524D\u89C4\u5219\u6570: ${data?.routeCount || 0}`);
      break;
    }
    case "unroute": {
      if (urlOrFilter) {
        console.log(`\u5DF2\u79FB\u9664\u62E6\u622A\u89C4\u5219: ${urlOrFilter}`);
      } else {
        console.log("\u5DF2\u79FB\u9664\u6240\u6709\u62E6\u622A\u89C4\u5219");
      }
      console.log(`\u5269\u4F59\u89C4\u5219\u6570: ${data?.routeCount || 0}`);
      break;
    }
    case "clear": {
      console.log("\u5DF2\u6E05\u7A7A\u7F51\u7EDC\u8BF7\u6C42\u8BB0\u5F55");
      break;
    }
    default:
      throw new Error(`\u672A\u77E5\u7684 network \u5B50\u547D\u4EE4: ${subCommand}`);
  }
}

// packages/cli/src/commands/console.ts
async function consoleCommand(options = {}) {
  let since;
  if (options.since) {
    const num = parseInt(options.since, 10);
    since = !isNaN(num) && String(num) === options.since ? num : options.since;
  }
  const request = {
    method: "console",
    action: options.clear ? "clear" : "get",
    tabId: options.tabId,
    since
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response));
    return;
  }
  if (response.error) {
    throw new Error(response.error.message || "Console command failed");
  }
  if (options.clear) {
    console.log("\u5DF2\u6E05\u7A7A\u63A7\u5236\u53F0\u6D88\u606F");
    return;
  }
  const messages = response.result?.consoleMessages || [];
  if (messages.length === 0) {
    console.log("\u6CA1\u6709\u63A7\u5236\u53F0\u6D88\u606F");
    console.log("\u63D0\u793A: console \u547D\u4EE4\u4F1A\u81EA\u52A8\u5F00\u59CB\u76D1\u63A7");
    return;
  }
  console.log(`\u63A7\u5236\u53F0\u6D88\u606F (${messages.length} \u6761):
`);
  const typeColors = {
    log: "",
    info: "[INFO]",
    warn: "[WARN]",
    error: "[ERROR]",
    debug: "[DEBUG]"
  };
  for (const msg of messages) {
    const prefix = typeColors[msg.type] || `[${msg.type.toUpperCase()}]`;
    const location = msg.url ? ` (${msg.url}${msg.lineNumber ? `:${msg.lineNumber}` : ""})` : "";
    if (prefix) {
      console.log(`${prefix} ${msg.text}${location}`);
    } else {
      console.log(`${msg.text}${location}`);
    }
  }
}

// packages/cli/src/commands/errors.ts
async function errorsCommand(options = {}) {
  let since;
  if (options.since) {
    const num = parseInt(options.since, 10);
    since = !isNaN(num) && String(num) === options.since ? num : options.since;
  }
  const request = {
    method: "errors",
    action: options.clear ? "clear" : "get",
    tabId: options.tabId,
    since
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response));
    return;
  }
  if (response.error) {
    throw new Error(response.error.message || "Errors command failed");
  }
  if (options.clear) {
    console.log("\u5DF2\u6E05\u7A7A JS \u9519\u8BEF\u8BB0\u5F55");
    return;
  }
  const errors = response.result?.jsErrors || [];
  if (errors.length === 0) {
    console.log("\u6CA1\u6709 JS \u9519\u8BEF");
    console.log("\u63D0\u793A: errors \u547D\u4EE4\u4F1A\u81EA\u52A8\u5F00\u59CB\u76D1\u63A7");
    return;
  }
  console.log(`JS \u9519\u8BEF (${errors.length} \u6761):
`);
  for (const err of errors) {
    console.log(`[ERROR] ${err.message}`);
    if (err.url) {
      console.log(`  \u4F4D\u7F6E: ${err.url}:${err.lineNumber || 0}:${err.columnNumber || 0}`);
    }
    if (err.stackTrace) {
      console.log(`  \u5806\u6808:`);
      console.log(err.stackTrace.split("\n").map((line) => `    ${line}`).join("\n"));
    }
    console.log("");
  }
}

// packages/cli/src/commands/trace.ts
async function traceCommand(subCommand, options = {}) {
  const request = {
    method: "trace",
    action: subCommand,
    tabId: options.tabId
  };
  if (subCommand === "events") {
    if (options.since !== void 0) request.since = Number(options.since);
    if (options.type) request.traceType = options.type;
    if (options.filter) request.filter = options.filter;
    if (options.limit) request.limit = Number(options.limit);
    if (options.excludeStatic) request.excludeStatic = true;
  }
  if (subCommand === "body") {
    request.requestId = options.requestId;
  }
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response));
    return;
  }
  if (response.error) {
    throw new Error(response.error.message || "Trace command failed");
  }
  const data = response.result;
  switch (subCommand) {
    case "start": {
      const status = data?.traceStatus;
      console.log("Trace started");
      if (status?.tracedTabs?.length) {
        console.log(`Tracing tabs: ${status.tracedTabs.join(", ")}`);
      }
      console.log("\nOperate the browser, then run 'bb-browser trace events' to see the timeline.");
      break;
    }
    case "stop": {
      const status = data?.traceStatus;
      console.log(`Trace stopped (${status?.eventCount ?? 0} events recorded)`);
      console.log("Data preserved \u2014 use 'trace events' to query, 'trace start' to begin a new session.");
      break;
    }
    case "status": {
      const status = data?.traceStatus;
      if (status?.recording) {
        console.log(`Recording (${status.eventCount} events)`);
        if (status.tracedTabs?.length) {
          console.log(`Tabs: ${status.tracedTabs.join(", ")}`);
        }
      } else if (status?.eventCount) {
        console.log(`Stopped (${status.eventCount} events in buffer)`);
      } else {
        console.log("No active trace session");
      }
      break;
    }
    case "events": {
      const events = data?.traceEvents || [];
      const cursor = data?.cursor;
      if (events.length === 0) {
        console.log("No events");
        break;
      }
      for (const e of events) {
        const tabStr = `[${e.tab}]`;
        switch (e.type) {
          case "action": {
            const src = e.source === "human" ? " (human)" : "";
            const ref = e.ref !== void 0 ? ` ref=${e.ref}` : "";
            const val = e.value ? ` "${e.value}"` : "";
            const key = e.key ? ` ${e.key}` : "";
            const info = e.text ? ` "${e.text}"` : "";
            const role = e.role ? ` [${e.role}]` : "";
            console.log(`  ${e.seq}  ${tabStr}  action${src}    ${e.action}${ref}${role}${info}${val}${key}`);
            break;
          }
          case "request": {
            const trigger = e.triggerSeq ? `  trigger:${e.triggerSeq}` : "";
            const body = e.body ? ` (body: ${e.body.length}B)` : "";
            console.log(`  ${e.seq}  ${tabStr}  request      ${e.method} ${e.url}${body}${trigger}`);
            break;
          }
          case "response": {
            const size = e.bodySize ? ` ${e.bodySize}B` : "";
            const mime = e.mimeType ? ` ${e.mimeType}` : "";
            console.log(`  ${e.seq}  ${tabStr}  response     ${e.requestId} \u2192 ${e.status}${mime}${size}`);
            break;
          }
          case "navigation": {
            const from = e.from ? ` (from: ${e.from})` : "";
            console.log(`  ${e.seq}  ${tabStr}  navigation   ${e.url}${from}`);
            break;
          }
        }
      }
      console.log(`
${events.length} events, cursor: ${cursor}`);
      break;
    }
    case "body": {
      const body = data?.traceBody;
      if (!body) {
        console.error("No body data returned");
        break;
      }
      if (body.requestBody) {
        console.log("=== Request Body ===");
        console.log(body.requestBody);
        console.log("");
      }
      if (body.body) {
        if (body.requestBody) {
          console.log("=== Response Body ===");
        }
        if (body.base64Encoded) {
          console.log(`[base64 encoded, ${body.body.length} chars]`);
        } else {
          console.log(body.body);
        }
      }
      break;
    }
  }
}

// packages/cli/src/commands/cookies.ts
async function cookiesCommand(options = {}) {
  const request = {
    method: "cookies",
    tabId: options.tabId,
    filter: options.filter
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response));
    return;
  }
  if (response.error) {
    throw new Error(response.error.message || "Cookies command failed");
  }
  const data = response.result;
  const cookies = data?.cookies || [];
  if (cookies.length === 0) {
    console.log("No cookies found");
    return;
  }
  console.log(`Cookies (${cookies.length}):
`);
  for (const c of cookies) {
    const flags = [];
    if (c.httpOnly) flags.push("httpOnly");
    if (c.secure) flags.push("secure");
    const expiresStr = c.expires > 0 ? `expires=${new Date(c.expires * 1e3).toISOString().split("T")[0]}` : "session";
    const flagStr = flags.length > 0 ? `  ${flags.join("  ")}` : "";
    console.log(`name=${c.name}  domain=${c.domain}  path=${c.path}${flagStr}  ${expiresStr}`);
  }
}

// packages/cli/src/commands/source.ts
async function sourceCommand(subCommand, pattern, options = {}) {
  const request = {
    method: "source",
    action: subCommand,
    pattern,
    tabId: options.tabId
  };
  const response = await sendCommand(request);
  if (options.json) {
    console.log(JSON.stringify(response));
    return;
  }
  if (response.error) {
    throw new Error(response.error.message || "Source command failed");
  }
  const data = response.result;
  const results = data?.sourceResults || [];
  if (results.length === 0) {
    console.log(`No matches found for "${pattern}"`);
    return;
  }
  let totalMatches = 0;
  for (const result of results) {
    totalMatches += result.matches.length;
    console.log(`=== ${result.url} (${result.matches.length} matches) ===`);
    for (const match of result.matches) {
      console.log(`  ${match}`);
    }
    console.log("");
  }
  console.log(`${totalMatches} matches in ${results.length} files`);
}

// packages/cli/src/commands/daemon.ts
async function statusCommand(options = {}) {
  const status = await getDaemonStatus();
  if (!status) {
    if (options.json) {
      console.log(JSON.stringify({ running: false }));
    } else {
      console.log("Daemon not running");
      console.log("\n\u{1F4A1} \u542F\u52A8: bb-browser daemon start");
    }
    return;
  }
  if (options.json) {
    console.log(JSON.stringify(status, null, 2));
    return;
  }
  console.log(`Daemon running: ${status.running ? "yes" : "no"}`);
  console.log(`CDP connected:  ${status.cdpConnected ? "yes" : "no"}`);
  console.log(`Uptime:         ${formatUptime(status.uptime)}`);
  console.log(`Global seq:     ${status.currentSeq ?? "N/A"}`);
  const tabs = status.tabs;
  if (tabs && tabs.length > 0) {
    console.log(`
Tabs (${tabs.length}):`);
    for (const tab of tabs) {
      const active = tab.targetId === status.currentTargetId ? " *" : "";
      console.log(
        `  ${tab.shortId}${active}  net:${tab.networkRequests} console:${tab.consoleMessages} err:${tab.jsErrors} seq:${tab.lastActionSeq}`
      );
    }
  } else {
    console.log("\nNo tabs");
  }
  if (status.cdpConnected === false) {
    console.log("\n\u26A0\uFE0F Chrome \u672A\u8FDE\u63A5\u3002\u8FD0\u884C bb-browser daemon stop && bb-browser tab list \u91CD\u65B0\u542F\u52A8");
  } else {
    console.log("\n\u{1F4A1} \u505C\u6B62: bb-browser daemon stop");
  }
}
async function startCommand(options = {}) {
  await ensureDaemon();
  const status = await getDaemonStatus();
  if (options.json) {
    console.log(JSON.stringify(status, null, 2));
  } else {
    console.log("Daemon started");
    if (status) {
      console.log(`CDP connected:  ${status.cdpConnected ? "yes" : "no"}`);
      const tabs = status.tabs;
      console.log(`Tabs:           ${tabs?.length ?? 0}`);
    }
  }
}
async function shutdownCommand(options = {}) {
  const ok = await stopDaemon();
  if (options.json) {
    console.log(JSON.stringify({ stopped: ok }));
  } else {
    console.log(ok ? "Daemon stopped" : "Daemon was not running");
  }
}
function formatUptime(ms) {
  if (!ms || ms <= 0) return "0s";
  const s = Math.floor(ms / 1e3);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// packages/cli/src/index.ts
var VERSION = "0.14.2";
var TAB_REQUIRED_COMMANDS = /* @__PURE__ */ new Set([
  "snap",
  "screenshot",
  "get",
  "click",
  "hover",
  "fill",
  "type",
  "check",
  "uncheck",
  "select",
  "press",
  "scroll",
  "back",
  "forward",
  "reload",
  "close",
  "frame",
  "dialog",
  "network",
  "console",
  "errors",
  "goto",
  "cookies",
  "source"
]);
var HELP_TEXT = `
bb-browser - AI Agent \u6D4F\u89C8\u5668\u81EA\u52A8\u5316\u5DE5\u5177

\u5B89\u88C5\uFF1A
  npm install -g bb-browser

\u63D0\u793A\uFF1A\u5927\u591A\u6570\u6570\u636E\u83B7\u53D6\u4EFB\u52A1\u8BF7\u76F4\u63A5\u4F7F\u7528 site \u547D\u4EE4\uFF0C\u65E0\u9700\u624B\u52A8\u64CD\u4F5C\u6D4F\u89C8\u5668\uFF1A
  bb-browser site list                    \u67E5\u770B\u6240\u6709\u53EF\u7528\u547D\u4EE4
  bb-browser site twitter/search "AI"     \u793A\u4F8B\uFF1A\u641C\u7D22\u63A8\u6587

\u7528\u6CD5\uFF1A
  bb-browser <command> [options]

\u5F00\u59CB\u4F7F\u7528\uFF1A
  site recommend               \u63A8\u8350\u4F60\u53EF\u80FD\u9700\u8981\u7684 adapter\uFF08\u57FA\u4E8E\u6D4F\u89C8\u5386\u53F2\uFF09
  site list                    \u5217\u51FA\u6240\u6709 adapter
  site info <name>             \u67E5\u770B adapter \u7528\u6CD5\uFF08\u53C2\u6570\u3001\u8FD4\u56DE\u503C\u3001\u793A\u4F8B\uFF09
  site <name> [args]           \u8FD0\u884C adapter
  site update                  \u66F4\u65B0\u793E\u533A adapter \u5E93
  guide                        \u5982\u4F55\u628A\u4EFB\u4F55\u7F51\u7AD9\u53D8\u6210 adapter
  star                         \u2B50 Star bb-browser on GitHub

\u6D4F\u89C8\u5668\u64CD\u4F5C\uFF1A
  open <url> [--tab]           \u6253\u5F00 URL\uFF08\u65B0 tab \u6216\u6307\u5B9A tab\uFF09
  goto <url> --tab <id>        \u5728\u5F53\u524D tab \u5BFC\u822A\u5230\u65B0 URL\uFF08\u4FDD\u6301\u4E0A\u4E0B\u6587\uFF09
  snap [-i] [-c] [-d <n>]     \u83B7\u53D6\u9875\u9762\u5FEB\u7167 (--tab required)
  click <ref>                  \u70B9\u51FB\u5143\u7D20 (--tab required)
  hover <ref>                  \u60AC\u505C\u5143\u7D20 (--tab required)
  fill <ref> <text>            \u586B\u5145\u8F93\u5165\u6846 (--tab required)
  type <ref> <text>            \u9010\u5B57\u7B26\u8F93\u5165 (--tab required)
  check/uncheck <ref>          \u52FE\u9009/\u53D6\u6D88\u590D\u9009\u6846 (--tab required)
  select <ref> <val>           \u4E0B\u62C9\u6846\u9009\u62E9 (--tab required)
  press <key>                  \u53D1\u9001\u6309\u952E (--tab required)
  scroll <dir> [px]            \u6EDA\u52A8\u9875\u9762 (--tab required)

\u9875\u9762\u4FE1\u606F\uFF1A
  get text|url|title|value|html [ref]  \u83B7\u53D6\u9875\u9762\u5185\u5BB9 (--tab required)
  screenshot [path]            \u622A\u56FE (--tab required)
  eval "<js>" [--domain d]     \u6267\u884C JavaScript (--tab or --domain)

\u6807\u7B7E\u9875\uFF1A
  tab [list|new]               \u7BA1\u7406\u6807\u7B7E\u9875
  close                        \u5173\u95ED\u6807\u7B7E\u9875 (--tab required)
  status                       \u67E5\u770B\u53D7\u7BA1\u6D4F\u89C8\u5668\u72B6\u6001

\u5BFC\u822A\uFF1A
  back / forward / reload      \u540E\u9000 / \u524D\u8FDB / \u5237\u65B0 (--tab required)

\u8C03\u8BD5\uFF1A
  network requests [filter]    \u67E5\u770B\u7F51\u7EDC\u8BF7\u6C42 (--tab required)
  cookies [--filter <str>]     \u67E5\u770B\u9875\u9762 cookies (--tab required)
  source grep <pattern>        \u641C\u7D22\u5DF2\u52A0\u8F7D JS \u6E90\u7801 (--tab required)
  console [--clear]            \u67E5\u770B/\u6E05\u7A7A\u63A7\u5236\u53F0 (--tab required)
  errors [--clear]             \u67E5\u770B/\u6E05\u7A7A JS \u9519\u8BEF (--tab required)
  trace start [--tab <id>]     \u5F55\u5236\u64CD\u4F5C+\u7F51\u7EDC\u7684\u7EDF\u4E00\u65F6\u95F4\u7EBF
  trace events [--type action|request] \u67E5\u770B\u65F6\u95F4\u7EBF\uFF08\u652F\u6301 --since/--filter/--tab\uFF09
  trace body <requestId>       \u83B7\u53D6\u67D0\u4E2A\u8BF7\u6C42\u7684 response body
  trace stop                   \u505C\u6B62\u5F55\u5236\uFF08\u6570\u636E\u4FDD\u7559\uFF09
  trace status                 \u67E5\u770B\u5F55\u5236\u72B6\u6001
  daemon [start|status|stop]   \u7BA1\u7406 daemon

\u9009\u9879\uFF1A
  --json               \u4EE5 JSON \u683C\u5F0F\u8F93\u51FA
  --port <n>           \u6307\u5B9A Chrome CDP \u7AEF\u53E3
  --openclaw           \u4F18\u5148\u590D\u7528 OpenClaw \u6D4F\u89C8\u5668\u5B9E\u4F8B
  --jq <expr>          \u5BF9 JSON \u8F93\u51FA\u5E94\u7528 jq \u8FC7\u6EE4
  -i, --interactive    \u53EA\u8F93\u51FA\u53EF\u4EA4\u4E92\u5143\u7D20\uFF08snap \u547D\u4EE4\uFF09
  -c, --compact        \u79FB\u9664\u7A7A\u7ED3\u6784\u8282\u70B9\uFF08snap \u547D\u4EE4\uFF09
  -d, --depth <n>      \u9650\u5236\u6811\u6DF1\u5EA6\uFF08snap \u547D\u4EE4\uFF09
  -s, --selector <sel> \u9650\u5B9A CSS \u9009\u62E9\u5668\u8303\u56F4\uFF08snap \u547D\u4EE4\uFF09
  --tab <tabId>        \u6307\u5B9A\u64CD\u4F5C\u7684\u6807\u7B7E\u9875 ID
  --since <seq>        \u589E\u91CF\u67E5\u8BE2\uFF08network/console/errors/trace events\uFF09
  --type <t>           \u8FC7\u6EE4\u4E8B\u4EF6\u7C7B\u578B\uFF08trace events: action/request/response\uFF09
  --filter <str>       URL \u6216\u6587\u5B57\u8FC7\u6EE4\uFF08trace events/network requests/cookies\uFF09
  --exclude-static     \u6392\u9664\u9759\u6001\u8D44\u6E90\uFF08trace events/network requests\uFF09
  --limit <n>          \u9650\u5236\u8FD4\u56DE\u6761\u6570
  --request-id <id>    \u8BF7\u6C42 ID\uFF08trace body\uFF09
  --help, -h           \u663E\u793A\u5E2E\u52A9\u4FE1\u606F
  --version, -v        \u663E\u793A\u7248\u672C\u53F7
`.trim();
function parseArgs(argv) {
  const args = argv.slice(2);
  const result = {
    command: null,
    args: [],
    flags: {
      json: false,
      help: false,
      version: false,
      interactive: false,
      compact: false
    }
  };
  let skipNext = false;
  for (const arg of args) {
    if (skipNext) {
      skipNext = false;
      continue;
    }
    if (arg === "--json") {
      result.flags.json = true;
    } else if (arg === "--jq") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.jq = args[nextIdx];
        result.flags.json = true;
      }
    } else if (arg === "--openclaw") {
      result.flags.openclaw = true;
    } else if (arg === "--port") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.port = parseInt(args[nextIdx], 10);
      }
    } else if (arg === "--help" || arg === "-h") {
      result.flags.help = true;
    } else if (arg === "--version" || arg === "-v") {
      result.flags.version = true;
    } else if (arg === "--interactive" || arg === "-i") {
      result.flags.interactive = true;
    } else if (arg === "--compact" || arg === "-c") {
      result.flags.compact = true;
    } else if (arg === "--depth" || arg === "-d") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.depth = parseInt(args[nextIdx], 10);
      }
    } else if (arg === "--selector" || arg === "-s") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.selector = args[nextIdx];
      }
    } else if (arg === "--days") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.days = parseInt(args[nextIdx], 10);
      }
    } else if (arg === "--id") {
      skipNext = true;
    } else if (arg === "--tab") {
      skipNext = true;
    } else if (arg === "--domain") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.domain = args[nextIdx];
      }
    } else if (arg === "--args") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.args = args[nextIdx];
      }
    } else if (arg === "--since") {
      skipNext = true;
    } else if (arg === "--method") {
      skipNext = true;
    } else if (arg === "--status") {
      skipNext = true;
    } else if (arg === "--type") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.type = args[nextIdx];
      }
    } else if (arg === "--filter") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.filter = args[nextIdx];
      }
    } else if (arg === "--limit") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags.limit = parseInt(args[nextIdx], 10);
      }
    } else if (arg === "--request-id") {
      skipNext = true;
      const nextIdx = args.indexOf(arg) + 1;
      if (nextIdx < args.length) {
        result.flags["request-id"] = args[nextIdx];
      }
    } else if (arg === "--exclude-static") {
      result.flags.excludeStatic = true;
    } else if (arg.startsWith("-")) {
    } else if (result.command === null) {
      result.command = arg;
    } else {
      result.args.push(arg);
    }
  }
  return result;
}
async function main() {
  const parsed = parseArgs(process.argv);
  setJqExpression(parsed.flags.jq);
  const tabArgIdx = process.argv.indexOf("--tab");
  const globalTabId = tabArgIdx >= 0 && process.argv[tabArgIdx + 1] ? process.argv[tabArgIdx + 1] : void 0;
  const sinceArgIdx = process.argv.indexOf("--since");
  const globalSince = sinceArgIdx >= 0 && process.argv[sinceArgIdx + 1] ? process.argv[sinceArgIdx + 1] : void 0;
  if (parsed.flags.version) {
    console.log(VERSION);
    return;
  }
  if (!parsed.command) {
    console.log(HELP_TEXT);
    return;
  }
  if (parsed.flags.help && parsed.command !== "daemon") {
    console.log(HELP_TEXT);
    return;
  }
  if (TAB_REQUIRED_COMMANDS.has(parsed.command) && !globalTabId) {
    console.error(`Missing --tab. Run 'bb-browser tab list' to see open tabs.`);
    process.exit(1);
  }
  try {
    switch (parsed.command) {
      case "open": {
        const url = parsed.args[0];
        if (!url) {
          console.error("\u9519\u8BEF\uFF1A\u7F3A\u5C11 URL \u53C2\u6570");
          console.error("\u7528\u6CD5\uFF1Abb-browser open <url> [--tab current|<tabId>]");
          process.exit(1);
        }
        const tabIndex = process.argv.findIndex((a) => a === "--tab");
        const tab = tabIndex >= 0 ? process.argv[tabIndex + 1] : void 0;
        await openCommand(url, { json: parsed.flags.json, tab });
        break;
      }
      case "goto": {
        const gotoUrl = parsed.args[0];
        if (!gotoUrl) {
          console.error("\u7528\u6CD5\uFF1Abb-browser goto <url> --tab <tabId>");
          process.exit(1);
        }
        await gotoCommand(gotoUrl, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "snap": {
        await snapshotCommand({
          json: parsed.flags.json,
          interactive: parsed.flags.interactive,
          compact: parsed.flags.compact,
          maxDepth: parsed.flags.depth,
          selector: parsed.flags.selector,
          tabId: globalTabId
        });
        break;
      }
      case "click": {
        const ref = parsed.args[0];
        if (!ref) {
          console.error("\u9519\u8BEF\uFF1A\u7F3A\u5C11 ref \u53C2\u6570");
          console.error("\u7528\u6CD5\uFF1Abb-browser click <ref> --tab <tabId>");
          process.exit(1);
        }
        await clickCommand(ref, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "hover": {
        const ref = parsed.args[0];
        if (!ref) {
          console.error("\u9519\u8BEF\uFF1A\u7F3A\u5C11 ref \u53C2\u6570");
          process.exit(1);
        }
        await hoverCommand(ref, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "check": {
        const ref = parsed.args[0];
        if (!ref) {
          console.error("\u9519\u8BEF\uFF1A\u7F3A\u5C11 ref \u53C2\u6570");
          process.exit(1);
        }
        await checkCommand(ref, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "uncheck": {
        const ref = parsed.args[0];
        if (!ref) {
          console.error("\u9519\u8BEF\uFF1A\u7F3A\u5C11 ref \u53C2\u6570");
          process.exit(1);
        }
        await uncheckCommand(ref, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "fill": {
        const ref = parsed.args[0];
        const text = parsed.args[1];
        if (!ref || text === void 0) {
          console.error("\u7528\u6CD5\uFF1Abb-browser fill <ref> <text> --tab <tabId>");
          process.exit(1);
        }
        await fillCommand(ref, text, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "type": {
        const ref = parsed.args[0];
        const text = parsed.args[1];
        if (!ref || text === void 0) {
          console.error("\u7528\u6CD5\uFF1Abb-browser type <ref> <text> --tab <tabId>");
          process.exit(1);
        }
        await typeCommand(ref, text, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "select": {
        const ref = parsed.args[0];
        const value = parsed.args[1];
        if (!ref || value === void 0) {
          console.error("\u7528\u6CD5\uFF1Abb-browser select <ref> <value> --tab <tabId>");
          process.exit(1);
        }
        await selectCommand(ref, value, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "eval": {
        const script = parsed.args[0];
        if (!script) {
          console.error("\u7528\u6CD5\uFF1Abb-browser eval <script> [--tab <tabId>] [--domain <domain>] [--args <json>]");
          process.exit(1);
        }
        if (!globalTabId && !parsed.flags.domain) {
          console.error("Missing --tab or --domain. Run 'bb-browser tab list' to see open tabs.");
          process.exit(1);
        }
        await evalCommand(script, {
          json: parsed.flags.json,
          tabId: globalTabId,
          domain: parsed.flags.domain,
          args: parsed.flags.args
        });
        break;
      }
      case "get": {
        const attribute = parsed.args[0];
        if (!attribute) {
          console.error("\u7528\u6CD5\uFF1Abb-browser get <text|url|title|value|html> [ref] --tab <tabId>");
          process.exit(1);
        }
        if (!["text", "url", "title", "value", "html"].includes(attribute)) {
          console.error(`\u9519\u8BEF\uFF1A\u672A\u77E5\u5C5E\u6027 "${attribute}"`);
          console.error("\u652F\u6301\u7684\u5C5E\u6027\uFF1Atext, url, title, value, html");
          process.exit(1);
        }
        const ref = parsed.args[1];
        await getCommand(attribute, ref, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "daemon": {
        const daemonSubcommand = parsed.args[0];
        if (daemonSubcommand === "status") {
          await statusCommand({ json: parsed.flags.json });
          break;
        }
        if (daemonSubcommand === "stop" || daemonSubcommand === "shutdown") {
          await shutdownCommand({ json: parsed.flags.json });
          break;
        }
        if (daemonSubcommand === "start") {
          await startCommand({ json: parsed.flags.json });
          break;
        }
        const daemonPath = getDaemonPath();
        const daemonArgs = process.argv.slice(3);
        const { spawn: spawn3 } = await import("child_process");
        const child = spawn3(process.execPath, [daemonPath, ...daemonArgs], {
          stdio: "inherit"
        });
        child.on("exit", (code, signal) => {
          if (signal) {
            process.kill(process.pid, signal);
            return;
          }
          process.exit(code ?? 0);
        });
        return;
      }
      case "close": {
        await closeCommand({ json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "back": {
        await backCommand({ json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "forward": {
        await forwardCommand({ json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "reload": {
        await reloadCommand({ json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "screenshot": {
        const outputPath = parsed.args[0];
        await screenshotCommand(outputPath, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "press": {
        const key = parsed.args[0];
        if (!key) {
          console.error("\u7528\u6CD5\uFF1Abb-browser press <key> --tab <tabId>");
          process.exit(1);
        }
        await pressCommand(key, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "scroll": {
        const direction = parsed.args[0];
        const pixels = parsed.args[1];
        if (!direction) {
          console.error("\u7528\u6CD5\uFF1Abb-browser scroll <up|down|left|right> [pixels] --tab <tabId>");
          process.exit(1);
        }
        await scrollCommand(direction, pixels, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "tab": {
        await tabCommand(parsed.args, { json: parsed.flags.json, globalTabId });
        break;
      }
      case "status": {
        await statusCommand({ json: parsed.flags.json });
        break;
      }
      case "frame": {
        const selectorOrMain = parsed.args[0];
        if (!selectorOrMain) {
          console.error("\u7528\u6CD5\uFF1Abb-browser frame <selector> --tab <tabId>");
          console.error("      bb-browser frame main --tab <tabId>");
          process.exit(1);
        }
        if (selectorOrMain === "main") {
          await frameMainCommand({ json: parsed.flags.json, tabId: globalTabId });
        } else {
          await frameCommand(selectorOrMain, { json: parsed.flags.json, tabId: globalTabId });
        }
        break;
      }
      case "dialog": {
        const subCommand = parsed.args[0];
        if (!subCommand) {
          console.error("\u7528\u6CD5\uFF1Abb-browser dialog <accept|dismiss> [text] --tab <tabId>");
          process.exit(1);
        }
        const promptText = parsed.args[1];
        await dialogCommand(subCommand, promptText, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "network": {
        const subCommand = parsed.args[0] || "requests";
        const urlOrFilter = parsed.args[1];
        const abort = process.argv.includes("--abort");
        const withBody = process.argv.includes("--with-body");
        const bodyIndex = process.argv.findIndex((a) => a === "--body");
        const body = bodyIndex >= 0 ? process.argv[bodyIndex + 1] : void 0;
        const methodIndex = process.argv.findIndex((a) => a === "--method");
        const method = methodIndex >= 0 ? process.argv[methodIndex + 1] : void 0;
        const statusIndex = process.argv.findIndex((a) => a === "--status");
        const statusFilter = statusIndex >= 0 ? process.argv[statusIndex + 1] : void 0;
        const excludeStatic = process.argv.includes("--exclude-static");
        await networkCommand(subCommand, urlOrFilter, { json: parsed.flags.json, abort, body, withBody, tabId: globalTabId, since: globalSince, method, status: statusFilter, excludeStatic });
        break;
      }
      case "console": {
        const clear = process.argv.includes("--clear");
        await consoleCommand({ json: parsed.flags.json, clear, tabId: globalTabId, since: globalSince });
        break;
      }
      case "errors": {
        const clear = process.argv.includes("--clear");
        await errorsCommand({ json: parsed.flags.json, clear, tabId: globalTabId, since: globalSince });
        break;
      }
      case "cookies": {
        const f = parsed.flags;
        await cookiesCommand({
          json: parsed.flags.json,
          tabId: globalTabId,
          filter: f.filter
        });
        break;
      }
      case "source": {
        const srcSubCmd = parsed.args[0];
        const srcPattern = parsed.args[1];
        if (!srcSubCmd || !srcPattern) {
          console.error("\u7528\u6CD5\uFF1Abb-browser source grep <pattern> --tab <tabId>");
          process.exit(1);
        }
        await sourceCommand(srcSubCmd, srcPattern, { json: parsed.flags.json, tabId: globalTabId });
        break;
      }
      case "trace": {
        const subCmd = parsed.args[0];
        if (!subCmd || !["start", "stop", "status", "events", "body"].includes(subCmd)) {
          console.error("\u7528\u6CD5\uFF1Abb-browser trace <start|stop|status|events|body> [--tab <tabId>]");
          process.exit(1);
        }
        const f = parsed.flags;
        await traceCommand(subCmd, {
          json: parsed.flags.json,
          tabId: globalTabId,
          since: globalSince,
          type: f.type,
          filter: f.filter,
          limit: f.limit,
          requestId: f["request-id"] || parsed.args[1],
          excludeStatic: f.excludeStatic
        });
        break;
      }
      case "site": {
        await siteCommand(parsed.args, {
          json: parsed.flags.json,
          jq: parsed.flags.jq,
          days: parsed.flags.days,
          tabId: globalTabId,
          openclaw: parsed.flags.openclaw
        });
        break;
      }
      case "star": {
        const { execSync: execSync4 } = await import("child_process");
        try {
          execSync4("gh auth status", { stdio: "pipe" });
        } catch {
          console.error("\u9700\u8981\u5148\u5B89\u88C5\u5E76\u767B\u5F55 GitHub CLI: https://cli.github.com");
          process.exit(1);
        }
        const repos = ["epiral/bb-browser", "epiral/bb-sites"];
        for (const repo of repos) {
          try {
            execSync4(`gh api user/starred/${repo} -X PUT`, { stdio: "pipe" });
            console.log(`Starred ${repo}`);
          } catch {
            console.log(`Already starred or failed: ${repo}`);
          }
        }
        console.log("\nThanks for your support!");
        break;
      }
      case "guide": {
        console.log(`How to turn any website into a bb-browser site adapter
=======================================================

1. REVERSE ENGINEER the API
   bb-browser network clear --tab <tabId>
   bb-browser reload --tab <tabId>
   bb-browser network requests --filter "api" --with-body --json --tab <tabId>

2. TEST if direct fetch works (Tier 1)
   bb-browser eval "fetch('/api/endpoint',{credentials:'include'}).then(r=>r.json())" --tab <tabId>

3. WRITE the adapter (one JS file per operation)

4. TEST it
   Save to ~/.bb-browser/sites/platform/command.js (private, takes priority)
   bb-browser site platform/command "test query" --json

5. CONTRIBUTE
   Full guide: https://github.com/epiral/bb-sites/blob/main/SKILL.md`);
        break;
      }
      default: {
        console.error(`\u9519\u8BEF\uFF1A\u672A\u77E5\u547D\u4EE4 "${parsed.command}"`);
        console.error("\u8FD0\u884C bb-browser --help \u67E5\u770B\u53EF\u7528\u547D\u4EE4");
        process.exit(1);
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (parsed.flags.json) {
      console.log(
        JSON.stringify({
          error: { message }
        })
      );
    } else {
      console.error(`\u9519\u8BEF\uFF1A${message}`);
    }
    process.exit(1);
  }
}
main().then(() => process.exit(0));
//# sourceMappingURL=cli.js.map
