# -*- coding: utf-8 -*-
"""拿云端真实未匹配问法当靶子，测规则命中率（不依赖网络/大模型）。

用法：python3 test_unmatched_cloud.py [unmatched.json路径]
默认读 /tmp/unmatched_cloud.json（从云端 consult_logs 拉下来的）。
只统计「规则层能不能接住」——接住 = 学生不会看到兜底那句。

⚠️ 病例解析必须跟 training.py 的 _base() 完全一致：
       CASES 优先，取不到才用 REASONING(R1+R2+R3+KS)。
   坑：R1/R2/R3 里也有 case001/002/003/005/010 这些同名 id，
   直接 update 会把 CASES 的底牌覆盖掉，测出来的数字全是假的。
"""
import json
import sys

from chat_matcher import match_answer
from cases import CASES
from reasoning_cases import REASONING as R1
from reasoning_cases2 import REASONING2 as R2
from reasoning_cases3 import REASONING3 as R3
from history_kaoshi43 import REASONING_KS as RKS

REASONING = {}
for D in (R1, R2, R3, RKS):
    REASONING.update(D)


def base(cid):
    """与 training.py 的 _base() 同一套解析顺序。"""
    return CASES.get(cid) or REASONING.get(cid, {})


path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/unmatched_cloud.json'
rows = json.load(open(path, encoding='utf-8'))

miss = []
skipped = 0
for x in rows:
    cid = x.get('case_id') or ''
    q = x.get('question') or ''
    c = base(cid)
    if not c or not c.get('conversation'):
        skipped += 1
        miss.append((cid, q))
        continue
    m = match_answer(q, c['conversation'], recent_answers=[], case_data=c)
    if not m:
        miss.append((cid, q))

total = len(rows)
print(f'靶子问法 {total} 条，仍未接住 {len(miss)} 条（命中率 {100*(total-len(miss))/total:.1f}%）'
      + (f'，其中 {skipped} 条病例底牌缺失' if skipped else ''))
if miss:
    print('--- 仍未接住 ---')
    for cid, q in miss:
        print(f'  {cid}  {q}')
