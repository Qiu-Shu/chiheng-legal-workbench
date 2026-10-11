"""Record an explicit public-source review declaration; no MCP write tool."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from review_records import append_record


def main():
    parser = argparse.ArgumentParser(
        description='追加公开引用的结构化核验记录；不会改正文库或自动确认人工审核。',
        epilog='必填: source_kind/source_url/locator/content_sha256/reviewer/reviewer_kind/'
               'checked_at/result/scope。reviewer_kind=human或automated；'
               'result=match/mismatch/inconclusive；scope=entire_law/entire_case/fragment。'
               '案例另须case_reference_status与judgment_validity，未知显式填unverified。'
               'hash必须对应本次scope的内容；match不表示法律适用性或裁判效力已获确认。')
    parser.add_argument('--input', required=True, help='结构化JSON文件；-表示从标准输入读取')
    parser.add_argument('--ledger', type=Path, default=ROOT / 'data/review-records.jsonl',
                        help='追加JSONL账本路径；默认data/review-records.jsonl')
    args = parser.parse_args()
    try:
        raw = sys.stdin.read() if args.input == '-' else Path(args.input).read_text(encoding='utf-8')
        result = append_record(args.ledger, json.loads(raw))
    except (OSError, ValueError) as error:
        parser.exit(2, f'未记录: {error}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
