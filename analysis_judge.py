# -*- coding: utf-8 -*-
"""病例分析 AI 语义判分 —— glm-5.3-flash 逐条「按意思」判定，关键词命中保留作双保险。

设计原则（保险丝与 llm_patient 一致）：
1. 未配置/无 key/熔断冷却/超时/解析失败 → 一律返回 None，调用方退回纯关键词判分，绝不卡提交；
2. AI 只能「救回」关键词漏判（与关键词命中做或合并），不能推翻关键词已判对的；
   诊断分同理：规则已给 24/30 的不动，其余与 AI 语义分取高、封顶 24；
3. 每次调用留痕 consult_logs/analysis_judge.jsonl（模型/耗时/token/判定结果），供教师抽查。

配置复用项目根 llm_config.json（与病史采集患者兜底共用一套，切智谱即整体生效）：
  {"enabled": true, "base_url": "https://open.bigmodel.cn/api/paas/v4",
   "api_key": "...", "model": "glm-5.3-flash"}
"""
import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, 'llm_config.json')
_TRACE_PATH = os.path.join(_BASE_DIR, 'consult_logs', 'analysis_judge.jsonl')

_TIMEOUT = 40         # 秒。实测 glm-5.3-flash 判一题要 7-20s，偶发 20s+；原本 20s 太紧，
                      # 超时即悄悄退回更严的关键词判分 → 学生写对了也白丢分且无感知，故放宽。
_RETRY = 1            # 5xx 瞬断重试一次（同 llm_patient 实测经验）
_RETRY_DELAY = 0.25

# 熔断器：连续失败 3 次暂停 60 秒，期间直接走关键词判分
_FAIL_LIMIT = 3
_COOLDOWN = 60
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
    cfg = {'enabled': True, 'base_url': '', 'api_key': '', 'model': ''}
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
    return bool(cfg.get('enabled', True) and cfg.get('api_key') and cfg.get('base_url'))


def _trace(case_id, model, ok, note, result=None, usage=None, latency=0.0):
    try:
        os.makedirs(os.path.dirname(_TRACE_PATH), exist_ok=True)
        rec = {'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
               'case_id': case_id, 'model': model, 'ok': ok, 'note': note,
               'latency': round(latency, 1)}
        if usage:
            rec['in_tokens'] = usage.get('prompt_tokens')
            rec['out_tokens'] = usage.get('completion_tokens')
        if result:
            rec['ai_diag'] = result.get('diagnosis_score')
            rec['hits'] = {k: sum(1 for x in (result.get(k) or []) if x.get('hit'))
                           for k in ('basis', 'differential', 'treatment')}
        with open(_TRACE_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass


_SYSTEM = (
    '你是口腔执业医师考试的阅卷专家，正在给「病例分析」题的学生答卷逐条判分。\n'
    '只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。\n'
)

_PROMPT_TMPL = """【病例材料】
{material}

【标准答案】
正确诊断：{diag}
其他可接受的诊断写法：{accept}

【学生答案】
诊断：{s_diag}
诊断依据：{s_basis}
鉴别诊断：{s_diff}
治疗设计：{s_treat}

请逐条判分（按意思判，学生换说法/口语化只要意思覆盖即算写到）：

1. diagnosis_score：学生诊断与正确诊断的语义接近度打分（0-24 整数）。
   完全等同或仅措辞/牙位写法差异=24；同病但缺要素（牙位、急慢性、分型）=14-20；
   相关但是另一种病=6-12；完全不符或胡乱拼凑=0。并给 diagnosis_reason（不超过16字）。

2. basis：对下面每条「诊断依据」，判断学生依据文字是否覆盖该条意思。
3. differential：对下面每条「需鉴别的病」，判断学生是否实际做了该鉴别
   （提到该病且能给出区分要点才算；仅罗列病名没有要点不算）。
4. treatment：对下面每条「治疗」，判断学生治疗设计是否覆盖该条意思。

依据条目（共{n_basis}条）：
{basis_list}

鉴别条目（共{n_diff}条）：
{diff_list}

治疗条目（共{n_treat}条）：
{treat_list}

输出 JSON（数组长度必须与上面条数一致、顺序一致）：
{{"diagnosis_score": 0, "diagnosis_reason": "…",
  "basis": [{{"hit": true, "comment": "≤14字点评"}}],
  "differential": [{{"hit": false, "comment": "…"}}],
  "treatment": [{{"hit": true, "comment": "…"}}]}}"""


def _build_prompt(a, ans):
    basis_list = '\n'.join('%d. %s' % (i + 1, bp['text']) for i, bp in enumerate(a.get('basis_points', [])))
    diff_list = '\n'.join('%d. %s——区分要点：%s' % (i + 1, dp['name'], dp.get('point', ''))
                          for i, dp in enumerate(a.get('differential_exam', [])))
    treat_list = '\n'.join('%d. %s' % (i + 1, tp['text']) for i, tp in enumerate(a.get('treatment_points', [])))
    return _PROMPT_TMPL.format(
        material=a.get('material', '').strip(),
        diag=a.get('diagnosis', ''),
        accept='、'.join(a.get('acceptable_diag', []) or []) or '（无）',
        s_diag=ans.get('diagnosis') or '（未作答）',
        s_basis=ans.get('basis') or '（未作答）',
        s_diff=ans.get('differential') or '（未作答）',
        s_treat=ans.get('treatment') or '（未作答）',
        n_basis=len(a.get('basis_points', [])),
        n_diff=len(a.get('differential_exam', [])),
        n_treat=len(a.get('treatment_points', [])),
        basis_list=basis_list or '（无）', diff_list=diff_list or '（无）', treat_list=treat_list or '（无）')


def _parse(txt):
    txt = txt.strip()
    txt = txt[txt.find('{'):txt.rfind('}') + 1]
    return json.loads(txt)


def _normalize(data, a):
    """长度对齐 + 字段清洗；任何不对齐的数组整段弃用（退回关键词判分）。"""
    out = {}
    for key, rows in (('basis', a.get('basis_points', [])),
                      ('differential', a.get('differential_exam', [])),
                      ('treatment', a.get('treatment_points', []))):
        arr = data.get(key)
        if isinstance(arr, list) and len(arr) == len(rows):
            out[key] = [{'hit': bool(x.get('hit')),
                         'comment': str(x.get('comment') or '')[:20]} for x in arr if isinstance(x, dict)]
            if len(out[key]) != len(rows):        # 混进了非 dict 项
                out.pop(key)
        else:
            out[key] = None
    try:
        out['diagnosis_score'] = max(0, min(24, int(data.get('diagnosis_score') or 0)))
    except Exception:
        out['diagnosis_score'] = 0
    out['diagnosis_reason'] = str(data.get('diagnosis_reason') or '')[:20]
    return out


def judge(case_id, a, answers):
    """a=病例 analysis 底牌；answers={diagnosis,basis,differential,treatment}。
    返回 {'diagnosis_score','diagnosis_reason','basis','differential','treatment',[...]} 或 None。"""
    if not is_enabled():
        return None
    if not _cb_allow():
        return None
    cfg = _load_config()
    body = json.dumps({'model': cfg['model'],
                       'messages': [{'role': 'system', 'content': _SYSTEM},
                                    {'role': 'user', 'content': _build_prompt(a, answers)}],
                       'temperature': 0.1, 'max_tokens': 3000}).encode('utf-8')
    url = cfg['base_url'].rstrip('/') + '/chat/completions'
    t0 = time.time()
    note = ''
    for attempt in range(_RETRY + 1):
        req = urllib.request.Request(url, data=body, headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg['api_key']})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            txt = (data['choices'][0]['message']['content'] or '').strip()
            if not txt:
                _trace(case_id, cfg['model'], False, '空回答', latency=time.time() - t0)
                return None
            result = _normalize(_parse(txt), a)
            _cb_record(True)
            note = '%.1fs' % (time.time() - t0)
            if attempt:
                note += '(重试成)'
            _trace(case_id, cfg['model'], True, note, result=result,
                   usage=data.get('usage'), latency=time.time() - t0)
            result['model'] = cfg['model']
            return result
        except urllib.error.HTTPError as e:
            note = 'HTTP %d' % e.code
            if e.code < 500 or attempt >= _RETRY:
                break
            time.sleep(_RETRY_DELAY)
        except Exception as e:
            note = str(e)[:50]
            break
    _cb_record(False)
    _trace(case_id, cfg.get('model'), False, note, latency=time.time() - t0)
    return None
