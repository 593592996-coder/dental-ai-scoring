# -*- coding: utf-8 -*-
"""开髓术照片【分诊】工具 —— 只做筛分，不判分。

定位（2026-10-11 定）：
    「髓室顶去净」这一维**不交给 AI 自动判分**。实测七种办法（找牙/找洞/框定位/
    宽度比/红色面积/提示词调优/few-shot）都无法稳定对上老师的判断，且结论随提示词
    倾向翻来覆去（范例偏正例→71%判"揭干净"；范例偏反例→几乎全判"未揭"）。
    ⇒ 结论：模型不是在"测量"，是在顺着提示词走。

    能做且已验证可靠的是【分诊】——认出：
      🔧 有锉照（插了K锉）    → 不能判髓室顶（只能说明根管找到了）
      🚫 非本次作业           → 邻面II类洞/X光片等，与本次无关
      ❓ 看不清               → 没拍到牙体/过糊
      👁 待老师判             → 交给老师看图判定（拼成对照表）

用法：
    python3 endo_triage.py manifest.csv   # manifest 每行: 标签,图片路径
输出：
    ~/Downloads/开髓_分诊_第N批.jpg   （👁类的拼图，老师对着圈）
    ~/Downloads/开髓_分诊_清单.md     （各类名单）
"""
import os
import sys
import csv
import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vision_endo as V   # 复用编码/配置/熔断/留痕

TRIAGE_TO = {'system': V.SYSTEM_PROMPT, 'user': '''这是一张开髓术实验课的学生提交照片。请只做**分类**，不要评分。

判断三件事：
1) tooth_visible：照片里能否看清"牙"（牙体本身）。没拍到牙 / 是X光片 / 糊到看不清 → false
2) kfile_visible：牙上或根管口里**是否插了K锉**（根管器械）。插了 → true
   （老师规则：插了锉的照片挡住所见，不能判髓室顶，只能说明"根管找到了"）
3) photo_type：这张照片属于 —— "开髓"（牙冠上的开髓洞）/ "其他洞型"（邻面II类洞等，
   与开髓无关）/ "X光片" / "其他"

严格按此 JSON 输出（只要这三个字段，键名英文）：
{"tooth_visible": true, "kfile_visible": false, "photo_type": "开髓", "evidence": "一句话依据"}'''}

CACHE = '/tmp/endo_triage_cache.json'


def _load_cache():
    try:
        return json.load(open(CACHE, encoding='utf-8'))
    except Exception:
        return {}


def _save_cache(c):
    try:
        json.dump(c, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception:
        pass


def triage_one(path):
    """单张分诊。返回 {'tooth_visible','kfile_visible','photo_type','evidence'} 或 None。"""
    cfg = V._load_config()
    if not (cfg.get('enabled') and cfg.get('api_key') and cfg.get('model')):
        return None
    if not V._cb_allow():
        return None
    uri = V._encode_image(path, int(cfg.get('max_image_side', 1280)))
    if uri is None:
        return None
    body = {'model': cfg['model'],
            'messages': [{'role': 'system', 'content': TRIAGE_TO['system']},
                         {'role': 'user', 'content': [
                             {'type': 'text', 'text': TRIAGE_TO['user']},
                             {'type': 'image_url', 'image_url': {'url': uri}}]}],
            'temperature': 0, 'thinking': {'type': 'disabled'}}
    url = cfg['base_url'].rstrip('/') + '/chat/completions'
    for _ in range(2):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                                         headers={'Content-Type': 'application/json',
                                                  'Authorization': 'Bearer ' + cfg['api_key']})
            with urllib.request.urlopen(req, timeout=int(cfg.get('timeout', 45))) as r:
                d = json.loads(r.read().decode('utf-8'))
            js = V._extract_json(d['choices'][0]['message'].get('content', ''))
            if not isinstance(js, dict):
                continue
            V._cb_record(True)
            return {'tooth_visible': bool(js.get('tooth_visible')),
                    'kfile_visible': bool(js.get('kfile_visible')),
                    'photo_type': str(js.get('photo_type') or '')[:12],
                    'evidence': str(js.get('evidence') or '')[:120]}
        except Exception:
            time.sleep(0.5)
    V._cb_record(False)
    return None


def classify(r):
    """分诊结果 → 归类标签。"""
    if r is None:
        return 'ERR'
    if not r['tooth_visible']:
        return 'BLUR'          # ❓ 看不清
    pt = r['photo_type'] or ''
    if pt and '开髓' not in pt:
        return 'WRONG'         # 🚫 非本次作业
    if r['kfile_visible']:
        return 'KFILE'         # 🔧 有锉
    return 'EYE'               # 👁 待老师判


LABELS = {'KFILE': '🔧 有锉（不可判髓室顶，只能说明根管找到了）',
          'WRONG': '🚫 非本次作业（邻面洞/X光片等）',
          'BLUR': '❓ 看不清（未拍到牙体/过糊）',
          'EYE': '👁 待老师判（需你看图圈定）',
          'ERR': '⚠️ 调用失败（未分类）'}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    rows = [r for r in csv.reader(open(sys.argv[1], encoding='utf-8')) if r]
    cache = _load_cache()
    print(f'待分诊 {len(rows)} 张…')

    def work(item):
        label, path = item[0], item[1]
        key = os.path.basename(path)
        if key not in cache:
            cache[key] = triage_one(path)
        return label, path, cache[key]

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(work, rows))
    _save_cache(cache)

    from collections import defaultdict
    buckets = defaultdict(list)
    for label, path, r in results:
        buckets[classify(r)].append((label, path, r))

    for k in ('EYE', 'KFILE', 'WRONG', 'BLUR', 'ERR'):
        print(f'{LABELS[k]}: {len(buckets[k])} 张')
    json.dump({k: [(l, p, r) for l, p, r in v] for k, v in buckets.items()},
              open('/tmp/endo_triage_result.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print('明细已存 /tmp/endo_triage_result.json')
