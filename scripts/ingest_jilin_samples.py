"""Manually triggered fixed local sample batch, not a background whole-site crawl."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jilin_sources import PublicReader, run_samples

if __name__ == '__main__':
    samples = json.loads((ROOT / 'config/jilin-samples.json').read_text())['samples']
    result = run_samples(ROOT, samples, PublicReader())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['ok'] else 1)
