"""Replay rehearsal tracking events; recorded progress never establishes legal approval."""
from datetime import date
import re


TRACKING_FIELDS = {'issue_id', 'questions', 'responses', 'tasks', 'law_checks'}
QUESTION_FIELDS = {'question_id', 'text', 'addressed_to'}
RESPONSE_FIELDS = {'question_id', 'kind', 'text'}
TASK_FIELDS = {'task_id', 'text', 'kind', 'status', 'material_ids', 'review_note'}
LAW_FIELDS = {'claim', 'source_card_index', 'fact_date', 'research_as_of',
              'temporal_note', 'transition_note', 'applicability_note', 'status'}
NOTICE = ('仅汇总已记录的演练进度；阶段完成、问题已回答或任务已补充均不代表风险消除、'
          '法律适用正确或已获批准。未记录 tracking 不代表没有风险；仍须律师核验。')


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('tracking 对象字段缺失或包含未知字段')


def _date(value):
    if value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('tracking 日期须为 null 或真实的 YYYY-MM-DD 日期')
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('tracking 日期须为 null 或真实的 YYYY-MM-DD 日期') from error


def replay_tracking(turns):
    """Validate cross-turn references and derive issues in first-appearance order.

    Turn indices are zero-based. Responses and law checks remain in the original
    turns; questions retain every response index, and tasks expose the latest event.
    Base turn, material and source-card shapes must already have been validated.
    """
    issues, questions, tasks = {}, {}, {}
    for index, turn in enumerate(turns):
        if 'tracking' not in turn:
            continue
        tracking = turn['tracking']
        _fields(tracking, TRACKING_FIELDS)
        issue_id = tracking['issue_id']
        if not _text(issue_id):
            raise ValueError('tracking issue_id 必须为非空字符串')
        if any(not isinstance(tracking[key], list) for key in TRACKING_FIELDS - {'issue_id'}):
            raise ValueError('tracking questions、responses、tasks、law_checks 必须为列表')
        if issue_id not in issues:
            issues[issue_id] = dict(issue_id=issue_id, questions=[], tasks={}, law_checks=[])
        issue = issues[issue_id]
        for question in tracking['questions']:
            _fields(question, QUESTION_FIELDS)
            identifier = question['question_id']
            if (not _text(identifier) or identifier in questions
                    or not _text(question['text']) or question['text'] not in turn['text']
                    or not _text(question['addressed_to'])
                    or question['addressed_to'] not in {'plaintiff', 'defendant'}):
                raise ValueError('tracking 问题 ID 须全局唯一、文本须出现在当轮发言中且指向一方')
            item = dict(question, question_turn_index=index, latest_response_kind=None,
                        response_turn_indices=[])
            questions[identifier] = (issue_id, item)
            issue['questions'].append(item)
        responded = set()
        for response in tracking['responses']:
            _fields(response, RESPONSE_FIELDS)
            identifier = response['question_id']
            if (not _text(identifier) or identifier not in questions or identifier in responded
                    or not _text(response['kind']) or response['kind'] not in {'answer', 'unable_to_answer'}
                    or not _text(response['text']) or response['text'] not in turn['text']):
                raise ValueError('tracking 回答须唯一关联已存在问题、使用有效类型并逐字出现在发言中')
            question_issue, question = questions[identifier]
            if (question_issue != issue_id or question['question_turn_index'] >= index
                    or question['addressed_to'] != turn['role']):
                raise ValueError('tracking 只能由被提问方回答同争点此前回合的问题')
            responded.add(identifier)
            question['latest_response_kind'] = response['kind']
            question['response_turn_indices'].append(index)
        for check in tracking['law_checks']:
            _fields(check, LAW_FIELDS)
            card_index = check['source_card_index']
            if (not _text(check['claim']) or check['claim'] not in turn['text']
                    or (card_index is not None and (type(card_index) is not int
                        or not 0 <= card_index < len(turn['source_cards'])))
                    or not _text(check['status']) or check['status'] not in {'needs_review', 'blocked'}):
                raise ValueError('tracking 法核命题须逐字绑定发言，引用卡序号须有效，状态仅限待核或阻断')
            for key in ('fact_date', 'research_as_of'):
                _date(check[key])
            for key in ('temporal_note', 'transition_note', 'applicability_note'):
                if check[key] is not None and not _text(check[key]):
                    raise ValueError('tracking 法核说明须为 null 或非空字符串')
            issue['law_checks'].append(dict(check, turn_index=index))
        updated = set()
        for task in tracking['tasks']:
            _fields(task, TASK_FIELDS)
            identifier, kind, status = task['task_id'], task['kind'], task['status']
            if (not _text(identifier) or identifier in updated or not _text(task['text'])
                    or not _text(kind) or kind not in {'evidence', 'law', 'wording'}
                    or not _text(status) or status not in {'open', 'addressed_pending_review'}
                    or (task['review_note'] is not None and not _text(task['review_note']))):
                raise ValueError('tracking 任务须有唯一 ID、文本、有效类型及未批准的状态')
            material_ids = task['material_ids']
            if (not isinstance(material_ids, list) or any(not _text(item) for item in material_ids)
                    or len(set(material_ids)) != len(material_ids)
                    or not set(material_ids) <= set(turn['material_ids'])):
                raise ValueError('tracking 任务材料 ID 须唯一且属于当轮 material_ids')
            if status == 'addressed_pending_review' and (
                    not _text(task['review_note']) or (kind == 'evidence' and not material_ids)
                    or (kind == 'law' and not tracking['law_checks'])):
                raise ValueError('tracking 已补充待复核任务须有说明；证据须有材料，法律须有当轮法核记录')
            identity = (issue_id, kind, task['text'])
            if identifier in tasks and tasks[identifier] != identity:
                raise ValueError('tracking 同一任务更新不得改变争点、类型或文本')
            updated.add(identifier)
            tasks[identifier] = identity
            issue['tasks'][identifier] = dict(task, turn_index=index)
    result = []
    for issue in issues.values():
        latest_tasks = list(issue['tasks'].values())
        result.append(dict(issue, tasks=latest_tasks,
            unanswered_question_ids=[question['question_id'] for question in issue['questions']
                                     if question['latest_response_kind'] != 'answer'],
            pending_review_task_ids=[task['task_id'] for task in latest_tasks
                                     if task['status'] == 'addressed_pending_review']))
    return result
