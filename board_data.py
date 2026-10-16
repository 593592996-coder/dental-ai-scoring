# -*- coding: utf-8 -*-
"""学情看板数据层（v1：病史采集 / 病例分析）。

口径（2026-10-15 定）：
  · 主口径 = 每人该板块各例的【平均分】（不取历史最高分，避免反复练习虚高）
  · 最高分 = 各例最高分 → 参考小字
  · 薄弱点 = 按【病例】排行（全班得分最低的病例最该讲）。
    attempts/ 的类别覆盖度、常漏问项、四小项明细目前只有 7 个学生有记录，
    样本太小，v1 不做维度口径；等数据攒够再加一层。
  · 训练成果 = 【练习曲线】第 N 次作答的全班均分。
    ⚠️ 不做「首例 vs 末例」：实测 177 人里 170 人的首例都是 case001（题库默认第一题），
    末例人人不同，两者相减测的是病例难度差、不是学生进步（实测会得出 -5.4 的假衰落）。
    练习曲线同样含自我选择偏差（做得越多的学生本身越投入、越强），
    所以样本数 n 随次数递减，页面必须同时标 n 并注明仅供趋势参考。

数据源：scores/*.json 的 sections.history / sections.analysis（逐例分数）。
班级归属复用 gradebook.collect()（老数据班名归一、教师/匿名账号剔除都在里面），
科目与折算分复用 analysis_subjects（勿另立口径）。
"""
import os
import glob
import json
import time

import gradebook
import analysis_subjects

BASE = os.path.dirname(os.path.abspath(__file__))
SCORE_DIR = os.path.join(BASE, 'scores')

SECTIONS = [('history', '病史采集'), ('analysis', '病例分析')]
SECTION_NAME = dict(SECTIONS)

MIN_CASES = 3        # 病例上榜的最小完成人数；不足的不进榜，但底部另计提示
SMALL_SAMPLE = 10    # 有成绩人数低于此值 → 页面上提示样本偏小

BUCKETS = [('90-100', '#27ae60'), ('80-89', '#2B7BEC'), ('70-79', '#f39c12'),
           ('60-69', '#e67e22'), ('<60', '#c0392b'), ('未完成', '#c7ced6')]

# 病例短标题兜底（training.CASE_BRIEF 的副本，仅当训练模块导入失败时用）
_BRIEF_FALLBACK = {
    'case001': '左下后牙夜间痛', 'case002': '门牙摔断', 'case003': '牙龈反复鼓脓包',
    'case004': '左下后牙跳痛 · 脸肿发热', 'case005': '后牙有洞 · 冷酸',
    'case006': '多颗牙颈部酸痛', 'case007': '后牙有洞 · 冷热痛',
    'case008': '后牙定点咬合痛', 'case009': '多颗牙表面发黄 · 敏感',
    'case010': '半侧脸电击样剧痛', 'case011': '后牙磨平 · 敏感',
    'case012': '牙缝胀痛 · 塞牙后', 'case013': '感冒后上后牙胀痛',
}

_meta_cache = None
_rows_cache = {'ts': 0.0, 'rows': None}


# ───────── 装载 ─────────
def _rows(ttl=30):
    """gradebook.collect() 结果，30 秒内复用（看板一次要出多个组合，避免重复读 1789 份报告）。"""
    now = time.time()
    if _rows_cache['rows'] is None or now - _rows_cache['ts'] > ttl:
        _rows_cache['rows'] = gradebook.collect()
        _rows_cache['ts'] = now
    return _rows_cache['rows'][0]


def _case_meta():
    """case_id → {'brief': 短标题, 'subject': 科目}。优先训练题库，失败退回题库文件与内置表。

    科目优先级：analysis_subjects.SUBJECT_OF（系统既有统一口径）→ 病例底牌自带 → 映射表。
    """
    global _meta_cache
    if _meta_cache is not None:
        return _meta_cache
    rc, briefs, subj = {}, dict(_BRIEF_FALLBACK), {}
    try:
        import training
        rc = getattr(training, 'REASONING', {}) or {}
        briefs.update(getattr(training, 'CASE_BRIEF', {}) or {})
        subj = getattr(training, 'CASE_SUBJECT', {}) or {}
    except Exception:
        pass
    if not rc:                                   # 兜底：直接读 56 道病例分析题库
        try:
            with open(os.path.join(BASE, 'analysis_cases_56.json'), encoding='utf-8') as f:
                rc = json.load(f)
        except Exception:
            rc = {}
    out = {}
    for cid, r in rc.items():
        r = r if isinstance(r, dict) else {}
        out[cid] = {'brief': r.get('brief') or briefs.get(cid, '') or r.get('title', ''),
                    'subject': (analysis_subjects.SUBJECT_OF.get(cid)
                                or r.get('subject') or subj.get(cid, ''))}
    for cid, b in briefs.items():               # 补齐兜底表里有、题库里没有的
        out.setdefault(cid, {'brief': b, 'subject': subj.get(cid, '')})
    _meta_cache = out
    return out


_per_case_cache = None


def _load_per_case():
    """{学号: {板块: {病例: 分数}}} —— 逐例分数，collect() 只给每节均分，这里自己读。"""
    global _per_case_cache
    if _per_case_cache is not None:              # 一次进程内不变，预览要跑 30 多个组合
        return _per_case_cache
    out = {}
    for f in glob.glob(os.path.join(SCORE_DIR, '*.json')):
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception:
            continue                              # 容错：坏文件跳过
        sid = str(d.get('student_number') or os.path.basename(f)[:-5]).strip()
        if not sid:
            continue
        secs = d.get('sections') or {}
        out[sid] = {k: (v if isinstance(v, dict) else {}) for k, v in secs.items()}
    _per_case_cache = out
    return out


# 板块 → 题库标志：病例底牌里有这个键，说明该例这个板块有题可做
_SECTION_FLAG = {'history': 'history_outline', 'analysis': 'analysis'}
_bank_cache = {}


def _bank_by_subject(section):
    """该板块题库按科目的病例数，如 {'口内': 48, '口外': 8, '口修': 13}。取不到返回 {}。"""
    if section in _bank_cache:
        return _bank_cache[section]
    flag = _SECTION_FLAG.get(section)
    out = {}
    rc = {}
    try:
        import training
        rc = getattr(training, 'REASONING', {}) or {}
    except Exception:
        pass
    if rc and flag:
        meta = _case_meta()
        for cid, r in rc.items():
            if not isinstance(r, dict) or flag not in r:
                continue
            s = (meta.get(cid) or {}).get('subject') or '未分类'
            out[s] = out.get(s, 0) + 1
    _bank_cache[section] = out
    return out


def _bucket(v):
    if v is None:
        return '未完成'
    if v >= 90:
        return '90-100'
    if v >= 80:
        return '80-89'
    if v >= 70:
        return '70-79'
    if v >= 60:
        return '60-69'
    return '<60'


def _avg(vs):
    return round(sum(vs) / len(vs), 1) if vs else None


# ───────── 主入口 ─────────
def board(klass='', section='history', subject=''):
    klass = (klass or '').strip()
    section = section if section in SECTION_NAME else 'history'
    subject = (subject or '').strip()

    rows = _rows()
    meta = _case_meta()
    per = _load_per_case()

    working = [(sid, r) for sid, r in rows.items() if not klass or r.get('class') == klass]

    # 该板块出现过的科目 → 下拉选项（口内/口外/口修固定在前，其余科目追加在后）
    seen_subj = set()
    for sid, _r in working:
        for cid in ((per.get(sid) or {}).get(section) or {}):
            seen_subj.add((meta.get(cid) or {}).get('subject') or '未分类')
    subject_options = [{'key': '', 'name': '全部科目'}] + [
        {'key': s, 'name': s} for s in
        (analysis_subjects.SUBJECT_ORDER + sorted(seen_subj - set(analysis_subjects.SUBJECT_ORDER)))]
    if subject and subject not in [o['key'] for o in subject_options]:
        subject = ''                              # 非法科目 → 回落全部

    def cases_of(sid):
        """该生本板块的逐例分数，按科目筛选后。"""
        cs = (per.get(sid) or {}).get(section) or {}
        if subject:
            cs = {c: v for c, v in cs.items()
                  if ((meta.get(c) or {}).get('subject') or '未分类') == subject}
        return cs

    people = []
    for sid, r in working:
        cs = cases_of(sid)
        vals = [v for c, v in cs.items() if isinstance(v, (int, float))]
        if not vals:
            continue                              # 该板块（该科目）没作答 → 算「未完成」
        order = [v for c, v in cs.items() if isinstance(v, (int, float))]  # JSON 保插入序 = 作答先后
        people.append({'sid': sid, 'name': r.get('name') or '', 'class': r.get('class') or '',
                       'cases': len(vals), 'avg': sum(vals) / len(vals),
                       'order': order, 'best': max(vals),
                       'cases_map': {c: v for c, v in cs.items() if isinstance(v, (int, float))}})

    roster = len([1 for _, r in working if r.get('in_roster')])
    scored = len(people)
    # scores/ 里有作答、但成绩册里找不到（无姓名/非本班）的学号
    known = set(rows)
    orphan = len([sid for sid in per
                  if sid not in known and (per[sid].get(section) or {})])

    # ① KPI
    avgs = [p['avg'] for p in people]
    kpi = {
        'roster': roster, 'scored': scored,
        'avg': _avg(avgs),
        'max': round(max(avgs), 1) if avgs else None,
        'min': round(min(avgs), 1) if avgs else None,
        'pass_rate': round(100 * sum(1 for v in avgs if v >= 60) / scored, 1) if scored else None,
        'excellent_rate': round(100 * sum(1 for v in avgs if v >= 85) / scored, 1) if scored else None,
        'avg_cases': _avg([p['cases'] for p in people]),
        'best': {'avg': _avg([p['best'] for p in people])},     # 各人最高那一例 → 参考
    }

    # ② 分数段分布（按个人平均分）
    dist = []
    for label, color in BUCKETS:
        n = (max(0, len(working) - scored) if label == '未完成'
             else sum(1 for p in people if _bucket(p['avg']) == label))
        dist.append({'label': label, 'color': color, 'n': n})

    # ⑤ 练习曲线：第 N 次作答的全班均分（含自我选择偏差，前端必须标 n）
    by_idx = {}
    for p in people:
        for i, v in enumerate(p['order'], 1):
            by_idx.setdefault(i, []).append(v)
    curve = [{'i': i, 'avg': _avg(by_idx[i]), 'n': len(by_idx[i])} for i in sorted(by_idx)]

    # ③ 薄弱病例排行
    by_case = {}
    for p in people:
        for cid, v in p['cases_map'].items():
            by_case.setdefault(cid, []).append(v)
    ranked, skipped = [], 0
    for cid, vs in by_case.items():
        if len(vs) < MIN_CASES:
            skipped += 1
            continue
        md = meta.get(cid) or {}
        ranked.append({'key': cid, 'name': md.get('brief') or cid, 'subject': md.get('subject') or '',
                       'avg': _avg(vs), 'loss': round(100 - _avg(vs), 1), 'n': len(vs)})
    ranked.sort(key=lambda x: x['avg'])
    strong = sorted(ranked, key=lambda x: -x['avg'])[:3]

    # ④ 病例分析专属：按科目（复用 analysis_subjects 口径，不另立）
    #    选了具体科目时这张表就多余了，不返回
    subjects = []
    if section == 'analysis' and not subject:
        agg = {}
        for p in people:
            st = analysis_subjects.subject_stats((per.get(p['sid']) or {}).get('analysis'))
            for s, v in st.items():
                a = agg.setdefault(s, {'done_students': 0, 'done_sum': 0, 'finals': [], 'threshold': v['threshold']})
                a['done_students'] += 1
                a['done_sum'] += v['done']
                a['finals'].append(v['final'])
        for s in analysis_subjects.SUBJECT_ORDER + [k for k in agg if k not in analysis_subjects.SUBJECT_ORDER]:
            if s not in agg:
                if s in analysis_subjects.SUBJECT_ORDER:
                    subjects.append({'name': s, 'done_students': 0, 'avg_done': None,
                                     'avg_final': None,
                                     'threshold': analysis_subjects.threshold_of(s)})
                continue
            a = agg[s]
            subjects.append({'name': s, 'done_students': a['done_students'],
                             'avg_done': round(a['done_sum'] / a['done_students'], 1),
                             'avg_final': _avg(a['finals']), 'threshold': a['threshold']})

    subj_tag = (' · ' + subject) if subject else ''
    bank = _bank_by_subject(section)
    note = None
    if scored == 0:
        note = '本班暂无「%s%s」的作答记录' % (SECTION_NAME[section], subj_tag)
        bn = bank.get(subject) if subject else sum(bank.values())
        if bn:
            note += '（该科目题库有 %d 例，学生还没做过）' % bn
        note += '。'
    elif scored < SMALL_SAMPLE:
        note = '本班仅 %d 人有「%s%s」成绩，样本偏小，结论仅供参考。' % (scored, SECTION_NAME[section], subj_tag)
    if orphan and not klass:                      # 全局统计，只在「全部班级」视角提示
        note = ((note + ' ') if note else '') + '另有 %d 个学号在成绩册里找不到，未计入。' % orphan

    return {
        'class': klass, 'classes': classes(),
        'sections': [{'key': k, 'name': n} for k, n in SECTIONS],
        'subject_options': subject_options,
        'section': section, 'section_name': SECTION_NAME[section],
        'subject': subject,
        'title': '%s · %s%s' % (SECTION_NAME[section], klass or '全部班级', subj_tag),
        'empty': scored == 0, 'sample_note': note,
        'kpi': kpi, 'dist': dist, 'curve': curve,
        'weak': {'mode': 'case', 'title': '薄弱病例（全班得分最低）',
                 'items': ranked, 'skipped': skipped, 'min_cases': MIN_CASES,
                 'strong': strong},
        'subjects': subjects,
    }


def classes():
    """看板班级下拉的取值。"""
    try:
        from students import list_classes
        return list_classes()
    except Exception:
        return []


if __name__ == '__main__':
    for sec, sname in SECTIONS:
        print('=' * 60)
        for kl in [''] + classes():
            d = board(kl, sec)
            k = d['kpi']
            print('%-22s %-6s 名册%-4s 有成绩%-4s 均分%-6s 及格率%-6s 人均例数%-5s 病例榜%d个(略过%d)' % (
                kl or '全部', sname, k['roster'], k['scored'], k['avg'],
                k['pass_rate'], k['avg_cases'],
                len(d['weak']['items']), d['weak']['skipped']))
    d = board('', 'history')
    print('\n练习曲线（第N次作答的全班均分）:',
          ' '.join('%d次:%s(n%d)' % (c['i'], c['avg'], c['n']) for c in d['curve']))
    print('\n病史采集·薄弱病例榜（最弱在前）:')
    for it in d['weak']['items']:
        print('  %-6s %-18s %-4s 均%-6s 失分%-6s n=%d' % (
            it['key'], it['name'], it['subject'], it['avg'], it['loss'], it['n']))
