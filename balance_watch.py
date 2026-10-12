# -*- coding: utf-8 -*-
"""DeepSeek 余额监控：低于阈值时推飞书。

用法：由 cron 每天调一次  python3 balance_watch.py
配置（二者取一，文件优先）：
  - llama 项目根目录 feishu_webhook.txt（一行，飞书自定义机器人地址；勿入库）
  - 环境变量 FEISHU_WEBHOOK
阈值：低于 20 元先提醒；低于 10 元再加急。
防骚扰：同一档位每天最多推一次；余额回升到 20 元以上则静音，等下次再降下来才重新提醒。
"""
import os
import json
import sys
import urllib.request
from datetime import datetime

import llm_usage

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_BASE_DIR, 'consult_logs', 'balance_state.json')
_WEBHOOK_FILE = os.path.join(_BASE_DIR, 'feishu_webhook.txt')

WARN = 20.0      # 低于此先提醒
URGENT = 10.0    # 低于此加急
COST_PER_CALL = 0.0006   # 元/次（实测 222 in + 22 out；仅供估算剩余次数）

TOP_UP = 'https://platform.deepseek.com/top_up'


def _webhook():
    if os.path.exists(_WEBHOOK_FILE):
        try:
            u = open(_WEBHOOK_FILE, encoding='utf-8').read().strip()
            if u:
                return u
        except Exception:
            pass
    return os.environ.get('FEISHU_WEBHOOK', '').strip()


def _load_state():
    try:
        with open(_STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        with open(_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _level(bal):
    if bal < URGENT:
        return 'urgent'
    if bal < WARN:
        return 'warn'
    return 'ok'


def _send(url, text):
    body = json.dumps({'msg_type': 'text', 'content': {'text': text}}).encode('utf-8')
    req = urllib.request.Request(url, data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def _message(bal, lv):
    calls = int(bal / COST_PER_CALL)
    head = '🚨【加急】' if lv == 'urgent' else '⚠️'
    tip = ('余额快见底了，建议今天就去充值，'
           '否则学生问诊会退回规则回答。' if lv == 'urgent'
           else '余额偏低了，方便时充一下就行，还没到影响上课的地步。')
    return (f'{head} 口腔训练平台 · 大模型余额提醒\n'
            f'DeepSeek 余额：{bal:.2f} 元\n'
            f'粗算还剩约 {calls:,} 次问诊\n'
            f'{tip}\n'
            f'充值：{TOP_UP}\n'
            f'（查于 {datetime.now().strftime("%Y-%m-%d %H:%M")}）')


def main(argv=None):
    dry = '--dry' in (argv or sys.argv)      # --dry：只打印不推送
    r = llm_usage.balance()
    if not r.get('ok'):
        print('[balance_watch] 查询失败：', r.get('error'))
        return 1
    bal = r['total_balance']
    lv = _level(bal)
    today = datetime.now().strftime('%Y-%m-%d')
    st = _load_state()
    prev_lv = st.get('level', 'ok')
    last_alert = st.get('last_alert', '')

    # 该不该推：档位升级了，或 已处于 warn/urgent 且今天还没推过
    need = (lv != prev_lv and lv != 'ok') or (lv in ('warn', 'urgent') and last_alert != today)

    msg = _message(bal, lv)
    if lv == 'ok':
        print(f'[balance_watch] 余额 {bal:.2f} 元，正常')
    else:
        print(f'[balance_watch] 余额 {bal:.2f} 元，档位={lv}，{"需推送" if need else "今日已推过，跳过"}')
        print(msg)

    if need and not dry:
        url = _webhook()
        if not url:
            print('[balance_watch] ⚠️ 未配置飞书 webhook（feishu_webhook.txt 或 FEISHU_WEBHOOK），本次不推送')
        else:
            try:
                res = _send(url, msg)
                ok = res.get('code') == 0 or res.get('StatusCode') == 0
                print('[balance_watch] 飞书推送', '成功' if ok else f'返回异常：{res}')
                if ok:
                    last_alert = today
            except Exception as e:
                print('[balance_watch] 推送失败：', type(e).__name__, str(e)[:120])

    _save_state({'balance': bal, 'level': lv, 'last_alert': last_alert,
                 'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    return 0


if __name__ == '__main__':
    sys.exit(main())
