"""Real Scrapling checks; fixture data is never ingested as legal material."""
import hashlib
import importlib.metadata
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scrapling.fetchers import Fetcher, DynamicFetcher

ROOT = Path(__file__).resolve().parents[1]
HTML = '<html><meta charset="utf-8"><h1>持衡抓取测试</h1><p id="dynamic"></p><script>document.querySelector("#dynamic").textContent="动态加载成功";</script></html>'.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *args):
        pass


def main():
    results = {"at": datetime.now(timezone.utc).isoformat(),
               "scrapling": importlib.metadata.version("scrapling"), "checks": []}
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/"
        for name, operation in (
            ("static_chinese", lambda: Fetcher.get(url, stealthy_headers=False, retries=0).css("h1::text").get() == "持衡抓取测试"),
            ("dynamic_javascript", lambda: DynamicFetcher.fetch(url, google_search=False, timeout=15000, retries=1).css("#dynamic::text").get() == "动态加载成功"),
        ):
            try:
                results["checks"].append({"name": name, "passed": bool(operation())})
            except Exception as error:
                results["checks"].append({"name": name, "passed": False, "error": str(error)[:1200]})
        server.shutdown()
        thread.join()
    # One ordinary request to the vendor's documentation; not a legal authority.
    try:
        page = Fetcher.get("https://scrapling.readthedocs.io/en/latest/ai/agent-skill.html",
                           stealthy_headers=False, retries=0, timeout=25)
        title = page.css("title::text").get()
        results["checks"].append({"name": "external_documentation", "passed": page.status == 200 and bool(title) and "Scrapling" in title,
                                  "status": page.status, "title": title, "sha256": hashlib.sha256(page.body).hexdigest()})
    except Exception as error:
        results["checks"].append({"name": "external_documentation", "passed": False, "error": str(error)[:1200]})
    target = ROOT / "verification" / "scrapling-smoke.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["passed"] for item in results["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
