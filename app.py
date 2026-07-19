#!/usr/bin/env python3
"""
II类洞AI评分系统 — Flask Web应用
支持：学生上传照片 → AI分析 → 评分报告 → 教师dashboard
"""

import os
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, send_from_directory, session, send_file)
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from io import BytesIO

from scoring_engine_v2 import II类洞评分引擎V2, SCORING_CONFIG

# ── App Setup ──
BASE_DIR = Path(__file__).parent.absolute()
UPLOAD_FOLDER = BASE_DIR / 'uploads'
REPORT_FOLDER = BASE_DIR / 'reports'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'tiff'}

app = Flask(__name__)
app.secret_key = 'kouqiang_neike_2026_ai_scoring'
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

UPLOAD_FOLDER.mkdir(exist_ok=True)
REPORT_FOLDER.mkdir(exist_ok=True)

# 全局评分历史（简化版，生产环境应使用数据库）
scoring_history = []

# 启动时加载历史报告
for f in sorted(REPORT_FOLDER.glob('*.json')):
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            scoring_history.append(json.load(fh))
    except:
        pass

engine = II类洞评分引擎V2()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Routes ──
@app.route('/')
def index():
    """学生端首页 — 上传照片"""
    return render_template('index.html', config=SCORING_CONFIG)


@app.route('/analyze', methods=['POST'])
def analyze():
    """分析上传的照片"""
    if 'photos' not in request.files:
        return jsonify({'error': '未上传照片'}), 400

    files = request.files.getlist('photos')
    student_name = request.form.get('student_name', '匿名')
    student_class = request.form.get('student_class', '未知班级')
    tooth_type = request.form.get('tooth_type', 'real')
    operation_time = request.form.get('operation_time', None)

    if operation_time:
        try:
            operation_time = float(operation_time)
        except ValueError:
            operation_time = None

    # 保存上传的照片
    saved_paths = []
    session_id = uuid.uuid4().hex[:8]
    for i, file in enumerate(files):
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f'{session_id}_{i}_{int(time.time())}.{ext}'
            filepath = UPLOAD_FOLDER / filename
            file.save(str(filepath))
            saved_paths.append(str(filepath))

    if not saved_paths:
        return jsonify({'error': '没有有效的照片文件（支持jpg/png/bmp）'}), 400

    # 分析每张照片，取最佳结果
    all_reports = []
    for path in saved_paths:
        report = engine.analyze(path, operation_time=operation_time, tooth_type=tooth_type)
        all_reports.append(report)

    # 选择总分最高的报告
    best_report = max(all_reports, key=lambda r: r.total_score)

    # 构建响应
    dimensions_data = []
    for d in best_report.dimensions:
        dimensions_data.append({
            'name': d.name,
            'score': d.score,
            'max_score': d.max_score,
            'percentage': round(d.score / d.max_score * 100, 1) if d.max_score > 0 else 0,
            'detail': d.detail,
            'status': d.status,
            'unit': d.unit,
            'raw_value': d.raw_value,
            'process_analysis': d.process_analysis,
            'targeted_suggestion': d.targeted_suggestion,
            'sub_scores': d.sub_scores if hasattr(d, 'sub_scores') else [],
        })

    result = {
        'session_id': session_id,
        'student_name': student_name,
        'student_class': student_class,
        'total_score': round(best_report.total_score, 1),
        'max_total': best_report.max_total,
        'percentage': round(best_report.total_score / best_report.max_total * 100, 1),
        'grade': ('优秀' if best_report.total_score >= 90 else
                  '良好' if best_report.total_score >= 80 else
                  '中等' if best_report.total_score >= 70 else
                  '及格' if best_report.total_score >= 60 else '不及格'),
        'dimensions': dimensions_data,
        'problem_areas': best_report.problem_areas,
        'suggestions': [d.targeted_suggestion for d in best_report.dimensions
                       if d.status in ('warning', 'bad') and d.targeted_suggestion][:5],
        'photo_count': len(saved_paths),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'overall_assessment': best_report.overall_assessment,
        'strengths': best_report.strengths,
        'weaknesses': best_report.weaknesses,
    }

    # 保存到历史记录
    scoring_history.append(result)
    if len(scoring_history) > 500:  # 保留最近500条
        scoring_history.pop(0)

    # 保存JSON报告
    report_json_path = REPORT_FOLDER / f'{session_id}.json'
    with open(report_json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return jsonify(result)


@app.route('/api/export')
def export_excel():
    """导出全班评分为Excel"""
    # 如果没有真实数据，加载所有保存的报告
    data_source = scoring_history if scoring_history else []
    if not data_source:
        # 尝试从reports文件夹加载
        for f in sorted(REPORT_FOLDER.glob('*.json')):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data_source.append(json.load(fh))
            except:
                pass

    if not data_source:
        return '暂无评分数据，请先进行至少一次评分后再导出。', 404

    wb = Workbook()

    # ── Sheet 1: 汇总表 ──
    ws1 = wb.active
    ws1.title = "评分汇总"

    # Style
    header_font = Font(name='微软雅黑', size=11, bold=True)
    title_font = Font(name='微软雅黑', size=14, bold=True)
    cell_font = Font(name='微软雅黑', size=10)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left = Alignment(horizontal='left', vertical='center', wrap_text=True)
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    header_fill = PatternFill(start_color='1B3A5C', end_color='1B3A5C', fill_type='solid')
    header_font_white = Font(name='微软雅黑', size=11, bold=True, color='FFFFFF')

    # Title
    ws1.merge_cells('A1:P1')
    ws1.cell(row=1, column=1, value='II类洞制备AI评分汇总表').font = title_font
    ws1.cell(row=1, column=1).alignment = center

    # Headers
    headers = ['序号', '学生姓名', '班级', '总分', '等级', '外形轮廓(20)', '鸠尾峡(15)', '洞深(10)',
               '髓壁平面度(8)', '侧壁垂直度(7)', '点线角锐度(10)', '邻面盒形(10)', '洞缘光滑度(5)',
               '邻牙保护(10)', '操作过程(5)', '分析时间']

    for col, h in enumerate(headers, 1):
        cell = ws1.cell(row=2, column=col, value=h)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.alignment = center
        cell.border = thin_border

    # Data
    sorted_data = sorted(data_source, key=lambda x: x.get('total_score', 0), reverse=True)
    for i, d in enumerate(sorted_data, 1):
        row = i + 2
        ws1.cell(row=row, column=1, value=i).font = cell_font
        ws1.cell(row=row, column=1).alignment = center
        ws1.cell(row=row, column=2, value=d.get('student_name', '')).font = cell_font
        ws1.cell(row=row, column=2).alignment = center
        ws1.cell(row=row, column=3, value=d.get('student_class', '')).font = cell_font
        ws1.cell(row=row, column=3).alignment = center
        ws1.cell(row=row, column=4, value=d.get('total_score', 0)).font = Font(name='微软雅黑', size=10, bold=True)
        ws1.cell(row=row, column=4).alignment = center
        ws1.cell(row=row, column=5, value=d.get('grade', '')).font = cell_font
        ws1.cell(row=row, column=5).alignment = center

        # Dimension scores
        dims = {x['name']: x for x in d.get('dimensions', [])}
        dim_order = ['外形轮廓', '鸠尾峡比例', '洞深', '髓壁平面度', '侧壁垂直度',
                     '点线角锐度', '邻面盒形', '洞缘光滑度', '邻牙保护', '操作过程']
        for j, dim_name in enumerate(dim_order):
            dim = dims.get(dim_name, {})
            score = dim.get('score', '')
            max_s = dim.get('max_score', '')
            cell = ws1.cell(row=row, column=6+j, value=f'{score}/{max_s}' if score != '' else '')
            cell.font = cell_font
            cell.alignment = center

        ws1.cell(row=row, column=16, value=d.get('timestamp', '')).font = cell_font
        ws1.cell(row=row, column=16).alignment = center

        for col in range(1, 17):
            ws1.cell(row=row, column=col).border = thin_border

        # 等级着色
        grade_colors = {'优秀': '27ae60', '良好': '2B7BEC', '中等': 'f39c12', '及格': 'e67e22', '不及格': 'c0392b'}
        g = d.get('grade', '')
        if g in grade_colors:
            ws1.cell(row=row, column=5).font = Font(name='微软雅黑', size=10, bold=True, color=grade_colors[g])

    # 统计行
    stat_row = len(sorted_data) + 3
    ws1.merge_cells(start_row=stat_row, start_column=1, end_row=stat_row, end_column=3)
    ws1.cell(row=stat_row, column=1, value=f'合计: {len(sorted_data)}人').font = Font(name='微软雅黑', size=11, bold=True)
    ws1.cell(row=stat_row, column=1).alignment = center
    scores = [d.get('total_score', 0) for d in sorted_data]
    ws1.cell(row=stat_row, column=4, value=f'平均: {sum(scores)/len(scores):.1f}' if scores else 'N/A').font = Font(name='微软雅黑', size=11, bold=True)
    ws1.cell(row=stat_row, column=4).alignment = center
    pass_count = sum(1 for s in scores if s >= 60)
    ws1.cell(row=stat_row, column=5, value=f'及格率: {pass_count/len(scores)*100:.1f}%' if scores else 'N/A').font = Font(name='微软雅黑', size=11, bold=True)
    ws1.cell(row=stat_row, column=5).alignment = center
    for col in range(1, 17):
        ws1.cell(row=stat_row, column=col).border = thin_border

    # ── Sheet 2: 详细报告 ──
    ws2 = wb.create_sheet("详细分析")
    for i, d in enumerate(sorted_data[:30]):  # 最多30人详细
        row_start = i * 20 + 1
        # 学生信息
        ws2.merge_cells(start_row=row_start, start_column=1, end_row=row_start, end_column=6)
        ws2.cell(row=row_start, column=1,
                 value=f'{d.get("student_name","")} | {d.get("student_class","")} | 总分: {d.get("total_score",0)} | {d.get("grade","")}').font = Font(name='微软雅黑', size=13, bold=True)

        dims = {x['name']: x for x in d.get('dimensions', [])}
        dim_order = ['外形轮廓', '鸠尾峡比例', '洞深', '髓壁平面度', '侧壁垂直度',
                     '点线角锐度', '邻面盒形', '洞缘光滑度', '邻牙保护', '操作过程']

        for j, dim_name in enumerate(dim_order):
            row_d = row_start + 1 + j
            dim = dims.get(dim_name, {})
            ws2.cell(row=row_d, column=1, value=dim_name).font = Font(name='微软雅黑', size=10, bold=True)
            ws2.cell(row=row_d, column=2, value=f'{dim.get("score","")}/{dim.get("max_score","")}').font = cell_font
            detail = dim.get('detail', '')
            suggestion = dim.get('targeted_suggestion', '')
            ws2.cell(row=row_d, column=3, value=detail).font = cell_font
            ws2.cell(row=row_d, column=4, value=suggestion).font = cell_font

        # 整体评估
        row_d = row_start + 12
        ws2.cell(row=row_d, column=1, value='整体评估').font = Font(name='微软雅黑', size=10, bold=True)
        ws2.cell(row=row_d, column=2, value=d.get('overall_assessment','')).font = cell_font
        ws2.cell(row=row_d + 1, column=1, value='强项').font = Font(name='微软雅黑', size=10, bold=True)
        ws2.cell(row=row_d + 1, column=2, value=' | '.join(d.get('strengths', [])[:3])).font = cell_font
        ws2.cell(row=row_d + 2, column=1, value='弱项').font = Font(name='微软雅黑', size=10, bold=True)
        ws2.cell(row=row_d + 2, column=2, value=' | '.join(d.get('weaknesses', [])[:3])).font = cell_font

    # 列宽
    ws1.column_dimensions['A'].width = 6
    ws1.column_dimensions['B'].width = 12
    ws1.column_dimensions['C'].width = 14
    for col in range(4, 17):
        ws1.column_dimensions[chr(64+col)].width = 13

    # 保存到内存
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'II类洞评分汇总_{datetime.now().strftime("%Y%m%d")}.xlsx'
    )


@app.route('/report/<session_id>')
def view_report(session_id):
    """查看评分报告"""
    report_path = REPORT_FOLDER / f'{session_id}.json'
    if report_path.exists():
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        return render_template('report.html', report=report)
    return '报告不存在', 404


@app.route('/dashboard')
def dashboard():
    """教师端 — 全班统计分析"""
    if not scoring_history:
        # 生成模拟数据用于演示
        import random
        random.seed(42)
        demo_data = []
        for i in range(59):
            base = random.gauss(73, 12)
            base = max(30, min(98, base))
            demo_data.append({
                'student_name': f'学生{i+1:02d}',
                'student_class': '25口腔1班',
                'total_score': round(base, 1),
                'percentage': round(base, 1),
                'grade': ('优秀' if base >= 90 else '良好' if base >= 80 else
                          '中等' if base >= 70 else '及格' if base >= 60 else '不及格'),
                'dimensions': [
                    {'name': '外形轮廓', 'score': round(random.gauss(16, 3), 1), 'max_score': 20},
                    {'name': '鸠尾峡比例', 'score': round(random.gauss(11, 3), 1), 'max_score': 15},
                    {'name': '洞深', 'score': round(random.gauss(7, 2), 1), 'max_score': 10},
                    {'name': '髓壁平面度', 'score': round(random.gauss(5, 2.5), 1), 'max_score': 8},
                    {'name': '侧壁垂直度', 'score': round(random.gauss(4.5, 2), 1), 'max_score': 7},
                    {'name': '点线角锐度', 'score': round(random.gauss(7, 2), 1), 'max_score': 10},
                    {'name': '邻面盒形', 'score': round(random.gauss(7.5, 1.8), 1), 'max_score': 10},
                    {'name': '洞缘光滑度', 'score': round(random.gauss(4, 0.8), 1), 'max_score': 5},
                    {'name': '邻牙保护', 'score': round(random.gauss(8.5, 1.5), 1), 'max_score': 10},
                    {'name': '操作过程', 'score': round(random.gauss(3.5, 1), 1), 'max_score': 5},
                ],
            })
        history = demo_data
    else:
        history = scoring_history

    # 统计分析
    scores = [h['total_score'] for h in history]
    avg_score = sum(scores) / len(scores) if scores else 0
    pass_rate = sum(1 for s in scores if s >= 60) / len(scores) * 100 if scores else 0

    # 分数分布
    distribution = {'<60': 0, '60-69': 0, '70-79': 0, '80-89': 0, '90-100': 0}
    for s in scores:
        if s < 60: distribution['<60'] += 1
        elif s < 70: distribution['60-69'] += 1
        elif s < 80: distribution['70-79'] += 1
        elif s < 90: distribution['80-89'] += 1
        else: distribution['90-100'] += 1

    # 维度薄弱点分析
    dim_avg_scores = {}
    dim_names = list(SCORING_CONFIG.keys())
    dim_labels = {k: v['desc'] for k, v in SCORING_CONFIG.items()}
    for h in history:
        for d in h.get('dimensions', []):
            name = d['name']
            if name not in dim_avg_scores:
                dim_avg_scores[name] = {'total': 0, 'max': 0, 'count': 0}
            dim_avg_scores[name]['total'] += d['score']
            dim_avg_scores[name]['max'] += d['max_score']
            dim_avg_scores[name]['count'] += 1

    dim_analysis = []
    for name, data in dim_avg_scores.items():
        if data['count'] > 0:
            loss_rate = round((1 - data['total'] / data['max']) * 100, 1)
            dim_analysis.append({
                'name': name,
                'avg_score': round(data['total'] / data['count'], 1),
                'max_score': round(data['max'] / data['count'], 1),
                'loss_rate': loss_rate,
            })
    dim_analysis.sort(key=lambda x: x['loss_rate'], reverse=True)

    return render_template('dashboard.html',
                           history=history,
                           avg_score=round(avg_score, 1),
                           pass_rate=round(pass_rate, 1),
                           distribution=distribution,
                           dim_analysis=dim_analysis,
                           total_students=len(history),
                           config=SCORING_CONFIG)


@app.route('/api/history')
def api_history():
    """API: 获取评分历史"""
    return jsonify(scoring_history[-20:])  # 最近20条


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


# ── Main ──
if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5050))
    print('=' * 60)
    print('  II类洞AI评分系统 v1.0')
    print('  学生端: http://localhost:5050/')
    print('  教师端: http://localhost:5050/dashboard')
    print('=' * 60)
    app.run(debug=False, host='0.0.0.0', port=port)
