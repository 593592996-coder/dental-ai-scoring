# -*- coding: utf-8 -*-
"""学生作答明细存储（教师后台画像/回看用）。

每次关键动作写一条事件到 attempts/{学号}.json：
  login / history_score / analysis_score / reasoning_score
只增不改，后台按学生聚合。分数仍由 training._save_score 另存汇总。
"""
import os
import json
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ATT_DIR = os.path.join(BASE, 'attempts')
os.makedirs(ATT_DIR, exist_ok=True)


def _safe(sid):
    return ''.join(ch for ch in str(sid) if ch.isalnum() or ch in '_-') or 'unknown'


def record(sid, name, klass, kind, case_id=None, **payload):
    """追加一条作答事件。"""
    if not sid:
        return
    path = os.path.join(ATT_DIR, _safe(sid) + '.json')
    data = {'student': {'sid': sid, 'name': name, 'class': klass}, 'events': []}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            pass
    # 更新最新身份信息（以最后一次登录为准）
    data['student'] = {'sid': sid, 'name': name or data['student'].get('name', ''),
                       'class': klass or data['student'].get('class', '')}
    data['events'].append({
        'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'kind': kind, 'case': case_id, **payload,
    })
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_student(sid):
    path = os.path.join(ATT_DIR, _safe(sid) + '.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def load_all():
    """返回 [(sid, data), ...]。"""
    out = []
    if not os.path.isdir(ATT_DIR):
        return out
    for fn in sorted(os.listdir(ATT_DIR)):
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(ATT_DIR, fn), encoding='utf-8') as f:
                data = json.load(f)
            out.append((fn[:-5], data))
        except Exception:
            continue
    return out
