# -*- coding: utf-8 -*-
"""成绩校正：把 scores/<学号>.json 里各板块的分，从「最后一次提交」修正为「历次最高」。

背景：_save_score 原来直接覆盖（sec[case]=score），学生重交考差会掉分；
与「历次提交取最高、只升不降」的既定口径不符（2026-10-15 已修代码）。
本脚本按 attempts/<学号>.json 的完整事件历史重算，把历史数据一并拉齐。

原则：
  - **只升不降**：低于现有值的一律不动（防误伤迁移/手工数据）
  - 只处理 history / analysis / reasoning 三板块；不写 tries（老提交不计入限次）

用法：
  python3 fix_best_score.py              # 预览，不改任何文件
  python3 fix_best_score.py --apply      # 实际写入（原地更新 scores/*.json）
  python3 fix_best_score.py --dir /opt/aiscore --apply
"""
import os
import re
import sys
import json
import glob
import shutil
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))

# 事件 kind → 成绩文件里的板块 key
KIND_SECTION = {'history_score': 'history',
                'analysis_score': 'analysis',
                'reasoning_score': 'reasoning'}


def _safe(sid):
    return ''.join(ch for ch in str(sid) if ch.isalnum() or ch in '_-') or 'unknown'


def collect_best(attempts_dir):
    """{学号: {板块: {病例号: 该例最高分}}}"""
    out = {}
    for p in glob.glob(os.path.join(attempts_dir, '*.json')):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            continue
        sid = (d.get('student') or {}).get('sid') or os.path.basename(p)[:-5]
        best = {}
        for e in d.get('events', []):
            sec = KIND_SECTION.get(e.get('kind'))
            if not sec:
                continue
            sc = e.get('score')
            if not isinstance(sc, (int, float)):
                continue
            case = e.get('case')
            if not case:
                continue
            slot = best.setdefault(sec, {})
            slot[case] = max(slot.get(case, float('-inf')), sc)
        if best:
            out[sid] = best
    return out


def run(score_dir, attempts_dir, apply_):
    best = collect_best(attempts_dir)
    changes = []
    touched = 0
    for f in sorted(glob.glob(os.path.join(score_dir, '*.json'))):
        try:
            with open(f, encoding='utf-8') as fh:
                rec = json.load(fh)
        except Exception:
            continue
        sid = rec.get('student_number') or os.path.basename(f)[:-5]
        want = best.get(sid)
        if not want:
            continue
        secs = rec.get('sections') or {}
        dirty = False
        for sec, cases in want.items():
            cur = secs.get(sec)
            if not isinstance(cur, dict):
                continue
            for case, mx in cases.items():
                old = cur.get(case)
                if not isinstance(old, (int, float)):
                    continue                 # 库里没有的不补（避免凭空造分）
                if mx > old + 0.5:           # 只升不降
                    changes.append((sid, rec.get('name', ''), sec, case,
                                    round(float(old), 1), round(float(mx), 1)))
                    if apply_:
                        cur[case] = round(float(mx), 1)
                        dirty = True
        if dirty:
            rec['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if apply_:
                shutil.copy2(f, f + '.bak_bestfix')     # 原文件备份一次
                tmp = f + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as fh:
                    json.dump(rec, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, f)
            touched += 1

    mode = '已写入' if apply_ else '预览（未改动任何文件）'
    print(f'=== {mode} ===')
    print(f'涉及成绩文件：{touched} 个；需要上调的（人,例）：{len(changes)} 条')
    by_sec = {}
    for c in changes:
        by_sec[c[2]] = by_sec.get(c[2], 0) + 1
    print('按板块：', by_sec or '无')
    for c in changes[:40]:
        print(f'  {c[0]} {c[1]:<6s} {c[2]:<10s} {c[3]:<9s} {c[4]:6.1f} → {c[5]:6.1f}')
    if len(changes) > 40:
        print(f'  …… 其余 {len(changes) - 40} 条略')
    if not apply_ and changes:
        print('\n确认无误后加 --apply 实际写入（原文件会存一份 .bak_bestfix 备份）')


if __name__ == '__main__':
    args = sys.argv[1:]
    apply_ = '--apply' in args
    target = BASE
    if '--dir' in args:
        target = args[args.index('--dir') + 1]
    run(os.path.join(target, 'scores'), os.path.join(target, 'attempts'), apply_)
