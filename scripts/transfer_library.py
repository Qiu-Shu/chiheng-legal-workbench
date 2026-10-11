#!/usr/bin/env python3
"""Offline personal export, verification and restore; never starts services."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_transfer import export_library, restore_library, verify_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    export.add_argument('--archive', type=Path, required=True)
    restore = commands.add_parser('restore')
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--target', type=Path, required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'export':
            result = export_library(args.root, args.archive)
        elif args.command == 'restore':
            result = restore_library(args.archive, args.target)
        else:
            result = verify_archive(args.archive)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Transfer refused: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
