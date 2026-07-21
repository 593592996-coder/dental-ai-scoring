"""口腔AI模拟诊疗 — 三阶段：自由对话问诊→检查器械技术→病历书写"""
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from cases import CASES
import uuid, os, json, time
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'dental_consult_v3'

IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'images')
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)

@app.route('/')
def index():
    return render_template('index.html', cases=CASES)


@app.route('/api/cases')
def list_cases():
    return jsonify({cid:{'id':cid,'title':c['title'],'difficulty':c['difficulty'],'patient':c['patient']} for cid,c in CASES.items()})


@app.route('/api/start/<case_id>', methods=['POST'])
def start(case_id):
    if case_id not in CASES: return jsonify({'error':'病例不存在'}),404
    c = CASES[case_id]
    session.clear()
    session['case_id'] = case_id
    session['phase'] = 1
    session['history_log'] = []
    session['exam_sequence'] = []
    session['exam_details'] = {}
    session['exam_score'] = 0
    session['consult_id'] = uuid.uuid4().hex[:8]
    session['chat_log'] = []
    # 给图片加上完整URL路径
    images_with_url = []
    for img in c.get('images', []):
        img_copy = dict(img)
        if img_copy.get('file'):
            img_copy['url'] = f'/images/{img_copy["file"]}'
        images_with_url.append(img_copy)

    return jsonify({
        'chief_complaint': c['chief_complaint'],
        'images': images_with_url,
        'patient': c['patient'],
        'case_title': c['title']
    })


# ══════════ 阶段1: 自由对话问诊 ══════════
@app.route('/api/chat', methods=['POST'])
def chat():
    case_id = session.get('case_id')
    if not case_id: return jsonify({'error':'请先选择病例'}),400
    c = CASES[case_id]
    data = request.get_json()
    student_input = data.get('message', '').strip()

    if not student_input:
        return jsonify({'reply': '请描述你想了解的情况。', 'coverage': len(session.get('history_log',[]))})

    # 关键词匹配（最佳匹配策略）
    conv = c['conversation']
    best_answer = None
    best_keywords = ''
    best_score = 0

    for keywords, answer in conv.items():
        ks = keywords.split('|')
        # 计算匹配分数: 每命中一个关键词+1，关键词越长加分越多
        score = 0
        for k in ks:
            if k in student_input:
                score += 1 + len(k) * 0.1  # 长关键词权重更高
        if score > best_score:
            best_score = score
            best_answer = answer

    if best_answer:
        reply = best_answer
        matched_kws = [k for k in best_keywords.split('|') if k in student_input]
    else:
        matched_kws = []
        # 记录未匹配问题
        unmatched_file = os.path.join(LOG_DIR, 'unmatched_questions.json')
        try:
            unmatched = []
            if os.path.exists(unmatched_file):
                with open(unmatched_file, 'r', encoding='utf-8') as f: unmatched = json.load(f)
            unmatched.append({'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'question': student_input, 'case_id': case_id, 'case_title': c['title']})
            with open(unmatched_file, 'w', encoding='utf-8') as f: json.dump(unmatched[-100:], f, ensure_ascii=False, indent=2)
        except: pass
        reply = '我记不清了，你换个方式问问？'

    log = session.get('history_log', [])
    log.append({'student': student_input, 'patient': reply})
    session['history_log'] = log

    # 计算问诊覆盖度
    covered = sum(1 for kw in conv if any(k in ''.join(s['student'] for s in log) for k in kw.split('|')))
    total_kw = len(conv)
    coverage = min(100, int(covered / total_kw * 100)) if total_kw > 0 else 0

    # 记录详细日志
    log_entry = {
        'timestamp': datetime.now().strftime('%H:%M:%S'),
        'student': student_input,
        'patient': reply,
        'matched_keywords': [k for k in best_keywords.split('|') if k in student_input] if best_answer else [],
        'all_keywords': best_keywords if best_answer else '',
        'coverage': coverage,
        'case_id': case_id,
    }
    log_data = session.get('chat_log', [])
    log_data.append(log_entry)
    session['chat_log'] = log_data

    # 持久化到文件
    consult_log_file = os.path.join(LOG_DIR, f'{session.get("consult_id","unknown")}.json')
    try:
        with open(consult_log_file, 'w', encoding='utf-8') as f:
            json.dump({'case_id': case_id, 'case_title': c['title'], 'log': log_data}, f, ensure_ascii=False, indent=2)
    except: pass

    return jsonify({'reply': reply, 'coverage': coverage, 'matched': best_keywords.split('|') if best_answer else []})


@app.route('/api/phase1/done', methods=['POST'])
def phase1_done():
    session['phase'] = 2
    case_id = session.get('case_id')
    c = CASES[case_id]
    conv = c['conversation']
    log = session.get('history_log', [])

    # 统计每个关键词组是否被覆盖
    coverage_detail = []
    total_kw_groups = len(conv)
    covered_groups = 0
    for keywords in conv:
        ks = keywords.split('|')
        asked = any(any(k in s['student'] for k in ks) for s in log)
        if asked:
            covered_groups += 1
            coverage_detail.append({'keywords': keywords, 'covered': True, 'status': 'good'})
        else:
            coverage_detail.append({'keywords': keywords, 'covered': False, 'status': 'missed'})

    coverage_pct = int(covered_groups / total_kw_groups * 100) if total_kw_groups > 0 else 0

    # 按类别分组统计
    categories = {
        '主诉': ['位置','部位','哪里','多久','时间','几天','加重','诱因','缓解','情况'],
        '现病史': ['疼','痛','性质','感觉','自发','夜间','自己','药','处理','吃过'],
        '既往史': ['病','全身','身体','过敏','看过','牙科','以前','治'],
        '生活习惯': ['抽烟','喝酒','吸烟','职业','工作'],
    }
    cat_scores = {}
    cat_missed = {}
    for cat, kws in categories.items():
        covered = sum(1 for kw_g in conv if any(any(k in s['student'] for s in log) for k in kw_g.split('|') if any(ck in k for ck in kws)))
        total = sum(1 for kw_g in conv if any(any(ck in k for ck in kws) for k in kw_g.split('|')))
        cat_scores[cat] = {'covered': covered, 'total': total, 'pct': int(covered/max(total,1)*100)}
        if total > 0 and covered < total:
            cat_missed[cat] = [kw_g for kw_g in conv if any(any(ck in k for ck in kws) for k in kw_g.split('|')) and not any(any(k in s['student'] for s in log) for k in kw_g.split('|'))]

    # 评分
    score = int(coverage_pct * 1.0)  # 100分制

    # 生成改进建议
    suggestions = []
    for cat, missed_kws in cat_missed.items():
        if missed_kws:
            suggestions.append(f'{cat}方面遗漏: {", ".join(missed_kws[:2])}')

    return jsonify({
        'score': score, 'coverage_pct': coverage_pct,
        'covered_groups': covered_groups, 'total_groups': total_kw_groups,
        'coverage_detail': coverage_detail,
        'cat_scores': cat_scores,
        'suggestions': suggestions[:5],
        'message': '病史采集完成。请根据以上信息，设计口腔检查方案。',
        'exam_items': list(c['examination']['items'].keys()),
    })


# ══════════ 阶段2: 口腔检查（两步：顺序→器械技术） ══════════
@app.route('/api/exam/submit_sequence', methods=['POST'])
def submit_sequence():
    """学生提交检查顺序"""
    case_id = session.get('case_id')
    if not case_id: return jsonify({'error':''}),400
    c = CASES[case_id]
    data = request.get_json()
    student_seq = data.get('sequence', [])

    correct = c['examination']['correct_sequence']
    session['exam_sequence'] = student_seq

    # 比较顺序
    errors = []
    for i, item in enumerate(student_seq):
        if item in correct:
            expected_idx = correct.index(item)
            if abs(i - expected_idx) > 1:
                errors.append(f'"{item}"建议在第{expected_idx+1}步，你放在第{i+1}步')
    for ci in correct:
        if ci not in student_seq:
            errors.append(f'缺少：{ci}')

    seq_score = max(0, 10 - len(errors) * 2)
    return jsonify({'errors': errors, 'score': seq_score, 'correct': correct})


@app.route('/api/exam/submit_item', methods=['POST'])
def submit_exam_item():
    """学生对单个检查项目提交器械选择和技术要点"""
    case_id = session.get('case_id')
    if not case_id: return jsonify({'error':''}),400
    c = CASES[case_id]
    data = request.get_json()
    item = data.get('item', '')
    instruments = data.get('instruments', '')
    technique = data.get('technique', '')
    key_points_input = data.get('key_points', '')

    if item not in c['examination']['items']:
        return jsonify({'error': '检查项目不存在'})

    exam_item = c['examination']['items'][item]
    correct_instruments = set(''.join(exam_item['instruments']).replace('（','').replace('）',''))
    student_instruments = set(instruments.replace('（','').replace('）',''))

    # 器械评分
    instr_overlap = len(correct_instruments & student_instruments) / max(len(correct_instruments), 1)
    instr_score = min(10, int(instr_overlap * 10))

    # 技术要点评分
    correct_kps = set(exam_item.get('key_points', '').replace('；',';').split(';'))
    student_kps = set(key_points_input.replace('；',';').replace('，',',').split(','))
    kp_overlap = len(correct_kps & student_kps) / max(len(correct_kps), 1) if correct_kps else 0.5
    tech_score = min(10, int(kp_overlap * 10))

    # 操作描述评分（基于关键词覆盖）
    tech_keywords = exam_item.get('technique', '')
    desc_score = min(10, 5 + int(len(set(student_instruments)) / max(len(correct_instruments),1) * 5))

    total = instr_score + tech_score + desc_score
    session['exam_score'] = session.get('exam_score', 0) + total

    # 保存详情
    details = session.get('exam_details', {})
    details[item] = {'instruments': instruments, 'technique': technique, 'key_points': key_points_input, 'score': total}
    session['exam_details'] = details

    return jsonify({
        'finding': exam_item['finding'],
        'correct_instruments': exam_item['instruments'],
        'correct_technique': exam_item['technique'],
        'correct_key_points': exam_item['key_points'],
        'scores': {'instruments': instr_score, 'technique': tech_score, 'description': desc_score, 'total': total}
    })


@app.route('/api/phase2/done', methods=['POST'])
def phase2_done():
    session['phase'] = 3
    case_id = session.get('case_id')
    c = CASES[case_id]
    student_seq = session.get('exam_sequence', [])
    correct_seq = c['examination']['correct_sequence']
    details = session.get('exam_details', {})
    total_items = len(correct_seq)
    completed_items = len(details)

    # 1. 检查顺序评分
    seq_errors = []
    for i, item in enumerate(student_seq):
        if item in correct_seq:
            expected = correct_seq.index(item)
            if abs(i - expected) > 1:
                seq_errors.append(f'"{item}"应在第{expected+1}步')
    missing = [ci for ci in correct_seq if ci not in student_seq]
    seq_score = max(0, 15 - len(seq_errors)*3 - len(missing)*5)
    if missing: seq_errors.append(f'缺少: {", ".join(missing)}')

    # 2. 器械/技术评分
    exam_score = session.get('exam_score', 0)
    max_per_item = 30  # 每项满分30
    exam_pct = min(100, int(exam_score / (total_items * max_per_item) * 100)) if total_items > 0 else 0

    # 3. 综合
    total = int(seq_score * 0.3 + exam_pct * 0.7)

    # 改进建议
    suggestions = []
    if missing: suggestions.append(f'检查项目遗漏: {", ".join(missing)}')
    if seq_errors: suggestions.extend(seq_errors[:3])
    if exam_pct < 60: suggestions.append('器械选择或技术描述需加强，请参照标准答案对比学习')

    return jsonify({
        'scores': {'sequence': seq_score, 'technique': exam_pct, 'total': total},
        'completed': f'{completed_items}/{total_items}',
        'errors': seq_errors,
        'suggestions': suggestions,
        'key_findings': [f"{item}: {c['examination']['items'].get(item, {}).get('finding','')[:80]}..."
                        for item in student_seq[:5] if item in c['examination']['items']],
    })


# ══════════ 阶段3: 病历书写 ══════════
@app.route('/api/record/submit', methods=['POST'])
def submit_record():
    case_id = session.get('case_id')
    if not case_id: return jsonify({'error':''}),400
    c = CASES[case_id]
    data = request.get_json()
    rec = c['medical_record']

    student_diag = data.get('diagnosis', '').strip()
    correct = rec['diagnosis']
    acceptable = rec.get('acceptable_diag', [])

    if student_diag == correct: diag_score = 100
    elif any(a in student_diag or student_diag in a for a in acceptable): diag_score = 75
    else:
        kw_s = set(student_diag.replace('，',',').replace(' ','').split(','))
        kw_c = set(correct.replace('，',',').replace(' ','').split(','))
        overlap = len(kw_s & kw_c) / max(len(kw_c), 1)
        diag_score = int(max(15, overlap * 70))

    student_diff = data.get('differential', '')
    diff_correct = rec.get('differential', [])
    diff_score = sum(33 for d in diff_correct if d in student_diff) if diff_correct else 80
    diff_score = min(100, diff_score)

    student_tx = data.get('treatment_plan', '')
    tx_score = 60
    for kw, pts in {'根管':20,'开髓':10,'充填':10,'修复':10,'全冠':10,'活髓':15,'盖髓':15,'卫生宣教':5,'复查':5,'戒烟':5}.items():
        if kw in student_tx: tx_score += pts
    tx_score = min(100, tx_score)

    exam_s = session.get('exam_score', 0)
    exam_pct = min(100, exam_s)

    total = int(diag_score * 0.30 + diff_score * 0.15 + tx_score * 0.20 + exam_pct * 0.20 + 80 * 0.15)

    # 生成病历
    p = c['patient']
    record = f"""════════════════════════════════════
           口腔门诊病历
════════════════════════════════════
姓名: {p['name']}  性别: {p['gender']}  年龄: {p['age']}岁

【主诉】{c['chief_complaint']}

【现病史】(学生问诊采集)

【既往史】(学生问诊采集)

【口腔检查】
{(chr(10)).join(f'{item}: {c["examination"]["items"][item]["finding"]}' for item in c['examination']['correct_sequence'] if item in c['examination']['items'])}

【影像学检查】
{(chr(10)).join(f'{img["label"]}: {img["desc"]}' for img in c['images'])}

【诊断】{correct}
【鉴别诊断】{', '.join(diff_correct) if diff_correct else ''}

【治疗计划】
{(chr(10)).join('  '+t for t in rec['treatment'])}

【处置】
{rec['procedure']}

【医嘱】
{(chr(10)).join('  · '+o for o in rec['orders'])}

医师: __________  日期: __________"""

    return jsonify({
        'scores': {'diagnosis': diag_score, 'differential': diff_score, 'treatment': tx_score,
                   'examination': exam_pct, 'total': total},
        'correct': {'diagnosis': correct, 'differential': diff_correct, 'treatment': rec['treatment'],
                    'procedure': rec['procedure'], 'orders': rec['orders']},
        'record': record
    })


# ══════════ 教师后台 ══════════
@app.route('/api/teacher/stats/save', methods=['POST'])
def save_wordbank_edit():
    """在线编辑词库 — 教师新增/修改关键词"""
    data = request.get_json()
    case_id = data.get('case_id', '')
    keywords = data.get('keywords', '').strip()
    answer = data.get('answer', '').strip()
    action = data.get('action', 'add')  # add or delete

    if not case_id or case_id not in CASES: return jsonify({'error': '病例不存在'}), 400
    if not keywords or not answer: return jsonify({'error': '关键词和回答不能为空'}), 400

    c = CASES[case_id]

    if action == 'delete':
        # 删除关键词
        if keywords in c['conversation']:
            del c['conversation'][keywords]
        message = f'已删除关键词: {keywords}'
    else:
        # 新增或更新
        c['conversation'][keywords] = answer
        message = f'已{"更新" if keywords in c.get("conversation",{}) else "新增"}关键词: {keywords}'

    # 保存到cases.py
    save_cases_to_file()
    return jsonify({'success': True, 'message': message})


def save_cases_to_file():
    """将当前CASES保存到cases.py"""
    import pprint
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, 'cases.py')

    lines = ['"""口腔AI模拟诊疗系统 — 病例数据库（可由教师在线编辑）"""\n']
    lines.append('CASES = {\n')
    for cid, c in CASES.items():
        lines.append(f'    "{cid}": {{\n')
        lines.append(f'        "id": "{c["id"]}",\n')
        lines.append(f'        "title": "{c["title"]}",\n')
        lines.append(f'        "difficulty": "{c["difficulty"]}",\n')
        lines.append(f'        "level": {c["level"]},\n')
        p = c['patient']
        lines.append(f'        "patient": {{"name": "{p["name"]}", "gender": "{p["gender"]}", "age": {p["age"]}, "occupation": "{p.get("occupation","")}"}},\n')
        lines.append(f'        "chief_complaint": """{c["chief_complaint"]}""",\n')
        imgs = c.get('images', [])
        lines.append(f'        "images": [\n')
        for img in imgs:
            if img.get('file'):
                lines.append(f'            {{"label": "{img["label"]}", "desc": """{img["desc"]}""", "file": "{img["file"]}"}},\n')
            else:
                lines.append(f'            {{"label": "{img["label"]}", "desc": """{img["desc"]}"""}},\n')
        lines.append(f'        ],\n')
        lines.append(f'        "diagnosis_answer": """{c.get("diagnosis_answer","")}""",\n')

        conv = c.get('conversation', {})
        lines.append(f'        "conversation": {{\n')
        for kw, ans in conv.items():
            lines.append(f'            "{kw}": """{ans}""",\n')
        lines.append(f'        }},\n')

        exam = c.get('examination', {})
        lines.append(f'        "examination": {{\n')
        lines.append(f'            "correct_sequence": {exam.get("correct_sequence", [])},\n')
        lines.append(f'            "items": {{\n')
        for item_name, item in exam.get('items', {}).items():
            lines.append(f'                "{item_name}": {{\n')
            lines.append(f'                    "instruments": {item.get("instruments", [])},\n')
            lines.append(f'                    "technique": """{item.get("technique","")}""",\n')
            lines.append(f'                    "key_points": """{item.get("key_points","")}""",\n')
            lines.append(f'                    "finding": """{item.get("finding","")}""",\n')
            lines.append(f'                }},\n')
        lines.append(f'            }},\n')
        lines.append(f'        }},\n')

        rec = c.get('medical_record', {})
        lines.append(f'        "medical_record": {{\n')
        lines.append(f'            "diagnosis": """{rec.get("diagnosis","")}""",\n')
        lines.append(f'            "acceptable_diag": {rec.get("acceptable_diag", [])},\n')
        lines.append(f'            "differential": {rec.get("differential", [])},\n')
        lines.append(f'            "treatment": {rec.get("treatment", [])},\n')
        lines.append(f'            "procedure": """{rec.get("procedure","")}""",\n')
        lines.append(f'            "orders": {rec.get("orders", [])},\n')
        lines.append(f'        }},\n')
        lines.append(f'    }},\n')
    lines.append('}\n')

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


@app.route('/api/teacher/wordbank/<case_id>')
def get_wordbank(case_id):
    """获取某病例的完整词库"""
    if case_id not in CASES: return jsonify({}), 404
    c = CASES[case_id]
    return jsonify({
        'case_id': case_id,
        'case_title': c['title'],
        'conversation': c.get('conversation', {}),
        'exam_items': list(c.get('examination', {}).get('items', {}).keys()),
    })


@app.route('/api/teacher/unmatched')
def get_unmatched():
    """获取未匹配问题列表"""
    unmatched_file = os.path.join(LOG_DIR, 'unmatched_questions.json')
    if os.path.exists(unmatched_file):
        with open(unmatched_file, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify([])


@app.route('/teacher')
def teacher_dashboard():
    """教师端 — 查看所有学生的对话记录"""
    # 读取所有日志文件
    all_logs = []
    case_stats = {}
    for fname in os.listdir(LOG_DIR):
        if fname.endswith('.json'):
            try:
                with open(os.path.join(LOG_DIR, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data['consult_id'] = fname.replace('.json', '')
                all_logs.append(data)

                # 统计每个病例的使用次数
                cid = data.get('case_id', 'unknown')
                if cid not in case_stats:
                    case_stats[cid] = {'count': 0, 'title': data.get('case_title', ''), 'total_coverage': 0, 'sessions': 0}
                case_stats[cid]['count'] += 1
                case_stats[cid]['sessions'] += 1
                if data.get('log'):
                    last = data['log'][-1]
                    case_stats[cid]['total_coverage'] += last.get('coverage', 0)
            except: pass

    # 计算平均覆盖度
    for cid in case_stats:
        if case_stats[cid]['sessions'] > 0:
            case_stats[cid]['avg_coverage'] = round(case_stats[cid]['total_coverage'] / case_stats[cid]['sessions'])

    # 分类统计
    category_stats = {}
    for log_data in all_logs:
        for entry in log_data.get('log', []):
            cat = classify_question(entry.get('student', ''))
            if cat not in category_stats:
                category_stats[cat] = {'count': 0, 'total': 0}
            category_stats[cat]['count'] += 1

    # 排序:最大覆盖率
    question_cats = {}
    for log_data in all_logs:
        for entry in log_data.get('log', []):
            q = entry.get('student', '')
            cat = classify_question(q)
            if q not in question_cats:
                question_cats[q] = {'category': cat, 'count': 0, 'answers': []}
            question_cats[q]['count'] += 1
            if entry.get('patient'):
                question_cats[q]['answers'].append(entry['patient'][:80])

    return render_template('teacher.html',
                          logs=all_logs, case_stats=case_stats,
                          category_stats=category_stats, question_cats=question_cats,
                          total_sessions=len(all_logs))


def classify_question(text):
    """将学生问题分类"""
    rules = [
        ('主诉-部位', ['位置', '部位', '哪里', '哪个牙']),
        ('主诉-时间', ['多久', '多长时间', '几天', '什么时候']),
        ('主诉-诱因', ['加重', '诱因', '什么情况', '怎样会']),
        ('现病史-疼痛', ['疼', '痛', '感觉', '性质', '怎么']),
        ('现病史-自发痛', ['自己', '自发', '夜间', '晚上', '睡觉']),
        ('现病史-用药', ['药', '吃过', '处理', '用']),
        ('既往史-全身病', ['病', '全身', '身体']),
        ('既往史-过敏', ['过敏']),
        ('既往史-牙科史', ['看过', '牙科', '以前', '治过']),
        ('生活习惯', ['抽烟', '喝酒', '吸烟']),
        ('基本信息', ['职业', '工作', '学校', '几岁', '多大']),
        ('外伤原因', ['受伤', '摔', '撞', '磕']),
        ('松动情况', ['松', '晃']),
    ]
    for cat, keywords in rules:
        if any(k in text for k in keywords):
            return cat
    return '其他'


@app.route('/api/teacher/log/<consult_id>')
def view_log_detail(consult_id):
    """查看单个对话详情"""
    log_file = os.path.join(LOG_DIR, f'{consult_id}.json')
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'error': '不存在'}), 404


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5051)
