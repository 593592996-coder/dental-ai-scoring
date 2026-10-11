# -*- coding: utf-8 -*-
"""大模型用量：在线余额 + 本地调用台账。

- balance(): 实时查 DeepSeek /user/balance（剩多少钱）
- stats():   聚合 consult_logs/llm_answers.jsonl（调用次数/按天/按病例/token/估算花费）

费率说明：DeepSeek 的单价会调整，所以不写死在代码里。可在 llm_config.json 加
  "price_in": 2.0, "price_out": 8.0     # 元/百万 token
不填则用下面的默认值。仅作估算，以 DeepSeek 账单为准。
"""
import os
import json
import urllib.request
from datetime import datetime, timedelta

import llm_patient

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_BASE_DIR, 'consult_logs')
_TRACE_PATH = os.path.join(_LOG_DIR, 'llm_answers.jsonl')
_CACHE_PATH = os.path.join(_LOG_DIR, 'llm_cache.json')

# 默认费率（元/百万 token），仅估算用 —— 以 DeepSeek 官方账单为准
_DEF_PRICE_IN = 2.0
_DEF_PRICE_OUT = 8.0


def _cfg():
    try:
        with open(os.path.join(_BASE_DIR, 'llm_config.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def balance():
    """实时查 DeepSeek 余额。返回 dict；失败返回 {'ok': False, 'error': ...}。"""
    cfg = llm_patient._load_config()
    if not cfg.get('api_key'):
        return {'ok': False, 'error': '未配置 api_key'}
    url = cfg['base_url'].rstrip('/') + '/user/balance'
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + cfg['api_key']})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        infos = data.get('balance_infos') or []
        cny = next((i for i in infos if i.get('currency') == 'CNY'), infos[0] if infos else {})
        return {'ok': True,
                'is_available': data.get('is_available'),
                'currency': cny.get('currency', 'CNY'),
                'total_balance': float(cny.get('total_balance', 0) or 0),
                'topped_up': float(cny.get('topped_up_balance', 0) or 0),
                'granted': float(cny.get('granted_balance', 0) or 0)}
    except Exception as e:
        return {'ok': False, 'error': type(e).__name__ + ': ' + str(e)[:120]}


def _read_trace():
    """逐行读留痕；坏行跳过（日志只增不减，容错优先）。"""
    rows = []
    if not os.path.exists(_TRACE_PATH):
        return rows
    try:
        with open(_TRACE_PATH, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return rows


def stats():
    rows = _read_trace()
    cfg = _cfg()
    p_in = float(cfg.get('price_in', _DEF_PRICE_IN) or _DEF_PRICE_IN)
    p_out = float(cfg.get('price_out', _DEF_PRICE_OUT) or _DEF_PRICE_OUT)

    today = datetime.now().strftime('%Y-%m-%d')
    week_ago = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')

    total = len(rows)
    ok = sum(1 for r in rows if r.get('ok'))
    fail = total - ok
    today_n = sum(1 for r in rows if str(r.get('time', '')).startswith(today))
    week_n = sum(1 for r in rows if str(r.get('time', ''))[:10] >= week_ago)

    # 按天（近14天，含零的补齐以便画图）
    by_day = {}
    for r in rows:
        d = str(r.get('time', ''))[:10]
        if d:
            by_day[d] = by_day.get(d, 0) + 1
    days = []
    for i in range(13, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        days.append({'date': d, 'n': by_day.get(d, 0)})

    # 按病例
    by_case = {}
    for r in rows:
        c = r.get('case_id') or '?'
        by_case[c] = by_case.get(c, 0) + 1
    by_case = sorted(({'case': k, 'n': v} for k, v in by_case.items()),
                     key=lambda x: -x['n'])

    # 耗时（note 形如 "0.6s"）
    lat = []
    for r in rows:
        n = str(r.get('note', ''))
        if n.endswith('s'):
            try:
                lat.append(float(n[:-1]))
            except Exception:
                pass
    avg_lat = round(sum(lat) / len(lat), 2) if lat else None

    # token 与估算花费（老记录无 token 字段，只统计有的）
    tin = sum(int(r.get('in_tokens') or 0) for r in rows)
    tout = sum(int(r.get('out_tokens') or 0) for r in rows)
    tracked = sum(1 for r in rows if r.get('in_tokens') is not None)
    est_cost = round(tin / 1e6 * p_in + tout / 1e6 * p_out, 4) if tracked else None

    # 缓存
    try:
        with open(_CACHE_PATH, encoding='utf-8') as f:
            cache_n = len(json.load(f))
    except Exception:
        cache_n = 0

    return {'ok': True,
            'enabled': llm_patient.is_enabled(),
            'model': cfg.get('model', ''),
            'total': total, 'ok_n': ok, 'fail_n': fail,
            'today_n': today_n, 'week_n': week_n,
            'success_rate': round(ok / total * 100, 1) if total else None,
            'avg_lat': avg_lat,
            'days': days, 'by_case': by_case,
            'cache_n': cache_n,
            'in_tokens': tin, 'out_tokens': tout, 'tracked_n': tracked,
            'est_cost': est_cost, 'price_in': p_in, 'price_out': p_out,
            'first_time': rows[0].get('time') if rows else None,
            'last_time': rows[-1].get('time') if rows else None,
            }
