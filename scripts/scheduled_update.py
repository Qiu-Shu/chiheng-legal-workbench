"""One bounded run per latest due period, including catch-up after sleep/reboot."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import portable_lock as fcntl
TZ = ZoneInfo('Asia/Shanghai')
TASKS = ('national', 'local', 'integrity', 'monthly-coverage')


def latest_due(task, now):
    if task not in TASKS:
        raise ValueError(f'未知任务：{task}')
    if now.tzinfo is None:
        raise ValueError('调度时间必须包含时区')
    local = now.astimezone(TZ)
    hour, minute = (6, 30) if task == 'national' else (7, 0) if task == 'local' else (8, 0)
    # Every configured period has an occurrence within the preceding 38 days.
    for days in range(39):
        due = (local - timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        valid = (due.weekday() < 5 if task == 'national' else
                 due.weekday() in (1, 4) if task == 'local' else
                 due.weekday() == 6 and (task != 'monthly-coverage' or due.day <= 7))
        if valid and due <= local:
            return due
    raise RuntimeError('未找到计划时点')


def save_state(path, state):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def execute(task, root=ROOT):
    commands = []
    if task in ('national', 'monthly-coverage'):
        commands.append([sys.executable, str(root / 'scripts/refresh_upstream_catalog.py'),
                         '--config', str(root / 'config/shared-library.json'),
                         '--output-root', str(root / 'data/upstream-catalog')])
    if task in ('national', 'local', 'monthly-coverage'):
        group = 'all' if task == 'monthly-coverage' else task
        commands.append([sys.executable, str(root / 'scripts/probe_sources.py'), '--group', group])
    if task in ('integrity', 'monthly-coverage'):
        commands.append([sys.executable, str(root / 'scripts/integrity_report.py'), '--kind', task])
        commands.append([sys.executable, str(root / 'scripts/export_obsidian_library.py')])
    if task == 'national':
        commands.append([sys.executable, str(root / 'scripts/discover_official_laws.py')])
        commands.append([sys.executable, str(root / 'scripts/check_official_originals.py')])
        commands.append([sys.executable, str(root / 'scripts/export_obsidian_library.py')])
    results = []
    log = root / 'verification' / f'{task}.log'
    with log.open('a') as output:
        for command in commands:
            if (task != 'national' and Path(command[1]).name == 'export_obsidian_library.py'
                    and results[-1].get('returncode') != 0):
                results.append({'script': 'export_obsidian_library.py', 'skipped': '报告生成失败'})
                continue
            output.write(f'\n{datetime.now(TZ).isoformat()} {task}\n')
            output.flush()
            try:
                completed = subprocess.run(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                           timeout=300, check=False)
                results.append({'script': Path(command[1]).name, 'returncode': completed.returncode})
            except subprocess.TimeoutExpired:
                results.append({'script': Path(command[1]).name, 'error': '300秒超时'})
    ok = all(result.get('returncode') == 0 for result in results)
    return {'ok': ok, 'commands': results, 'log': str(log),
            'error': None if ok else '任务未完成；详见命令状态与日志'}


def run_due(*, root=ROOT, now=None, tasks=TASKS, runner=None):
    root = Path(root)
    now = (now or datetime.now(TZ)).astimezone(TZ)
    verification = root / 'verification'
    verification.mkdir(parents=True, exist_ok=True)
    runner = runner or (lambda task: execute(task, root))
    state_path = verification / 'scheduler-state.json'
    with (verification / 'scheduler.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'locked', 'tasks': {}}
        state = json.loads(state_path.read_text()) if state_path.exists() else {'tasks': {}}
        state.update(schema_version=1, timezone='Asia/Shanghai')
        results = {}
        for task in tasks:
            due = latest_due(task, now)
            entry = state['tasks'].setdefault(task, {})
            if entry.get('last_success_due') and datetime.fromisoformat(entry['last_success_due']) >= due:
                results[task] = {'status': 'not_due'}
                continue
            if entry.get('retry_after') and datetime.fromisoformat(entry['retry_after']) > now:
                results[task] = {'status': 'backoff', 'retry_after': entry['retry_after']}
                continue
            entry.update(status='running', last_attempt=now.isoformat(), last_attempt_due=due.isoformat())
            entry.pop('result', None)
            save_state(state_path, state)
            try:
                result = runner(task)
                if not result.get('ok'):
                    raise RuntimeError(json.dumps(result, ensure_ascii=False))
                entry.update(status='succeeded', last_success=now.isoformat(), last_success_due=due.isoformat(),
                             failures=0, result=result)
                entry.pop('error', None)
                entry.pop('retry_after', None)
            except Exception as error:
                failures = entry.get('failures', 0) + 1
                delay = min(360, 15 * 2 ** min(failures - 1, 5))
                entry.update(status='failed', failures=failures, error=str(error)[:2000],
                             retry_after=(now + timedelta(minutes=delay)).isoformat())
            save_state(state_path, state)
            results[task] = dict(entry)
        return {'status': 'failed' if any(row['status'] == 'failed' for row in results.values()) else 'ok',
                'tasks': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=('all',) + TASKS, default='all')
    args = parser.parse_args()
    result = run_due(tasks=TASKS if args.task == 'all' else (args.task,))
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(1 if result['status'] == 'failed' else 0)
