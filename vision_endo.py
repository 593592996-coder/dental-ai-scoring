# -*- coding: utf-8 -*-
"""开髓术「髓室顶去净」—— 火山方舟视觉大模型判读

为什么需要它：
    纯 CV 判「髓室顶去净」在这批照片上不稳。根因有二：
      1) ROI 找错（课堂照片背景/手套/锉柄/手机翻拍 X 光片混在一起，规则法在
         "深色锉柄"和"真洞口"之间摇摆）；
      2) 判据方向反了（白树脂牙"洞外"极亮 → 只要开了个又小又深的口，
         深度就爆表 → 误判"已揭除✓"，小开口反而比大揭顶得分高）。
    视觉模型直接看图回答"洞口在哪 + 髓室顶是否完整"，并把洞口包围盒交回给
    CV 当 ROI 用，两个问题一起解决。

设计原则（照搬「磨法预备生」vision_client.py，已验证的那套）：
    1. OpenAI 兼容协议，标准库 urllib，不装 SDK。
    2. 未配置 key/model、超时、解析失败一律返回 None → 引擎回落 CV，绝不 500。
    3. 熔断（连 3 失败冷却 120s）+ 重试 + 留痕 vision_logs/vision_calls.jsonl。

配置 vision_config.json（勿提交仓库，见 .gitignore；云端用 ARK_API_KEY 环境变量）：
    {"enabled": true,
     "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",   # 必须带 /plan/，否则产生额外费用
     "api_key": "ark-xxxx", "model": "doubao-seed-2.1-pro"}
"""
import os
import re
import cv2
import json
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, 'vision_config.json')
_LOG_DIR = os.path.join(_BASE_DIR, 'vision_logs')

_FAIL_LIMIT = 3
_COOLDOWN = 120
_RETRIES = 2
_CB = {'fails': 0, 'open_until': 0.0}

# 髓室顶三档 → 得分（25 分制）。阈值可调，改这里即可。
ROOF_SCORE = {'完全揭除': 25.0, '部分残留': 14.0, '基本未揭': 6.0}
ROOF_STATUS_OK = tuple(ROOF_SCORE.keys())

SYSTEM_PROMPT = (
    '你是口腔内科实验课的资深带教老师，负责评判学生开髓术的「髓室顶去净」。'
    '必须只依据照片中真实可见的内容判断，看不清就说看不清，绝不猜测。'
    '只输出一个 JSON 对象，不要任何解释文字、不要 markdown 代码块。'
)

USER_PROMPT = '''这是一张开髓术的课堂照片，拍摄方式不统一（可能捏在手里、放在桌面、背景杂乱、也可能是插了K锉的洞底照）。请完成三件事：

1) 判断照片里能否看清"开髓洞口"（牙冠上被钻开的那个洞）。
   - 若牙体根本没入镜、或画面是 X 光片/别的物体、或糊到看不清 → tooth_visible=false。

1.5) 判断照片里**是否插了K锉**（或其他根管器械）在牙上/根管口内：插了就 kfile_visible=true。
   ⚠️ 老师规则：插了锉的照片**挡住所见**，只能说明"根管找到了"，
      **不能用来判断髓室顶有没有揭干净**。请务必如实判断这一项。
   ⚠️ 但第 3 步的 roof_status **无论如何都要给**（哪怕插了锉，也按你看到的最佳判断给三档之一，
      不要写"不可判/无法判断"）。

2) 给出两个外接矩形（归一化 [x, y, w, h]，左上角x、左上角y、宽、高，取值 0~1）：
   - tooth_box = 这颗牙**牙冠合面**（咬合面）的矩形
   - cavity_box = **开髓洞口**的矩形

3) 判断髓室顶状态，只能是这三个值之一（判据是"洞里有没有白色顶盖残留"，**不是洞口大小**）：
   - "完全揭除"：洞内能直接看到髓室壁与髓室底围成的腔体（比牙合面暗），
     **没有横跨/遮盖洞口的白色牙本质顶盖残留**，根管口可直视。
     ⚠️「洞口大小」**不是**判据——有的牙髓腔本来就小，小洞口同样可能是揭干净的。
   - "部分残留"：洞内仍有白色牙本质顶盖残留（横跨或遮盖部分洞口），
     或能看到一块白色顶板平台挡在洞口里。
   - "基本未揭"：只有一个小的穿入孔，**洞内看不到腔体**（既看不到髓室壁也看不到髓室底），
     周围合面完整。

3.5) 判断这张照片是不是**本次开髓作业**的照片：photo_type 填
   "开髓"（牙冠上的开髓洞）、或 "其他洞型"（如邻面II类洞、充填体等，与开髓无关）、
   或 "X光片"、或 "其他"。

严格按此 JSON 结构输出：
{"tooth_visible": true, "kfile_visible": false, "photo_type": "开髓", "tooth_box": [0.30, 0.25, 0.40, 0.45], "cavity_box": [0.38, 0.35, 0.20, 0.18], "roof_status": "完全揭除", "evidence": "一句话说明依据（看到的什么现象）", "uncertain": false}

说明：
- 两个 box 的四个数都必须是 0~1 之间的小数（相对画面宽高的比例），**不要填像素坐标**。
- tooth_visible=false 时，两个 box 都填 null、roof_status 填 null。
- 照片模糊、反光过强、角度太偏导致你无法有把握判断时，把 uncertain 设为 true。
- evidence 写你实际看到的东西（例如"洞口仅约牙冠1/4宽，洞底可见白色牙本质平台"）。'''


def _load_config():
    cfg = {'enabled': True,
           'base_url': 'https://ark.cn-beijing.volces.com/api/plan/v3',
           'api_key': '', 'model': '', 'timeout': 45,
           'temperature': 0.2, 'max_image_side': 1280}
    try:
        with open(_CONFIG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    cfg['api_key'] = os.environ.get('ARK_API_KEY', cfg.get('api_key', ''))
    env_model = os.environ.get('ARK_VISION_ENDPOINT')
    if env_model:
        cfg['model'] = env_model
    return cfg


def is_configured():
    cfg = _load_config()
    return bool(cfg.get('enabled') and cfg.get('api_key') and cfg.get('model'))


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


def _encode_image(path, max_side):
    """读图 → 压到长边≤max_side → JPEG base64 data URI。失败返回 None。"""
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)))
    ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        return None
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.tobytes()).decode('ascii')


def _trace(payload, ok, note=''):
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(os.path.join(_LOG_DIR, 'vision_calls.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'ok': ok, 'note': note, **payload}, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _extract_json(text):
    """从模型回复中截取 JSON 对象（容错 ```json 包裹/前后多余文字）。"""
    if not text:
        return None
    text = re.sub(r'```(?:json)?', '', text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _norm_status(s):
    """把模型的三档说法归一到标准值（容错"未完全揭除""已揭净""不可判"等自由发挥）。"""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t in ROOF_STATUS_OK:
        return t
    if '未完全' in t or '不完全' in t or '未彻底' in t:
        return '部分残留'
    if '基本未揭' in t or '基本完整' in t or '基本没' in t:
        return '基本未揭'
    if '完全' in t or '揭净' in t or '揭干净' in t or '已揭除' in t:
        return '完全揭除'
    if '部分' in t or '残留' in t:
        return '部分残留'
    if '未揭' in t or '没揭' in t or '未去除' in t:
        return '基本未揭'
    return None


def _validate(data):
    """校验并归一化模型返回。不合规返回 None（→ 回落 CV）。"""
    if not isinstance(data, dict):
        return None
    visible = bool(data.get('tooth_visible'))
    uncertain = bool(data.get('uncertain'))
    kfile = bool(data.get('kfile_visible'))
    status = _norm_status(data.get('roof_status'))

    def _box(v):
        if not isinstance(v, (list, tuple)) or len(v) != 4:
            return None
        try:
            vals = [float(x) for x in v]
        except (TypeError, ValueError):
            return None
        if not all(-0.02 <= x <= 1.02 for x in vals):
            return None
        if vals[2] <= 0.02 or vals[3] <= 0.02:
            return None
        return [max(0.0, min(1.0, vals[0])), max(0.0, min(1.0, vals[1])),
                max(0.0, min(1.0, vals[2])), max(0.0, min(1.0, vals[3]))]

    if not visible:
        return {'tooth_visible': False, 'kfile_visible': bool(data.get('kfile_visible')),
                'cavity_box': None, 'tooth_box': None, 'ratio': None,
                'roof_status': None, 'evidence': str(data.get('evidence') or '')[:200],
                'uncertain': uncertain}

    # 插锉照：status 可能被模型写成"不可判"，不算错——它本来就不参与判分
    if status is None and not kfile:
        return None

    cb, tb = _box(data.get('cavity_box')), _box(data.get('tooth_box'))
    ratio = None
    if cb and tb:
        denom = tb[2] * tb[3]
        if denom > 0:
            ratio = max(0.0, min(1.0, (cb[2] * cb[3]) / denom))

    ptype = str(data.get('photo_type') or '').strip()[:12]
    return {'tooth_visible': True, 'kfile_visible': kfile, 'photo_type': ptype,
            'cavity_box': cb, 'tooth_box': tb, 'ratio': ratio,
            'roof_status': status, 'evidence': str(data.get('evidence') or '')[:200],
            'uncertain': uncertain}


def _call_once(image_path):
    """单次调用。返回校验后的 dict 或 None。"""
    cfg = _load_config()
    if not (cfg.get('enabled') and cfg.get('api_key') and cfg.get('model')):
        return None
    if not _cb_allow():
        return None

    uri = _encode_image(image_path, int(cfg.get('max_image_side', 1280)))
    if uri is None:
        return None

    body_obj = {
        'model': cfg['model'],
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': USER_PROMPT},
                {'type': 'image_url', 'image_url': {'url': uri}},
            ]},
        ],
        'temperature': float(cfg.get('temperature', 0.2)),
        # 关思维链：实测 95s → 4.3s，判断质量不变。学生页面等不起 95 秒。
        'thinking': {'type': 'disabled'},
    }
    url = cfg['base_url'].rstrip('/') + '/chat/completions'

    last_note = ''
    for _ in range(_RETRIES + 1):
        req = urllib.request.Request(
            url, data=json.dumps(body_obj).encode('utf-8'),
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer ' + cfg['api_key']})
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=int(cfg.get('timeout', 20))) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            _u = data.get('usage') or {}   # 留痕 token，供用量看板统计
            raw = data['choices'][0]['message'].get('content', '')
            parsed = _validate(_extract_json(raw))
            if parsed is None:
                last_note = 'JSON解析/校验失败'
                _trace({'model': cfg['model'], 'raw': raw[:400]}, False, last_note)
                continue
            _cb_record(True)
            _trace({'model': cfg['model'], 'sec': round(time.time() - t0, 1),
                    'usage': _u,
                    'tooth_visible': parsed['tooth_visible'],
                    'roof_status': parsed['roof_status'],
                    'uncertain': parsed['uncertain']}, True)
            return parsed
        except urllib.error.HTTPError as e:
            last_note = f'HTTP {e.code}'
            time.sleep(0.6)
        except Exception as e:
            last_note = type(e).__name__
            time.sleep(0.6)

    _cb_record(False)
    _trace({'model': cfg['model']}, False, f'{last_note}（重试{_RETRIES}次后失败）')
    return None


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def score_from_ratio(r):
    """「洞口面积 ÷ 牙冠面积」→ 25 分制。
    阈值来自 2026-10-11 实测标定（王柔 0.135 / 李晓梅 0.14 / 陈晨 0.74）；
    等老师给「揭顶良好」样本后再复核一次。"""
    if r is None:
        return None
    if r >= 0.45:
        return 25.0
    if r >= 0.25:
        return round(14.0 + (r - 0.25) / 0.20 * 11.0, 1)
    if r >= 0.12:
        return round(6.0 + (r - 0.12) / 0.13 * 8.0, 1)
    return 6.0


def judge_roof(image_path, runs=3):
    """判读单张照片的髓室顶状态（并发跑 runs 次取中位，压掉单次离谱框）。

    返回 {'tooth_visible','cavity_box','tooth_box','ratio','roof_status',
          'evidence','uncertain','score','runs'};
    未配置 / 熔断 / 全部失败 → None（调用方按 60% 保底）。
    """
    cfg = _load_config()
    if not (cfg.get('enabled') and cfg.get('api_key') and cfg.get('model')):
        return None
    if not _cb_allow():
        return None

    runs = max(1, int(runs))
    if runs == 1:
        results = [_call_once(image_path)]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=runs) as ex:
            results = list(ex.map(lambda _: _call_once(image_path), range(runs)))

    ok = [r for r in results if r]
    if not ok:
        return None

    seen = [r for r in ok if r['tooth_visible']]
    if len(seen) * 2 < len(ok):
        return {'tooth_visible': False, 'kfile_visible': False, 'usable': False,
                'cavity_box': None, 'tooth_box': None, 'ratio': None,
                'roof_status': None, 'evidence': ok[0]['evidence'], 'uncertain': False,
                'score': None, 'runs': runs}

    # 老师规则：插了K锉的照片挡住所见，不能判髓室顶（只能说明根管找到了）
    kf = [r for r in seen if r['kfile_visible']]
    if len(kf) * 2 > len(seen):
        return {'tooth_visible': True, 'kfile_visible': True, 'usable': False,
                'cavity_box': None, 'tooth_box': None, 'ratio': None, 'roof_status': None,
                'evidence': '照片中插有K锉，遮挡髓室顶，不能据此判断髓室顶是否揭净（只能说明根管口已找到）。',
                'uncertain': False, 'score': None, 'runs': runs}

    # 不是开髓术的照片（如邻面II类洞、X光片）与本次作业无关，不能拿来判
    wrong = [r for r in seen if r.get('photo_type') and '开髓' not in r['photo_type']]
    if len(wrong) * 2 > len(seen):
        return {'tooth_visible': True, 'kfile_visible': False, 'usable': False,
                'cavity_box': None, 'tooth_box': None, 'ratio': None, 'roof_status': None,
                'evidence': f'这张照片不是开髓术照片（识别为：{wrong[0]["photo_type"]}），与本次作业无关。',
                'uncertain': False, 'score': None, 'runs': runs}

    # 只用「没插锉」且给出有效判定的那几次投票
    clean = [r for r in seen if not r['kfile_visible'] and r['roof_status']
             and '开髓' in (r.get('photo_type') or '开髓')]
    if not clean:
        return {'tooth_visible': True, 'kfile_visible': True, 'usable': False,
                'cavity_box': None, 'tooth_box': None, 'ratio': None, 'roof_status': None,
                'evidence': '未能取得可用的髓室顶判定，请按规范补拍颌面正位照。',
                'uncertain': False, 'score': None, 'runs': runs}
    seen = clean

    statuses = [r['roof_status'] for r in seen]
    status = max(set(statuses), key=statuses.count)
    # 分数按【三档判定的中位】算：实测框定位不稳（同一张图 box 比值 0.74↔0.05），
    # 而三档判定在明确病例上稳定；中位能挡掉单次离谱。
    scores = [ROOF_SCORE[s] for s in statuses]
    score = _median(scores)
    agree = len(set(statuses)) == 1

    ratios = [r['ratio'] for r in seen if r['ratio'] is not None]
    med = _median(ratios)
    # 代表结果 = 判定与多数一致且比值最接近中位的那一次（依据文字最贴合）
    same = [r for r in seen if r['roof_status'] == status] or seen
    rep = min(same, key=lambda r: abs((r['ratio'] if r['ratio'] is not None else 9) - (med or 9)))

    return {'tooth_visible': True, 'kfile_visible': False, 'usable': True,
            'cavity_box': rep['cavity_box'], 'tooth_box': rep['tooth_box'],
            'ratio': round(med, 3) if med is not None else None,
            'roof_status': status, 'evidence': rep['evidence'],
            'uncertain': (not agree) or (sum(1 for r in seen if r['uncertain']) * 2 > len(seen)),
            'score': score, 'runs': runs}


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        print('已配置:', is_configured())
        for p in sys.argv[1:]:
            t0 = time.time()
            print(p, '->', judge_roof(p), f'({time.time()-t0:.1f}s)')
