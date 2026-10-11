"""Manual fixed disclosure batch. No scheduler, discovery, or legal approval."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jilin_disclosures import run_disclosures
from jilin_sources import PublicReader


if __name__ == '__main__':
    config = json.loads((ROOT/'config/jilin-disclosures.json').read_text())
    report = run_disclosures(ROOT, config['sources'], PublicReader())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['ok'] else 1)
