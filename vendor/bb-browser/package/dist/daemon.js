#!/usr/bin/env node
import {
  COMMANDS,
  COMMAND_TIMEOUT,
  DAEMON_DIR,
  DAEMON_HOST,
  DAEMON_PORT,
  commandToJsonSchema
} from "./chunk-ELAKRFAZ.js";

// packages/daemon/src/index.ts
import { parseArgs } from "util";
import { writeFileSync as writeFileSync4, unlinkSync as unlinkSync2, existsSync as existsSync4, readFileSync as readFileSync5 } from "fs";
import { request as httpRequest2 } from "http";
import { mkdirSync as mkdirSync4 } from "fs";
import { randomBytes } from "crypto";
import os3 from "os";
import path3 from "path";

// packages/daemon/src/http-server.ts
import { createServer } from "http";

// packages/daemon/src/command-dispatch.ts
import { readFileSync as readFileSync2, mkdirSync, writeFileSync } from "fs";
import path from "path";
import os from "os";
import { fileURLToPath } from "url";

// packages/daemon/src/site-adapter.ts
import { readFileSync, readdirSync, existsSync } from "fs";
import { join, relative } from "path";
import { homedir } from "os";
var BB_DIR = process.env.BB_BROWSER_HOME || join(homedir(), ".bb-browser");
var LOCAL_SITES_DIR = join(BB_DIR, "sites");
var COMMUNITY_SITES_DIR = join(BB_DIR, "bb-sites");
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
  if (!existsSync(dir)) return [];
  const sites = [];
  function walk(currentDir) {
    let entries;
    try {
      entries = readdirSync(currentDir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const fullPath = join(currentDir, entry.name);
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
function getAllSites() {
  const community = scanSites(COMMUNITY_SITES_DIR, "community");
  const local = scanSites(LOCAL_SITES_DIR, "local");
  const byName = /* @__PURE__ */ new Map();
  for (const s of community) byName.set(s.name, s);
  for (const s of local) byName.set(s.name, s);
  return Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name));
}
function matchTabOrigin(tabUrl, domain) {
  try {
    const tabOrigin = new URL(tabUrl).hostname;
    return tabOrigin === domain || tabOrigin.endsWith("." + domain);
  } catch {
    return false;
  }
}
async function executeSiteAdapter(cdp, name, args, tabId) {
  const sites = getAllSites();
  const site = sites.find((s) => s.name === name);
  if (!site) {
    const fuzzy = sites.filter((s) => s.name.includes(name));
    const suggestions = fuzzy.slice(0, 5).map((s) => s.name);
    throw new Error(
      `Site adapter "${name}" not found` + (suggestions.length > 0 ? `. Did you mean: ${suggestions.join(", ")}` : "")
    );
  }
  for (const [argName, argDef] of Object.entries(site.args)) {
    if (argDef.required && !args[argName]) {
      const usage = Object.keys(site.args).map((a) => {
        const def = site.args[a];
        return def.required ? `<${a}>` : `[${a}]`;
      }).join(" ");
      throw new Error(
        `Missing required argument "${argName}". Usage: site_run ${name} ${usage}`
      );
    }
  }
  let targetId;
  let shortId;
  if (tabId !== void 0) {
    const target = await cdp.ensurePageTarget(
      typeof tabId === "number" ? String(tabId) : tabId
    );
    targetId = target.id;
    shortId = cdp.tabManager.getTab(target.id)?.shortId;
  } else if (site.domain) {
    const targets = (await cdp.getTargets()).filter((t) => t.type === "page");
    for (const t of targets) {
      if (matchTabOrigin(t.url, site.domain)) {
        await cdp.attachAndEnable(t.id);
        targetId = t.id;
        shortId = cdp.tabManager.getTab(t.id)?.shortId;
        break;
      }
    }
    if (!targetId) {
      const created = await cdp.browserCommand(
        "Target.createTarget",
        { url: `https://${site.domain}` }
      );
      await cdp.attachAndEnable(created.targetId);
      targetId = created.targetId;
      shortId = cdp.tabManager.getTab(created.targetId)?.shortId;
      await new Promise((resolve2) => setTimeout(resolve2, 3e3));
    }
  }
  if (!targetId) {
    const target = await cdp.ensurePageTarget();
    targetId = target.id;
    shortId = cdp.tabManager.getTab(target.id)?.shortId;
  }
  const adapterDir = join(site.filePath, "..");
  const helperPath = join(adapterDir, "_helper.js");
  const helperScript = existsSync(helperPath) ? readFileSync(helperPath, "utf-8") + "\n" : "";
  const jsContent = readFileSync(site.filePath, "utf-8");
  const jsBody = jsContent.replace(/\/\*\s*@meta[\s\S]*?\*\//, "").trim();
  const argsJson = JSON.stringify(args);
  const script = `(async function(){${helperScript}
return (${jsBody})(${argsJson});})()`;
  const result = await cdp.evaluate(targetId, script, true);
  return {
    tab: shortId,
    result
  };
}

// packages/daemon/src/command-dispatch.ts
function buildRequestError(error2) {
  return error2 instanceof Error ? error2 : new Error(String(error2));
}
function ok(data) {
  return { result: data };
}
function fail(error2) {
  return { error: { message: buildRequestError(error2).message } };
}
var cachedBuildDomTreeScript = null;
function loadBuildDomTreeScript() {
  if (cachedBuildDomTreeScript) return cachedBuildDomTreeScript;
  const currentDir = path.dirname(fileURLToPath(import.meta.url));
  const candidates = [
    // Built dist: dist/daemon.js → ../packages/shared/buildDomTree.js
    path.resolve(currentDir, "../packages/shared/buildDomTree.js"),
    // Dev mode: packages/daemon/src/ → ../../shared/buildDomTree.js
    path.resolve(currentDir, "../../shared/buildDomTree.js"),
    // npm installed: dist/daemon.js → same level
    path.resolve(currentDir, "./buildDomTree.js"),
    path.resolve(currentDir, "../buildDomTree.js")
  ];
  for (const candidate of candidates) {
    try {
      cachedBuildDomTreeScript = readFileSync2(candidate, "utf8");
      return cachedBuildDomTreeScript;
    } catch {
    }
  }
  throw new Error("Cannot find buildDomTree.js");
}
function convertBuildDomTreeResult(result, options) {
  const { interactiveOnly, compact, maxDepth, selector } = options;
  const { rootId, map } = result;
  const refs = {};
  const lines = [];
  const getRole = (node) => {
    const tagName = node.tagName.toLowerCase();
    const role = node.attributes?.role;
    if (role) return role;
    const type = node.attributes?.type?.toLowerCase() || "text";
    const inputRoleMap = {
      text: "textbox",
      password: "textbox",
      email: "textbox",
      url: "textbox",
      tel: "textbox",
      search: "searchbox",
      number: "spinbutton",
      range: "slider",
      checkbox: "checkbox",
      radio: "radio",
      button: "button",
      submit: "button",
      reset: "button",
      file: "button"
    };
    const roleMap = {
      a: "link",
      button: "button",
      input: inputRoleMap[type] || "textbox",
      select: "combobox",
      textarea: "textbox",
      img: "image",
      nav: "navigation",
      main: "main",
      header: "banner",
      footer: "contentinfo",
      aside: "complementary",
      form: "form",
      table: "table",
      ul: "list",
      ol: "list",
      li: "listitem",
      h1: "heading",
      h2: "heading",
      h3: "heading",
      h4: "heading",
      h5: "heading",
      h6: "heading",
      dialog: "dialog",
      article: "article",
      section: "region",
      label: "label",
      details: "group",
      summary: "button"
    };
    return roleMap[tagName] || tagName;
  };
  const collectTextContent = (node, nodeMap, depthLimit = 5) => {
    const texts = [];
    const visit = (nodeId, depth) => {
      if (depth > depthLimit) return;
      const currentNode = nodeMap[nodeId];
      if (!currentNode) return;
      if ("type" in currentNode && currentNode.type === "TEXT_NODE") {
        const text = currentNode.text.trim();
        if (text) texts.push(text);
        return;
      }
      for (const childId of currentNode.children || []) visit(childId, depth + 1);
    };
    for (const childId of node.children || []) visit(childId, 0);
    return texts.join(" ").trim();
  };
  const getName = (node) => {
    const attrs = node.attributes || {};
    return attrs["aria-label"] || attrs.title || attrs.placeholder || attrs.alt || attrs.value || collectTextContent(node, map) || attrs.name || void 0;
  };
  const truncateText = (text, length = 50) => text.length <= length ? text : `${text.slice(0, length - 3)}...`;
  const selectorText = selector?.trim().toLowerCase();
  const matchesSelector = (node, role, name) => {
    if (!selectorText) return true;
    const haystack = [node.tagName, role, name, node.xpath || "", ...Object.values(node.attributes || {})].join(" ").toLowerCase();
    return haystack.includes(selectorText);
  };
  if (interactiveOnly) {
    const interactiveNodes = Object.entries(map).filter(([, node]) => !("type" in node) && node.highlightIndex !== void 0 && node.highlightIndex !== null).map(([id, node]) => ({ id, node })).sort((a, b) => (a.node.highlightIndex ?? 0) - (b.node.highlightIndex ?? 0));
    for (const { node } of interactiveNodes) {
      const refId = String(node.highlightIndex);
      const role = getRole(node);
      const name = getName(node);
      if (!matchesSelector(node, role, name)) continue;
      let line = `${role} [ref=${refId}]`;
      if (name) line += ` ${JSON.stringify(truncateText(name))}`;
      lines.push(line);
      refs[refId] = { xpath: node.xpath || "", role, name, tagName: node.tagName.toLowerCase() };
    }
    return { snapshot: lines.join("\n"), refs };
  }
  const walk = (nodeId, depth) => {
    if (maxDepth !== void 0 && depth > maxDepth) return;
    const node = map[nodeId];
    if (!node) return;
    if ("type" in node && node.type === "TEXT_NODE") {
      const text = node.text.trim();
      if (!text) return;
      lines.push(`${"  ".repeat(depth)}- text ${JSON.stringify(truncateText(text, compact ? 80 : 120))}`);
      return;
    }
    const el = node;
    const role = getRole(el);
    const name = getName(el);
    if (!matchesSelector(el, role, name)) {
      for (const childId of el.children || []) walk(childId, depth + 1);
      return;
    }
    const indent = "  ".repeat(depth);
    const refId = el.highlightIndex !== void 0 && el.highlightIndex !== null ? String(el.highlightIndex) : null;
    let line = `${indent}- ${role}`;
    if (refId) line += ` [ref=${refId}]`;
    if (name) line += ` ${JSON.stringify(truncateText(name, compact ? 50 : 80))}`;
    if (!compact) line += ` <${el.tagName.toLowerCase()}>`;
    lines.push(line);
    if (refId) {
      refs[refId] = { xpath: el.xpath || "", role, name, tagName: el.tagName.toLowerCase() };
    }
    for (const childId of el.children || []) walk(childId, depth + 1);
  };
  walk(rootId, 0);
  return { snapshot: lines.join("\n"), refs };
}
var CLEANUP_HIGHLIGHTS_SCRIPT = `(() => {
  if (window._highlightCleanupFunctions && window._highlightCleanupFunctions.length) {
    window._highlightCleanupFunctions.forEach(fn => { try { fn(); } catch {} });
    window._highlightCleanupFunctions = [];
  }
  const c = document.getElementById('playwright-highlight-container');
  if (c) c.remove();
})()`;
async function buildSnapshot(cdp, targetId, tab, request3) {
  const script = loadBuildDomTreeScript();
  const buildArgs = {
    showHighlightElements: true,
    focusHighlightIndex: -1,
    viewportExpansion: -1,
    debugMode: false,
    startId: 0,
    startHighlightIndex: 0
  };
  const expression = `(() => { ${script}; const fn = globalThis.buildDomTree ?? (typeof window !== 'undefined' ? window.buildDomTree : undefined); if (typeof fn !== 'function') { throw new Error('buildDomTree is not available after script injection'); } return fn(${JSON.stringify(buildArgs)}); })()`;
  const value = await cdp.evaluate(targetId, expression, true);
  if (!value || !value.map || !value.rootId) {
    const title = await cdp.evaluate(targetId, "document.title", true);
    const pageUrl = await cdp.evaluate(targetId, "location.href", true);
    tab.refs = {};
    return { snapshot: title || pageUrl, refs: {} };
  }
  const snapshot = convertBuildDomTreeResult(value, {
    interactiveOnly: !!request3.interactive,
    compact: !!request3.compact,
    maxDepth: request3.maxDepth,
    selector: request3.selector
  });
  tab.refs = snapshot.refs || {};
  return snapshot;
}
async function resolveBackendNodeIdByXPath(cdp, targetId, xpath) {
  await cdp.sessionCommand(targetId, "DOM.getDocument", { depth: 0 });
  const search = await cdp.sessionCommand(
    targetId,
    "DOM.performSearch",
    { query: xpath, includeUserAgentShadowDOM: true }
  );
  try {
    if (!search.resultCount) {
      throw new Error(`Unknown ref xpath: ${xpath}`);
    }
    const { nodeIds } = await cdp.sessionCommand(
      targetId,
      "DOM.getSearchResults",
      { searchId: search.searchId, fromIndex: 0, toIndex: search.resultCount }
    );
    for (const nodeId of nodeIds) {
      const described = await cdp.sessionCommand(targetId, "DOM.describeNode", { nodeId });
      if (described.node.backendNodeId) {
        return described.node.backendNodeId;
      }
    }
    throw new Error(`XPath resolved but no backend node id found: ${xpath}`);
  } finally {
    await cdp.sessionCommand(targetId, "DOM.discardSearchResults", { searchId: search.searchId }).catch(() => {
    });
  }
}
async function parseRef(cdp, targetId, tab, ref) {
  const found = tab.refs[ref];
  if (!found) {
    throw new Error(`Unknown ref: ${ref}. Run snapshot first.`);
  }
  if (found.backendDOMNodeId) {
    return found.backendDOMNodeId;
  }
  if (found.xpath) {
    const backendDOMNodeId = await resolveBackendNodeIdByXPath(cdp, targetId, found.xpath);
    found.backendDOMNodeId = backendDOMNodeId;
    return backendDOMNodeId;
  }
  throw new Error(`Unknown ref: ${ref}. Run snapshot first.`);
}
async function getInteractablePoint(cdp, targetId, backendNodeId) {
  const resolved = await cdp.sessionCommand(
    targetId,
    "DOM.resolveNode",
    { backendNodeId }
  );
  const call = await cdp.sessionCommand(targetId, "Runtime.callFunctionOn", {
    objectId: resolved.object.objectId,
    functionDeclaration: `function() {
      if (!(this instanceof Element)) {
        throw new Error('Ref does not resolve to an element');
      }
      this.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'center' });
      const rect = this.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0) {
        throw new Error('Element is not visible');
      }
      return {
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      };
    }`,
    returnByValue: true
  });
  if (call.exceptionDetails) {
    throw new Error(call.exceptionDetails.text || "Failed to resolve element point");
  }
  const point = call.result.value;
  if (!point || typeof point.x !== "number" || typeof point.y !== "number" || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
    throw new Error("Failed to resolve element point");
  }
  return point;
}
async function mouseClick(cdp, targetId, x, y) {
  await cdp.sessionCommand(targetId, "Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x,
    y,
    button: "none"
  });
  await cdp.sessionCommand(targetId, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 1
  });
  await cdp.sessionCommand(targetId, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 1
  });
}
async function insertTextIntoNode(cdp, targetId, backendNodeId, text, clearFirst) {
  const resolved = await cdp.sessionCommand(
    targetId,
    "DOM.resolveNode",
    { backendNodeId }
  );
  await cdp.sessionCommand(targetId, "Runtime.callFunctionOn", {
    objectId: resolved.object.objectId,
    functionDeclaration: `function(clearFirst) {
      if (typeof this.scrollIntoView === 'function') {
        this.scrollIntoView({ behavior: 'auto', block: 'center', inline: 'center' });
      }
      if (typeof this.focus === 'function') this.focus();
      if (this instanceof HTMLInputElement || this instanceof HTMLTextAreaElement) {
        if (clearFirst) {
          this.value = '';
          this.dispatchEvent(new Event('input', { bubbles: true }));
        }
        if (typeof this.setSelectionRange === 'function') {
          const end = this.value.length;
          this.setSelectionRange(end, end);
        }
        return true;
      }
      if (this instanceof HTMLElement && this.isContentEditable) {
        if (clearFirst) {
          this.textContent = '';
          this.dispatchEvent(new Event('input', { bubbles: true }));
        }
        const selection = window.getSelection();
        if (selection) {
          const range = document.createRange();
          range.selectNodeContents(this);
          range.collapse(false);
          selection.removeAllRanges();
          selection.addRange(range);
        }
        return true;
      }
      return false;
    }`,
    arguments: [{ value: clearFirst }],
    returnByValue: true
  });
  if (text) {
    await cdp.sessionCommand(targetId, "DOM.focus", { backendNodeId });
    await cdp.sessionCommand(targetId, "Input.insertText", { text });
  }
}
async function getAttributeValue(cdp, targetId, backendNodeId, attribute) {
  if (attribute === "text") {
    const resolved = await cdp.sessionCommand(
      targetId,
      "DOM.resolveNode",
      { backendNodeId }
    );
    const call2 = await cdp.sessionCommand(
      targetId,
      "Runtime.callFunctionOn",
      {
        objectId: resolved.object.objectId,
        functionDeclaration: `function() { return (this instanceof HTMLElement ? this.innerText : this.textContent || '').trim(); }`,
        returnByValue: true
      }
    );
    return String(call2.result.value ?? "");
  }
  const result = await cdp.sessionCommand(
    targetId,
    "DOM.resolveNode",
    { backendNodeId }
  );
  const call = await cdp.sessionCommand(
    targetId,
    "Runtime.callFunctionOn",
    {
      objectId: result.object.objectId,
      functionDeclaration: `function() { if (${JSON.stringify(attribute)} === 'url') return this.href || this.src || location.href; if (${JSON.stringify(attribute)} === 'title') return document.title; return this.getAttribute(${JSON.stringify(attribute)}) || ''; }`,
      returnByValue: true
    }
  );
  return String(call.result.value ?? "");
}
function isStaticAsset(url) {
  if (url.includes("/_next/static/")) return true;
  const ext = url.split("?")[0].split("#")[0].split(".").pop()?.toLowerCase();
  return ["js", "css", "png", "jpg", "jpeg", "gif", "svg", "ico", "woff", "woff2", "ttf", "eot", "map"].includes(ext || "");
}
function matchTabDomain(tabUrl, domain) {
  try {
    const hostname = new URL(tabUrl).hostname;
    return hostname === domain || hostname.endsWith("." + domain);
  } catch {
    return false;
  }
}
async function resolveTabByDomain(cdp, domain) {
  const targets = (await cdp.getTargets()).filter((t) => t.type === "page");
  for (const t of targets) {
    if (matchTabDomain(t.url, domain)) {
      await cdp.attachAndEnable(t.id);
      const tabState2 = cdp.tabManager.getTab(t.id);
      if (tabState2) {
        return { targetId: t.id, shortId: tabState2.shortId, tab: tabState2 };
      }
    }
  }
  const created = await cdp.browserCommand(
    "Target.createTarget",
    { url: `https://${domain}` }
  );
  await cdp.attachAndEnable(created.targetId);
  const LOAD_TIMEOUT = 1e4;
  await Promise.race([
    new Promise((resolve2) => {
      const check = () => {
        const tab = cdp.tabManager.getTab(created.targetId);
        if (tab) {
          resolve2();
          return;
        }
        setTimeout(check, 200);
      };
      setTimeout(check, 500);
    }),
    new Promise((resolve2) => setTimeout(resolve2, LOAD_TIMEOUT))
  ]);
  await new Promise((resolve2) => setTimeout(resolve2, 2e3));
  const tabState = cdp.tabManager.getTab(created.targetId);
  if (!tabState) throw new Error(`Failed to create tab for domain: ${domain}`);
  return { targetId: created.targetId, shortId: tabState.shortId, tab: tabState };
}
async function dispatchRequest(cdp, request3) {
  const tabRef = request3.tabId;
  if (request3.method === "tab_new") {
    const url = request3.url ?? "about:blank";
    const created = await cdp.browserCommand(
      "Target.createTarget",
      { url, background: true }
    );
    await cdp.attachAndEnable(created.targetId);
    const newTab = cdp.tabManager.getTab(created.targetId);
    return ok({
      tabId: created.targetId,
      url,
      tab: newTab?.shortId ?? created.targetId.slice(-4).toLowerCase(),
      seq: newTab?.recordAction({ action: "tab_new", url })
    });
  }
  if (request3.method === "eval" && request3.domain && tabRef === void 0) {
    if (!request3.script) return fail("Missing script parameter");
    try {
      const resolved = await resolveTabByDomain(cdp, request3.domain);
      const seq = resolved.tab.recordAction({ action: "eval", url: request3.domain });
      let script = request3.script;
      if (request3.args !== void 0) {
        const argsJson = JSON.stringify(request3.args);
        script = `(async function(){return (${script})(${argsJson});})()`;
      }
      const result = await cdp.evaluate(resolved.targetId, script, true);
      return ok({ result, tab: resolved.shortId, seq });
    } catch (error2) {
      return fail(error2);
    }
  }
  const target = await cdp.ensurePageTarget(
    tabRef !== void 0 ? String(tabRef) : void 0
  );
  const tab = cdp.tabManager.getTab(target.id);
  if (!tab) throw new Error("Internal error: tab state not found");
  const shortId = tab.shortId;
  switch (request3.method) {
    // -----------------------------------------------------------------------
    // Navigation
    // -----------------------------------------------------------------------
    case "open": {
      if (!request3.url) return fail("Missing url parameter");
      const seq = tab.recordAction({ action: "open", url: request3.url });
      if (tabRef === void 0) {
        const created = await cdp.browserCommand(
          "Target.createTarget",
          { url: request3.url, background: true }
        );
        const newTarget = await cdp.ensurePageTarget(created.targetId);
        const newTab = cdp.tabManager.getTab(newTarget.id);
        return ok({
          url: request3.url,
          tabId: newTarget.id,
          tab: newTab?.shortId ?? shortId,
          seq
        });
      }
      await cdp.pageCommand(target.id, "Page.navigate", { url: request3.url });
      tab.refs = {};
      return ok({
        url: request3.url,
        title: target.title,
        tabId: target.id,
        tab: shortId,
        seq
      });
    }
    case "goto": {
      if (!request3.url) return fail("Missing url");
      let url = request3.url;
      if (!url.startsWith("http://") && !url.startsWith("https://")) {
        url = "https://" + url;
      }
      const seq = tab.recordAction({ action: "goto", url });
      await cdp.pageCommand(target.id, "Page.navigate", { url });
      await new Promise((r) => setTimeout(r, 500));
      tab.refs = {};
      return ok({ tab: shortId, seq, url });
    }
    case "back": {
      const seq = tab.recordAction({ action: "back" });
      await cdp.evaluate(target.id, "history.back(); undefined");
      return ok({ tab: shortId, seq });
    }
    case "forward": {
      const seq = tab.recordAction({ action: "forward" });
      await cdp.evaluate(target.id, "history.forward(); undefined");
      return ok({ tab: shortId, seq });
    }
    case "reload": {
      const seq = tab.recordAction({ action: "reload" });
      await cdp.sessionCommand(target.id, "Page.reload", { ignoreCache: false });
      return ok({ tab: shortId, seq });
    }
    case "close": {
      const seq = tab.recordAction({ action: "close" });
      await cdp.browserCommand("Target.closeTarget", { targetId: target.id });
      tab.refs = {};
      return ok({ tab: shortId, seq });
    }
    // -----------------------------------------------------------------------
    // Snapshot / observation
    // -----------------------------------------------------------------------
    case "snap": {
      const snapshotData = await buildSnapshot(cdp, target.id, tab, request3);
      return ok({
        title: target.title,
        url: target.url,
        snapshotData,
        tab: shortId
      });
    }
    case "screenshot": {
      await cdp.evaluate(target.id, CLEANUP_HIGHLIGHTS_SCRIPT, true).catch(() => {
      });
      const result = await cdp.sessionCommand(
        target.id,
        "Page.captureScreenshot",
        { format: "png", fromSurface: true }
      );
      const dataDir = path.join(process.env.PINIX_HOME || path.join(os.homedir(), ".pinix"), "data", "browser", "screenshots");
      mkdirSync(dataDir, { recursive: true });
      const filename = `${Date.now()}.png`;
      writeFileSync(path.join(dataDir, filename), Buffer.from(result.data, "base64"));
      const data = {
        path: `pinix://browser/screenshots/${filename}`,
        tab: shortId
      };
      if (request3.includeBase64) {
        data.dataUrl = `data:image/png;base64,${result.data}`;
      }
      return ok(data);
    }
    // -----------------------------------------------------------------------
    // Element interaction
    // -----------------------------------------------------------------------
    case "click":
    case "hover": {
      if (!request3.ref) return fail("Missing ref parameter");
      const refInfo = tab.refs[request3.ref];
      const seq = tab.recordAction({
        action: request3.method,
        ref: Number(request3.ref),
        text: refInfo?.name?.slice(0, 80),
        role: refInfo?.role,
        tag: refInfo?.tagName
      });
      const backendNodeId = await parseRef(cdp, target.id, tab, request3.ref);
      const point = await getInteractablePoint(cdp, target.id, backendNodeId);
      await cdp.sessionCommand(target.id, "Input.dispatchMouseEvent", {
        type: "mouseMoved",
        x: point.x,
        y: point.y,
        button: "none"
      });
      if (request3.method === "click") {
        await mouseClick(cdp, target.id, point.x, point.y);
      }
      return ok({ tab: shortId, seq });
    }
    case "fill":
    case "type": {
      if (!request3.ref) return fail("Missing ref parameter");
      if (request3.text == null) return fail("Missing text parameter");
      const fillRefInfo = tab.refs[request3.ref];
      const seq = tab.recordAction({
        action: request3.method,
        ref: Number(request3.ref),
        value: request3.text,
        text: fillRefInfo?.name?.slice(0, 80),
        role: fillRefInfo?.role,
        tag: fillRefInfo?.tagName
      });
      const backendNodeId = await parseRef(cdp, target.id, tab, request3.ref);
      await insertTextIntoNode(cdp, target.id, backendNodeId, request3.text, request3.method === "fill");
      return ok({
        value: request3.text,
        tab: shortId,
        seq
      });
    }
    case "check":
    case "uncheck": {
      if (!request3.ref) return fail("Missing ref parameter");
      const seq = tab.recordAction({ action: request3.method, ref: Number(request3.ref) });
      const desired = request3.method === "check";
      const backendNodeId = await parseRef(cdp, target.id, tab, request3.ref);
      const resolved = await cdp.sessionCommand(
        target.id,
        "DOM.resolveNode",
        { backendNodeId }
      );
      await cdp.sessionCommand(target.id, "Runtime.callFunctionOn", {
        objectId: resolved.object.objectId,
        functionDeclaration: `function() { this.checked = ${desired}; this.dispatchEvent(new Event('input', { bubbles: true })); this.dispatchEvent(new Event('change', { bubbles: true })); }`
      });
      return ok({ tab: shortId, seq });
    }
    case "select": {
      if (!request3.ref || request3.value == null) return fail("Missing ref or value parameter");
      const seq = tab.recordAction({ action: "select", ref: Number(request3.ref), value: request3.value });
      const backendNodeId = await parseRef(cdp, target.id, tab, request3.ref);
      const resolved = await cdp.sessionCommand(
        target.id,
        "DOM.resolveNode",
        { backendNodeId }
      );
      await cdp.sessionCommand(target.id, "Runtime.callFunctionOn", {
        objectId: resolved.object.objectId,
        functionDeclaration: `function() { this.value = ${JSON.stringify(request3.value)}; this.dispatchEvent(new Event('input', { bubbles: true })); this.dispatchEvent(new Event('change', { bubbles: true })); }`
      });
      return ok({
        value: request3.value,
        tab: shortId,
        seq
      });
    }
    case "get": {
      if (!request3.attribute) return fail("Missing attribute parameter");
      if (request3.attribute === "url" && !request3.ref) {
        return ok({
          value: await cdp.evaluate(target.id, "location.href", true),
          tab: shortId
        });
      }
      if (request3.attribute === "title" && !request3.ref) {
        return ok({
          value: await cdp.evaluate(target.id, "document.title", true),
          tab: shortId
        });
      }
      if (!request3.ref) return fail("Missing ref parameter");
      const value = await getAttributeValue(
        cdp,
        target.id,
        await parseRef(cdp, target.id, tab, request3.ref),
        request3.attribute
      );
      return ok({ value, tab: shortId });
    }
    case "press": {
      if (!request3.key) return fail("Missing key parameter");
      const seq = tab.recordAction({ action: "press", key: request3.key });
      await cdp.sessionCommand(target.id, "Input.dispatchKeyEvent", {
        type: "keyDown",
        key: request3.key
      });
      if (request3.key.length === 1) {
        await cdp.sessionCommand(target.id, "Input.dispatchKeyEvent", {
          type: "char",
          text: request3.key,
          key: request3.key
        });
      }
      await cdp.sessionCommand(target.id, "Input.dispatchKeyEvent", {
        type: "keyUp",
        key: request3.key
      });
      return ok({ tab: shortId, seq });
    }
    case "scroll": {
      const seq = tab.recordAction({ action: "scroll", direction: request3.direction });
      const pixels = request3.pixels ?? 300;
      let deltaX = 0;
      let deltaY = 0;
      switch (request3.direction) {
        case "up":
          deltaY = -pixels;
          break;
        case "down":
          deltaY = pixels;
          break;
        case "left":
          deltaX = -pixels;
          break;
        case "right":
          deltaX = pixels;
          break;
      }
      await cdp.sessionCommand(target.id, "Input.dispatchMouseEvent", {
        type: "mouseWheel",
        x: 0,
        y: 0,
        deltaX,
        deltaY
      });
      return ok({ tab: shortId, seq });
    }
    case "eval": {
      if (!request3.script) return fail("Missing script parameter");
      const seq = tab.recordAction({ action: "eval" });
      let script = request3.script;
      if (request3.args !== void 0) {
        const argsJson = JSON.stringify(request3.args);
        script = `(async function(){return (${script})(${argsJson});})()`;
      }
      const result = await cdp.evaluate(target.id, script, true);
      return ok({ result, tab: shortId, seq });
    }
    // -----------------------------------------------------------------------
    // Tab management
    // -----------------------------------------------------------------------
    case "tab_list": {
      const targets = (await cdp.getTargets()).filter((t) => t.type === "page");
      const tabs = targets.map((t, index) => {
        const tState = cdp.tabManager.getTab(t.id);
        return {
          index,
          url: t.url,
          title: t.title,
          active: t.id === cdp.currentTargetId || !cdp.currentTargetId && index === 0,
          tabId: t.id,
          tab: tState?.shortId ?? t.id.slice(-4).toLowerCase()
        };
      });
      return ok({
        tabs,
        activeIndex: tabs.findIndex((t) => t.active)
      });
    }
    // tab_new is handled before ensurePageTarget() above
    // -----------------------------------------------------------------------
    // Frame navigation
    // -----------------------------------------------------------------------
    case "frame": {
      if (!request3.selector) return fail("Missing selector parameter");
      const seq = tab.recordAction({ action: "frame" });
      const document = await cdp.pageCommand(
        target.id,
        "DOM.getDocument",
        {}
      );
      const node = await cdp.pageCommand(
        target.id,
        "DOM.querySelector",
        { nodeId: document.root.nodeId, selector: request3.selector }
      );
      if (!node.nodeId) return fail(`iframe not found: ${request3.selector}`);
      const described = await cdp.pageCommand(target.id, "DOM.describeNode", { nodeId: node.nodeId });
      const frameId = described.node.frameId;
      const nodeName = String(described.node.nodeName ?? "").toLowerCase();
      if (!frameId) return fail(`Cannot get iframe frameId: ${request3.selector}`);
      if (nodeName && nodeName !== "iframe" && nodeName !== "frame") {
        return fail(`Element is not an iframe: ${nodeName}`);
      }
      tab.activeFrameId = frameId;
      const attributes = described.node.attributes ?? [];
      const attrMap = {};
      for (let i = 0; i < attributes.length; i += 2) {
        attrMap[String(attributes[i])] = String(attributes[i + 1] ?? "");
      }
      return ok({
        frameInfo: {
          selector: request3.selector,
          name: attrMap.name ?? "",
          url: attrMap.src ?? "",
          frameId
        },
        tab: shortId,
        seq
      });
    }
    case "frame_main": {
      const seq = tab.recordAction({ action: "frame_main" });
      tab.activeFrameId = null;
      return ok({
        frameInfo: { frameId: 0 },
        tab: shortId,
        seq
      });
    }
    // -----------------------------------------------------------------------
    // Dialog
    // -----------------------------------------------------------------------
    case "dialog": {
      const seq = tab.recordAction({ action: "dialog" });
      tab.dialogHandler = {
        accept: request3.dialogResponse !== "dismiss",
        ...request3.promptText !== void 0 ? { promptText: request3.promptText } : {}
      };
      await cdp.sessionCommand(target.id, "Page.enable");
      return ok({
        dialogInfo: {
          type: "armed",
          message: `Dialog handler armed: ${request3.dialogResponse ?? "accept"}`,
          handled: false
        },
        tab: shortId,
        seq
      });
    }
    // -----------------------------------------------------------------------
    // Network observation
    // -----------------------------------------------------------------------
    case "network": {
      const subCommand = request3.action ?? request3.networkCommand ?? "requests";
      switch (subCommand) {
        case "requests": {
          const queryResult = tab.getNetworkRequests({
            since: request3.since,
            filter: request3.filter,
            method: request3.httpMethod,
            status: request3.status,
            limit: request3.limit
          });
          let items = queryResult.items;
          if (request3.excludeStatic) {
            items = items.filter((item) => !isStaticAsset(item.url));
          }
          if (request3.withBody) {
            await Promise.all(
              items.map(async (item) => {
                if (item.failed || item.responseBody !== void 0 || item.bodyError !== void 0) return;
                try {
                  const body = await cdp.sessionCommand(
                    target.id,
                    "Network.getResponseBody",
                    { requestId: item.requestId }
                  );
                  item.responseBody = body.body;
                  item.responseBodyBase64 = body.base64Encoded;
                } catch (error2) {
                  item.bodyError = error2 instanceof Error ? error2.message : String(error2);
                }
              })
            );
          }
          return ok({
            networkRequests: items,
            tab: shortId,
            cursor: queryResult.cursor
          });
        }
        case "route":
          return ok({ routeCount: 0, tab: shortId });
        case "unroute":
          return ok({ routeCount: 0, tab: shortId });
        case "clear":
          tab.clearNetwork();
          return ok({ tab: shortId });
        default:
          return fail(`Unknown network subcommand: ${subCommand}`);
      }
    }
    // -----------------------------------------------------------------------
    // Console observation
    // -----------------------------------------------------------------------
    case "console": {
      const subCommand = request3.action ?? request3.consoleCommand ?? "get";
      switch (subCommand) {
        case "get": {
          const queryResult = tab.getConsoleMessages({
            since: request3.since,
            filter: request3.filter,
            limit: request3.limit
          });
          return ok({
            consoleMessages: queryResult.items,
            tab: shortId,
            cursor: queryResult.cursor
          });
        }
        case "clear":
          tab.clearConsole();
          return ok({ tab: shortId });
        default:
          return fail(`Unknown console subcommand: ${subCommand}`);
      }
    }
    // -----------------------------------------------------------------------
    // JS Errors observation
    // -----------------------------------------------------------------------
    case "errors": {
      const subCommand = request3.action ?? request3.errorsCommand ?? "get";
      switch (subCommand) {
        case "get": {
          const queryResult = tab.getJSErrors({
            since: request3.since,
            filter: request3.filter,
            limit: request3.limit
          });
          return ok({
            jsErrors: queryResult.items,
            tab: shortId,
            cursor: queryResult.cursor
          });
        }
        case "clear":
          tab.clearErrors();
          return ok({ tab: shortId });
        default:
          return fail(`Unknown errors subcommand: ${subCommand}`);
      }
    }
    // -----------------------------------------------------------------------
    // Trace
    // -----------------------------------------------------------------------
    case "trace": {
      const subCommand = request3.action ?? request3.traceCommand ?? "status";
      const tm = cdp.tabManager;
      switch (subCommand) {
        case "start": {
          let traceTargetId;
          if (tabRef !== void 0) {
            traceTargetId = target.id;
          }
          const session = tm.traceStart(traceTargetId);
          for (const tid of session.tracedTabs) {
            cdp.enableHumanCapture(tid).catch(() => {
            });
          }
          const tracedShortIds = Array.from(session.tracedTabs).map((tid) => tm.getTabShortId(tid)).filter(Boolean);
          return ok({
            traceStatus: { recording: true, eventCount: 0, tracedTabs: tracedShortIds },
            tab: shortId
          });
        }
        case "stop": {
          const session = tm.traceSession;
          tm.traceStop();
          return ok({
            traceStatus: {
              recording: false,
              eventCount: session?.timeline.length ?? 0,
              tracedTabs: session ? Array.from(session.tracedTabs).map((tid) => tm.getTabShortId(tid)).filter(Boolean) : []
            },
            tab: shortId
          });
        }
        case "status": {
          const session = tm.traceSession;
          return ok({
            traceStatus: {
              recording: session?.active ?? false,
              eventCount: session?.timeline.length ?? 0,
              tracedTabs: session ? Array.from(session.tracedTabs).map((tid) => tm.getTabShortId(tid)).filter(Boolean) : []
            },
            tab: shortId
          });
        }
        case "events": {
          const session = tm.traceSession;
          if (!session) return ok({ traceEvents: [], cursor: 0, tab: shortId });
          let events = [...session.timeline];
          if (request3.tabId !== void 0) {
            const filterTab = String(request3.tabId);
            events = events.filter((e) => e.tab === filterTab);
          }
          if (request3.traceType) {
            events = events.filter((e) => e.type === request3.traceType);
          }
          if (request3.since !== void 0) {
            const threshold = typeof request3.since === "number" ? request3.since : 0;
            events = events.filter((e) => e.seq > threshold);
          }
          if (request3.excludeStatic) {
            const excludedRequestIds = /* @__PURE__ */ new Set();
            events = events.filter((e) => {
              if (e.type === "request") {
                if (isStaticAsset(e.url)) {
                  excludedRequestIds.add(e.requestId);
                  return false;
                }
                return true;
              }
              if (e.type === "response") {
                return !excludedRequestIds.has(e.requestId);
              }
              return true;
            });
          }
          if (request3.filter) {
            const f = request3.filter.toLowerCase();
            events = events.filter((e) => {
              if (e.type === "request") return e.url.toLowerCase().includes(f);
              if (e.type === "navigation") return e.url.toLowerCase().includes(f);
              if (e.type === "action") return (e.text || e.action || "").toLowerCase().includes(f);
              return false;
            });
          }
          if (request3.limit !== void 0 && request3.limit > 0 && events.length > request3.limit) {
            events = events.slice(-request3.limit);
          }
          const cursor = events.length > 0 ? events[events.length - 1].seq : typeof request3.since === "number" ? request3.since : 0;
          return ok({ traceEvents: events, cursor, tab: shortId });
        }
        case "body": {
          if (!request3.requestId) return fail("Missing requestId parameter");
          const session = tm.traceSession;
          if (!session) return fail("No trace session");
          const reqEntry = session.timeline.find(
            (e) => e.type === "request" && e.requestId === request3.requestId
          );
          if (!reqEntry || reqEntry.type !== "request") return fail(`Request ${request3.requestId} not found in trace`);
          const reqTabShortId = reqEntry.tab;
          const reqTargetId = tm.resolveShortId(reqTabShortId);
          if (!reqTargetId) return fail(`Tab ${reqTabShortId} no longer exists`);
          try {
            const body = await cdp.sessionCommand(
              reqTargetId,
              "Network.getResponseBody",
              { requestId: request3.requestId }
            );
            const traceRequestBody = reqEntry.body;
            return ok({
              traceBody: {
                requestId: request3.requestId,
                body: body.body,
                base64Encoded: body.base64Encoded,
                requestBody: traceRequestBody
              },
              tab: shortId
            });
          } catch (error2) {
            const traceRequestBody = reqEntry.body;
            if (traceRequestBody) {
              return ok({
                traceBody: {
                  requestId: request3.requestId,
                  body: "",
                  base64Encoded: false,
                  requestBody: traceRequestBody
                },
                tab: shortId
              });
            }
            return fail(error2);
          }
        }
        default:
          return fail(`Unknown trace subcommand: ${subCommand}`);
      }
    }
    // -----------------------------------------------------------------------
    // Cookies
    // -----------------------------------------------------------------------
    case "cookies": {
      const seq = tab.recordAction({ action: "cookies" });
      const { cookies } = await cdp.sessionCommand(target.id, "Network.getCookies", {});
      let filtered = cookies;
      if (request3.filter) {
        const f = request3.filter.toLowerCase();
        filtered = cookies.filter(
          (c) => c.name.toLowerCase().includes(f) || c.domain.toLowerCase().includes(f)
        );
      }
      return ok({
        tab: shortId,
        seq,
        cookies: filtered.map((c) => ({
          name: c.name,
          value: c.value,
          domain: c.domain,
          path: c.path,
          expires: c.expires,
          httpOnly: c.httpOnly,
          secure: c.secure
        }))
      });
    }
    // -----------------------------------------------------------------------
    // Source search
    // -----------------------------------------------------------------------
    case "source": {
      let collectScripts2 = function(node) {
        if (node.resources) {
          for (const r of node.resources) {
            if (r.type === "Script" && r.url && !r.url.startsWith("data:")) {
              scripts.push({ url: r.url, frameId: node.frame.id });
            }
          }
        }
        if (node.childFrames) {
          for (const child of node.childFrames) collectScripts2(child);
        }
      };
      var collectScripts = collectScripts2;
      const subCmd = request3.action ?? request3.sourceCommand;
      if (subCmd !== "grep") return fail("Unknown source subcommand. Use: source --action grep --pattern <pattern>");
      const pattern = request3.pattern ?? request3.sourcePattern;
      if (!pattern) return fail("Missing search pattern");
      const seq = tab.recordAction({ action: "source", url: `grep ${pattern}` });
      const { frameTree } = await cdp.sessionCommand(target.id, "Page.getResourceTree", {});
      const scripts = [];
      collectScripts2(frameTree);
      const sourceResults = [];
      for (const script of scripts) {
        try {
          const { content } = await cdp.sessionCommand(
            target.id,
            "Page.getResourceContent",
            { frameId: script.frameId, url: script.url }
          );
          if (!content) continue;
          const regex = new RegExp(pattern, "gi");
          const lines = content.split("\n");
          const matches = [];
          for (const line of lines) {
            if (regex.test(line)) {
              const trimmed = line.trim().slice(0, 200);
              matches.push(trimmed);
              regex.lastIndex = 0;
            }
          }
          if (matches.length > 0) {
            const shortUrl = script.url.replace(/^https?:\/\/[^/]+/, "");
            sourceResults.push({ url: shortUrl, matches });
          }
        } catch {
          continue;
        }
      }
      return ok({ tab: shortId, seq, sourceResults });
    }
    // -----------------------------------------------------------------------
    // Site adapters
    // -----------------------------------------------------------------------
    case "site_list": {
      const sites = getAllSites();
      return ok({
        sites: sites.map((s) => ({
          name: s.name,
          description: s.description,
          domain: s.domain,
          source: s.source
        }))
      });
    }
    case "site_info": {
      const name = request3.siteName;
      if (!name) return fail("Missing siteName");
      const sites = getAllSites();
      const site = sites.find((s) => s.name === name);
      if (!site) return fail(`Site adapter "${name}" not found`);
      return ok({
        name: site.name,
        description: site.description,
        domain: site.domain,
        args: site.args,
        example: site.example,
        readOnly: site.readOnly
      });
    }
    case "site_search": {
      const query = (request3.query || "").toLowerCase();
      const sites = getAllSites();
      const matches = sites.filter(
        (s) => s.name.toLowerCase().includes(query) || s.description?.toLowerCase().includes(query) || s.domain?.toLowerCase().includes(query)
      );
      return ok({
        sites: matches.map((s) => ({
          name: s.name,
          description: s.description,
          domain: s.domain,
          source: s.source
        }))
      });
    }
    case "site_run": {
      const name = request3.siteName;
      const args = request3.siteArgs || {};
      if (!name) return fail("Missing siteName");
      try {
        const result = await executeSiteAdapter(cdp, name, args, request3.tabId);
        return ok({
          tab: result.tab,
          result: result.result
        });
      } catch (error2) {
        return fail(error2);
      }
    }
    default:
      return fail(`Unknown method: ${request3.method}`);
  }
}

// packages/daemon/src/http-server.ts
var HttpServer = class {
  server = null;
  host;
  port;
  token;
  cdp;
  cdpHost;
  cdpPort;
  onShutdown;
  startTime = 0;
  constructor(options) {
    this.host = options.host ?? "127.0.0.1";
    this.port = options.port ?? DAEMON_PORT;
    this.token = options.token ?? null;
    this.cdp = options.cdp;
    this.cdpHost = options.cdpHost ?? null;
    this.cdpPort = options.cdpPort ?? null;
    this.onShutdown = options.onShutdown;
  }
  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------
  async start() {
    return new Promise((resolve2, reject) => {
      this.server = createServer((req, res) => {
        this.handleRequest(req, res);
      });
      this.server.on("error", reject);
      this.server.listen(this.port, this.host, () => {
        this.startTime = Date.now();
        resolve2();
      });
    });
  }
  async stop() {
    if (this.server) {
      return new Promise((resolve2) => {
        this.server.close(() => resolve2());
      });
    }
  }
  get uptime() {
    if (this.startTime === 0) return 0;
    return Math.floor((Date.now() - this.startTime) / 1e3);
  }
  // ---------------------------------------------------------------------------
  // Auth
  // ---------------------------------------------------------------------------
  checkAuth(req, res) {
    if (!this.token) return true;
    const auth = req.headers.authorization ?? "";
    if (auth === `Bearer ${this.token}`) return true;
    this.sendJson(res, 401, { error: "Unauthorized" });
    return false;
  }
  // ---------------------------------------------------------------------------
  // Routing
  // ---------------------------------------------------------------------------
  handleRequest(req, res) {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
    if (req.method === "OPTIONS") {
      res.writeHead(204);
      res.end();
      return;
    }
    if (!this.checkAuth(req, res)) return;
    const url = req.url ?? "/";
    if (req.method === "POST" && url === "/command") {
      this.handleCommand(req, res);
    } else if (req.method === "GET" && url === "/status") {
      this.handleStatus(req, res);
    } else if (req.method === "POST" && url === "/shutdown") {
      this.handleShutdown(req, res);
    } else {
      this.sendJson(res, 404, { error: "Not found" });
    }
  }
  // ---------------------------------------------------------------------------
  // POST /command
  // ---------------------------------------------------------------------------
  async handleCommand(req, res) {
    try {
      const body = await this.readBody(req);
      const request3 = JSON.parse(body);
      if (!this.cdp.connected) {
        try {
          await Promise.race([
            this.cdp.waitUntilReady(),
            new Promise(
              (_, reject) => setTimeout(() => reject(new Error("CDP connection timeout")), COMMAND_TIMEOUT)
            )
          ]);
        } catch {
          const cdpTarget = `${this.cdp.host}:${this.cdp.port}`;
          this.sendJson(res, 503, {
            error: {
              message: `Chrome not connected (CDP at ${cdpTarget})`,
              hint: "Make sure Chrome is running. Try: bb-browser daemon shutdown && bb-browser tab list"
            }
          });
          return;
        }
      }
      const timeout = new Promise(
        (_, reject) => setTimeout(() => reject(new Error("Command timeout")), COMMAND_TIMEOUT)
      );
      const response = await Promise.race([
        dispatchRequest(this.cdp, request3),
        timeout
      ]);
      this.sendJson(res, 200, response);
    } catch (error2) {
      this.sendJson(res, 400, {
        error: {
          message: error2 instanceof Error ? error2.message : "Invalid request"
        }
      });
    }
  }
  // ---------------------------------------------------------------------------
  // GET /status
  // ---------------------------------------------------------------------------
  handleStatus(_req, res) {
    const tabs = this.cdp.tabManager.allTabs().map((tab) => ({
      shortId: tab.shortId,
      targetId: tab.targetId,
      networkRequests: tab.networkRequests.size,
      consoleMessages: tab.consoleMessages.size,
      jsErrors: tab.jsErrors.size,
      lastActionSeq: tab.lastActionSeq
    }));
    this.sendJson(res, 200, {
      running: true,
      cdpConnected: this.cdp.connected,
      cdpHost: this.cdpHost,
      cdpPort: this.cdpPort,
      uptime: this.uptime,
      currentSeq: this.cdp.tabManager.currentSeq(),
      currentTargetId: this.cdp.currentTargetId,
      tabs
    });
  }
  // ---------------------------------------------------------------------------
  // POST /shutdown
  // ---------------------------------------------------------------------------
  handleShutdown(_req, res) {
    this.sendJson(res, 200, { code: 0, message: "Shutting down" });
    setTimeout(() => {
      if (this.onShutdown) {
        this.onShutdown();
      }
    }, 100);
  }
  // ---------------------------------------------------------------------------
  // Utility
  // ---------------------------------------------------------------------------
  readBody(req) {
    return new Promise((resolve2, reject) => {
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => resolve2(Buffer.concat(chunks).toString("utf-8")));
      req.on("error", reject);
    });
  }
  sendJson(res, status, data) {
    const body = JSON.stringify(data);
    res.writeHead(status, {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body)
    });
    res.end(body);
  }
};

// packages/daemon/src/cdp-connection.ts
import { request as httpRequest } from "http";
import WebSocket from "ws";
var STEALTH_SCRIPT = `
(() => {
  if (window.__bbStealthApplied) return;
  try { Object.defineProperty(window, '__bbStealthApplied', { value: true, configurable: false }); }
  catch (e) { window.__bbStealthApplied = true; }

  const define = (obj, name, value) => {
    try {
      Object.defineProperty(obj, name, { get: () => value, configurable: true });
    } catch (e) {}
  };

  try {
    define(Navigator.prototype, 'webdriver', false);
  } catch (e) {}
  define(navigator, 'webdriver', false);
  define(navigator, 'languages', ['zh-CN', 'zh', 'en-US', 'en']);
  define(navigator, 'language', 'zh-CN');
  define(navigator, 'platform', 'MacIntel');
  define(navigator, 'hardwareConcurrency', 8);
  define(navigator, 'deviceMemory', 8);

  const fakePlugin = (name, filename, description) => {
    const plugin = { name, filename, description, length: 1 };
    plugin[0] = { type: 'application/pdf', suffixes: 'pdf', description, enabledPlugin: plugin };
    return plugin;
  };
  try {
    const plugins = [
      fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Microsoft Edge PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('WebKit built-in PDF', 'internal-pdf-viewer', 'Portable Document Format'),
    ];
    plugins.item = (i) => plugins[i] || null;
    plugins.namedItem = (name) => plugins.find((p) => p.name === name) || null;
    plugins.refresh = () => {};
    Object.setPrototypeOf(plugins, PluginArray.prototype);
    define(navigator, 'plugins', plugins);

    const mimeTypes = [{
      type: 'application/pdf',
      suffixes: 'pdf',
      description: 'Portable Document Format',
      enabledPlugin: plugins[0],
    }];
    mimeTypes.item = (i) => mimeTypes[i] || null;
    mimeTypes.namedItem = (name) => mimeTypes.find((m) => m.type === name) || null;
    Object.setPrototypeOf(mimeTypes, MimeTypeArray.prototype);
    define(navigator, 'mimeTypes', mimeTypes);
  } catch (e) {}

  try {
    window.chrome = window.chrome || {};
    window.chrome.runtime = window.chrome.runtime || {};
    window.chrome.app = window.chrome.app || {
      isInstalled: false,
      InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
      RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
    };
    window.chrome.csi = window.chrome.csi || function () { return { onloadT: Date.now(), startE: Date.now() }; };
    window.chrome.loadTimes = window.chrome.loadTimes || function () { return {}; };
  } catch (e) {}

  try {
    const origQuery = navigator.permissions && navigator.permissions.query;
    if (origQuery) {
      navigator.permissions.query = (params) =>
        params && params.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission || 'prompt', onchange: null })
          : origQuery.call(navigator.permissions, params);
    }
  } catch (e) {}

  const overrideGetParameter = (proto) => {
    if (!proto || !proto.getParameter) return;
    const original = proto.getParameter;
    proto.getParameter = function (param) {
      if (param === 37445) return 'Intel Inc.';
      if (param === 37446) return 'Intel Iris OpenGL Engine';
      return original.apply(this, [param]);
    };
  };
  try { overrideGetParameter(WebGLRenderingContext.prototype); } catch (e) {}
  try { overrideGetParameter(WebGL2RenderingContext.prototype); } catch (e) {}

  try {
    if (typeof Notification !== 'undefined') {
      define(Notification, 'permission', 'default');
      Notification.requestPermission = function () {
        return new Promise((resolve) => setTimeout(() => resolve('default'), 120));
      };
    }
  } catch (e) {}

  // Per-session stable seed for canvas/WebGL/audio fingerprint noise
  const seed = (() => {
    if (window.__bbSeed !== undefined) return window.__bbSeed;
    const value = Math.floor(Math.random() * 251) + 1;
    try { Object.defineProperty(window, '__bbSeed', { value, configurable: false }); } catch (e) { window.__bbSeed = value; }
    return value;
  })();

  try {
    const stamped = new WeakSet();
    const stampNoise = (canvas) => {
      if (!canvas || canvas.width <= 0 || canvas.height <= 0) return;
      if (stamped.has(canvas)) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      try {
        const x = canvas.width - 1;
        const y = canvas.height - 1;
        ctx.save();
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = 'rgba(' + seed + ',' + ((seed * 37) & 255) + ',' + ((seed * 53) & 255) + ',0.005)';
        ctx.fillRect(x, y, 1, 1);
        ctx.restore();
        stamped.add(canvas);
      } catch (e) {}
    };
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function () {
      stampNoise(this);
      return origToDataURL.apply(this, arguments);
    };
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    if (origToBlob) {
      HTMLCanvasElement.prototype.toBlob = function () {
        stampNoise(this);
        return origToBlob.apply(this, arguments);
      };
    }
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function () {
      const data = origGetImageData.apply(this, arguments);
      if (data && data.data && data.data.length >= 4) {
        const i = data.data.length - 4;
        data.data[i] = (data.data[i] + seed) & 0xff;
        data.data[i + 1] = (data.data[i + 1] + ((seed * 37) & 0xff)) & 0xff;
        data.data[i + 2] = (data.data[i + 2] + ((seed * 53) & 0xff)) & 0xff;
      }
      return data;
    };
  } catch (e) {}

  try {
    const audioMutated = new WeakSet();
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function (channel) {
      const data = origGetChannelData.call(this, channel);
      if (data && data.length >= 1 && !audioMutated.has(this)) {
        data[0] = data[0] + ((seed - 128) * 1e-7);
        audioMutated.add(this);
      }
      return data;
    };
  } catch (e) {}

  try {
    const wrapReadPixels = (proto) => {
      if (!proto || !proto.readPixels) return;
      const original = proto.readPixels;
      proto.readPixels = function () {
        original.apply(this, arguments);
        const pixels = arguments[6];
        if (pixels && pixels.length >= 4) {
          pixels[0] = (pixels[0] + seed) & 0xff;
          pixels[1] = (pixels[1] + ((seed * 37) & 0xff)) & 0xff;
          pixels[2] = (pixels[2] + ((seed * 53) & 0xff)) & 0xff;
        }
      };
    };
    wrapReadPixels(WebGLRenderingContext.prototype);
    wrapReadPixels(WebGL2RenderingContext.prototype);
  } catch (e) {}
})();
`;
function fetchJson(url) {
  return new Promise((resolve2, reject) => {
    const req = httpRequest(url, { method: "GET" }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        if ((res.statusCode ?? 500) >= 400) {
          reject(new Error(`HTTP ${res.statusCode ?? 500}: ${raw}`));
          return;
        }
        try {
          resolve2(JSON.parse(raw));
        } catch (error2) {
          reject(error2);
        }
      });
    });
    req.on("error", reject);
    req.end();
  });
}
function connectWebSocket(url) {
  return new Promise((resolve2, reject) => {
    const ws = new WebSocket(url);
    ws.once("open", () => resolve2(ws));
    ws.once("error", reject);
  });
}
function normalizeHeaders(headers) {
  if (!headers || typeof headers !== "object") return void 0;
  return Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [key, String(value)])
  );
}
var CdpConnection = class _CdpConnection {
  socket = null;
  pending = /* @__PURE__ */ new Map();
  nextId = 1;
  /** targetId -> sessionId (flat-mode) */
  sessions = /* @__PURE__ */ new Map();
  /** sessionId -> targetId */
  attachedTargets = /* @__PURE__ */ new Map();
  host;
  port;
  tabManager;
  /** Current (most recently selected) target ID. */
  currentTargetId;
  connectionPromise = null;
  _connected = false;
  /** Last connection error (for diagnostics in 503 responses). */
  lastError = null;
  /** Resolvers for commands queued before CDP is ready. */
  readyWaiters = [];
  constructor(host, port, tabManager) {
    this.host = host;
    this.port = port;
    this.tabManager = tabManager;
  }
  get connected() {
    return this._connected && this.socket !== null && this.socket.readyState === WebSocket.OPEN;
  }
  // ---------------------------------------------------------------------------
  // Connection lifecycle
  // ---------------------------------------------------------------------------
  /**
   * Connect to Chrome's browser-level WebSocket endpoint.
   * Idempotent — returns immediately if already connected.
   */
  async connect() {
    if (this._connected) return;
    if (this.connectionPromise) return this.connectionPromise;
    this.connectionPromise = this.doConnect();
    try {
      await this.connectionPromise;
      this.lastError = null;
    } catch (err) {
      this.lastError = err instanceof Error ? err.message : String(err);
      const connErr = new Error(this.lastError);
      for (const waiter of this.readyWaiters) {
        waiter.reject(connErr);
      }
      this.readyWaiters = [];
      throw err;
    } finally {
      this.connectionPromise = null;
    }
  }
  async doConnect() {
    const versionData = await fetchJson(
      `http://${this.host}:${this.port}/json/version`
    );
    const wsUrl = versionData.webSocketDebuggerUrl;
    if (typeof wsUrl !== "string" || !wsUrl) {
      throw new Error("CDP endpoint missing webSocketDebuggerUrl");
    }
    const ws = await connectWebSocket(wsUrl);
    this.socket = ws;
    this._connected = true;
    this.setupListeners(ws);
    await this.browserCommand("Target.setDiscoverTargets", { discover: true });
    const result = await this.browserCommand("Target.getTargets");
    const pages = (result.targetInfos || []).filter((t) => t.type === "page");
    for (const page of pages) {
      await this.attachAndEnable(page.targetId).catch(() => {
      });
    }
    for (const waiter of this.readyWaiters) {
      waiter.resolve();
    }
    this.readyWaiters = [];
  }
  /** Wait until CDP connection is established (for two-phase startup). */
  waitUntilReady() {
    if (this._connected) return Promise.resolve();
    if (this.lastError) return Promise.reject(new Error(this.lastError));
    return new Promise((resolve2, reject) => {
      this.readyWaiters.push({ resolve: resolve2, reject });
    });
  }
  /** Gracefully close the CDP connection. */
  disconnect() {
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
      }
    }
    this.socket = null;
    this._connected = false;
    for (const p of this.pending.values()) {
      p.reject(new Error("CDP connection closed"));
    }
    this.pending.clear();
    for (const waiter of this.readyWaiters) {
      waiter.reject(new Error("CDP connection closed before ready"));
    }
    this.readyWaiters = [];
  }
  // ---------------------------------------------------------------------------
  // WebSocket message handling
  // ---------------------------------------------------------------------------
  setupListeners(ws) {
    ws.on("message", (raw) => {
      const message = JSON.parse(raw.toString());
      if (typeof message.id === "number") {
        const p = this.pending.get(message.id);
        if (!p) return;
        this.pending.delete(message.id);
        if (message.error) {
          p.reject(
            new Error(
              `${p.method}: ${message.error.message ?? "Unknown CDP error"}`
            )
          );
        } else {
          p.resolve(message.result);
        }
        return;
      }
      if (message.method === "Target.attachedToTarget") {
        const params = message.params;
        const sessionId = params.sessionId;
        const targetInfo = params.targetInfo;
        if (typeof sessionId === "string" && typeof targetInfo?.targetId === "string") {
          const targetId = targetInfo.targetId;
          this.sessions.set(targetId, sessionId);
          this.attachedTargets.set(sessionId, targetId);
          const existingTab = this.tabManager.getTab(targetId);
          if (existingTab) {
            this.sessionCommand(targetId, "Page.enable").catch(() => {
            });
            this.sessionCommand(targetId, "Runtime.enable").catch(() => {
            });
            this.sessionCommand(targetId, "Network.enable").catch(() => {
            });
            this.sessionCommand(targetId, "DOM.enable").catch(() => {
            });
            this.sessionCommand(targetId, "Accessibility.enable").catch(() => {
            });
            if (this.tabManager.isTraced(targetId)) {
              this.enableHumanCapture(targetId).catch(() => {
              });
            }
          } else {
            this.tabManager.addTab(targetId);
          }
        }
        return;
      }
      if (message.method === "Target.detachedFromTarget") {
        const params = message.params;
        const sessionId = params.sessionId;
        if (typeof sessionId === "string") {
          const targetId = this.attachedTargets.get(sessionId);
          if (targetId) {
            this.sessions.delete(targetId);
            this.attachedTargets.delete(sessionId);
          }
        }
        return;
      }
      if (message.method === "Target.targetCreated") {
        const params = message.params;
        const targetInfo = params.targetInfo;
        if (targetInfo?.type === "page" && typeof targetInfo.targetId === "string") {
          const newTargetId = targetInfo.targetId;
          const openerId = typeof targetInfo.openerId === "string" ? targetInfo.openerId : void 0;
          this.attachAndEnable(newTargetId).catch(() => {
          });
          const session = this.tabManager.traceSession;
          if (session?.active && openerId && session.tracedTabs.has(openerId)) {
            session.tracedTabs.add(newTargetId);
            setTimeout(() => {
              this.enableHumanCapture(newTargetId).catch(() => {
              });
            }, 500);
          }
        }
        return;
      }
      if (message.method === "Target.targetDestroyed") {
        const params = message.params;
        const targetId = params.targetId;
        if (typeof targetId === "string") {
          const sessionId = this.sessions.get(targetId);
          if (sessionId) {
            this.sessions.delete(targetId);
            this.attachedTargets.delete(sessionId);
          }
          this.tabManager.removeTab(targetId);
          if (this.currentTargetId === targetId) {
            this.currentTargetId = void 0;
          }
        }
        return;
      }
      if (typeof message.sessionId === "string" && typeof message.method === "string") {
        const targetId = this.attachedTargets.get(message.sessionId);
        if (targetId) {
          this.handleSessionEvent(targetId, message).catch(() => {
          });
        }
      }
    });
    ws.on("close", () => {
      this._connected = false;
      this.socket = null;
      this.lastError = "CDP WebSocket closed unexpectedly";
      for (const p of this.pending.values()) {
        p.reject(new Error("CDP connection closed"));
      }
      this.pending.clear();
      const closeErr = new Error(this.lastError);
      for (const waiter of this.readyWaiters) {
        waiter.reject(closeErr);
      }
      this.readyWaiters = [];
    });
    ws.on("error", () => {
    });
  }
  // ---------------------------------------------------------------------------
  // Session event routing (network, console, errors, dialog)
  // ---------------------------------------------------------------------------
  async handleSessionEvent(targetId, event) {
    const method = event.method;
    const params = event.params ?? {};
    if (typeof method !== "string") return;
    const tab = this.tabManager.getTab(targetId);
    if (!tab) return;
    if (method === "Page.javascriptDialogOpening") {
      if (tab.dialogHandler) {
        await this.sessionCommand(targetId, "Page.handleJavaScriptDialog", {
          accept: tab.dialogHandler.accept,
          ...tab.dialogHandler.promptText !== void 0 ? { promptText: tab.dialogHandler.promptText } : {}
        });
      }
      return;
    }
    if (method === "Network.requestWillBeSent") {
      const requestId = typeof params.requestId === "string" ? params.requestId : void 0;
      const request3 = params.request;
      if (!requestId || !request3) return;
      const url = String(request3.url ?? "");
      const reqMethod = String(request3.method ?? "GET");
      const resourceType = String(params.type ?? "Other");
      const headers = normalizeHeaders(request3.headers);
      const body = typeof request3.postData === "string" ? request3.postData : void 0;
      tab.addNetworkRequest(requestId, {
        url,
        method: reqMethod,
        type: resourceType,
        timestamp: Math.round(Number(params.timestamp ?? Date.now()) * 1e3),
        requestHeaders: headers,
        requestBody: body
      });
      if (this.tabManager.isTraced(targetId)) {
        const now = Date.now();
        this.tabManager.tracePush({
          seq: this.tabManager.nextSeq(),
          ts: now,
          tab: tab.shortId,
          type: "request",
          requestId,
          method: reqMethod,
          url,
          resourceType,
          headers,
          body,
          triggerSeq: this.tabManager.inferTriggerSeq(now)
        });
      }
      return;
    }
    if (method === "Network.responseReceived") {
      const requestId = typeof params.requestId === "string" ? params.requestId : void 0;
      const response = params.response;
      if (!requestId || !response) return;
      const status = typeof response.status === "number" ? response.status : 0;
      const mimeType = typeof response.mimeType === "string" ? response.mimeType : void 0;
      tab.updateNetworkResponse(requestId, {
        status: typeof response.status === "number" ? response.status : void 0,
        statusText: typeof response.statusText === "string" ? response.statusText : void 0,
        responseHeaders: normalizeHeaders(response.headers),
        mimeType
      });
      if (this.tabManager.isTraced(targetId)) {
        this.tabManager.tracePush({
          seq: this.tabManager.nextSeq(),
          ts: Date.now(),
          tab: tab.shortId,
          type: "response",
          requestId,
          status,
          mimeType
        });
      }
      return;
    }
    if (method === "Network.loadingFailed") {
      const requestId = typeof params.requestId === "string" ? params.requestId : void 0;
      if (!requestId) return;
      tab.updateNetworkFailure(
        requestId,
        typeof params.errorText === "string" ? params.errorText : "Unknown error"
      );
      return;
    }
    if (method === "Runtime.consoleAPICalled") {
      const type = String(params.type ?? "log");
      const args = Array.isArray(params.args) ? params.args : [];
      const text = args.map((arg) => {
        if (typeof arg.value === "string") return arg.value;
        if (arg.value !== void 0) return String(arg.value);
        if (typeof arg.description === "string") return arg.description;
        return "";
      }).filter(Boolean).join(" ");
      const stack = params.stackTrace;
      const firstCallFrame = Array.isArray(stack?.callFrames) ? stack?.callFrames[0] : void 0;
      const consoleTypeMap = { warning: "warn" };
      const normalizedType = consoleTypeMap[type] || type;
      tab.addConsoleMessage({
        type: ["log", "info", "warn", "error", "debug"].includes(normalizedType) ? normalizedType : "log",
        text,
        timestamp: Math.round(Number(params.timestamp ?? Date.now())),
        url: typeof firstCallFrame?.url === "string" ? firstCallFrame.url : void 0,
        lineNumber: typeof firstCallFrame?.lineNumber === "number" ? firstCallFrame.lineNumber : void 0
      });
      return;
    }
    if (method === "Runtime.exceptionThrown") {
      const details = params.exceptionDetails;
      if (!details) return;
      const exception = details.exception;
      const stackTrace = details.stackTrace;
      const callFrames = Array.isArray(stackTrace?.callFrames) ? stackTrace.callFrames : [];
      tab.addJSError({
        message: typeof exception?.description === "string" ? exception.description : String(details.text ?? "JavaScript exception"),
        url: typeof details.url === "string" ? details.url : typeof callFrames[0]?.url === "string" ? String(callFrames[0].url) : void 0,
        lineNumber: typeof details.lineNumber === "number" ? details.lineNumber : void 0,
        columnNumber: typeof details.columnNumber === "number" ? details.columnNumber : void 0,
        stackTrace: callFrames.length > 0 ? callFrames.map(
          (frame) => `${String(frame.functionName ?? "<anonymous>")} (${String(frame.url ?? "")}:${String(frame.lineNumber ?? 0)}:${String(frame.columnNumber ?? 0)})`
        ).join("\n") : void 0,
        timestamp: Date.now()
      });
    }
    if (method === "Runtime.bindingCalled") {
      const name = params.name;
      const payload = params.payload;
      if (name === "__bb_trace" && typeof payload === "string" && this.tabManager.isTraced(targetId)) {
        try {
          const data = JSON.parse(payload);
          this.tabManager.tracePush({
            seq: this.tabManager.nextSeq(),
            ts: Date.now(),
            tab: tab.shortId,
            type: "action",
            source: "human",
            action: String(data.action ?? "unknown"),
            selector: typeof data.selector === "string" ? data.selector : void 0,
            text: typeof data.text === "string" ? data.text : void 0,
            role: typeof data.role === "string" ? data.role : void 0,
            tag: typeof data.tag === "string" ? data.tag : void 0,
            value: typeof data.value === "string" ? data.value : void 0,
            key: typeof data.key === "string" ? data.key : void 0
          });
        } catch {
        }
      }
    }
  }
  // ---------------------------------------------------------------------------
  // Target management
  // ---------------------------------------------------------------------------
  /** Attach to a target and enable required CDP domains. */
  async attachAndEnable(targetId) {
    if (this.sessions.has(targetId)) {
      this.tabManager.addTab(targetId);
      return this.sessions.get(targetId);
    }
    const result = await this.browserCommand(
      "Target.attachToTarget",
      { targetId, flatten: true }
    );
    this.sessions.set(targetId, result.sessionId);
    this.attachedTargets.set(result.sessionId, targetId);
    this.tabManager.addTab(targetId);
    await this.sessionCommand(targetId, "Page.enable").catch(() => {
    });
    await this.sessionCommand(targetId, "Runtime.enable").catch(() => {
    });
    await this.sessionCommand(targetId, "Network.enable").catch(() => {
    });
    await this.sessionCommand(targetId, "DOM.enable").catch(() => {
    });
    await this.sessionCommand(targetId, "Accessibility.enable").catch(() => {
    });
    {
      const versionInfo = await this.browserCommand(
        "Browser.getVersion"
      ).catch(() => null);
      const product = String(versionInfo?.product ?? "");
      const isHeadlessShell = false;
      if (isHeadlessShell) {
        const versionMatch = product.match(/(\d+\.\d+\.\d+\.\d+)/);
        const fullVersion = versionMatch ? versionMatch[1] : "149.0.7827.22";
        const majorVersion = fullVersion.split(".")[0];
        const cleanUA = `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${fullVersion} Safari/537.36`;
        await this.sessionCommand(targetId, "Emulation.setUserAgentOverride", {
          userAgent: cleanUA,
          acceptLanguage: "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
          platform: "MacIntel",
          userAgentMetadata: {
            brands: [
              { brand: "Chromium", version: majorVersion },
              { brand: "Google Chrome", version: majorVersion },
              { brand: "Not.A/Brand", version: "24" }
            ],
            fullVersionList: [
              { brand: "Chromium", version: fullVersion },
              { brand: "Google Chrome", version: fullVersion },
              { brand: "Not.A/Brand", version: "24.0.0.0" }
            ],
            platform: "macOS",
            platformVersion: "10.15.7",
            architecture: "x86",
            bitness: "64",
            model: "",
            mobile: false,
            wow64: false
          }
        }).catch(() => {
        });
        await this.sessionCommand(targetId, "Emulation.setDeviceMetricsOverride", {
          width: 1920,
          height: 1080,
          deviceScaleFactor: 1,
          mobile: false,
          screenWidth: 1920,
          screenHeight: 1080
        }).catch(() => {
        });
        await this.sessionCommand(targetId, "Page.addScriptToEvaluateOnNewDocument", {
          source: STEALTH_SCRIPT
        }).catch(() => {
        });
        await this.evaluate(targetId, STEALTH_SCRIPT, false).catch(() => {
        });
      }
    }
    return result.sessionId;
  }
  // ---------------------------------------------------------------------------
  // Human action capture for trace
  // ---------------------------------------------------------------------------
  static HUMAN_CAPTURE_SCRIPT = `(function() {
    if (window.__bb_trace_installed) return;
    window.__bb_trace_installed = true;
    function report(data) {
      try { window.__bb_trace(JSON.stringify(data)); } catch(e) {}
    }
    function meta(el) {
      if (!el || !el.tagName) return {};
      return {
        tag: el.tagName,
        text: (el.innerText || '').slice(0, 80).trim(),
        role: el.getAttribute ? el.getAttribute('role') : undefined,
        selector: el.id ? '#' + el.id
          : el.className && typeof el.className === 'string' ? el.tagName.toLowerCase() + '.' + el.className.split(' ')[0]
          : el.tagName.toLowerCase(),
      };
    }
    document.addEventListener('click', function(e) {
      report({ action: 'click', ...meta(e.target), x: e.clientX, y: e.clientY });
    }, true);
    document.addEventListener('input', function(e) {
      report({ action: 'input', ...meta(e.target), value: e.target.value });
    }, true);
    document.addEventListener('keydown', function(e) {
      if (['Enter','Tab','Escape','Backspace','Delete'].indexOf(e.key) >= 0 || e.ctrlKey || e.metaKey) {
        report({ action: 'press', key: e.key, ...meta(e.target) });
      }
    }, true);
    document.addEventListener('submit', function(e) {
      report({ action: 'submit', ...meta(e.target) });
    }, true);
  })();`;
  /** Inject human action capture listeners into a tab via CDP binding. */
  async enableHumanCapture(targetId) {
    try {
      await this.sessionCommand(targetId, "Runtime.addBinding", { name: "__bb_trace" });
    } catch {
    }
    await this.sessionCommand(targetId, "Page.addScriptToEvaluateOnNewDocument", {
      source: _CdpConnection.HUMAN_CAPTURE_SCRIPT
    }).catch(() => {
    });
    await this.evaluate(targetId, _CdpConnection.HUMAN_CAPTURE_SCRIPT, false).catch(() => {
    });
  }
  /** Get all targets via CDP Target.getTargets. */
  async getTargets() {
    const result = await this.browserCommand("Target.getTargets");
    return (result.targetInfos || []).map((t) => ({
      id: t.targetId,
      type: t.type,
      title: t.title,
      url: t.url
    }));
  }
  /**
   * Ensure we have a valid page target and return it. Supports resolution by:
   *   - short ID string
   *   - full target ID string
   *   - numeric index
   *   - undefined (use currentTargetId or first page)
   */
  async ensurePageTarget(tabRef) {
    const targets = (await this.getTargets()).filter((t) => t.type === "page");
    if (targets.length === 0) throw new Error("No page target found");
    let target;
    if (typeof tabRef === "string") {
      const resolvedTargetId = this.tabManager.resolveShortId(tabRef);
      if (resolvedTargetId) {
        target = targets.find((t) => t.id === resolvedTargetId);
      }
      if (!target) {
        target = targets.find((t) => t.id === tabRef);
      }
      if (!target) {
        const num = Number(tabRef);
        if (!Number.isNaN(num)) {
          target = targets[num];
        }
      }
    } else if (typeof tabRef === "number") {
      target = targets[tabRef];
    } else if (this.currentTargetId) {
      target = targets.find((t) => t.id === this.currentTargetId);
    }
    if (typeof tabRef === "string" && !target) {
      throw new Error(`Tab not found: ${tabRef}`);
    }
    target ??= targets[0];
    this.currentTargetId = target.id;
    await this.attachAndEnable(target.id);
    return target;
  }
  /** Check if a session exists for a given targetId. */
  hasSession(targetId) {
    return this.sessions.has(targetId);
  }
  // ---------------------------------------------------------------------------
  // CDP command sending
  // ---------------------------------------------------------------------------
  /** Send a browser-level CDP command. */
  async browserCommand(method, params = {}) {
    if (!this.socket) throw new Error("CDP not connected");
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve2, reject) => {
      this.pending.set(id, {
        resolve: resolve2,
        reject,
        method
      });
      this.socket.send(payload);
    });
  }
  /** Send a session-level CDP command (flat protocol). */
  async sessionCommand(targetId, method, params = {}) {
    if (!this.socket) throw new Error("CDP not connected");
    const sessionId = this.sessions.get(targetId) ?? await this.attachAndEnable(targetId);
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params, sessionId });
    return new Promise((resolve2, reject) => {
      const check = (raw) => {
        const msg = JSON.parse(raw.toString());
        if (msg.id === id && msg.sessionId === sessionId) {
          this.socket.off("message", check);
          if (msg.error) {
            reject(
              new Error(
                `${method}: ${msg.error.message ?? "Unknown CDP error"}`
              )
            );
          } else {
            resolve2(msg.result);
          }
        }
      };
      this.socket.on("message", check);
      this.socket.send(payload);
    });
  }
  /**
   * Send a page-scoped command. If the tab has an active iframe,
   * the frameId is injected into the params.
   */
  async pageCommand(targetId, method, params = {}) {
    const tab = this.tabManager.getTab(targetId);
    const frameId = tab?.activeFrameId;
    return this.sessionCommand(
      targetId,
      method,
      frameId ? { ...params, frameId } : params
    );
  }
  /**
   * Evaluate JavaScript expression on a target.
   */
  async evaluate(targetId, expression, returnByValue = true) {
    const result = await this.sessionCommand(targetId, "Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue
    });
    if (result.exceptionDetails) {
      throw new Error(
        result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate failed"
      );
    }
    return result.result.value ?? result.result;
  }
};

// packages/daemon/src/ring-buffer.ts
var RingBuffer = class {
  items;
  head = 0;
  // next write position
  count = 0;
  capacity;
  constructor(capacity) {
    if (capacity < 1) throw new Error("RingBuffer capacity must be >= 1");
    this.capacity = capacity;
    this.items = new Array(capacity);
  }
  /** Number of elements currently stored. */
  get size() {
    return this.count;
  }
  /** Push a new element, evicting the oldest if at capacity. */
  push(item) {
    this.items[this.head] = item;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) {
      this.count++;
    }
  }
  /** Return all stored elements in insertion order (oldest first). */
  toArray() {
    if (this.count === 0) return [];
    const result = new Array(this.count);
    const start = this.count < this.capacity ? 0 : this.head;
    for (let i = 0; i < this.count; i++) {
      result[i] = this.items[(start + i) % this.capacity];
    }
    return result;
  }
  /** Remove all elements. */
  clear() {
    this.items.fill(void 0);
    this.head = 0;
    this.count = 0;
  }
};

// packages/daemon/src/tab-state.ts
var NETWORK_CAPACITY = 500;
var CONSOLE_CAPACITY = 200;
var ERRORS_CAPACITY = 100;
var TabState = class {
  constructor(targetId, shortId, nextSeq) {
    this.nextSeq = nextSeq;
    this.targetId = targetId;
    this.shortId = shortId;
  }
  targetId;
  shortId;
  networkRequests = new RingBuffer(NETWORK_CAPACITY);
  consoleMessages = new RingBuffer(CONSOLE_CAPACITY);
  jsErrors = new RingBuffer(ERRORS_CAPACITY);
  /** Lookup in-flight network requests by requestId for response/failure updates. */
  networkByRequestId = /* @__PURE__ */ new Map();
  /** seq of the last user-initiated action on this tab. */
  lastActionSeq = 0;
  /** Element refs from the most recent snapshot. */
  refs = {};
  /** Active frame ID for iframe navigation, null = main frame. */
  activeFrameId = null;
  /** Dialog auto-handler config. */
  dialogHandler = null;
  /** Reference to the manager (set after construction) */
  manager;
  // --------------- Action seq ---------------
  /** Increment global seq and record it as this tab's last action.
   *  When trace is active, pushes a TraceAction to the timeline. */
  recordAction(detail) {
    const seq = this.nextSeq();
    this.lastActionSeq = seq;
    const session = this.manager?.traceSession;
    if (session?.active && session.tracedTabs.has(this.targetId) && detail) {
      const entry = {
        seq,
        ts: Date.now(),
        tab: this.shortId,
        type: "action",
        source: "command",
        action: detail.action,
        ref: detail.ref,
        value: detail.value,
        key: detail.key,
        direction: detail.direction,
        url: detail.url
      };
      session.timeline.push(entry);
    }
    return seq;
  }
  // --------------- Network events ---------------
  addNetworkRequest(requestId, info) {
    const seq = this.nextSeq();
    const entry = { ...info, requestId, seq };
    this.networkRequests.push(entry);
    this.networkByRequestId.set(requestId, entry);
  }
  updateNetworkResponse(requestId, data) {
    const existing = this.networkByRequestId.get(requestId);
    if (!existing) return;
    if (data.status !== void 0) existing.status = data.status;
    if (data.statusText !== void 0) existing.statusText = data.statusText;
    if (data.responseHeaders !== void 0) existing.responseHeaders = data.responseHeaders;
    if (data.mimeType !== void 0) existing.mimeType = data.mimeType;
  }
  updateNetworkFailure(requestId, reason) {
    const existing = this.networkByRequestId.get(requestId);
    if (!existing) return;
    existing.failed = true;
    existing.failureReason = reason;
  }
  // --------------- Console events ---------------
  addConsoleMessage(info) {
    const seq = this.nextSeq();
    this.consoleMessages.push({ ...info, seq });
  }
  // --------------- JS Error events ---------------
  addJSError(info) {
    const seq = this.nextSeq();
    this.jsErrors.push({ ...info, seq });
  }
  // --------------- Query helpers ---------------
  getNetworkRequests(options) {
    let items = this.networkRequests.toArray();
    if (options?.since !== void 0) {
      const threshold = options.since === "last_action" ? this.lastActionSeq : options.since;
      items = items.filter((item) => item.seq > threshold);
    }
    if (options?.filter) {
      const f = options.filter;
      items = items.filter((item) => item.url.includes(f));
    }
    if (options?.method) {
      const m = options.method.toUpperCase();
      items = items.filter((item) => item.method === m);
    }
    if (options?.status) {
      const s = options.status;
      if (s === "4xx") {
        items = items.filter((item) => item.status !== void 0 && item.status >= 400 && item.status < 500);
      } else if (s === "5xx") {
        items = items.filter((item) => item.status !== void 0 && item.status >= 500 && item.status < 600);
      } else {
        const code = Number(s);
        if (!Number.isNaN(code)) {
          items = items.filter((item) => item.status === code);
        }
      }
    }
    if (options?.limit !== void 0 && options.limit > 0 && items.length > options.limit) {
      items = items.slice(-options.limit);
    }
    const sinceThreshold = options?.since !== void 0 ? options.since === "last_action" ? this.lastActionSeq : options.since : 0;
    const cursor = items.length > 0 ? Math.max(...items.map((i) => i.seq)) : sinceThreshold;
    return { items, cursor };
  }
  getConsoleMessages(options) {
    let items = this.consoleMessages.toArray();
    if (options?.since !== void 0) {
      const threshold = options.since === "last_action" ? this.lastActionSeq : options.since;
      items = items.filter((item) => item.seq > threshold);
    }
    if (options?.filter) {
      const f = options.filter;
      items = items.filter((item) => item.text.includes(f));
    }
    if (options?.limit !== void 0 && options.limit > 0 && items.length > options.limit) {
      items = items.slice(-options.limit);
    }
    const sinceThreshold = options?.since !== void 0 ? options.since === "last_action" ? this.lastActionSeq : options.since : 0;
    const cursor = items.length > 0 ? Math.max(...items.map((i) => i.seq)) : sinceThreshold;
    return { items, cursor };
  }
  getJSErrors(options) {
    let items = this.jsErrors.toArray();
    if (options?.since !== void 0) {
      const threshold = options.since === "last_action" ? this.lastActionSeq : options.since;
      items = items.filter((item) => item.seq > threshold);
    }
    if (options?.filter) {
      const f = options.filter;
      items = items.filter(
        (item) => item.message.includes(f) || (item.url?.includes(f) ?? false)
      );
    }
    if (options?.limit !== void 0 && options.limit > 0 && items.length > options.limit) {
      items = items.slice(-options.limit);
    }
    const sinceThreshold = options?.since !== void 0 ? options.since === "last_action" ? this.lastActionSeq : options.since : 0;
    const cursor = items.length > 0 ? Math.max(...items.map((i) => i.seq)) : sinceThreshold;
    return { items, cursor };
  }
  // --------------- Clear helpers ---------------
  clearNetwork() {
    this.networkRequests.clear();
    this.networkByRequestId.clear();
  }
  clearConsole() {
    this.consoleMessages.clear();
  }
  clearErrors() {
    this.jsErrors.clear();
  }
};
var TabStateManager = class {
  seq = 0;
  tabs = /* @__PURE__ */ new Map();
  // targetId -> TabState
  shortToTarget = /* @__PURE__ */ new Map();
  // shortId -> targetId
  targetToShort = /* @__PURE__ */ new Map();
  // targetId -> shortId
  /** Active trace session (at most one at a time) */
  traceSession = null;
  /** Generate a globally unique short ID for a target. */
  generateShortId(targetId) {
    for (let len = 4; len <= targetId.length; len++) {
      const candidate = targetId.slice(-len).toLowerCase();
      if (!this.shortToTarget.has(candidate)) {
        return candidate;
      }
    }
    return targetId.toLowerCase();
  }
  /** Get next seq (globally monotonic). */
  nextSeq() {
    return ++this.seq;
  }
  /** Get current seq without incrementing. */
  currentSeq() {
    return this.seq;
  }
  /** Register a new tab. Returns the TabState. */
  addTab(targetId) {
    const existing = this.tabs.get(targetId);
    if (existing) return existing;
    const shortId = this.generateShortId(targetId);
    const tab = new TabState(targetId, shortId, () => this.nextSeq());
    tab.manager = this;
    this.tabs.set(targetId, tab);
    this.shortToTarget.set(shortId, targetId);
    this.targetToShort.set(targetId, shortId);
    return tab;
  }
  /** Remove a tab (on targetDestroyed / detach). */
  removeTab(targetId) {
    const tab = this.tabs.get(targetId);
    if (!tab) return;
    this.shortToTarget.delete(tab.shortId);
    this.targetToShort.delete(targetId);
    this.tabs.delete(targetId);
  }
  /** Get tab by targetId. */
  getTab(targetId) {
    return this.tabs.get(targetId);
  }
  /** Resolve a short ID to a targetId. */
  resolveShortId(shortId) {
    return this.shortToTarget.get(shortId);
  }
  /** Get the short ID for a targetId. */
  getShortId(targetId) {
    return this.targetToShort.get(targetId);
  }
  /** Get all active tabs. */
  allTabs() {
    return Array.from(this.tabs.values());
  }
  /** Get tab count. */
  get tabCount() {
    return this.tabs.size;
  }
  // --------------- Trace session helpers ---------------
  /** Start a new trace session. If a targetId is given, only trace that tab
   *  (plus any tabs it opens). If omitted, trace all current and future tabs. */
  traceStart(targetId) {
    const tracedTabs = /* @__PURE__ */ new Set();
    if (targetId) {
      tracedTabs.add(targetId);
    } else {
      for (const tid of this.tabs.keys()) tracedTabs.add(tid);
    }
    this.traceSession = {
      active: true,
      tracedTabs,
      timeline: [],
      startSeq: this.seq
    };
    return this.traceSession;
  }
  /** Stop the current trace session. Data is preserved for querying. */
  traceStop() {
    if (this.traceSession) {
      this.traceSession.active = false;
    }
  }
  /** Push a trace entry (used by cdp-connection for network/navigation events). */
  tracePush(entry) {
    this.traceSession?.timeline.push(entry);
  }
  /** Check if a target is being traced. */
  isTraced(targetId) {
    const s = this.traceSession;
    return !!s?.active && s.tracedTabs.has(targetId);
  }
  /** Get shortId for a tab being traced, for building trace entries. */
  getTabShortId(targetId) {
    return this.tabs.get(targetId)?.shortId;
  }
  /** Infer which action likely triggered a network request (heuristic). */
  inferTriggerSeq(requestTs) {
    const tl = this.traceSession?.timeline;
    if (!tl) return void 0;
    for (let i = tl.length - 1; i >= 0; i--) {
      const e = tl[i];
      if (e.type !== "action") continue;
      if (requestTs - e.ts < 2e3) return e.seq;
      break;
    }
    return void 0;
  }
};

// packages/daemon/src/hub-bridge.ts
import { readFileSync as readFileSync3, existsSync as existsSync2, mkdirSync as mkdirSync2, writeFileSync as writeFileSync2, chmodSync } from "fs";
import { readFile as readFileAsync } from "fs/promises";
import { pipeline } from "stream/promises";
import { createWriteStream } from "fs";
import { join as join2, dirname, resolve, extname } from "path";
import { spawn } from "child_process";
import { fileURLToPath as fileURLToPath2 } from "url";
import { createHmac } from "crypto";
import { homedir as homedir2, platform, arch } from "os";
import { statSync, readdirSync as readdirSyncNative, unlinkSync } from "fs";

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/is-message.js
function isMessage(arg, schema) {
  const isMessage2 = arg !== null && typeof arg == "object" && "$typeName" in arg && typeof arg.$typeName == "string";
  if (!isMessage2) {
    return false;
  }
  if (schema === void 0) {
    return true;
  }
  return schema.typeName === arg.$typeName;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/descriptors.js
var ScalarType;
(function(ScalarType2) {
  ScalarType2[ScalarType2["DOUBLE"] = 1] = "DOUBLE";
  ScalarType2[ScalarType2["FLOAT"] = 2] = "FLOAT";
  ScalarType2[ScalarType2["INT64"] = 3] = "INT64";
  ScalarType2[ScalarType2["UINT64"] = 4] = "UINT64";
  ScalarType2[ScalarType2["INT32"] = 5] = "INT32";
  ScalarType2[ScalarType2["FIXED64"] = 6] = "FIXED64";
  ScalarType2[ScalarType2["FIXED32"] = 7] = "FIXED32";
  ScalarType2[ScalarType2["BOOL"] = 8] = "BOOL";
  ScalarType2[ScalarType2["STRING"] = 9] = "STRING";
  ScalarType2[ScalarType2["BYTES"] = 12] = "BYTES";
  ScalarType2[ScalarType2["UINT32"] = 13] = "UINT32";
  ScalarType2[ScalarType2["SFIXED32"] = 15] = "SFIXED32";
  ScalarType2[ScalarType2["SFIXED64"] = 16] = "SFIXED64";
  ScalarType2[ScalarType2["SINT32"] = 17] = "SINT32";
  ScalarType2[ScalarType2["SINT64"] = 18] = "SINT64";
})(ScalarType || (ScalarType = {}));

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wire/varint.js
function varint64read() {
  let lowBits = 0;
  let highBits = 0;
  for (let shift = 0; shift < 28; shift += 7) {
    let b = this.buf[this.pos++];
    lowBits |= (b & 127) << shift;
    if ((b & 128) == 0) {
      this.assertBounds();
      return [lowBits, highBits];
    }
  }
  let middleByte = this.buf[this.pos++];
  lowBits |= (middleByte & 15) << 28;
  highBits = (middleByte & 112) >> 4;
  if ((middleByte & 128) == 0) {
    this.assertBounds();
    return [lowBits, highBits];
  }
  for (let shift = 3; shift <= 31; shift += 7) {
    let b = this.buf[this.pos++];
    highBits |= (b & 127) << shift;
    if ((b & 128) == 0) {
      this.assertBounds();
      return [lowBits, highBits];
    }
  }
  throw new Error("invalid varint");
}
function varint64write(lo, hi, bytes) {
  for (let i = 0; i < 28; i = i + 7) {
    const shift = lo >>> i;
    const hasNext = !(shift >>> 7 == 0 && hi == 0);
    const byte = (hasNext ? shift | 128 : shift) & 255;
    bytes.push(byte);
    if (!hasNext) {
      return;
    }
  }
  const splitBits = lo >>> 28 & 15 | (hi & 7) << 4;
  const hasMoreBits = !(hi >> 3 == 0);
  bytes.push((hasMoreBits ? splitBits | 128 : splitBits) & 255);
  if (!hasMoreBits) {
    return;
  }
  for (let i = 3; i < 31; i = i + 7) {
    const shift = hi >>> i;
    const hasNext = !(shift >>> 7 == 0);
    const byte = (hasNext ? shift | 128 : shift) & 255;
    bytes.push(byte);
    if (!hasNext) {
      return;
    }
  }
  bytes.push(hi >>> 31 & 1);
}
var TWO_PWR_32_DBL = 4294967296;
function int64FromString(dec) {
  const minus = dec[0] === "-";
  if (minus) {
    dec = dec.slice(1);
  }
  const base = 1e6;
  let lowBits = 0;
  let highBits = 0;
  function add1e6digit(begin, end) {
    const digit1e6 = Number(dec.slice(begin, end));
    highBits *= base;
    lowBits = lowBits * base + digit1e6;
    if (lowBits >= TWO_PWR_32_DBL) {
      highBits = highBits + (lowBits / TWO_PWR_32_DBL | 0);
      lowBits = lowBits % TWO_PWR_32_DBL;
    }
  }
  add1e6digit(-24, -18);
  add1e6digit(-18, -12);
  add1e6digit(-12, -6);
  add1e6digit(-6);
  return minus ? negate(lowBits, highBits) : newBits(lowBits, highBits);
}
function int64ToString(lo, hi) {
  let bits = newBits(lo, hi);
  const negative = bits.hi & 2147483648;
  if (negative) {
    bits = negate(bits.lo, bits.hi);
  }
  const result = uInt64ToString(bits.lo, bits.hi);
  return negative ? "-" + result : result;
}
function uInt64ToString(lo, hi) {
  ({ lo, hi } = toUnsigned(lo, hi));
  if (hi <= 2097151) {
    return String(TWO_PWR_32_DBL * hi + lo);
  }
  const low = lo & 16777215;
  const mid = (lo >>> 24 | hi << 8) & 16777215;
  const high = hi >> 16 & 65535;
  let digitA = low + mid * 6777216 + high * 6710656;
  let digitB = mid + high * 8147497;
  let digitC = high * 2;
  const base = 1e7;
  if (digitA >= base) {
    digitB += Math.floor(digitA / base);
    digitA %= base;
  }
  if (digitB >= base) {
    digitC += Math.floor(digitB / base);
    digitB %= base;
  }
  return digitC.toString() + decimalFrom1e7WithLeadingZeros(digitB) + decimalFrom1e7WithLeadingZeros(digitA);
}
function toUnsigned(lo, hi) {
  return { lo: lo >>> 0, hi: hi >>> 0 };
}
function newBits(lo, hi) {
  return { lo: lo | 0, hi: hi | 0 };
}
function negate(lowBits, highBits) {
  highBits = ~highBits;
  if (lowBits) {
    lowBits = ~lowBits + 1;
  } else {
    highBits += 1;
  }
  return newBits(lowBits, highBits);
}
var decimalFrom1e7WithLeadingZeros = (digit1e7) => {
  const partial = String(digit1e7);
  return "0000000".slice(partial.length) + partial;
};
function varint32write(value, bytes) {
  if (value >= 0) {
    while (value > 127) {
      bytes.push(value & 127 | 128);
      value = value >>> 7;
    }
    bytes.push(value);
  } else {
    for (let i = 0; i < 9; i++) {
      bytes.push(value & 127 | 128);
      value = value >> 7;
    }
    bytes.push(1);
  }
}
function varint32read() {
  let b = this.buf[this.pos++];
  let result = b & 127;
  if ((b & 128) == 0) {
    this.assertBounds();
    return result;
  }
  b = this.buf[this.pos++];
  result |= (b & 127) << 7;
  if ((b & 128) == 0) {
    this.assertBounds();
    return result;
  }
  b = this.buf[this.pos++];
  result |= (b & 127) << 14;
  if ((b & 128) == 0) {
    this.assertBounds();
    return result;
  }
  b = this.buf[this.pos++];
  result |= (b & 127) << 21;
  if ((b & 128) == 0) {
    this.assertBounds();
    return result;
  }
  b = this.buf[this.pos++];
  result |= (b & 15) << 28;
  for (let readBytes = 5; (b & 128) !== 0 && readBytes < 10; readBytes++)
    b = this.buf[this.pos++];
  if ((b & 128) != 0)
    throw new Error("invalid varint");
  this.assertBounds();
  return result >>> 0;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/proto-int64.js
var protoInt64 = /* @__PURE__ */ makeInt64Support();
function makeInt64Support() {
  const dv = new DataView(new ArrayBuffer(8));
  const ok2 = typeof BigInt === "function" && typeof dv.getBigInt64 === "function" && typeof dv.getBigUint64 === "function" && typeof dv.setBigInt64 === "function" && typeof dv.setBigUint64 === "function" && (!!globalThis.Deno || typeof process != "object" || typeof process.env != "object" || process.env.BUF_BIGINT_DISABLE !== "1");
  if (ok2) {
    const MIN = BigInt("-9223372036854775808");
    const MAX = BigInt("9223372036854775807");
    const UMIN = BigInt("0");
    const UMAX = BigInt("18446744073709551615");
    return {
      zero: BigInt(0),
      supported: true,
      parse(value) {
        const bi = typeof value == "bigint" ? value : BigInt(value);
        if (bi > MAX || bi < MIN) {
          throw new Error(`invalid int64: ${value}`);
        }
        return bi;
      },
      uParse(value) {
        const bi = typeof value == "bigint" ? value : BigInt(value);
        if (bi > UMAX || bi < UMIN) {
          throw new Error(`invalid uint64: ${value}`);
        }
        return bi;
      },
      enc(value) {
        dv.setBigInt64(0, this.parse(value), true);
        return {
          lo: dv.getInt32(0, true),
          hi: dv.getInt32(4, true)
        };
      },
      uEnc(value) {
        dv.setBigInt64(0, this.uParse(value), true);
        return {
          lo: dv.getInt32(0, true),
          hi: dv.getInt32(4, true)
        };
      },
      dec(lo, hi) {
        dv.setInt32(0, lo, true);
        dv.setInt32(4, hi, true);
        return dv.getBigInt64(0, true);
      },
      uDec(lo, hi) {
        dv.setInt32(0, lo, true);
        dv.setInt32(4, hi, true);
        return dv.getBigUint64(0, true);
      }
    };
  }
  return {
    zero: "0",
    supported: false,
    parse(value) {
      if (typeof value != "string") {
        value = value.toString();
      }
      assertInt64String(value);
      return value;
    },
    uParse(value) {
      if (typeof value != "string") {
        value = value.toString();
      }
      assertUInt64String(value);
      return value;
    },
    enc(value) {
      if (typeof value != "string") {
        value = value.toString();
      }
      assertInt64String(value);
      return int64FromString(value);
    },
    uEnc(value) {
      if (typeof value != "string") {
        value = value.toString();
      }
      assertUInt64String(value);
      return int64FromString(value);
    },
    dec(lo, hi) {
      return int64ToString(lo, hi);
    },
    uDec(lo, hi) {
      return uInt64ToString(lo, hi);
    }
  };
}
function assertInt64String(value) {
  if (!/^-?[0-9]+$/.test(value)) {
    throw new Error("invalid int64: " + value);
  }
}
function assertUInt64String(value) {
  if (!/^[0-9]+$/.test(value)) {
    throw new Error("invalid uint64: " + value);
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/scalar.js
function scalarZeroValue(type, longAsString) {
  switch (type) {
    case ScalarType.STRING:
      return "";
    case ScalarType.BOOL:
      return false;
    case ScalarType.DOUBLE:
    case ScalarType.FLOAT:
      return 0;
    case ScalarType.INT64:
    case ScalarType.UINT64:
    case ScalarType.SFIXED64:
    case ScalarType.FIXED64:
    case ScalarType.SINT64:
      return longAsString ? "0" : protoInt64.zero;
    case ScalarType.BYTES:
      return new Uint8Array(0);
    default:
      return 0;
  }
}
function isScalarZeroValue(type, value) {
  switch (type) {
    case ScalarType.BOOL:
      return value === false;
    case ScalarType.STRING:
      return value === "";
    case ScalarType.BYTES:
      return value instanceof Uint8Array && !value.byteLength;
    default:
      return value == 0;
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/unsafe.js
var IMPLICIT = 2;
var unsafeLocal = /* @__PURE__ */ Symbol.for("reflect unsafe local");
function unsafeOneofCase(target, oneof) {
  const c = target[oneof.localName].case;
  if (c === void 0) {
    return c;
  }
  return oneof.fields.find((f) => f.localName === c);
}
function unsafeIsSet(target, field) {
  const name = field.localName;
  if (field.oneof) {
    return target[field.oneof.localName].case === name;
  }
  if (field.presence != IMPLICIT) {
    return target[name] !== void 0 && Object.prototype.hasOwnProperty.call(target, name);
  }
  switch (field.fieldKind) {
    case "list":
      return target[name].length > 0;
    case "map":
      return Object.keys(target[name]).length > 0;
    case "scalar":
      return !isScalarZeroValue(field.scalar, target[name]);
    case "enum":
      return target[name] !== field.enum.values[0].number;
  }
  throw new Error("message field with implicit presence");
}
function unsafeIsSetExplicit(target, localName) {
  return Object.prototype.hasOwnProperty.call(target, localName) && target[localName] !== void 0;
}
function unsafeGet(target, field) {
  if (field.oneof) {
    const oneof = target[field.oneof.localName];
    if (oneof.case === field.localName) {
      return oneof.value;
    }
    return void 0;
  }
  return target[field.localName];
}
function unsafeSet(target, field, value) {
  if (field.oneof) {
    target[field.oneof.localName] = {
      case: field.localName,
      value
    };
  } else {
    target[field.localName] = value;
  }
}
function unsafeClear(target, field) {
  const name = field.localName;
  if (field.oneof) {
    const oneofLocalName = field.oneof.localName;
    if (target[oneofLocalName].case === name) {
      target[oneofLocalName] = { case: void 0 };
    }
  } else if (field.presence != IMPLICIT) {
    delete target[name];
  } else {
    switch (field.fieldKind) {
      case "map":
        target[name] = {};
        break;
      case "list":
        target[name] = [];
        break;
      case "enum":
        target[name] = field.enum.values[0].number;
        break;
      case "scalar":
        target[name] = scalarZeroValue(field.scalar, field.longAsString);
        break;
    }
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/guard.js
function isObject(arg) {
  return arg !== null && typeof arg == "object" && !Array.isArray(arg);
}
function isReflectList(arg, field) {
  var _a, _b, _c, _d;
  if (isObject(arg) && unsafeLocal in arg && "add" in arg && "field" in arg && typeof arg.field == "function") {
    if (field !== void 0) {
      const a = field;
      const b = arg.field();
      return a.listKind == b.listKind && a.scalar === b.scalar && ((_a = a.message) === null || _a === void 0 ? void 0 : _a.typeName) === ((_b = b.message) === null || _b === void 0 ? void 0 : _b.typeName) && ((_c = a.enum) === null || _c === void 0 ? void 0 : _c.typeName) === ((_d = b.enum) === null || _d === void 0 ? void 0 : _d.typeName);
    }
    return true;
  }
  return false;
}
function isReflectMap(arg, field) {
  var _a, _b, _c, _d;
  if (isObject(arg) && unsafeLocal in arg && "has" in arg && "field" in arg && typeof arg.field == "function") {
    if (field !== void 0) {
      const a = field, b = arg.field();
      return a.mapKey === b.mapKey && a.mapKind == b.mapKind && a.scalar === b.scalar && ((_a = a.message) === null || _a === void 0 ? void 0 : _a.typeName) === ((_b = b.message) === null || _b === void 0 ? void 0 : _b.typeName) && ((_c = a.enum) === null || _c === void 0 ? void 0 : _c.typeName) === ((_d = b.enum) === null || _d === void 0 ? void 0 : _d.typeName);
    }
    return true;
  }
  return false;
}
function isReflectMessage(arg, messageDesc2) {
  return isObject(arg) && unsafeLocal in arg && "desc" in arg && isObject(arg.desc) && arg.desc.kind === "message" && (messageDesc2 === void 0 || arg.desc.typeName == messageDesc2.typeName);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wkt/wrappers.js
function isWrapper(arg) {
  return isWrapperTypeName(arg.$typeName);
}
function isWrapperDesc(messageDesc2) {
  const f = messageDesc2.fields[0];
  return isWrapperTypeName(messageDesc2.typeName) && f !== void 0 && f.fieldKind == "scalar" && f.name == "value" && f.number == 1;
}
function isWrapperTypeName(name) {
  return name.startsWith("google.protobuf.") && [
    "DoubleValue",
    "FloatValue",
    "Int64Value",
    "UInt64Value",
    "Int32Value",
    "UInt32Value",
    "BoolValue",
    "StringValue",
    "BytesValue"
  ].includes(name.substring(16));
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/create.js
var EDITION_PROTO3 = 999;
var EDITION_PROTO2 = 998;
var IMPLICIT2 = 2;
function create(schema, init) {
  if (isMessage(init, schema)) {
    return init;
  }
  const message = createZeroMessage(schema);
  if (init !== void 0) {
    initMessage(schema, message, init);
  }
  return message;
}
function initMessage(messageDesc2, message, init) {
  for (const member of messageDesc2.members) {
    let value = init[member.localName];
    if (value == null) {
      continue;
    }
    let field;
    if (member.kind == "oneof") {
      const oneofField = unsafeOneofCase(init, member);
      if (!oneofField) {
        continue;
      }
      field = oneofField;
      value = unsafeGet(init, oneofField);
    } else {
      field = member;
    }
    switch (field.fieldKind) {
      case "message":
        value = toMessage(field, value);
        break;
      case "scalar":
        value = initScalar(field, value);
        break;
      case "list":
        value = initList(field, value);
        break;
      case "map":
        value = initMap(field, value);
        break;
    }
    unsafeSet(message, field, value);
  }
  return message;
}
function initScalar(field, value) {
  if (field.scalar == ScalarType.BYTES) {
    return toU8Arr(value);
  }
  return value;
}
function initMap(field, value) {
  if (isObject(value)) {
    if (field.scalar == ScalarType.BYTES) {
      return convertObjectValues(value, toU8Arr);
    }
    if (field.mapKind == "message") {
      return convertObjectValues(value, (val) => toMessage(field, val));
    }
  }
  return value;
}
function initList(field, value) {
  if (Array.isArray(value)) {
    if (field.scalar == ScalarType.BYTES) {
      return value.map(toU8Arr);
    }
    if (field.listKind == "message") {
      return value.map((item) => toMessage(field, item));
    }
  }
  return value;
}
function toMessage(field, value) {
  if (field.fieldKind == "message" && !field.oneof && isWrapperDesc(field.message)) {
    return initScalar(field.message.fields[0], value);
  }
  if (isObject(value)) {
    if (field.message.typeName == "google.protobuf.Struct" && field.parent.typeName !== "google.protobuf.Value") {
      return value;
    }
    if (!isMessage(value, field.message)) {
      return create(field.message, value);
    }
  }
  return value;
}
function toU8Arr(value) {
  return Array.isArray(value) ? new Uint8Array(value) : value;
}
function convertObjectValues(obj, fn) {
  const ret = {};
  for (const entry of Object.entries(obj)) {
    ret[entry[0]] = fn(entry[1]);
  }
  return ret;
}
var tokenZeroMessageField = /* @__PURE__ */ Symbol();
var messagePrototypes = /* @__PURE__ */ new WeakMap();
function createZeroMessage(desc) {
  let msg;
  if (!needsPrototypeChain(desc)) {
    msg = {
      $typeName: desc.typeName
    };
    for (const member of desc.members) {
      if (member.kind == "oneof" || member.presence == IMPLICIT2) {
        msg[member.localName] = createZeroField(member);
      }
    }
  } else {
    const cached = messagePrototypes.get(desc);
    let prototype;
    let members;
    if (cached) {
      ({ prototype, members } = cached);
    } else {
      prototype = {};
      members = /* @__PURE__ */ new Set();
      for (const member of desc.members) {
        if (member.kind == "oneof") {
          continue;
        }
        if (member.fieldKind != "scalar" && member.fieldKind != "enum") {
          continue;
        }
        if (member.presence == IMPLICIT2) {
          continue;
        }
        members.add(member);
        prototype[member.localName] = createZeroField(member);
      }
      messagePrototypes.set(desc, { prototype, members });
    }
    msg = Object.create(prototype);
    msg.$typeName = desc.typeName;
    for (const member of desc.members) {
      if (members.has(member)) {
        continue;
      }
      if (member.kind == "field") {
        if (member.fieldKind == "message") {
          continue;
        }
        if (member.fieldKind == "scalar" || member.fieldKind == "enum") {
          if (member.presence != IMPLICIT2) {
            continue;
          }
        }
      }
      msg[member.localName] = createZeroField(member);
    }
  }
  return msg;
}
function needsPrototypeChain(desc) {
  switch (desc.file.edition) {
    case EDITION_PROTO3:
      return false;
    case EDITION_PROTO2:
      return true;
    default:
      return desc.fields.some((f) => f.presence != IMPLICIT2 && f.fieldKind != "message" && !f.oneof);
  }
}
function createZeroField(field) {
  if (field.kind == "oneof") {
    return { case: void 0 };
  }
  if (field.fieldKind == "list") {
    return [];
  }
  if (field.fieldKind == "map") {
    return {};
  }
  if (field.fieldKind == "message") {
    return tokenZeroMessageField;
  }
  const defaultValue = field.getDefaultValue();
  if (defaultValue !== void 0) {
    return field.fieldKind == "scalar" && field.longAsString ? defaultValue.toString() : defaultValue;
  }
  return field.fieldKind == "scalar" ? scalarZeroValue(field.scalar, field.longAsString) : field.enum.values[0].number;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/error.js
var errorNames = [
  "FieldValueInvalidError",
  "FieldListRangeError",
  "ForeignFieldError"
];
var FieldError = class extends Error {
  constructor(fieldOrOneof, message, name = "FieldValueInvalidError") {
    super(message);
    this.name = name;
    this.field = () => fieldOrOneof;
  }
};
function isFieldError(arg) {
  return arg instanceof Error && errorNames.includes(arg.name) && "field" in arg && typeof arg.field == "function";
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wire/text-encoding.js
var symbol = /* @__PURE__ */ Symbol.for("@bufbuild/protobuf/text-encoding");
function getTextEncoding() {
  if (globalThis[symbol] == void 0) {
    const te = new globalThis.TextEncoder();
    const td = new globalThis.TextDecoder();
    globalThis[symbol] = {
      encodeUtf8(text) {
        return te.encode(text);
      },
      decodeUtf8(bytes) {
        return td.decode(bytes);
      },
      checkUtf8(text) {
        try {
          encodeURIComponent(text);
          return true;
        } catch (_) {
          return false;
        }
      }
    };
  }
  return globalThis[symbol];
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wire/binary-encoding.js
var WireType;
(function(WireType2) {
  WireType2[WireType2["Varint"] = 0] = "Varint";
  WireType2[WireType2["Bit64"] = 1] = "Bit64";
  WireType2[WireType2["LengthDelimited"] = 2] = "LengthDelimited";
  WireType2[WireType2["StartGroup"] = 3] = "StartGroup";
  WireType2[WireType2["EndGroup"] = 4] = "EndGroup";
  WireType2[WireType2["Bit32"] = 5] = "Bit32";
})(WireType || (WireType = {}));
var FLOAT32_MAX = 34028234663852886e22;
var FLOAT32_MIN = -34028234663852886e22;
var UINT32_MAX = 4294967295;
var INT32_MAX = 2147483647;
var INT32_MIN = -2147483648;
var BinaryWriter = class {
  constructor(encodeUtf8 = getTextEncoding().encodeUtf8) {
    this.encodeUtf8 = encodeUtf8;
    this.stack = [];
    this.chunks = [];
    this.buf = [];
  }
  /**
   * Return all bytes written and reset this writer.
   */
  finish() {
    if (this.buf.length) {
      this.chunks.push(new Uint8Array(this.buf));
      this.buf = [];
    }
    let len = 0;
    for (let i = 0; i < this.chunks.length; i++)
      len += this.chunks[i].length;
    let bytes = new Uint8Array(len);
    let offset = 0;
    for (let i = 0; i < this.chunks.length; i++) {
      bytes.set(this.chunks[i], offset);
      offset += this.chunks[i].length;
    }
    this.chunks = [];
    return bytes;
  }
  /**
   * Start a new fork for length-delimited data like a message
   * or a packed repeated field.
   *
   * Must be joined later with `join()`.
   */
  fork() {
    this.stack.push({ chunks: this.chunks, buf: this.buf });
    this.chunks = [];
    this.buf = [];
    return this;
  }
  /**
   * Join the last fork. Write its length and bytes, then
   * return to the previous state.
   */
  join() {
    let chunk = this.finish();
    let prev = this.stack.pop();
    if (!prev)
      throw new Error("invalid state, fork stack empty");
    this.chunks = prev.chunks;
    this.buf = prev.buf;
    this.uint32(chunk.byteLength);
    return this.raw(chunk);
  }
  /**
   * Writes a tag (field number and wire type).
   *
   * Equivalent to `uint32( (fieldNo << 3 | type) >>> 0 )`.
   *
   * Generated code should compute the tag ahead of time and call `uint32()`.
   */
  tag(fieldNo, type) {
    return this.uint32((fieldNo << 3 | type) >>> 0);
  }
  /**
   * Write a chunk of raw bytes.
   */
  raw(chunk) {
    if (this.buf.length) {
      this.chunks.push(new Uint8Array(this.buf));
      this.buf = [];
    }
    this.chunks.push(chunk);
    return this;
  }
  /**
   * Write a `uint32` value, an unsigned 32 bit varint.
   */
  uint32(value) {
    assertUInt32(value);
    while (value > 127) {
      this.buf.push(value & 127 | 128);
      value = value >>> 7;
    }
    this.buf.push(value);
    return this;
  }
  /**
   * Write a `int32` value, a signed 32 bit varint.
   */
  int32(value) {
    assertInt32(value);
    varint32write(value, this.buf);
    return this;
  }
  /**
   * Write a `bool` value, a variant.
   */
  bool(value) {
    this.buf.push(value ? 1 : 0);
    return this;
  }
  /**
   * Write a `bytes` value, length-delimited arbitrary data.
   */
  bytes(value) {
    this.uint32(value.byteLength);
    return this.raw(value);
  }
  /**
   * Write a `string` value, length-delimited data converted to UTF-8 text.
   */
  string(value) {
    let chunk = this.encodeUtf8(value);
    this.uint32(chunk.byteLength);
    return this.raw(chunk);
  }
  /**
   * Write a `float` value, 32-bit floating point number.
   */
  float(value) {
    assertFloat32(value);
    let chunk = new Uint8Array(4);
    new DataView(chunk.buffer).setFloat32(0, value, true);
    return this.raw(chunk);
  }
  /**
   * Write a `double` value, a 64-bit floating point number.
   */
  double(value) {
    let chunk = new Uint8Array(8);
    new DataView(chunk.buffer).setFloat64(0, value, true);
    return this.raw(chunk);
  }
  /**
   * Write a `fixed32` value, an unsigned, fixed-length 32-bit integer.
   */
  fixed32(value) {
    assertUInt32(value);
    let chunk = new Uint8Array(4);
    new DataView(chunk.buffer).setUint32(0, value, true);
    return this.raw(chunk);
  }
  /**
   * Write a `sfixed32` value, a signed, fixed-length 32-bit integer.
   */
  sfixed32(value) {
    assertInt32(value);
    let chunk = new Uint8Array(4);
    new DataView(chunk.buffer).setInt32(0, value, true);
    return this.raw(chunk);
  }
  /**
   * Write a `sint32` value, a signed, zigzag-encoded 32-bit varint.
   */
  sint32(value) {
    assertInt32(value);
    value = (value << 1 ^ value >> 31) >>> 0;
    varint32write(value, this.buf);
    return this;
  }
  /**
   * Write a `fixed64` value, a signed, fixed-length 64-bit integer.
   */
  sfixed64(value) {
    let chunk = new Uint8Array(8), view = new DataView(chunk.buffer), tc = protoInt64.enc(value);
    view.setInt32(0, tc.lo, true);
    view.setInt32(4, tc.hi, true);
    return this.raw(chunk);
  }
  /**
   * Write a `fixed64` value, an unsigned, fixed-length 64 bit integer.
   */
  fixed64(value) {
    let chunk = new Uint8Array(8), view = new DataView(chunk.buffer), tc = protoInt64.uEnc(value);
    view.setInt32(0, tc.lo, true);
    view.setInt32(4, tc.hi, true);
    return this.raw(chunk);
  }
  /**
   * Write a `int64` value, a signed 64-bit varint.
   */
  int64(value) {
    let tc = protoInt64.enc(value);
    varint64write(tc.lo, tc.hi, this.buf);
    return this;
  }
  /**
   * Write a `sint64` value, a signed, zig-zag-encoded 64-bit varint.
   */
  sint64(value) {
    const tc = protoInt64.enc(value), sign = tc.hi >> 31, lo = tc.lo << 1 ^ sign, hi = (tc.hi << 1 | tc.lo >>> 31) ^ sign;
    varint64write(lo, hi, this.buf);
    return this;
  }
  /**
   * Write a `uint64` value, an unsigned 64-bit varint.
   */
  uint64(value) {
    const tc = protoInt64.uEnc(value);
    varint64write(tc.lo, tc.hi, this.buf);
    return this;
  }
};
var BinaryReader = class {
  constructor(buf, decodeUtf8 = getTextEncoding().decodeUtf8) {
    this.decodeUtf8 = decodeUtf8;
    this.varint64 = varint64read;
    this.uint32 = varint32read;
    this.buf = buf;
    this.len = buf.length;
    this.pos = 0;
    this.view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  }
  /**
   * Reads a tag - field number and wire type.
   */
  tag() {
    let tag = this.uint32(), fieldNo = tag >>> 3, wireType = tag & 7;
    if (fieldNo <= 0 || wireType < 0 || wireType > 5)
      throw new Error("illegal tag: field no " + fieldNo + " wire type " + wireType);
    return [fieldNo, wireType];
  }
  /**
   * Skip one element and return the skipped data.
   *
   * When skipping StartGroup, provide the tags field number to check for
   * matching field number in the EndGroup tag.
   */
  skip(wireType, fieldNo) {
    let start = this.pos;
    switch (wireType) {
      case WireType.Varint:
        while (this.buf[this.pos++] & 128) {
        }
        break;
      // @ts-ignore TS7029: Fallthrough case in switch -- ignore instead of expect-error for compiler settings without noFallthroughCasesInSwitch: true
      case WireType.Bit64:
        this.pos += 4;
      case WireType.Bit32:
        this.pos += 4;
        break;
      case WireType.LengthDelimited:
        let len = this.uint32();
        this.pos += len;
        break;
      case WireType.StartGroup:
        for (; ; ) {
          const [fn, wt] = this.tag();
          if (wt === WireType.EndGroup) {
            if (fieldNo !== void 0 && fn !== fieldNo) {
              throw new Error("invalid end group tag");
            }
            break;
          }
          this.skip(wt, fn);
        }
        break;
      default:
        throw new Error("cant skip wire type " + wireType);
    }
    this.assertBounds();
    return this.buf.subarray(start, this.pos);
  }
  /**
   * Throws error if position in byte array is out of range.
   */
  assertBounds() {
    if (this.pos > this.len)
      throw new RangeError("premature EOF");
  }
  /**
   * Read a `int32` field, a signed 32 bit varint.
   */
  int32() {
    return this.uint32() | 0;
  }
  /**
   * Read a `sint32` field, a signed, zigzag-encoded 32-bit varint.
   */
  sint32() {
    let zze = this.uint32();
    return zze >>> 1 ^ -(zze & 1);
  }
  /**
   * Read a `int64` field, a signed 64-bit varint.
   */
  int64() {
    return protoInt64.dec(...this.varint64());
  }
  /**
   * Read a `uint64` field, an unsigned 64-bit varint.
   */
  uint64() {
    return protoInt64.uDec(...this.varint64());
  }
  /**
   * Read a `sint64` field, a signed, zig-zag-encoded 64-bit varint.
   */
  sint64() {
    let [lo, hi] = this.varint64();
    let s = -(lo & 1);
    lo = (lo >>> 1 | (hi & 1) << 31) ^ s;
    hi = hi >>> 1 ^ s;
    return protoInt64.dec(lo, hi);
  }
  /**
   * Read a `bool` field, a variant.
   */
  bool() {
    let [lo, hi] = this.varint64();
    return lo !== 0 || hi !== 0;
  }
  /**
   * Read a `fixed32` field, an unsigned, fixed-length 32-bit integer.
   */
  fixed32() {
    return this.view.getUint32((this.pos += 4) - 4, true);
  }
  /**
   * Read a `sfixed32` field, a signed, fixed-length 32-bit integer.
   */
  sfixed32() {
    return this.view.getInt32((this.pos += 4) - 4, true);
  }
  /**
   * Read a `fixed64` field, an unsigned, fixed-length 64 bit integer.
   */
  fixed64() {
    return protoInt64.uDec(this.sfixed32(), this.sfixed32());
  }
  /**
   * Read a `fixed64` field, a signed, fixed-length 64-bit integer.
   */
  sfixed64() {
    return protoInt64.dec(this.sfixed32(), this.sfixed32());
  }
  /**
   * Read a `float` field, 32-bit floating point number.
   */
  float() {
    return this.view.getFloat32((this.pos += 4) - 4, true);
  }
  /**
   * Read a `double` field, a 64-bit floating point number.
   */
  double() {
    return this.view.getFloat64((this.pos += 8) - 8, true);
  }
  /**
   * Read a `bytes` field, length-delimited arbitrary data.
   */
  bytes() {
    let len = this.uint32(), start = this.pos;
    this.pos += len;
    this.assertBounds();
    return this.buf.subarray(start, start + len);
  }
  /**
   * Read a `string` field, length-delimited data converted to UTF-8 text.
   */
  string() {
    return this.decodeUtf8(this.bytes());
  }
};
function assertInt32(arg) {
  if (typeof arg == "string") {
    arg = Number(arg);
  } else if (typeof arg != "number") {
    throw new Error("invalid int32: " + typeof arg);
  }
  if (!Number.isInteger(arg) || arg > INT32_MAX || arg < INT32_MIN)
    throw new Error("invalid int32: " + arg);
}
function assertUInt32(arg) {
  if (typeof arg == "string") {
    arg = Number(arg);
  } else if (typeof arg != "number") {
    throw new Error("invalid uint32: " + typeof arg);
  }
  if (!Number.isInteger(arg) || arg > UINT32_MAX || arg < 0)
    throw new Error("invalid uint32: " + arg);
}
function assertFloat32(arg) {
  if (typeof arg == "string") {
    const o = arg;
    arg = Number(arg);
    if (Number.isNaN(arg) && o !== "NaN") {
      throw new Error("invalid float32: " + o);
    }
  } else if (typeof arg != "number") {
    throw new Error("invalid float32: " + typeof arg);
  }
  if (Number.isFinite(arg) && (arg > FLOAT32_MAX || arg < FLOAT32_MIN))
    throw new Error("invalid float32: " + arg);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/reflect-check.js
function checkField(field, value) {
  const check = field.fieldKind == "list" ? isReflectList(value, field) : field.fieldKind == "map" ? isReflectMap(value, field) : checkSingular(field, value);
  if (check === true) {
    return void 0;
  }
  let reason;
  switch (field.fieldKind) {
    case "list":
      reason = `expected ${formatReflectList(field)}, got ${formatVal(value)}`;
      break;
    case "map":
      reason = `expected ${formatReflectMap(field)}, got ${formatVal(value)}`;
      break;
    default: {
      reason = reasonSingular(field, value, check);
    }
  }
  return new FieldError(field, reason);
}
function checkListItem(field, index, value) {
  const check = checkSingular(field, value);
  if (check !== true) {
    return new FieldError(field, `list item #${index + 1}: ${reasonSingular(field, value, check)}`);
  }
  return void 0;
}
function checkMapEntry(field, key, value) {
  const checkKey = checkScalarValue(key, field.mapKey);
  if (checkKey !== true) {
    return new FieldError(field, `invalid map key: ${reasonSingular({ scalar: field.mapKey }, key, checkKey)}`);
  }
  const checkVal = checkSingular(field, value);
  if (checkVal !== true) {
    return new FieldError(field, `map entry ${formatVal(key)}: ${reasonSingular(field, value, checkVal)}`);
  }
  return void 0;
}
function checkSingular(field, value) {
  if (field.scalar !== void 0) {
    return checkScalarValue(value, field.scalar);
  }
  if (field.enum !== void 0) {
    if (field.enum.open) {
      return Number.isInteger(value);
    }
    return field.enum.values.some((v) => v.number === value);
  }
  return isReflectMessage(value, field.message);
}
function checkScalarValue(value, scalar) {
  switch (scalar) {
    case ScalarType.DOUBLE:
      return typeof value == "number";
    case ScalarType.FLOAT:
      if (typeof value != "number") {
        return false;
      }
      if (Number.isNaN(value) || !Number.isFinite(value)) {
        return true;
      }
      if (value > FLOAT32_MAX || value < FLOAT32_MIN) {
        return `${value.toFixed()} out of range`;
      }
      return true;
    case ScalarType.INT32:
    case ScalarType.SFIXED32:
    case ScalarType.SINT32:
      if (typeof value !== "number" || !Number.isInteger(value)) {
        return false;
      }
      if (value > INT32_MAX || value < INT32_MIN) {
        return `${value.toFixed()} out of range`;
      }
      return true;
    case ScalarType.FIXED32:
    case ScalarType.UINT32:
      if (typeof value !== "number" || !Number.isInteger(value)) {
        return false;
      }
      if (value > UINT32_MAX || value < 0) {
        return `${value.toFixed()} out of range`;
      }
      return true;
    case ScalarType.BOOL:
      return typeof value == "boolean";
    case ScalarType.STRING:
      if (typeof value != "string") {
        return false;
      }
      return getTextEncoding().checkUtf8(value) || "invalid UTF8";
    case ScalarType.BYTES:
      return value instanceof Uint8Array;
    case ScalarType.INT64:
    case ScalarType.SFIXED64:
    case ScalarType.SINT64:
      if (typeof value == "bigint" || typeof value == "number" || typeof value == "string" && value.length > 0) {
        try {
          protoInt64.parse(value);
          return true;
        } catch (_) {
          return `${value} out of range`;
        }
      }
      return false;
    case ScalarType.FIXED64:
    case ScalarType.UINT64:
      if (typeof value == "bigint" || typeof value == "number" || typeof value == "string" && value.length > 0) {
        try {
          protoInt64.uParse(value);
          return true;
        } catch (_) {
          return `${value} out of range`;
        }
      }
      return false;
  }
}
function reasonSingular(field, val, details) {
  details = typeof details == "string" ? `: ${details}` : `, got ${formatVal(val)}`;
  if (field.scalar !== void 0) {
    return `expected ${scalarTypeDescription(field.scalar)}` + details;
  }
  if (field.enum !== void 0) {
    return `expected ${field.enum.toString()}` + details;
  }
  return `expected ${formatReflectMessage(field.message)}` + details;
}
function formatVal(val) {
  switch (typeof val) {
    case "object":
      if (val === null) {
        return "null";
      }
      if (val instanceof Uint8Array) {
        return `Uint8Array(${val.length})`;
      }
      if (Array.isArray(val)) {
        return `Array(${val.length})`;
      }
      if (isReflectList(val)) {
        return formatReflectList(val.field());
      }
      if (isReflectMap(val)) {
        return formatReflectMap(val.field());
      }
      if (isReflectMessage(val)) {
        return formatReflectMessage(val.desc);
      }
      if (isMessage(val)) {
        return `message ${val.$typeName}`;
      }
      return "object";
    case "string":
      return val.length > 30 ? "string" : `"${val.split('"').join('\\"')}"`;
    case "boolean":
      return String(val);
    case "number":
      return String(val);
    case "bigint":
      return String(val) + "n";
    default:
      return typeof val;
  }
}
function formatReflectMessage(desc) {
  return `ReflectMessage (${desc.typeName})`;
}
function formatReflectList(field) {
  switch (field.listKind) {
    case "message":
      return `ReflectList (${field.message.toString()})`;
    case "enum":
      return `ReflectList (${field.enum.toString()})`;
    case "scalar":
      return `ReflectList (${ScalarType[field.scalar]})`;
  }
}
function formatReflectMap(field) {
  switch (field.mapKind) {
    case "message":
      return `ReflectMap (${ScalarType[field.mapKey]}, ${field.message.toString()})`;
    case "enum":
      return `ReflectMap (${ScalarType[field.mapKey]}, ${field.enum.toString()})`;
    case "scalar":
      return `ReflectMap (${ScalarType[field.mapKey]}, ${ScalarType[field.scalar]})`;
  }
}
function scalarTypeDescription(scalar) {
  switch (scalar) {
    case ScalarType.STRING:
      return "string";
    case ScalarType.BOOL:
      return "boolean";
    case ScalarType.INT64:
    case ScalarType.SINT64:
    case ScalarType.SFIXED64:
      return "bigint (int64)";
    case ScalarType.UINT64:
    case ScalarType.FIXED64:
      return "bigint (uint64)";
    case ScalarType.BYTES:
      return "Uint8Array";
    case ScalarType.DOUBLE:
      return "number (float64)";
    case ScalarType.FLOAT:
      return "number (float32)";
    case ScalarType.FIXED32:
    case ScalarType.UINT32:
      return "number (uint32)";
    case ScalarType.INT32:
    case ScalarType.SFIXED32:
    case ScalarType.SINT32:
      return "number (int32)";
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/reflect.js
function reflect(messageDesc2, message, check = true) {
  return new ReflectMessageImpl(messageDesc2, message, check);
}
var messageSortedFields = /* @__PURE__ */ new WeakMap();
var ReflectMessageImpl = class {
  get sortedFields() {
    const cached = messageSortedFields.get(this.desc);
    if (cached) {
      return cached;
    }
    const sortedFields = this.desc.fields.concat().sort((a, b) => a.number - b.number);
    messageSortedFields.set(this.desc, sortedFields);
    return sortedFields;
  }
  constructor(messageDesc2, message, check = true) {
    this.lists = /* @__PURE__ */ new Map();
    this.maps = /* @__PURE__ */ new Map();
    this.check = check;
    this.desc = messageDesc2;
    this.message = this[unsafeLocal] = message !== null && message !== void 0 ? message : create(messageDesc2);
    this.fields = messageDesc2.fields;
    this.oneofs = messageDesc2.oneofs;
    this.members = messageDesc2.members;
  }
  findNumber(number) {
    if (!this._fieldsByNumber) {
      this._fieldsByNumber = new Map(this.desc.fields.map((f) => [f.number, f]));
    }
    return this._fieldsByNumber.get(number);
  }
  oneofCase(oneof) {
    assertOwn(this.message, oneof);
    return unsafeOneofCase(this.message, oneof);
  }
  isSet(field) {
    assertOwn(this.message, field);
    return unsafeIsSet(this.message, field);
  }
  clear(field) {
    assertOwn(this.message, field);
    unsafeClear(this.message, field);
  }
  get(field) {
    assertOwn(this.message, field);
    const value = unsafeGet(this.message, field);
    switch (field.fieldKind) {
      case "list":
        let list = this.lists.get(field);
        if (!list || list[unsafeLocal] !== value) {
          this.lists.set(
            field,
            // biome-ignore lint/suspicious/noAssignInExpressions: no
            list = new ReflectListImpl(field, value, this.check)
          );
        }
        return list;
      case "map":
        let map = this.maps.get(field);
        if (!map || map[unsafeLocal] !== value) {
          this.maps.set(
            field,
            // biome-ignore lint/suspicious/noAssignInExpressions: no
            map = new ReflectMapImpl(field, value, this.check)
          );
        }
        return map;
      case "message":
        return messageToReflect(field, value, this.check);
      case "scalar":
        return value === void 0 ? scalarZeroValue(field.scalar, false) : longToReflect(field, value);
      case "enum":
        return value !== null && value !== void 0 ? value : field.enum.values[0].number;
    }
  }
  set(field, value) {
    assertOwn(this.message, field);
    if (this.check) {
      const err = checkField(field, value);
      if (err) {
        throw err;
      }
    }
    let local;
    if (field.fieldKind == "message") {
      local = messageToLocal(field, value);
    } else if (isReflectMap(value) || isReflectList(value)) {
      local = value[unsafeLocal];
    } else {
      local = longToLocal(field, value);
    }
    unsafeSet(this.message, field, local);
  }
  getUnknown() {
    return this.message.$unknown;
  }
  setUnknown(value) {
    this.message.$unknown = value;
  }
};
function assertOwn(owner, member) {
  if (member.parent.typeName !== owner.$typeName) {
    throw new FieldError(member, `cannot use ${member.toString()} with message ${owner.$typeName}`, "ForeignFieldError");
  }
}
var ReflectListImpl = class {
  field() {
    return this._field;
  }
  get size() {
    return this._arr.length;
  }
  constructor(field, unsafeInput, check) {
    this._field = field;
    this._arr = this[unsafeLocal] = unsafeInput;
    this.check = check;
  }
  get(index) {
    const item = this._arr[index];
    return item === void 0 ? void 0 : listItemToReflect(this._field, item, this.check);
  }
  set(index, item) {
    if (index < 0 || index >= this._arr.length) {
      throw new FieldError(this._field, `list item #${index + 1}: out of range`);
    }
    if (this.check) {
      const err = checkListItem(this._field, index, item);
      if (err) {
        throw err;
      }
    }
    this._arr[index] = listItemToLocal(this._field, item);
  }
  add(item) {
    if (this.check) {
      const err = checkListItem(this._field, this._arr.length, item);
      if (err) {
        throw err;
      }
    }
    this._arr.push(listItemToLocal(this._field, item));
    return void 0;
  }
  clear() {
    this._arr.splice(0, this._arr.length);
  }
  [Symbol.iterator]() {
    return this.values();
  }
  keys() {
    return this._arr.keys();
  }
  *values() {
    for (const item of this._arr) {
      yield listItemToReflect(this._field, item, this.check);
    }
  }
  *entries() {
    for (let i = 0; i < this._arr.length; i++) {
      yield [i, listItemToReflect(this._field, this._arr[i], this.check)];
    }
  }
};
var ReflectMapImpl = class {
  constructor(field, unsafeInput, check = true) {
    this.obj = this[unsafeLocal] = unsafeInput !== null && unsafeInput !== void 0 ? unsafeInput : {};
    this.check = check;
    this._field = field;
  }
  field() {
    return this._field;
  }
  set(key, value) {
    if (this.check) {
      const err = checkMapEntry(this._field, key, value);
      if (err) {
        throw err;
      }
    }
    this.obj[mapKeyToLocal(key)] = mapValueToLocal(this._field, value);
    return this;
  }
  delete(key) {
    const k = mapKeyToLocal(key);
    const has = Object.prototype.hasOwnProperty.call(this.obj, k);
    if (has) {
      delete this.obj[k];
    }
    return has;
  }
  clear() {
    for (const key of Object.keys(this.obj)) {
      delete this.obj[key];
    }
  }
  get(key) {
    let val = this.obj[mapKeyToLocal(key)];
    if (val !== void 0) {
      val = mapValueToReflect(this._field, val, this.check);
    }
    return val;
  }
  has(key) {
    return Object.prototype.hasOwnProperty.call(this.obj, mapKeyToLocal(key));
  }
  *keys() {
    for (const objKey of Object.keys(this.obj)) {
      yield mapKeyToReflect(objKey, this._field.mapKey);
    }
  }
  *entries() {
    for (const objEntry of Object.entries(this.obj)) {
      yield [
        mapKeyToReflect(objEntry[0], this._field.mapKey),
        mapValueToReflect(this._field, objEntry[1], this.check)
      ];
    }
  }
  [Symbol.iterator]() {
    return this.entries();
  }
  get size() {
    return Object.keys(this.obj).length;
  }
  *values() {
    for (const val of Object.values(this.obj)) {
      yield mapValueToReflect(this._field, val, this.check);
    }
  }
  forEach(callbackfn, thisArg) {
    for (const mapEntry of this.entries()) {
      callbackfn.call(thisArg, mapEntry[1], mapEntry[0], this);
    }
  }
};
function messageToLocal(field, value) {
  if (!isReflectMessage(value)) {
    return value;
  }
  if (isWrapper(value.message) && !field.oneof && field.fieldKind == "message") {
    return value.message.value;
  }
  if (value.desc.typeName == "google.protobuf.Struct" && field.parent.typeName != "google.protobuf.Value") {
    return wktStructToLocal(value.message);
  }
  return value.message;
}
function messageToReflect(field, value, check) {
  if (value !== void 0) {
    if (isWrapperDesc(field.message) && !field.oneof && field.fieldKind == "message") {
      value = {
        $typeName: field.message.typeName,
        value: longToReflect(field.message.fields[0], value)
      };
    } else if (field.message.typeName == "google.protobuf.Struct" && field.parent.typeName != "google.protobuf.Value" && isObject(value)) {
      value = wktStructToReflect(value);
    }
  }
  return new ReflectMessageImpl(field.message, value, check);
}
function listItemToLocal(field, value) {
  if (field.listKind == "message") {
    return messageToLocal(field, value);
  }
  return longToLocal(field, value);
}
function listItemToReflect(field, value, check) {
  if (field.listKind == "message") {
    return messageToReflect(field, value, check);
  }
  return longToReflect(field, value);
}
function mapValueToLocal(field, value) {
  if (field.mapKind == "message") {
    return messageToLocal(field, value);
  }
  return longToLocal(field, value);
}
function mapValueToReflect(field, value, check) {
  if (field.mapKind == "message") {
    return messageToReflect(field, value, check);
  }
  return value;
}
function mapKeyToLocal(key) {
  return typeof key == "string" || typeof key == "number" ? key : String(key);
}
function mapKeyToReflect(key, type) {
  switch (type) {
    case ScalarType.STRING:
      return key;
    case ScalarType.INT32:
    case ScalarType.FIXED32:
    case ScalarType.UINT32:
    case ScalarType.SFIXED32:
    case ScalarType.SINT32: {
      const n = Number.parseInt(key);
      if (Number.isFinite(n)) {
        return n;
      }
      break;
    }
    case ScalarType.BOOL:
      switch (key) {
        case "true":
          return true;
        case "false":
          return false;
      }
      break;
    case ScalarType.UINT64:
    case ScalarType.FIXED64:
      try {
        return protoInt64.uParse(key);
      } catch (_a) {
      }
      break;
    default:
      try {
        return protoInt64.parse(key);
      } catch (_b) {
      }
      break;
  }
  return key;
}
function longToReflect(field, value) {
  switch (field.scalar) {
    case ScalarType.INT64:
    case ScalarType.SFIXED64:
    case ScalarType.SINT64:
      if ("longAsString" in field && field.longAsString && typeof value == "string") {
        value = protoInt64.parse(value);
      }
      break;
    case ScalarType.FIXED64:
    case ScalarType.UINT64:
      if ("longAsString" in field && field.longAsString && typeof value == "string") {
        value = protoInt64.uParse(value);
      }
      break;
  }
  return value;
}
function longToLocal(field, value) {
  switch (field.scalar) {
    case ScalarType.INT64:
    case ScalarType.SFIXED64:
    case ScalarType.SINT64:
      if ("longAsString" in field && field.longAsString) {
        value = String(value);
      } else if (typeof value == "string" || typeof value == "number") {
        value = protoInt64.parse(value);
      }
      break;
    case ScalarType.FIXED64:
    case ScalarType.UINT64:
      if ("longAsString" in field && field.longAsString) {
        value = String(value);
      } else if (typeof value == "string" || typeof value == "number") {
        value = protoInt64.uParse(value);
      }
      break;
  }
  return value;
}
function wktStructToReflect(json) {
  const struct = {
    $typeName: "google.protobuf.Struct",
    fields: {}
  };
  if (isObject(json)) {
    for (const [k, v] of Object.entries(json)) {
      struct.fields[k] = wktValueToReflect(v);
    }
  }
  return struct;
}
function wktStructToLocal(val) {
  const json = {};
  for (const [k, v] of Object.entries(val.fields)) {
    json[k] = wktValueToLocal(v);
  }
  return json;
}
function wktValueToLocal(val) {
  switch (val.kind.case) {
    case "structValue":
      return wktStructToLocal(val.kind.value);
    case "listValue":
      return val.kind.value.values.map(wktValueToLocal);
    case "nullValue":
    case void 0:
      return null;
    default:
      return val.kind.value;
  }
}
function wktValueToReflect(json) {
  const value = {
    $typeName: "google.protobuf.Value",
    kind: { case: void 0 }
  };
  switch (typeof json) {
    case "number":
      value.kind = { case: "numberValue", value: json };
      break;
    case "string":
      value.kind = { case: "stringValue", value: json };
      break;
    case "boolean":
      value.kind = { case: "boolValue", value: json };
      break;
    case "object":
      if (json === null) {
        const nullValue = 0;
        value.kind = { case: "nullValue", value: nullValue };
      } else if (Array.isArray(json)) {
        const listValue = {
          $typeName: "google.protobuf.ListValue",
          values: []
        };
        if (Array.isArray(json)) {
          for (const e of json) {
            listValue.values.push(wktValueToReflect(e));
          }
        }
        value.kind = {
          case: "listValue",
          value: listValue
        };
      } else {
        value.kind = {
          case: "structValue",
          value: wktStructToReflect(json)
        };
      }
      break;
  }
  return value;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wire/base64-encoding.js
function base64Decode(base64Str) {
  const table = getDecodeTable();
  let es = base64Str.length * 3 / 4;
  if (base64Str[base64Str.length - 2] == "=")
    es -= 2;
  else if (base64Str[base64Str.length - 1] == "=")
    es -= 1;
  let bytes = new Uint8Array(es), bytePos = 0, groupPos = 0, b, p = 0;
  for (let i = 0; i < base64Str.length; i++) {
    b = table[base64Str.charCodeAt(i)];
    if (b === void 0) {
      switch (base64Str[i]) {
        // @ts-ignore TS7029: Fallthrough case in switch -- ignore instead of expect-error for compiler settings without noFallthroughCasesInSwitch: true
        case "=":
          groupPos = 0;
        // reset state when padding found
        case "\n":
        case "\r":
        case "	":
        case " ":
          continue;
        // skip white-space, and padding
        default:
          throw Error("invalid base64 string");
      }
    }
    switch (groupPos) {
      case 0:
        p = b;
        groupPos = 1;
        break;
      case 1:
        bytes[bytePos++] = p << 2 | (b & 48) >> 4;
        p = b;
        groupPos = 2;
        break;
      case 2:
        bytes[bytePos++] = (p & 15) << 4 | (b & 60) >> 2;
        p = b;
        groupPos = 3;
        break;
      case 3:
        bytes[bytePos++] = (p & 3) << 6 | b;
        groupPos = 0;
        break;
    }
  }
  if (groupPos == 1)
    throw Error("invalid base64 string");
  return bytes.subarray(0, bytePos);
}
function base64Encode(bytes, encoding = "std") {
  const table = getEncodeTable(encoding);
  const pad = encoding == "std";
  let base64 = "", groupPos = 0, b, p = 0;
  for (let i = 0; i < bytes.length; i++) {
    b = bytes[i];
    switch (groupPos) {
      case 0:
        base64 += table[b >> 2];
        p = (b & 3) << 4;
        groupPos = 1;
        break;
      case 1:
        base64 += table[p | b >> 4];
        p = (b & 15) << 2;
        groupPos = 2;
        break;
      case 2:
        base64 += table[p | b >> 6];
        base64 += table[b & 63];
        groupPos = 0;
        break;
    }
  }
  if (groupPos) {
    base64 += table[p];
    if (pad) {
      base64 += "=";
      if (groupPos == 1)
        base64 += "=";
    }
  }
  return base64;
}
var encodeTableStd;
var encodeTableUrl;
var decodeTable;
function getEncodeTable(encoding) {
  if (!encodeTableStd) {
    encodeTableStd = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".split("");
    encodeTableUrl = encodeTableStd.slice(0, -2).concat("-", "_");
  }
  return encoding == "url" ? (
    // biome-ignore lint/style/noNonNullAssertion: TS fails to narrow down
    encodeTableUrl
  ) : encodeTableStd;
}
function getDecodeTable() {
  if (!decodeTable) {
    decodeTable = [];
    const encodeTable = getEncodeTable("std");
    for (let i = 0; i < encodeTable.length; i++)
      decodeTable[encodeTable[i].charCodeAt(0)] = i;
    decodeTable["-".charCodeAt(0)] = encodeTable.indexOf("+");
    decodeTable["_".charCodeAt(0)] = encodeTable.indexOf("/");
  }
  return decodeTable;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/names.js
function protoCamelCase(snakeCase) {
  let capNext = false;
  const b = [];
  for (let i = 0; i < snakeCase.length; i++) {
    let c = snakeCase.charAt(i);
    switch (c) {
      case "_":
        capNext = true;
        break;
      case "0":
      case "1":
      case "2":
      case "3":
      case "4":
      case "5":
      case "6":
      case "7":
      case "8":
      case "9":
        b.push(c);
        capNext = false;
        break;
      default:
        if (capNext) {
          capNext = false;
          c = c.toUpperCase();
        }
        b.push(c);
        break;
    }
  }
  return b.join("");
}
function protoSnakeCase(lowerCamelCase) {
  return lowerCamelCase.replace(/[A-Z]/g, (letter) => "_" + letter.toLowerCase());
}
var reservedObjectProperties = /* @__PURE__ */ new Set([
  // names reserved by JavaScript
  "constructor",
  "toString",
  "toJSON",
  "valueOf"
]);
function safeObjectProperty(name) {
  return reservedObjectProperties.has(name) ? name + "$" : name;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/codegenv2/restore-json-names.js
function restoreJsonNames(message) {
  for (const f of message.field) {
    if (!unsafeIsSetExplicit(f, "jsonName")) {
      f.jsonName = protoCamelCase(f.name);
    }
  }
  message.nestedType.forEach(restoreJsonNames);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wire/text-format.js
function parseTextFormatEnumValue(descEnum, value) {
  const enumValue = descEnum.values.find((v) => v.name === value);
  if (!enumValue) {
    throw new Error(`cannot parse ${descEnum} default value: ${value}`);
  }
  return enumValue.number;
}
function parseTextFormatScalarValue(type, value) {
  switch (type) {
    case ScalarType.STRING:
      return value;
    case ScalarType.BYTES: {
      const u = unescapeBytesDefaultValue(value);
      if (u === false) {
        throw new Error(`cannot parse ${ScalarType[type]} default value: ${value}`);
      }
      return u;
    }
    case ScalarType.INT64:
    case ScalarType.SFIXED64:
    case ScalarType.SINT64:
      return protoInt64.parse(value);
    case ScalarType.UINT64:
    case ScalarType.FIXED64:
      return protoInt64.uParse(value);
    case ScalarType.DOUBLE:
    case ScalarType.FLOAT:
      switch (value) {
        case "inf":
          return Number.POSITIVE_INFINITY;
        case "-inf":
          return Number.NEGATIVE_INFINITY;
        case "nan":
          return Number.NaN;
        default:
          return parseFloat(value);
      }
    case ScalarType.BOOL:
      return value === "true";
    case ScalarType.INT32:
    case ScalarType.UINT32:
    case ScalarType.SINT32:
    case ScalarType.FIXED32:
    case ScalarType.SFIXED32:
      return parseInt(value, 10);
  }
}
function unescapeBytesDefaultValue(str) {
  const b = [];
  const input = {
    tail: str,
    c: "",
    next() {
      if (this.tail.length == 0) {
        return false;
      }
      this.c = this.tail[0];
      this.tail = this.tail.substring(1);
      return true;
    },
    take(n) {
      if (this.tail.length >= n) {
        const r = this.tail.substring(0, n);
        this.tail = this.tail.substring(n);
        return r;
      }
      return false;
    }
  };
  while (input.next()) {
    switch (input.c) {
      case "\\":
        if (input.next()) {
          switch (input.c) {
            case "\\":
              b.push(input.c.charCodeAt(0));
              break;
            case "b":
              b.push(8);
              break;
            case "f":
              b.push(12);
              break;
            case "n":
              b.push(10);
              break;
            case "r":
              b.push(13);
              break;
            case "t":
              b.push(9);
              break;
            case "v":
              b.push(11);
              break;
            case "0":
            case "1":
            case "2":
            case "3":
            case "4":
            case "5":
            case "6":
            case "7": {
              const s = input.c;
              const t = input.take(2);
              if (t === false) {
                return false;
              }
              const n = parseInt(s + t, 8);
              if (Number.isNaN(n)) {
                return false;
              }
              b.push(n);
              break;
            }
            case "x": {
              const s = input.c;
              const t = input.take(2);
              if (t === false) {
                return false;
              }
              const n = parseInt(s + t, 16);
              if (Number.isNaN(n)) {
                return false;
              }
              b.push(n);
              break;
            }
            case "u": {
              const s = input.c;
              const t = input.take(4);
              if (t === false) {
                return false;
              }
              const n = parseInt(s + t, 16);
              if (Number.isNaN(n)) {
                return false;
              }
              const chunk = new Uint8Array(4);
              const view = new DataView(chunk.buffer);
              view.setInt32(0, n, true);
              b.push(chunk[0], chunk[1], chunk[2], chunk[3]);
              break;
            }
            case "U": {
              const s = input.c;
              const t = input.take(8);
              if (t === false) {
                return false;
              }
              const tc = protoInt64.uEnc(s + t);
              const chunk = new Uint8Array(8);
              const view = new DataView(chunk.buffer);
              view.setInt32(0, tc.lo, true);
              view.setInt32(4, tc.hi, true);
              b.push(chunk[0], chunk[1], chunk[2], chunk[3], chunk[4], chunk[5], chunk[6], chunk[7]);
              break;
            }
          }
        }
        break;
      default:
        b.push(input.c.charCodeAt(0));
    }
  }
  return new Uint8Array(b);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/reflect/nested-types.js
function* nestedTypes(desc) {
  switch (desc.kind) {
    case "file":
      for (const message of desc.messages) {
        yield message;
        yield* nestedTypes(message);
      }
      yield* desc.enums;
      yield* desc.services;
      yield* desc.extensions;
      break;
    case "message":
      for (const message of desc.nestedMessages) {
        yield message;
        yield* nestedTypes(message);
      }
      yield* desc.nestedEnums;
      yield* desc.nestedExtensions;
      break;
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/registry.js
function createFileRegistry(...args) {
  const registry = createBaseRegistry();
  if (!args.length) {
    return registry;
  }
  if ("$typeName" in args[0] && args[0].$typeName == "google.protobuf.FileDescriptorSet") {
    for (const file of args[0].file) {
      addFile(file, registry);
    }
    return registry;
  }
  if ("$typeName" in args[0]) {
    let recurseDeps = function(file) {
      const deps = [];
      for (const protoFileName of file.dependency) {
        if (registry.getFile(protoFileName) != void 0) {
          continue;
        }
        if (seen.has(protoFileName)) {
          continue;
        }
        const dep = resolve2(protoFileName);
        if (!dep) {
          throw new Error(`Unable to resolve ${protoFileName}, imported by ${file.name}`);
        }
        if ("kind" in dep) {
          registry.addFile(dep, false, true);
        } else {
          seen.add(dep.name);
          deps.push(dep);
        }
      }
      return deps.concat(...deps.map(recurseDeps));
    };
    const input = args[0];
    const resolve2 = args[1];
    const seen = /* @__PURE__ */ new Set();
    for (const file of [input, ...recurseDeps(input)].reverse()) {
      addFile(file, registry);
    }
  } else {
    for (const fileReg of args) {
      for (const file of fileReg.files) {
        registry.addFile(file);
      }
    }
  }
  return registry;
}
function createBaseRegistry() {
  const types = /* @__PURE__ */ new Map();
  const extendees = /* @__PURE__ */ new Map();
  const files = /* @__PURE__ */ new Map();
  return {
    kind: "registry",
    types,
    extendees,
    [Symbol.iterator]() {
      return types.values();
    },
    get files() {
      return files.values();
    },
    addFile(file, skipTypes, withDeps) {
      files.set(file.proto.name, file);
      if (!skipTypes) {
        for (const type of nestedTypes(file)) {
          this.add(type);
        }
      }
      if (withDeps) {
        for (const f of file.dependencies) {
          this.addFile(f, skipTypes, withDeps);
        }
      }
    },
    add(desc) {
      if (desc.kind == "extension") {
        let numberToExt = extendees.get(desc.extendee.typeName);
        if (!numberToExt) {
          extendees.set(
            desc.extendee.typeName,
            // biome-ignore lint/suspicious/noAssignInExpressions: no
            numberToExt = /* @__PURE__ */ new Map()
          );
        }
        numberToExt.set(desc.number, desc);
      }
      types.set(desc.typeName, desc);
    },
    get(typeName) {
      return types.get(typeName);
    },
    getFile(fileName) {
      return files.get(fileName);
    },
    getMessage(typeName) {
      const t = types.get(typeName);
      return (t === null || t === void 0 ? void 0 : t.kind) == "message" ? t : void 0;
    },
    getEnum(typeName) {
      const t = types.get(typeName);
      return (t === null || t === void 0 ? void 0 : t.kind) == "enum" ? t : void 0;
    },
    getExtension(typeName) {
      const t = types.get(typeName);
      return (t === null || t === void 0 ? void 0 : t.kind) == "extension" ? t : void 0;
    },
    getExtensionFor(extendee, no) {
      var _a;
      return (_a = extendees.get(extendee.typeName)) === null || _a === void 0 ? void 0 : _a.get(no);
    },
    getService(typeName) {
      const t = types.get(typeName);
      return (t === null || t === void 0 ? void 0 : t.kind) == "service" ? t : void 0;
    }
  };
}
var EDITION_PROTO22 = 998;
var EDITION_PROTO32 = 999;
var TYPE_STRING = 9;
var TYPE_GROUP = 10;
var TYPE_MESSAGE = 11;
var TYPE_BYTES = 12;
var TYPE_ENUM = 14;
var LABEL_REPEATED = 3;
var LABEL_REQUIRED = 2;
var JS_STRING = 1;
var IDEMPOTENCY_UNKNOWN = 0;
var EXPLICIT = 1;
var IMPLICIT3 = 2;
var LEGACY_REQUIRED = 3;
var PACKED = 1;
var DELIMITED = 2;
var OPEN = 1;
var featureDefaults = {
  // EDITION_PROTO2
  998: {
    fieldPresence: 1,
    // EXPLICIT,
    enumType: 2,
    // CLOSED,
    repeatedFieldEncoding: 2,
    // EXPANDED,
    utf8Validation: 3,
    // NONE,
    messageEncoding: 1,
    // LENGTH_PREFIXED,
    jsonFormat: 2,
    // LEGACY_BEST_EFFORT,
    enforceNamingStyle: 2,
    // STYLE_LEGACY,
    defaultSymbolVisibility: 1
    // EXPORT_ALL,
  },
  // EDITION_PROTO3
  999: {
    fieldPresence: 2,
    // IMPLICIT,
    enumType: 1,
    // OPEN,
    repeatedFieldEncoding: 1,
    // PACKED,
    utf8Validation: 2,
    // VERIFY,
    messageEncoding: 1,
    // LENGTH_PREFIXED,
    jsonFormat: 1,
    // ALLOW,
    enforceNamingStyle: 2,
    // STYLE_LEGACY,
    defaultSymbolVisibility: 1
    // EXPORT_ALL,
  },
  // EDITION_2023
  1e3: {
    fieldPresence: 1,
    // EXPLICIT,
    enumType: 1,
    // OPEN,
    repeatedFieldEncoding: 1,
    // PACKED,
    utf8Validation: 2,
    // VERIFY,
    messageEncoding: 1,
    // LENGTH_PREFIXED,
    jsonFormat: 1,
    // ALLOW,
    enforceNamingStyle: 2,
    // STYLE_LEGACY,
    defaultSymbolVisibility: 1
    // EXPORT_ALL,
  },
  // EDITION_2024
  1001: {
    fieldPresence: 1,
    // EXPLICIT,
    enumType: 1,
    // OPEN,
    repeatedFieldEncoding: 1,
    // PACKED,
    utf8Validation: 2,
    // VERIFY,
    messageEncoding: 1,
    // LENGTH_PREFIXED,
    jsonFormat: 1,
    // ALLOW,
    enforceNamingStyle: 1,
    // STYLE2024,
    defaultSymbolVisibility: 2
    // EXPORT_TOP_LEVEL,
  }
};
function addFile(proto, reg) {
  var _a, _b;
  const file = {
    kind: "file",
    proto,
    deprecated: (_b = (_a = proto.options) === null || _a === void 0 ? void 0 : _a.deprecated) !== null && _b !== void 0 ? _b : false,
    edition: getFileEdition(proto),
    name: proto.name.replace(/\.proto$/, ""),
    dependencies: findFileDependencies(proto, reg),
    enums: [],
    messages: [],
    extensions: [],
    services: [],
    toString() {
      return `file ${proto.name}`;
    }
  };
  const mapEntriesStore = /* @__PURE__ */ new Map();
  const mapEntries = {
    get(typeName) {
      return mapEntriesStore.get(typeName);
    },
    add(desc) {
      var _a2;
      assert(((_a2 = desc.proto.options) === null || _a2 === void 0 ? void 0 : _a2.mapEntry) === true);
      mapEntriesStore.set(desc.typeName, desc);
    }
  };
  for (const enumProto of proto.enumType) {
    addEnum(enumProto, file, void 0, reg);
  }
  for (const messageProto of proto.messageType) {
    addMessage(messageProto, file, void 0, reg, mapEntries);
  }
  for (const serviceProto of proto.service) {
    addService(serviceProto, file, reg);
  }
  addExtensions(file, reg);
  for (const mapEntry of mapEntriesStore.values()) {
    addFields(mapEntry, reg, mapEntries);
  }
  for (const message of file.messages) {
    addFields(message, reg, mapEntries);
    addExtensions(message, reg);
  }
  reg.addFile(file, true);
}
function addExtensions(desc, reg) {
  switch (desc.kind) {
    case "file":
      for (const proto of desc.proto.extension) {
        const ext = newField(proto, desc, reg);
        desc.extensions.push(ext);
        reg.add(ext);
      }
      break;
    case "message":
      for (const proto of desc.proto.extension) {
        const ext = newField(proto, desc, reg);
        desc.nestedExtensions.push(ext);
        reg.add(ext);
      }
      for (const message of desc.nestedMessages) {
        addExtensions(message, reg);
      }
      break;
  }
}
function addFields(message, reg, mapEntries) {
  const allOneofs = message.proto.oneofDecl.map((proto) => newOneof(proto, message));
  const oneofsSeen = /* @__PURE__ */ new Set();
  for (const proto of message.proto.field) {
    const oneof = findOneof(proto, allOneofs);
    const field = newField(proto, message, reg, oneof, mapEntries);
    message.fields.push(field);
    message.field[field.localName] = field;
    if (oneof === void 0) {
      message.members.push(field);
    } else {
      oneof.fields.push(field);
      if (!oneofsSeen.has(oneof)) {
        oneofsSeen.add(oneof);
        message.members.push(oneof);
      }
    }
  }
  for (const oneof of allOneofs.filter((o) => oneofsSeen.has(o))) {
    message.oneofs.push(oneof);
  }
  for (const child of message.nestedMessages) {
    addFields(child, reg, mapEntries);
  }
}
function addEnum(proto, file, parent, reg) {
  var _a, _b, _c, _d, _e;
  const sharedPrefix = findEnumSharedPrefix(proto.name, proto.value);
  const desc = {
    kind: "enum",
    proto,
    deprecated: (_b = (_a = proto.options) === null || _a === void 0 ? void 0 : _a.deprecated) !== null && _b !== void 0 ? _b : false,
    file,
    parent,
    open: true,
    name: proto.name,
    typeName: makeTypeName(proto, parent, file),
    value: {},
    values: [],
    sharedPrefix,
    toString() {
      return `enum ${this.typeName}`;
    }
  };
  desc.open = isEnumOpen(desc);
  reg.add(desc);
  for (const p of proto.value) {
    const name = p.name;
    desc.values.push(
      // biome-ignore lint/suspicious/noAssignInExpressions: no
      desc.value[p.number] = {
        kind: "enum_value",
        proto: p,
        deprecated: (_d = (_c = p.options) === null || _c === void 0 ? void 0 : _c.deprecated) !== null && _d !== void 0 ? _d : false,
        parent: desc,
        name,
        localName: safeObjectProperty(sharedPrefix == void 0 ? name : name.substring(sharedPrefix.length)),
        number: p.number,
        toString() {
          return `enum value ${desc.typeName}.${name}`;
        }
      }
    );
  }
  ((_e = parent === null || parent === void 0 ? void 0 : parent.nestedEnums) !== null && _e !== void 0 ? _e : file.enums).push(desc);
}
function addMessage(proto, file, parent, reg, mapEntries) {
  var _a, _b, _c, _d;
  const desc = {
    kind: "message",
    proto,
    deprecated: (_b = (_a = proto.options) === null || _a === void 0 ? void 0 : _a.deprecated) !== null && _b !== void 0 ? _b : false,
    file,
    parent,
    name: proto.name,
    typeName: makeTypeName(proto, parent, file),
    fields: [],
    field: {},
    oneofs: [],
    members: [],
    nestedEnums: [],
    nestedMessages: [],
    nestedExtensions: [],
    toString() {
      return `message ${this.typeName}`;
    }
  };
  if (((_c = proto.options) === null || _c === void 0 ? void 0 : _c.mapEntry) === true) {
    mapEntries.add(desc);
  } else {
    ((_d = parent === null || parent === void 0 ? void 0 : parent.nestedMessages) !== null && _d !== void 0 ? _d : file.messages).push(desc);
    reg.add(desc);
  }
  for (const enumProto of proto.enumType) {
    addEnum(enumProto, file, desc, reg);
  }
  for (const messageProto of proto.nestedType) {
    addMessage(messageProto, file, desc, reg, mapEntries);
  }
}
function addService(proto, file, reg) {
  var _a, _b;
  const desc = {
    kind: "service",
    proto,
    deprecated: (_b = (_a = proto.options) === null || _a === void 0 ? void 0 : _a.deprecated) !== null && _b !== void 0 ? _b : false,
    file,
    name: proto.name,
    typeName: makeTypeName(proto, void 0, file),
    methods: [],
    method: {},
    toString() {
      return `service ${this.typeName}`;
    }
  };
  file.services.push(desc);
  reg.add(desc);
  for (const methodProto of proto.method) {
    const method = newMethod(methodProto, desc, reg);
    desc.methods.push(method);
    desc.method[method.localName] = method;
  }
}
function newMethod(proto, parent, reg) {
  var _a, _b, _c, _d;
  let methodKind;
  if (proto.clientStreaming && proto.serverStreaming) {
    methodKind = "bidi_streaming";
  } else if (proto.clientStreaming) {
    methodKind = "client_streaming";
  } else if (proto.serverStreaming) {
    methodKind = "server_streaming";
  } else {
    methodKind = "unary";
  }
  const input = reg.getMessage(trimLeadingDot(proto.inputType));
  const output = reg.getMessage(trimLeadingDot(proto.outputType));
  assert(input, `invalid MethodDescriptorProto: input_type ${proto.inputType} not found`);
  assert(output, `invalid MethodDescriptorProto: output_type ${proto.inputType} not found`);
  const name = proto.name;
  return {
    kind: "rpc",
    proto,
    deprecated: (_b = (_a = proto.options) === null || _a === void 0 ? void 0 : _a.deprecated) !== null && _b !== void 0 ? _b : false,
    parent,
    name,
    localName: safeObjectProperty(name.length ? safeObjectProperty(name[0].toLowerCase() + name.substring(1)) : name),
    methodKind,
    input,
    output,
    idempotency: (_d = (_c = proto.options) === null || _c === void 0 ? void 0 : _c.idempotencyLevel) !== null && _d !== void 0 ? _d : IDEMPOTENCY_UNKNOWN,
    toString() {
      return `rpc ${parent.typeName}.${name}`;
    }
  };
}
function newOneof(proto, parent) {
  return {
    kind: "oneof",
    proto,
    deprecated: false,
    parent,
    fields: [],
    name: proto.name,
    localName: safeObjectProperty(protoCamelCase(proto.name)),
    toString() {
      return `oneof ${parent.typeName}.${this.name}`;
    }
  };
}
function newField(proto, parentOrFile, reg, oneof, mapEntries) {
  var _a, _b, _c;
  const isExtension = mapEntries === void 0;
  const field = {
    kind: "field",
    proto,
    deprecated: (_b = (_a = proto.options) === null || _a === void 0 ? void 0 : _a.deprecated) !== null && _b !== void 0 ? _b : false,
    name: proto.name,
    number: proto.number,
    scalar: void 0,
    message: void 0,
    enum: void 0,
    presence: getFieldPresence(proto, oneof, isExtension, parentOrFile),
    listKind: void 0,
    mapKind: void 0,
    mapKey: void 0,
    delimitedEncoding: void 0,
    packed: void 0,
    longAsString: false,
    getDefaultValue: void 0
  };
  if (isExtension) {
    const file = parentOrFile.kind == "file" ? parentOrFile : parentOrFile.file;
    const parent = parentOrFile.kind == "file" ? void 0 : parentOrFile;
    const typeName = makeTypeName(proto, parent, file);
    field.kind = "extension";
    field.file = file;
    field.parent = parent;
    field.oneof = void 0;
    field.typeName = typeName;
    field.jsonName = `[${typeName}]`;
    field.toString = () => `extension ${typeName}`;
    const extendee = reg.getMessage(trimLeadingDot(proto.extendee));
    assert(extendee, `invalid FieldDescriptorProto: extendee ${proto.extendee} not found`);
    field.extendee = extendee;
  } else {
    const parent = parentOrFile;
    assert(parent.kind == "message");
    field.parent = parent;
    field.oneof = oneof;
    field.localName = oneof ? protoCamelCase(proto.name) : safeObjectProperty(protoCamelCase(proto.name));
    field.jsonName = proto.jsonName;
    field.toString = () => `field ${parent.typeName}.${proto.name}`;
  }
  const label = proto.label;
  const type = proto.type;
  const jstype = (_c = proto.options) === null || _c === void 0 ? void 0 : _c.jstype;
  if (label === LABEL_REPEATED) {
    const mapEntry = type == TYPE_MESSAGE ? mapEntries === null || mapEntries === void 0 ? void 0 : mapEntries.get(trimLeadingDot(proto.typeName)) : void 0;
    if (mapEntry) {
      field.fieldKind = "map";
      const { key, value } = findMapEntryFields(mapEntry);
      field.mapKey = key.scalar;
      field.mapKind = value.fieldKind;
      field.message = value.message;
      field.delimitedEncoding = false;
      field.enum = value.enum;
      field.scalar = value.scalar;
      return field;
    }
    field.fieldKind = "list";
    switch (type) {
      case TYPE_MESSAGE:
      case TYPE_GROUP:
        field.listKind = "message";
        field.message = reg.getMessage(trimLeadingDot(proto.typeName));
        assert(field.message);
        field.delimitedEncoding = isDelimitedEncoding(proto, parentOrFile);
        break;
      case TYPE_ENUM:
        field.listKind = "enum";
        field.enum = reg.getEnum(trimLeadingDot(proto.typeName));
        assert(field.enum);
        break;
      default:
        field.listKind = "scalar";
        field.scalar = type;
        field.longAsString = jstype == JS_STRING;
        break;
    }
    field.packed = isPackedField(proto, parentOrFile);
    return field;
  }
  switch (type) {
    case TYPE_MESSAGE:
    case TYPE_GROUP:
      field.fieldKind = "message";
      field.message = reg.getMessage(trimLeadingDot(proto.typeName));
      assert(field.message, `invalid FieldDescriptorProto: type_name ${proto.typeName} not found`);
      field.delimitedEncoding = isDelimitedEncoding(proto, parentOrFile);
      field.getDefaultValue = () => void 0;
      break;
    case TYPE_ENUM: {
      const enumeration = reg.getEnum(trimLeadingDot(proto.typeName));
      assert(enumeration !== void 0, `invalid FieldDescriptorProto: type_name ${proto.typeName} not found`);
      field.fieldKind = "enum";
      field.enum = reg.getEnum(trimLeadingDot(proto.typeName));
      field.getDefaultValue = () => {
        return unsafeIsSetExplicit(proto, "defaultValue") ? parseTextFormatEnumValue(enumeration, proto.defaultValue) : void 0;
      };
      break;
    }
    default: {
      field.fieldKind = "scalar";
      field.scalar = type;
      field.longAsString = jstype == JS_STRING;
      field.getDefaultValue = () => {
        return unsafeIsSetExplicit(proto, "defaultValue") ? parseTextFormatScalarValue(type, proto.defaultValue) : void 0;
      };
      break;
    }
  }
  return field;
}
function getFileEdition(proto) {
  switch (proto.syntax) {
    case "":
    case "proto2":
      return EDITION_PROTO22;
    case "proto3":
      return EDITION_PROTO32;
    case "editions":
      if (proto.edition in featureDefaults) {
        return proto.edition;
      }
      throw new Error(`${proto.name}: unsupported edition`);
    default:
      throw new Error(`${proto.name}: unsupported syntax "${proto.syntax}"`);
  }
}
function findFileDependencies(proto, reg) {
  return proto.dependency.map((wantName) => {
    const dep = reg.getFile(wantName);
    if (!dep) {
      throw new Error(`Cannot find ${wantName}, imported by ${proto.name}`);
    }
    return dep;
  });
}
function findEnumSharedPrefix(enumName, values) {
  const prefix = camelToSnakeCase(enumName) + "_";
  for (const value of values) {
    if (!value.name.toLowerCase().startsWith(prefix)) {
      return void 0;
    }
    const shortName = value.name.substring(prefix.length);
    if (shortName.length == 0) {
      return void 0;
    }
    if (/^\d/.test(shortName)) {
      return void 0;
    }
  }
  return prefix;
}
function camelToSnakeCase(camel) {
  return (camel.substring(0, 1) + camel.substring(1).replace(/[A-Z]/g, (c) => "_" + c)).toLowerCase();
}
function makeTypeName(proto, parent, file) {
  let typeName;
  if (parent) {
    typeName = `${parent.typeName}.${proto.name}`;
  } else if (file.proto.package.length > 0) {
    typeName = `${file.proto.package}.${proto.name}`;
  } else {
    typeName = `${proto.name}`;
  }
  return typeName;
}
function trimLeadingDot(typeName) {
  return typeName.startsWith(".") ? typeName.substring(1) : typeName;
}
function findOneof(proto, allOneofs) {
  if (!unsafeIsSetExplicit(proto, "oneofIndex")) {
    return void 0;
  }
  if (proto.proto3Optional) {
    return void 0;
  }
  const oneof = allOneofs[proto.oneofIndex];
  assert(oneof, `invalid FieldDescriptorProto: oneof #${proto.oneofIndex} for field #${proto.number} not found`);
  return oneof;
}
function getFieldPresence(proto, oneof, isExtension, parent) {
  if (proto.label == LABEL_REQUIRED) {
    return LEGACY_REQUIRED;
  }
  if (proto.label == LABEL_REPEATED) {
    return IMPLICIT3;
  }
  if (!!oneof || proto.proto3Optional) {
    return EXPLICIT;
  }
  if (isExtension) {
    return EXPLICIT;
  }
  const resolved = resolveFeature("fieldPresence", { proto, parent });
  if (resolved == IMPLICIT3 && (proto.type == TYPE_MESSAGE || proto.type == TYPE_GROUP)) {
    return EXPLICIT;
  }
  return resolved;
}
function isPackedField(proto, parent) {
  if (proto.label != LABEL_REPEATED) {
    return false;
  }
  switch (proto.type) {
    case TYPE_STRING:
    case TYPE_BYTES:
    case TYPE_GROUP:
    case TYPE_MESSAGE:
      return false;
  }
  const o = proto.options;
  if (o && unsafeIsSetExplicit(o, "packed")) {
    return o.packed;
  }
  return PACKED == resolveFeature("repeatedFieldEncoding", {
    proto,
    parent
  });
}
function findMapEntryFields(mapEntry) {
  const key = mapEntry.fields.find((f) => f.number === 1);
  const value = mapEntry.fields.find((f) => f.number === 2);
  assert(key && key.fieldKind == "scalar" && key.scalar != ScalarType.BYTES && key.scalar != ScalarType.FLOAT && key.scalar != ScalarType.DOUBLE && value && value.fieldKind != "list" && value.fieldKind != "map");
  return { key, value };
}
function isEnumOpen(desc) {
  var _a;
  return OPEN == resolveFeature("enumType", {
    proto: desc.proto,
    parent: (_a = desc.parent) !== null && _a !== void 0 ? _a : desc.file
  });
}
function isDelimitedEncoding(proto, parent) {
  if (proto.type == TYPE_GROUP) {
    return true;
  }
  return DELIMITED == resolveFeature("messageEncoding", {
    proto,
    parent
  });
}
function resolveFeature(name, ref) {
  var _a, _b;
  const featureSet = (_a = ref.proto.options) === null || _a === void 0 ? void 0 : _a.features;
  if (featureSet) {
    const val = featureSet[name];
    if (val != 0) {
      return val;
    }
  }
  if ("kind" in ref) {
    if (ref.kind == "message") {
      return resolveFeature(name, (_b = ref.parent) !== null && _b !== void 0 ? _b : ref.file);
    }
    const editionDefaults = featureDefaults[ref.edition];
    if (!editionDefaults) {
      throw new Error(`feature default for edition ${ref.edition} not found`);
    }
    return editionDefaults[name];
  }
  return resolveFeature(name, ref.parent);
}
function assert(condition, msg) {
  if (!condition) {
    throw new Error(msg);
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/codegenv2/boot.js
function boot(boot2) {
  const root = bootFileDescriptorProto(boot2);
  root.messageType.forEach(restoreJsonNames);
  const reg = createFileRegistry(root, () => void 0);
  return reg.getFile(root.name);
}
function bootFileDescriptorProto(init) {
  const proto = /* @__PURE__ */ Object.create({
    syntax: "",
    edition: 0
  });
  return Object.assign(proto, Object.assign(Object.assign({ $typeName: "google.protobuf.FileDescriptorProto", dependency: [], publicDependency: [], weakDependency: [], optionDependency: [], service: [], extension: [] }, init), { messageType: init.messageType.map(bootDescriptorProto), enumType: init.enumType.map(bootEnumDescriptorProto) }));
}
function bootDescriptorProto(init) {
  var _a, _b, _c, _d, _e, _f, _g, _h;
  const proto = /* @__PURE__ */ Object.create({
    visibility: 0
  });
  return Object.assign(proto, {
    $typeName: "google.protobuf.DescriptorProto",
    name: init.name,
    field: (_b = (_a = init.field) === null || _a === void 0 ? void 0 : _a.map(bootFieldDescriptorProto)) !== null && _b !== void 0 ? _b : [],
    extension: [],
    nestedType: (_d = (_c = init.nestedType) === null || _c === void 0 ? void 0 : _c.map(bootDescriptorProto)) !== null && _d !== void 0 ? _d : [],
    enumType: (_f = (_e = init.enumType) === null || _e === void 0 ? void 0 : _e.map(bootEnumDescriptorProto)) !== null && _f !== void 0 ? _f : [],
    extensionRange: (_h = (_g = init.extensionRange) === null || _g === void 0 ? void 0 : _g.map((e) => Object.assign({ $typeName: "google.protobuf.DescriptorProto.ExtensionRange" }, e))) !== null && _h !== void 0 ? _h : [],
    oneofDecl: [],
    reservedRange: [],
    reservedName: []
  });
}
function bootFieldDescriptorProto(init) {
  const proto = /* @__PURE__ */ Object.create({
    label: 1,
    typeName: "",
    extendee: "",
    defaultValue: "",
    oneofIndex: 0,
    jsonName: "",
    proto3Optional: false
  });
  return Object.assign(proto, Object.assign(Object.assign({ $typeName: "google.protobuf.FieldDescriptorProto" }, init), { options: init.options ? bootFieldOptions(init.options) : void 0 }));
}
function bootFieldOptions(init) {
  var _a, _b, _c;
  const proto = /* @__PURE__ */ Object.create({
    ctype: 0,
    packed: false,
    jstype: 0,
    lazy: false,
    unverifiedLazy: false,
    deprecated: false,
    weak: false,
    debugRedact: false,
    retention: 0
  });
  return Object.assign(proto, Object.assign(Object.assign({ $typeName: "google.protobuf.FieldOptions" }, init), { targets: (_a = init.targets) !== null && _a !== void 0 ? _a : [], editionDefaults: (_c = (_b = init.editionDefaults) === null || _b === void 0 ? void 0 : _b.map((e) => Object.assign({ $typeName: "google.protobuf.FieldOptions.EditionDefault" }, e))) !== null && _c !== void 0 ? _c : [], uninterpretedOption: [] }));
}
function bootEnumDescriptorProto(init) {
  const proto = /* @__PURE__ */ Object.create({
    visibility: 0
  });
  return Object.assign(proto, {
    $typeName: "google.protobuf.EnumDescriptorProto",
    name: init.name,
    reservedName: [],
    reservedRange: [],
    value: init.value.map((e) => Object.assign({ $typeName: "google.protobuf.EnumValueDescriptorProto" }, e))
  });
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/codegenv2/message.js
function messageDesc(file, path4, ...paths) {
  return paths.reduce((acc, cur) => acc.nestedMessages[cur], file.messages[path4]);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wkt/gen/google/protobuf/descriptor_pb.js
var file_google_protobuf_descriptor = /* @__PURE__ */ boot({ "name": "google/protobuf/descriptor.proto", "package": "google.protobuf", "messageType": [{ "name": "FileDescriptorSet", "field": [{ "name": "file", "number": 1, "type": 11, "label": 3, "typeName": ".google.protobuf.FileDescriptorProto" }], "extensionRange": [{ "start": 536e6, "end": 536000001 }] }, { "name": "FileDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "package", "number": 2, "type": 9, "label": 1 }, { "name": "dependency", "number": 3, "type": 9, "label": 3 }, { "name": "public_dependency", "number": 10, "type": 5, "label": 3 }, { "name": "weak_dependency", "number": 11, "type": 5, "label": 3 }, { "name": "option_dependency", "number": 15, "type": 9, "label": 3 }, { "name": "message_type", "number": 4, "type": 11, "label": 3, "typeName": ".google.protobuf.DescriptorProto" }, { "name": "enum_type", "number": 5, "type": 11, "label": 3, "typeName": ".google.protobuf.EnumDescriptorProto" }, { "name": "service", "number": 6, "type": 11, "label": 3, "typeName": ".google.protobuf.ServiceDescriptorProto" }, { "name": "extension", "number": 7, "type": 11, "label": 3, "typeName": ".google.protobuf.FieldDescriptorProto" }, { "name": "options", "number": 8, "type": 11, "label": 1, "typeName": ".google.protobuf.FileOptions" }, { "name": "source_code_info", "number": 9, "type": 11, "label": 1, "typeName": ".google.protobuf.SourceCodeInfo" }, { "name": "syntax", "number": 12, "type": 9, "label": 1 }, { "name": "edition", "number": 14, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }] }, { "name": "DescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "field", "number": 2, "type": 11, "label": 3, "typeName": ".google.protobuf.FieldDescriptorProto" }, { "name": "extension", "number": 6, "type": 11, "label": 3, "typeName": ".google.protobuf.FieldDescriptorProto" }, { "name": "nested_type", "number": 3, "type": 11, "label": 3, "typeName": ".google.protobuf.DescriptorProto" }, { "name": "enum_type", "number": 4, "type": 11, "label": 3, "typeName": ".google.protobuf.EnumDescriptorProto" }, { "name": "extension_range", "number": 5, "type": 11, "label": 3, "typeName": ".google.protobuf.DescriptorProto.ExtensionRange" }, { "name": "oneof_decl", "number": 8, "type": 11, "label": 3, "typeName": ".google.protobuf.OneofDescriptorProto" }, { "name": "options", "number": 7, "type": 11, "label": 1, "typeName": ".google.protobuf.MessageOptions" }, { "name": "reserved_range", "number": 9, "type": 11, "label": 3, "typeName": ".google.protobuf.DescriptorProto.ReservedRange" }, { "name": "reserved_name", "number": 10, "type": 9, "label": 3 }, { "name": "visibility", "number": 11, "type": 14, "label": 1, "typeName": ".google.protobuf.SymbolVisibility" }], "nestedType": [{ "name": "ExtensionRange", "field": [{ "name": "start", "number": 1, "type": 5, "label": 1 }, { "name": "end", "number": 2, "type": 5, "label": 1 }, { "name": "options", "number": 3, "type": 11, "label": 1, "typeName": ".google.protobuf.ExtensionRangeOptions" }] }, { "name": "ReservedRange", "field": [{ "name": "start", "number": 1, "type": 5, "label": 1 }, { "name": "end", "number": 2, "type": 5, "label": 1 }] }] }, { "name": "ExtensionRangeOptions", "field": [{ "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }, { "name": "declaration", "number": 2, "type": 11, "label": 3, "typeName": ".google.protobuf.ExtensionRangeOptions.Declaration", "options": { "retention": 2 } }, { "name": "features", "number": 50, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "verification", "number": 3, "type": 14, "label": 1, "typeName": ".google.protobuf.ExtensionRangeOptions.VerificationState", "defaultValue": "UNVERIFIED", "options": { "retention": 2 } }], "nestedType": [{ "name": "Declaration", "field": [{ "name": "number", "number": 1, "type": 5, "label": 1 }, { "name": "full_name", "number": 2, "type": 9, "label": 1 }, { "name": "type", "number": 3, "type": 9, "label": 1 }, { "name": "reserved", "number": 5, "type": 8, "label": 1 }, { "name": "repeated", "number": 6, "type": 8, "label": 1 }] }], "enumType": [{ "name": "VerificationState", "value": [{ "name": "DECLARATION", "number": 0 }, { "name": "UNVERIFIED", "number": 1 }] }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "FieldDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "number", "number": 3, "type": 5, "label": 1 }, { "name": "label", "number": 4, "type": 14, "label": 1, "typeName": ".google.protobuf.FieldDescriptorProto.Label" }, { "name": "type", "number": 5, "type": 14, "label": 1, "typeName": ".google.protobuf.FieldDescriptorProto.Type" }, { "name": "type_name", "number": 6, "type": 9, "label": 1 }, { "name": "extendee", "number": 2, "type": 9, "label": 1 }, { "name": "default_value", "number": 7, "type": 9, "label": 1 }, { "name": "oneof_index", "number": 9, "type": 5, "label": 1 }, { "name": "json_name", "number": 10, "type": 9, "label": 1 }, { "name": "options", "number": 8, "type": 11, "label": 1, "typeName": ".google.protobuf.FieldOptions" }, { "name": "proto3_optional", "number": 17, "type": 8, "label": 1 }], "enumType": [{ "name": "Type", "value": [{ "name": "TYPE_DOUBLE", "number": 1 }, { "name": "TYPE_FLOAT", "number": 2 }, { "name": "TYPE_INT64", "number": 3 }, { "name": "TYPE_UINT64", "number": 4 }, { "name": "TYPE_INT32", "number": 5 }, { "name": "TYPE_FIXED64", "number": 6 }, { "name": "TYPE_FIXED32", "number": 7 }, { "name": "TYPE_BOOL", "number": 8 }, { "name": "TYPE_STRING", "number": 9 }, { "name": "TYPE_GROUP", "number": 10 }, { "name": "TYPE_MESSAGE", "number": 11 }, { "name": "TYPE_BYTES", "number": 12 }, { "name": "TYPE_UINT32", "number": 13 }, { "name": "TYPE_ENUM", "number": 14 }, { "name": "TYPE_SFIXED32", "number": 15 }, { "name": "TYPE_SFIXED64", "number": 16 }, { "name": "TYPE_SINT32", "number": 17 }, { "name": "TYPE_SINT64", "number": 18 }] }, { "name": "Label", "value": [{ "name": "LABEL_OPTIONAL", "number": 1 }, { "name": "LABEL_REPEATED", "number": 3 }, { "name": "LABEL_REQUIRED", "number": 2 }] }] }, { "name": "OneofDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "options", "number": 2, "type": 11, "label": 1, "typeName": ".google.protobuf.OneofOptions" }] }, { "name": "EnumDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "value", "number": 2, "type": 11, "label": 3, "typeName": ".google.protobuf.EnumValueDescriptorProto" }, { "name": "options", "number": 3, "type": 11, "label": 1, "typeName": ".google.protobuf.EnumOptions" }, { "name": "reserved_range", "number": 4, "type": 11, "label": 3, "typeName": ".google.protobuf.EnumDescriptorProto.EnumReservedRange" }, { "name": "reserved_name", "number": 5, "type": 9, "label": 3 }, { "name": "visibility", "number": 6, "type": 14, "label": 1, "typeName": ".google.protobuf.SymbolVisibility" }], "nestedType": [{ "name": "EnumReservedRange", "field": [{ "name": "start", "number": 1, "type": 5, "label": 1 }, { "name": "end", "number": 2, "type": 5, "label": 1 }] }] }, { "name": "EnumValueDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "number", "number": 2, "type": 5, "label": 1 }, { "name": "options", "number": 3, "type": 11, "label": 1, "typeName": ".google.protobuf.EnumValueOptions" }] }, { "name": "ServiceDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "method", "number": 2, "type": 11, "label": 3, "typeName": ".google.protobuf.MethodDescriptorProto" }, { "name": "options", "number": 3, "type": 11, "label": 1, "typeName": ".google.protobuf.ServiceOptions" }] }, { "name": "MethodDescriptorProto", "field": [{ "name": "name", "number": 1, "type": 9, "label": 1 }, { "name": "input_type", "number": 2, "type": 9, "label": 1 }, { "name": "output_type", "number": 3, "type": 9, "label": 1 }, { "name": "options", "number": 4, "type": 11, "label": 1, "typeName": ".google.protobuf.MethodOptions" }, { "name": "client_streaming", "number": 5, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "server_streaming", "number": 6, "type": 8, "label": 1, "defaultValue": "false" }] }, { "name": "FileOptions", "field": [{ "name": "java_package", "number": 1, "type": 9, "label": 1 }, { "name": "java_outer_classname", "number": 8, "type": 9, "label": 1 }, { "name": "java_multiple_files", "number": 10, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "java_generate_equals_and_hash", "number": 20, "type": 8, "label": 1, "options": { "deprecated": true } }, { "name": "java_string_check_utf8", "number": 27, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "optimize_for", "number": 9, "type": 14, "label": 1, "typeName": ".google.protobuf.FileOptions.OptimizeMode", "defaultValue": "SPEED" }, { "name": "go_package", "number": 11, "type": 9, "label": 1 }, { "name": "cc_generic_services", "number": 16, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "java_generic_services", "number": 17, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "py_generic_services", "number": 18, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "deprecated", "number": 23, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "cc_enable_arenas", "number": 31, "type": 8, "label": 1, "defaultValue": "true" }, { "name": "objc_class_prefix", "number": 36, "type": 9, "label": 1 }, { "name": "csharp_namespace", "number": 37, "type": 9, "label": 1 }, { "name": "swift_prefix", "number": 39, "type": 9, "label": 1 }, { "name": "php_class_prefix", "number": 40, "type": 9, "label": 1 }, { "name": "php_namespace", "number": 41, "type": 9, "label": 1 }, { "name": "php_metadata_namespace", "number": 44, "type": 9, "label": 1 }, { "name": "ruby_package", "number": 45, "type": 9, "label": 1 }, { "name": "features", "number": 50, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "enumType": [{ "name": "OptimizeMode", "value": [{ "name": "SPEED", "number": 1 }, { "name": "CODE_SIZE", "number": 2 }, { "name": "LITE_RUNTIME", "number": 3 }] }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "MessageOptions", "field": [{ "name": "message_set_wire_format", "number": 1, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "no_standard_descriptor_accessor", "number": 2, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "deprecated", "number": 3, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "map_entry", "number": 7, "type": 8, "label": 1 }, { "name": "deprecated_legacy_json_field_conflicts", "number": 11, "type": 8, "label": 1, "options": { "deprecated": true } }, { "name": "features", "number": 12, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "FieldOptions", "field": [{ "name": "ctype", "number": 1, "type": 14, "label": 1, "typeName": ".google.protobuf.FieldOptions.CType", "defaultValue": "STRING" }, { "name": "packed", "number": 2, "type": 8, "label": 1 }, { "name": "jstype", "number": 6, "type": 14, "label": 1, "typeName": ".google.protobuf.FieldOptions.JSType", "defaultValue": "JS_NORMAL" }, { "name": "lazy", "number": 5, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "unverified_lazy", "number": 15, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "deprecated", "number": 3, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "weak", "number": 10, "type": 8, "label": 1, "defaultValue": "false", "options": { "deprecated": true } }, { "name": "debug_redact", "number": 16, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "retention", "number": 17, "type": 14, "label": 1, "typeName": ".google.protobuf.FieldOptions.OptionRetention" }, { "name": "targets", "number": 19, "type": 14, "label": 3, "typeName": ".google.protobuf.FieldOptions.OptionTargetType" }, { "name": "edition_defaults", "number": 20, "type": 11, "label": 3, "typeName": ".google.protobuf.FieldOptions.EditionDefault" }, { "name": "features", "number": 21, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "feature_support", "number": 22, "type": 11, "label": 1, "typeName": ".google.protobuf.FieldOptions.FeatureSupport" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "nestedType": [{ "name": "EditionDefault", "field": [{ "name": "edition", "number": 3, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }, { "name": "value", "number": 2, "type": 9, "label": 1 }] }, { "name": "FeatureSupport", "field": [{ "name": "edition_introduced", "number": 1, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }, { "name": "edition_deprecated", "number": 2, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }, { "name": "deprecation_warning", "number": 3, "type": 9, "label": 1 }, { "name": "edition_removed", "number": 4, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }] }], "enumType": [{ "name": "CType", "value": [{ "name": "STRING", "number": 0 }, { "name": "CORD", "number": 1 }, { "name": "STRING_PIECE", "number": 2 }] }, { "name": "JSType", "value": [{ "name": "JS_NORMAL", "number": 0 }, { "name": "JS_STRING", "number": 1 }, { "name": "JS_NUMBER", "number": 2 }] }, { "name": "OptionRetention", "value": [{ "name": "RETENTION_UNKNOWN", "number": 0 }, { "name": "RETENTION_RUNTIME", "number": 1 }, { "name": "RETENTION_SOURCE", "number": 2 }] }, { "name": "OptionTargetType", "value": [{ "name": "TARGET_TYPE_UNKNOWN", "number": 0 }, { "name": "TARGET_TYPE_FILE", "number": 1 }, { "name": "TARGET_TYPE_EXTENSION_RANGE", "number": 2 }, { "name": "TARGET_TYPE_MESSAGE", "number": 3 }, { "name": "TARGET_TYPE_FIELD", "number": 4 }, { "name": "TARGET_TYPE_ONEOF", "number": 5 }, { "name": "TARGET_TYPE_ENUM", "number": 6 }, { "name": "TARGET_TYPE_ENUM_ENTRY", "number": 7 }, { "name": "TARGET_TYPE_SERVICE", "number": 8 }, { "name": "TARGET_TYPE_METHOD", "number": 9 }] }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "OneofOptions", "field": [{ "name": "features", "number": 1, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "EnumOptions", "field": [{ "name": "allow_alias", "number": 2, "type": 8, "label": 1 }, { "name": "deprecated", "number": 3, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "deprecated_legacy_json_field_conflicts", "number": 6, "type": 8, "label": 1, "options": { "deprecated": true } }, { "name": "features", "number": 7, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "EnumValueOptions", "field": [{ "name": "deprecated", "number": 1, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "features", "number": 2, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "debug_redact", "number": 3, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "feature_support", "number": 4, "type": 11, "label": 1, "typeName": ".google.protobuf.FieldOptions.FeatureSupport" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "ServiceOptions", "field": [{ "name": "features", "number": 34, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "deprecated", "number": 33, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "MethodOptions", "field": [{ "name": "deprecated", "number": 33, "type": 8, "label": 1, "defaultValue": "false" }, { "name": "idempotency_level", "number": 34, "type": 14, "label": 1, "typeName": ".google.protobuf.MethodOptions.IdempotencyLevel", "defaultValue": "IDEMPOTENCY_UNKNOWN" }, { "name": "features", "number": 35, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "uninterpreted_option", "number": 999, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption" }], "enumType": [{ "name": "IdempotencyLevel", "value": [{ "name": "IDEMPOTENCY_UNKNOWN", "number": 0 }, { "name": "NO_SIDE_EFFECTS", "number": 1 }, { "name": "IDEMPOTENT", "number": 2 }] }], "extensionRange": [{ "start": 1e3, "end": 536870912 }] }, { "name": "UninterpretedOption", "field": [{ "name": "name", "number": 2, "type": 11, "label": 3, "typeName": ".google.protobuf.UninterpretedOption.NamePart" }, { "name": "identifier_value", "number": 3, "type": 9, "label": 1 }, { "name": "positive_int_value", "number": 4, "type": 4, "label": 1 }, { "name": "negative_int_value", "number": 5, "type": 3, "label": 1 }, { "name": "double_value", "number": 6, "type": 1, "label": 1 }, { "name": "string_value", "number": 7, "type": 12, "label": 1 }, { "name": "aggregate_value", "number": 8, "type": 9, "label": 1 }], "nestedType": [{ "name": "NamePart", "field": [{ "name": "name_part", "number": 1, "type": 9, "label": 2 }, { "name": "is_extension", "number": 2, "type": 8, "label": 2 }] }] }, { "name": "FeatureSet", "field": [{ "name": "field_presence", "number": 1, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.FieldPresence", "options": { "retention": 1, "targets": [4, 1], "editionDefaults": [{ "value": "EXPLICIT", "edition": 900 }, { "value": "IMPLICIT", "edition": 999 }, { "value": "EXPLICIT", "edition": 1e3 }] } }, { "name": "enum_type", "number": 2, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.EnumType", "options": { "retention": 1, "targets": [6, 1], "editionDefaults": [{ "value": "CLOSED", "edition": 900 }, { "value": "OPEN", "edition": 999 }] } }, { "name": "repeated_field_encoding", "number": 3, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.RepeatedFieldEncoding", "options": { "retention": 1, "targets": [4, 1], "editionDefaults": [{ "value": "EXPANDED", "edition": 900 }, { "value": "PACKED", "edition": 999 }] } }, { "name": "utf8_validation", "number": 4, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.Utf8Validation", "options": { "retention": 1, "targets": [4, 1], "editionDefaults": [{ "value": "NONE", "edition": 900 }, { "value": "VERIFY", "edition": 999 }] } }, { "name": "message_encoding", "number": 5, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.MessageEncoding", "options": { "retention": 1, "targets": [4, 1], "editionDefaults": [{ "value": "LENGTH_PREFIXED", "edition": 900 }] } }, { "name": "json_format", "number": 6, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.JsonFormat", "options": { "retention": 1, "targets": [3, 6, 1], "editionDefaults": [{ "value": "LEGACY_BEST_EFFORT", "edition": 900 }, { "value": "ALLOW", "edition": 999 }] } }, { "name": "enforce_naming_style", "number": 7, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.EnforceNamingStyle", "options": { "retention": 2, "targets": [1, 2, 3, 4, 5, 6, 7, 8, 9], "editionDefaults": [{ "value": "STYLE_LEGACY", "edition": 900 }, { "value": "STYLE2024", "edition": 1001 }] } }, { "name": "default_symbol_visibility", "number": 8, "type": 14, "label": 1, "typeName": ".google.protobuf.FeatureSet.VisibilityFeature.DefaultSymbolVisibility", "options": { "retention": 2, "targets": [1], "editionDefaults": [{ "value": "EXPORT_ALL", "edition": 900 }, { "value": "EXPORT_TOP_LEVEL", "edition": 1001 }] } }], "nestedType": [{ "name": "VisibilityFeature", "enumType": [{ "name": "DefaultSymbolVisibility", "value": [{ "name": "DEFAULT_SYMBOL_VISIBILITY_UNKNOWN", "number": 0 }, { "name": "EXPORT_ALL", "number": 1 }, { "name": "EXPORT_TOP_LEVEL", "number": 2 }, { "name": "LOCAL_ALL", "number": 3 }, { "name": "STRICT", "number": 4 }] }] }], "enumType": [{ "name": "FieldPresence", "value": [{ "name": "FIELD_PRESENCE_UNKNOWN", "number": 0 }, { "name": "EXPLICIT", "number": 1 }, { "name": "IMPLICIT", "number": 2 }, { "name": "LEGACY_REQUIRED", "number": 3 }] }, { "name": "EnumType", "value": [{ "name": "ENUM_TYPE_UNKNOWN", "number": 0 }, { "name": "OPEN", "number": 1 }, { "name": "CLOSED", "number": 2 }] }, { "name": "RepeatedFieldEncoding", "value": [{ "name": "REPEATED_FIELD_ENCODING_UNKNOWN", "number": 0 }, { "name": "PACKED", "number": 1 }, { "name": "EXPANDED", "number": 2 }] }, { "name": "Utf8Validation", "value": [{ "name": "UTF8_VALIDATION_UNKNOWN", "number": 0 }, { "name": "VERIFY", "number": 2 }, { "name": "NONE", "number": 3 }] }, { "name": "MessageEncoding", "value": [{ "name": "MESSAGE_ENCODING_UNKNOWN", "number": 0 }, { "name": "LENGTH_PREFIXED", "number": 1 }, { "name": "DELIMITED", "number": 2 }] }, { "name": "JsonFormat", "value": [{ "name": "JSON_FORMAT_UNKNOWN", "number": 0 }, { "name": "ALLOW", "number": 1 }, { "name": "LEGACY_BEST_EFFORT", "number": 2 }] }, { "name": "EnforceNamingStyle", "value": [{ "name": "ENFORCE_NAMING_STYLE_UNKNOWN", "number": 0 }, { "name": "STYLE2024", "number": 1 }, { "name": "STYLE_LEGACY", "number": 2 }] }], "extensionRange": [{ "start": 1e3, "end": 9995 }, { "start": 9995, "end": 1e4 }, { "start": 1e4, "end": 10001 }] }, { "name": "FeatureSetDefaults", "field": [{ "name": "defaults", "number": 1, "type": 11, "label": 3, "typeName": ".google.protobuf.FeatureSetDefaults.FeatureSetEditionDefault" }, { "name": "minimum_edition", "number": 4, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }, { "name": "maximum_edition", "number": 5, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }], "nestedType": [{ "name": "FeatureSetEditionDefault", "field": [{ "name": "edition", "number": 3, "type": 14, "label": 1, "typeName": ".google.protobuf.Edition" }, { "name": "overridable_features", "number": 4, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }, { "name": "fixed_features", "number": 5, "type": 11, "label": 1, "typeName": ".google.protobuf.FeatureSet" }] }] }, { "name": "SourceCodeInfo", "field": [{ "name": "location", "number": 1, "type": 11, "label": 3, "typeName": ".google.protobuf.SourceCodeInfo.Location" }], "nestedType": [{ "name": "Location", "field": [{ "name": "path", "number": 1, "type": 5, "label": 3, "options": { "packed": true } }, { "name": "span", "number": 2, "type": 5, "label": 3, "options": { "packed": true } }, { "name": "leading_comments", "number": 3, "type": 9, "label": 1 }, { "name": "trailing_comments", "number": 4, "type": 9, "label": 1 }, { "name": "leading_detached_comments", "number": 6, "type": 9, "label": 3 }] }], "extensionRange": [{ "start": 536e6, "end": 536000001 }] }, { "name": "GeneratedCodeInfo", "field": [{ "name": "annotation", "number": 1, "type": 11, "label": 3, "typeName": ".google.protobuf.GeneratedCodeInfo.Annotation" }], "nestedType": [{ "name": "Annotation", "field": [{ "name": "path", "number": 1, "type": 5, "label": 3, "options": { "packed": true } }, { "name": "source_file", "number": 2, "type": 9, "label": 1 }, { "name": "begin", "number": 3, "type": 5, "label": 1 }, { "name": "end", "number": 4, "type": 5, "label": 1 }, { "name": "semantic", "number": 5, "type": 14, "label": 1, "typeName": ".google.protobuf.GeneratedCodeInfo.Annotation.Semantic" }], "enumType": [{ "name": "Semantic", "value": [{ "name": "NONE", "number": 0 }, { "name": "SET", "number": 1 }, { "name": "ALIAS", "number": 2 }] }] }] }], "enumType": [{ "name": "Edition", "value": [{ "name": "EDITION_UNKNOWN", "number": 0 }, { "name": "EDITION_LEGACY", "number": 900 }, { "name": "EDITION_PROTO2", "number": 998 }, { "name": "EDITION_PROTO3", "number": 999 }, { "name": "EDITION_2023", "number": 1e3 }, { "name": "EDITION_2024", "number": 1001 }, { "name": "EDITION_UNSTABLE", "number": 9999 }, { "name": "EDITION_1_TEST_ONLY", "number": 1 }, { "name": "EDITION_2_TEST_ONLY", "number": 2 }, { "name": "EDITION_99997_TEST_ONLY", "number": 99997 }, { "name": "EDITION_99998_TEST_ONLY", "number": 99998 }, { "name": "EDITION_99999_TEST_ONLY", "number": 99999 }, { "name": "EDITION_MAX", "number": 2147483647 }] }, { "name": "SymbolVisibility", "value": [{ "name": "VISIBILITY_UNSET", "number": 0 }, { "name": "VISIBILITY_LOCAL", "number": 1 }, { "name": "VISIBILITY_EXPORT", "number": 2 }] }] });
var FileDescriptorProtoSchema = /* @__PURE__ */ messageDesc(file_google_protobuf_descriptor, 1);
var ExtensionRangeOptions_VerificationState;
(function(ExtensionRangeOptions_VerificationState2) {
  ExtensionRangeOptions_VerificationState2[ExtensionRangeOptions_VerificationState2["DECLARATION"] = 0] = "DECLARATION";
  ExtensionRangeOptions_VerificationState2[ExtensionRangeOptions_VerificationState2["UNVERIFIED"] = 1] = "UNVERIFIED";
})(ExtensionRangeOptions_VerificationState || (ExtensionRangeOptions_VerificationState = {}));
var FieldDescriptorProto_Type;
(function(FieldDescriptorProto_Type2) {
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["DOUBLE"] = 1] = "DOUBLE";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["FLOAT"] = 2] = "FLOAT";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["INT64"] = 3] = "INT64";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["UINT64"] = 4] = "UINT64";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["INT32"] = 5] = "INT32";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["FIXED64"] = 6] = "FIXED64";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["FIXED32"] = 7] = "FIXED32";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["BOOL"] = 8] = "BOOL";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["STRING"] = 9] = "STRING";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["GROUP"] = 10] = "GROUP";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["MESSAGE"] = 11] = "MESSAGE";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["BYTES"] = 12] = "BYTES";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["UINT32"] = 13] = "UINT32";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["ENUM"] = 14] = "ENUM";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["SFIXED32"] = 15] = "SFIXED32";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["SFIXED64"] = 16] = "SFIXED64";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["SINT32"] = 17] = "SINT32";
  FieldDescriptorProto_Type2[FieldDescriptorProto_Type2["SINT64"] = 18] = "SINT64";
})(FieldDescriptorProto_Type || (FieldDescriptorProto_Type = {}));
var FieldDescriptorProto_Label;
(function(FieldDescriptorProto_Label2) {
  FieldDescriptorProto_Label2[FieldDescriptorProto_Label2["OPTIONAL"] = 1] = "OPTIONAL";
  FieldDescriptorProto_Label2[FieldDescriptorProto_Label2["REPEATED"] = 3] = "REPEATED";
  FieldDescriptorProto_Label2[FieldDescriptorProto_Label2["REQUIRED"] = 2] = "REQUIRED";
})(FieldDescriptorProto_Label || (FieldDescriptorProto_Label = {}));
var FileOptions_OptimizeMode;
(function(FileOptions_OptimizeMode2) {
  FileOptions_OptimizeMode2[FileOptions_OptimizeMode2["SPEED"] = 1] = "SPEED";
  FileOptions_OptimizeMode2[FileOptions_OptimizeMode2["CODE_SIZE"] = 2] = "CODE_SIZE";
  FileOptions_OptimizeMode2[FileOptions_OptimizeMode2["LITE_RUNTIME"] = 3] = "LITE_RUNTIME";
})(FileOptions_OptimizeMode || (FileOptions_OptimizeMode = {}));
var FieldOptions_CType;
(function(FieldOptions_CType2) {
  FieldOptions_CType2[FieldOptions_CType2["STRING"] = 0] = "STRING";
  FieldOptions_CType2[FieldOptions_CType2["CORD"] = 1] = "CORD";
  FieldOptions_CType2[FieldOptions_CType2["STRING_PIECE"] = 2] = "STRING_PIECE";
})(FieldOptions_CType || (FieldOptions_CType = {}));
var FieldOptions_JSType;
(function(FieldOptions_JSType2) {
  FieldOptions_JSType2[FieldOptions_JSType2["JS_NORMAL"] = 0] = "JS_NORMAL";
  FieldOptions_JSType2[FieldOptions_JSType2["JS_STRING"] = 1] = "JS_STRING";
  FieldOptions_JSType2[FieldOptions_JSType2["JS_NUMBER"] = 2] = "JS_NUMBER";
})(FieldOptions_JSType || (FieldOptions_JSType = {}));
var FieldOptions_OptionRetention;
(function(FieldOptions_OptionRetention2) {
  FieldOptions_OptionRetention2[FieldOptions_OptionRetention2["RETENTION_UNKNOWN"] = 0] = "RETENTION_UNKNOWN";
  FieldOptions_OptionRetention2[FieldOptions_OptionRetention2["RETENTION_RUNTIME"] = 1] = "RETENTION_RUNTIME";
  FieldOptions_OptionRetention2[FieldOptions_OptionRetention2["RETENTION_SOURCE"] = 2] = "RETENTION_SOURCE";
})(FieldOptions_OptionRetention || (FieldOptions_OptionRetention = {}));
var FieldOptions_OptionTargetType;
(function(FieldOptions_OptionTargetType2) {
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_UNKNOWN"] = 0] = "TARGET_TYPE_UNKNOWN";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_FILE"] = 1] = "TARGET_TYPE_FILE";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_EXTENSION_RANGE"] = 2] = "TARGET_TYPE_EXTENSION_RANGE";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_MESSAGE"] = 3] = "TARGET_TYPE_MESSAGE";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_FIELD"] = 4] = "TARGET_TYPE_FIELD";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_ONEOF"] = 5] = "TARGET_TYPE_ONEOF";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_ENUM"] = 6] = "TARGET_TYPE_ENUM";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_ENUM_ENTRY"] = 7] = "TARGET_TYPE_ENUM_ENTRY";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_SERVICE"] = 8] = "TARGET_TYPE_SERVICE";
  FieldOptions_OptionTargetType2[FieldOptions_OptionTargetType2["TARGET_TYPE_METHOD"] = 9] = "TARGET_TYPE_METHOD";
})(FieldOptions_OptionTargetType || (FieldOptions_OptionTargetType = {}));
var MethodOptions_IdempotencyLevel;
(function(MethodOptions_IdempotencyLevel2) {
  MethodOptions_IdempotencyLevel2[MethodOptions_IdempotencyLevel2["IDEMPOTENCY_UNKNOWN"] = 0] = "IDEMPOTENCY_UNKNOWN";
  MethodOptions_IdempotencyLevel2[MethodOptions_IdempotencyLevel2["NO_SIDE_EFFECTS"] = 1] = "NO_SIDE_EFFECTS";
  MethodOptions_IdempotencyLevel2[MethodOptions_IdempotencyLevel2["IDEMPOTENT"] = 2] = "IDEMPOTENT";
})(MethodOptions_IdempotencyLevel || (MethodOptions_IdempotencyLevel = {}));
var FeatureSet_VisibilityFeature_DefaultSymbolVisibility;
(function(FeatureSet_VisibilityFeature_DefaultSymbolVisibility2) {
  FeatureSet_VisibilityFeature_DefaultSymbolVisibility2[FeatureSet_VisibilityFeature_DefaultSymbolVisibility2["DEFAULT_SYMBOL_VISIBILITY_UNKNOWN"] = 0] = "DEFAULT_SYMBOL_VISIBILITY_UNKNOWN";
  FeatureSet_VisibilityFeature_DefaultSymbolVisibility2[FeatureSet_VisibilityFeature_DefaultSymbolVisibility2["EXPORT_ALL"] = 1] = "EXPORT_ALL";
  FeatureSet_VisibilityFeature_DefaultSymbolVisibility2[FeatureSet_VisibilityFeature_DefaultSymbolVisibility2["EXPORT_TOP_LEVEL"] = 2] = "EXPORT_TOP_LEVEL";
  FeatureSet_VisibilityFeature_DefaultSymbolVisibility2[FeatureSet_VisibilityFeature_DefaultSymbolVisibility2["LOCAL_ALL"] = 3] = "LOCAL_ALL";
  FeatureSet_VisibilityFeature_DefaultSymbolVisibility2[FeatureSet_VisibilityFeature_DefaultSymbolVisibility2["STRICT"] = 4] = "STRICT";
})(FeatureSet_VisibilityFeature_DefaultSymbolVisibility || (FeatureSet_VisibilityFeature_DefaultSymbolVisibility = {}));
var FeatureSet_FieldPresence;
(function(FeatureSet_FieldPresence2) {
  FeatureSet_FieldPresence2[FeatureSet_FieldPresence2["FIELD_PRESENCE_UNKNOWN"] = 0] = "FIELD_PRESENCE_UNKNOWN";
  FeatureSet_FieldPresence2[FeatureSet_FieldPresence2["EXPLICIT"] = 1] = "EXPLICIT";
  FeatureSet_FieldPresence2[FeatureSet_FieldPresence2["IMPLICIT"] = 2] = "IMPLICIT";
  FeatureSet_FieldPresence2[FeatureSet_FieldPresence2["LEGACY_REQUIRED"] = 3] = "LEGACY_REQUIRED";
})(FeatureSet_FieldPresence || (FeatureSet_FieldPresence = {}));
var FeatureSet_EnumType;
(function(FeatureSet_EnumType2) {
  FeatureSet_EnumType2[FeatureSet_EnumType2["ENUM_TYPE_UNKNOWN"] = 0] = "ENUM_TYPE_UNKNOWN";
  FeatureSet_EnumType2[FeatureSet_EnumType2["OPEN"] = 1] = "OPEN";
  FeatureSet_EnumType2[FeatureSet_EnumType2["CLOSED"] = 2] = "CLOSED";
})(FeatureSet_EnumType || (FeatureSet_EnumType = {}));
var FeatureSet_RepeatedFieldEncoding;
(function(FeatureSet_RepeatedFieldEncoding2) {
  FeatureSet_RepeatedFieldEncoding2[FeatureSet_RepeatedFieldEncoding2["REPEATED_FIELD_ENCODING_UNKNOWN"] = 0] = "REPEATED_FIELD_ENCODING_UNKNOWN";
  FeatureSet_RepeatedFieldEncoding2[FeatureSet_RepeatedFieldEncoding2["PACKED"] = 1] = "PACKED";
  FeatureSet_RepeatedFieldEncoding2[FeatureSet_RepeatedFieldEncoding2["EXPANDED"] = 2] = "EXPANDED";
})(FeatureSet_RepeatedFieldEncoding || (FeatureSet_RepeatedFieldEncoding = {}));
var FeatureSet_Utf8Validation;
(function(FeatureSet_Utf8Validation2) {
  FeatureSet_Utf8Validation2[FeatureSet_Utf8Validation2["UTF8_VALIDATION_UNKNOWN"] = 0] = "UTF8_VALIDATION_UNKNOWN";
  FeatureSet_Utf8Validation2[FeatureSet_Utf8Validation2["VERIFY"] = 2] = "VERIFY";
  FeatureSet_Utf8Validation2[FeatureSet_Utf8Validation2["NONE"] = 3] = "NONE";
})(FeatureSet_Utf8Validation || (FeatureSet_Utf8Validation = {}));
var FeatureSet_MessageEncoding;
(function(FeatureSet_MessageEncoding2) {
  FeatureSet_MessageEncoding2[FeatureSet_MessageEncoding2["MESSAGE_ENCODING_UNKNOWN"] = 0] = "MESSAGE_ENCODING_UNKNOWN";
  FeatureSet_MessageEncoding2[FeatureSet_MessageEncoding2["LENGTH_PREFIXED"] = 1] = "LENGTH_PREFIXED";
  FeatureSet_MessageEncoding2[FeatureSet_MessageEncoding2["DELIMITED"] = 2] = "DELIMITED";
})(FeatureSet_MessageEncoding || (FeatureSet_MessageEncoding = {}));
var FeatureSet_JsonFormat;
(function(FeatureSet_JsonFormat2) {
  FeatureSet_JsonFormat2[FeatureSet_JsonFormat2["JSON_FORMAT_UNKNOWN"] = 0] = "JSON_FORMAT_UNKNOWN";
  FeatureSet_JsonFormat2[FeatureSet_JsonFormat2["ALLOW"] = 1] = "ALLOW";
  FeatureSet_JsonFormat2[FeatureSet_JsonFormat2["LEGACY_BEST_EFFORT"] = 2] = "LEGACY_BEST_EFFORT";
})(FeatureSet_JsonFormat || (FeatureSet_JsonFormat = {}));
var FeatureSet_EnforceNamingStyle;
(function(FeatureSet_EnforceNamingStyle2) {
  FeatureSet_EnforceNamingStyle2[FeatureSet_EnforceNamingStyle2["ENFORCE_NAMING_STYLE_UNKNOWN"] = 0] = "ENFORCE_NAMING_STYLE_UNKNOWN";
  FeatureSet_EnforceNamingStyle2[FeatureSet_EnforceNamingStyle2["STYLE2024"] = 1] = "STYLE2024";
  FeatureSet_EnforceNamingStyle2[FeatureSet_EnforceNamingStyle2["STYLE_LEGACY"] = 2] = "STYLE_LEGACY";
})(FeatureSet_EnforceNamingStyle || (FeatureSet_EnforceNamingStyle = {}));
var GeneratedCodeInfo_Annotation_Semantic;
(function(GeneratedCodeInfo_Annotation_Semantic2) {
  GeneratedCodeInfo_Annotation_Semantic2[GeneratedCodeInfo_Annotation_Semantic2["NONE"] = 0] = "NONE";
  GeneratedCodeInfo_Annotation_Semantic2[GeneratedCodeInfo_Annotation_Semantic2["SET"] = 1] = "SET";
  GeneratedCodeInfo_Annotation_Semantic2[GeneratedCodeInfo_Annotation_Semantic2["ALIAS"] = 2] = "ALIAS";
})(GeneratedCodeInfo_Annotation_Semantic || (GeneratedCodeInfo_Annotation_Semantic = {}));
var Edition;
(function(Edition2) {
  Edition2[Edition2["EDITION_UNKNOWN"] = 0] = "EDITION_UNKNOWN";
  Edition2[Edition2["EDITION_LEGACY"] = 900] = "EDITION_LEGACY";
  Edition2[Edition2["EDITION_PROTO2"] = 998] = "EDITION_PROTO2";
  Edition2[Edition2["EDITION_PROTO3"] = 999] = "EDITION_PROTO3";
  Edition2[Edition2["EDITION_2023"] = 1e3] = "EDITION_2023";
  Edition2[Edition2["EDITION_2024"] = 1001] = "EDITION_2024";
  Edition2[Edition2["EDITION_UNSTABLE"] = 9999] = "EDITION_UNSTABLE";
  Edition2[Edition2["EDITION_1_TEST_ONLY"] = 1] = "EDITION_1_TEST_ONLY";
  Edition2[Edition2["EDITION_2_TEST_ONLY"] = 2] = "EDITION_2_TEST_ONLY";
  Edition2[Edition2["EDITION_99997_TEST_ONLY"] = 99997] = "EDITION_99997_TEST_ONLY";
  Edition2[Edition2["EDITION_99998_TEST_ONLY"] = 99998] = "EDITION_99998_TEST_ONLY";
  Edition2[Edition2["EDITION_99999_TEST_ONLY"] = 99999] = "EDITION_99999_TEST_ONLY";
  Edition2[Edition2["EDITION_MAX"] = 2147483647] = "EDITION_MAX";
})(Edition || (Edition = {}));
var SymbolVisibility;
(function(SymbolVisibility2) {
  SymbolVisibility2[SymbolVisibility2["VISIBILITY_UNSET"] = 0] = "VISIBILITY_UNSET";
  SymbolVisibility2[SymbolVisibility2["VISIBILITY_LOCAL"] = 1] = "VISIBILITY_LOCAL";
  SymbolVisibility2[SymbolVisibility2["VISIBILITY_EXPORT"] = 2] = "VISIBILITY_EXPORT";
})(SymbolVisibility || (SymbolVisibility = {}));

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/from-binary.js
var readDefaults = {
  readUnknownFields: true
};
function makeReadOptions(options) {
  return options ? Object.assign(Object.assign({}, readDefaults), options) : readDefaults;
}
function fromBinary(schema, bytes, options) {
  const msg = reflect(schema, void 0, false);
  readMessage(msg, new BinaryReader(bytes), makeReadOptions(options), false, bytes.byteLength);
  return msg.message;
}
function readMessage(message, reader, options, delimited, lengthOrDelimitedFieldNo) {
  var _a;
  const end = delimited ? reader.len : reader.pos + lengthOrDelimitedFieldNo;
  let fieldNo;
  let wireType;
  const unknownFields = (_a = message.getUnknown()) !== null && _a !== void 0 ? _a : [];
  while (reader.pos < end) {
    [fieldNo, wireType] = reader.tag();
    if (delimited && wireType == WireType.EndGroup) {
      break;
    }
    const field = message.findNumber(fieldNo);
    if (!field) {
      const data = reader.skip(wireType, fieldNo);
      if (options.readUnknownFields) {
        unknownFields.push({ no: fieldNo, wireType, data });
      }
      continue;
    }
    readField(message, reader, field, wireType, options);
  }
  if (delimited) {
    if (wireType != WireType.EndGroup || fieldNo !== lengthOrDelimitedFieldNo) {
      throw new Error("invalid end group tag");
    }
  }
  if (unknownFields.length > 0) {
    message.setUnknown(unknownFields);
  }
}
function readField(message, reader, field, wireType, options) {
  var _a;
  switch (field.fieldKind) {
    case "scalar":
      message.set(field, readScalar(reader, field.scalar));
      break;
    case "enum":
      const val = readScalar(reader, ScalarType.INT32);
      if (field.enum.open) {
        message.set(field, val);
      } else {
        const ok2 = field.enum.values.some((v) => v.number === val);
        if (ok2) {
          message.set(field, val);
        } else if (options.readUnknownFields) {
          const bytes = [];
          varint32write(val, bytes);
          const unknownFields = (_a = message.getUnknown()) !== null && _a !== void 0 ? _a : [];
          unknownFields.push({
            no: field.number,
            wireType,
            data: new Uint8Array(bytes)
          });
          message.setUnknown(unknownFields);
        }
      }
      break;
    case "message":
      message.set(field, readMessageField(reader, options, field, message.get(field)));
      break;
    case "list":
      readListField(reader, wireType, message.get(field), options);
      break;
    case "map":
      readMapEntry(reader, message.get(field), options);
      break;
  }
}
function readMapEntry(reader, map, options) {
  const field = map.field();
  let key;
  let val;
  const len = reader.uint32();
  const end = reader.pos + len;
  while (reader.pos < end) {
    const [fieldNo] = reader.tag();
    switch (fieldNo) {
      case 1:
        key = readScalar(reader, field.mapKey);
        break;
      case 2:
        switch (field.mapKind) {
          case "scalar":
            val = readScalar(reader, field.scalar);
            break;
          case "enum":
            val = reader.int32();
            break;
          case "message":
            val = readMessageField(reader, options, field);
            break;
        }
        break;
    }
  }
  if (key === void 0) {
    key = scalarZeroValue(field.mapKey, false);
  }
  if (val === void 0) {
    switch (field.mapKind) {
      case "scalar":
        val = scalarZeroValue(field.scalar, false);
        break;
      case "enum":
        val = field.enum.values[0].number;
        break;
      case "message":
        val = reflect(field.message, void 0, false);
        break;
    }
  }
  map.set(key, val);
}
function readListField(reader, wireType, list, options) {
  var _a;
  const field = list.field();
  if (field.listKind === "message") {
    list.add(readMessageField(reader, options, field));
    return;
  }
  const scalarType = (_a = field.scalar) !== null && _a !== void 0 ? _a : ScalarType.INT32;
  const packed = wireType == WireType.LengthDelimited && scalarType != ScalarType.STRING && scalarType != ScalarType.BYTES;
  if (!packed) {
    list.add(readScalar(reader, scalarType));
    return;
  }
  const e = reader.uint32() + reader.pos;
  while (reader.pos < e) {
    list.add(readScalar(reader, scalarType));
  }
}
function readMessageField(reader, options, field, mergeMessage) {
  const delimited = field.delimitedEncoding;
  const message = mergeMessage !== null && mergeMessage !== void 0 ? mergeMessage : reflect(field.message, void 0, false);
  readMessage(message, reader, options, delimited, delimited ? field.number : reader.uint32());
  return message;
}
function readScalar(reader, type) {
  switch (type) {
    case ScalarType.STRING:
      return reader.string();
    case ScalarType.BOOL:
      return reader.bool();
    case ScalarType.DOUBLE:
      return reader.double();
    case ScalarType.FLOAT:
      return reader.float();
    case ScalarType.INT32:
      return reader.int32();
    case ScalarType.INT64:
      return reader.int64();
    case ScalarType.UINT64:
      return reader.uint64();
    case ScalarType.FIXED64:
      return reader.fixed64();
    case ScalarType.BYTES:
      return reader.bytes();
    case ScalarType.FIXED32:
      return reader.fixed32();
    case ScalarType.SFIXED32:
      return reader.sfixed32();
    case ScalarType.SFIXED64:
      return reader.sfixed64();
    case ScalarType.SINT64:
      return reader.sint64();
    case ScalarType.UINT32:
      return reader.uint32();
    case ScalarType.SINT32:
      return reader.sint32();
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/codegenv2/file.js
function fileDesc(b64, imports) {
  var _a;
  const root = fromBinary(FileDescriptorProtoSchema, base64Decode(b64));
  root.messageType.forEach(restoreJsonNames);
  root.dependency = (_a = imports === null || imports === void 0 ? void 0 : imports.map((f) => f.proto.name)) !== null && _a !== void 0 ? _a : [];
  const reg = createFileRegistry(root, (protoFileName) => imports === null || imports === void 0 ? void 0 : imports.find((f) => f.proto.name === protoFileName));
  return reg.getFile(root.name);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wkt/gen/google/protobuf/any_pb.js
var file_google_protobuf_any = /* @__PURE__ */ fileDesc("Chlnb29nbGUvcHJvdG9idWYvYW55LnByb3RvEg9nb29nbGUucHJvdG9idWYiJgoDQW55EhAKCHR5cGVfdXJsGAEgASgJEg0KBXZhbHVlGAIgASgMQnYKE2NvbS5nb29nbGUucHJvdG9idWZCCEFueVByb3RvUAFaLGdvb2dsZS5nb2xhbmcub3JnL3Byb3RvYnVmL3R5cGVzL2tub3duL2FueXBiogIDR1BCqgIeR29vZ2xlLlByb3RvYnVmLldlbGxLbm93blR5cGVzYgZwcm90bzM");
var AnySchema = /* @__PURE__ */ messageDesc(file_google_protobuf_any, 0);

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/to-binary.js
var LEGACY_REQUIRED2 = 3;
var writeDefaults = {
  writeUnknownFields: true
};
function makeWriteOptions(options) {
  return options ? Object.assign(Object.assign({}, writeDefaults), options) : writeDefaults;
}
function toBinary(schema, message, options) {
  return writeFields(new BinaryWriter(), makeWriteOptions(options), reflect(schema, message)).finish();
}
function writeFields(writer, opts, msg) {
  var _a;
  for (const f of msg.sortedFields) {
    if (!msg.isSet(f)) {
      if (f.presence == LEGACY_REQUIRED2) {
        throw new Error(`cannot encode ${f} to binary: required field not set`);
      }
      continue;
    }
    writeField(writer, opts, msg, f);
  }
  if (opts.writeUnknownFields) {
    for (const { no, wireType, data } of (_a = msg.getUnknown()) !== null && _a !== void 0 ? _a : []) {
      writer.tag(no, wireType).raw(data);
    }
  }
  return writer;
}
function writeField(writer, opts, msg, field) {
  var _a;
  switch (field.fieldKind) {
    case "scalar":
    case "enum":
      writeScalar(writer, msg.desc.typeName, field.name, (_a = field.scalar) !== null && _a !== void 0 ? _a : ScalarType.INT32, field.number, msg.get(field));
      break;
    case "list":
      writeListField(writer, opts, field, msg.get(field));
      break;
    case "message":
      writeMessageField(writer, opts, field, msg.get(field));
      break;
    case "map":
      for (const [key, val] of msg.get(field)) {
        writeMapEntry(writer, opts, field, key, val);
      }
      break;
  }
}
function writeScalar(writer, msgName, fieldName, scalarType, fieldNo, value) {
  writeScalarValue(writer.tag(fieldNo, writeTypeOfScalar(scalarType)), msgName, fieldName, scalarType, value);
}
function writeMessageField(writer, opts, field, message) {
  if (field.delimitedEncoding) {
    writeFields(writer.tag(field.number, WireType.StartGroup), opts, message).tag(field.number, WireType.EndGroup);
  } else {
    writeFields(writer.tag(field.number, WireType.LengthDelimited).fork(), opts, message).join();
  }
}
function writeListField(writer, opts, field, list) {
  var _a;
  if (field.listKind == "message") {
    for (const item of list) {
      writeMessageField(writer, opts, field, item);
    }
    return;
  }
  const scalarType = (_a = field.scalar) !== null && _a !== void 0 ? _a : ScalarType.INT32;
  if (field.packed) {
    if (!list.size) {
      return;
    }
    writer.tag(field.number, WireType.LengthDelimited).fork();
    for (const item of list) {
      writeScalarValue(writer, field.parent.typeName, field.name, scalarType, item);
    }
    writer.join();
    return;
  }
  for (const item of list) {
    writeScalar(writer, field.parent.typeName, field.name, scalarType, field.number, item);
  }
}
function writeMapEntry(writer, opts, field, key, value) {
  var _a;
  writer.tag(field.number, WireType.LengthDelimited).fork();
  writeScalar(writer, field.parent.typeName, field.name, field.mapKey, 1, key);
  switch (field.mapKind) {
    case "scalar":
    case "enum":
      writeScalar(writer, field.parent.typeName, field.name, (_a = field.scalar) !== null && _a !== void 0 ? _a : ScalarType.INT32, 2, value);
      break;
    case "message":
      writeFields(writer.tag(2, WireType.LengthDelimited).fork(), opts, value).join();
      break;
  }
  writer.join();
}
function writeScalarValue(writer, msgName, fieldName, type, value) {
  try {
    switch (type) {
      case ScalarType.STRING:
        writer.string(value);
        break;
      case ScalarType.BOOL:
        writer.bool(value);
        break;
      case ScalarType.DOUBLE:
        writer.double(value);
        break;
      case ScalarType.FLOAT:
        writer.float(value);
        break;
      case ScalarType.INT32:
        writer.int32(value);
        break;
      case ScalarType.INT64:
        writer.int64(value);
        break;
      case ScalarType.UINT64:
        writer.uint64(value);
        break;
      case ScalarType.FIXED64:
        writer.fixed64(value);
        break;
      case ScalarType.BYTES:
        writer.bytes(value);
        break;
      case ScalarType.FIXED32:
        writer.fixed32(value);
        break;
      case ScalarType.SFIXED32:
        writer.sfixed32(value);
        break;
      case ScalarType.SFIXED64:
        writer.sfixed64(value);
        break;
      case ScalarType.SINT64:
        writer.sint64(value);
        break;
      case ScalarType.UINT32:
        writer.uint32(value);
        break;
      case ScalarType.SINT32:
        writer.sint32(value);
        break;
    }
  } catch (e) {
    if (e instanceof Error) {
      throw new Error(`cannot encode field ${msgName}.${fieldName} to binary: ${e.message}`);
    }
    throw e;
  }
}
function writeTypeOfScalar(type) {
  switch (type) {
    case ScalarType.BYTES:
    case ScalarType.STRING:
      return WireType.LengthDelimited;
    case ScalarType.DOUBLE:
    case ScalarType.FIXED64:
    case ScalarType.SFIXED64:
      return WireType.Bit64;
    case ScalarType.FIXED32:
    case ScalarType.SFIXED32:
    case ScalarType.FLOAT:
      return WireType.Bit32;
    default:
      return WireType.Varint;
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wkt/any.js
function anyPack(schema, message, into) {
  let ret = false;
  if (!into) {
    into = create(AnySchema);
    ret = true;
  }
  into.value = toBinary(schema, message);
  into.typeUrl = typeNameToUrl(message.$typeName);
  return ret ? into : void 0;
}
function anyIs(any, descOrTypeName) {
  if (any.typeUrl === "") {
    return false;
  }
  const want = typeof descOrTypeName == "string" ? descOrTypeName : descOrTypeName.typeName;
  const got = typeUrlToName(any.typeUrl);
  return want === got;
}
function anyUnpack(any, registryOrMessageDesc) {
  if (any.typeUrl === "") {
    return void 0;
  }
  const desc = registryOrMessageDesc.kind == "message" ? registryOrMessageDesc : registryOrMessageDesc.getMessage(typeUrlToName(any.typeUrl));
  if (!desc || !anyIs(any, desc)) {
    return void 0;
  }
  return fromBinary(desc, any.value);
}
function typeNameToUrl(name) {
  return `type.googleapis.com/${name}`;
}
function typeUrlToName(url) {
  const slash = url.lastIndexOf("/");
  const name = slash >= 0 ? url.substring(slash + 1) : url;
  if (!name.length) {
    throw new Error(`invalid type url: ${url}`);
  }
  return name;
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/wkt/gen/google/protobuf/struct_pb.js
var file_google_protobuf_struct = /* @__PURE__ */ fileDesc("Chxnb29nbGUvcHJvdG9idWYvc3RydWN0LnByb3RvEg9nb29nbGUucHJvdG9idWYihAEKBlN0cnVjdBIzCgZmaWVsZHMYASADKAsyIy5nb29nbGUucHJvdG9idWYuU3RydWN0LkZpZWxkc0VudHJ5GkUKC0ZpZWxkc0VudHJ5EgsKA2tleRgBIAEoCRIlCgV2YWx1ZRgCIAEoCzIWLmdvb2dsZS5wcm90b2J1Zi5WYWx1ZToCOAEi6gEKBVZhbHVlEjAKCm51bGxfdmFsdWUYASABKA4yGi5nb29nbGUucHJvdG9idWYuTnVsbFZhbHVlSAASFgoMbnVtYmVyX3ZhbHVlGAIgASgBSAASFgoMc3RyaW5nX3ZhbHVlGAMgASgJSAASFAoKYm9vbF92YWx1ZRgEIAEoCEgAEi8KDHN0cnVjdF92YWx1ZRgFIAEoCzIXLmdvb2dsZS5wcm90b2J1Zi5TdHJ1Y3RIABIwCgpsaXN0X3ZhbHVlGAYgASgLMhouZ29vZ2xlLnByb3RvYnVmLkxpc3RWYWx1ZUgAQgYKBGtpbmQiMwoJTGlzdFZhbHVlEiYKBnZhbHVlcxgBIAMoCzIWLmdvb2dsZS5wcm90b2J1Zi5WYWx1ZSobCglOdWxsVmFsdWUSDgoKTlVMTF9WQUxVRRAAQn8KE2NvbS5nb29nbGUucHJvdG9idWZCC1N0cnVjdFByb3RvUAFaL2dvb2dsZS5nb2xhbmcub3JnL3Byb3RvYnVmL3R5cGVzL2tub3duL3N0cnVjdHBi+AEBogIDR1BCqgIeR29vZ2xlLlByb3RvYnVmLldlbGxLbm93blR5cGVzYgZwcm90bzM");
var StructSchema = /* @__PURE__ */ messageDesc(file_google_protobuf_struct, 0);
var ValueSchema = /* @__PURE__ */ messageDesc(file_google_protobuf_struct, 1);
var ListValueSchema = /* @__PURE__ */ messageDesc(file_google_protobuf_struct, 2);
var NullValue;
(function(NullValue2) {
  NullValue2[NullValue2["NULL_VALUE"] = 0] = "NULL_VALUE";
})(NullValue || (NullValue = {}));

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/extensions.js
function getExtension(message, extension) {
  assertExtendee(extension, message);
  const ufs = filterUnknownFields(message.$unknown, extension);
  const [container, field, get] = createExtensionContainer(extension);
  for (const uf of ufs) {
    readField(container, new BinaryReader(uf.data), field, uf.wireType, {
      readUnknownFields: true
    });
  }
  return get();
}
function setExtension(message, extension, value) {
  var _a;
  assertExtendee(extension, message);
  const ufs = ((_a = message.$unknown) !== null && _a !== void 0 ? _a : []).filter((uf) => uf.no !== extension.number);
  const [container, field] = createExtensionContainer(extension, value);
  const writer = new BinaryWriter();
  writeField(writer, { writeUnknownFields: true }, container, field);
  const reader = new BinaryReader(writer.finish());
  while (reader.pos < reader.len) {
    const [no, wireType] = reader.tag();
    const data = reader.skip(wireType, no);
    ufs.push({ no, wireType, data });
  }
  message.$unknown = ufs;
}
function filterUnknownFields(unknownFields, extension) {
  if (unknownFields === void 0)
    return [];
  if (extension.fieldKind === "enum" || extension.fieldKind === "scalar") {
    for (let i = unknownFields.length - 1; i >= 0; --i) {
      if (unknownFields[i].no == extension.number) {
        return [unknownFields[i]];
      }
    }
    return [];
  }
  return unknownFields.filter((uf) => uf.no === extension.number);
}
function createExtensionContainer(extension, value) {
  const localName = extension.typeName;
  const field = Object.assign(Object.assign({}, extension), { kind: "field", parent: extension.extendee, localName });
  const desc = Object.assign(Object.assign({}, extension.extendee), { fields: [field], members: [field], oneofs: [] });
  const container = create(desc, value !== void 0 ? { [localName]: value } : void 0);
  return [
    reflect(desc, container),
    field,
    () => {
      const value2 = container[localName];
      if (value2 === void 0) {
        const desc2 = extension.message;
        if (isWrapperDesc(desc2)) {
          return scalarZeroValue(desc2.fields[0].scalar, desc2.fields[0].longAsString);
        }
        return create(desc2);
      }
      return value2;
    }
  ];
}
function assertExtendee(extension, message) {
  if (extension.extendee.typeName != message.$typeName) {
    throw new Error(`extension ${extension.typeName} can only be applied to message ${extension.extendee.typeName}`);
  }
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/to-json.js
var LEGACY_REQUIRED3 = 3;
var IMPLICIT4 = 2;
var jsonWriteDefaults = {
  alwaysEmitImplicit: false,
  enumAsInteger: false,
  useProtoFieldName: false
};
function makeWriteOptions2(options) {
  return options ? Object.assign(Object.assign({}, jsonWriteDefaults), options) : jsonWriteDefaults;
}
function toJson(schema, message, options) {
  return reflectToJson(reflect(schema, message), makeWriteOptions2(options));
}
function toJsonString(schema, message, options) {
  var _a;
  const jsonValue = toJson(schema, message, options);
  return JSON.stringify(jsonValue, null, (_a = options === null || options === void 0 ? void 0 : options.prettySpaces) !== null && _a !== void 0 ? _a : 0);
}
function reflectToJson(msg, opts) {
  var _a;
  const wktJson = tryWktToJson(msg, opts);
  if (wktJson !== void 0)
    return wktJson;
  const json = {};
  for (const f of msg.sortedFields) {
    if (!msg.isSet(f)) {
      if (f.presence == LEGACY_REQUIRED3) {
        throw new Error(`cannot encode ${f} to JSON: required field not set`);
      }
      if (!opts.alwaysEmitImplicit || f.presence !== IMPLICIT4) {
        continue;
      }
    }
    const jsonValue = fieldToJson(f, msg.get(f), opts);
    if (jsonValue !== void 0) {
      json[jsonName(f, opts)] = jsonValue;
    }
  }
  if (opts.registry) {
    const tagSeen = /* @__PURE__ */ new Set();
    for (const { no } of (_a = msg.getUnknown()) !== null && _a !== void 0 ? _a : []) {
      if (!tagSeen.has(no)) {
        tagSeen.add(no);
        const extension = opts.registry.getExtensionFor(msg.desc, no);
        if (!extension) {
          continue;
        }
        const value = getExtension(msg.message, extension);
        const [container, field] = createExtensionContainer(extension, value);
        const jsonValue = fieldToJson(field, container.get(field), opts);
        if (jsonValue !== void 0) {
          json[extension.jsonName] = jsonValue;
        }
      }
    }
  }
  return json;
}
function fieldToJson(f, val, opts) {
  switch (f.fieldKind) {
    case "scalar":
      return scalarToJson(f, val);
    case "message":
      return reflectToJson(val, opts);
    case "enum":
      return enumToJsonInternal(f.enum, val, opts.enumAsInteger);
    case "list":
      return listToJson(val, opts);
    case "map":
      return mapToJson(val, opts);
  }
}
function mapToJson(map, opts) {
  const f = map.field();
  const jsonObj = {};
  switch (f.mapKind) {
    case "scalar":
      for (const [entryKey, entryValue] of map) {
        jsonObj[entryKey] = scalarToJson(f, entryValue);
      }
      break;
    case "message":
      for (const [entryKey, entryValue] of map) {
        jsonObj[entryKey] = reflectToJson(entryValue, opts);
      }
      break;
    case "enum":
      for (const [entryKey, entryValue] of map) {
        jsonObj[entryKey] = enumToJsonInternal(f.enum, entryValue, opts.enumAsInteger);
      }
      break;
  }
  return opts.alwaysEmitImplicit || map.size > 0 ? jsonObj : void 0;
}
function listToJson(list, opts) {
  const f = list.field();
  const jsonArr = [];
  switch (f.listKind) {
    case "scalar":
      for (const item of list) {
        jsonArr.push(scalarToJson(f, item));
      }
      break;
    case "enum":
      for (const item of list) {
        jsonArr.push(enumToJsonInternal(f.enum, item, opts.enumAsInteger));
      }
      break;
    case "message":
      for (const item of list) {
        jsonArr.push(reflectToJson(item, opts));
      }
      break;
  }
  return opts.alwaysEmitImplicit || jsonArr.length > 0 ? jsonArr : void 0;
}
function enumToJsonInternal(desc, value, enumAsInteger) {
  var _a;
  if (typeof value != "number") {
    throw new Error(`cannot encode ${desc} to JSON: expected number, got ${formatVal(value)}`);
  }
  if (desc.typeName == "google.protobuf.NullValue") {
    return null;
  }
  if (enumAsInteger) {
    return value;
  }
  const val = desc.value[value];
  return (_a = val === null || val === void 0 ? void 0 : val.name) !== null && _a !== void 0 ? _a : value;
}
function scalarToJson(field, value) {
  var _a, _b, _c, _d, _e, _f;
  switch (field.scalar) {
    // int32, fixed32, uint32: JSON value will be a decimal number. Either numbers or strings are accepted.
    case ScalarType.INT32:
    case ScalarType.SFIXED32:
    case ScalarType.SINT32:
    case ScalarType.FIXED32:
    case ScalarType.UINT32:
      if (typeof value != "number") {
        throw new Error(`cannot encode ${field} to JSON: ${(_a = checkField(field, value)) === null || _a === void 0 ? void 0 : _a.message}`);
      }
      return value;
    // float, double: JSON value will be a number or one of the special string values "NaN", "Infinity", and "-Infinity".
    // Either numbers or strings are accepted. Exponent notation is also accepted.
    case ScalarType.FLOAT:
    case ScalarType.DOUBLE:
      if (typeof value != "number") {
        throw new Error(`cannot encode ${field} to JSON: ${(_b = checkField(field, value)) === null || _b === void 0 ? void 0 : _b.message}`);
      }
      if (Number.isNaN(value))
        return "NaN";
      if (value === Number.POSITIVE_INFINITY)
        return "Infinity";
      if (value === Number.NEGATIVE_INFINITY)
        return "-Infinity";
      return value;
    // string:
    case ScalarType.STRING:
      if (typeof value != "string") {
        throw new Error(`cannot encode ${field} to JSON: ${(_c = checkField(field, value)) === null || _c === void 0 ? void 0 : _c.message}`);
      }
      return value;
    // bool:
    case ScalarType.BOOL:
      if (typeof value != "boolean") {
        throw new Error(`cannot encode ${field} to JSON: ${(_d = checkField(field, value)) === null || _d === void 0 ? void 0 : _d.message}`);
      }
      return value;
    // JSON value will be a decimal string. Either numbers or strings are accepted.
    case ScalarType.UINT64:
    case ScalarType.FIXED64:
    case ScalarType.INT64:
    case ScalarType.SFIXED64:
    case ScalarType.SINT64:
      if (typeof value != "bigint" && typeof value != "string") {
        throw new Error(`cannot encode ${field} to JSON: ${(_e = checkField(field, value)) === null || _e === void 0 ? void 0 : _e.message}`);
      }
      return value.toString();
    // bytes: JSON value will be the data encoded as a string using standard base64 encoding with paddings.
    // Either standard or URL-safe base64 encoding with/without paddings are accepted.
    case ScalarType.BYTES:
      if (value instanceof Uint8Array) {
        return base64Encode(value);
      }
      throw new Error(`cannot encode ${field} to JSON: ${(_f = checkField(field, value)) === null || _f === void 0 ? void 0 : _f.message}`);
  }
}
function jsonName(f, opts) {
  return opts.useProtoFieldName ? f.name : f.jsonName;
}
function tryWktToJson(msg, opts) {
  if (!msg.desc.typeName.startsWith("google.protobuf.")) {
    return void 0;
  }
  switch (msg.desc.typeName) {
    case "google.protobuf.Any":
      return anyToJson(msg.message, opts);
    case "google.protobuf.Timestamp":
      return timestampToJson(msg.message);
    case "google.protobuf.Duration":
      return durationToJson(msg.message);
    case "google.protobuf.FieldMask":
      return fieldMaskToJson(msg.message);
    case "google.protobuf.Struct":
      return structToJson(msg.message);
    case "google.protobuf.Value":
      return valueToJson(msg.message);
    case "google.protobuf.ListValue":
      return listValueToJson(msg.message);
    default:
      if (isWrapperDesc(msg.desc)) {
        const valueField = msg.desc.fields[0];
        return scalarToJson(valueField, msg.get(valueField));
      }
      return void 0;
  }
}
function anyToJson(val, opts) {
  if (val.typeUrl === "") {
    return {};
  }
  const { registry } = opts;
  let message;
  let desc;
  if (registry) {
    message = anyUnpack(val, registry);
    if (message) {
      desc = registry.getMessage(message.$typeName);
    }
  }
  if (!desc || !message) {
    throw new Error(`cannot encode message ${val.$typeName} to JSON: "${val.typeUrl}" is not in the type registry`);
  }
  let json = reflectToJson(reflect(desc, message), opts);
  if (desc.typeName.startsWith("google.protobuf.") || json === null || Array.isArray(json) || typeof json !== "object") {
    json = { value: json };
  }
  json["@type"] = val.typeUrl;
  return json;
}
function durationToJson(val) {
  const seconds = Number(val.seconds);
  const nanos = val.nanos;
  if (seconds > 315576e6 || seconds < -315576e6) {
    throw new Error(`cannot encode message ${val.$typeName} to JSON: value out of range`);
  }
  if (seconds > 0 && nanos < 0 || seconds < 0 && nanos > 0) {
    throw new Error(`cannot encode message ${val.$typeName} to JSON: nanos sign must match seconds sign`);
  }
  let text = val.seconds.toString();
  if (nanos !== 0) {
    let nanosStr = Math.abs(nanos).toString();
    nanosStr = "0".repeat(9 - nanosStr.length) + nanosStr;
    if (nanosStr.substring(3) === "000000") {
      nanosStr = nanosStr.substring(0, 3);
    } else if (nanosStr.substring(6) === "000") {
      nanosStr = nanosStr.substring(0, 6);
    }
    text += "." + nanosStr;
    if (nanos < 0 && seconds == 0) {
      text = "-" + text;
    }
  }
  return text + "s";
}
function fieldMaskToJson(val) {
  return val.paths.map((p) => {
    if (protoSnakeCase(protoCamelCase(p)) !== p) {
      throw new Error(`cannot encode message ${val.$typeName} to JSON: lowerCamelCase of path name "${p}" is irreversible`);
    }
    return protoCamelCase(p);
  }).join(",");
}
function structToJson(val) {
  const json = {};
  for (const [k, v] of Object.entries(val.fields)) {
    json[k] = valueToJson(v);
  }
  return json;
}
function valueToJson(val) {
  switch (val.kind.case) {
    case "nullValue":
      return null;
    case "numberValue":
      if (!Number.isFinite(val.kind.value)) {
        throw new Error(`${val.$typeName} cannot be NaN or Infinity`);
      }
      return val.kind.value;
    case "boolValue":
      return val.kind.value;
    case "stringValue":
      return val.kind.value;
    case "structValue":
      return structToJson(val.kind.value);
    case "listValue":
      return listValueToJson(val.kind.value);
    default:
      throw new Error(`${val.$typeName} must have a value`);
  }
}
function listValueToJson(val) {
  return val.values.map(valueToJson);
}
function timestampToJson(val) {
  const ms = Number(val.seconds) * 1e3;
  if (ms < Date.parse("0001-01-01T00:00:00Z") || ms > Date.parse("9999-12-31T23:59:59Z")) {
    throw new Error(`cannot encode message ${val.$typeName} to JSON: must be from 0001-01-01T00:00:00Z to 9999-12-31T23:59:59Z inclusive`);
  }
  if (val.nanos < 0) {
    throw new Error(`cannot encode message ${val.$typeName} to JSON: nanos must not be negative`);
  }
  if (val.nanos > 999999999) {
    throw new Error(`cannot encode message ${val.$typeName} to JSON: nanos must not be greater than 99999999`);
  }
  let z = "Z";
  if (val.nanos > 0) {
    const nanosStr = (val.nanos + 1e9).toString().substring(1);
    if (nanosStr.substring(3) === "000000") {
      z = "." + nanosStr.substring(0, 3) + "Z";
    } else if (nanosStr.substring(6) === "000") {
      z = "." + nanosStr.substring(0, 6) + "Z";
    } else {
      z = "." + nanosStr + "Z";
    }
  }
  return new Date(ms).toISOString().replace(".000Z", z);
}

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/from-json.js
var jsonReadDefaults = {
  ignoreUnknownFields: false
};
function makeReadOptions2(options) {
  return options ? Object.assign(Object.assign({}, jsonReadDefaults), options) : jsonReadDefaults;
}
function fromJsonString(schema, json, options) {
  return fromJson(schema, parseJsonString(json, schema.typeName), options);
}
function fromJson(schema, json, options) {
  const msg = reflect(schema);
  try {
    readMessage2(msg, json, makeReadOptions2(options));
  } catch (e) {
    if (isFieldError(e)) {
      throw new Error(`cannot decode ${e.field()} from JSON: ${e.message}`, {
        cause: e
      });
    }
    throw e;
  }
  return msg.message;
}
var messageJsonFields = /* @__PURE__ */ new WeakMap();
function getJsonField(desc, jsonKey) {
  var _a;
  if (!messageJsonFields.has(desc)) {
    const jsonNames = /* @__PURE__ */ new Map();
    for (const field of desc.fields) {
      jsonNames.set(field.name, field).set(field.jsonName, field);
    }
    messageJsonFields.set(desc, jsonNames);
  }
  return (_a = messageJsonFields.get(desc)) === null || _a === void 0 ? void 0 : _a.get(jsonKey);
}
function readMessage2(msg, json, opts) {
  var _a;
  if (tryWktFromJson(msg, json, opts)) {
    return;
  }
  if (json == null || Array.isArray(json) || typeof json != "object") {
    throw new Error(`cannot decode ${msg.desc} from JSON: ${formatVal(json)}`);
  }
  const oneofSeen = /* @__PURE__ */ new Map();
  for (const [jsonKey, jsonValue] of Object.entries(json)) {
    const field = getJsonField(msg.desc, jsonKey);
    if (field) {
      if (field.oneof) {
        if (jsonValue === null && field.fieldKind == "scalar") {
          continue;
        }
        const seen = oneofSeen.get(field.oneof);
        if (seen !== void 0) {
          throw new FieldError(field.oneof, `oneof set multiple times by ${seen.name} and ${field.name}`);
        }
        oneofSeen.set(field.oneof, field);
      }
      readField2(msg, field, jsonValue, opts);
    } else {
      let extension = void 0;
      if (jsonKey.startsWith("[") && jsonKey.endsWith("]") && // biome-ignore lint/suspicious/noAssignInExpressions: no
      (extension = (_a = opts.registry) === null || _a === void 0 ? void 0 : _a.getExtension(jsonKey.substring(1, jsonKey.length - 1))) && extension.extendee.typeName === msg.desc.typeName) {
        const [container, field2, get] = createExtensionContainer(extension);
        readField2(container, field2, jsonValue, opts);
        setExtension(msg.message, extension, get());
      }
      if (!extension && !opts.ignoreUnknownFields) {
        throw new Error(`cannot decode ${msg.desc} from JSON: key "${jsonKey}" is unknown`);
      }
    }
  }
}
function readField2(msg, field, json, opts) {
  switch (field.fieldKind) {
    case "scalar":
      readScalarField(msg, field, json);
      break;
    case "enum":
      readEnumField(msg, field, json, opts);
      break;
    case "message":
      readMessageField2(msg, field, json, opts);
      break;
    case "list":
      readListField2(msg.get(field), json, opts);
      break;
    case "map":
      readMapField(msg.get(field), json, opts);
      break;
  }
}
function readListOrMapItem(field, json, opts) {
  if (field.scalar && json !== null) {
    return scalarFromJson(field, json);
  }
  if (field.message && !isResetSentinelNullValue(field, json)) {
    const msgValue = reflect(field.message);
    readMessage2(msgValue, json, opts);
    return msgValue;
  }
  if (field.enum && !isResetSentinelNullValue(field, json)) {
    return readEnum(field.enum, json, opts.ignoreUnknownFields);
  }
  throw new FieldError(field, `${field.fieldKind === "list" ? "list item" : "map value"} must not be null`);
}
function readMapField(map, json, opts) {
  if (json === null) {
    return;
  }
  const field = map.field();
  if (typeof json != "object" || Array.isArray(json)) {
    throw new FieldError(field, "expected object, got " + formatVal(json));
  }
  for (const [jsonMapKey, jsonMapValue] of Object.entries(json)) {
    const key = mapKeyFromJson(field.mapKey, jsonMapKey);
    const value = readListOrMapItem(field, jsonMapValue, opts);
    if (value !== tokenIgnoredUnknownEnum) {
      map.set(key, value);
    }
  }
}
function readListField2(list, json, opts) {
  if (json === null) {
    return;
  }
  const field = list.field();
  if (!Array.isArray(json)) {
    throw new FieldError(field, "expected Array, got " + formatVal(json));
  }
  for (const jsonItem of json) {
    const value = readListOrMapItem(field, jsonItem, opts);
    if (value !== tokenIgnoredUnknownEnum) {
      list.add(value);
    }
  }
}
function readMessageField2(msg, field, json, opts) {
  if (isResetSentinelNullValue(field, json)) {
    msg.clear(field);
    return;
  }
  const msgValue = msg.isSet(field) ? msg.get(field) : reflect(field.message);
  readMessage2(msgValue, json, opts);
  msg.set(field, msgValue);
}
function readEnumField(msg, field, json, opts) {
  if (isResetSentinelNullValue(field, json)) {
    msg.clear(field);
    return;
  }
  const enumValue = readEnum(field.enum, json, opts.ignoreUnknownFields);
  if (enumValue !== tokenIgnoredUnknownEnum) {
    msg.set(field, enumValue);
  }
}
function readScalarField(msg, field, json) {
  if (json === null) {
    msg.clear(field);
  } else {
    msg.set(field, scalarFromJson(field, json));
  }
}
function isResetSentinelNullValue(field, json) {
  var _a, _b;
  return json === null && ((_a = field.message) === null || _a === void 0 ? void 0 : _a.typeName) != "google.protobuf.Value" && ((_b = field.enum) === null || _b === void 0 ? void 0 : _b.typeName) != "google.protobuf.NullValue";
}
var tokenIgnoredUnknownEnum = /* @__PURE__ */ Symbol();
function readEnum(desc, json, ignoreUnknownFields) {
  if (json === null) {
    return desc.values[0].number;
  }
  switch (typeof json) {
    case "number":
      if (Number.isInteger(json)) {
        return json;
      }
      break;
    case "string":
      const value = desc.values.find((ev) => ev.name === json);
      if (value !== void 0) {
        return value.number;
      }
      if (ignoreUnknownFields) {
        return tokenIgnoredUnknownEnum;
      }
      break;
  }
  throw new Error(`cannot decode ${desc} from JSON: ${formatVal(json)}`);
}
function scalarFromJson(field, json) {
  switch (field.scalar) {
    // float, double: JSON value will be a number or one of the special string values "NaN", "Infinity", and "-Infinity".
    // Either numbers or strings are accepted. Exponent notation is also accepted.
    case ScalarType.DOUBLE:
    case ScalarType.FLOAT:
      if (json === "NaN")
        return NaN;
      if (json === "Infinity")
        return Number.POSITIVE_INFINITY;
      if (json === "-Infinity")
        return Number.NEGATIVE_INFINITY;
      if (typeof json == "number") {
        if (Number.isNaN(json)) {
          throw new FieldError(field, "unexpected NaN number");
        }
        if (!Number.isFinite(json)) {
          throw new FieldError(field, "unexpected infinite number");
        }
        break;
      }
      if (typeof json == "string") {
        if (json === "") {
          break;
        }
        if (json.trim().length !== json.length) {
          break;
        }
        const float = Number(json);
        if (!Number.isFinite(float)) {
          break;
        }
        return float;
      }
      break;
    // int32, fixed32, uint32: JSON value will be a decimal number. Either numbers or strings are accepted.
    case ScalarType.INT32:
    case ScalarType.FIXED32:
    case ScalarType.SFIXED32:
    case ScalarType.SINT32:
    case ScalarType.UINT32:
      return int32FromJson(json);
    // bytes: JSON value will be the data encoded as a string using standard base64 encoding with paddings.
    // Either standard or URL-safe base64 encoding with/without paddings are accepted.
    case ScalarType.BYTES:
      if (typeof json == "string") {
        if (json === "") {
          return new Uint8Array(0);
        }
        try {
          return base64Decode(json);
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          throw new FieldError(field, message);
        }
      }
      break;
  }
  return json;
}
function mapKeyFromJson(type, jsonString) {
  switch (type) {
    case ScalarType.BOOL:
      switch (jsonString) {
        case "true":
          return true;
        case "false":
          return false;
      }
      return jsonString;
    case ScalarType.INT32:
    case ScalarType.FIXED32:
    case ScalarType.UINT32:
    case ScalarType.SFIXED32:
    case ScalarType.SINT32:
      return int32FromJson(jsonString);
    default:
      return jsonString;
  }
}
function int32FromJson(json) {
  if (typeof json == "string") {
    if (json === "") {
      return json;
    }
    if (json.trim().length !== json.length) {
      return json;
    }
    const num = Number(json);
    if (Number.isNaN(num)) {
      return json;
    }
    return num;
  }
  return json;
}
function parseJsonString(jsonString, typeName) {
  try {
    return JSON.parse(jsonString);
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    throw new Error(
      `cannot decode message ${typeName} from JSON: ${message}`,
      // @ts-expect-error we use the ES2022 error CTOR option "cause" for better stack traces
      { cause: e }
    );
  }
}
function tryWktFromJson(msg, jsonValue, opts) {
  if (!msg.desc.typeName.startsWith("google.protobuf.")) {
    return false;
  }
  switch (msg.desc.typeName) {
    case "google.protobuf.Any":
      anyFromJson(msg.message, jsonValue, opts);
      return true;
    case "google.protobuf.Timestamp":
      timestampFromJson(msg.message, jsonValue);
      return true;
    case "google.protobuf.Duration":
      durationFromJson(msg.message, jsonValue);
      return true;
    case "google.protobuf.FieldMask":
      fieldMaskFromJson(msg.message, jsonValue);
      return true;
    case "google.protobuf.Struct":
      structFromJson(msg.message, jsonValue);
      return true;
    case "google.protobuf.Value":
      valueFromJson(msg.message, jsonValue);
      return true;
    case "google.protobuf.ListValue":
      listValueFromJson(msg.message, jsonValue);
      return true;
    default:
      if (isWrapperDesc(msg.desc)) {
        const valueField = msg.desc.fields[0];
        if (jsonValue === null) {
          msg.clear(valueField);
        } else {
          msg.set(valueField, scalarFromJson(valueField, jsonValue));
        }
        return true;
      }
      return false;
  }
}
function anyFromJson(any, json, opts) {
  var _a;
  if (json === null || Array.isArray(json) || typeof json != "object") {
    throw new Error(`cannot decode message ${any.$typeName} from JSON: expected object but got ${formatVal(json)}`);
  }
  if (Object.keys(json).length == 0) {
    return;
  }
  const typeUrl = json["@type"];
  if (typeof typeUrl != "string" || typeUrl == "") {
    throw new Error(`cannot decode message ${any.$typeName} from JSON: "@type" is empty`);
  }
  const typeName = typeUrl.includes("/") ? typeUrl.substring(typeUrl.lastIndexOf("/") + 1) : typeUrl;
  if (!typeName.length) {
    throw new Error(`cannot decode message ${any.$typeName} from JSON: "@type" is invalid`);
  }
  const desc = (_a = opts.registry) === null || _a === void 0 ? void 0 : _a.getMessage(typeName);
  if (!desc) {
    throw new Error(`cannot decode message ${any.$typeName} from JSON: ${typeUrl} is not in the type registry`);
  }
  const msg = reflect(desc);
  if (typeName.startsWith("google.protobuf.") && Object.prototype.hasOwnProperty.call(json, "value")) {
    const value = json.value;
    readMessage2(msg, value, opts);
  } else {
    const copy = Object.assign({}, json);
    delete copy["@type"];
    readMessage2(msg, copy, opts);
  }
  anyPack(msg.desc, msg.message, any);
}
function timestampFromJson(timestamp, json) {
  if (typeof json !== "string") {
    throw new Error(`cannot decode message ${timestamp.$typeName} from JSON: ${formatVal(json)}`);
  }
  const matches = json.match(/^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,9}))?(?:Z|([+-][0-9][0-9]:[0-9][0-9]))$/);
  if (!matches) {
    throw new Error(`cannot decode message ${timestamp.$typeName} from JSON: invalid RFC 3339 string`);
  }
  const ms = Date.parse(
    // biome-ignore format: want this to read well
    matches[1] + "-" + matches[2] + "-" + matches[3] + "T" + matches[4] + ":" + matches[5] + ":" + matches[6] + (matches[8] ? matches[8] : "Z")
  );
  if (Number.isNaN(ms)) {
    throw new Error(`cannot decode message ${timestamp.$typeName} from JSON: invalid RFC 3339 string`);
  }
  if (ms < Date.parse("0001-01-01T00:00:00Z") || ms > Date.parse("9999-12-31T23:59:59Z")) {
    throw new Error(`cannot decode message ${timestamp.$typeName} from JSON: must be from 0001-01-01T00:00:00Z to 9999-12-31T23:59:59Z inclusive`);
  }
  timestamp.seconds = protoInt64.parse(ms / 1e3);
  timestamp.nanos = 0;
  if (matches[7]) {
    timestamp.nanos = parseInt("1" + matches[7] + "0".repeat(9 - matches[7].length)) - 1e9;
  }
}
function durationFromJson(duration, json) {
  if (typeof json !== "string") {
    throw new Error(`cannot decode message ${duration.$typeName} from JSON: ${formatVal(json)}`);
  }
  const match = json.match(/^(-?[0-9]+)(?:\.([0-9]+))?s/);
  if (match === null) {
    throw new Error(`cannot decode message ${duration.$typeName} from JSON: ${formatVal(json)}`);
  }
  const longSeconds = Number(match[1]);
  if (longSeconds > 315576e6 || longSeconds < -315576e6) {
    throw new Error(`cannot decode message ${duration.$typeName} from JSON: ${formatVal(json)}`);
  }
  duration.seconds = protoInt64.parse(longSeconds);
  if (typeof match[2] !== "string") {
    return;
  }
  const nanosStr = match[2] + "0".repeat(9 - match[2].length);
  duration.nanos = parseInt(nanosStr);
  if (longSeconds < 0 || Object.is(longSeconds, -0)) {
    duration.nanos = -duration.nanos;
  }
}
function fieldMaskFromJson(fieldMask, json) {
  if (typeof json !== "string") {
    throw new Error(`cannot decode message ${fieldMask.$typeName} from JSON: ${formatVal(json)}`);
  }
  if (json === "") {
    return;
  }
  fieldMask.paths = json.split(",").map((path4) => {
    if (path4.includes("_")) {
      throw new Error(`cannot decode message ${fieldMask.$typeName} from JSON: path names must be lowerCamelCase`);
    }
    return protoSnakeCase(path4);
  });
}
function structFromJson(struct, json) {
  if (typeof json != "object" || json == null || Array.isArray(json)) {
    throw new Error(`cannot decode message ${struct.$typeName} from JSON ${formatVal(json)}`);
  }
  for (const [k, v] of Object.entries(json)) {
    const parsedV = create(ValueSchema);
    valueFromJson(parsedV, v);
    struct.fields[k] = parsedV;
  }
}
function valueFromJson(value, json) {
  switch (typeof json) {
    case "number":
      value.kind = { case: "numberValue", value: json };
      break;
    case "string":
      value.kind = { case: "stringValue", value: json };
      break;
    case "boolean":
      value.kind = { case: "boolValue", value: json };
      break;
    case "object":
      if (json === null) {
        value.kind = { case: "nullValue", value: NullValue.NULL_VALUE };
      } else if (Array.isArray(json)) {
        const listValue = create(ListValueSchema);
        listValueFromJson(listValue, json);
        value.kind = { case: "listValue", value: listValue };
      } else {
        const struct = create(StructSchema);
        structFromJson(struct, json);
        value.kind = { case: "structValue", value: struct };
      }
      break;
    default:
      throw new Error(`cannot decode message ${value.$typeName} from JSON ${formatVal(json)}`);
  }
  return value;
}
function listValueFromJson(listValue, json) {
  if (!Array.isArray(json)) {
    throw new Error(`cannot decode message ${listValue.$typeName} from JSON ${formatVal(json)}`);
  }
  for (const e of json) {
    const value = create(ValueSchema);
    valueFromJson(value, e);
    listValue.values.push(value);
  }
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/code.js
var Code;
(function(Code2) {
  Code2[Code2["Canceled"] = 1] = "Canceled";
  Code2[Code2["Unknown"] = 2] = "Unknown";
  Code2[Code2["InvalidArgument"] = 3] = "InvalidArgument";
  Code2[Code2["DeadlineExceeded"] = 4] = "DeadlineExceeded";
  Code2[Code2["NotFound"] = 5] = "NotFound";
  Code2[Code2["AlreadyExists"] = 6] = "AlreadyExists";
  Code2[Code2["PermissionDenied"] = 7] = "PermissionDenied";
  Code2[Code2["ResourceExhausted"] = 8] = "ResourceExhausted";
  Code2[Code2["FailedPrecondition"] = 9] = "FailedPrecondition";
  Code2[Code2["Aborted"] = 10] = "Aborted";
  Code2[Code2["OutOfRange"] = 11] = "OutOfRange";
  Code2[Code2["Unimplemented"] = 12] = "Unimplemented";
  Code2[Code2["Internal"] = 13] = "Internal";
  Code2[Code2["Unavailable"] = 14] = "Unavailable";
  Code2[Code2["DataLoss"] = 15] = "DataLoss";
  Code2[Code2["Unauthenticated"] = 16] = "Unauthenticated";
})(Code || (Code = {}));

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-connect/code-string.js
function codeToString(value) {
  const name = Code[value];
  if (typeof name != "string") {
    return value.toString();
  }
  return name[0].toLowerCase() + name.substring(1).replace(/[A-Z]/g, (c) => "_" + c.toLowerCase());
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/connect-error.js
var ConnectError = class _ConnectError extends Error {
  /**
   * Create a new ConnectError.
   * If no code is provided, code "unknown" is used.
   * Outgoing details are only relevant for the server side - a service may
   * raise an error with details, and it is up to the protocol implementation
   * to encode and send the details along with the error.
   */
  constructor(message, code = Code.Unknown, metadata, outgoingDetails, cause) {
    super(createMessage(message, code));
    this.name = "ConnectError";
    Object.setPrototypeOf(this, new.target.prototype);
    this.rawMessage = message;
    this.code = code;
    this.metadata = new Headers(metadata !== null && metadata !== void 0 ? metadata : {});
    this.details = outgoingDetails !== null && outgoingDetails !== void 0 ? outgoingDetails : [];
    this.cause = cause;
  }
  /**
   * Convert any value - typically a caught error into a ConnectError,
   * following these rules:
   * - If the value is already a ConnectError, return it as is.
   * - If the value is an AbortError or TimeoutError from the fetch API, return
   *   the message of the error with code Canceled.
   * - For other Errors, return the error message with code Unknown by default.
   * - For other values, return the values String representation as a message,
   *   with the code Unknown by default.
   * The original value will be used for the "cause" property for the new
   * ConnectError.
   */
  static from(reason, code = Code.Unknown) {
    if (reason instanceof _ConnectError) {
      return reason;
    }
    if (reason instanceof Error) {
      if (reason.name == "AbortError" || reason.name == "TimeoutError") {
        return new _ConnectError(reason.message, Code.Canceled);
      }
      return new _ConnectError(reason.message, code, void 0, void 0, reason);
    }
    return new _ConnectError(String(reason), code, void 0, void 0, reason);
  }
  static [Symbol.hasInstance](v) {
    if (!(v instanceof Error)) {
      return false;
    }
    if (Object.getPrototypeOf(v) === _ConnectError.prototype) {
      return true;
    }
    return v.name === "ConnectError" && "code" in v && typeof v.code === "number" && "metadata" in v && "details" in v && Array.isArray(v.details) && "rawMessage" in v && typeof v.rawMessage == "string" && "cause" in v;
  }
  findDetails(typeOrRegistry) {
    const registry = typeOrRegistry.kind === "message" ? {
      getMessage: (typeName) => typeName === typeOrRegistry.typeName ? typeOrRegistry : void 0
    } : typeOrRegistry;
    const details = [];
    for (const data of this.details) {
      if ("desc" in data) {
        if (registry.getMessage(data.desc.typeName)) {
          details.push(create(data.desc, data.value));
        }
        continue;
      }
      const desc = registry.getMessage(data.type);
      if (desc) {
        try {
          details.push(fromBinary(desc, data.value));
        } catch (_) {
        }
      }
    }
    return details;
  }
};
function createMessage(message, code) {
  return message.length ? `[${codeToString(code)}] ${message}` : `[${codeToString(code)}]`;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/http-headers.js
function decodeBinaryHeader(value, desc, options) {
  try {
    const bytes = base64Decode(value);
    if (desc) {
      return fromBinary(desc, bytes, options);
    }
    return bytes;
  } catch (e) {
    throw ConnectError.from(e, Code.DataLoss);
  }
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/any-client.js
function makeAnyClient(service, createMethod) {
  const client = {};
  for (const desc of service.methods) {
    const method = createMethod(desc);
    if (method != null) {
      client[desc.localName] = method;
    }
  }
  return client;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/compression.js
var compressedFlag = 1;

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/limit-io.js
var maxReadMaxBytes = 4294967295;
var maxWriteMaxBytes = maxReadMaxBytes;
var defaultCompressMinBytes = 1024;
function validateReadWriteMaxBytes(readMaxBytes, writeMaxBytes, compressMinBytes) {
  writeMaxBytes !== null && writeMaxBytes !== void 0 ? writeMaxBytes : writeMaxBytes = maxWriteMaxBytes;
  readMaxBytes !== null && readMaxBytes !== void 0 ? readMaxBytes : readMaxBytes = maxReadMaxBytes;
  compressMinBytes !== null && compressMinBytes !== void 0 ? compressMinBytes : compressMinBytes = defaultCompressMinBytes;
  if (writeMaxBytes < 1 || writeMaxBytes > maxWriteMaxBytes) {
    throw new ConnectError(`writeMaxBytes ${writeMaxBytes} must be >= 1 and <= ${maxWriteMaxBytes}`, Code.Internal);
  }
  if (readMaxBytes < 1 || readMaxBytes > maxReadMaxBytes) {
    throw new ConnectError(`readMaxBytes ${readMaxBytes} must be >= 1 and <= ${maxReadMaxBytes}`, Code.Internal);
  }
  return {
    readMaxBytes,
    writeMaxBytes,
    compressMinBytes
  };
}
function assertWriteMaxBytes(writeMaxBytes, bytesWritten) {
  if (bytesWritten > writeMaxBytes) {
    throw new ConnectError(`message size ${bytesWritten} is larger than configured writeMaxBytes ${writeMaxBytes}`, Code.ResourceExhausted);
  }
}
function assertReadMaxBytes(readMaxBytes, bytesRead, totalSizeKnown = false) {
  if (bytesRead > readMaxBytes) {
    let message = `message size is larger than configured readMaxBytes ${readMaxBytes}`;
    if (totalSizeKnown) {
      message = `message size ${bytesRead} is larger than configured readMaxBytes ${readMaxBytes}`;
    }
    throw new ConnectError(message, Code.ResourceExhausted);
  }
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/envelope.js
function createEnvelopeDecoder(readMaxBytes) {
  return new EnvelopeDecoderImpl(readMaxBytes);
}
var EnvelopeDecoderImpl = class {
  constructor(readMaxBytes) {
    this.readMaxBytes = readMaxBytes;
    this.header = new Uint8Array(5);
    this.headerView = new DataView(this.header.buffer);
    this.buf = [];
  }
  get byteLength() {
    return this.buf.reduce((a, b) => a + b.byteLength, 0);
  }
  decode(chunk) {
    this.buf.push(chunk);
    const envs = [];
    for (; ; ) {
      let env = this.pop();
      if (!env) {
        break;
      }
      envs.push(env);
    }
    return envs;
  }
  // consume an enveloped message
  pop() {
    if (!this.env) {
      this.env = this.head();
      if (!this.env) {
        return void 0;
      }
    }
    if (this.cons(this.env.data)) {
      const env = this.env;
      this.env = void 0;
      return env;
    }
    return void 0;
  }
  // consume header
  head() {
    if (!this.cons(this.header)) {
      return void 0;
    }
    const flags = this.headerView.getUint8(0);
    const length = this.headerView.getUint32(1);
    assertReadMaxBytes(this.readMaxBytes, length, true);
    return {
      flags,
      data: new Uint8Array(length)
    };
  }
  // consume from buffer, fill target
  cons(target) {
    const wantLength = target.byteLength;
    if (this.byteLength < wantLength) {
      return false;
    }
    let offset = 0;
    while (offset < wantLength) {
      const chunk = this.buf.shift();
      if (chunk.byteLength > wantLength - offset) {
        target.set(chunk.subarray(0, wantLength - offset), offset);
        this.buf.unshift(chunk.subarray(wantLength - offset));
        offset += wantLength - offset;
      } else {
        target.set(chunk, offset);
        offset += chunk.byteLength;
      }
    }
    return true;
  }
};
async function envelopeCompress(envelope, compression, compressMinBytes) {
  let { flags, data } = envelope;
  if ((flags & compressedFlag) === compressedFlag) {
    throw new ConnectError("invalid envelope, already compressed", Code.Internal);
  }
  if (compression && data.byteLength >= compressMinBytes) {
    data = await compression.compress(data);
    flags = flags | compressedFlag;
  }
  return { data, flags };
}
async function envelopeDecompress(envelope, compression, readMaxBytes) {
  let { flags, data } = envelope;
  if ((flags & compressedFlag) === compressedFlag) {
    if (!compression) {
      throw new ConnectError("received compressed envelope, but do not know how to decompress", Code.Internal);
    }
    data = await compression.decompress(data, readMaxBytes);
    flags = flags ^ compressedFlag;
  }
  return { data, flags };
}
function encodeEnvelope(flags, data) {
  const bytes = new Uint8Array(data.length + 5);
  bytes.set(data, 5);
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  v.setUint8(0, flags);
  v.setUint32(1, data.length);
  return bytes;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/async-iterable.js
var __asyncValues = function(o) {
  if (!Symbol.asyncIterator) throw new TypeError("Symbol.asyncIterator is not defined.");
  var m = o[Symbol.asyncIterator], i;
  return m ? m.call(o) : (o = typeof __values === "function" ? __values(o) : o[Symbol.iterator](), i = {}, verb("next"), verb("throw"), verb("return"), i[Symbol.asyncIterator] = function() {
    return this;
  }, i);
  function verb(n) {
    i[n] = o[n] && function(v) {
      return new Promise(function(resolve2, reject) {
        v = o[n](v), settle(resolve2, reject, v.done, v.value);
      });
    };
  }
  function settle(resolve2, reject, d, v) {
    Promise.resolve(v).then(function(v2) {
      resolve2({ value: v2, done: d });
    }, reject);
  }
};
var __await = function(v) {
  return this instanceof __await ? (this.v = v, this) : new __await(v);
};
var __asyncGenerator = function(thisArg, _arguments, generator) {
  if (!Symbol.asyncIterator) throw new TypeError("Symbol.asyncIterator is not defined.");
  var g = generator.apply(thisArg, _arguments || []), i, q = [];
  return i = Object.create((typeof AsyncIterator === "function" ? AsyncIterator : Object).prototype), verb("next"), verb("throw"), verb("return", awaitReturn), i[Symbol.asyncIterator] = function() {
    return this;
  }, i;
  function awaitReturn(f) {
    return function(v) {
      return Promise.resolve(v).then(f, reject);
    };
  }
  function verb(n, f) {
    if (g[n]) {
      i[n] = function(v) {
        return new Promise(function(a, b) {
          q.push([n, v, a, b]) > 1 || resume(n, v);
        });
      };
      if (f) i[n] = f(i[n]);
    }
  }
  function resume(n, v) {
    try {
      step(g[n](v));
    } catch (e) {
      settle(q[0][3], e);
    }
  }
  function step(r) {
    r.value instanceof __await ? Promise.resolve(r.value.v).then(fulfill, reject) : settle(q[0][2], r);
  }
  function fulfill(value) {
    resume("next", value);
  }
  function reject(value) {
    resume("throw", value);
  }
  function settle(f, v) {
    if (f(v), q.shift(), q.length) resume(q[0][0], q[0][1]);
  }
};
var __asyncDelegator = function(o) {
  var i, p;
  return i = {}, verb("next"), verb("throw", function(e) {
    throw e;
  }), verb("return"), i[Symbol.iterator] = function() {
    return this;
  }, i;
  function verb(n, f) {
    i[n] = o[n] ? function(v) {
      return (p = !p) ? { value: __await(o[n](v)), done: false } : f ? f(v) : v;
    } : f;
  }
};
function pipeTo(source, ...rest) {
  const [transforms, sink, opt] = pickTransformsAndSink(rest);
  let iterable = source;
  let abortable;
  if ((opt === null || opt === void 0 ? void 0 : opt.propagateDownStreamError) === true) {
    iterable = abortable = makeIterableAbortable(iterable);
  }
  iterable = pipe(iterable, ...transforms, { propagateDownStreamError: false });
  return sink(iterable).catch((reason) => {
    if (abortable) {
      return abortable.abort(reason).then(() => Promise.reject(reason));
    }
    return Promise.reject(reason);
  });
}
function pickTransformsAndSink(rest) {
  let opt;
  if (typeof rest[rest.length - 1] != "function") {
    opt = rest.pop();
  }
  const sink = rest.pop();
  return [rest, sink, opt];
}
function pipe(source, ...rest) {
  return __asyncGenerator(this, arguments, function* pipe_1() {
    var _a;
    const [transforms, opt] = pickTransforms(rest);
    let abortable;
    const sourceIt = source[Symbol.asyncIterator]();
    const cachedSource = {
      [Symbol.asyncIterator]() {
        return sourceIt;
      }
    };
    let iterable = cachedSource;
    if ((opt === null || opt === void 0 ? void 0 : opt.propagateDownStreamError) === true) {
      iterable = abortable = makeIterableAbortable(iterable);
    }
    for (const t of transforms) {
      iterable = t(iterable);
    }
    const it = iterable[Symbol.asyncIterator]();
    try {
      for (; ; ) {
        const r = yield __await(it.next());
        if (r.done === true) {
          break;
        }
        if (!abortable) {
          yield yield __await(r.value);
          continue;
        }
        try {
          yield yield __await(r.value);
        } catch (e) {
          yield __await(abortable.abort(e));
          throw e;
        }
      }
    } finally {
      if ((opt === null || opt === void 0 ? void 0 : opt.propagateDownStreamError) === true) {
        (_a = sourceIt.return) === null || _a === void 0 ? void 0 : _a.call(sourceIt).catch(() => {
        });
      }
    }
  });
}
function pickTransforms(rest) {
  let opt;
  if (typeof rest[rest.length - 1] != "function") {
    opt = rest.pop();
  }
  return [rest, opt];
}
function transformSerializeEnvelope(serialization, endStreamFlag, endSerialization) {
  if (endStreamFlag === void 0 || endSerialization === void 0) {
    return function(iterable) {
      return __asyncGenerator(this, arguments, function* () {
        var _a, e_4, _b, _c;
        try {
          for (var _d = true, iterable_4 = __asyncValues(iterable), iterable_4_1; iterable_4_1 = yield __await(iterable_4.next()), _a = iterable_4_1.done, !_a; _d = true) {
            _c = iterable_4_1.value;
            _d = false;
            const chunk = _c;
            const data = serialization.serialize(chunk);
            yield yield __await({ flags: 0, data });
          }
        } catch (e_4_1) {
          e_4 = { error: e_4_1 };
        } finally {
          try {
            if (!_d && !_a && (_b = iterable_4.return)) yield __await(_b.call(iterable_4));
          } finally {
            if (e_4) throw e_4.error;
          }
        }
      });
    };
  }
  return function(iterable) {
    return __asyncGenerator(this, arguments, function* () {
      var _a, e_5, _b, _c;
      try {
        for (var _d = true, iterable_5 = __asyncValues(iterable), iterable_5_1; iterable_5_1 = yield __await(iterable_5.next()), _a = iterable_5_1.done, !_a; _d = true) {
          _c = iterable_5_1.value;
          _d = false;
          const chunk = _c;
          let data;
          let flags = 0;
          if (chunk.end) {
            flags = flags | endStreamFlag;
            data = endSerialization.serialize(chunk.value);
          } else {
            data = serialization.serialize(chunk.value);
          }
          yield yield __await({ flags, data });
        }
      } catch (e_5_1) {
        e_5 = { error: e_5_1 };
      } finally {
        try {
          if (!_d && !_a && (_b = iterable_5.return)) yield __await(_b.call(iterable_5));
        } finally {
          if (e_5) throw e_5.error;
        }
      }
    });
  };
}
function transformParseEnvelope(serialization, endStreamFlag, endSerialization) {
  if (endSerialization && endStreamFlag !== void 0) {
    return function(iterable) {
      return __asyncGenerator(this, arguments, function* () {
        var _a, e_6, _b, _c;
        try {
          for (var _d = true, iterable_6 = __asyncValues(iterable), iterable_6_1; iterable_6_1 = yield __await(iterable_6.next()), _a = iterable_6_1.done, !_a; _d = true) {
            _c = iterable_6_1.value;
            _d = false;
            const { flags, data } = _c;
            if ((flags & endStreamFlag) === endStreamFlag) {
              yield yield __await({ value: endSerialization.parse(data), end: true });
            } else {
              yield yield __await({ value: serialization.parse(data), end: false });
            }
          }
        } catch (e_6_1) {
          e_6 = { error: e_6_1 };
        } finally {
          try {
            if (!_d && !_a && (_b = iterable_6.return)) yield __await(_b.call(iterable_6));
          } finally {
            if (e_6) throw e_6.error;
          }
        }
      });
    };
  }
  return function(iterable) {
    return __asyncGenerator(this, arguments, function* () {
      var _a, e_7, _b, _c;
      try {
        for (var _d = true, iterable_7 = __asyncValues(iterable), iterable_7_1; iterable_7_1 = yield __await(iterable_7.next()), _a = iterable_7_1.done, !_a; _d = true) {
          _c = iterable_7_1.value;
          _d = false;
          const { flags, data } = _c;
          if (endStreamFlag !== void 0 && (flags & endStreamFlag) === endStreamFlag) {
            if (endSerialization === null) {
              throw new ConnectError("unexpected end flag", Code.InvalidArgument);
            }
            continue;
          }
          yield yield __await(serialization.parse(data));
        }
      } catch (e_7_1) {
        e_7 = { error: e_7_1 };
      } finally {
        try {
          if (!_d && !_a && (_b = iterable_7.return)) yield __await(_b.call(iterable_7));
        } finally {
          if (e_7) throw e_7.error;
        }
      }
    });
  };
}
function transformCompressEnvelope(compression, compressMinBytes) {
  return function(iterable) {
    return __asyncGenerator(this, arguments, function* () {
      var _a, e_8, _b, _c;
      try {
        for (var _d = true, iterable_8 = __asyncValues(iterable), iterable_8_1; iterable_8_1 = yield __await(iterable_8.next()), _a = iterable_8_1.done, !_a; _d = true) {
          _c = iterable_8_1.value;
          _d = false;
          const env = _c;
          yield yield __await(yield __await(envelopeCompress(env, compression, compressMinBytes)));
        }
      } catch (e_8_1) {
        e_8 = { error: e_8_1 };
      } finally {
        try {
          if (!_d && !_a && (_b = iterable_8.return)) yield __await(_b.call(iterable_8));
        } finally {
          if (e_8) throw e_8.error;
        }
      }
    });
  };
}
function transformDecompressEnvelope(compression, readMaxBytes) {
  return function(iterable) {
    return __asyncGenerator(this, arguments, function* () {
      var _a, e_9, _b, _c;
      try {
        for (var _d = true, iterable_9 = __asyncValues(iterable), iterable_9_1; iterable_9_1 = yield __await(iterable_9.next()), _a = iterable_9_1.done, !_a; _d = true) {
          _c = iterable_9_1.value;
          _d = false;
          const env = _c;
          yield yield __await(yield __await(envelopeDecompress(env, compression, readMaxBytes)));
        }
      } catch (e_9_1) {
        e_9 = { error: e_9_1 };
      } finally {
        try {
          if (!_d && !_a && (_b = iterable_9.return)) yield __await(_b.call(iterable_9));
        } finally {
          if (e_9) throw e_9.error;
        }
      }
    });
  };
}
function transformJoinEnvelopes() {
  return function(iterable) {
    return __asyncGenerator(this, arguments, function* () {
      var _a, e_10, _b, _c;
      try {
        for (var _d = true, iterable_10 = __asyncValues(iterable), iterable_10_1; iterable_10_1 = yield __await(iterable_10.next()), _a = iterable_10_1.done, !_a; _d = true) {
          _c = iterable_10_1.value;
          _d = false;
          const { flags, data } = _c;
          yield yield __await(encodeEnvelope(flags, data));
        }
      } catch (e_10_1) {
        e_10 = { error: e_10_1 };
      } finally {
        try {
          if (!_d && !_a && (_b = iterable_10.return)) yield __await(_b.call(iterable_10));
        } finally {
          if (e_10) throw e_10.error;
        }
      }
    });
  };
}
function transformSplitEnvelope(readMaxBytes) {
  return function(iterable) {
    return __asyncGenerator(this, arguments, function* () {
      var _a, e_11, _b, _c;
      const buffer = createEnvelopeDecoder(readMaxBytes);
      try {
        for (var _d = true, iterable_11 = __asyncValues(iterable), iterable_11_1; iterable_11_1 = yield __await(iterable_11.next()), _a = iterable_11_1.done, !_a; _d = true) {
          _c = iterable_11_1.value;
          _d = false;
          const chunk = _c;
          for (const env of buffer.decode(chunk)) {
            yield yield __await(env);
          }
        }
      } catch (e_11_1) {
        e_11 = { error: e_11_1 };
      } finally {
        try {
          if (!_d && !_a && (_b = iterable_11.return)) yield __await(_b.call(iterable_11));
        } finally {
          if (e_11) throw e_11.error;
        }
      }
      if (buffer.byteLength > 0) {
        throw new ConnectError("protocol error: incomplete envelope", Code.InvalidArgument);
      }
    });
  };
}
function makeIterableAbortable(iterable) {
  const innerCandidate = iterable[Symbol.asyncIterator]();
  if (innerCandidate.throw === void 0) {
    throw new Error("AsyncIterable does not implement throw");
  }
  const inner = innerCandidate;
  let aborted;
  let resultPromise;
  let it = {
    next() {
      resultPromise = inner.next().finally(() => {
        resultPromise = void 0;
      });
      return resultPromise;
    },
    throw(e) {
      return inner.throw(e);
    }
  };
  if (innerCandidate.return !== void 0) {
    it = Object.assign(Object.assign({}, it), { return(value) {
      return inner.return(value);
    } });
  }
  let used = false;
  return {
    abort(reason) {
      if (aborted) {
        return aborted.state;
      }
      const f = () => {
        return inner.throw(reason).then((r) => r.done === true ? "completed" : "caught", () => "rethrown");
      };
      if (resultPromise) {
        aborted = { reason, state: resultPromise.then(f, f) };
        return aborted.state;
      }
      aborted = { reason, state: f() };
      return aborted.state;
    },
    [Symbol.asyncIterator]() {
      if (used) {
        throw new Error("AsyncIterable cannot be re-used");
      }
      used = true;
      return it;
    }
  };
}
function createAsyncIterable(items) {
  return __asyncGenerator(this, arguments, function* createAsyncIterable_1() {
    yield __await(yield* __asyncDelegator(__asyncValues(items)));
  });
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/promise-client.js
var __asyncValues2 = function(o) {
  if (!Symbol.asyncIterator) throw new TypeError("Symbol.asyncIterator is not defined.");
  var m = o[Symbol.asyncIterator], i;
  return m ? m.call(o) : (o = typeof __values === "function" ? __values(o) : o[Symbol.iterator](), i = {}, verb("next"), verb("throw"), verb("return"), i[Symbol.asyncIterator] = function() {
    return this;
  }, i);
  function verb(n) {
    i[n] = o[n] && function(v) {
      return new Promise(function(resolve2, reject) {
        v = o[n](v), settle(resolve2, reject, v.done, v.value);
      });
    };
  }
  function settle(resolve2, reject, d, v) {
    Promise.resolve(v).then(function(v2) {
      resolve2({ value: v2, done: d });
    }, reject);
  }
};
var __await2 = function(v) {
  return this instanceof __await2 ? (this.v = v, this) : new __await2(v);
};
var __asyncDelegator2 = function(o) {
  var i, p;
  return i = {}, verb("next"), verb("throw", function(e) {
    throw e;
  }), verb("return"), i[Symbol.iterator] = function() {
    return this;
  }, i;
  function verb(n, f) {
    i[n] = o[n] ? function(v) {
      return (p = !p) ? { value: __await2(o[n](v)), done: false } : f ? f(v) : v;
    } : f;
  }
};
var __asyncGenerator2 = function(thisArg, _arguments, generator) {
  if (!Symbol.asyncIterator) throw new TypeError("Symbol.asyncIterator is not defined.");
  var g = generator.apply(thisArg, _arguments || []), i, q = [];
  return i = Object.create((typeof AsyncIterator === "function" ? AsyncIterator : Object).prototype), verb("next"), verb("throw"), verb("return", awaitReturn), i[Symbol.asyncIterator] = function() {
    return this;
  }, i;
  function awaitReturn(f) {
    return function(v) {
      return Promise.resolve(v).then(f, reject);
    };
  }
  function verb(n, f) {
    if (g[n]) {
      i[n] = function(v) {
        return new Promise(function(a, b) {
          q.push([n, v, a, b]) > 1 || resume(n, v);
        });
      };
      if (f) i[n] = f(i[n]);
    }
  }
  function resume(n, v) {
    try {
      step(g[n](v));
    } catch (e) {
      settle(q[0][3], e);
    }
  }
  function step(r) {
    r.value instanceof __await2 ? Promise.resolve(r.value.v).then(fulfill, reject) : settle(q[0][2], r);
  }
  function fulfill(value) {
    resume("next", value);
  }
  function reject(value) {
    resume("throw", value);
  }
  function settle(f, v) {
    if (f(v), q.shift(), q.length) resume(q[0][0], q[0][1]);
  }
};
function createClient(service, transport) {
  return makeAnyClient(service, (method) => {
    switch (method.methodKind) {
      case "unary":
        return createUnaryFn(transport, method);
      case "server_streaming":
        return createServerStreamingFn(transport, method);
      case "client_streaming":
        return createClientStreamingFn(transport, method);
      case "bidi_streaming":
        return createBiDiStreamingFn(transport, method);
      default:
        return null;
    }
  });
}
function createUnaryFn(transport, method) {
  return async (input, options) => {
    var _a, _b;
    const response = await transport.unary(method, options === null || options === void 0 ? void 0 : options.signal, options === null || options === void 0 ? void 0 : options.timeoutMs, options === null || options === void 0 ? void 0 : options.headers, input, options === null || options === void 0 ? void 0 : options.contextValues);
    (_a = options === null || options === void 0 ? void 0 : options.onHeader) === null || _a === void 0 ? void 0 : _a.call(options, response.header);
    (_b = options === null || options === void 0 ? void 0 : options.onTrailer) === null || _b === void 0 ? void 0 : _b.call(options, response.trailer);
    return response.message;
  };
}
function createServerStreamingFn(transport, method) {
  return (input, options) => handleStreamResponse(transport.stream(method, options === null || options === void 0 ? void 0 : options.signal, options === null || options === void 0 ? void 0 : options.timeoutMs, options === null || options === void 0 ? void 0 : options.headers, createAsyncIterable([input]), options === null || options === void 0 ? void 0 : options.contextValues), options);
}
function createClientStreamingFn(transport, method) {
  return async (request3, options) => {
    var _a, e_1, _b, _c;
    var _d, _e;
    const response = await transport.stream(method, options === null || options === void 0 ? void 0 : options.signal, options === null || options === void 0 ? void 0 : options.timeoutMs, options === null || options === void 0 ? void 0 : options.headers, request3, options === null || options === void 0 ? void 0 : options.contextValues);
    (_d = options === null || options === void 0 ? void 0 : options.onHeader) === null || _d === void 0 ? void 0 : _d.call(options, response.header);
    let singleMessage;
    let count = 0;
    try {
      for (var _f = true, _g = __asyncValues2(response.message), _h; _h = await _g.next(), _a = _h.done, !_a; _f = true) {
        _c = _h.value;
        _f = false;
        const message = _c;
        singleMessage = message;
        count++;
      }
    } catch (e_1_1) {
      e_1 = { error: e_1_1 };
    } finally {
      try {
        if (!_f && !_a && (_b = _g.return)) await _b.call(_g);
      } finally {
        if (e_1) throw e_1.error;
      }
    }
    if (!singleMessage) {
      throw new ConnectError("protocol error: missing response message", Code.Unimplemented);
    }
    if (count > 1) {
      throw new ConnectError("protocol error: received extra messages for client streaming method", Code.Unimplemented);
    }
    (_e = options === null || options === void 0 ? void 0 : options.onTrailer) === null || _e === void 0 ? void 0 : _e.call(options, response.trailer);
    return singleMessage;
  };
}
function createBiDiStreamingFn(transport, method) {
  return (request3, options) => handleStreamResponse(transport.stream(method, options === null || options === void 0 ? void 0 : options.signal, options === null || options === void 0 ? void 0 : options.timeoutMs, options === null || options === void 0 ? void 0 : options.headers, request3, options === null || options === void 0 ? void 0 : options.contextValues), options);
}
function handleStreamResponse(stream, options) {
  const it = (function() {
    return __asyncGenerator2(this, arguments, function* () {
      var _a, _b;
      const response = yield __await2(stream);
      (_a = options === null || options === void 0 ? void 0 : options.onHeader) === null || _a === void 0 ? void 0 : _a.call(options, response.header);
      yield __await2(yield* __asyncDelegator2(__asyncValues2(response.message)));
      (_b = options === null || options === void 0 ? void 0 : options.onTrailer) === null || _b === void 0 ? void 0 : _b.call(options, response.trailer);
    });
  })()[Symbol.asyncIterator]();
  return {
    [Symbol.asyncIterator]: () => ({
      next: () => it.next()
    })
  };
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/signals.js
function createLinkedAbortController(...signals) {
  const controller = new AbortController();
  const sa = signals.filter((s) => s !== void 0).concat(controller.signal);
  for (const signal of sa) {
    if (signal.aborted) {
      onAbort.apply(signal);
      break;
    }
    signal.addEventListener("abort", onAbort);
  }
  function onAbort() {
    if (!controller.signal.aborted) {
      controller.abort(getAbortSignalReason(this));
    }
    for (const signal of sa) {
      signal.removeEventListener("abort", onAbort);
    }
  }
  return controller;
}
function createDeadlineSignal(timeoutMs) {
  const controller = new AbortController();
  const listener = () => {
    controller.abort(new ConnectError("the operation timed out", Code.DeadlineExceeded));
  };
  let timeoutId;
  if (timeoutMs !== void 0) {
    if (timeoutMs <= 0)
      listener();
    else
      timeoutId = setTimeout(listener, timeoutMs);
  }
  return {
    signal: controller.signal,
    cleanup: () => clearTimeout(timeoutId)
  };
}
function getAbortSignalReason(signal) {
  if (!signal.aborted) {
    return void 0;
  }
  if (signal.reason !== void 0) {
    return signal.reason;
  }
  const e = new Error("This operation was aborted");
  e.name = "AbortError";
  return e;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/context-values.js
function createContextValues() {
  return {
    get(key) {
      return key.id in this ? this[key.id] : key.defaultValue;
    },
    set(key, value) {
      this[key.id] = value;
      return this;
    },
    delete(key) {
      delete this[key.id];
      return this;
    }
  };
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/headers.js
var headerContentType = "Content-Type";
var headerEncoding = "Grpc-Encoding";
var headerAcceptEncoding = "Grpc-Accept-Encoding";
var headerTimeout = "Grpc-Timeout";
var headerGrpcStatus = "Grpc-Status";
var headerGrpcMessage = "Grpc-Message";
var headerStatusDetailsBin = "Grpc-Status-Details-Bin";
var headerUserAgent = "User-Agent";

// node_modules/.pnpm/@bufbuild+protobuf@2.11.0/node_modules/@bufbuild/protobuf/dist/esm/codegenv2/service.js
function serviceDesc(file, path4, ...paths) {
  if (paths.length > 0) {
    throw new Error();
  }
  return file.services[path4];
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/gen/status_pb.js
var file_status = /* @__PURE__ */ fileDesc("CgxzdGF0dXMucHJvdG8SCmdvb2dsZS5ycGMiTgoGU3RhdHVzEgwKBGNvZGUYASABKAUSDwoHbWVzc2FnZRgCIAEoCRIlCgdkZXRhaWxzGAMgAygLMhQuZ29vZ2xlLnByb3RvYnVmLkFueUJeCg5jb20uZ29vZ2xlLnJwY0ILU3RhdHVzUHJvdG9QAVo3Z29vZ2xlLmdvbGFuZy5vcmcvZ2VucHJvdG8vZ29vZ2xlYXBpcy9ycGMvc3RhdHVzO3N0YXR1c6ICA1JQQ2IGcHJvdG8z", [file_google_protobuf_any]);
var StatusSchema = /* @__PURE__ */ messageDesc(file_status, 0);

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/trailer-status.js
var grpcStatusOk = "0";
function findTrailerError(headerOrTrailer) {
  var _a;
  const statusBytes = headerOrTrailer.get(headerStatusDetailsBin);
  if (statusBytes != null) {
    const status = decodeBinaryHeader(statusBytes, StatusSchema);
    if (status.code == 0) {
      return void 0;
    }
    const error2 = new ConnectError(status.message, status.code, headerOrTrailer);
    error2.details = status.details.map((any) => ({
      type: any.typeUrl.substring(any.typeUrl.lastIndexOf("/") + 1),
      value: any.value
    }));
    return error2;
  }
  const grpcStatus = headerOrTrailer.get(headerGrpcStatus);
  if (grpcStatus != null) {
    if (grpcStatus === grpcStatusOk) {
      return void 0;
    }
    const code = parseInt(grpcStatus, 10);
    if (code in Code) {
      return new ConnectError(decodeURIComponent((_a = headerOrTrailer.get(headerGrpcMessage)) !== null && _a !== void 0 ? _a : ""), code, headerOrTrailer);
    }
    return new ConnectError(`invalid grpc-status: ${grpcStatus}`, Code.Internal, headerOrTrailer);
  }
  return void 0;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/create-method-url.js
function createMethodUrl(baseUrl, method) {
  return baseUrl.toString().replace(/\/?$/, `/${method.parent.typeName}/${method.name}`);
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/normalize.js
function normalize(desc, message) {
  return create(desc, message);
}
function normalizeIterable(desc, input) {
  function transform(result) {
    if (result.done === true) {
      return result;
    }
    return {
      done: result.done,
      value: normalize(desc, result.value)
    };
  }
  return {
    [Symbol.asyncIterator]() {
      const it = input[Symbol.asyncIterator]();
      const res = {
        next: () => it.next().then(transform)
      };
      if (it.throw !== void 0) {
        res.throw = (e) => it.throw(e).then(transform);
      }
      if (it.return !== void 0) {
        res.return = (v) => it.return(v).then(transform);
      }
      return res;
    }
  };
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/interceptor.js
function applyInterceptors(next, interceptors) {
  if (!interceptors) {
    return next;
  }
  for (const i of interceptors.concat().reverse()) {
    next = i(next);
  }
  return next;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/serialization.js
function getJsonOptions(options) {
  var _a;
  const o = Object.assign({}, options);
  (_a = o.ignoreUnknownFields) !== null && _a !== void 0 ? _a : o.ignoreUnknownFields = true;
  return o;
}
function createMethodSerializationLookup(method, binaryOptions, jsonOptions, limitOptions) {
  const inputBinary = limitSerialization(createBinarySerialization(method.input, binaryOptions), limitOptions);
  const inputJson = limitSerialization(createJsonSerialization(method.input, jsonOptions), limitOptions);
  const outputBinary = limitSerialization(createBinarySerialization(method.output, binaryOptions), limitOptions);
  const outputJson = limitSerialization(createJsonSerialization(method.output, jsonOptions), limitOptions);
  return {
    getI(useBinaryFormat) {
      return useBinaryFormat ? inputBinary : inputJson;
    },
    getO(useBinaryFormat) {
      return useBinaryFormat ? outputBinary : outputJson;
    }
  };
}
function limitSerialization(serialization, limitOptions) {
  return {
    serialize(data) {
      const bytes = serialization.serialize(data);
      assertWriteMaxBytes(limitOptions.writeMaxBytes, bytes.byteLength);
      return bytes;
    },
    parse(data) {
      assertReadMaxBytes(limitOptions.readMaxBytes, data.byteLength, true);
      return serialization.parse(data);
    }
  };
}
function createBinarySerialization(desc, options) {
  return {
    parse(data) {
      try {
        return fromBinary(desc, data, options);
      } catch (e) {
        const m = e instanceof Error ? e.message : String(e);
        throw new ConnectError(`parse binary: ${m}`, Code.Internal);
      }
    },
    serialize(data) {
      try {
        return toBinary(desc, data, options);
      } catch (e) {
        const m = e instanceof Error ? e.message : String(e);
        throw new ConnectError(`serialize binary: ${m}`, Code.Internal);
      }
    }
  };
}
function createJsonSerialization(desc, options) {
  var _a, _b;
  const textEncoder2 = (_a = options === null || options === void 0 ? void 0 : options.textEncoder) !== null && _a !== void 0 ? _a : new TextEncoder();
  const textDecoder2 = (_b = options === null || options === void 0 ? void 0 : options.textDecoder) !== null && _b !== void 0 ? _b : new TextDecoder();
  const o = getJsonOptions(options);
  return {
    parse(data) {
      try {
        const json = textDecoder2.decode(data);
        return fromJsonString(desc, json, o);
      } catch (e) {
        throw ConnectError.from(e, Code.InvalidArgument);
      }
    },
    serialize(data) {
      try {
        const json = toJsonString(desc, data, o);
        return textEncoder2.encode(json);
      } catch (e) {
        throw ConnectError.from(e, Code.Internal);
      }
    }
  };
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/content-type.js
var contentTypeRegExp = /^application\/grpc(?:\+(?:(json)(?:; ?charset=utf-?8)?|proto))?$/i;
var contentTypeProto = "application/grpc+proto";
var contentTypeJson = "application/grpc+json";
function parseContentType(contentType) {
  const match = contentType === null || contentType === void 0 ? void 0 : contentType.match(contentTypeRegExp);
  if (!match) {
    return void 0;
  }
  const binary = !match[1];
  return { binary };
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol/run-call.js
function runUnaryCall(opt) {
  const next = applyInterceptors(opt.next, opt.interceptors);
  const [signal, abort, done] = setupSignal(opt);
  const req = Object.assign(Object.assign({}, opt.req), { message: normalize(opt.req.method.input, opt.req.message), signal });
  return next(req).then((res) => {
    done();
    return res;
  }, abort);
}
function runStreamingCall(opt) {
  const next = applyInterceptors(opt.next, opt.interceptors);
  const [signal, abort, done] = setupSignal(opt);
  const req = Object.assign(Object.assign({}, opt.req), { message: normalizeIterable(opt.req.method.input, opt.req.message), signal });
  let doneCalled = false;
  signal.addEventListener("abort", function() {
    var _a, _b;
    const it = opt.req.message[Symbol.asyncIterator]();
    if (!doneCalled) {
      (_a = it.throw) === null || _a === void 0 ? void 0 : _a.call(it, this.reason).catch(() => {
      });
    }
    (_b = it.return) === null || _b === void 0 ? void 0 : _b.call(it).catch(() => {
    });
  });
  return next(req).then((res) => {
    return Object.assign(Object.assign({}, res), { message: {
      [Symbol.asyncIterator]() {
        const it = res.message[Symbol.asyncIterator]();
        return {
          next() {
            return it.next().then((r) => {
              if (r.done == true) {
                doneCalled = true;
                done();
              }
              return r;
            }, abort);
          }
          // We deliberately omit throw/return.
        };
      }
    } });
  }, abort);
}
function setupSignal(opt) {
  const { signal, cleanup } = createDeadlineSignal(opt.timeoutMs);
  const controller = createLinkedAbortController(opt.signal, signal);
  return [
    controller.signal,
    function abort(reason) {
      const e = ConnectError.from(signal.aborted ? getAbortSignalReason(signal) : reason);
      controller.abort(e);
      cleanup();
      return Promise.reject(e);
    },
    function done() {
      cleanup();
      controller.abort();
    }
  ];
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/validate-trailer.js
function validateTrailer(trailer, header) {
  const err = findTrailerError(trailer);
  if (err) {
    header.forEach((value, key) => {
      err.metadata.append(key, value);
    });
    throw err;
  }
  if (!header.has(headerGrpcStatus) && !trailer.has(headerGrpcStatus)) {
    throw new ConnectError("protocol error: missing status", Code.Internal);
  }
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/http-status.js
function codeFromHttpStatus(httpStatus) {
  switch (httpStatus) {
    case 400:
      return Code.Internal;
    case 401:
      return Code.Unauthenticated;
    case 403:
      return Code.PermissionDenied;
    case 404:
      return Code.Unimplemented;
    case 429:
      return Code.Unavailable;
    case 502:
      return Code.Unavailable;
    case 503:
      return Code.Unavailable;
    case 504:
      return Code.Unavailable;
    default:
      return Code.Unknown;
  }
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/request-header.js
function requestHeader(useBinaryFormat, timeoutMs, userProvidedHeaders) {
  const result = new Headers(userProvidedHeaders !== null && userProvidedHeaders !== void 0 ? userProvidedHeaders : {});
  result.set(headerContentType, useBinaryFormat ? contentTypeProto : contentTypeJson);
  if (!result.has(headerUserAgent)) {
    result.set(headerUserAgent, "connect-es/2.1.1");
  }
  if (timeoutMs !== void 0) {
    result.set(headerTimeout, `${timeoutMs}m`);
  }
  result.set("Te", "trailers");
  return result;
}
function requestHeaderWithCompression(useBinaryFormat, timeoutMs, userProvidedHeaders, acceptCompression, sendCompression) {
  const result = requestHeader(useBinaryFormat, timeoutMs, userProvidedHeaders);
  if (sendCompression != null) {
    result.set(headerEncoding, sendCompression.name);
  }
  if (acceptCompression.length > 0) {
    result.set(headerAcceptEncoding, acceptCompression.map((c) => c.name).join(","));
  }
  return result;
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/validate-response.js
function validateResponse(status, headers) {
  if (status != 200) {
    throw new ConnectError(`HTTP ${status}`, codeFromHttpStatus(status), headers);
  }
  const mimeType = headers.get(headerContentType);
  const parsedType = parseContentType(mimeType);
  if (parsedType == void 0) {
    throw new ConnectError(`unsupported content type ${mimeType}`, Code.Unknown);
  }
  return {
    foundStatus: headers.has(headerGrpcStatus),
    headerError: findTrailerError(headers)
  };
}
function validateResponseWithCompression(acceptCompression, status, headers) {
  const { foundStatus, headerError } = validateResponse(status, headers);
  let compression;
  const encoding = headers.get(headerEncoding);
  if (encoding !== null && encoding.toLowerCase() !== "identity") {
    compression = acceptCompression.find((c) => c.name === encoding);
    if (!compression) {
      throw new ConnectError(`unsupported response encoding "${encoding}"`, Code.Internal, headers);
    }
  }
  return {
    foundStatus,
    compression,
    headerError
  };
}

// node_modules/.pnpm/@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0/node_modules/@connectrpc/connect/dist/esm/protocol-grpc/transport.js
var __asyncValues3 = function(o) {
  if (!Symbol.asyncIterator) throw new TypeError("Symbol.asyncIterator is not defined.");
  var m = o[Symbol.asyncIterator], i;
  return m ? m.call(o) : (o = typeof __values === "function" ? __values(o) : o[Symbol.iterator](), i = {}, verb("next"), verb("throw"), verb("return"), i[Symbol.asyncIterator] = function() {
    return this;
  }, i);
  function verb(n) {
    i[n] = o[n] && function(v) {
      return new Promise(function(resolve2, reject) {
        v = o[n](v), settle(resolve2, reject, v.done, v.value);
      });
    };
  }
  function settle(resolve2, reject, d, v) {
    Promise.resolve(v).then(function(v2) {
      resolve2({ value: v2, done: d });
    }, reject);
  }
};
var __await3 = function(v) {
  return this instanceof __await3 ? (this.v = v, this) : new __await3(v);
};
var __asyncDelegator3 = function(o) {
  var i, p;
  return i = {}, verb("next"), verb("throw", function(e) {
    throw e;
  }), verb("return"), i[Symbol.iterator] = function() {
    return this;
  }, i;
  function verb(n, f) {
    i[n] = o[n] ? function(v) {
      return (p = !p) ? { value: __await3(o[n](v)), done: false } : f ? f(v) : v;
    } : f;
  }
};
var __asyncGenerator3 = function(thisArg, _arguments, generator) {
  if (!Symbol.asyncIterator) throw new TypeError("Symbol.asyncIterator is not defined.");
  var g = generator.apply(thisArg, _arguments || []), i, q = [];
  return i = Object.create((typeof AsyncIterator === "function" ? AsyncIterator : Object).prototype), verb("next"), verb("throw"), verb("return", awaitReturn), i[Symbol.asyncIterator] = function() {
    return this;
  }, i;
  function awaitReturn(f) {
    return function(v) {
      return Promise.resolve(v).then(f, reject);
    };
  }
  function verb(n, f) {
    if (g[n]) {
      i[n] = function(v) {
        return new Promise(function(a, b) {
          q.push([n, v, a, b]) > 1 || resume(n, v);
        });
      };
      if (f) i[n] = f(i[n]);
    }
  }
  function resume(n, v) {
    try {
      step(g[n](v));
    } catch (e) {
      settle(q[0][3], e);
    }
  }
  function step(r) {
    r.value instanceof __await3 ? Promise.resolve(r.value.v).then(fulfill, reject) : settle(q[0][2], r);
  }
  function fulfill(value) {
    resume("next", value);
  }
  function reject(value) {
    resume("throw", value);
  }
  function settle(f, v) {
    if (f(v), q.shift(), q.length) resume(q[0][0], q[0][1]);
  }
};
function createTransport(opt) {
  return {
    async unary(method, signal, timeoutMs, header, message, contextValues) {
      const serialization = createMethodSerializationLookup(method, opt.binaryOptions, opt.jsonOptions, opt);
      timeoutMs = timeoutMs === void 0 ? opt.defaultTimeoutMs : timeoutMs <= 0 ? void 0 : timeoutMs;
      return await runUnaryCall({
        interceptors: opt.interceptors,
        signal,
        timeoutMs,
        req: {
          stream: false,
          service: method.parent,
          method,
          requestMethod: "POST",
          url: createMethodUrl(opt.baseUrl, method),
          header: requestHeaderWithCompression(opt.useBinaryFormat, timeoutMs, header, opt.acceptCompression, opt.sendCompression),
          contextValues: contextValues !== null && contextValues !== void 0 ? contextValues : createContextValues(),
          message
        },
        next: async (req) => {
          const uRes = await opt.httpClient({
            url: req.url,
            method: "POST",
            header: req.header,
            signal: req.signal,
            body: pipe(createAsyncIterable([req.message]), transformSerializeEnvelope(serialization.getI(opt.useBinaryFormat)), transformCompressEnvelope(opt.sendCompression, opt.compressMinBytes), transformJoinEnvelopes(), {
              propagateDownStreamError: true
            })
          });
          const { compression, headerError } = validateResponseWithCompression(opt.acceptCompression, uRes.status, uRes.header);
          const message2 = await pipeTo(uRes.body, transformSplitEnvelope(opt.readMaxBytes), transformDecompressEnvelope(compression !== null && compression !== void 0 ? compression : null, opt.readMaxBytes), transformParseEnvelope(serialization.getO(opt.useBinaryFormat)), async (iterable) => {
            var _a, e_1, _b, _c;
            let message3;
            try {
              for (var _d = true, iterable_1 = __asyncValues3(iterable), iterable_1_1; iterable_1_1 = await iterable_1.next(), _a = iterable_1_1.done, !_a; _d = true) {
                _c = iterable_1_1.value;
                _d = false;
                const chunk = _c;
                if (message3 !== void 0) {
                  throw new ConnectError("protocol error: received extra output message for unary method", Code.Unimplemented);
                }
                message3 = chunk;
              }
            } catch (e_1_1) {
              e_1 = { error: e_1_1 };
            } finally {
              try {
                if (!_d && !_a && (_b = iterable_1.return)) await _b.call(iterable_1);
              } finally {
                if (e_1) throw e_1.error;
              }
            }
            return message3;
          }, { propagateDownStreamError: false });
          validateTrailer(uRes.trailer, uRes.header);
          if (message2 === void 0) {
            if (headerError) {
              throw headerError;
            }
            throw new ConnectError("protocol error: missing output message for unary method", uRes.trailer.has(headerGrpcStatus) ? Code.Unimplemented : Code.Unknown);
          }
          if (headerError) {
            throw new ConnectError("protocol error: received output message for unary method with error status", Code.Unknown);
          }
          return {
            stream: false,
            service: method.parent,
            method,
            header: uRes.header,
            message: message2,
            trailer: uRes.trailer
          };
        }
      });
    },
    async stream(method, signal, timeoutMs, header, input, contextValues) {
      const serialization = createMethodSerializationLookup(method, opt.binaryOptions, opt.jsonOptions, opt);
      timeoutMs = timeoutMs === void 0 ? opt.defaultTimeoutMs : timeoutMs <= 0 ? void 0 : timeoutMs;
      return runStreamingCall({
        interceptors: opt.interceptors,
        signal,
        timeoutMs,
        req: {
          stream: true,
          service: method.parent,
          method,
          requestMethod: "POST",
          url: createMethodUrl(opt.baseUrl, method),
          header: requestHeaderWithCompression(opt.useBinaryFormat, timeoutMs, header, opt.acceptCompression, opt.sendCompression),
          contextValues: contextValues !== null && contextValues !== void 0 ? contextValues : createContextValues(),
          message: input
        },
        next: async (req) => {
          const uRes = await opt.httpClient({
            url: req.url,
            method: "POST",
            header: req.header,
            signal: req.signal,
            body: pipe(req.message, transformSerializeEnvelope(serialization.getI(opt.useBinaryFormat)), transformCompressEnvelope(opt.sendCompression, opt.compressMinBytes), transformJoinEnvelopes(), { propagateDownStreamError: true })
          });
          const { compression, foundStatus, headerError } = validateResponseWithCompression(opt.acceptCompression, uRes.status, uRes.header);
          if (headerError) {
            throw headerError;
          }
          const res = Object.assign(Object.assign({}, req), { header: uRes.header, trailer: uRes.trailer, message: pipe(uRes.body, transformSplitEnvelope(opt.readMaxBytes), transformDecompressEnvelope(compression !== null && compression !== void 0 ? compression : null, opt.readMaxBytes), transformParseEnvelope(serialization.getO(opt.useBinaryFormat)), function(iterable) {
            return __asyncGenerator3(this, arguments, function* () {
              yield __await3(yield* __asyncDelegator3(__asyncValues3(iterable)));
              if (!foundStatus) {
                validateTrailer(uRes.trailer, uRes.header);
              }
            });
          }, { propagateDownStreamError: true }) });
          return res;
        }
      });
    }
  };
}

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/compression.js
import * as zlib from "zlib";
import { promisify } from "util";

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/node-error.js
function connectErrorFromNodeReason(reason) {
  let code = Code.Internal;
  const chain = unwrapNodeErrorChain(reason).map(getNodeErrorProps);
  if (chain.some((p) => p.code == "ERR_STREAM_WRITE_AFTER_END")) {
    code = Code.Aborted;
  } else if (chain.some((p) => p.code == "ERR_STREAM_DESTROYED" || p.code == "ERR_HTTP2_INVALID_STREAM" || p.code == "ECONNRESET")) {
    code = Code.Aborted;
  } else if (chain.some((p) => p.code == "ETIMEDOUT" || p.code == "ENOTFOUND" || p.code == "EAI_AGAIN" || p.code == "ECONNREFUSED")) {
    code = Code.Unavailable;
  }
  const ce = ConnectError.from(reason, code);
  if (ce !== reason) {
    ce.cause = reason;
  }
  return ce;
}
function unwrapNodeErrorChain(reason) {
  const chain = [];
  for (; ; ) {
    if (!(reason instanceof Error)) {
      break;
    }
    if (chain.includes(reason)) {
      break;
    }
    chain.push(reason);
    if (!("cause" in reason)) {
      break;
    }
    reason = reason.cause;
  }
  return chain;
}
function getNodeErrorProps(reason) {
  const props = {};
  if (reason instanceof Error) {
    if ("code" in reason && typeof reason.code == "string") {
      props.code = reason.code;
    }
    if ("syscall" in reason && typeof reason.syscall == "string") {
      props.syscall = reason.syscall;
    }
  }
  return props;
}
function connectErrorFromH2ResetCode(rstCode) {
  switch (rstCode) {
    case H2Code.PROTOCOL_ERROR:
    case H2Code.INTERNAL_ERROR:
    case H2Code.FLOW_CONTROL_ERROR:
    case H2Code.SETTINGS_TIMEOUT:
    case H2Code.FRAME_SIZE_ERROR:
    case H2Code.COMPRESSION_ERROR:
    case H2Code.CONNECT_ERROR:
      return new ConnectError(`http/2 stream closed with error code ${H2Code[rstCode]} (0x${rstCode.toString(16)})`, Code.Internal);
    case H2Code.REFUSED_STREAM:
      return new ConnectError(`http/2 stream closed with error code ${H2Code[rstCode]} (0x${rstCode.toString(16)})`, Code.Unavailable);
    case H2Code.CANCEL:
      return new ConnectError(`http/2 stream closed with error code ${H2Code[rstCode]} (0x${rstCode.toString(16)})`, Code.Canceled);
    case H2Code.ENHANCE_YOUR_CALM:
      return new ConnectError(`http/2 stream closed with error code ${H2Code[rstCode]} (0x${rstCode.toString(16)})`, Code.ResourceExhausted);
    case H2Code.INADEQUATE_SECURITY:
      return new ConnectError(`http/2 stream closed with error code ${H2Code[rstCode]} (0x${rstCode.toString(16)})`, Code.PermissionDenied);
    case H2Code.HTTP_1_1_REQUIRED:
      return new ConnectError(`http/2 stream closed with error code ${H2Code[rstCode]} (0x${rstCode.toString(16)})`, Code.PermissionDenied);
    default:
      break;
  }
  return void 0;
}
var H2Code;
(function(H2Code2) {
  H2Code2[H2Code2["PROTOCOL_ERROR"] = 1] = "PROTOCOL_ERROR";
  H2Code2[H2Code2["INTERNAL_ERROR"] = 2] = "INTERNAL_ERROR";
  H2Code2[H2Code2["FLOW_CONTROL_ERROR"] = 3] = "FLOW_CONTROL_ERROR";
  H2Code2[H2Code2["SETTINGS_TIMEOUT"] = 4] = "SETTINGS_TIMEOUT";
  H2Code2[H2Code2["STREAM_CLOSED"] = 5] = "STREAM_CLOSED";
  H2Code2[H2Code2["FRAME_SIZE_ERROR"] = 6] = "FRAME_SIZE_ERROR";
  H2Code2[H2Code2["REFUSED_STREAM"] = 7] = "REFUSED_STREAM";
  H2Code2[H2Code2["CANCEL"] = 8] = "CANCEL";
  H2Code2[H2Code2["COMPRESSION_ERROR"] = 9] = "COMPRESSION_ERROR";
  H2Code2[H2Code2["CONNECT_ERROR"] = 10] = "CONNECT_ERROR";
  H2Code2[H2Code2["ENHANCE_YOUR_CALM"] = 11] = "ENHANCE_YOUR_CALM";
  H2Code2[H2Code2["INADEQUATE_SECURITY"] = 12] = "INADEQUATE_SECURITY";
  H2Code2[H2Code2["HTTP_1_1_REQUIRED"] = 13] = "HTTP_1_1_REQUIRED";
})(H2Code || (H2Code = {}));

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/compression.js
var gzip2 = promisify(zlib.gzip);
var gunzip2 = promisify(zlib.gunzip);
var brotliCompress2 = promisify(zlib.brotliCompress);
var brotliDecompress2 = promisify(zlib.brotliDecompress);
var compressionGzip = {
  name: "gzip",
  compress(bytes) {
    return asUint8ArrayArrayBuffer(gzip2(bytes, {}));
  },
  decompress(bytes, readMaxBytes) {
    if (bytes.length == 0) {
      return Promise.resolve(new Uint8Array(0));
    }
    return asUint8ArrayArrayBuffer(wrapZLibErrors(gunzip2(bytes, {
      maxOutputLength: readMaxBytes
    }), readMaxBytes));
  }
};
var compressionBrotli = {
  name: "br",
  compress(bytes) {
    return asUint8ArrayArrayBuffer(brotliCompress2(bytes, {}));
  },
  decompress(bytes, readMaxBytes) {
    if (bytes.length == 0) {
      return Promise.resolve(new Uint8Array(0));
    }
    return asUint8ArrayArrayBuffer(wrapZLibErrors(brotliDecompress2(bytes, {
      maxOutputLength: readMaxBytes
    }), readMaxBytes));
  }
};
function asUint8ArrayArrayBuffer(bytes) {
  return bytes.then((b) => {
    if (b.buffer instanceof ArrayBuffer) {
      return b;
    }
    return new Uint8Array(b);
  });
}
function wrapZLibErrors(promise, readMaxBytes) {
  return promise.catch((e) => {
    var _a;
    const props = getNodeErrorProps(e);
    let code = Code.Internal;
    let message = "decompression failed";
    switch (props.code) {
      case "ERR_BUFFER_TOO_LARGE":
        code = Code.ResourceExhausted;
        message = `message is larger than configured readMaxBytes ${readMaxBytes} after decompression`;
        break;
      case "Z_DATA_ERROR":
      case "ERR_PADDING_2":
        code = Code.InvalidArgument;
        break;
      default:
        if ((_a = props.code) === null || _a === void 0 ? void 0 : _a.startsWith("ERR__ERROR_FORMAT_")) {
          code = Code.InvalidArgument;
        }
        break;
    }
    return Promise.reject(new ConnectError(message, code, void 0, void 0, e));
  });
}

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/node-universal-client.js
import * as http from "http";
import * as https from "https";

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/node-universal-header.js
function nodeHeaderToWebHeader(nodeHeaders) {
  const header = new Headers();
  for (const [k, v] of Object.entries(nodeHeaders)) {
    if (k.startsWith(":")) {
      continue;
    }
    if (v === void 0) {
      continue;
    }
    if (typeof v == "string") {
      header.append(k, v);
    } else if (typeof v == "number") {
      header.append(k, String(v));
    } else {
      for (const e of v) {
        header.append(k, e);
      }
    }
  }
  return header;
}
function webHeaderToNodeHeaders(headersInit, defaultNodeHeaders) {
  if (headersInit === void 0 && defaultNodeHeaders === void 0) {
    return void 0;
  }
  const o = /* @__PURE__ */ Object.create(null);
  if (defaultNodeHeaders !== void 0) {
    if (Array.isArray(defaultNodeHeaders)) {
      for (let i = 0; i + 1 < defaultNodeHeaders.length; i += 2) {
        const key = defaultNodeHeaders[i];
        const value = defaultNodeHeaders[i + 1];
        if (Array.isArray(o[key])) {
          o[key].push(value);
        } else if (typeof o[key] == "string") {
          o[key] = [o[key], value];
        } else {
          o[key] = value;
        }
      }
    } else {
      for (const [key, value] of Object.entries(defaultNodeHeaders)) {
        if (Array.isArray(value)) {
          o[key] = value.concat();
        } else if (value !== void 0) {
          o[key] = value;
        }
      }
    }
  }
  if (headersInit !== void 0) {
    if (Array.isArray(headersInit)) {
      for (const [key, value] of headersInit) {
        appendWebHeader(o, key, value);
      }
    } else if ("forEach" in headersInit) {
      if (typeof headersInit.forEach == "function") {
        headersInit.forEach((value, key) => {
          appendWebHeader(o, key, value);
        });
      }
    } else {
      for (const [key, value] of Object.entries(headersInit)) {
        appendWebHeader(o, key, value);
      }
    }
  }
  return o;
}
function appendWebHeader(o, key, value) {
  key = key.toLowerCase();
  const existing = o[key];
  if (Array.isArray(existing)) {
    existing.push(value);
  } else if (existing === void 0) {
    o[key] = value;
  } else {
    o[key] = [existing.toString(), value];
  }
}

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/http2-session-manager.js
import * as http2 from "http2";
var Http2SessionManager = class {
  /**
   * The current state of the connection:
   *
   * - "closed"
   *   The connection is closed, or no connection has been opened yet.
   * - connecting
   *   Currently establishing a connection.
   *
   * - "open"
   *   A connection is open and has open streams. PING frames are sent every
   *   pingIntervalMs, unless a stream received data.
   *   If a PING frame is not responded to within pingTimeoutMs, the connection
   *   and all open streams close.
   *
   * - "idle"
   *   A connection is open, but it does not have any open streams.
   *   If pingIdleConnection is enabled, PING frames are used to keep the
   *   connection alive, similar to an "open" connection.
   *   If a connection is idle for longer than idleConnectionTimeoutMs, it closes.
   *   If a request is made on an idle connection that has not been used for
   *   longer than pingIntervalMs, the connection is verified.
   *
   * - "verifying"
   *   Verifying a connection after a long period of inactivity before issuing a
   *   request. A PING frame is sent, and if it times out within pingTimeoutMs, a
   *   new connection is opened.
   *
   * - "error"
   *   The connection is closed because of a transient error. A connection
   *   may have failed to reach the host, or the connection may have died,
   *   or it may have been aborted.
   */
  state() {
    if (this.s.t == "ready") {
      if (this.verifying !== void 0) {
        return "verifying";
      }
      return this.s.streamCount() > 0 ? "open" : "idle";
    }
    return this.s.t;
  }
  /**
   * Returns the error object if the connection is in the "error" state,
   * `undefined` otherwise.
   */
  error() {
    if (this.s.t == "error") {
      return this.s.reason;
    }
    return void 0;
  }
  constructor(url, pingOptions, http2SessionOptions) {
    var _a, _b, _c, _d;
    this.s = closed();
    this.shuttingDown = [];
    this.authority = new URL(url).origin;
    this.http2SessionOptions = http2SessionOptions;
    this.options = {
      pingIntervalMs: (_a = pingOptions === null || pingOptions === void 0 ? void 0 : pingOptions.pingIntervalMs) !== null && _a !== void 0 ? _a : Number.POSITIVE_INFINITY,
      pingTimeoutMs: (_b = pingOptions === null || pingOptions === void 0 ? void 0 : pingOptions.pingTimeoutMs) !== null && _b !== void 0 ? _b : 1e3 * 15,
      pingIdleConnection: (_c = pingOptions === null || pingOptions === void 0 ? void 0 : pingOptions.pingIdleConnection) !== null && _c !== void 0 ? _c : false,
      idleConnectionTimeoutMs: (_d = pingOptions === null || pingOptions === void 0 ? void 0 : pingOptions.idleConnectionTimeoutMs) !== null && _d !== void 0 ? _d : 1e3 * 60 * 15
    };
  }
  /**
   * Open a connection if none exists, verify an existing connection if
   * necessary.
   */
  async connect() {
    try {
      const ready2 = await this.gotoReady();
      return ready2.streamCount() > 0 ? "open" : "idle";
    } catch (e) {
      return "error";
    }
  }
  /**
   * Issue a request.
   *
   * This method automatically opens a connection if none exists, and verifies
   * an existing connection if necessary. It calls http2.ClientHttp2Session.request(),
   * and keeps track of all open http2.ClientHttp2Stream.
   *
   * Clients must call notifyResponseByteRead() whenever they successfully read
   * data from the http2.ClientHttp2Stream.
   */
  async request(method, path4, headers, options) {
    for (; ; ) {
      const ready2 = await this.gotoReady();
      try {
        const stream = ready2.conn.request(Object.assign(Object.assign({}, headers), { ":method": method, ":path": path4 }), options);
        ready2.registerRequest(stream);
        return stream;
      } catch (e) {
        if (ready2.conn.closed || ready2.conn.destroyed) {
          continue;
        }
        throw e;
      }
    }
  }
  /**
   * Notify the manager of a successful read from a http2.ClientHttp2Stream.
   *
   * Clients must call this function whenever they successfully read data from
   * a http2.ClientHttp2Stream obtained from request(). This informs the
   * keep-alive logic that the connection is alive, and prevents it from sending
   * unnecessary PING frames.
   */
  notifyResponseByteRead(stream) {
    if (this.s.t == "ready") {
      this.s.responseByteRead(stream);
    }
    for (const s of this.shuttingDown) {
      s.responseByteRead(stream);
    }
  }
  /**
   * If there is an open connection, close it. This also closes any open streams.
   */
  abort(reason) {
    var _a, _b, _c;
    const err = reason !== null && reason !== void 0 ? reason : new ConnectError("connection aborted", Code.Canceled);
    (_b = (_a = this.s).abort) === null || _b === void 0 ? void 0 : _b.call(_a, err);
    for (const s of this.shuttingDown) {
      (_c = s.abort) === null || _c === void 0 ? void 0 : _c.call(s, err);
    }
    this.setState(closedOrError(err));
  }
  async gotoReady() {
    if (this.s.t == "ready") {
      if (this.s.isShuttingDown() || this.s.conn.closed || this.s.conn.destroyed) {
        this.setState(connect2(this.authority, this.http2SessionOptions));
      } else if (this.s.requiresVerify()) {
        await this.verify(this.s);
      }
    } else if (this.s.t == "closed" || this.s.t == "error") {
      this.setState(connect2(this.authority, this.http2SessionOptions));
    }
    while (this.s.t !== "ready") {
      if (this.s.t === "error") {
        throw this.s.reason;
      }
      if (this.s.t === "connecting") {
        await this.s.conn;
      }
    }
    return this.s;
  }
  setState(state) {
    var _a, _b;
    (_b = (_a = this.s).onExitState) === null || _b === void 0 ? void 0 : _b.call(_a);
    if (this.s.t == "ready" && this.s.isShuttingDown()) {
      const sd = this.s;
      this.shuttingDown.push(sd);
      sd.onClose = sd.onError = () => {
        const i = this.shuttingDown.indexOf(sd);
        if (i !== -1) {
          this.shuttingDown.splice(i, 1);
        }
      };
    }
    switch (state.t) {
      case "connecting":
        state.conn.then((value) => {
          this.setState(ready(value, this.options));
        }, (reason) => {
          this.setState(closedOrError(reason));
        });
        break;
      case "ready":
        state.onClose = () => this.setState(closed());
        state.onError = (err) => this.setState(closedOrError(err));
        break;
      case "closed":
        break;
      case "error":
        break;
    }
    this.s = state;
  }
  verify(stateReady) {
    if (this.verifying !== void 0) {
      return this.verifying;
    }
    this.verifying = stateReady.verify().then((success) => {
      if (success) {
        return;
      }
      this.setState(connect2(this.authority, this.http2SessionOptions));
    }, (reason) => {
      this.setState(closedOrError(reason));
    }).finally(() => {
      this.verifying = void 0;
    });
    return this.verifying;
  }
};
function closed() {
  return {
    t: "closed"
  };
}
function error(reason) {
  return {
    t: "error",
    reason
  };
}
function closedOrError(reason) {
  const isCancel = reason instanceof ConnectError && ConnectError.from(reason).code == Code.Canceled;
  return isCancel ? closed() : error(reason);
}
function connect2(authority, http2SessionOptions) {
  let resolve2;
  let reject;
  const conn = new Promise((res, rej) => {
    resolve2 = res;
    reject = rej;
  });
  const newConn = http2.connect(authority, http2SessionOptions);
  newConn.on("connect", onConnect);
  newConn.on("error", onError);
  function onConnect() {
    resolve2 === null || resolve2 === void 0 ? void 0 : resolve2(newConn);
    cleanup();
  }
  function onError(err) {
    reject === null || reject === void 0 ? void 0 : reject(connectErrorFromNodeReason(err));
    cleanup();
  }
  function cleanup() {
    newConn.off("connect", onConnect);
    newConn.off("error", onError);
  }
  return {
    t: "connecting",
    conn,
    abort(reason) {
      if (!newConn.destroyed) {
        newConn.destroy(void 0, http2.constants.NGHTTP2_CANCEL);
      }
      reject === null || reject === void 0 ? void 0 : reject(reason);
    },
    onExitState() {
      cleanup();
    }
  };
}
function ready(conn, options) {
  assertSessionOpen(conn);
  conn.unref();
  let lastAliveAt = Date.now();
  let streamCount = 0;
  let pingIntervalId;
  let pingTimeoutId;
  let receivedGoAway = false;
  let receivedGoAwayEnhanceYourCalmTooManyPings = false;
  let idleTimeoutId;
  resetIdleTimeout();
  const state = {
    t: "ready",
    conn,
    streamCount() {
      return streamCount;
    },
    requiresVerify() {
      const elapsedMs = Date.now() - lastAliveAt;
      return elapsedMs > options.pingIntervalMs;
    },
    isShuttingDown() {
      return receivedGoAway;
    },
    onClose: void 0,
    onError: void 0,
    registerRequest(stream) {
      streamCount++;
      if (streamCount == 1) {
        conn.ref();
        resetPingInterval();
        stopIdleTimeout();
      }
      stream.once("response", () => {
        lastAliveAt = Date.now();
        resetPingInterval();
      });
      stream.once("close", () => {
        streamCount--;
        if (streamCount == 0) {
          conn.unref();
          resetPingInterval();
          resetIdleTimeout();
        }
      });
    },
    responseByteRead(stream) {
      if (stream.session !== conn) {
        return;
      }
      if (conn.closed || conn.destroyed) {
        return;
      }
      if (streamCount <= 0) {
        return;
      }
      lastAliveAt = Date.now();
      resetPingInterval();
    },
    verify() {
      conn.ref();
      return new Promise((resolve2) => {
        const onError2 = () => {
          resolve2(false);
        };
        commonPing(() => {
          if (streamCount == 0)
            conn.unref();
          conn.off("error", onError2);
          resolve2(true);
        });
        conn.once("error", onError2);
      });
    },
    abort(reason) {
      if (!conn.destroyed) {
        conn.once("error", () => {
        });
        conn.destroy(reason, http2.constants.NGHTTP2_CANCEL);
      }
    },
    onExitState() {
      if (state.isShuttingDown()) {
        return;
      }
      cleanup();
      this.onError = void 0;
      this.onClose = void 0;
    }
  };
  function resetPingInterval() {
    stopPingInterval();
    if (streamCount > 0 || options.pingIdleConnection) {
      pingIntervalId = safeSetTimeout(onPingInterval, options.pingIntervalMs);
    }
  }
  function stopPingInterval() {
    clearTimeout(pingIntervalId);
    clearTimeout(pingTimeoutId);
  }
  function onPingInterval() {
    commonPing(resetPingInterval);
  }
  function commonPing(onSuccess) {
    clearTimeout(pingTimeoutId);
    pingTimeoutId = safeSetTimeout(() => {
      conn.destroy(new ConnectError("PING timed out", Code.Unavailable), http2.constants.NGHTTP2_CANCEL);
    }, options.pingTimeoutMs);
    conn.ping((err, duration) => {
      clearTimeout(pingTimeoutId);
      if (err !== null) {
        return;
      }
      if (duration > options.pingTimeoutMs) {
        conn.destroy(new ConnectError("PING timed out", Code.Unavailable), http2.constants.NGHTTP2_CANCEL);
        return;
      }
      lastAliveAt = Date.now();
      onSuccess();
    });
  }
  function stopIdleTimeout() {
    clearTimeout(idleTimeoutId);
  }
  function resetIdleTimeout() {
    idleTimeoutId = safeSetTimeout(onIdleTimeout, options.idleConnectionTimeoutMs);
  }
  function onIdleTimeout() {
    conn.close();
    onClose();
  }
  function onGoaway(errorCode, lastStreamID, opaqueData) {
    if (errorCode === http2.constants.NGHTTP2_NO_ERROR && streamCount === 0) {
      conn.destroy(new ConnectError("received GOAWAY without any open streams", Code.Canceled), http2.constants.NGHTTP2_NO_ERROR);
      return;
    }
    receivedGoAway = true;
    const tooManyPingsAscii = Buffer.from("too_many_pings", "ascii");
    if (opaqueData === null || opaqueData === void 0 ? void 0 : opaqueData.equals(tooManyPingsAscii)) {
      options.pingIntervalMs = options.pingIntervalMs * 2;
      receivedGoAwayEnhanceYourCalmTooManyPings = true;
    }
  }
  function onClose() {
    var _a;
    cleanup();
    (_a = state.onClose) === null || _a === void 0 ? void 0 : _a.call(state);
  }
  function onError(err) {
    var _a, _b;
    cleanup();
    if (receivedGoAwayEnhanceYourCalmTooManyPings) {
      const ce = new ConnectError(`http/2 connection closed with error code ENHANCE_YOUR_CALM (0x${http2.constants.NGHTTP2_ENHANCE_YOUR_CALM.toString(16)}), too_many_pings, doubled the interval`, Code.ResourceExhausted);
      (_a = state.onError) === null || _a === void 0 ? void 0 : _a.call(state, ce);
    } else {
      (_b = state.onError) === null || _b === void 0 ? void 0 : _b.call(state, connectErrorFromNodeReason(err));
    }
  }
  function cleanup() {
    stopPingInterval();
    stopIdleTimeout();
    conn.off("error", onError);
    conn.off("close", onClose);
    conn.off("goaway", onGoaway);
  }
  conn.on("error", onError);
  conn.on("close", onClose);
  conn.on("goaway", onGoaway);
  return state;
}
function safeSetTimeout(callback, ms) {
  if (ms > 2147483647) {
    return;
  }
  return setTimeout(callback, ms).unref();
}
function assertSessionOpen(conn) {
  if (conn.connecting) {
    throw new ConnectError("expected open session, but it is connecting", Code.Internal);
  }
  if (conn.destroyed) {
    throw new ConnectError("expected open session, but it is destroyed", Code.Internal);
  }
  if (conn.closed) {
    throw new ConnectError("expected open session, but it is closed", Code.Internal);
  }
}

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/node-universal-client.js
function createNodeHttpClient(options) {
  var _a;
  if (options.httpVersion == "1.1") {
    return createNodeHttp1Client(options.nodeOptions);
  }
  const sessionProvider = (_a = options.sessionProvider) !== null && _a !== void 0 ? _a : ((url) => new Http2SessionManager(url));
  return createNodeHttp2Client(sessionProvider);
}
function createNodeHttp1Client(httpOptions) {
  return async function request3(req) {
    const sentinel = createSentinel(req.signal);
    return new Promise((resolve2, reject) => {
      sentinel.onError((e) => {
        reject(e);
      });
      h1Request(sentinel, req.url, Object.assign(Object.assign({}, httpOptions), { headers: webHeaderToNodeHeaders(req.header, httpOptions === null || httpOptions === void 0 ? void 0 : httpOptions.headers), method: req.method }), (request4) => {
        void sinkRequest(req, request4, sentinel);
        request4.on("response", (response) => {
          var _a;
          response.on("error", sentinel.error);
          sentinel.onError((reason) => response.destroy(reason));
          const trailer = new Headers();
          resolve2({
            status: (_a = response.statusCode) !== null && _a !== void 0 ? _a : 0,
            header: nodeHeaderToWebHeader(response.headers),
            body: h1ResponseIterable(sentinel, response, trailer),
            trailer
          });
        });
      });
    });
  };
}
function createNodeHttp2Client(sessionProvider) {
  return function request3(req) {
    const sentinel = createSentinel(req.signal);
    const sessionManager = sessionProvider(req.url);
    return new Promise((resolve2, reject) => {
      sentinel.onError((e) => {
        reject(e);
      });
      h2Request(sentinel, sessionManager, req.url, req.method, webHeaderToNodeHeaders(req.header), {}, (stream) => {
        void sinkRequest(req, stream, sentinel);
        stream.on("response", (headers) => {
          var _a;
          const response = {
            status: (_a = headers[":status"]) !== null && _a !== void 0 ? _a : 0,
            header: nodeHeaderToWebHeader(headers),
            body: h2ResponseIterable(sentinel, stream, sessionManager),
            trailer: h2ResponseTrailer(stream)
          };
          resolve2(response);
        });
      });
    });
  };
}
function h1Request(sentinel, url, options, onRequest) {
  let request3;
  if (new URL(url).protocol.startsWith("https")) {
    request3 = https.request(url, options);
  } else {
    request3 = http.request(url, options);
  }
  sentinel.onError((reason) => request3.destroy(reason));
  request3.flushHeaders();
  request3.on("error", sentinel.error);
  request3.on("socket", function onRequestSocket(socket) {
    function onSocketConnect() {
      socket.off("connect", onSocketConnect);
      onRequest(request3);
    }
    if (socket.readyState === "open") {
      onRequest(request3);
    } else {
      socket.on("connect", onSocketConnect);
    }
  });
}
function h1ResponseIterable(sentinel, response, trailer) {
  const inner = response[Symbol.asyncIterator]();
  return {
    [Symbol.asyncIterator]() {
      return {
        async next() {
          const r = await sentinel.race(inner.next());
          if (r.done === true) {
            nodeHeaderToWebHeader(response.trailers).forEach((value, key) => {
              trailer.set(key, value);
            });
            sentinel.close();
          }
          return r;
        },
        throw(e) {
          sentinel.error(e);
          throw e;
        }
      };
    }
  };
}
function h2Request(sentinel, sm, url, method, headers, options, onStream) {
  const requestUrl = new URL(url);
  if (requestUrl.origin !== sm.authority) {
    const message = `cannot make a request to ${requestUrl.origin}: the http2 session is connected to ${sm.authority}`;
    sentinel.error(new ConnectError(message, Code.Internal));
    return;
  }
  sm.request(method, requestUrl.pathname + requestUrl.search, headers, {}).then((stream) => {
    sentinel.onError((reason) => {
      if (stream.closed) {
        return;
      }
      const rstCode = reason.code == Code.Canceled ? H2Code.CANCEL : H2Code.INTERNAL_ERROR;
      return new Promise((resolve2) => stream.close(rstCode, resolve2));
    });
    stream.on("error", function h2StreamError(e) {
      if (stream.writableEnded && unwrapNodeErrorChain(e).map(getNodeErrorProps).some((p) => p.code == "ERR_STREAM_WRITE_AFTER_END")) {
        return;
      }
      sentinel.error(e);
    });
    stream.on("close", function h2StreamClose() {
      const err = connectErrorFromH2ResetCode(stream.rstCode);
      if (err) {
        sentinel.error(err);
      }
    });
    onStream(stream);
  }, (reason) => {
    sentinel.error(reason);
  });
}
function h2ResponseTrailer(response) {
  const trailer = new Headers();
  response.on("trailers", (args) => {
    nodeHeaderToWebHeader(args).forEach((value, key) => {
      trailer.set(key, value);
    });
  });
  return trailer;
}
function h2ResponseIterable(sentinel, response, sm) {
  const inner = response[Symbol.asyncIterator]();
  return {
    [Symbol.asyncIterator]() {
      return {
        async next() {
          const r = await sentinel.race(inner.next());
          if (r.done === true) {
            sentinel.close();
          }
          sm === null || sm === void 0 ? void 0 : sm.notifyResponseByteRead(response);
          return r;
        },
        throw(e) {
          sentinel.error(e);
          throw e;
        }
      };
    }
  };
}
async function sinkRequest(request3, nodeRequest, sentinel) {
  if (request3.body === void 0) {
    await new Promise((resolve2) => nodeRequest.end(resolve2));
    return;
  }
  const it = request3.body[Symbol.asyncIterator]();
  return new Promise((resolve2) => {
    writeNext();
    function writeNext() {
      if (sentinel.isClosed()) {
        return;
      }
      it.next().then((r) => {
        if (r.done === true) {
          nodeRequest.end(resolve2);
          return;
        }
        nodeRequest.write(r.value, "binary", (e) => {
          if (e === null || e === void 0) {
            writeNext();
            return;
          }
          if (it.throw !== void 0) {
            it.throw(connectErrorFromNodeReason(e)).catch(() => {
            });
          }
          if (nodeRequest.writableEnded && unwrapNodeErrorChain(e).map(getNodeErrorProps).some((p) => p.code == "ERR_STREAM_WRITE_AFTER_END")) {
            return;
          }
          sentinel.error(e);
        });
      }, (e) => {
        sentinel.error(e);
      });
    }
  });
}
function createSentinel(signal) {
  let rejectRace;
  let closed2 = false;
  let closedError = void 0;
  let onErrorListeners = [];
  const sentinel = {
    error(error2) {
      if (closed2) {
        return;
      }
      closed2 = true;
      closedError = error2 instanceof ConnectError ? error2 : connectErrorFromNodeReason(error2);
      rejectRace === null || rejectRace === void 0 ? void 0 : rejectRace(closedError);
      for (const onRejected of onErrorListeners) {
        onRejected(closedError);
      }
      cleanup();
    },
    close() {
      if (closed2) {
        return;
      }
      closed2 = true;
      if (rejectRace) {
        rejectRace(new ConnectError("sentinel completed early", Code.Internal));
      }
      cleanup();
    },
    isClosed() {
      return closed2;
    },
    onError(onError) {
      if (closed2) {
        if (closedError !== void 0) {
          onError(closedError);
        }
      } else {
        onErrorListeners.push(onError);
      }
    },
    race(promise) {
      let resolveRace;
      const race = new Promise((resolve2, reject) => {
        resolveRace = resolve2;
        rejectRace = reject;
      });
      promise.then((value) => {
        resolveRace === null || resolveRace === void 0 ? void 0 : resolveRace(value);
      }, (reason) => {
        rejectRace === null || rejectRace === void 0 ? void 0 : rejectRace(reason);
      });
      if (closed2) {
        rejectRace === null || rejectRace === void 0 ? void 0 : rejectRace(closedError !== null && closedError !== void 0 ? closedError : new ConnectError("sentinel completed early", Code.Internal));
      }
      return race;
    }
  };
  function cleanup() {
    if (signal) {
      signal.removeEventListener("abort", onSignalAbort);
    }
    onErrorListeners = [];
    rejectRace = void 0;
  }
  function onSignalAbort() {
    sentinel.error(getAbortSignalReason(this));
  }
  if (signal) {
    signal.addEventListener("abort", onSignalAbort);
    if (signal.aborted) {
      sentinel.error(getAbortSignalReason(signal));
    }
  }
  return sentinel;
}

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/node-transport-options.js
function validateNodeTransportOptions(options) {
  var _a, _b, _c, _d;
  let httpClient;
  if (options.httpVersion == "2") {
    let sessionManager;
    if (options.sessionManager) {
      sessionManager = options.sessionManager;
    } else {
      sessionManager = new Http2SessionManager(options.baseUrl, {
        pingIntervalMs: options.pingIntervalMs,
        pingIdleConnection: options.pingIdleConnection,
        pingTimeoutMs: options.pingTimeoutMs,
        idleConnectionTimeoutMs: options.idleConnectionTimeoutMs
      }, options.nodeOptions);
    }
    httpClient = createNodeHttpClient({
      httpVersion: "2",
      sessionProvider: () => sessionManager
    });
  } else {
    httpClient = createNodeHttpClient({
      httpVersion: "1.1",
      nodeOptions: options.nodeOptions
    });
  }
  return Object.assign(Object.assign(Object.assign({}, options), { httpClient, useBinaryFormat: (_a = options.useBinaryFormat) !== null && _a !== void 0 ? _a : true, interceptors: (_b = options.interceptors) !== null && _b !== void 0 ? _b : [], sendCompression: (_c = options.sendCompression) !== null && _c !== void 0 ? _c : null, acceptCompression: (_d = options.acceptCompression) !== null && _d !== void 0 ? _d : [
    compressionGzip,
    compressionBrotli
  ] }), validateReadWriteMaxBytes(options.readMaxBytes, options.writeMaxBytes, options.compressMinBytes));
}

// node_modules/.pnpm/@connectrpc+connect-node@2.1.1_@bufbuild+protobuf@2.11.0_@connectrpc+connect@2.1.1_@bufbuild+protobuf@2.11.0_/node_modules/@connectrpc/connect-node/dist/esm/grpc-transport.js
function createGrpcTransport(options) {
  return createTransport(validateNodeTransportOptions(Object.assign(Object.assign({}, options), { httpVersion: "2" })));
}

// node_modules/.pnpm/@pinixai+hub-client@0.2.0_typescript@5.9.3/node_modules/@pinixai/hub-client/src/gen/hub_pb.ts
var file_pinix_v2_hub = /* @__PURE__ */ fileDesc("ChJwaW5peC92Mi9odWIucHJvdG8SCHBpbml4LnYyIikKCEh1YkVycm9yEgwKBGNvZGUYASABKAkSDwoHbWVzc2FnZRgCIAEoCSJPCgtDb21tYW5kSW5mbxIMCgRuYW1lGAEgASgJEhMKC2Rlc2NyaXB0aW9uGAIgASgJEg0KBWlucHV0GAMgASgJEg4KBm91dHB1dBgEIAEoCSKDAgoIQ2xpcEluZm8SDAoEbmFtZRgBIAEoCRIPCgdwYWNrYWdlGAIgASgJEg8KB3ZlcnNpb24YAyABKAkSEAoIcHJvdmlkZXIYBCABKAkSDgoGZG9tYWluGAUgASgJEicKCGNvbW1hbmRzGAYgAygLMhUucGluaXgudjIuQ29tbWFuZEluZm8SDwoHaGFzX3dlYhgHIAEoCBIXCg90b2tlbl9wcm90ZWN0ZWQYCCABKAgSFAoMZGVwZW5kZW5jaWVzGAkgAygJEiQKBnN0YXR1cxgKIAEoDjIULnBpbml4LnYyLkNsaXBTdGF0dXMSFgoOc3RhdHVzX21lc3NhZ2UYCyABKAkiMgoORGVwZW5kZW5jeVNsb3QSDwoHcGFja2FnZRgBIAEoCRIPCgd2ZXJzaW9uGAIgASgJIlAKC0NsaXBCaW5kaW5nEg0KBWFsaWFzGAEgASgJEgsKA2h1YhgCIAEoCRIRCglodWJfdG9rZW4YAyABKAkSEgoKY2xpcF90b2tlbhgEIAEoCSLHAwoMQ2xpcE1hbmlmZXN0EgwKBG5hbWUYASABKAkSDwoHcGFja2FnZRgCIAEoCRIPCgd2ZXJzaW9uGAMgASgJEg4KBmRvbWFpbhgEIAEoCRITCgtkZXNjcmlwdGlvbhgFIAEoCRInCghjb21tYW5kcxgGIAMoCzIVLnBpbml4LnYyLkNvbW1hbmRJbmZvEhQKDGRlcGVuZGVuY2llcxgHIAMoCRIPCgdoYXNfd2ViGAggASgIEhAKCHBhdHRlcm5zGAkgAygJEjYKCGVudGl0aWVzGAogAygLMiQucGluaXgudjIuQ2xpcE1hbmlmZXN0LkVudGl0aWVzRW50cnkSRQoQZGVwZW5kZW5jeV9zbG90cxgLIAMoCzIrLnBpbml4LnYyLkNsaXBNYW5pZmVzdC5EZXBlbmRlbmN5U2xvdHNFbnRyeRovCg1FbnRpdGllc0VudHJ5EgsKA2tleRgBIAEoCRINCgV2YWx1ZRgCIAEoCToCOAEaUAoURGVwZW5kZW5jeVNsb3RzRW50cnkSCwoDa2V5GAEgASgJEicKBXZhbHVlGAIgASgLMhgucGluaXgudjIuRGVwZW5kZW5jeVNsb3Q6AjgBIlkKDFByb3ZpZGVySW5mbxIMCgRuYW1lGAEgASgJEhYKDmFjY2VwdHNfbWFuYWdlGAIgASgIEg0KBWNsaXBzGAMgAygJEhQKDGNvbm5lY3RlZF9hdBgEIAEoAyJYChFDbGlwU3RhdHVzQ2hhbmdlZBIMCgRuYW1lGAEgASgJEiQKBnN0YXR1cxgCIAEoDjIULnBpbml4LnYyLkNsaXBTdGF0dXMSDwoHbWVzc2FnZRgDIAEoCSKfAwoPUHJvdmlkZXJNZXNzYWdlEi0KCHJlZ2lzdGVyGAEgASgLMhkucGluaXgudjIuUmVnaXN0ZXJSZXF1ZXN0SAASKQoKY2xpcF9hZGRlZBgCIAEoCzITLnBpbml4LnYyLkNsaXBBZGRlZEgAEi0KDGNsaXBfcmVtb3ZlZBgDIAEoCzIVLnBpbml4LnYyLkNsaXBSZW1vdmVkSAASLwoNaW52b2tlX3Jlc3VsdBgEIAEoCzIWLnBpbml4LnYyLkludm9rZVJlc3VsdEgAEiMKBHBpbmcYBSABKAsyEy5waW5peC52Mi5IZWFydGJlYXRIABI5ChNnZXRfY2xpcF93ZWJfcmVzdWx0GAcgASgLMhoucGluaXgudjIuR2V0Q2xpcFdlYlJlc3VsdEgAEjoKE2NsaXBfc3RhdHVzX2NoYW5nZWQYCCABKAsyGy5waW5peC52Mi5DbGlwU3RhdHVzQ2hhbmdlZEgAEisKC2RhdGFfcmVzdWx0GAkgASgLMhQucGluaXgudjIuRGF0YVJlc3VsdEgAQgkKB3BheWxvYWQiwwIKCkh1Yk1lc3NhZ2USNwoRcmVnaXN0ZXJfcmVzcG9uc2UYASABKAsyGi5waW5peC52Mi5SZWdpc3RlclJlc3BvbnNlSAASMQoOaW52b2tlX2NvbW1hbmQYAiABKAsyFy5waW5peC52Mi5JbnZva2VDb21tYW5kSAASLQoMaW52b2tlX2lucHV0GAMgASgLMhUucGluaXgudjIuSW52b2tlSW5wdXRIABIjCgRwb25nGAUgASgLMhMucGluaXgudjIuSGVhcnRiZWF0SAASOwoUZ2V0X2NsaXBfd2ViX2NvbW1hbmQYBiABKAsyGy5waW5peC52Mi5HZXRDbGlwV2ViQ29tbWFuZEgAEi0KDGRhdGFfY29tbWFuZBgHIAEoCzIVLnBpbml4LnYyLkRhdGFDb21tYW5kSABCCQoHcGF5bG9hZCLTAQoOUnVudGltZU1lc3NhZ2USLQoIcmVnaXN0ZXIYASABKAsyGS5waW5peC52Mi5SdW50aW1lUmVnaXN0ZXJIABIxCg5pbnN0YWxsX3Jlc3VsdBgCIAEoCzIXLnBpbml4LnYyLkluc3RhbGxSZXN1bHRIABIvCg1yZW1vdmVfcmVzdWx0GAMgASgLMhYucGluaXgudjIuUmVtb3ZlUmVzdWx0SAASIwoEcGluZxgEIAEoCzITLnBpbml4LnYyLkhlYXJ0YmVhdEgAQgkKB3BheWxvYWQi6wEKEUh1YlJ1bnRpbWVNZXNzYWdlEj4KEXJlZ2lzdGVyX3Jlc3BvbnNlGAEgASgLMiEucGluaXgudjIuUnVudGltZVJlZ2lzdGVyUmVzcG9uc2VIABIzCg9pbnN0YWxsX2NvbW1hbmQYAiABKAsyGC5waW5peC52Mi5JbnN0YWxsQ29tbWFuZEgAEjEKDnJlbW92ZV9jb21tYW5kGAMgASgLMhcucGluaXgudjIuUmVtb3ZlQ29tbWFuZEgAEiMKBHBvbmcYBCABKAsyEy5waW5peC52Mi5IZWFydGJlYXRIAEIJCgdwYXlsb2FkIlMKD1JlZ2lzdGVyUmVxdWVzdBIVCg1wcm92aWRlcl9uYW1lGAEgASgJEikKBWNsaXBzGAMgAygLMhoucGluaXgudjIuQ2xpcFJlZ2lzdHJhdGlvbiLNAgoQQ2xpcFJlZ2lzdHJhdGlvbhINCgVhbGlhcxgBIAEoCRIPCgdwYWNrYWdlGAIgASgJEg8KB3ZlcnNpb24YAyABKAkSDgoGZG9tYWluGAQgASgJEicKCGNvbW1hbmRzGAUgAygLMhUucGluaXgudjIuQ29tbWFuZEluZm8SDwoHaGFzX3dlYhgGIAEoCBIUCgxkZXBlbmRlbmNpZXMYByADKAkSFwoPdG9rZW5fcHJvdGVjdGVkGAggASgIEhAKBG5hbWUYCSABKAlCAhgBEhAKCHBhdHRlcm5zGAogAygJEjoKCGVudGl0aWVzGAsgAygLMigucGluaXgudjIuQ2xpcFJlZ2lzdHJhdGlvbi5FbnRpdGllc0VudHJ5Gi8KDUVudGl0aWVzRW50cnkSCwoDa2V5GAEgASgJEg0KBXZhbHVlGAIgASgJOgI4ASJJCglDbGlwQWRkZWQSKAoEY2xpcBgBIAEoCzIaLnBpbml4LnYyLkNsaXBSZWdpc3RyYXRpb24SEgoKcmVxdWVzdF9pZBgCIAEoCSIvCgtDbGlwUmVtb3ZlZBIMCgRuYW1lGAEgASgJEhIKCnJlcXVlc3RfaWQYAiABKAkiYwoMSW52b2tlUmVzdWx0EhIKCnJlcXVlc3RfaWQYASABKAkSDgoGb3V0cHV0GAIgASgMEiEKBWVycm9yGAMgASgLMhIucGluaXgudjIuSHViRXJyb3ISDAoEZG9uZRgEIAEoCCJ/ChFHZXRDbGlwV2ViQ29tbWFuZBISCgpyZXF1ZXN0X2lkGAEgASgJEhEKCWNsaXBfbmFtZRgCIAEoCRIMCgRwYXRoGAMgASgJEg4KBm9mZnNldBgEIAEoAxIOCgZsZW5ndGgYBSABKAMSFQoNaWZfbm9uZV9tYXRjaBgGIAEoCSKoAQoQR2V0Q2xpcFdlYlJlc3VsdBISCgpyZXF1ZXN0X2lkGAEgASgJEg8KB2NvbnRlbnQYAiABKAwSFAoMY29udGVudF90eXBlGAMgASgJEgwKBGV0YWcYBCABKAkSEgoKdG90YWxfc2l6ZRgFIAEoAxIUCgxub3RfbW9kaWZpZWQYBiABKAgSIQoFZXJyb3IYByABKAsyEi5waW5peC52Mi5IdWJFcnJvciI1ChBSZWdpc3RlclJlc3BvbnNlEhAKCGFjY2VwdGVkGAEgASgIEg8KB21lc3NhZ2UYAiABKAkiZwoPUnVudGltZVJlZ2lzdGVyEgwKBG5hbWUYASABKAkSEAoIaG9zdG5hbWUYAiABKAkSCgoCb3MYAyABKAkSDAoEYXJjaBgEIAEoCRIaChJzdXBwb3J0ZWRfcnVudGltZXMYBSADKAkiPAoXUnVudGltZVJlZ2lzdGVyUmVzcG9uc2USEAoIYWNjZXB0ZWQYASABKAgSDwoHbWVzc2FnZRgCIAEoCSJqCg1JbnZva2VDb21tYW5kEhIKCnJlcXVlc3RfaWQYASABKAkSEQoJY2xpcF9uYW1lGAIgASgJEg8KB2NvbW1hbmQYAyABKAkSDQoFaW5wdXQYBCABKAwSEgoKY2xpcF90b2tlbhgFIAEoCSI9CgtJbnZva2VJbnB1dBISCgpyZXF1ZXN0X2lkGAEgASgJEgwKBGRhdGEYAiABKAwSDAoEZG9uZRgDIAEoCCJXCg5JbnN0YWxsQ29tbWFuZBISCgpyZXF1ZXN0X2lkGAEgASgJEg4KBnNvdXJjZRgCIAEoCRINCgVhbGlhcxgDIAEoCRISCgpjbGlwX3Rva2VuGAQgASgJImgKDUluc3RhbGxSZXN1bHQSEgoKcmVxdWVzdF9pZBgBIAEoCRIhCgVlcnJvchgCIAEoCzISLnBpbml4LnYyLkh1YkVycm9yEiAKBGNsaXAYAyABKAsyEi5waW5peC52Mi5DbGlwSW5mbyIyCg1SZW1vdmVDb21tYW5kEhIKCnJlcXVlc3RfaWQYASABKAkSDQoFYWxpYXMYAiABKAkiRQoMUmVtb3ZlUmVzdWx0EhIKCnJlcXVlc3RfaWQYASABKAkSIQoFZXJyb3IYAiABKAsyEi5waW5peC52Mi5IdWJFcnJvciIkCglIZWFydGJlYXQSFwoPc2VudF9hdF91bml4X21zGAEgASgDIhIKEExpc3RDbGlwc1JlcXVlc3QiNgoRTGlzdENsaXBzUmVzcG9uc2USIQoFY2xpcHMYASADKAsyEi5waW5peC52Mi5DbGlwSW5mbyIWChRMaXN0UHJvdmlkZXJzUmVxdWVzdCJCChVMaXN0UHJvdmlkZXJzUmVzcG9uc2USKQoJcHJvdmlkZXJzGAEgAygLMhYucGluaXgudjIuUHJvdmlkZXJJbmZvIicKEkdldE1hbmlmZXN0UmVxdWVzdBIRCgljbGlwX25hbWUYASABKAkiPwoTR2V0TWFuaWZlc3RSZXNwb25zZRIoCghtYW5pZmVzdBgBIAEoCzIWLnBpbml4LnYyLkNsaXBNYW5pZmVzdCJrChFHZXRDbGlwV2ViUmVxdWVzdBIRCgljbGlwX25hbWUYASABKAkSDAoEcGF0aBgCIAEoCRIVCg1pZl9ub25lX21hdGNoGAMgASgJEg4KBm9mZnNldBgEIAEoAxIOCgZsZW5ndGgYBSABKAMicwoSR2V0Q2xpcFdlYlJlc3BvbnNlEg8KB2NvbnRlbnQYASABKAwSFAoMY29udGVudF90eXBlGAIgASgJEgwKBGV0YWcYAyABKAkSFAoMbm90X21vZGlmaWVkGAQgASgIEhIKCnRvdGFsX3NpemUYBSABKAMiVgoNSW52b2tlUmVxdWVzdBIRCgljbGlwX25hbWUYASABKAkSDwoHY29tbWFuZBgCIAEoCRINCgVpbnB1dBgDIAEoDBISCgpjbGlwX3Rva2VuGAQgASgJIkMKDkludm9rZVJlc3BvbnNlEg4KBm91dHB1dBgBIAEoDBIhCgVlcnJvchgCIAEoCzISLnBpbml4LnYyLkh1YkVycm9yInEKE0ludm9rZVN0cmVhbU1lc3NhZ2USKAoFc3RhcnQYASABKAsyFy5waW5peC52Mi5JbnZva2VSZXF1ZXN0SAASJQoFY2h1bmsYAiABKAsyFC5waW5peC52Mi5JbnB1dENodW5rSABCCQoHcGF5bG9hZCIoCgpJbnB1dENodW5rEgwKBGRhdGEYASABKAwSDAoEZG9uZRgCIAEoCCJtCg5BZGRDbGlwUmVxdWVzdBIOCgZzb3VyY2UYASABKAkSDAoEbmFtZRgCIAEoCRIQCghwcm92aWRlchgDIAEoCRISCgpjbGlwX3Rva2VuGAQgASgJEhcKD3JlcXVlc3RlZF9hbGlhcxgFIAEoCSIzCg9BZGRDbGlwUmVzcG9uc2USIAoEY2xpcBgBIAEoCzISLnBpbml4LnYyLkNsaXBJbmZvIjUKEVJlbW92ZUNsaXBSZXF1ZXN0EhEKCWNsaXBfbmFtZRgBIAEoCRINCgVwdXJnZRgCIAEoCCInChJSZW1vdmVDbGlwUmVzcG9uc2USEQoJY2xpcF9uYW1lGAEgASgJIicKEkdldEJpbmRpbmdzUmVxdWVzdBIRCgljbGlwX25hbWUYASABKAkivAIKE0dldEJpbmRpbmdzUmVzcG9uc2USPQoIYmluZGluZ3MYASADKAsyKy5waW5peC52Mi5HZXRCaW5kaW5nc1Jlc3BvbnNlLkJpbmRpbmdzRW50cnkSTAoQZGVwZW5kZW5jeV9zbG90cxgCIAMoCzIyLnBpbml4LnYyLkdldEJpbmRpbmdzUmVzcG9uc2UuRGVwZW5kZW5jeVNsb3RzRW50cnkaRgoNQmluZGluZ3NFbnRyeRILCgNrZXkYASABKAkSJAoFdmFsdWUYAiABKAsyFS5waW5peC52Mi5DbGlwQmluZGluZzoCOAEaUAoURGVwZW5kZW5jeVNsb3RzRW50cnkSCwoDa2V5GAEgASgJEicKBXZhbHVlGAIgASgLMhgucGluaXgudjIuRGVwZW5kZW5jeVNsb3Q6AjgBIlwKEVNldEJpbmRpbmdSZXF1ZXN0EhEKCWNsaXBfbmFtZRgBIAEoCRIMCgRzbG90GAIgASgJEiYKB2JpbmRpbmcYAyABKAsyFS5waW5peC52Mi5DbGlwQmluZGluZyIUChJTZXRCaW5kaW5nUmVzcG9uc2UiNwoUUmVtb3ZlQmluZGluZ1JlcXVlc3QSEQoJY2xpcF9uYW1lGAEgASgJEgwKBHNsb3QYAiABKAkiFwoVUmVtb3ZlQmluZGluZ1Jlc3BvbnNlInQKC0RhdGFSZXF1ZXN0EhEKCWNsaXBfbmFtZRgBIAEoCRIRCglvcGVyYXRpb24YAiABKAkSDAoEcGF0aBgDIAEoCRIPCgdjb250ZW50GAQgASgMEgwKBG1pbWUYBSABKAkSEgoKY2xpcF90b2tlbhgGIAEoCSKXAQoMRGF0YVJlc3BvbnNlEg8KB2NvbnRlbnQYASABKAwSCwoDdXJpGAIgASgJEiQKB2VudHJpZXMYAyADKAsyEy5waW5peC52Mi5EYXRhRW50cnkSIAoEc3RhdBgEIAEoCzISLnBpbml4LnYyLkRhdGFTdGF0EiEKBWVycm9yGAUgASgLMhIucGluaXgudjIuSHViRXJyb3IiUQoJRGF0YUVudHJ5EgwKBG5hbWUYASABKAkSDAoEcGF0aBgCIAEoCRIMCgR0eXBlGAMgASgJEgwKBHNpemUYBCABKAMSDAoEbWltZRgFIAEoCSI4CghEYXRhU3RhdBIMCgRzaXplGAEgASgDEgwKBG1pbWUYAiABKAkSEAoIbW9kaWZpZWQYAyABKAkidAoLRGF0YUNvbW1hbmQSEgoKcmVxdWVzdF9pZBgBIAEoCRIRCgljbGlwX25hbWUYAiABKAkSEQoJb3BlcmF0aW9uGAMgASgJEgwKBHBhdGgYBCABKAkSDwoHY29udGVudBgFIAEoDBIMCgRtaW1lGAYgASgJIqkBCgpEYXRhUmVzdWx0EhIKCnJlcXVlc3RfaWQYASABKAkSDwoHY29udGVudBgCIAEoDBILCgN1cmkYAyABKAkSJAoHZW50cmllcxgEIAMoCzITLnBpbml4LnYyLkRhdGFFbnRyeRIgCgRzdGF0GAUgASgLMhIucGluaXgudjIuRGF0YVN0YXQSIQoFZXJyb3IYBiABKAsyEi5waW5peC52Mi5IdWJFcnJvcipzCgpDbGlwU3RhdHVzEhsKF0NMSVBfU1RBVFVTX1VOU1BFQ0lGSUVEEAASFwoTQ0xJUF9TVEFUVVNfUlVOTklORxABEhgKFENMSVBfU1RBVFVTX1NMRUVQSU5HEAISFQoRQ0xJUF9TVEFUVVNfRVJST1IQAzL/BwoKSHViU2VydmljZRJFCg5Qcm92aWRlclN0cmVhbRIZLnBpbml4LnYyLlByb3ZpZGVyTWVzc2FnZRoULnBpbml4LnYyLkh1Yk1lc3NhZ2UoATABEkoKDVJ1bnRpbWVTdHJlYW0SGC5waW5peC52Mi5SdW50aW1lTWVzc2FnZRobLnBpbml4LnYyLkh1YlJ1bnRpbWVNZXNzYWdlKAEwARJECglMaXN0Q2xpcHMSGi5waW5peC52Mi5MaXN0Q2xpcHNSZXF1ZXN0GhsucGluaXgudjIuTGlzdENsaXBzUmVzcG9uc2USUAoNTGlzdFByb3ZpZGVycxIeLnBpbml4LnYyLkxpc3RQcm92aWRlcnNSZXF1ZXN0Gh8ucGluaXgudjIuTGlzdFByb3ZpZGVyc1Jlc3BvbnNlEkoKC0dldE1hbmlmZXN0EhwucGluaXgudjIuR2V0TWFuaWZlc3RSZXF1ZXN0Gh0ucGluaXgudjIuR2V0TWFuaWZlc3RSZXNwb25zZRJHCgpHZXRDbGlwV2ViEhsucGluaXgudjIuR2V0Q2xpcFdlYlJlcXVlc3QaHC5waW5peC52Mi5HZXRDbGlwV2ViUmVzcG9uc2USPQoGSW52b2tlEhcucGluaXgudjIuSW52b2tlUmVxdWVzdBoYLnBpbml4LnYyLkludm9rZVJlc3BvbnNlMAESSwoMSW52b2tlU3RyZWFtEh0ucGluaXgudjIuSW52b2tlU3RyZWFtTWVzc2FnZRoYLnBpbml4LnYyLkludm9rZVJlc3BvbnNlKAEwARI1CgREYXRhEhUucGluaXgudjIuRGF0YVJlcXVlc3QaFi5waW5peC52Mi5EYXRhUmVzcG9uc2USPgoHQWRkQ2xpcBIYLnBpbml4LnYyLkFkZENsaXBSZXF1ZXN0GhkucGluaXgudjIuQWRkQ2xpcFJlc3BvbnNlEkcKClJlbW92ZUNsaXASGy5waW5peC52Mi5SZW1vdmVDbGlwUmVxdWVzdBocLnBpbml4LnYyLlJlbW92ZUNsaXBSZXNwb25zZRJKCgtHZXRCaW5kaW5ncxIcLnBpbml4LnYyLkdldEJpbmRpbmdzUmVxdWVzdBodLnBpbml4LnYyLkdldEJpbmRpbmdzUmVzcG9uc2USRwoKU2V0QmluZGluZxIbLnBpbml4LnYyLlNldEJpbmRpbmdSZXF1ZXN0GhwucGluaXgudjIuU2V0QmluZGluZ1Jlc3BvbnNlElAKDVJlbW92ZUJpbmRpbmcSHi5waW5peC52Mi5SZW1vdmVCaW5kaW5nUmVxdWVzdBofLnBpbml4LnYyLlJlbW92ZUJpbmRpbmdSZXNwb25zZUIxWi9naXRodWIuY29tL2VwaXJhbC9waW5peC9nZW4vZ28vcGluaXgvdjI7cGluaXh2MmIGcHJvdG8z");
var HubErrorSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 0);
var ProviderMessageSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 8);
var RegisterRequestSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 12);
var ClipRegistrationSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 13);
var InvokeResultSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 16);
var GetClipWebResultSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 18);
var HeartbeatSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 28);
var DataEntrySchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 53);
var DataStatSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 54);
var DataResultSchema = /* @__PURE__ */ messageDesc(file_pinix_v2_hub, 56);
var HubService = /* @__PURE__ */ serviceDesc(file_pinix_v2_hub, 0);

// node_modules/.pnpm/@pinixai+hub-client@0.2.0_typescript@5.9.3/node_modules/@pinixai/hub-client/src/helpers.ts
var encoder = new TextEncoder();
var decoder = new TextDecoder();

// packages/daemon/src/hub-bridge.ts
var LOG_PREFIX = "[hub-bridge]";
var PROVIDER_NAME = "bb-browser";
var BROWSER_CLIP_ALIAS = "browser";
var BROWSER_CLIP_PACKAGE = "browser";
var BROWSER_CLIP_DOMAIN = "\u6D4F\u89C8\u5668";
var RECONNECT_DELAY_MS = 5e3;
var REGISTER_TIMEOUT_MS = 1e4;
var HEARTBEAT_INTERVAL_MS = 15e3;
var STREAMER_PORT = "3334";
var STREAMER_API_BASE = `http://127.0.0.1:${STREAMER_PORT}`;
var PINIX_DATA_ROOT = join2(process.env.PINIX_HOME || join2(homedir2(), ".pinix"), "data");
var textEncoder = new TextEncoder();
var textDecoder = new TextDecoder();
function readPackageVersion() {
  try {
    const currentDir = dirname(fileURLToPath2(import.meta.url));
    const candidates = [
      resolve(currentDir, "../../../package.json"),
      // dev: packages/daemon/src/
      resolve(currentDir, "../../package.json"),
      // built: packages/daemon/dist/
      resolve(currentDir, "../package.json")
      // release bundle: dist/
    ];
    for (const p of candidates) {
      try {
        const pkg = JSON.parse(readFileSync3(p, "utf-8"));
        if (pkg.version) return pkg.version.trim();
      } catch {
      }
    }
    return "0.0.0";
  } catch {
    return "0.0.0";
  }
}
var CLIP_VERSION = readPackageVersion();
var streamerProcess = null;
var activeHubUrl = null;
async function fetchTurnCredentials() {
  if (activeHubUrl) {
    try {
      const hubBase = activeHubUrl.replace(/\/$/, "");
      const resp = await fetch(`${hubBase}/turn/credentials`, { signal: AbortSignal.timeout(5e3) });
      if (resp.ok) {
        const data = await resp.json();
        if (data.url && data.username && data.password) return data;
      }
    } catch {
    }
  }
  const turnUrl = process.env.TURN_URL;
  const turnSecret = process.env.TURN_SECRET;
  if (turnUrl && turnSecret) {
    const { username, password } = generateTurnCredentials(turnSecret);
    return { url: turnUrl, username, password };
  }
  return null;
}
var BB_VIEWER_COS_BASE = "https://pinix-blobs-1251447449.cos.ap-beijing.myqcloud.com/releases/bb-viewer/latest";
function viewerPlatformKey() {
  const p = platform();
  const a = arch();
  if (p === "darwin" && a === "arm64") return "darwin-arm64";
  if (p === "darwin" && a === "x64") return "darwin-x64";
  if (p === "linux" && a === "x64") return "linux-amd64";
  return null;
}
async function downloadStreamerBinary(destPath) {
  const key = viewerPlatformKey();
  if (!key) throw new Error(`No pre-built bb-viewer for ${platform()}/${arch()}`);
  const url = `${BB_VIEWER_COS_BASE}/bb-viewer-${key}`;
  console.error(`${LOG_PREFIX} Downloading bb-viewer from ${url}...`);
  const resp = await fetch(url, { signal: AbortSignal.timeout(6e4) });
  if (!resp.ok || !resp.body) throw new Error(`Failed to download bb-viewer: ${resp.status}`);
  mkdirSync2(dirname(destPath), { recursive: true });
  const tmpPath = destPath + ".tmp";
  await pipeline(resp.body, createWriteStream(tmpPath));
  const { renameSync: renameSync2 } = await import("fs");
  renameSync2(tmpPath, destPath);
  chmodSync(destPath, 493);
  console.error(`${LOG_PREFIX} bb-viewer installed at ${destPath}`);
}
async function ensureStreamerBinary() {
  const localPath = join2(DAEMON_DIR, "bin", "bb-viewer");
  if (existsSync2(localPath)) return localPath;
  try {
    const { execSync: execSync2 } = await import("child_process");
    const which = execSync2("which bb-viewer 2>/dev/null", { encoding: "utf8", timeout: 3e3 }).trim();
    if (which && existsSync2(which)) return which;
  } catch {
  }
  await downloadStreamerBinary(localPath);
  return localPath;
}
function generateTurnCredentials(secret, ttlSeconds = 86400) {
  const expiry = Math.floor(Date.now() / 1e3) + ttlSeconds;
  const username = `${expiry}:bbviewer`;
  const password = createHmac("sha1", secret).update(username).digest("base64");
  return { username, password };
}
async function ensureStreamer() {
  if (streamerProcess && !streamerProcess.killed) {
    try {
      const resp = await fetch(`${STREAMER_API_BASE}/health`, { signal: AbortSignal.timeout(2e3) });
      if (resp.ok) return;
    } catch {
    }
    try {
      streamerProcess.kill();
    } catch {
    }
    streamerProcess = null;
  }
  const bin = await ensureStreamerBinary();
  const args = ["--api-only", "--port", STREAMER_PORT];
  const turnCreds = await fetchTurnCredentials();
  if (turnCreds) {
    args.push("--turn-url", turnCreds.url, "--turn-user", turnCreds.username, "--turn-cred", turnCreds.password);
  }
  console.error(`${LOG_PREFIX} Spawning streamer: ${bin} ${args.join(" ")}`);
  const child = spawn(bin, args, { stdio: ["ignore", "pipe", "pipe"] });
  streamerProcess = child;
  child.on("error", (err) => {
    console.error(`${LOG_PREFIX} [streamer] spawn error: ${err.message}`);
    if (streamerProcess === child) streamerProcess = null;
  });
  child.stdout?.on("data", (d) => {
    for (const line of d.toString().trim().split("\n")) console.error(`${LOG_PREFIX} [streamer] ${line}`);
  });
  child.stderr?.on("data", (d) => {
    for (const line of d.toString().trim().split("\n")) console.error(`${LOG_PREFIX} [streamer] ${line}`);
  });
  child.on("exit", (code) => {
    console.error(`${LOG_PREFIX} [streamer] exited with code ${code}`);
    if (streamerProcess === child) streamerProcess = null;
  });
  const deadline = Date.now() + 1e4;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 300));
    try {
      const resp = await fetch(`${STREAMER_API_BASE}/health`, { signal: AbortSignal.timeout(2e3) });
      if (resp.ok) {
        console.error(`${LOG_PREFIX} Streamer ready at port ${STREAMER_PORT}`);
        return;
      }
    } catch {
    }
  }
  throw new Error("Streamer did not become healthy in 10s");
}
async function streamerCommand(path4, body) {
  const url = `${STREAMER_API_BASE}${path4}`;
  const opts = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    signal: AbortSignal.timeout(15e3)
  };
  const resp = await fetch(url, opts);
  const text = await resp.text();
  if (!resp.ok) throw new Error(`Streamer ${path4} failed (${resp.status}): ${text}`);
  try {
    return JSON.parse(text);
  } catch {
    return { output: text };
  }
}
function stopStreamer() {
  if (streamerProcess && !streamerProcess.killed) {
    console.error(`${LOG_PREFIX} Stopping streamer`);
    try {
      streamerProcess.kill();
    } catch {
    }
    streamerProcess = null;
  }
}
var BROWSER_COMMANDS = COMMANDS.filter((c) => c.group !== "site");
var STREAM_COMMANDS = [
  {
    name: "stream.start",
    description: "Start remote viewing: creates a WebRTC peer and returns offer SDP + ICE candidates",
    inputSchema: JSON.stringify({ type: "object", properties: {}, additionalProperties: true })
  },
  {
    name: "stream.answer",
    description: "Complete WebRTC connection: accepts answer SDP + ICE candidates, starts video streaming",
    inputSchema: JSON.stringify({
      type: "object",
      properties: {
        answer_sdp: { type: "string", description: "Answer SDP from the remote peer" },
        candidates: {
          type: "array",
          items: {
            type: "object",
            properties: { candidate: { type: "string" }, sdpMLineIndex: { type: "number" } },
            required: ["candidate", "sdpMLineIndex"]
          },
          description: "ICE candidates from the remote peer"
        }
      },
      required: ["answer_sdp"],
      additionalProperties: true
    })
  },
  {
    name: "stream.close",
    description: "Stop remote viewing and close the WebRTC peer",
    inputSchema: JSON.stringify({ type: "object", properties: {}, additionalProperties: true })
  },
  {
    name: "stream.switch",
    description: "Switch the streaming tab: tell the streamer to connect to a different tab's CDP WebSocket",
    inputSchema: JSON.stringify({
      type: "object",
      properties: {
        tab: { type: "string", description: "Short tab ID to switch streaming to" }
      },
      required: ["tab"],
      additionalProperties: true
    })
  }
];
var BROWSER_COMMAND_NAMES = [
  ...BROWSER_COMMANDS.map((c) => c.method),
  "stream.start",
  "stream.answer",
  "stream.close",
  "stream.switch"
];
function buildClipRegistrations() {
  const browserCommands = [
    ...BROWSER_COMMANDS.map((cmd) => ({
      name: cmd.method,
      description: cmd.description,
      input: commandToJsonSchema(cmd),
      output: JSON.stringify({ type: "object", additionalProperties: true })
    })),
    ...STREAM_COMMANDS.map((cmd) => ({
      name: cmd.name,
      description: cmd.description,
      input: cmd.inputSchema,
      output: JSON.stringify({ type: "object", additionalProperties: true })
    }))
  ];
  const browserClip = create(ClipRegistrationSchema, {
    alias: BROWSER_CLIP_ALIAS,
    package: BROWSER_CLIP_PACKAGE,
    version: CLIP_VERSION,
    domain: BROWSER_CLIP_DOMAIN,
    commands: browserCommands,
    hasWeb: true,
    dependencies: [],
    tokenProtected: false
  });
  return { browserClip };
}
function decodeInput(data) {
  if (!data || data.length === 0) return {};
  let raw = textDecoder.decode(data).trim();
  if (!raw) return {};
  raw = raw.replace(
    /"(?:[^"\\]|\\.)*"|\d{16,}/g,
    (m) => m.startsWith('"') ? m : `"${m}"`
  );
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("Invoke input must be valid JSON");
  }
}
function encodeOutput(value) {
  return textEncoder.encode(JSON.stringify(value ?? {}));
}
function clipDataDir(clipName) {
  return join2(PINIX_DATA_ROOT, clipName);
}
function validateDataPath(p) {
  if (!p && p !== "") return;
  if (p.startsWith("/") || p.startsWith("\\")) throw new Error("Absolute paths not allowed");
  const cleaned = p.replace(/\\/g, "/").split("/").filter((s) => s !== ".");
  if (cleaned.some((s) => s === "..")) throw new Error(`Path "${p}" escapes data directory`);
}
function guessMime(name) {
  const ext = extname(name).toLowerCase();
  const map = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".txt": "text/plain",
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav"
  };
  return map[ext] || "application/octet-stream";
}
async function handleDataCommand(cmd) {
  const clipName = cmd.clipName?.trim() || "";
  const operation = cmd.operation?.trim().toLowerCase() || "";
  const dataPath = cmd.path?.trim() || "";
  if (!clipName) throw new Error("clip_name is required");
  if (!operation) throw new Error("operation is required");
  if (operation !== "list" && !dataPath) throw new Error("path is required");
  validateDataPath(dataPath);
  const dataDir = clipDataDir(clipName);
  const fullPath = dataPath ? join2(dataDir, dataPath) : dataDir;
  switch (operation) {
    case "read": {
      const content = await readFileAsync(fullPath);
      return textEncoder.encode(JSON.stringify({ content: Buffer.from(content).toString("base64") }));
    }
    case "write": {
      mkdirSync2(dirname(fullPath), { recursive: true });
      writeFileSync2(fullPath, cmd.content);
      const uri = `pinix://${clipName}/${dataPath}`;
      return textEncoder.encode(JSON.stringify({ uri }));
    }
    case "list": {
      mkdirSync2(fullPath, { recursive: true });
      const entries = readdirSyncNative(fullPath, { withFileTypes: true }).map((e) => {
        const entryPath = dataPath ? `${dataPath}/${e.name}` : e.name;
        let size = 0;
        try {
          size = statSync(join2(fullPath, e.name)).size;
        } catch {
        }
        return {
          name: e.name,
          path: `pinix://${clipName}/${entryPath}`,
          type: e.isDirectory() ? "directory" : "file",
          size,
          mime: e.isDirectory() ? "" : guessMime(e.name)
        };
      });
      return textEncoder.encode(JSON.stringify({ entries }));
    }
    case "delete": {
      unlinkSync(fullPath);
      return textEncoder.encode(JSON.stringify({ uri: `pinix://${clipName}/${dataPath}` }));
    }
    case "stat": {
      const info = statSync(fullPath);
      return textEncoder.encode(JSON.stringify({
        stat: { size: info.size, mime: guessMime(dataPath), modified: info.mtime.toISOString() }
      }));
    }
    default:
      throw new Error(`Unsupported data operation: ${operation}`);
  }
}
var AsyncMessageQueue = class {
  values = [];
  waiters = [];
  closed = false;
  failed = null;
  push(value) {
    if (this.closed) throw new Error("queue is closed");
    if (this.failed) throw this.failed;
    const w = this.waiters.shift();
    if (w) {
      w.resolve({ done: false, value });
      return;
    }
    this.values.push(value);
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    while (this.waiters.length) this.waiters.shift().resolve({ done: true, value: void 0 });
  }
  fail(error2) {
    if (this.failed) return;
    this.failed = error2 instanceof Error ? error2 : new Error(String(error2));
    while (this.waiters.length) this.waiters.shift().reject(this.failed);
  }
  next() {
    if (this.values.length) return Promise.resolve({ done: false, value: this.values.shift() });
    if (this.failed) return Promise.reject(this.failed);
    if (this.closed) return Promise.resolve({ done: true, value: void 0 });
    return new Promise((resolve2, reject) => {
      this.waiters.push({ resolve: resolve2, reject });
    });
  }
  return() {
    this.close();
    return Promise.resolve({ done: true, value: void 0 });
  }
  throw(e) {
    this.fail(e ?? new Error("aborted"));
    return Promise.reject(this.failed);
  }
  [Symbol.asyncIterator]() {
    return this;
  }
};
var HubBridge = class {
  abortController = null;
  reconnectTimer = null;
  stopped = false;
  hubUrl;
  hubToken;
  cdp;
  constructor(options) {
    this.hubUrl = options.hubUrl;
    this.hubToken = options.hubToken;
    this.cdp = options.cdp;
    activeHubUrl = options.hubUrl;
  }
  start() {
    this.connect();
  }
  stop() {
    this.stopped = true;
    this.clearReconnect();
    this.abortController?.abort();
    stopStreamer();
  }
  connect() {
    if (this.stopped) return;
    this.runStream().catch((err) => {
      if (this.stopped) return;
      console.error(`${LOG_PREFIX} Stream error: ${err instanceof Error ? err.message : err}`);
      this.scheduleReconnect();
    });
  }
  async runStream() {
    console.error(`${LOG_PREFIX} Connecting to ${this.hubUrl}`);
    const transport = createGrpcTransport({ baseUrl: this.hubUrl, httpVersion: "2" });
    const client = createClient(HubService, transport);
    const ac = new AbortController();
    this.abortController = ac;
    const queue = new AsyncMessageQueue();
    const heartbeat = setInterval(() => {
      if (ac.signal.aborted) return;
      try {
        queue.push(create(ProviderMessageSchema, {
          payload: { case: "ping", value: create(HeartbeatSchema, { sentAtUnixMs: BigInt(Date.now()) }) }
        }));
      } catch {
      }
    }, HEARTBEAT_INTERVAL_MS);
    let registerAccepted = false;
    const registerTimeout = setTimeout(() => {
      if (registerAccepted || ac.signal.aborted) return;
      ac.abort();
    }, REGISTER_TIMEOUT_MS);
    try {
      const callOpts = this.getCallOptions(ac.signal);
      const stream = client.providerStream(queue, callOpts);
      const { browserClip } = buildClipRegistrations();
      queue.push(create(ProviderMessageSchema, {
        payload: {
          case: "register",
          value: create(RegisterRequestSchema, {
            providerName: PROVIDER_NAME,
            clips: [browserClip]
          })
        }
      }));
      for await (const msg of stream) {
        if (ac.signal.aborted && this.stopped) return;
        switch (msg.payload.case) {
          case "registerResponse": {
            clearTimeout(registerTimeout);
            if (!msg.payload.value.accepted) {
              throw new Error(msg.payload.value.message || "Registration rejected");
            }
            registerAccepted = true;
            this.clearReconnect();
            console.error(`${LOG_PREFIX} Registered browser clip (${BROWSER_COMMAND_NAMES.length} commands) at ${this.hubUrl}`);
            break;
          }
          case "invokeCommand": {
            void this.handleInvoke(queue, msg.payload.value);
            break;
          }
          case "dataCommand": {
            void this.handleData(queue, msg.payload.value);
            break;
          }
          case "invokeInput":
            break;
          case "pong":
            break;
          case "getClipWebCommand": {
            void this.handleGetClipWeb(queue, msg.payload.value);
            break;
          }
          default:
            break;
        }
      }
      throw new Error("Provider stream closed");
    } catch (err) {
      if (this.stopped) return;
      throw err;
    } finally {
      clearInterval(heartbeat);
      clearTimeout(registerTimeout);
      queue.close();
      if (this.abortController === ac) this.abortController = null;
    }
  }
  // ---------------------------------------------------------------------------
  // Invoke handling — calls dispatchRequest() directly (no HTTP round-trip)
  // ---------------------------------------------------------------------------
  async handleInvoke(queue, inv) {
    const requestId = inv.requestId?.trim();
    if (!requestId) return;
    try {
      const clipName = inv.clipName?.trim() || "";
      const command = inv.command?.trim() || "";
      const input = decodeInput(inv.input);
      let result;
      if (clipName === BROWSER_CLIP_ALIAS && command === "stream.start") {
        await ensureStreamer();
        const cdpUrl = await this.getCurrentTabCdpUrl();
        const resp = await streamerCommand("/command", {
          method: "connect",
          params: { cdpUrl }
        });
        result = resp?.result ?? resp;
      } else if (clipName === BROWSER_CLIP_ALIAS && command === "stream.answer") {
        const resp = await streamerCommand("/command", {
          method: "answer",
          params: input
        });
        result = resp?.result ?? resp;
      } else if (clipName === BROWSER_CLIP_ALIAS && command === "stream.close") {
        if (!streamerProcess || streamerProcess.killed) {
          result = { ok: true };
        } else {
          const resp = await streamerCommand("/command", {
            method: "stop"
          });
          result = resp?.result ?? resp;
        }
      } else if (clipName === BROWSER_CLIP_ALIAS && command === "stream.switch") {
        const tabRef = input.tab;
        if (!tabRef) throw new Error("Missing tab parameter");
        const cdpUrl = await this.getTabCdpUrl(String(tabRef));
        const resp = await streamerCommand("/command", {
          method: "switch",
          params: { cdpUrl }
        });
        result = resp?.result ?? resp;
      } else if (clipName === BROWSER_CLIP_ALIAS) {
        result = await this.executeBrowserCommand(command, input);
      } else {
        throw new Error(`Unknown clip: ${clipName}`);
      }
      this.send(queue, requestId, encodeOutput(result), void 0);
    } catch (err) {
      this.send(queue, requestId, void 0, err);
    }
  }
  /**
   * Build the CDP WebSocket URL for the current (or first) page target.
   * Used by stream.start to tell the streamer which tab to connect to.
   */
  async getCurrentTabCdpUrl() {
    if (!this.cdp.connected) {
      await Promise.race([
        this.cdp.waitUntilReady(),
        new Promise(
          (_, reject) => setTimeout(() => reject(new Error("CDP connection timeout")), COMMAND_TIMEOUT)
        )
      ]);
    }
    const targets = await this.cdp.getTargets();
    const current = this.cdp.currentTargetId ? targets.find((t) => t.id === this.cdp.currentTargetId && t.type === "page") : void 0;
    const page = current ?? targets.find((t) => t.type === "page");
    if (!page) throw new Error("No page target found for streamer");
    return `ws://${this.cdp.host}:${this.cdp.port}/devtools/page/${page.id}`;
  }
  /**
   * Resolve a short tab ID to a CDP WebSocket URL.
   * Used by stream.switch to tell the streamer which tab to connect to.
   */
  async getTabCdpUrl(tabRef) {
    if (!this.cdp.connected) {
      await Promise.race([
        this.cdp.waitUntilReady(),
        new Promise(
          (_, reject) => setTimeout(() => reject(new Error("CDP connection timeout")), COMMAND_TIMEOUT)
        )
      ]);
    }
    const resolvedId = this.cdp.tabManager.resolveShortId(tabRef);
    const targetId = resolvedId || tabRef;
    const targets = await this.cdp.getTargets();
    const page = targets.find((t) => t.id === targetId && t.type === "page");
    if (!page) throw new Error(`Tab not found: ${tabRef}`);
    return `ws://${this.cdp.host}:${this.cdp.port}/devtools/page/${page.id}`;
  }
  /**
   * Execute a browser command by calling dispatchRequest() directly.
   * This is the key improvement over the standalone provider which
   * had to HTTP POST to the daemon.
   */
  async executeBrowserCommand(cmdName, input) {
    const cmd = BROWSER_COMMANDS.find((c) => c.method === cmdName);
    if (!cmd) throw new Error(`Unknown browser command: ${cmdName}`);
    if (!this.cdp.connected) {
      await Promise.race([
        this.cdp.waitUntilReady(),
        new Promise(
          (_, reject) => setTimeout(() => reject(new Error("CDP connection timeout")), COMMAND_TIMEOUT)
        )
      ]);
    }
    const { tab, ...rest } = input;
    const request3 = {
      method: cmd.method,
      ...rest,
      ...tab !== void 0 ? { tabId: tab } : {}
    };
    const response = await dispatchRequest(this.cdp, request3);
    if (response.error) throw new Error(response.error.message || "Command failed");
    return response.result ?? {};
  }
  // ---------------------------------------------------------------------------
  // Data handling
  // ---------------------------------------------------------------------------
  async handleData(queue, cmd) {
    const requestId = cmd.requestId?.trim();
    if (!requestId) return;
    try {
      const output = await handleDataCommand(cmd);
      this.sendDataResult(queue, requestId, output, void 0);
    } catch (err) {
      this.sendDataResult(queue, requestId, void 0, err);
    }
  }
  // ---------------------------------------------------------------------------
  // GetClipWeb handling — serve files from web/ directory
  // ---------------------------------------------------------------------------
  async handleGetClipWeb(queue, cmd) {
    const requestId = cmd.requestId?.trim();
    if (!requestId) return;
    try {
      let filePath = cmd.path?.trim() || "";
      if (!filePath || filePath === "/" || filePath === "index.html") filePath = "view.html";
      if (filePath.startsWith("/")) filePath = filePath.slice(1);
      if (filePath.includes("..") || filePath.startsWith("/")) {
        throw new Error("Invalid path");
      }
      const currentDir = dirname(fileURLToPath2(import.meta.url));
      const webDirCandidates = [
        resolve(currentDir, "../../../web"),
        resolve(currentDir, "../../web"),
        resolve(currentDir, "../web")
      ];
      let webDir = null;
      for (const candidate of webDirCandidates) {
        if (existsSync2(candidate)) {
          webDir = candidate;
          break;
        }
      }
      if (!webDir) throw new Error("web directory not found");
      const fullPath = join2(webDir, filePath);
      const resolvedFull = resolve(fullPath);
      const resolvedWeb = resolve(webDir);
      if (!resolvedFull.startsWith(resolvedWeb)) {
        throw new Error("Invalid path");
      }
      const content = await readFileAsync(fullPath);
      const ext = extname(filePath).toLowerCase();
      const MIME_MAP = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf"
      };
      const contentType = MIME_MAP[ext] || "application/octet-stream";
      const etag = `"${content.length.toString(16)}"`;
      if (cmd.ifNoneMatch && cmd.ifNoneMatch === etag) {
        queue.push(create(ProviderMessageSchema, {
          payload: {
            case: "getClipWebResult",
            value: create(GetClipWebResultSchema, {
              requestId,
              notModified: true,
              etag,
              totalSize: BigInt(content.length)
            })
          }
        }));
        return;
      }
      const offset = Number(cmd.offset || 0n);
      const length = Number(cmd.length || 0n);
      let slice;
      if (length > 0) {
        slice = new Uint8Array(content.buffer, content.byteOffset + offset, Math.min(length, content.length - offset));
      } else if (offset > 0) {
        slice = new Uint8Array(content.buffer, content.byteOffset + offset);
      } else {
        slice = new Uint8Array(content);
      }
      queue.push(create(ProviderMessageSchema, {
        payload: {
          case: "getClipWebResult",
          value: create(GetClipWebResultSchema, {
            requestId,
            content: slice,
            contentType,
            etag,
            totalSize: BigInt(content.length)
          })
        }
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      const code = message === "Invalid path" ? "invalid_argument" : "not_found";
      queue.push(create(ProviderMessageSchema, {
        payload: {
          case: "getClipWebResult",
          value: create(GetClipWebResultSchema, {
            requestId,
            error: create(HubErrorSchema, { code, message })
          })
        }
      }));
    }
  }
  // ---------------------------------------------------------------------------
  // Result senders
  // ---------------------------------------------------------------------------
  sendDataResult(queue, requestId, output, error2) {
    try {
      const hubError = error2 ? create(HubErrorSchema, { code: "internal", message: error2 instanceof Error ? error2.message : String(error2) }) : void 0;
      let parsed = {};
      if (output) {
        try {
          parsed = JSON.parse(textDecoder.decode(output));
        } catch {
        }
      }
      queue.push(create(ProviderMessageSchema, {
        payload: {
          case: "dataResult",
          value: create(DataResultSchema, {
            requestId,
            content: parsed.content ? new Uint8Array(Buffer.from(parsed.content, "base64")) : void 0,
            uri: parsed.uri || "",
            entries: Array.isArray(parsed.entries) ? parsed.entries.map((e) => create(DataEntrySchema, {
              name: e.name || "",
              path: e.path || "",
              type: e.type || "file",
              size: BigInt(e.size || 0),
              mime: e.mime || ""
            })) : [],
            stat: parsed.stat ? create(DataStatSchema, {
              size: BigInt(parsed.stat.size || 0),
              mime: parsed.stat.mime || "",
              modified: parsed.stat.modified || ""
            }) : void 0,
            error: hubError
          })
        }
      }));
    } catch (e) {
      if (!this.stopped) console.error(`${LOG_PREFIX} Failed to send data result: ${e instanceof Error ? e.message : e}`);
    }
  }
  send(queue, requestId, output, error2) {
    try {
      const hubError = error2 ? create(HubErrorSchema, { code: "internal", message: error2 instanceof Error ? error2.message : String(error2) }) : void 0;
      queue.push(create(ProviderMessageSchema, {
        payload: {
          case: "invokeResult",
          value: create(InvokeResultSchema, { requestId, output, error: hubError, done: true })
        }
      }));
    } catch (e) {
      if (!this.stopped) console.error(`${LOG_PREFIX} Failed to send result: ${e instanceof Error ? e.message : e}`);
    }
  }
  getCallOptions(signal) {
    const token = this.hubToken || process.env.PINIX_HUB_TOKEN?.trim() || process.env.PINIX_TOKEN?.trim();
    const opts = { signal, timeoutMs: 0 };
    if (token) opts.headers = { Authorization: `Bearer ${token}` };
    return opts;
  }
  scheduleReconnect() {
    if (this.reconnectTimer || this.stopped) return;
    console.error(`${LOG_PREFIX} Reconnecting in ${RECONNECT_DELAY_MS}ms`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, RECONNECT_DELAY_MS);
  }
  clearReconnect() {
    if (!this.reconnectTimer) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }
};

// packages/daemon/src/chrome.ts
import { spawn as spawn2, execSync } from "child_process";
import { existsSync as existsSync3, mkdirSync as mkdirSync3, readFileSync as readFileSync4, writeFileSync as writeFileSync3, rmSync, chmodSync as chmodSync2, renameSync, readdirSync as readdirSync2, statSync as statSync2 } from "fs";
import { pipeline as pipeline2 } from "stream/promises";
import { createWriteStream as createWriteStream2 } from "fs";
import path2 from "path";
import os2 from "os";
var BROWSER_DIR = path2.join(
  process.env.BB_BROWSER_HOME || path2.join(os2.homedir(), ".bb-browser"),
  "browser"
);
var CHROME_VERSION = "149.0.7827.22";
var CHROME_CDN_BASE = "https://storage.googleapis.com/chrome-for-testing-public";
var CHROME_COS_BASE = "https://pinix-blobs-1251447449.cos.ap-beijing.myqcloud.com/releases/chrome";
var LOG_PREFIX2 = "[Chrome]";
function detectPlatform() {
  const arch2 = os2.arch();
  const plat = os2.platform();
  if (plat === "darwin") {
    return arch2 === "arm64" ? "mac-arm64" : "mac-x64";
  }
  if (plat === "linux") {
    return arch2 === "arm64" ? "linux-arm64" : "linux64";
  }
  return null;
}
var SYSTEM_CHROME_PATHS = {
  darwin: [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
  ],
  linux: [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium",
    "/usr/bin/microsoft-edge",
    "/usr/bin/brave-browser"
  ]
};
function findSystemChrome() {
  const candidates = SYSTEM_CHROME_PATHS[os2.platform()] ?? [];
  for (const p of candidates) {
    if (existsSync3(p)) return p;
  }
  try {
    const which = os2.platform() === "darwin" ? "which 'Google Chrome' 2>/dev/null || true" : "which google-chrome 2>/dev/null || which chromium 2>/dev/null || which chromium-browser 2>/dev/null || true";
    const result = execSync(which, { encoding: "utf8", timeout: 3e3, stdio: ["pipe", "pipe", "pipe"] }).trim();
    if (result && existsSync3(result)) return result;
  } catch {
  }
  return null;
}
function chromeBinaryName(platform2) {
  if (platform2.startsWith("mac")) {
    return "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";
  }
  return "chrome";
}
function chromeDir(platform2) {
  return path2.join(BROWSER_DIR, `chrome-${platform2}`);
}
function chromePath(platform2) {
  return path2.join(chromeDir(platform2), chromeBinaryName(platform2));
}
function installedVersion() {
  try {
    return readFileSync4(path2.join(BROWSER_DIR, "version"), "utf8").trim();
  } catch {
    return null;
  }
}
function saveVersion(version) {
  mkdirSync3(BROWSER_DIR, { recursive: true });
  writeFileSync3(path2.join(BROWSER_DIR, "version"), version);
}
function getDownloadUrls(platform2) {
  const zipName = `chrome-${platform2}.zip`;
  return [
    `${CHROME_CDN_BASE}/${CHROME_VERSION}/${platform2}/${zipName}`,
    `${CHROME_COS_BASE}/${zipName}`
  ];
}
async function tryFetch(url) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3e4);
    try {
      const resp = await fetch(url, { signal: controller.signal });
      if (resp.ok && resp.body) return resp;
    } finally {
      clearTimeout(timer);
    }
  } catch {
  }
  return null;
}
async function downloadAndExtractChrome(platform2) {
  const zipPath = path2.join(BROWSER_DIR, `chrome-${platform2}.zip`);
  const targetDir = chromeDir(platform2);
  if (existsSync3(targetDir)) {
    rmSync(targetDir, { recursive: true, force: true });
  }
  mkdirSync3(BROWSER_DIR, { recursive: true });
  const urls = getDownloadUrls(platform2);
  let resp = null;
  let usedUrl = "";
  for (const url of urls) {
    console.error(`${LOG_PREFIX2} Downloading Chrome ${CHROME_VERSION} (${platform2}) from ${new URL(url).host}...`);
    resp = await tryFetch(url);
    if (resp) {
      usedUrl = url;
      break;
    }
    console.error(`${LOG_PREFIX2} Download failed, trying next source...`);
  }
  if (!resp) {
    throw new Error(`Failed to download Chrome from any source`);
  }
  const fileStream = createWriteStream2(zipPath);
  await pipeline2(resp.body, fileStream);
  const extractDir = targetDir + ".extract";
  if (existsSync3(extractDir)) {
    rmSync(extractDir, { recursive: true, force: true });
  }
  mkdirSync3(extractDir, { recursive: true });
  console.error(`${LOG_PREFIX2} Extracting...`);
  try {
    execSync(`unzip -q -o "${zipPath}" -d "${extractDir}"`, { stdio: "pipe" });
  } catch (error2) {
    throw new Error(`Failed to extract zip: ${error2 instanceof Error ? error2.message : String(error2)}`);
  }
  rmSync(zipPath, { force: true });
  const binary = findBinaryRecursive(extractDir, "Google Chrome for Testing") ?? findBinaryRecursive(extractDir, "chrome");
  if (!binary) {
    rmSync(extractDir, { recursive: true, force: true });
    throw new Error("Chrome binary not found in zip");
  }
  const binaryParent = platform2.startsWith("mac") ? findAppBundleRoot(extractDir) ?? path2.dirname(binary) : path2.dirname(binary);
  if (existsSync3(targetDir)) rmSync(targetDir, { recursive: true, force: true });
  renameSync(binaryParent, targetDir);
  if (existsSync3(extractDir)) rmSync(extractDir, { recursive: true, force: true });
  const finalPath = chromePath(platform2);
  if (!existsSync3(finalPath)) {
    throw new Error(`Binary not at expected path: ${finalPath}`);
  }
  chmodSync2(finalPath, 493);
  saveVersion(CHROME_VERSION);
  console.error(`${LOG_PREFIX2} Installed Chrome ${CHROME_VERSION}`);
  return finalPath;
}
function findBinaryRecursive(dir, name) {
  try {
    for (const entry of readdirSync2(dir)) {
      const full = path2.join(dir, entry);
      if (entry === name) return full;
      try {
        if (statSync2(full).isDirectory()) {
          const found = findBinaryRecursive(full, name);
          if (found) return found;
        }
      } catch {
      }
    }
  } catch {
  }
  return null;
}
function findAppBundleRoot(extractDir) {
  try {
    const entries = readdirSync2(extractDir);
    const dirs = entries.filter((e) => {
      try {
        return statSync2(path2.join(extractDir, e)).isDirectory();
      } catch {
        return false;
      }
    });
    if (dirs.length === 1) return path2.join(extractDir, dirs[0]);
  } catch {
  }
  return null;
}
function createChromeManager() {
  const platform2 = detectPlatform();
  let resolvedBinary = null;
  return {
    async ensureBinary() {
      const systemChrome = findSystemChrome();
      if (systemChrome) {
        console.error(`${LOG_PREFIX2} Using system Chrome at ${systemChrome}`);
        resolvedBinary = systemChrome;
        return systemChrome;
      }
      if (platform2) {
        const managed = chromePath(platform2);
        if (existsSync3(managed)) {
          const version = installedVersion();
          console.error(`${LOG_PREFIX2} Using managed Chrome ${version ?? "unknown"} at ${managed}`);
          resolvedBinary = managed;
          return managed;
        }
      }
      if (!platform2) {
        throw new Error(
          `No Chrome browser found for ${os2.platform()}/${os2.arch()}. Install Google Chrome or use --no-chrome.`
        );
      }
      console.error(`${LOG_PREFIX2} No Chrome found \u2014 downloading Chrome for Testing...`);
      const binary = await downloadAndExtractChrome(platform2);
      resolvedBinary = binary;
      return binary;
    },
    launch(port, options) {
      const binary = resolvedBinary ?? findSystemChrome() ?? (platform2 ? chromePath(platform2) : null);
      if (!binary || !existsSync3(binary)) {
        throw new Error(`No Chrome binary available. Run ensureBinary() first.`);
      }
      const userDataDir = options?.userDataDir ?? path2.join(
        process.env.BB_BROWSER_HOME || path2.join(os2.homedir(), ".bb-browser"),
        "chrome-data"
      );
      const windowSize = options?.windowSize ?? process.env.CHROME_WINDOW_SIZE ?? "1920,1080";
      mkdirSync3(userDataDir, { recursive: true });
      const args = [
        `--remote-debugging-port=${port}`,
        `--user-data-dir=${userDataDir}`,
        `--window-size=${windowSize}`,
        "--no-first-run",
        "--disable-default-apps",
        "--no-sandbox",
        "about:blank"
      ];
      const isSystem = binary === findSystemChrome();
      const label = isSystem ? "system Chrome" : `managed Chrome ${installedVersion() ?? ""}`;
      console.error(`${LOG_PREFIX2} Launching ${label.trim()} on port ${port}`);
      const child = spawn2(binary, args, {
        stdio: ["ignore", "pipe", "pipe"],
        detached: false
      });
      child.stderr?.on("data", (data) => {
        const line = data.toString().trim();
        if (line) console.error(`${LOG_PREFIX2} ${line}`);
      });
      child.on("exit", (code, signal) => {
        console.error(`${LOG_PREFIX2} Process exited (code=${code}, signal=${signal})`);
      });
      const portFile = path2.join(BROWSER_DIR, "cdp-port");
      mkdirSync3(BROWSER_DIR, { recursive: true });
      writeFileSync3(portFile, String(port));
      return child;
    },
    async waitForCdp(host, port, timeoutMs = 15e3) {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        try {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 2e3);
          try {
            const resp = await fetch(`http://${host}:${port}/json/version`, {
              signal: controller.signal
            });
            if (resp.ok) {
              const info = await resp.json();
              console.error(`${LOG_PREFIX2} CDP ready: ${info.Browser ?? "unknown"}`);
              return;
            }
          } finally {
            clearTimeout(timer);
          }
        } catch {
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      throw new Error(`CDP not ready at ${host}:${port} after ${timeoutMs}ms`);
    }
  };
}

// packages/daemon/src/index.ts
var DAEMON_DIR2 = process.env.BB_BROWSER_HOME || path3.join(os3.homedir(), ".bb-browser");
var DAEMON_JSON = path3.join(DAEMON_DIR2, "daemon.json");
var DEFAULT_CDP_PORT = 9222;
function parseOptions() {
  const { values } = parseArgs({
    allowPositionals: true,
    options: {
      host: {
        type: "string",
        short: "H",
        default: DAEMON_HOST
      },
      port: {
        type: "string",
        short: "p",
        default: String(DAEMON_PORT)
      },
      "cdp-host": {
        type: "string",
        default: "127.0.0.1"
      },
      "cdp-port": {
        type: "string",
        default: String(DEFAULT_CDP_PORT)
      },
      token: {
        type: "string",
        default: ""
      },
      hub: {
        type: "string",
        default: ""
      },
      "hub-token": {
        type: "string",
        default: ""
      },
      "no-chrome": {
        type: "boolean",
        default: false
      },
      help: {
        type: "boolean",
        short: "h",
        default: false
      }
    }
  });
  if (values.help) {
    console.error(`
bb-browser-daemon \u2014 CDP-direct backend for bb-browser

Usage:
  bb-browser-daemon [options]

Options:
  -H, --host <host>          HTTP server host (default: ${DAEMON_HOST})
  -p, --port <port>          HTTP server port (default: ${DAEMON_PORT})
      --cdp-host <host>      Chrome CDP host (default: 127.0.0.1)
      --cdp-port <port>      Chrome CDP port (default: ${DEFAULT_CDP_PORT})
      --token <token>        Bearer auth token (auto-generated if empty)
      --hub <url>            Pinix Hub gRPC URL (enables Hub mode)
      --hub-token <token>    Pinix Hub auth token
      --no-chrome            Skip auto Chrome management (use external Chrome)
  -h, --help                 Show this help message

Endpoints:
  POST /command      Send command and get result (via CDP)
  GET  /status       Daemon health + per-tab stats
  POST /shutdown     Graceful shutdown

Hub mode:
  When --hub is set, the daemon connects to Pinix Hub as an Edge Clip
  provider, registering browser and site commands. Invokes are handled
  directly via CDP without HTTP round-trips.
`);
    process.exit(0);
  }
  let token = values.token ?? "";
  if (!token) {
    token = randomBytes(16).toString("hex");
  }
  let hubUrl = values.hub?.trim() || void 0;
  if (hubUrl) {
    hubUrl = hubUrl.replace(/^ws:\/\//i, "http://").replace(/^wss:\/\//i, "https://");
    const url = new URL(hubUrl);
    if (url.pathname === "/ws/provider" || url.pathname === "/ws/capability") url.pathname = "";
    url.search = "";
    url.hash = "";
    hubUrl = url.toString().replace(/\/$/, "");
  }
  return {
    host: values.host ?? DAEMON_HOST,
    port: parseInt(values.port ?? String(DAEMON_PORT), 10),
    cdpHost: values["cdp-host"] ?? "127.0.0.1",
    cdpPort: parseInt(values["cdp-port"] ?? String(DEFAULT_CDP_PORT), 10),
    token,
    hubUrl,
    hubToken: values["hub-token"]?.trim() || void 0,
    noChrome: values["no-chrome"] ?? false
  };
}
function writeDaemonJson(info) {
  try {
    mkdirSync4(DAEMON_DIR2, { recursive: true });
    writeFileSync4(DAEMON_JSON, JSON.stringify(info), { mode: 384 });
  } catch {
  }
}
function cleanupDaemonJson() {
  // Windows state, even after normal shutdown, is retained for manual identity review.
  if (process.platform === "win32") return;
  if (existsSync4(DAEMON_JSON)) {
    try {
      unlinkSync2(DAEMON_JSON);
    } catch {
    }
  }
}
async function discoverCdpPort(host, port) {
  if (process.platform === "win32" && (host !== "127.0.0.1" || port !== 19224)) {
    throw new Error("Only dedicated CDP 127.0.0.1:19224 is allowed.");
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2e3);
    try {
      const response = await fetch(`http://${host}:${port}/json/version`, {
        signal: controller.signal
      });
      if (response.ok) {
        return { host, port };
      }
    } finally {
      clearTimeout(timer);
    }
  } catch {
  }
  if (process.platform === "win32") throw new Error("Dedicated CDP 19224 disconnected; no fallback.");
  const managedPortFile = path3.join(DAEMON_DIR2, "browser", "cdp-port");
  try {
    const rawPort = readFileSync5(managedPortFile, "utf8").trim();
    const managedPort = parseInt(rawPort, 10);
    if (Number.isInteger(managedPort) && managedPort > 0) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 2e3);
        try {
          const response = await fetch(`http://127.0.0.1:${managedPort}/json/version`, {
            signal: controller.signal
          });
          if (response.ok) {
            return { host: "127.0.0.1", port: managedPort };
          }
        } finally {
          clearTimeout(timer);
        }
      } catch {
      }
    }
  } catch {
  }
  throw new Error(
    `Cannot connect to Chrome CDP at ${host}:${port}. Make sure Chrome is running with --remote-debugging-port=${port}`
  );
}
function readStaleDaemonJson() {
  try {
    const raw = readFileSync5(DAEMON_JSON, "utf8");
    const info = JSON.parse(raw);
    if (typeof info.pid === "number" && typeof info.host === "string" && typeof info.port === "number" && typeof info.token === "string") {
      return info;
    }
    return null;
  } catch {
    return null;
  }
}
function isProcessAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
async function cleanupStaleDaemon() {
  if (process.platform === "win32") {
    if (existsSync4(DAEMON_JSON)) throw new Error("Existing daemon state requires manual identity review.");
    return;
  }
  const info = readStaleDaemonJson();
  if (!info) return;
  if (info.pid === process.pid) return;
  if (!isProcessAlive(info.pid)) {
    cleanupDaemonJson();
    return;
  }
  console.error(`[Daemon] Found stale daemon (pid ${info.pid}), requesting shutdown...`);
  try {
    await new Promise((resolve2, _reject) => {
      const req = httpRequest2(
        {
          hostname: info.host,
          port: info.port,
          path: "/shutdown",
          method: "POST",
          headers: { Authorization: `Bearer ${info.token}` },
          timeout: 3e3
        },
        (res) => {
          res.resume();
          res.on("end", () => resolve2());
        }
      );
      req.on("error", () => resolve2());
      req.on("timeout", () => {
        req.destroy();
        resolve2();
      });
      req.end();
    });
  } catch {
  }
  const deadline = Date.now() + 5e3;
  while (Date.now() < deadline) {
    if (!isProcessAlive(info.pid)) {
      cleanupDaemonJson();
      console.error("[Daemon] Old daemon exited cleanly");
      return;
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  console.error(`[Daemon] Force-killing stale daemon (pid ${info.pid})`);
  try {
    process.kill(info.pid, "SIGKILL");
  } catch {
  }
  cleanupDaemonJson();
}
async function main() {
  const options = parseOptions();
  await cleanupStaleDaemon();
  let chromeProcess = null;
  if (!options.noChrome) {
    const chrome = createChromeManager();
    try {
      await chrome.ensureBinary();
    } catch (error2) {
      console.error(`[Daemon] Failed to get headless-shell: ${error2 instanceof Error ? error2.message : String(error2)}`);
      console.error("[Daemon] Falling back to external Chrome. Use --no-chrome to suppress this.");
    }
    let chromeAlreadyRunning = false;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2e3);
      try {
        const resp = await fetch(`http://${options.cdpHost}:${options.cdpPort}/json/version`, { signal: controller.signal });
        chromeAlreadyRunning = resp.ok;
      } finally {
        clearTimeout(timer);
      }
    } catch {
    }
    if (!chromeAlreadyRunning) {
      try {
        chromeProcess = chrome.launch(options.cdpPort);
        await chrome.waitForCdp(options.cdpHost, options.cdpPort);
      } catch (error2) {
        console.error(`[Daemon] Failed to launch Chrome: ${error2 instanceof Error ? error2.message : String(error2)}`);
      }
    } else {
      console.error(`[Daemon] Chrome already running on port ${options.cdpPort}`);
    }
  }
  const tabManager = new TabStateManager();
  let cdpEndpoint;
  try {
    cdpEndpoint = await discoverCdpPort(options.cdpHost, options.cdpPort);
  } catch (error2) {
    console.error(
      `[Daemon] ${error2 instanceof Error ? error2.message : String(error2)}`
    );
    process.exit(1);
  }
  const cdp = new CdpConnection(cdpEndpoint.host, cdpEndpoint.port, tabManager);
  let hubBridge = null;
  let shuttingDown = false;
  const shutdown = async () => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.error("[Daemon] Shutting down...");
    if (hubBridge) {
      hubBridge.stop();
      hubBridge = null;
    }
    cdp.disconnect();
    await httpServer.stop();
    if (chromeProcess && !chromeProcess.killed) {
      console.error("[Daemon] Stopping managed Chrome");
      chromeProcess.kill("SIGTERM");
    }
    cleanupDaemonJson();
    process.exit(0);
  };
  const httpServer = new HttpServer({
    host: options.host,
    port: options.port,
    token: options.token,
    cdp,
    cdpHost: cdpEndpoint.host,
    cdpPort: cdpEndpoint.port,
    onShutdown: shutdown
  });
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  await httpServer.start();
  writeDaemonJson({
    pid: process.pid,
    host: options.host,
    port: options.port,
    token: options.token,
    cdpHost: cdpEndpoint.host,
    cdpPort: cdpEndpoint.port
  });
  console.error(
    `[Daemon] HTTP server listening on http://${options.host}:${options.port}`
  );
  console.error(`[Daemon] Auth token: ${options.token}`);
  console.error(
    `[Daemon] Connecting to Chrome CDP at ${cdpEndpoint.host}:${cdpEndpoint.port}...`
  );
  try {
    await cdp.connect();
    const tabCount = tabManager.tabCount;
    console.error(
      `[Daemon] CDP connected, monitoring ${tabCount} tab(s)`
    );
  } catch (error2) {
    console.error(
      `[Daemon] Failed to connect to CDP: ${error2 instanceof Error ? error2.message : String(error2)}`
    );
    console.error("[Daemon] HTTP server is running, but commands will fail until CDP connects.");
  }
  if (options.hubUrl) {
    hubBridge = new HubBridge({
      hubUrl: options.hubUrl,
      hubToken: options.hubToken,
      cdp,
      cdpPort: cdpEndpoint.port
    });
    console.error(`[Daemon] Starting Hub bridge to ${options.hubUrl}`);
    hubBridge.start();
  }
}
main().catch((error2) => {
  console.error("[Daemon] Fatal error:", error2);
  cleanupDaemonJson();
  process.exit(1);
});
//# sourceMappingURL=daemon.js.map
