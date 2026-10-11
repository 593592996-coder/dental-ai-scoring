#!/bin/bash
# 把 PA 抓取的数据合并进本地 reports/uploads（不覆盖已有）
cd "$(dirname "$0")/.."
cp -n migration_pa/reports/*.json reports/ 2>/dev/null
cp -n  migration_pa/uploads/*   uploads/ 2>/dev/null
python3 - <<'EOF'
import json, glob, collections, os
c = collections.Counter()
for f in glob.glob('reports/*.json'):
    b = os.path.basename(f)[:-5]
    for mod, pfx in [('crown_ant','crown_ant_'),('crown_post','crown_post_'),('impression','impression_'),('endo','endo_'),('xray','xray_')]:
        if b.startswith(pfx): c[mod] += 1; break
    else: c['class2'] += 1
print('合并后报告分布:', dict(c), '总计:', sum(c.values()))
endo = [f for f in glob.glob('reports/endo_*.json')]
sids = set()
for f in endo:
    try: sids.add(json.load(open(f)).get('student_number'))
    except Exception: pass
print('开髓报告:', len(endo), '唯一学生:', len([s for s in sids if s]))
EOF
