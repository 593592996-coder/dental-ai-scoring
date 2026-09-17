# -*- coding: utf-8 -*-
"""病史采集「患者回答」统一匹配引擎（板块1/板块3 + 老问诊流程共用）

旧算法的两个坑：
1) 每条关键词只要出现就给 1 + len*0.1，单字「疼/痛/药/病」和多字词得分几乎一样，
   学生任何带「疼」字的问题都被疼痛性质那条劫走 → 问什么都答同一句。
2) 关键词只按 `|` 分隔，病例里误写成 `/` 的两条永远匹配不上。

新算法：
- 命中分 = 命中关键词长度平方之和（2字词 4 分，3字词 9 分，单字仅 1 分兜底），
  且单字命中最多只算一个（避免「疼、痛、病」凑分）；
- 同分组内，含「疼/痛/怎么/什么」等泛化语素的条目降权，把具体条目（冷热/咬合/放射…）顶上来；
- `|` 和 `/` 都作为分隔符（兼容旧数据）；
- 同一条回答本轮已说过时跳过（防复读），换个话题再问可再次命中；
- 实在匹配不上返回 None，由调用方回「换个问法」并记录未匹配问法。
"""
import os
import re
import json
from datetime import datetime

# 维度泛词：常见于任何疼痛提问，单独命中时不能压过「冷热/咬合/放射」等具体特征词
_WEAK_WORDS = frozenset(
    ['怎么疼', '怎么痛', '什么感觉', '怎么样', '什么样的疼', '疼痛性质', '感觉', '性质',
     '不舒服', '怎么回事', '怎么不好', '怎么酸', '怎么个疼法',
     '加重', '缓解', '诱因', '诱发', '引起', '什么情况',
     '持续', '阵痛', '一阵', '症状', '疼吗', '痛吗', '疼不疼', '痛不痛'])

# 口语问法归一化：学生的说法千变万化，统一映射到词库里的标准词后再匹配。
# 左边正则命中即替换为右边标准词；以后发现新问法，在这里加一行即可。
_SYNONYM_RULES = [
    # —— 病历栏目名（学生按教材栏目直接提问）：映射到词库里的标准问法 ——
    (r'既往牙科治疗史|牙科治疗史|口腔治疗史|既往治疗史|治疗经过|治疗史', '看过医生 看过牙 治过 补过'),
    (r'既往牙病史|既往口腔病史|既往牙科病史|既往牙病|牙病史|口腔病史|牙科病史', '看过牙 看过医生 补过 治过 拔过'),
    (r'全身病史|系统病史|既往全身病史|既往系统病史', '全身疾病 慢性病'),
    (r'用药史|服药史|药物治疗史', '吃药 用药'),
    (r'烟酒史|吸烟饮酒史|吸烟史|饮酒史', '抽烟 喝酒 烟酒'),
    (r'既往史', '全身疾病 慢性病'),
    (r'检查史|拍片史|影像史', '拍片 X光'),
    # —— 饮食/个人习惯类宽泛问法，桥接到「饮食」主题，再由各病例的具体饮食条目接住 ——
    (r'饮食习惯|饮食情况|饮食|吃什么|爱吃什么|喜欢吃什么|喜欢喝什么|爱喝什么|爱吃|平时吃|平时喝|吃的方面|喝的方面', '饮食 喝什么'),
    (r'个人嗜好|嗜好|生活习惯|个人习惯', '抽烟 喝酒 饮食'),
    # —— 口语问法 ——
    (r'怎么个疼法|怎么个痛法|什么疼法|啥疼法|疼法|痛法', '怎么疼'),
    (r'吃过什么药|吃了什么药|吃过啥药|吃什么药|吃过药|什么药|啥药', '吃药'),
    (r'松了吗|松没松|松了没|松不松|晃不晃|晃了吗', '松动'),
    (r'拔了牙|拔了没有|拔过没有|拔没拔', '拔过'),
    (r'补了牙|补过没有|补没补', '补过'),
    (r'治过没有|治疗过没有|治没治过', '治过'),
    (r'冷热刺激|化学刺激|温度刺激', '冷热'),
    # —— 夜磨牙/紧咬：「晚上睡着咬牙」要路由到磨牙，而不是被「晚上」误判成夜间自发痛 ——
    (r'咬牙切齿|咯吱咯吱|锉牙|夜磨牙|夜里咬牙|晚上咬牙|睡着咬牙|睡觉咬牙|咬牙', '夜磨牙 磨牙 紧咬 腮帮'),
    (r'腮帮子|咬肌酸|脸颊酸|脸侧酸', '腮帮'),
]


def normalize_text(q):
    """供外部（评分覆盖度）复用的问法归一化。"""
    return _normalize(q)


# 学生问到「病史栏目」但该病例没有对应条目时的中性兜底回答（不含具体病情、不影响评分）。
# 仅当病例确实没设计该维度时才触发，避免患者对正经提问回「听不懂」。
_SECTION_FALLBACK = [
    (('用药史', '服药史', '吃药', '用药'), '没专门吃过什么药。'),
    (('烟酒史', '抽烟', '喝酒', '烟酒', '吸烟', '饮酒'), '烟酒我都不怎么沾。'),
    (('过敏史', '过敏'), '没发现对什么过敏。'),
    (('全身病史', '系统病史', '慢性病', '全身疾病'), '身体还行，没什么慢性病。'),
    (('治疗史', '既往牙病', '看过医生', '看过牙', '牙病史'), '牙齿以前没怎么看过、也没治过。'),
    (('拍片', 'X光', '影像'), '没有拍过片子。'),
    (('饮食', '喝什么', '爱吃', '吃的方面', '喝的方面'), '饮食上没什么特别的，跟平时一样。'),
]


def _normalize(q):
    """把口语化问句归一成标准说法，提升关键词命中率。"""
    out = q
    for pat, rep in _SYNONYM_RULES:
        out = re.sub(pat, rep, out)
    return out


def _split_keywords(keywords):
    """关键词串拆词：| 和 / 都算分隔符。"""
    parts = []
    for chunk in str(keywords).replace('/', '|').split('|'):
        k = chunk.strip()
        if k:
            parts.append(k)
    return parts


def _entry_score(q, words):
    """一条问答对该问题的匹配分。

    返回 (concrete, weak, single, longest)：
      concrete —— 具体特征词（冷热/咬合/放射/松动…）长度平方之和
      weak     —— 只命中维度泛词（怎么疼/加重/感觉…）的长度平方之和
      single   —— 仅单字命中记 1，纯兜底
    选择条目时 concrete 高者优先，从而「遇冷热刺激是否诱发疼痛」选冷热条而非加重条/性质条。
    """
    hits = [k for k in words if k in q]
    if not hits:
        return None
    multi = [k for k in hits if len(k) >= 2]
    longest = max(multi, key=len) if multi else max(hits, key=len)
    if not multi:
        return (0, 0, 1, longest)
    concrete = weak = 0
    for k in multi:
        s = len(k) ** 2
        if k in _WEAK_WORDS or all(g in k for g in ['疼']) or any(g in k for g in ('怎么', '什么')):
            weak += s
        else:
            concrete += s
    return (concrete, weak, 0, longest)


def match_answer(q, conversation, recent_answers=None, recent_n=4):
    """在 conversation（{关键词串: 回答}）中为问题 q 选最贴切的回答。

    recent_answers: 最近若干轮已给出的回答列表；与之重复的条目降权/跳过，防复读。
    返回 dict: {answer, keywords, hit, score} 或 None。
    """
    q = (q or '').strip()
    if not q:
        return None
    hay = q + ' ' + _normalize(q)   # 原句 + 归一化句一起参与匹配
    recent = list(recent_answers or [])[-recent_n:]
    best = None
    for keywords, answer in conversation.items():
        words = _split_keywords(keywords)
        res = _entry_score(hay, words)
        if res is None:
            continue
        concrete, weak, single, longest = res
        base_rank = (concrete, weak, single)
        # 防复读：最近几轮说过的同一条压到最低（所有条目都说过时才复读）
        eff_rank = (-1, -1, -1) if answer in recent else base_rank
        cand = (eff_rank, base_rank, len(longest), longest, keywords, answer)
        if best is None or cand[:3] > best[:3]:
            best = cand
    if not best:
        # 无任何条目命中：若问的是规范病史栏目而该病例无此维度，给中性兜底回答
        nq = _normalize(q)
        for kws, ans in _SECTION_FALLBACK:
            if any(k in nq for k in kws):
                return {'answer': ans, 'keywords': '', 'hit': '', 'score': 0, 'fallback': True}
        return None
    eff_rank, base_rank, _, longest, keywords, answer = best
    return {'answer': answer, 'keywords': keywords, 'hit': longest,
            'score': sum(base_rank[:2])}


def log_unmatched(log_dir, q, case_id='', case_title='', filename='unmatched_questions.json'):
    """患者「听不懂」的问题落盘，供教师收集后补充词库。

    同一病例同一句问法只保留一条，累计提问次数与首/末时间；按次数排序，
    高频问法排在前面优先补。只保留最近 500 个不同问法。
    """
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, filename)
        data = []
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for item in data:
            if item.get('case_id') == case_id and item.get('question') == q:
                item['count'] = item.get('count', 1) + 1
                item['last_time'] = now
                break
        else:
            data.append({'first_time': now, 'last_time': now, 'question': q,
                         'case_id': case_id, 'case_title': case_title, 'count': 1})
        data.sort(key=lambda x: x.get('count', 1), reverse=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data[:500], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_unmatched(log_dir, filename='unmatched_questions.json'):
    """读取收集到的未匹配问法（list）；文件不存在或损坏时返回空列表。"""
    path = os.path.join(log_dir, filename)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []
