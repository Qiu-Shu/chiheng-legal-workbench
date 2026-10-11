#!/usr/bin/env node

// packages/shared/dist/index.js
import { readFile } from "fs/promises";
import { request as httpRequest } from "http";
import { homedir } from "os";
import { join } from "path";
var DAEMON_PORT = 19824;
var DAEMON_HOST = "127.0.0.1";
var COMMAND_TIMEOUT = 3e4;
var COMMANDS = [
  // ---------------------------------------------------------------------------
  // Navigate
  // ---------------------------------------------------------------------------
  {
    method: "open",
    group: "navigate",
    description: "Navigate to a URL. Opens in a new tab if no tab is specified.",
    requiresTab: false,
    params: {
      url: { type: "string", required: true, position: 0, description: "URL to open" },
      tab: { type: "string", required: false, description: "Tab short ID to navigate in (omit to open in a new tab)" }
    }
  },
  {
    method: "goto",
    group: "navigate",
    description: "Navigate current tab to a URL (keeps tab context)",
    requiresTab: true,
    params: {
      url: { type: "string", required: true, position: 0, description: "URL to navigate to" },
      tab: { type: "string", required: false, description: "Tab ID" }
    }
  },
  {
    method: "back",
    group: "navigate",
    description: "Navigate back in browser history",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "forward",
    group: "navigate",
    description: "Navigate forward in browser history",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "reload",
    group: "navigate",
    description: "Reload the current page",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "close",
    group: "navigate",
    description: "Close the current tab",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  // ---------------------------------------------------------------------------
  // Observe
  // ---------------------------------------------------------------------------
  {
    method: "snap",
    group: "observe",
    description: "Get accessibility tree snapshot of the current page. Returns ref numbers for interactive elements.",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" },
      interactive: { type: "boolean", required: false, description: "Only show interactive elements" },
      compact: { type: "boolean", required: false, description: "Remove empty structural nodes for a more concise tree" },
      maxDepth: { type: "number", required: false, description: "Limit tree depth" },
      selector: { type: "string", required: false, description: "CSS selector to filter the snapshot scope" }
    }
  },
  {
    method: "screenshot",
    group: "observe",
    description: "Take a screenshot of the current page and return it as a PNG data URL",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "get",
    group: "observe",
    description: "Get element text, attribute, or page-level values (url, title)",
    requiresTab: true,
    params: {
      attribute: { type: "string", required: true, position: 0, description: "Attribute to retrieve (text/url/title/value/html)" },
      ref: { type: "string", required: false, description: "Element ref from snapshot (optional for url/title)" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "eval",
    group: "observe",
    description: "Execute JavaScript in the page context and return the result",
    requiresTab: false,
    params: {
      script: { type: "string", required: true, position: 0, description: "JavaScript source to execute" },
      tab: { type: "string", required: false, description: "Tab short ID (optional when domain is set)" },
      domain: { type: "string", required: false, description: "Target domain \u2014 auto-routes to a matching tab or creates one" },
      args: { type: "string", required: false, description: "JSON arguments to pass to the script (accessible as first arg in an IIFE)" }
    }
  },
  // ---------------------------------------------------------------------------
  // Interact
  // ---------------------------------------------------------------------------
  {
    method: "click",
    group: "interact",
    description: "Click an element by ref number from snapshot",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "hover",
    group: "interact",
    description: "Hover over an element by ref number from snapshot",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "fill",
    group: "interact",
    description: "Clear an input field and fill it with new text",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      text: { type: "string", required: true, position: 1, description: "Text to fill" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "type",
    group: "interact",
    description: "Type text into an input field without clearing existing content",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      text: { type: "string", required: true, position: 1, description: "Text to type" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "check",
    group: "interact",
    description: "Check a checkbox element",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "uncheck",
    group: "interact",
    description: "Uncheck a checkbox element",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "select",
    group: "interact",
    description: "Select a value from a dropdown (select element)",
    requiresTab: true,
    params: {
      ref: { type: "string", required: true, position: 0, description: "Element ref from snapshot" },
      value: { type: "string", required: true, position: 1, description: "Option value to select" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "press",
    group: "interact",
    description: "Press a keyboard key (e.g. Enter, Tab, Control+a)",
    requiresTab: true,
    params: {
      key: { type: "string", required: true, position: 0, description: "Key name to press, e.g. Enter or Control+a" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "scroll",
    group: "interact",
    description: "Scroll the page in a given direction",
    requiresTab: true,
    params: {
      direction: { type: "string", required: true, position: 0, description: "Scroll direction (up/down/left/right)" },
      pixels: { type: "number", required: false, description: "Scroll distance in pixels", default: 300 },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  // ---------------------------------------------------------------------------
  // Tab
  // ---------------------------------------------------------------------------
  {
    method: "tab_list",
    group: "tab",
    description: "List all open browser tabs with their URLs, titles, and short IDs",
    requiresTab: false,
    params: {}
  },
  {
    method: "tab_new",
    group: "tab",
    description: "Open a new browser tab, optionally navigating to a URL",
    requiresTab: false,
    params: {
      url: { type: "string", required: false, position: 0, description: "URL to open in the new tab (defaults to about:blank)" }
    }
  },
  // ---------------------------------------------------------------------------
  // Frame
  // ---------------------------------------------------------------------------
  {
    method: "frame",
    group: "frame",
    description: "Switch context to an iframe by CSS selector",
    requiresTab: true,
    params: {
      selector: { type: "string", required: true, position: 0, description: "CSS selector for the iframe element" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "frame_main",
    group: "frame",
    description: "Switch context back to the main frame",
    requiresTab: true,
    params: {
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "dialog",
    group: "frame",
    description: "Arm a handler for the next browser dialog (alert, confirm, prompt, beforeunload)",
    requiresTab: true,
    params: {
      dialogResponse: { type: "string", required: true, position: 0, description: "How to respond: accept or dismiss", default: "accept" },
      promptText: { type: "string", required: false, description: "Text to enter in a prompt dialog (optional, used with accept)" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  // ---------------------------------------------------------------------------
  // Site
  // ---------------------------------------------------------------------------
  {
    method: "site_list",
    group: "site",
    description: "List all available site adapters",
    requiresTab: false,
    params: {}
  },
  {
    method: "site_search",
    group: "site",
    description: "Search site adapters by name, description, or domain",
    requiresTab: false,
    params: {
      query: { type: "string", required: true, position: 0, description: "Search query" }
    }
  },
  {
    method: "site_info",
    group: "site",
    description: "Show detailed metadata for a site adapter",
    requiresTab: false,
    params: {
      siteName: { type: "string", required: true, position: 0, description: "Adapter name (e.g. reddit/thread)" }
    }
  },
  {
    method: "site_run",
    group: "site",
    description: "Run a site adapter to extract structured data from a website",
    requiresTab: false,
    params: {
      siteName: { type: "string", required: true, position: 0, description: "Adapter name (e.g. reddit/thread, twitter/user)" },
      tab: { type: "string", required: false, description: "Tab short ID (auto-detected from adapter domain if omitted)" }
    }
  },
  // ---------------------------------------------------------------------------
  // Debug
  // ---------------------------------------------------------------------------
  {
    method: "network",
    group: "debug",
    description: "Inspect or manage network activity. Supports incremental queries with since.",
    requiresTab: true,
    params: {
      action: { type: "string", required: false, position: 0, description: "Sub-command: requests (default), route, unroute, clear", default: "requests" },
      filter: { type: "string", required: false, description: "URL substring filter for requests" },
      since: { type: "string", required: false, description: "Incremental query: 'last_action' for events since last operation, or a seq number" },
      method: { type: "string", required: false, description: "Filter by HTTP method (GET, POST, etc.)" },
      status: { type: "string", required: false, description: "Filter by status: '4xx', '5xx', or exact code like '200'" },
      limit: { type: "number", required: false, description: "Max number of results to return" },
      withBody: { type: "boolean", required: false, description: "Include request and response bodies" },
      excludeStatic: { type: "boolean", required: false, description: "Exclude static assets (.js, .css, .png, etc.)" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "console",
    group: "debug",
    description: "Get or clear console messages from the page",
    requiresTab: true,
    params: {
      action: { type: "string", required: false, description: "Sub-command: get (default) or clear", default: "get" },
      filter: { type: "string", required: false, description: "Filter console messages by text substring" },
      since: { type: "string", required: false, description: "Incremental query: 'last_action' for events since last operation, or a seq number" },
      limit: { type: "number", required: false, description: "Max number of results to return" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "errors",
    group: "debug",
    description: "Get or clear JavaScript errors from the page",
    requiresTab: true,
    params: {
      action: { type: "string", required: false, description: "Sub-command: get (default) or clear", default: "get" },
      filter: { type: "string", required: false, description: "Filter errors by text substring" },
      since: { type: "string", required: false, description: "Incremental query: 'last_action' for events since last operation, or a seq number" },
      limit: { type: "number", required: false, description: "Max number of results to return" },
      tab: { type: "string", required: true, description: "Tab short ID" }
    }
  },
  {
    method: "trace",
    group: "debug",
    description: "Record a unified timeline of actions + network requests for site adapter creation",
    requiresTab: false,
    params: {
      action: { type: "string", required: true, position: 0, description: "Sub-command: start, stop, status, events, body" },
      tab: { type: "string", required: false, description: "Tab short ID (start: trace only this tab; events: filter by tab)" },
      since: { type: "string", required: false, description: "Incremental query cursor (seq number)" },
      type: { type: "string", required: false, description: "Filter by event type: action, request, response, navigation" },
      filter: { type: "string", required: false, description: "URL or text substring filter" },
      limit: { type: "number", required: false, description: "Max number of events to return" },
      requestId: { type: "string", required: false, description: "Request ID (for trace body)" },
      excludeStatic: { type: "boolean", required: false, description: "Exclude static assets (.js, .css, .png, etc.)" }
    }
  },
  {
    method: "cookies",
    group: "debug",
    description: "List cookies for the current page",
    requiresTab: true,
    params: {
      tab: { type: "string", required: false, description: "Tab ID" },
      filter: { type: "string", required: false, description: "Filter by cookie name or domain" }
    }
  },
  {
    method: "source",
    group: "debug",
    description: "Search loaded JavaScript sources (e.g. source grep '/api/')",
    requiresTab: true,
    params: {
      action: { type: "string", required: true, position: 0, description: "Sub-command: grep" },
      pattern: { type: "string", required: true, position: 1, description: "Search pattern (string or regex)" },
      tab: { type: "string", required: false, description: "Tab ID" }
    }
  }
];
function commandToJsonSchema(cmd) {
  const properties = {};
  const required = [];
  for (const [name, def] of Object.entries(cmd.params)) {
    if (name === "tab") continue;
    const prop = { type: def.type, description: def.description };
    if (def.default !== void 0) prop.default = def.default;
    properties[name] = prop;
    if (def.required) required.push(name);
  }
  return JSON.stringify({
    type: "object",
    properties,
    ...required.length > 0 ? { required } : {},
    additionalProperties: true
  });
}
var DAEMON_DIR = process.env.BB_BROWSER_HOME || join(homedir(), ".bb-browser");
var DAEMON_JSON = join(DAEMON_DIR, "daemon.json");
async function readDaemonJson() {
  try {
    const raw = await readFile(DAEMON_JSON, "utf8");
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
function httpJson(method, urlPath, info, body, timeout = 5e3) {
  return new Promise((resolveP, reject) => {
    const payload = body !== void 0 ? JSON.stringify(body) : void 0;
    const req = httpRequest(
      {
        hostname: info.host,
        port: info.port,
        path: urlPath,
        method,
        headers: {
          Authorization: `Bearer ${info.token}`,
          ...payload ? {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(payload)
          } : {}
        },
        timeout
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        res.on("end", () => {
          const raw = Buffer.concat(chunks).toString("utf8");
          if ((res.statusCode ?? 500) >= 400) {
            reject(new Error(`Daemon HTTP ${res.statusCode}: ${raw}`));
            return;
          }
          try {
            resolveP(JSON.parse(raw));
          } catch {
            reject(new Error(`Invalid JSON from daemon: ${raw}`));
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Daemon request timed out"));
    });
    if (payload) req.write(payload);
    req.end();
  });
}

export {
  DAEMON_PORT,
  DAEMON_HOST,
  COMMAND_TIMEOUT,
  COMMANDS,
  commandToJsonSchema,
  DAEMON_DIR,
  DAEMON_JSON,
  readDaemonJson,
  isProcessAlive,
  httpJson
};
//# sourceMappingURL=chunk-ELAKRFAZ.js.map