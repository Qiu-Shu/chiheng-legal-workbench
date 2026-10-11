"""Manual fixed traffic collection; --offline replays only archived originals."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jilin_sources import PublicReader
from legal_store import LegalStore
from traffic_collection import BASE, CachedReader, ingest_collection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'config/jilin-traffic.json')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    reader = (CachedReader(args.root, manifest) if args.offline
              else PublicReader(evidence_root=args.root / BASE / 'responses'))
    store = LegalStore(args.root / 'data/legal.sqlite3')
    try:
        report = ingest_collection(args.root, manifest, reader, store)
    finally:
        store.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
