"""National official database automation remains blocked on this installation."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from official_access import FLK_ACCESS_BLOCK

if __name__ == '__main__':
    print(json.dumps({'status': 'blocked', 'policy': FLK_ACCESS_BLOCK}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(2)
