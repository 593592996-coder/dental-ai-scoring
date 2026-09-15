# -*- coding: utf-8 -*-
"""临床思维训练 · 三板块后端引擎（Blueprint，挂到 app.py，不影响原问诊流程）

板块1 病史采集：关键词覆盖度评分（现病史五要素+既往/过敏/个人/用药）
板块2 病例分析：书面作答，诊断30/依据30/鉴别20/治疗20
板块3 临床思维：问诊→检查→诊断(依据链+关键决策)→治疗逻辑→复盘，6维评分
综合成绩：病史30% + 分析30% + 思维40%
"""
from flask import Blueprint, render_template, request, jsonify, session, send_file
import uuid, os, json, re, io
from datetime import datetime
from cases import CASES
from reasoning_cases import REASONING as R1, WEIGHTS, in_scope_cases
from reasoning_cases2 import REASONING2 as R2
from reasoning_cases3 import REASONING3 as R3
from students import (load_roster, roster_exists, load_students, list_classes,
                      fill_workbook, blank_workbook, class_template_map,
                      roster_source_files, SCORE_COLS)
import attempts

# 教师试用账号：只需在学号框输 abc123 即登录（无需姓名/密码）；成绩标记 teacher，不进学生总览/导出
TEACHER_ACCOUNT = {'sid': 'abc123',
                   'name': '教师体验', 'class': '（教师体验，不计入学生成绩）'}

# 合并全部底牌：001/005/006（R1）+ 002/003/004（R2）+ 007~013（R3，自包含问诊/检查）
REASONING = {}
REASONING.update(R1); REASONING.update(R2); REASONING.update(R3)

train_bp = Blueprint('training', __name__)

SCORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scores')
os.makedirs(SCORE_DIR, exist_ok=True)


# ═══════════════════ 通用 ═══════════════════
def _student_id():
    """学生身份 id 跨板块保持（综合成绩合并用）；不清空。
    已登记学号则直接用学号做成绩文件主键，保证一人一档、可按花名册导出。"""
    sid = session.get('student_number') or session.get('student_sid')
    if not sid:
        sid = uuid.uuid4().hex[:8]
        session['student_sid'] = sid
    return sid


def _cc(case_id):
    """病例的主诉（卡片只显示主诉，不暴露诊断）。"""
    return _base(case_id).get('chief_complaint', '')


# ── 身份登记 ──
@train_bp.route('/train/api/roster')
def api_roster():
    return jsonify({'exists': roster_exists(), 'count': len(load_roster())})


@train_bp.route('/train/api/identify', methods=['POST'])
def api_identify():
    """进门登录：有花名册须“学号+姓名”与名册匹配；无花名册则手填姓名/学号/班级。"""
    d = request.get_json() or {}
    sid = (d.get('student_number') or '').strip()
    name = (d.get('name') or '').strip()
    klass = (d.get('class_name') or '').strip()

    # 教师试用账号：只需在“学号”框输 abc123，无需姓名、无需密码、不在名册中
    if sid == TEACHER_ACCOUNT['sid']:
        session['student_number'] = TEACHER_ACCOUNT['sid']
        session['student_name'] = TEACHER_ACCOUNT['name']
        session['student_class'] = TEACHER_ACCOUNT['class']
        session['student_sid'] = TEACHER_ACCOUNT['sid']
        session['is_teacher'] = True
        attempts.record(TEACHER_ACCOUNT['sid'], TEACHER_ACCOUNT['name'],
                        TEACHER_ACCOUNT['class'], 'login', teacher=True)
        return jsonify({'ok': True, 'name': TEACHER_ACCOUNT['name'],
                        'student_number': TEACHER_ACCOUNT['sid'],
                        'class_name': TEACHER_ACCOUNT['class'], 'roster': True, 'teacher': True})

    roster = load_roster()
    if roster:
        if not sid or not name:
            return jsonify({'ok': False, 'error': '请输入学号和姓名'}), 400
        st = roster.get(sid)
        if not st:
            return jsonify({'ok': False, 'error': '学号不在花名册中，请核对后再输'}), 400
        if st['name'].replace(' ', '') != name.replace(' ', ''):
            return jsonify({'ok': False, 'error': '学号与姓名不匹配，请核对'}), 400
        name, klass = st['name'], st['class']
    else:
        if not name or not sid:
            return jsonify({'ok': False, 'error': '请填齐姓名和学号'}), 400
    session['student_number'] = sid
    session['student_name'] = name
    session['student_class'] = klass
    session['student_sid'] = sid
    session['is_teacher'] = False
    attempts.record(sid, name, klass, 'login')
    return jsonify({'ok': True, 'name': name, 'student_number': sid, 'class_name': klass,
                    'roster': bool(roster)})


@train_bp.route('/train/api/me')
def api_me():
    if not session.get('student_number'):
        return jsonify({'identified': False, 'roster': roster_exists()})
    return jsonify({'identified': True, 'roster': roster_exists(),
                    'name': session.get('student_name'),
                    'student_number': session.get('student_number'),
                    'class_name': session.get('student_class')})


@train_bp.route('/train/api/logout', methods=['POST'])
def api_logout():
    for k in ('student_number', 'student_name', 'student_class', 'student_sid'):
        session.pop(k, None)
    return jsonify({'ok': True})

def _reset_attempt():
    """开始新一次作答：清过程状态，但保留学生身份 student_sid（跨板块累计成绩）。"""
    for k in ['train_case', 'train_mode', 'hist_log', 'rs_phase', 'rs_log', 'rs_exams', 'train_id']:
        session.pop(k, None)
    session['train_id'] = _student_id()

def _rc(case_id):
    return REASONING.get(case_id)

def _base(case_id):
    """病例的问诊/检查底座：001-006 用 cases.py 的 CASES；007-013 用底牌自带数据。"""
    return CASES.get(case_id) or REASONING.get(case_id, {})

@train_bp.route('/train')
def train_home():
    """三板块训练首页"""
    cases = []
    for cid, rc in REASONING.items():
        cases.append({
            'id': cid, 'title': rc.get('title', cid),
            'level': rc.get('level', 1), 'tag': rc.get('module_tag', ''),
            'in_scope': rc.get('in_scope', True),
            'has_history': 'history_outline' in rc,
            'has_analysis': 'analysis' in rc,
            'has_reasoning': 'reasoning' in rc,
        })
    return render_template('train.html', cases=cases, weights=WEIGHTS)


@train_bp.route('/train/api/cases')
def train_cases():
    return jsonify({cid: {'title': rc.get('title'),
                          'chief_complaint': _cc(cid),
                          'level': rc.get('level'),
                          'tag': rc.get('module_tag'), 'in_scope': rc.get('in_scope', True)}
                    for cid, rc in REASONING.items()})


# ═══════════════════ 板块1 · 病史采集 ═══════════════════
@train_bp.route('/train/api/history/start/<case_id>', methods=['POST'])
def history_start(case_id):
    rc = _rc(case_id); b = _base(case_id)
    if not rc or 'history_outline' not in rc:
        return jsonify({'error': '该病例暂无病史采集提纲'}), 404
    _reset_attempt()
    session['train_case'] = case_id
    session['train_mode'] = request.json.get('mode', 'practice') if request.is_json else 'practice'
    session['hist_log'] = []
    return jsonify({
        'case_id': case_id, 'title': rc['title'], 'patient': b.get('patient', {}),
        'chief_complaint': b.get('chief_complaint', ''),
        'images': [{'label': i.get('label'), 'desc': i.get('desc')} for i in b.get('images', [])],
        'instruction': '根据主诉向患者提问，采集完整病史。问完后点「完成采集」评分。',
    })


@train_bp.route('/train/api/history/chat', methods=['POST'])
def history_chat():
    case_id = session.get('train_case')
    if not case_id: return jsonify({'error': '请先开始'}), 400
    b = _base(case_id)
    data = request.get_json()
    q = (data.get('message') or '').strip()
    conv = b.get('conversation', {})
    best, best_score = None, 0
    for keywords, answer in conv.items():
        score = 0
        for k in keywords.split('|'):
            if k and k in q:
                score += 1 + len(k) * 0.1
        if score > best_score:
            best_score, best = score, answer
    reply = best if best else '我……不太明白你问的是哪样，你换个问法嘛？'
    log = session.get('hist_log', [])
    log.append({'student': q, 'patient': reply})
    session['hist_log'] = log
    return jsonify({'reply': reply})


@train_bp.route('/train/api/history/score', methods=['POST'])
def history_score():
    case_id = session.get('train_case')
    rc = _rc(case_id)
    if not case_id or not rc or 'history_outline' not in rc:
        return jsonify({'error': '会话失效'}), 400
    log = session.get('hist_log', [])
    all_q = ' '.join(x['student'] for x in log)

    outline = rc['history_outline']
    detail, total, covered = [], 0, 0
    crit_missed = []
    cat_stats = []
    for cat, items in outline.items():
        cat_total = cat_hit = 0
        rows = []
        for it in items:
            total += 1; cat_total += 1
            hit = any(k and k in all_q for k in it['keywords'])
            if hit: covered += 1; cat_hit += 1
            elif it.get('critical'): crit_missed.append(it['label'])
            rows.append({'label': it['label'], 'covered': hit, 'critical': it.get('critical', False)})
        cat_stats.append({'cat': cat, 'hit': cat_hit, 'total': cat_total,
                          'pct': round(cat_hit / cat_total * 100) if cat_total else 0})
        detail.append({'cat': cat, 'items': rows})

    base = round(covered / total * 100) if total else 0
    penalty = len(crit_missed) * 5   # 关键项（过敏史/自发痛等）遗漏加重扣
    score = max(0, base - penalty)
    result = {'score': score, 'covered': covered, 'total': total,
              'critical_missed': crit_missed, 'cat_stats': cat_stats, 'detail': detail,
              'question_count': len(log)}
    _save_score(case_id, 'history', score)
    attempts.record(_student_id(), session.get('student_name', ''), session.get('student_class', ''),
                    'history_score', case_id, score=score, covered=covered, total=total,
                    question_count=len(log), critical_missed=crit_missed,
                    cat_stats=cat_stats, detail=detail,
                    transcript=[{'q': x['student'], 'a': x['patient']} for x in log],
                    teacher=session.get('is_teacher', False))
    return jsonify(result)


# ═══════════════════ 板块2 · 病例分析 ═══════════════════
@train_bp.route('/train/api/analysis/<case_id>')
def analysis_material(case_id):
    rc = _rc(case_id)
    if not rc or 'analysis' not in rc:
        return jsonify({'error': '该病例暂无病例分析'}), 404
    a = rc['analysis']
    return jsonify({
        'case_id': case_id, 'title': rc['title'], 'tag': rc.get('module_tag', ''),
        'material': a['material'],
        'fields': ['diagnosis', 'basis', 'differential', 'treatment'],
    })


@train_bp.route('/train/api/analysis/score/<case_id>', methods=['POST'])
def analysis_score(case_id):
    rc = _rc(case_id)
    if not rc or 'analysis' not in rc:
        return jsonify({'error': '病例不存在'}), 404
    a = rc['analysis']
    d = request.get_json()
    diag = (d.get('diagnosis') or '').strip()
    basis = (d.get('basis') or '').strip()
    diff = (d.get('differential') or '').strip()
    treat = (d.get('treatment') or '').strip()

    # —— 诊断 30 ——
    correct_diag = a['diagnosis']
    if diag == correct_diag:
        diag_score = 30
    elif any(acc in diag or diag in acc for acc in a.get('acceptable_diag', []) if acc):
        diag_score = 24
    else:
        hit = sum(1 for acc in a.get('acceptable_diag', []) if acc and acc in diag)
        diag_score = min(20, hit * 8) if hit else 6

    # —— 诊断依据 30 ——
    basis_rows = []
    for bp in a['basis_points']:
        hit = any(k and k in basis for k in bp['keywords'])
        basis_rows.append({'text': bp['text'], 'hit': hit})
    basis_hit = sum(1 for r in basis_rows if r['hit'])
    basis_score = round(basis_hit / len(basis_rows) * 30) if basis_rows else 0

    # —— 鉴别诊断 20（考试鉴别）——
    diff_rows = []
    for dp in a.get('differential_exam', []):
        hit = (dp['name'] in diff) or any(k and k in diff for k in dp.get('keywords', []))
        diff_rows.append({'name': dp['name'], 'hit': hit, 'point': dp['point']})
    diff_hit = sum(1 for r in diff_rows if r['hit'])
    diff_score = round(diff_hit / max(len(diff_rows), 1) * 20) if diff_rows else 16

    # —— 治疗设计 20 ——
    treat_rows = []
    for tp in a['treatment_points']:
        hit = any(k and k in treat for k in tp['keywords'])
        treat_rows.append({'text': tp['text'], 'hit': hit})
    treat_hit = sum(1 for r in treat_rows if r['hit'])
    treat_score = round(treat_hit / len(treat_rows) * 20) if treat_rows else 0

    total = diag_score + basis_score + diff_score + treat_score
    result = {
        'scores': {'diagnosis': diag_score, 'basis': basis_score,
                   'differential': diff_score, 'treatment': treat_score, 'total': total},
        'basis_rows': basis_rows, 'diff_rows': diff_rows, 'treat_rows': treat_rows,
        'correct': {'diagnosis': correct_diag,
                    'differential_exam': [{'name': x['name'], 'point': x['point']} for x in a.get('differential_exam', [])],
                    'differential_clinical': [x['name'] for x in a.get('differential_clinical', [])],
                    'treatment_points': [x['text'] for x in a['treatment_points']],
                    'basis_points': [x['text'] for x in a['basis_points']]},
    }
    _save_score(case_id, 'analysis', total)
    attempts.record(_student_id(), session.get('student_name', ''), session.get('student_class', ''),
                    'analysis_score', case_id, score=total, scores=result['scores'],
                    answers={'diagnosis': diag, 'basis': basis,
                             'differential': diff, 'treatment': treat},
                    basis_rows=basis_rows, diff_rows=diff_rows, treat_rows=treat_rows,
                    correct_diagnosis=correct_diag,
                    teacher=session.get('is_teacher', False))
    return jsonify(result)


# ═══════════════════ 板块3 · 临床思维 ═══════════════════
@train_bp.route('/train/api/reasoning/start/<case_id>', methods=['POST'])
def reasoning_start(case_id):
    rc = _rc(case_id); b = _base(case_id)
    if not rc or 'reasoning' not in rc:
        return jsonify({'error': '该病例暂无思维训练'}), 404
    _reset_attempt()
    session['train_case'] = case_id
    session['rs_phase'] = 'history'
    session['rs_log'] = []
    session['rs_exams'] = []
    session['rs_rejects'] = 0
    rz = rc['reasoning']
    # 检查项（用 CASES 的 examination，附目的题）
    exams = []
    exam_items = b.get('examination', {}).get('items', {})
    for name in b.get('examination', {}).get('correct_sequence', []):
        if name in exam_items:
            exams.append({'name': name, 'purpose_options': None})
    return jsonify({
        'case_id': case_id, 'title': rc['title'], 'patient': b.get('patient', {}),
        'chief_complaint': b.get('chief_complaint', ''),
        'images': [{'label': i.get('label'), 'desc': i.get('desc')} for i in b.get('images', [])],
        'exam_names': [e['name'] for e in exams],
        'exam_purpose': rz.get('exam_purpose', {}),
        'evidence': [{'id': e['id'], 'text': e['text'], 'source': e['source'], 'weight': e['weight']}
                     for e in rz.get('evidence', [])],
        'key_decisions': [{'id': d['id'], 'question': d['question'], 'hint': d.get('hint', '')}
                          for d in rz.get('key_decisions', [])],
    })


@train_bp.route('/train/api/reasoning/chat', methods=['POST'])
def reasoning_chat():
    case_id = session.get('train_case')
    if not case_id: return jsonify({'error': '请先开始'}), 400
    b = _base(case_id)
    q = (request.get_json().get('message') or '').strip()
    conv = b.get('conversation', {})
    best, best_score, best_kw = None, 0, ''
    for keywords, answer in conv.items():
        score = 0
        for k in keywords.split('|'):
            if k and k in q: score += 1 + len(k) * 0.1
        if score > best_score: best_score, best, best_kw = score, answer, keywords
    reply = best if best else '我……不太明白，你换个问法嘛？'
    log = session.get('rs_log', [])
    log.append({'student': q, 'patient': reply, 'matched': bool(best)})
    session['rs_log'] = log
    return jsonify({'reply': reply})


@train_bp.route('/train/api/reasoning/exam', methods=['POST'])
def reasoning_exam():
    """学生做一项检查，返回 finding（检查环节以"选检查→看结果"为主）"""
    case_id = session.get('train_case')
    b = _base(case_id)
    name = (request.get_json().get('item') or '').strip()
    items = b.get('examination', {}).get('items', {})
    if name not in items:
        return jsonify({'error': '无此检查项'}), 400
    done = session.get('rs_exams', [])
    if name not in done: done.append(name)
    session['rs_exams'] = done
    rc = _rc(case_id)
    purpose = rc.get('reasoning', {}).get('exam_purpose', {}).get(name, '')
    return jsonify({'item': name, 'finding': items[name].get('finding', ''),
                    'key_points': items[name].get('key_points', ''), 'purpose': purpose,
                    'done': done})


@train_bp.route('/train/api/reasoning/diagnose', methods=['POST'])
def reasoning_diagnose():
    """诊断阶段：勾选证据 + 关键决策 + 诊断 + 鉴别 → 依据链不闭合则打回"""
    case_id = session.get('train_case')
    rc = _rc(case_id)
    if not rc: return jsonify({'error': '会话失效'}), 400
    rz = rc['reasoning']
    d = request.get_json()
    picked = set(d.get('evidence', []))
    decisions = d.get('decisions', {})           # {d1: "活髓", ...}
    diag = (d.get('diagnosis') or '').strip()
    diff = (d.get('differential') or '').strip()

    # 依据链：高权重(weight=3)证据覆盖率
    ev = rz.get('evidence', [])
    critical_ev = [e for e in ev if e['weight'] == 3]
    picked_crit = [e for e in critical_ev if e['id'] in picked]
    chain_pct = len(picked_crit) / len(critical_ev) if critical_ev else 1

    # 关键决策判定
    dec_rows = []
    dec_wrong = []
    for kd in rz.get('key_decisions', []):
        ans = (decisions.get(kd['id']) or '').strip()
        ok = any(acc and acc in ans for acc in kd.get('accept', [])) or (kd['answer'] in ans)
        dec_rows.append({'id': kd['id'], 'question': kd['question'], 'your': ans,
                         'correct': kd['answer'], 'ok': ok})
        if not ok: dec_wrong.append(kd['question'])

    # 鉴别命中（考试+临床）
    a = rc.get('analysis', {})
    diff_names = [x['name'] for x in a.get('differential_exam', [])] + \
                 [x['name'] for x in a.get('differential_clinical', [])]
    diff_hit = sum(1 for n in diff_names if n in diff)

    # 打回条件：关键决策错 或 决定性证据覆盖<60%
    blocks = []
    if dec_wrong:
        blocks.append('关键判断有误：' + '；'.join(dec_wrong) + '。请依据证据重新判断。')
    if chain_pct < 0.6:
        missing = [f"{e['id']} {e['text']}" for e in critical_ev if e['id'] not in picked]
        blocks.append('诊断依据链不完整，缺少决定性证据：' + '；'.join(missing[:4]) + '。回去补问/补查。')

    passed = len(blocks) == 0
    if not passed:
        session['rs_rejects'] = session.get('rs_rejects', 0) + 1
    return jsonify({
        'passed': passed, 'blocks': blocks,
        'chain_pct': round(chain_pct * 100),
        'decision_rows': dec_rows,
        'diff_hit': diff_hit, 'diff_total': len(diff_names),
        'picked_count': len(picked),
    })


@train_bp.route('/train/api/reasoning/treat', methods=['POST'])
def reasoning_treat():
    """治疗阶段：返回治疗决策逻辑题（学生思考后对照）"""
    case_id = session.get('train_case')
    rc = _rc(case_id)
    if not rc: return jsonify({'error': '会话失效'}), 400
    return jsonify({'rationale': rc['reasoning'].get('treatment_rationale', [])})


@train_bp.route('/train/api/reasoning/review', methods=['POST'])
def reasoning_review():
    """复盘 + 6维评分"""
    case_id = session.get('train_case')
    rc = _rc(case_id); b = _base(case_id)
    if not rc: return jsonify({'error': '会话失效'}), 400
    rz = rc['reasoning']
    d = request.get_json()
    picked = set(d.get('evidence', []))
    decisions = d.get('decisions', {})
    exams_done = set(session.get('rs_exams', []))
    log = session.get('rs_log', [])

    ev = rz.get('evidence', [])
    crit = [e for e in ev if e['weight'] == 3]
    # 1 依据链完整性 25
    chain = round(len([e for e in crit if e['id'] in picked]) / max(len(crit), 1) * 25)
    # 2 证据权重 20（选中决定性证据；没乱选无关不扣）
    weight_score = round(len([e for e in ev if e['id'] in picked and e['weight'] == 3]) /
                         max(len(crit), 1) * 20)
    # 3 鉴别 20（关键决策中含排除类 + 鉴别文本）
    dec_ok = 0; dec_total = len(rz.get('key_decisions', []))
    for kd in rz.get('key_decisions', []):
        ans = (decisions.get(kd['id']) or '').strip()
        if any(acc and acc in ans for acc in kd.get('accept', [])) or kd['answer'] in ans:
            dec_ok += 1
    diff_text = (d.get('differential') or '')
    a = rc.get('analysis', {})
    diff_names = [x['name'] for x in a.get('differential_exam', [])] + \
                 [x['name'] for x in a.get('differential_clinical', [])]
    diff_hit = sum(1 for n in diff_names if n in diff_text)
    diff_score = round((dec_ok / max(dec_total, 1)) * 12 + (diff_hit / max(len(diff_names), 1)) * 8)
    # 4 问诊目的性 15（问到关键信息：问诊轮次覆盖 conversation 比例）
    conv = b.get('conversation', {})
    all_q = ' '.join(x['student'] for x in log)
    ask_hit = sum(1 for kw in conv if any(k and k in all_q for k in kw.split('|')))
    ask_score = round(ask_hit / max(len(conv), 1) * 15) if conv else 10
    # 5 检查-假设 10（做了关键检查：冷测/热测/电活力/X线 中该病例有的）
    key_exams = [n for n in ['冷测', '热测', '牙髓电活力测试', 'X线片判读', '叩诊']
                 if n in b.get('examination', {}).get('items', {})]
    exam_score = round(len([n for n in key_exams if n in exams_done]) / max(len(key_exams), 1) * 10) if key_exams else 8
    # 6 治疗-诊断 10（治疗逻辑自评对照，前端答后给分；这里按是否进入复盘给基线+关键决策）
    treat_ok = d.get('treat_ok', 0)
    treat_score = min(10, int(treat_ok))

    dims = {'chain': chain, 'weight': weight_score, 'differential': diff_score,
            'ask_purpose': ask_score, 'exam_hypothesis': exam_score, 'treat_logic': treat_score}
    total = sum(dims.values())

    result = {
        'scores': {'dims': dims, 'total': total},
        'evidence_chain': [{'id': e['id'], 'text': e['text'], 'points_to': e['points_to'],
                            'weight': e['weight'], 'picked': e['id'] in picked} for e in ev],
        'model_record': rc.get('model_record', {}),
        'decision_rows': [{'q': kd['question'], 'correct': kd['answer']} for kd in rz.get('key_decisions', [])],
    }
    _save_score(case_id, 'reasoning', total)
    picked_rows = [{'id': e['id'], 'text': e['text'], 'weight': e['weight'],
                    'picked': e['id'] in picked} for e in ev]
    attempts.record(_student_id(), session.get('student_name', ''), session.get('student_class', ''),
                    'reasoning_score', case_id, score=total, dims=dims,
                    evidence=picked_rows,
                    decisions=[{'q': kd['question'], 'your': (decisions.get(kd['id']) or '').strip(),
                                'correct': kd['answer']} for kd in rz.get('key_decisions', [])],
                    exams_done=sorted(exams_done), question_count=len(log),
                    rejects=session.get('rs_rejects', 0),
                    diagnosis=(d.get('diagnosis') or '').strip(),
                    differential=(d.get('differential') or '').strip(),
                    teacher=session.get('is_teacher', False))
    return jsonify(result)


# ═══════════════════ 综合成绩 ═══════════════════
def _score_file(sid):
    return os.path.join(SCORE_DIR, f'{sid}.json')

def _save_score(case_id, section, score):
    sid = _student_id()
    path = _score_file(sid)
    rec = {}
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f: rec = json.load(f)
        except: rec = {}
    rec.setdefault('sections', {})
    rec['sections'].setdefault(section, {})[case_id] = score
    rec['name'] = session.get('student_name', rec.get('name', ''))
    rec['class'] = session.get('student_class', rec.get('class', ''))
    rec['student_number'] = sid
    rec['updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


@train_bp.route('/train/api/final', methods=['POST'])
def final_score():
    """按三板块各题平均分加权算综合总分"""
    sid = _student_id()
    rec = {}
    if sid and os.path.exists(_score_file(sid)):
        with open(_score_file(sid), encoding='utf-8') as f:
            rec = json.load(f)
    secs = rec.get('sections', {})
    def avg(d): return round(sum(d.values()) / len(d)) if d else None
    h, an, rs = avg(secs.get('history', {})), avg(secs.get('analysis', {})), avg(secs.get('reasoning', {}))
    parts = {}
    total = 0; wsum = 0
    for key, val in (('history', h), ('analysis', an), ('reasoning', rs)):
        if val is not None:
            parts[key] = val; total += val * WEIGHTS[key]; wsum += WEIGHTS[key]
    final = round(total / wsum) if wsum else None
    return jsonify({'sections': {'history': h, 'analysis': an, 'reasoning': rs},
                    'weights': WEIGHTS, 'final': final, 'detail': secs})


# ═══════════════════ 教师：成绩总览 + 按学校格式导出 ═══════════════════
def _avg(d):
    return round(sum(d.values()) / len(d)) if d else None


def _all_grade_records():
    """读 scores/ 全部成绩文件，按学号汇总三板块均分与综合分。"""
    recs = {}
    if os.path.isdir(SCORE_DIR):
        for fn in os.listdir(SCORE_DIR):
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(SCORE_DIR, fn), encoding='utf-8') as f:
                    rec = json.load(f)
            except Exception:
                continue
            sid = rec.get('student_number') or fn[:-5]
            secs = rec.get('sections', {})
            h, an, rs = _avg(secs.get('history', {})), _avg(secs.get('analysis', {})), _avg(secs.get('reasoning', {}))
            tot = wsum = 0
            for key, val in (('history', h), ('analysis', an), ('reasoning', rs)):
                if val is not None:
                    tot += val * WEIGHTS[key]; wsum += WEIGHTS[key]
            final = round(tot / wsum) if wsum else None
            recs[sid] = {'sid': sid, 'name': rec.get('name', ''), 'class': rec.get('class', ''),
                         'history': h, 'analysis': an, 'reasoning': rs, 'final': final,
                         'updated': rec.get('updated', '')}
    return recs
