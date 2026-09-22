# -*- coding: utf-8 -*-
"""病史采集匹配引擎 + 初步诊断判定 回归验证（不发 HTTP，直接调函数）"""
from chat_matcher import match_answer
from cases import CASES
from reasoning_cases import REASONING as R1
from reasoning_cases2 import REASONING2 as R2
from reasoning_cases3 import REASONING3 as R3

ALL = {}
for cid, c in CASES.items():
    ALL[cid] = c.get('conversation', {})
for D in (R1, R2, R3):
    for cid, c in D.items():
        if c.get('conversation'):
            ALL[cid] = c['conversation']
RC = {}
RC.update(R1); RC.update(R2); RC.update(R3)

fails = []

def ask(cid, q, recent=None):
    m = match_answer(q, ALL[cid], recent_answers=recent or [])
    return m['answer'] if m else '【未匹配】'

# ── 1. 截图原始三问：case001 必须给出三个不同回答 ──
print('═══ case001 截图三问 ═══')
q1 = '疼痛能不能定位到具体哪一颗牙齿？会不会放射到头部、耳部？'
q2 = '遇冷热刺激、化学刺激是否诱发或加重疼痛？'
q3 = '咬东西的时候会不会疼？'
a1 = ask('case001', q1)
a2 = ask('case001', q2, [a1])
a3 = ask('case001', q3, [a1, a2])
for q, a in ((q1, a1), (q2, a2), (q3, a3)):
    print(f'  问：{q}\n  答：{a}\n')
if len({a1, a2, a3}) != 3:
    fails.append('case001 三问出现复读')
if '太阳穴' not in a1: fails.append('case001 放射问 → 未答放射')
if not any(w in a2 for w in ['冷热', '凉水', '冷水', '热水']): fails.append('case001 冷热问 → 未答冷热')
if '咬' not in a3: fails.append('case001 咬合问 → 未答咬合')

# 截图第三张的三问
print('═══ case001 截图3 三问 ═══')
qs = ['疼痛是自发痛还是刺激痛？', '疼痛是阵发性的还是持续性的？', '什么时候出现疼痛的？']
ans = []
recent = []
for q in qs:
    a = ask('case001', q, recent); ans.append(a); recent.append(a)
    print(f'  问：{q}\n  答：{a}\n')
if not any(w in ans[0] for w in ['自己疼', '自发', '没吃东西', '没吃']): fails.append('自发痛问 → 未答自发')
if '一阵' not in ans[1]: fails.append('阵发性问 → 未答性质')
if '3天' not in ans[2]: fails.append('病程问 → 未答时间')

# ── 2. 每病例一组覆盖性问题，检查未匹配率与复读 ──
probes = {
    'case001': ['哪颗牙疼？', '疼多久了？', '怎么个疼法？', '喝冷水疼吗？', '晚上睡觉疼吗？',
                '咬东西疼不疼？', '吃过什么药？', '有高血压糖尿病吗？', '对什么药过敏吗？', '抽烟喝酒吗？'],
    'case002': ['什么时候受的伤？', '怎么摔的？', '现在碰它疼吗？', '牙松了吗？', '喝冷水酸吗？',
                '身体有什么病吗？', '过敏吗？', '几岁了上几年级？'],
    'case003': ['鼓包多久了？', '疼不疼？', '挤破有脓吗？', '吃过什么药？', '青霉素过敏吗？',
                '这颗牙以前补过吗？'],
    'case004': ['哪颗牙疼、能定位吗？', '怎么疼，跳着疼吗？', '咬东西疼吗？', '脸肿了吗发烧吗？',
                '冷热有感觉吗？', '吃过甲硝唑吗？'],
    'case005': ['哪颗牙？', '多久了？', '喝冷水疼多久？', '会自己疼吗？', '咬东西疼吗？', '过敏吗？'],
    'case006': ['哪些牙酸、什么部位？', '怎么刷牙的？', '晚上磨牙吗？', '多久了？', '会自己疼吗？'],
    'case007': ['多久了？', '怎么疼？', '冷热刺激后疼多久？', '会自己隐隐疼吗？', '塞东西疼吗？'],
    'case008': ['哪颗牙？', '怎么疼，是不是咬到某一点？', '松开的时候疼吗？', '喝冷水呢？',
                '有自发痛吗？', '以前补过吗？'],
    'case009': ['平时爱喝什么饮料？', '胃反酸吗？', '吃酸的敏感吗？', '会自己疼吗？', '多久了？'],
    'case010': ['怎么个疼法？', '一次疼多久？', '刷牙洗脸会诱发吗？', '跟冷热有关系吗？',
                '哪颗牙疼、过中线吗？', '以前拔了牙还疼吗？'],
    'case011': ['晚上磨牙吗？', '爱吃硬东西吗？', '哪些牙磨平了？', '会自己疼吗？', '多久了？'],
    'case012': ['哪里肿、能指出来吗？', '怎么开始的，塞牙了吗？', '吸一下出血吗？', '有自发痛吗？',
                '咬东西疼吗？'],
    'case013': ['哪颗牙疼、几颗？', '感冒鼻塞了吗？', '弯腰会加重吗？', '冷热疼吗？',
                '有自发痛吗？'],
}
print('═══ 13病例覆盖回归 ═══')
total_q = unmatched = 0
for cid, qs in probes.items():
    recent, replies = [], []
    for q in qs:
        total_q += 1
        m = match_answer(q, ALL[cid], recent_answers=recent)
        if not m:
            unmatched += 1
            print(f'  ✗ {cid} 未匹配：{q}')
            fails.append(f'{cid} 未匹配：{q}')
        else:
            recent.append(m['answer']); replies.append(m['answer'])
    dup = len(replies) - len(set(replies))
    if dup:
        print(f'  ⚠ {cid} 有 {dup} 次复读')
print(f'问题总数 {total_q}，未匹配 {unmatched}')

# ── 3. 初步诊断判定 ──
print('\n═══ 初步诊断判定 ═══')
import training
# （impression, 期望level）：规则=首位须最可能、且列≥2种才 correct
cases_test = [
    # 首位对 + 列≥2种
    ('case001', '36急性牙髓炎、急性龈乳头炎、三叉神经痛', 'correct'),
    ('case001', '慢性牙髓炎急性发作，急性根尖周炎', 'correct'),
    ('case010', '三叉神经痛、急性牙髓炎', 'correct'),
    ('case008', '牙隐裂、深龋', 'correct'),
    ('case002', '冠折露髓，牙脱位', 'correct'),
    ('case004', '急性根尖周炎、急性牙周脓肿', 'correct'),
    ('case003', '慢性根尖周炎、根尖囊肿', 'correct'),
    ('case005', '深龋、不可复性牙髓炎', 'correct'),
    ('case009', '酸蚀症、楔状缺损', 'correct'),
    # 只写1种 → partial（要求两种以上）
    ('case001', '36急性牙髓炎', 'partial'),
    # 只写家族大类 → partial
    ('case001', '牙髓炎、三叉神经痛', 'partial'),
    ('case004', '根尖周炎、牙周脓肿', 'partial'),
    ('case002', '冠折、牙震荡', 'partial'),
    # 想到了但没排第一 → partial
    ('case001', '三叉神经痛、急性牙髓炎', 'partial'),
    # 首位完全不对 → wrong
    ('case001', '三叉神经痛、急性龈乳头炎', 'wrong'),
    ('case013', '牙髓炎、根尖周炎', 'wrong'),
]
for cid, imp, want in cases_test:
    fb = training._judge_impression(RC[cid], imp)
    ok = '✓' if fb['level'] == want else '✗'
    if fb['level'] != want:
        fails.append(f'判定 {cid}「{imp}」期望{want}实得{fb["level"]}')
    print(f'  {ok} {cid} 「{imp[:22]}」→ {fb["level"]}（首位：{fb["primary"][:14]}）')

print('\n' + ('✅ 全部通过' if not fails else '❌ 失败项：\n' + '\n'.join(fails)))
raise SystemExit(1 if fails else 0)
