#!/usr/bin/env python3
"""Read-only inventory: do not run shell startup files or hide scan failures."""
import argparse
from pathlib import Path
import json
import sys
import common
import verify_reset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--deep', action='store_true')
    args = parser.parse_args()
    common.require_supported()
    path = Path.home() / '.claude.json'
    if common.exists(path):
        common.regular(path)
        obj = json.loads(path.read_text())
        if not isinstance(obj, dict):
            raise ValueError('.claude.json 必须是 JSON 对象')
        keys = [key for key in ('machineID', 'userID', 'deviceId', 'installationId') if key in obj]
        print('身份键存在数量: ' + str(len(keys)))
    alive = common.relevant_processes(common.process_list())
    print(f'相关运行进程: {len(alive)}；清理前必须全部退出')
    total = verify_reset.report(verify_reset.collect(deep=args.deep, no_browser=args.no_browser))
    if args.no_browser:
        print('[EXCLUDED] 用户通过 --no-browser 排除浏览器层；这不是完整验收')
    return 1 if total or alive else 0


if __name__ == '__main__':
    sys.exit(common.cli(main))
