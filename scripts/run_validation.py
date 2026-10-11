"""Record real engineering test results separately from model/lawyer evaluation."""
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {'at': datetime.now(timezone.utc).isoformat(), 'tests_run': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'passed': result.wasSuccessful(),
              'model_behavior_50_scenarios_completed': False, 'human_law_review_completed': False}
    (ROOT / 'verification/acceptance-latest.log').write_text(stream.getvalue())
    (ROOT / 'verification/acceptance-latest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if not result.wasSuccessful():
        print(stream.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
