#!/usr/bin/env python3
"""Run a confirmed hand-over plan in a standalone terminal.

Steps, each checked before the next: preflight -> preview -> the user types
是 -> backup -> verify backup -> move to Trash / Recycle Bin -> verification.
Cancelling writes nothing.
Only the targets written in the plan are touched. Everything shown is also
appended to the plan's log so the AI can read the outcome afterwards.
Exit 0 = finished (see the verification result), 2 = a step failed and the
run stopped, 3 = the user did not confirm (nothing was moved).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import common
import platforms

CONFIRM = '是'
PLAN_KEYS = {'version', 'platform', 'skill_root', 'targets', 'dest', 'includes'}
OK_LINE = '[OK] 备份与源数据一致: '


class Stop(Exception):
    """A step failed; the run ends with exit 2 after reporting."""


def load_plan(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != PLAN_KEYS or data['version'] != 1:
        raise ValueError(f'交接计划格式无效: {path}')
    if data['platform'] != platforms.current().key:
        raise ValueError('交接计划是为另一个平台生成的，拒绝执行')
    targets = data['targets']
    if not isinstance(targets, list) or not 1 <= len(targets) <= 10 or not all(isinstance(t, str) for t in targets):
        raise ValueError('交接计划的目标清单无效（需要 1–10 个路径）')
    if not isinstance(data['includes'], list) or not all(isinstance(i, str) for i in data['includes']):
        raise ValueError('交接计划的额外备份清单无效')
    return data


class Runner:
    def __init__(self, plan, log):
        self.plan, self.log = plan, log
        self.scripts = Path(plan['skill_root']) / 'scripts'
        self.folder = None  # set once a backup has been created

    def say(self, text=''):
        print(text, flush=True)
        self.log.write(text + '\n')
        self.log.flush()

    def call(self, title, script, *args, accept=(0,)):
        self.say(f'\n== {title} ==')
        result = subprocess.run([sys.executable, str(self.scripts / script), *args],
                                capture_output=True, text=True, encoding='utf-8')
        for stream in (result.stdout, result.stderr):
            if stream:
                self.say(stream.rstrip('\n'))
        if result.returncode not in accept:
            raise Stop(f'{title}失败（退出码 {result.returncode}）')
        return result

    def run(self, answer):
        plan = self.plan
        target_args = list(plan['targets'])
        include_args = [arg for item in plan['includes'] for arg in ('--include', item)]
        place = '回收站' if platforms.current().key == 'win32' else '废纸篓'
        self.say('本次交接只处理以下已确认的目标：')
        for target in target_args:
            self.say('  ' + target)
        self.call('第 1 步：前提自检', 'preflight.py', '--dest', plan['dest'], *include_args)
        self.call('第 2 步：预览将要移走的目标', 'trash_paths.py', '--dry-run', *target_args)
        self.say(f'\n确认后会先备份到 {plan["dest"]}，校验通过才把上面列出的目标移入{place}。')
        try:
            reply = answer(f'确认请输入“{CONFIRM}”并回车，其他输入都会取消：').strip()
        except EOFError:
            reply = ''  # no answer is not a confirmation
        self.say(f'（输入：{reply or "空"}）')
        if reply != CONFIRM:
            self.say('[已取消] 没有备份、也没有移动任何文件。')
            return 3
        made = self.call('第 3 步：创建备份', 'backup.py', '--dest', plan['dest'], *include_args)
        folders = [line[len(OK_LINE):] for line in made.stdout.splitlines() if line.startswith(OK_LINE)]
        if len(folders) != 1:
            raise Stop('第 3 步没有给出唯一的备份目录，无法继续')
        self.folder = folders[0]
        self.call('第 4 步：校验备份', 'backup.py', '--verify', self.folder)
        self.call(f'第 5 步：移入{place}', 'trash_paths.py', '--apply', '--backup', self.folder, *target_args)
        check = self.call('第 6 步：验收扫描（不含浏览器）', 'scan_readonly.py', '--no-browser', accept=(0, 1))
        self.say('\n[完成] 已按确认清单处理。' + ('验收无命中。' if check.returncode == 0 else
                                             '验收仍有命中项，需要逐项判断（可能是保留项）。'))
        self.restore_hint(self.folder)
        return 0

    def restore_hint(self, folder):
        windows = platforms.current().key == 'win32'
        script = 'py -3 scripts\\backup.py' if windows else 'python3 scripts/backup.py'
        paths = ' '.join(f'--path "{target}"' for target in self.plan['targets'])
        self.say('需要恢复时，在 skill 目录先预检再执行（每个目标一条 --path）：')
        self.say(f'  {script} --restore "{folder}" {paths} --dry-run')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    args = parser.parse_args()
    common.require_supported()
    plan = load_plan(args.plan)
    log_path = args.plan.with_suffix('.log')
    with log_path.open('a', encoding='utf-8') as log:
        runner = Runner(plan, log)
        try:
            code = runner.run(input)
        except Stop as stop:
            runner.say(f'\n[停止] {stop}。之后的步骤都没有执行；已完成的步骤见上方输出。')
            if runner.folder:
                runner.restore_hint(runner.folder)
            code = 2
        runner.say(f'\n交接结束，退出码 {code}。日志：{log_path}')
    return code


if __name__ == '__main__':
    sys.exit(common.cli(main))
