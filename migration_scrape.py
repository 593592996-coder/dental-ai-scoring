# -*- coding: utf-8 -*-
"""从 PythonAnywhere 抓取全部评分记录 -> 重建 reports/*.json + uploads/ 缩略图
用法: python3 migration_scrape.py [--test]   (--test 只解析1条开髓并打印)
可断点续跑: 已存在的 json 自动跳过
"""
import requests, re, json, os, base64, time, sys

BASE = 'https://ouou.pythonanywhere.com'
STAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migration_pa')
RDIR, UDIR = os.path.join(STAGE, 'reports'), os.path.join(STAGE, 'uploads')
os.makedirs(RDIR, exist_ok=True); os.makedirs(UDIR, exist_ok=True)

PREFIX = {'class2': '', 'endo': 'endo_', 'xray': 'xray_',
          'crown_ant': 'crown_ant_', 'crown_post': 'crown_post_', 'impression': 'impression_'}
TITLE_KEY = {'class2': 'II类洞', 'endo': '开髓', 'xray': 'X光',
             'crown_ant': '全瓷冠', 'crown_post': '全瓷冠', 'impression': '印模'}
ICON2STATUS = {'✅': 'good', '⚠️': 'warning', '⬜': 'skip', '❌': 'bad'}

def strip_tags(x):
    return re.sub(r'<[^>]+>', '', x or '').strip()

def parse_report(html):
    r = {}
    m = re.search(r'class="subtitle">AI评分系统 · ([^<]+)<', html)
    r['timestamp'] = m.group(1).strip() if m else ''
    m = re.search(r'<span class="big">([\d.]+)</span>\s*<span class="small">/ (\d+) · (\w+)</span>', html)
    if m:
        r['total_score'] = float(m.group(1)); r['max_total'] = int(m.group(2)); r['grade'] = m.group(3)
        r['percentage'] = round(r['total_score'] / r['max_total'] * 100, 1)
    m = re.search(r'<p class="meta"><strong>([^<]+)</strong> · ([^<·]+)', html)
    if m: r['student_name'], r['student_class'] = m.group(1).strip(), m.group(2).strip()
    m = re.search(r'共分析 (\d+) 张照片', html)
    if m: r['photo_count'] = int(m.group(1))
    m = re.search(r'牙位 <strong>([^<]+)</strong>', html)
    if m: r['tooth'] = m.group(1).strip()
    # 印模上下颌分
    up = re.search(r'>上颌</div>\s*<div[^>]*>([\d.—]+)</div>', html)
    lo = re.search(r'>下颌</div>\s*<div[^>]*>([\d.—]+)</div>', html)
    if up: r['upper_score'], r['upper_present'] = (float(up.group(1)), True) if up.group(1) != '—' else (None, False)
    if lo: r['lower_score'], r['lower_present'] = (float(lo.group(1)), True) if lo.group(1) != '—' else (None, False)
    m = re.search(r'class="overall">(.*?)</div>', html, re.S)
    if m: r['overall_assessment'] = strip_tags(m.group(1))
    dims = []
    for blk in re.findall(r'<div class="dim">(.*?)</div>\s*(?=<div class="dim">|</div>)', html, re.S):
        d = {}
        nm = re.search(r'class="name">\s*(.)\s*([^<]+)<', blk)
        if not nm: continue
        icon, name = nm.group(1), nm.group(2).strip()
        d['name'] = name; d['status'] = ICON2STATUS.get(icon, 'bad')
        val = re.search(r'class="val">([\d.]+)/(\d+)<', blk)
        if val: d['score'] = float(val.group(1)); d['max_score'] = int(val.group(2)); d['percentage'] = round(d['score']/d['max_score']*100, 1)
        det = re.search(r'class="dim-detail">(.*?)</p>', blk, re.S)
        if det: d['detail'] = strip_tags(det.group(1))
        proc = re.search(r'class="dim-process">(.*?)</div>', blk, re.S)
        if proc: d['process_analysis'] = strip_tags(proc.group(1))
        sug = re.search(r'class="dim-sugg">💡\s*(.*?)</div>', blk, re.S)
        if sug: d['targeted_suggestion'] = strip_tags(sug.group(1))
        dims.append(d)
    r['dimensions'] = dims
    r['strengths'] = [strip_tags(x)[2:].strip() for x in re.findall(r'<div class="sw good">(.*?)</div>', html)]
    r['weaknesses'] = [strip_tags(x)[2:].strip() for x in re.findall(r'<div class="sw bad">(.*?)</div>', html)]
    probs = [strip_tags(x) for x in re.findall(r'<div class="problem">(.*?)</div>', html, re.S)]
    if probs: r['problem_areas'] = probs
    r['suggestions'] = [re.sub(r'^\d+\.\s*', '', strip_tags(x)) for x in re.findall(r'<div class="suggestion">(.*?)</div>', html, re.S)]
    photos = re.findall(r'data:image/(jpeg|png|jpg);base64,([A-Za-z0-9+/=]+)', html)
    return r, photos

def main():
    test = '--test' in sys.argv
    sess = requests.Session()
    sess.post(BASE + '/admin/login', data={'password': 'aimei2026'}, timeout=30)
    ov = sess.get(BASE + '/admin/api/overview', timeout=60).json()
    unmatched = ov.get('unmatched')
    print('overview: rows=%s junk=%s unmatched=%s' % (len(ov.get('rows', [])), ov.get('junk'), len(unmatched) if isinstance(unmatched, list) else unmatched))
    tasks = []
    for row in ov.get('rows', []):
        for mod, modid in (row.get('report_ids') or {}).items():
            if mod not in PREFIX or not modid: continue
            raw = modid[len(PREFIX[mod]):] if PREFIX[mod] and modid.startswith(PREFIX[mod]) else modid
            tasks.append({'mod': mod, 'raw': raw, 'sid': row.get('sid'), 'name': row.get('name'), 'class': row.get('class')})
    from collections import Counter
    print('任务分布:', dict(Counter(t['mod'] for t in tasks)))
    if test: tasks = [t for t in tasks if t['mod'] == 'endo'][:1]
    ok, fail, skip = 0, [], 0
    for i, t in enumerate(tasks):
        outp = os.path.join(RDIR, PREFIX[t['mod']] + t['raw'] + '.json')
        if os.path.exists(outp) and not test:
            skip += 1; continue
        try:
            h = sess.get(BASE + '/report/' + t['raw'], timeout=40).text
            if TITLE_KEY[t['mod']] not in h.split('</h1>')[0]:
                fail.append((t['mod'], t['raw'], '标题不符')); continue
            rep, photos = parse_report(h)
            rep['session_id'] = t['raw']
            if t.get('sid'): rep['student_number'] = t['sid']
            if rep.get('student_name') != t.get('name') and t.get('name'):
                rep['student_name'], rep['student_class'] = t['name'], t.get('class') or rep.get('student_class', '')
            # 保存缩略图
            for j, (ext, b64) in enumerate(photos):
                try:
                    fn = '%s%s_%d.%s' % (PREFIX[t['mod']], t['raw'], j, 'jpg' if ext in ('jpeg', 'jpg') else 'png')
                    with open(os.path.join(UDIR, fn), 'wb') as f: f.write(base64.b64decode(b64))
                except Exception: pass
            if photos: rep['photo_count'] = len(photos)
            json.dump(rep, open(outp, 'w'), ensure_ascii=False, indent=1)
            ok += 1
            if test:
                print(json.dumps(rep, ensure_ascii=False, indent=1)[:1500]); print('图片数:', len(photos)); return
        except Exception as e:
            fail.append((t['mod'], t['raw'], str(e)[:60]))
        if i % 25 == 0: print('进度 %d/%d ok=%d' % (i, len(tasks), ok)); sys.stdout.flush()
        time.sleep(0.25)
    json.dump({'ok': ok, 'skip': skip, 'fail': fail,
               'unmatched_shape': str(unmatched)[:500],
               'counts': dict(Counter(t['mod'] for t in tasks))},
              open(os.path.join(STAGE, 'summary.json'), 'w'), ensure_ascii=False, indent=1)
    print('完成: ok=%d skip=%d fail=%d' % (ok, skip, len(fail)))
    if fail: print('失败:', fail[:10])

if __name__ == '__main__':
    main()
