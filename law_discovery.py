"""Bounded official candidate discovery, separate from legal text and approval."""
import asyncio
import copy
import portable_lock as fcntl
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from official_monitor import atomic_write, encode, stamp


class PageDrift(ValueError):
    pass


def save_evidence(root, category, value):
    payload = encode(value)
    path = root / 'data/discovery' / category / (hashlib.sha256(payload).hexdigest()+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes()!=payload:
            raise ValueError('证据内容冲突')
    else:
        atomic_write(path,payload)


def discovery_lines(report):
    if not report:
        return ['尚未运行官方候选发现。']
    if report.get('status') == 'access_blocked':
        previous = report.get('previous_report')
        history = f'[旧报告]({previous})' if previous else '未附旧报告链接'
        return ['- 状态：access_blocked；本次未检查官方候选。',
                f'- 停止原因：{report.get("reason", "来源访问受限")}。',
                f'- 来源限制证据：[robots.txt]({report.get("evidence", {}).get("url", "")})。',
                f'- 历史候选数量本次未核对，见旧报告：{history}；不能据此判断候选为空或发现完成。']
    window = report.get('window') or {}
    return [f'- 最近尝试：{report.get("at", "未知")}；状态：{report.get("status", "未知")}',
            f'- 查询范围：{window.get("start", "未知")} 至 {window.get("end", "未知")}。',
            f'- 来源声称总数：{report.get("source_total", "未知")}；本窗口已校验候选：{report.get("observed_in_window", 0)}；',
            f'- 分页覆盖：{"未完成" if report.get("partial", True) else "该窗口已读完"}；历史去重候选：{report.get("candidate_count", 0)}。',
            f'- 异常重扫次数：{report.get("restarts",0)}；需要人工处理分页异常：{report.get("requires_attention",False)}。',
            '- 候选不等于正文入库、现行有效或人工审核；90日以外迟录资料可能遗漏，不能视为全国完整覆盖。']


def validate_page(data, window, page, size):
    total, rows = data.get('total'), data.get('rows')
    if (data.get('code') != 200 or type(total) is not int or total < 0 or not isinstance(rows, list)
            or len(rows) != min(size, max(0, total - (page - 1) * size))):
        raise ValueError('页长或源总数异常')
    selected = []
    for row in rows:
        if (not isinstance(row, dict) or not re.fullmatch('[0-9a-f]{32}', row.get('bbbs', ''))
                or any(not isinstance(row.get(k), str) or not row[k].strip()
                       for k in ('title', 'gbrq', 'zdjgName', 'flxz'))
                or 'sxrq' not in row or 'sxx' not in row):
            raise ValueError('候选身份或字段缺失')
        published = date.fromisoformat(row['gbrq'])
        if not date.fromisoformat(window['start']) <= published <= date.fromisoformat(window['end']):
            raise ValueError('公布日期不符合查询范围')
        selected.append({k: row[k] for k in ('bbbs', 'title', 'gbrq', 'sxrq', 'sxx', 'zdjgName', 'flxz')})
    if len({row['bbbs'] for row in selected}) != len(selected):
        raise ValueError('页内ID重复')
    return total, selected


async def run_discovery(root, fetch_page, *, today=None, page_size=50, max_rows=100, timeout=240,
                        query_profile='default'):
    root = Path(root)
    today = today or date.today()
    if not 1 <= page_size <= 50 or not 2*page_size <= max_rows <= 100:
        raise ValueError('超出固定读取范围')
    verification = root / 'verification'
    verification.mkdir(parents=True, exist_ok=True)
    report_path = verification / 'law-discovery-latest.json'
    with (verification / 'law-discovery.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'ok': False, 'partial': True, 'status': 'locked'}
        report = {'at': stamp(), 'ok': False, 'partial': True, 'status': 'running',
                  'scope': '官方近90日候选；非全国完整性、非原文入库、非效力审核',
                  'candidate_count': 0, 'read_this_run': 0, 'new_candidates_this_run': 0}
        atomic_write(report_path, encode(report))
        state = {'catalog': {}, 'last_completed_window': None}
        persisted = copy.deepcopy(state)
        initial_count = 0
        state_path = root / 'data/discovery/state.json'
        try:
            if state_path.exists():
                state = json.loads(state_path.read_text())
            if not isinstance(state.get('catalog'),dict) or 'last_completed_window' not in state:
                raise ValueError('状态结构异常')
            persisted = copy.deepcopy(state)
            initial_count = len(state['catalog'])
            active = state.get('active')
            if not active or active['complete']:
                active = {'window': {'start': (today - timedelta(days=90)).isoformat(), 'end': today.isoformat()},
                          'page_size': page_size, 'next_page': 1, 'total': None, 'seen': [],
                          'last_page_hash': None, 'complete': False,'query_profile':query_profile}
                state['active'] = active
            if active.get('query_profile','default')!=query_profile:
                save_evidence(root,'abandoned',active)
                active = dict(active, next_page=1,total=None,seen=[],last_page_hash=None,
                              complete=False,restart_pending=False,restarts=0,query_profile=query_profile)
                state['active']=active
            if active.get('restart_pending'):
                if active.get('restarts',0)>=2:
                    raise ValueError('两次重扫仍不稳定，需人工检查来源；不再自动重扫')
                save_evidence(root,'abandoned',active)
                active = dict(active, next_page=1,total=None,seen=[],last_page_hash=None,
                              complete=False,restart_pending=False,restarts=active.get('restarts',0)+1)
                state['active'] = active
            # A resumed window uses its original page size, not caller defaults.
            size = active['page_size']
            if 2*size>max_rows:
                raise ValueError('续跑预算不足以重验并推进')
            deadline = asyncio.get_running_loop().time() + timeout
            recheck = active['next_page'] > 1
            while report['read_this_run'] + size <= max_rows:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError()
                page = active['next_page'] - 1 if recheck else active['next_page']
                data = await asyncio.wait_for(fetch_page(active['window'], page, size), min(45, remaining))
                save_evidence(root,'responses',{'window':active['window'],'page':page,'size':size,
                                              'query_profile':query_profile,'data':data})
                total, rows = validate_page(data, active['window'], page, size)
                report['read_this_run'] += len(rows)
                digest = hashlib.sha256(encode({'total': total, 'rows': rows})).hexdigest()
                if active['total'] is not None and active['total'] != total:
                    raise PageDrift('源总数漂移，需重新核对窗口')
                if recheck:
                    if digest != active['last_page_hash']:
                        raise PageDrift('已读页漂移，停止推进')
                    recheck = False
                    continue
                ids = [row['bbbs'] for row in rows]
                if set(ids) & set(active['seen']):
                    raise PageDrift('跨页重复，停止推进')
                snapshot = root / 'data/discovery/pages' / (digest + '.json')
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                if not snapshot.exists():
                    atomic_write(snapshot, encode({'total': total, 'rows': rows}))
                for row in rows:
                    key = row['bbbs']
                    report['new_candidates_this_run'] += key not in state['catalog']
                    state['catalog'][key] = dict(row, source_url=f'https://flk.npc.gov.cn/detail?id={key}',
                                                review_state='candidate_only', text_acquired=False)
                active.update(total=total, next_page=page+1, last_page_hash=digest,
                              seen=active['seen'] + ids)
                active['complete'] = len(active['seen']) == total
                if active['complete']:
                    state['last_completed_window'] = dict(active['window'])
                state_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(state_path, encode(state))
                persisted = copy.deepcopy(state)
                if active['complete']:
                    break
            report.update(ok=active['complete'], partial=not active['complete'],
                          status='window_complete' if active['complete'] else 'partial')
        except Exception as error:
            report.update(status='failed', error='超时' if isinstance(error, TimeoutError) else
                          '来源筛选、分页、数据或本地状态异常；未推进失败页，不接受为完整结果')
            if isinstance(error,PageDrift):
                # Failed page is never committed. Journal bounded recovery using
                # only the last durable cursor; next run restarts this same window.
                recovery = copy.deepcopy(persisted)
                recovery['active']['restart_pending'] = True
                try:
                    atomic_write(state_path,encode(recovery))
                    persisted = recovery
                except OSError:
                    pass
        state = persisted
        active = state.get('active', {})
        report.update(window=active.get('window'), source_total=active.get('total'),
                      observed_in_window=len(active.get('seen', [])), next_page=active.get('next_page', 1),
                      candidate_count=len(state['catalog']), last_completed_window=state['last_completed_window'],
                      new_candidates_this_run=len(state['catalog'])-initial_count,
                      restart_pending=active.get('restart_pending',False),restarts=active.get('restarts',0),
                      query_profile=active.get('query_profile','default'),
                      requires_attention=bool(active.get('restart_pending') and active.get('restarts',0)>=2),
                      finished_at=stamp())
        atomic_write(report_path, encode(report))
        return report
