# -*- coding: utf-8 -*-
"""教师后台聚合：从 attempts 明细 + scores 汇总，生成总览、个人画像、全班薄弱点。"""
from collections import defaultdict, OrderedDict
import attempts

TEACHER_SID = 'abc123'

# 临床思维 6 维：键 → (中文名, 满分)
DIMS = OrderedDict([
    ('chain', ('依据链完整性', 25)),
    ('weight', ('证据权重识别', 20)),
    ('differential', ('鉴别诊断', 20)),
    ('ask_purpose', ('问诊目的性', 15)),
    ('exam_hypothesis', ('检查-假设对应', 10)),
    ('treat_logic', ('治疗-诊断逻辑', 10)),
])

SECTION_NAME = {'history': '病史采集', 'analysis': '病例分析', 'reasoning': '临床思维'}
KIND_SECTION = {'history_score': 'history', 'analysis_score': 'analysis', 'reasoning_score': 'reasoning'}


def _latest_by_case(events, kind):
    """每个病例取该类最新一次事件。"""
    latest = {}
    for ev in events:
        if ev['kind'] == kind and ev.get('case'):
            latest[ev['case']] = ev
    return list(latest.values())


def student_summary(data):
    """从一个学生的 attempts 数据聚合画像摘要。"""
    st = data.get('student', {})
    events = data.get('events', [])
    logins = [e for e in events if e['kind'] == 'login' and not e.get('teacher')]
    score_events = [e for e in events if e['kind'] in KIND_SECTION and not e.get('teacher')]

    sec = {}
    for kind, key in KIND_SECTION.items():
        latest = _latest_by_case(events, kind)
        scores = [e.get('score') for e in latest if isinstance(e.get('score'), (int, float))]
        sec[key] = {
            'cases': len(latest),
            'avg': round(sum(scores) / len(scores)) if scores else None,
        }

    # 临床思维 6 维（每个病例最新一次，再平均）
    dim_avg = {}
    rev = _latest_by_case(events, 'reasoning_score')
    for k, (_, full) in DIMS.items():
        vals = [e['dims'][k] / full for e in rev if e.get('dims') and k in e['dims']]
        dim_avg[k] = round(sum(vals) / len(vals) * 100) if vals else None

    rejects = sum(e.get('rejects', 0) for e in rev)
    last_active = max((e['ts'] for e in events), default='')
    return {
        'sid': st.get('sid'), 'name': st.get('name'), 'class': st.get('class'),
        'logins': len(logins), 'last_active': last_active,
        'sections': sec, 'dims': dim_avg, 'rejects': rejects,
        'attempt_count': len(score_events),
        'active': bool(logins or score_events),
    }


def all_summaries():
    out = {}
    for sid, data in attempts.load_all():
        if sid == TEACHER_SID:
            continue
        out[sid] = student_summary(data)
    return out


def class_weakness(summaries):
    """全班 6 维平均薄弱度 + 病史采集高频漏项。"""
    # 6 维
    dim_agg = {}
    for k, (name, full) in DIMS.items():
        vals = [s['dims'][k] for s in summaries.values() if s['dims'][k] is not None]
        dim_agg[k] = {'name': name, 'avg': round(sum(vals) / len(vals)) if vals else None,
                      'full': full, 'n': len(vals)}

    # 病史高频漏项（关键项 + 一般项分别统计未覆盖次数）
    miss_crit = defaultdict(int)
    miss_item = defaultdict(int)
    students_seen = set()
    for sid, data in attempts.load_all():
        if sid == TEACHER_SID:
            continue
        for e in _latest_by_case(data.get('events', []), 'history_score'):
            students_seen.add((sid, e.get('case')))
            for m in e.get('critical_missed', []):
                miss_crit[m] += 1
            for cat in e.get('detail', []):
                for it in cat.get('items', []):
                    if not it.get('covered'):
                        miss_item[it['label']] += 1
    top_miss = sorted(miss_item.items(), key=lambda x: -x[1])[:10]
    top_crit = sorted(miss_crit.items(), key=lambda x: -x[1])[:8]
    return {'dims': dim_agg, 'top_missed': top_miss, 'top_critical_missed': top_crit,
            'history_sample': len(students_seen)}


def student_detail(sid):
    """个人画像 + 完整时间线（含原始作答）。"""
    data = attempts.load_student(sid)
    if not data:
        return None
    summary = student_summary(data)
    events = sorted(data.get('events', []), key=lambda e: e.get('ts', ''))
    # 薄弱标签
    tags = []
    for k, (name, _) in DIMS.items():
        v = summary['dims'][k]
        if v is not None and v < 60:
            tags.append(f'{name}偏弱({v})')
    if summary['rejects'] >= 2:
        tags.append(f'依据链多次被打回({summary["rejects"]}次)')
    # 病史关键漏项（跨病例去重计数）
    cm = defaultdict(int)
    for e in _latest_by_case(events, 'history_score'):
        for m in e.get('critical_missed', []):
            cm[m] += 1
    for m, n in sorted(cm.items(), key=lambda x: -x[1])[:4]:
        tags.append(f'常漏问：{m}({n}次)')
    summary['tags'] = tags
    return {'summary': summary, 'events': events, 'dim_meta': {k: list(v) for k, v in DIMS.items()}}
