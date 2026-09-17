# -*- coding: utf-8 -*-
"""大模型「模拟患者」兜底 —— 规则匹配答不上时，由 LLM 拿病例事实底牌扮演患者回答。

设计原则：
1. 只用病例底牌里的事实，不许编造；底牌没有就说「没注意/不晓得」。
2. 患者身份：不说诊断名、不给治疗/用药建议（防泄漏答案）。
3. 超时/无 key/任何报错都返回 None，由调用方退回规则或中性兜底，绝不阻塞课堂。
4. 相似问法本地缓存（省钱、提速）；每次回答留痕供教师抽查。

配置：项目根目录 llm_config.json
  {"enabled": true, "base_url": "https://api.deepseek.com", "api_key": "sk-xxx",
   "model": "deepseek-chat"}
也可用环境变量 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 覆盖。
"""
import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, 'llm_config.json')
_LOG_DIR = os.path.join(_BASE_DIR, 'consult_logs')
_CACHE_PATH = os.path.join(_LOG_DIR, 'llm_cache.json')
_TRACE_PATH = os.path.join(_LOG_DIR, 'llm_answers.jsonl')

_TIMEOUT = 6          # 秒；大模型回答再慢也不能拖死课堂
_CACHE_QMAX = 24      # 归一化问题取前若干字做缓存键

# 熔断器：连续失败 _FAIL_LIMIT 次后，暂停调用 AI _COOLDOWN 秒（期间立即走规则兜底，
# 学生不用干等超时），冷却后只试一次，成功则恢复。防止断网/欠费时全班卡顿。
_FAIL_LIMIT = 3
_COOLDOWN = 120
_CB = {'fails': 0, 'open_until': 0.0}


def _cb_allow():
    return time.time() >= _CB['open_until']


def _cb_record(ok):
    if ok:
        _CB['fails'] = 0
        _CB['open_until'] = 0.0
    else:
        _CB['fails'] += 1
        if _CB['fails'] >= _FAIL_LIMIT:
            _CB['open_until'] = time.time() + _COOLDOWN


def _load_config():
    cfg = {'enabled': True, 'base_url': 'https://api.deepseek.com',
           'api_key': '', 'model': 'deepseek-chat'}
    try:
        with open(_CONFIG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    cfg['api_key'] = os.environ.get('LLM_API_KEY', cfg.get('api_key', ''))
    cfg['base_url'] = os.environ.get('LLM_BASE_URL', cfg.get('base_url', ''))
    cfg['model'] = os.environ.get('LLM_MODEL', cfg.get('model', ''))
    return cfg


def is_enabled():
    cfg = _load_config()
    return bool(cfg.get('enabled', True) and cfg.get('api_key'))


def _build_brief(case_data):
    """从病例数据提炼「患者视角事实清单」（不含诊断/治疗，防止模型泄漏答案）。"""
    p = case_data.get('patient', {}) or {}
    lines = [f"主诉：{case_data.get('chief_complaint', '').strip()}"]
    who = f"{p.get('gender', '')}性，{p.get('age', '')}岁"
    if p.get('occupation'):
        who += f"，{p['occupation']}"
    lines.append('基本情况：' + who)
    facts = []
    seen = set()
    for ans in (case_data.get('conversation', {}) or {}).values():
        a = ' '.join(str(ans).split())
        if a and a not in seen:
            seen.add(a)
            facts.append(a)
    if facts:
        lines.append('已知病情（你回答时只能在这些事实范围内）：\n' +
                     '\n'.join(f'- {a}' for a in facts))
    return '\n'.join(lines)


_SYSTEM = (
    '你正在口腔临床教学系统里扮演一位来看牙的普通患者，正在回答实习医生的问诊。\n'
    '【病情事实】\n{brief}\n\n'
    '铁律：\n'
    '1. 只能依据上面事实回答，不许编造病情、症状、用药、检查结果；事实没提到的，就说"这个我没在意/不晓得"。\n'
    '2. 你是患者、不是医生：不能说出任何诊断名称（如牙髓炎、根尖周炎、隐裂等），不做鉴别，不给治疗或用药建议。'
    '医生问"我是什么病/该怎么治/要不要根管"时，回答"我也不懂，就靠医生你帮我看了"。\n'
    '3. 口语、简短（1-2句、一般不超过40字），可带云南口语（如"老火""牙花子""不晓得""咋个"），像真人聊天，不要书面罗列。\n'
    '4. 直接回答医生当前这一句，顺着已有的对话，不要重复寒暄、不要反问一大串。'
)


def _cache_key(case_id, q):
    return case_id + '|' + ''.join(q.split())[:_CACHE_QMAX]


def _load_cache():
    try:
        with open(_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _trace(case_id, q, answer, model, ok, note=''):
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_TRACE_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'case_id': case_id, 'q': q, 'a': answer,
                                'model': model, 'ok': ok, 'note': note},
                               ensure_ascii=False) + '\n')
    except Exception:
        pass


def answer(case_id, case_data, q, recent=None):
    """规则答不上时调用。返回患者回答字符串；未启用/失败/超时返回 None。"""
    if not is_enabled():
        return None
    cfg = _load_config()
    q = (q or '').strip()
    if not q:
        return None

    if not _cb_allow():
        return None                  # 熔断冷却中：立即走规则兜底，不干等
    cache = _load_cache()
    key = _cache_key(case_id, q)
    if key in cache:
        return cache[key]

    messages = [{'role': 'system', 'content': _SYSTEM.format(brief=_build_brief(case_data))}]
    for turn in (recent or [])[-4:]:
        if turn.get('student'):
            messages.append({'role': 'user', 'content': turn['student']})
        if turn.get('patient'):
            messages.append({'role': 'assistant', 'content': turn['patient']})
    messages.append({'role': 'user', 'content': q})

    url = cfg['base_url'].rstrip('/') + '/chat/completions'
    body = json.dumps({'model': cfg['model'], 'messages': messages,
                       'temperature': 0.7, 'max_tokens': 120}).encode('utf-8')
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/json',
                 'Authorization': 'Bearer ' + cfg['api_key']})
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        reply = data['choices'][0]['message']['content'].strip()
        if not reply:
            _trace(case_id, q, '', cfg['model'], False, '空回答')
            return None
        cache[key] = reply
        if len(cache) > 2000:
            cache = dict(list(cache.items())[-2000:])
        _save_cache(cache)
        _cb_record(True)
        _trace(case_id, q, reply, cfg['model'], True, f'{time.time()-t0:.1f}s')
        return reply
    except urllib.error.HTTPError as e:
        _cb_record(False)
        _trace(case_id, q, '', cfg['model'], False, f'HTTP {e.code}')
        return None
    except Exception as e:
        _cb_record(False)
        _trace(case_id, q, '', cfg['model'], False, type(e).__name__)
        return None
