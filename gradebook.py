# -*- coding: utf-8 -*-
"""统一成绩册：把 5 个操作评分板块（reports/）+ 临床思维训练（scores/）
按学号聚合成“一人一行、一列一个板块”。

- 新提交带 student_number，直接归学号；
- 历史报告只有姓名/班级：按 (姓名, 班级) 自动匹配花名册，重名或匹配不上列入 unmatched；
- 明显测试数据（匿名/test/测试等）归为 junk，不计入。
"""
import os
import json
import glob
from students import load_students, class_template_map, fill_workbook, SCORE_COLS

BASE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(BASE, 'reports')
SCORE_DIR = os.path.join(BASE, 'scores')

# 板块键 → (中文名, 报告文件前缀；思维板块无报告)
MODULES = [
    ('class2', 'II类洞制备'),
    ('endo', '开髓术'),
    ('xray', '根管X光'),
    ('crown_ant', '前牙全瓷冠'),
    ('crown_post', '后牙全瓷冠'),
    ('thinking', '临床思维'),
]
MODULE_NAME = dict(MODULES)
SCORING_MODULES = [k for k, _ in MODULES if k != 'thinking']

_PREFIX = {'endo_': 'endo', 'xray_': 'xray', 'crown_ant_': 'crown_ant', 'crown_post_': 'crown_post'}
_JUNK_NAMES = {'匿名', '未知', 'test', 'testing', '测试', '测试学生', '冒烟', '123456', '同学', '学生'}


def _norm(s):
    return str(s or '').strip().replace(' ', '')


def _is_junk(name):
    n = _norm(name).lower()
    return (not n) or (n in _JUNK_NAMES) or any(j in n for j in ('测试', 'test', '冒烟', 'abc'))


def _roster_nameclass_index():
    """(姓名,班级) → 学号；同名同班重复则置 None（不自动匹配）。"""
    idx, dup = {}, set()
    for st in load_students():
        key = (_norm(st['name']), _norm(st['class']))
        if key in idx:
            dup.add(key)
        idx[key] = st['sid']
    for key in dup:
        idx[key] = None
    return idx


def _module_of(fname):
    name = fname[:-5] if fname.endswith('.json') else fname
    for pre, mod in _PREFIX.items():
        if name.startswith(pre):
            return mod, name[len(pre):]
    return 'class2', name


def _thinking_scores():
    """读思维训练成绩：{学号: {history,analysis,reasoning,final}}"""
    out = {}
    if not os.path.isdir(SCORE_DIR):
        return out
    for f in glob.glob(os.path.join(SCORE_DIR, '*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        sid = d.get('student_number') or os.path.basename(f)[:-5]
        secs = d.get('sections', {})

        def avg(x):
            vals = [v for v in (x or {}).values() if isinstance(v, (int, float))]
            return round(sum(vals) / len(vals)) if vals else None

        h, a, r = avg(secs.get('history')), avg(secs.get('analysis')), avg(secs.get('reasoning'))
        tot = wsum = 0
        for key, val, w in (('h', h, .3), ('a', a, .3), ('r', r, .4)):
            if val is not None:
                tot += val * w; wsum += w
        final = round(tot / wsum) if wsum else None
        out[sid] = {'history': h, 'analysis': a, 'reasoning': r, 'final': final,
                    'name': d.get('name', ''), 'class': d.get('class', '')}
    return out


def collect():
    """返回 (rows_by_sid, unmatched, junk_count)。
    rows_by_sid[sid] = {sid,name,class, modules:{key:{best,latest,report_id}}, thinking:{...}}
    """
    roster = {st['sid']: st for st in load_students()}
    name_idx = _roster_nameclass_index()
    rows = {}
    unmatched = []
    junk = 0

    def ensure(sid, name='', klass=''):
        row = rows.setdefault(sid, {'sid': sid, 'name': name, 'class': klass,
                                    'modules': {}})
        if not row['name'] and name:
            row['name'] = name
        if not row['class'] and klass:
            row['class'] = klass
        return row

    # 1) 操作评分报告
    for f in sorted(glob.glob(os.path.join(REPORT_DIR, '*.json'))):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        mod, rep_id = _module_of(os.path.basename(f))
        score = d.get('total_score')
        if not isinstance(score, (int, float)):
            continue
        score = round(float(score), 1)
        sid = _norm(d.get('student_number'))
        name, klass = _norm(d.get('student_name')), _norm(d.get('student_class'))
        ts = d.get('timestamp', '')

        if not sid:
            if _is_junk(name):
                junk += 1
                continue
            sid = name_idx.get((name, klass)) if klass and klass != '未知班级' else None
            if not sid:
                unmatched.append({'name': name, 'class': klass, 'module': mod,
                                  'module_name': MODULE_NAME[mod], 'score': score,
                                  'report_id': rep_id, 'ts': ts})
                continue
        row = ensure(sid, name or roster.get(sid, {}).get('name', ''),
                     klass or roster.get(sid, {}).get('class', ''))
        m = row['modules'].setdefault(mod, {'best': None, 'latest': None, 'report_id': None, 'ts': ''})
        if m['best'] is None or score > m['best']:
            m['best'] = score; m['report_id'] = rep_id
        if ts >= m['ts']:
            m['latest'] = score; m['ts'] = ts

    # 2) 思维训练成绩
    for sid, t in _thinking_scores().items():
        if sid == 'abc123' or _is_junk(t.get('name')):
            continue
        row = ensure(sid, t.get('name') or roster.get(sid, {}).get('name', ''),
                     t.get('class') or roster.get(sid, {}).get('class', ''))
        if t.get('final') is not None:
            row['modules']['thinking'] = {'best': t['final'], 'latest': t['final'],
                                          'report_id': None, 'ts': '',
                                          'sub': {'history': t['history'], 'analysis': t['analysis'],
                                                  'reasoning': t['reasoning']}}
        row['thinking_detail'] = {'history': t['history'], 'analysis': t['analysis'],
                                  'reasoning': t['reasoning'], 'final': t['final']}

    # 3) 补齐花名册信息
    for sid, st in roster.items():
        row = ensure(sid, st['name'], st['class'])
        row['in_roster'] = True
    return rows, unmatched, junk


def class_rows(klass=''):
    rows, unmatched, junk = collect()
    out = []
    for sid, r in rows.items():
        if klass and r.get('class') != klass:
            continue
        rec = {'sid': sid, 'name': r['name'], 'class': r.get('class', ''),
               'in_roster': r.get('in_roster', False)}
        for key, _ in MODULES:
            m = r['modules'].get(key)
            rec[key] = m['best'] if m else None
        rec['report_ids'] = {k: v['report_id'] for k, v in r['modules'].items() if v.get('report_id')}
        rec['thinking_detail'] = r.get('thinking_detail')
        done = [k for k, _ in MODULES if rec.get(k) is not None]
        rec['done_modules'] = done
        out.append(rec)
    out.sort(key=lambda x: (x['class'], x['sid']))
    return out, unmatched, junk


def composite(rec, include):
    """所勾板块简单平均（各占 100/N），缺做不计；返回 (综合分, 已做数, 缺做数)。"""
    vals = [rec[k] for k in include if rec.get(k) is not None]
    if not vals:
        return None, 0, len(include)
    return round(sum(vals) / len(vals)), len(vals), len(include) - len(vals)
