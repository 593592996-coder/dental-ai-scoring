# -*- coding: utf-8 -*-
"""账号禁用名单：banned.json 持久化（账号sid → 原因/时间）。
用于老师封掉非本机构、未实名的账号；成绩保留不删。"""
import os, json
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
_FILE = os.path.join(BASE, 'banned.json')


def _load():
    if not os.path.exists(_FILE):
        return {}
    try:
        return json.load(open(_FILE, encoding='utf-8'))
    except Exception:
        return {}


def _save(d):
    json.dump(d, open(_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def is_banned(sid):
    return bool(sid) and sid in _load()


def info(sid):
    return _load().get(sid)


def all_bans():
    return dict(_load())


def ban(sid, reason='', by=''):
    sid = str(sid or '').strip()
    if not sid:
        return False
    d = _load()
    d[sid] = {'reason': str(reason or '').strip(),
              'banned_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              'by': by}
    _save(d)
    return True


def unban(sid):
    d = _load()
    if sid in d:
        del d[sid]
        _save(d)
        return True
    return False
