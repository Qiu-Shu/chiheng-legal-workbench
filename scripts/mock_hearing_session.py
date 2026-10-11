"""Explicit local mock hearing JSON session operations; no database or MCP writes."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mock_hearing import append_turn, create_rehearsal, create_session, hearing_progress, load_session


def main():
    parser = argparse.ArgumentParser(
        description='个人本机民商事一审演练：显式 JSON 输入，专用案卷目录，会话不代表真实裁判。',
        epilog='阶段依次为 issues → evidence → questions → debate → review。'
               'issues/questions 须 moderator、plaintiff、defendant 各至少一回；'
               'evidence/debate 须双方各一回；review 仅 reviewer，完成后禁止追加。'
               '目录权限须 0700，新会话与锁为 0600；不自动修改既有目录权限。'
               '材料仅读取 manifest 指定的 UTF-8 文本，最多 100 份，每份 2MB；不转换格式。'
               '普通 append 的 source_cards 为调用者提供的引用卡，本程序不认证其来源；'
               'append-law 调用本地 get_law_fragment，记录完整返回及命题绑定；不核验法律适用性。'
               '为空时 unresolved 必须用非空字符串列表说明未检索或未核实。'
               'synthetic 为布尔值，human_review 永远为 null，不写人工签名。'
               '文件锁仅协调本模块，不能防护同一 OS 账号的其他工具，也不提供多用户安全隔离。')
    commands = parser.add_subparsers(dest='operation', required=True)
    for name, description in [('init', '创建会话，禁止覆盖'), ('read', '校验并读取会话'),
                              ('rehearse', '关联已完成的 v2 会话，在新目录重新演练'),
                              ('progress', '校验并汇总已记录演练进度，仍待律师核验'),
                              ('append', '校验后原子追加回合'),
                              ('append-law', '读取本地法库片段后原子追加回合')]:
        command = commands.add_parser(name, help=description)
        command.add_argument('--case-root', required=True, type=Path, help='专用演练目录的明确路径')
        if name == 'rehearse':
            command.add_argument('--previous-case-root', required=True, type=Path,
                                 help='已完成的 v2 演练目录，仅保存摘要关联')
        if name not in ('read', 'progress'):
            command.add_argument('--input', required=True, type=Path, help='UTF-8 JSON 文件路径')
    args = parser.parse_args()
    try:
        if args.operation == 'read':
            result = load_session(args.case_root)
        elif args.operation == 'progress':
            result = hearing_progress(args.case_root)
        else:
            value = json.loads(args.input.read_text(encoding='utf-8'))
            if args.operation == 'rehearse':
                if not isinstance(value, dict) or set(value) != {'packet', 'focus'}:
                    raise ValueError('rehearse 输入恰需 packet 和 focus')
                result = create_rehearsal(args.case_root, value['packet'],
                                          args.previous_case_root, value['focus'])
            elif args.operation == 'append-law':
                from hearing_sources import append_law_turn
                if not isinstance(value, dict) or set(value) != {'turn', 'sources'}:
                    raise ValueError('append-law 输入恰需 turn 和 sources')
                result = append_law_turn(args.case_root, value['turn'], value['sources'])
            else:
                operation = create_session if args.operation == 'init' else append_turn
                result = operation(args.case_root, value)
    except (OSError, ValueError) as error:
        parser.exit(2, f'未完成：{error}\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
