# -*- coding: utf-8 -*-
"""病例分析题库的科目归属与达标门槛。

成绩册（gradebook.py）、教师后台（unified_admin）、学情看板共用这一份口径，
不要在别处另立一份，否则题库扩充后会对不上。

口径（2026-10-15 定）：
  - 完成数  = 该生在该科目下【去重后】的病例数（同一例重交只算一例）
  - 均分    = 该科目各例分数平均
  - 折算分  = 均分 × min(完成数 ÷ 门槛, 1)   ← 做够门槛才拿满分，不足按比例砍
  - 门槛    = 口内 10 例为基准，口外/口修按各自题库规模等比折算（四舍五入，至少 1 例）
"""
import os
import json

BASE = os.path.dirname(os.path.abspath(__file__))

# 原有 13 例（reasoning_cases / 2 / 3），全部口内
_LEGACY = {f'case{i:03d}': '口内' for i in range(1, 14)}

SUBJECT_ORDER = ['口内', '口外', '口修']

BASE_SUBJECT = '口内'
BASE_DONE = 10          # 基准：口内做满 10 例


def _load():
    """case_id → 科目。只收进【病例分析板块有题】的病例（病史采集专用的不参与）。"""
    m = dict(_LEGACY)
    p = os.path.join(BASE, 'analysis_cases_56.json')
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
            for cid, r in d.items():
                if isinstance(r, dict) and r.get('analysis'):
                    m[cid] = r.get('subject') or '未分类'
        except Exception:
            pass
    return m


SUBJECT_OF = _load()


def count_by_subject():
    c = {}
    for s in SUBJECT_OF.values():
        c[s] = c.get(s, 0) + 1
    return c


def _thresholds():
    cnt = count_by_subject()
    base = cnt.get(BASE_SUBJECT) or 1
    return {s: max(1, round(n * BASE_DONE / base)) for s, n in cnt.items()}


THRESHOLDS = _thresholds()


def threshold_of(subject):
    return THRESHOLDS.get(subject, BASE_DONE)


def subject_stats(case_scores):
    """{case_id: 分数} → {科目: {done, avg, threshold, final}}；无提交的科目不出现。"""
    agg = {}
    for cid, sc in (case_scores or {}).items():
        if not isinstance(sc, (int, float)):
            continue
        s = SUBJECT_OF.get(cid, '未分类')
        a = agg.setdefault(s, {'done': 0, 'total': 0.0})
        a['done'] += 1
        a['total'] += float(sc)
    out = {}
    for s, a in agg.items():
        avg = round(a['total'] / a['done'], 1)
        th = threshold_of(s)
        out[s] = {'done': a['done'], 'avg': avg, 'threshold': th,
                  'final': round(avg * min(a['done'] / th, 1.0), 1)}
    return out


def official_score(case_scores):
    """正式总评用的病例分析折算分（2026-10-16 起计入总评，与学生通知口径一致）：

    各科目折算分（均分×min(完成/门槛,1)）按该科门槛数加权平均；
    只累计【有提交】的科目——没做过的科目不拖分（口外/口修未布置时不惩罚），
    一旦做了就自动按各自门槛计入。当前实际只有口内有提交，等价于口内折算分。
    """
    st = subject_stats(case_scores)
    if not st:
        return None
    num = sum((v['final'] or 0) * v['threshold'] for v in st.values())
    den = sum(v['threshold'] for v in st.values())
    return round(num / den) if den else None


if __name__ == '__main__':
    print('题库规模:', count_by_subject())
    print('达标门槛:', THRESHOLDS)
