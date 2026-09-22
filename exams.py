# -*- coding: utf-8 -*-
"""考试模式核心（不依赖 Flask，路由层负责收发，本文件只管规则和数据）。

设计要点：
- 考试 = 名称 + 板块 + 参加班级 + 起止时间 + 选择题 + 收卷规则；
- 学生在时间窗口内、班级匹配、只能交一次；交完即锁分，学生端看不到成绩；
- AI 在收卷时于后台自动打分，与练习成绩完全分开存储（exam_data/）；
- 练习端口按"板块 + 班级 + 时间窗口"定时开放，未开放一律拦截。

数据目录 exam_data/（已加入 .gitignore，成绩和答卷不进 GitHub）：
  exams.json                          全部考试配置
  practice.json                       各板块练习端口开放窗口
  submissions/{exam_id}/{sid}.json    每人一份锁分答卷
"""
import os
import json
import uuid
import shutil
from datetime import datetime

from students import load_students

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, 'exam_data')
SUB_DIR = os.path.join(DATA_DIR, 'submissions')
FILM_DIR = os.path.join(DATA_DIR, 'films')
EXAMS_FILE = os.path.join(DATA_DIR, 'exams.json')
PRACTICE_FILE = os.path.join(DATA_DIR, 'practice.json')

os.makedirs(SUB_DIR, exist_ok=True)
os.makedirs(FILM_DIR, exist_ok=True)

# 考试形式：
#  xray_upload = 学生上传自己的X光片，AI给成品打分（原有）
#  xray_read   = 老师发一张片，学生对着片做客观判读题（新增）

ALL_CLASSES = 'ALL'          # 班级字段取此值表示全体
TEACHER_SID = 'abc123'       # 教师体验账号，任何考试都可进（成绩单独标记）

DT_FMT = '%Y-%m-%d %H:%M'


# ───────── 时间与基础读写 ─────────
def parse_dt(text):
    """'2026-09-24 08:00' -> datetime；失败返回 None。"""
    try:
        return datetime.strptime((text or '').strip(), DT_FMT)
    except Exception:
        return None


def now_dt():
    return datetime.now()


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


def _save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ───────── 考试配置 ─────────
def list_exams(module=None):
    exams = _load_json(EXAMS_FILE, [])
    if module:
        exams = [e for e in exams if e.get('module') == module]
    return sorted(exams, key=lambda e: e.get('created_at', ''), reverse=True)


def get_exam(exam_id):
    for e in _load_json(EXAMS_FILE, []):
        if e.get('id') == exam_id:
            return e
    return None


def _valid_questions(questions):
    for item in questions or []:
        if len(item.get('options', [])) != 4 or item.get('answer') not in (0, 1, 2, 3):
            return False
    return True


def create_exam(name, module, classes, start, end, kind='xray_upload',
                quiz=None, quiz_max=20, questions=None, film_src=None, note=''):
    """新建考试。classes 为班级列表或 ['ALL']。
    kind:
      xray_upload — 学生上传自己的X光片，AI给成品打分；quiz 为前置选择题；
      xray_read   — 老师发一张片(film_src)，学生对着片做 questions 客观判读题。
    quiz/questions: [{'q': 题干, 'options': [4个选项], 'answer': 正确序号}]
    返回 (exam, error)；校验不通过时 exam 为 None。"""
    name = (name or '').strip()
    if not name:
        return None, '请填写考试名称'
    if module not in ('xray',):                    # 先只做 X 光，后续板块再放开
        return None, '暂只支持根管X光片板块'
    if kind not in ('xray_upload', 'xray_read'):
        return None, '考试形式无效'
    classes = [c for c in (classes or []) if c]
    if not classes:
        return None, '请选择参加班级'
    s_dt, e_dt = parse_dt(start), parse_dt(end)
    if not s_dt or not e_dt:
        return None, '起止时间格式应为：2026-09-24 08:00'
    if e_dt <= s_dt:
        return None, '结束时间必须晚于开始时间'

    exam = {'id': 'exam_' + uuid.uuid4().hex[:8],
            'name': name, 'module': module, 'kind': kind,
            'classes': classes,
            'start': s_dt.strftime(DT_FMT), 'end': e_dt.strftime(DT_FMT),
            'note': (note or '').strip(),
            'created_at': datetime.now().strftime(DT_FMT)}

    if kind == 'xray_read':
        questions = questions or []
        if not questions:
            return None, '请至少出一道判读题'
        if not _valid_questions(questions):
            return None, '每道判读题必须有4个选项且标出正确答案'
        if not film_src or not os.path.exists(film_src):
            return None, '请先指定要发给学生看的X光片'
        film_name = f'{exam["id"]}.jpg'
        shutil.copyfile(film_src, os.path.join(FILM_DIR, film_name))
        exam['film'] = film_name
        exam['questions'] = questions
    else:
        quiz = quiz or []
        if quiz and not _valid_questions(quiz):
            return None, '每道选择题必须有4个选项且标出正确答案'
        exam['quiz'] = quiz
        exam['quiz_max'] = int(quiz_max) if quiz else 0
        exam['skill_max'] = (100 - int(quiz_max)) if quiz else 100

    exams = _load_json(EXAMS_FILE, [])
    exams.append(exam)
    _save_json(EXAMS_FILE, exams)
    return exam, None


def delete_exam(exam_id):
    """删除考试；已有学生提交则拒删（防误删证据）。返回 error 或 None。"""
    if os.path.isdir(os.path.join(SUB_DIR, exam_id)) and \
            os.listdir(os.path.join(SUB_DIR, exam_id)):
        return '已有学生提交，不能删除（可改名或忽略本场考试）'
    exams = [e for e in _load_json(EXAMS_FILE, []) if e.get('id') != exam_id]
    _save_json(EXAMS_FILE, exams)
    return None


# ───────── 资格与状态 ─────────
def _class_allowed(exam, klass):
    if exam['classes'] == [ALL_CLASSES]:
        return True
    return (klass or '') in exam['classes']


def exam_status(exam_id, sid, klass, at=None):
    """返回给学生端的状态码：
    not_found / class_not_allowed / not_started / ended / submitted / open"""
    exam = get_exam(exam_id)
    if not exam:
        return 'not_found', None
    if sid != TEACHER_SID and not _class_allowed(exam, klass):
        return 'class_not_allowed', exam
    at = at or now_dt()
    if get_submission(exam_id, sid):
        return 'submitted', exam
    if at < parse_dt(exam['start']):
        return 'not_started', exam
    if at > parse_dt(exam['end']):
        return 'ended', exam
    return 'open', exam


# ───────── 收卷与锁分 ─────────
def _sub_path(exam_id, sid):
    return os.path.join(SUB_DIR, exam_id, f'{sid}.json')


def get_submission(exam_id, sid):
    path = _sub_path(exam_id, sid)
    return _load_json(path, None) if os.path.exists(path) else None


def grade_quiz(exam, answers):
    """选择题判分。answers: {'q0': 选择序号, ...}。返回 (得分, 满分, 明细)。"""
    quiz = exam.get('quiz') or []
    if not quiz:
        return None, 0, []
    per = exam['quiz_max'] / len(quiz)
    detail, got = [], 0.0
    for i, item in enumerate(quiz):
        chosen = answers.get(f'q{i}')
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = -1
        ok = chosen == item['answer']
        if ok:
            got += per
        detail.append({'chosen': chosen if chosen >= 0 else None,
                       'correct': item['answer'], 'ok': ok})
    return round(got, 1), exam['quiz_max'], detail


def submit(exam_id, sid, name, klass, quiz_answers, image_paths, scorer=None):
    """收卷：判选择题 → AI 后台打分（学生看不到）→ 锁存。
    scorer: 引擎 analyze 函数，收一张图片路径返回带 total_score 的报告；
            不传或分析失败时 skill 分留空，标记 need_review 由老师处理。
    返回 (submission, error)。"""
    status_code, exam = exam_status(exam_id, sid, klass)
    if not exam:
        return None, '考试不存在'
    if status_code == 'submitted':
        return None, '你已经提交过，不能重复提交'
    if status_code in ('not_started', 'ended'):
        return None, '当前不在考试时间内'
    if status_code == 'class_not_allowed':
        return None, '你所在的班级不在本场考试名单内'
    if not image_paths:
        return None, '请上传X光片后再提交'

    quiz_got, quiz_full, quiz_detail = grade_quiz(exam, quiz_answers or {})

    # AI 后台判分：逐张尝试，取最高分（与练习端同一引擎、同一把尺子）
    skill_score, skill_used = None, None
    skill_error = ''
    if scorer:
        for p in image_paths:
            try:
                r = scorer(p)
                val = getattr(r, 'total_score', None)
                if isinstance(val, (int, float)):
                    if skill_score is None or val > skill_score:
                        skill_score = round(float(val), 1)
                        skill_used = os.path.basename(p)
            except Exception as e:
                skill_error = str(e)
    else:
        skill_error = '未配置评分引擎'

    total = None
    if skill_score is not None:
        total = round((quiz_got or 0) + skill_score / 100 * exam['skill_max'], 1)

    submission = {
        'exam_id': exam_id, 'sid': sid,
        'name': name, 'class': klass,
        'is_teacher': sid == TEACHER_SID,
        'quiz_score': quiz_got, 'quiz_full': quiz_full, 'quiz_detail': quiz_detail,
        'skill_score': skill_score,                 # AI 对 X 光片打的 0-100
        'skill_image': skill_used,
        'total_score': total,                      # 选择+判读合成的锁定总分
        'status': 'graded' if total is not None else 'need_review',
        'images': [os.path.basename(p) for p in image_paths],
        'skill_error': skill_error if skill_score is None else '',
        'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    os.makedirs(os.path.join(SUB_DIR, exam_id), exist_ok=True)
    _save_json(_sub_path(exam_id, sid), submission)
    return submission, None


def film_path(exam):
    """该场看片判读考试所用X光片的完整路径。"""
    fn = exam.get('film')
    return os.path.join(FILM_DIR, fn) if fn else None


def grade_reading(exam, answers):
    """判读题判分。answers: {'r0': 选择序号, ...}。返回 (得分0-100, 明细)。"""
    qs = exam.get('questions') or []
    per = 100 / len(qs)
    detail, got = [], 0.0
    for i, item in enumerate(qs):
        chosen = answers.get(f'r{i}')
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = -1
        ok = chosen == item['answer']
        if ok:
            got += per
        detail.append({'chosen': chosen if chosen >= 0 else None,
                       'correct': item['answer'], 'ok': ok})
    return round(got, 1), detail


def submit_reading(exam_id, sid, name, klass, answers):
    """看片判读收卷：对照标准答案自动判分并锁存，学生端看不到分。"""
    status_code, exam = exam_status(exam_id, sid, klass)
    if not exam:
        return None, '考试不存在'
    if status_code == 'submitted':
        return None, '你已经提交过，不能重复提交'
    if status_code in ('not_started', 'ended'):
        return None, '当前不在考试时间内'
    if status_code == 'class_not_allowed':
        return None, '你所在的班级不在本场考试名单内'

    qs = exam.get('questions') or []
    for i in range(len(qs)):
        if answers.get(f'r{i}') is None:
            return None, f'第{i+1}题还没有作答'

    score, detail = grade_reading(exam, answers)
    submission = {
        'exam_id': exam_id, 'sid': sid,
        'name': name, 'class': klass,
        'is_teacher': sid == TEACHER_SID,
        'reading_score': score, 'reading_detail': detail,
        'total_score': score,
        'status': 'graded',
        'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    os.makedirs(os.path.join(SUB_DIR, exam_id), exist_ok=True)
    _save_json(_sub_path(exam_id, sid), submission)
    return submission, None


def list_submissions(exam_id, include_teacher=False):
    d = os.path.join(SUB_DIR, exam_id)
    out = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.json'):
                continue
            sub = _load_json(os.path.join(d, fn), None)
            if sub and (include_teacher or not sub.get('is_teacher')):
                out.append(sub)
    out.sort(key=lambda s: (s.get('class', ''), s.get('sid', '')))
    return out


def expected_students(exam):
    """应考名单（取自花名册并按班级过滤），用于出勤/缺考统计。"""
    out = []
    for st in load_students():
        if exam['classes'] == [ALL_CLASSES] or st['class'] in exam['classes']:
            out.append(st)
    return out


# ───────── 练习端口定时开放 ─────────
def _practice_all():
    return _load_json(PRACTICE_FILE, {})


def set_practice_window(module, classes, start, end):
    """设置某板块练习端口的开放窗口（窗口外一律关闭）。
    返回 error 或 None。"""
    classes = [c for c in (classes or []) if c]
    if not classes:
        return '请选择开放班级'
    s_dt, e_dt = parse_dt(start), parse_dt(end)
    if not s_dt or not e_dt or e_dt <= s_dt:
        return '请检查开放起止时间'
    data = _practice_all()
    data[module] = {'classes': classes,
                    'start': s_dt.strftime(DT_FMT), 'end': e_dt.strftime(DT_FMT)}
    _save_json(PRACTICE_FILE, data)
    return None


def clear_practice_window(module):
    data = _practice_all()
    data.pop(module, None)
    _save_json(PRACTICE_FILE, data)


def get_practice_window(module):
    return _practice_all().get(module)


def practice_allowed(module, sid, klass, at=None):
    """练习端口此刻是否对此学生开放。教师体验账号恒为放行（仅用于试用）。"""
    if sid == TEACHER_SID:
        return True
    win = get_practice_window(module)
    if not win:
        return False
    if win['classes'] != [ALL_CLASSES] and (klass or '') not in win['classes']:
        return False
    at = at or now_dt()
    return parse_dt(win['start']) <= at <= parse_dt(win['end'])
