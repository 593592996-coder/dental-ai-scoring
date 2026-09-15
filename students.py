# -*- coding: utf-8 -*-
"""学生花名册 + 成绩导出（对齐学校教务成绩录入表格式）。

花名册放在本目录 `花名册/` 下，支持每个教学班一个文件：
  · 学校教务下载的 .xls（前若干行课程信息，表头含 *学号/*姓名/行政班/修读性质）
  · 普通 .xlsx / .csv（含 学号、姓名、班级 列即可）
学生进门按学号登录，自动带出姓名/行政班/修读性质。
导出时套用花名册原表格式回填成绩。
"""
import os
import csv
import xlrd
from xlutils.copy import copy as xl_copy
import xlwt

BASE = os.path.dirname(os.path.abspath(__file__))
ROSTER_DIR = os.path.join(BASE, '花名册')

# 学校成绩表中需要清空/回填的成绩列（按表头名定位）
SCORE_COLS = ['平时', '期末', '技能', '月考1', '月考2', '月考3', '综合成绩']


def norm(s):
    s = str(s if s is not None else '').strip()
    if s.endswith('.0') and s[:-2].isdigit():   # Excel 数字学号读成浮点
        s = s[:-2]
    return s


def _find_header(rows):
    """找含“学号”“姓名”的表头行，返回 (行号, [表头])。"""
    for i, r in enumerate(rows[:10]):
        line = ''.join(norm(c) for c in r)
        if '学号' in line and '姓名' in line:
            return i, [norm(c) for c in r]
    return None, None


def _col(header, *kws):
    for kw in kws:
        for j, h in enumerate(header):
            if h and kw in h:
                return j
    return None


def _parse_rows(rows, source):
    hidx, header = _find_header(rows)
    if header is None:
        return [], {}
    c_sid = _col(header, '学号', '学籍', '考号')
    c_name = _col(header, '姓名', '名字')
    c_cls = _col(header, '行政班', '班级')
    c_nat = _col(header, '修读性质', '修读')
    if c_sid is None:
        c_sid = 0
    if c_name is None:
        c_name = 1
    if c_cls is None:
        c_cls = 2

    # 抓课程/教学班元信息（学校表前几行）
    meta = {}
    for r in rows[:hidx]:
        line = norm(r[0]) if r else ''
        if line.startswith('教学班组成'):
            meta['class'] = line.split(':', 1)[-1].split('：', 1)[-1].strip()
        if line.startswith('教学班名称'):
            meta['teach_class'] = line.split(':', 1)[-1].split('：', 1)[-1].strip()

    students = []
    for r in rows[hidx + 1:]:
        if not r:
            continue
        sid = norm(r[c_sid]) if c_sid < len(r) else ''
        name = norm(r[c_name]) if c_name < len(r) else ''
        if not sid or not name or sid == '学号':
            continue
        klass = norm(r[c_cls]) if c_cls is not None and c_cls < len(r) else meta.get('class', '')
        nature = norm(r[c_nat]) if c_nat is not None and c_nat < len(r) else ''
        students.append({'sid': sid, 'name': name, 'class': klass,
                         'nature': nature or '初修', 'source': source})
    return students, meta


def _iter_sheet_rows_xls(path):
    wb = xlrd.open_workbook(path)
    for sh in wb.sheets():
        rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
        yield sh.name, rows


def _iter_sheet_rows_xlsx(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    for sh in wb.worksheets:
        rows = [list(r) for r in sh.iter_rows(values_only=True)]
        yield sh.title, rows
    wb.close()


def load_students():
    """返回全部学生列表（去重，按学号）。"""
    out, seen = [], set()
    if not os.path.isdir(ROSTER_DIR):
        return out
    for fn in sorted(os.listdir(ROSTER_DIR)):
        path = os.path.join(ROSTER_DIR, fn)
        if not os.path.isfile(path) or fn.startswith('~$'):
            continue
        ext = fn.lower().rsplit('.', 1)[-1] if '.' in fn else ''
        try:
            if ext == 'xls':
                sheets = _iter_sheet_rows_xls(path)
            elif ext == 'xlsx':
                sheets = _iter_sheet_rows_xlsx(path)
            elif ext == 'csv':
                with open(path, encoding='utf-8-sig') as f:
                    sheets = [(fn, list(csv.reader(f)))]
            else:
                continue
            for sheet_name, rows in sheets:
                students, _ = _parse_rows(rows, fn)
                for st in students:
                    if st['sid'] not in seen:
                        seen.add(st['sid'])
                        out.append(st)
        except Exception:
            continue
    return out


def load_roster():
    """返回 {学号: 学生信息}，供登录校验。"""
    return {st['sid']: st for st in load_students()}


def roster_exists():
    return bool(load_students())


def list_classes():
    kls = []
    for st in load_students():
        if st['class'] and st['class'] not in kls:
            kls.append(st['class'])
    return kls


# ───────── 保留学校格式：清空成绩 / 回填成绩 ─────────
def _school_layout(path):
    """返回 (sheet名, 表头行号, {成绩列名:列号}, 学号列, 姓名列)。"""
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    hidx, header = _find_header(rows)
    if hidx is None:
        return None
    cols = {name: _col(header, name) for name in SCORE_COLS}
    return {'sheet': sh.name, 'header_row': hidx,
            'cols': cols, 'sid_col': _col(header, '学号'),
            'name_col': _col(header, '姓名')}


def blank_workbook(src_path, dst_path):
    """复制学校原表、清空所有成绩列，保留学生名册与格式。"""
    rb = xlrd.open_workbook(src_path, formatting_info=True)
    wb = xl_copy(rb)
    ws = wb.get_sheet(0)
    sh = rb.sheet_by_index(0)
    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    layout = _school_layout(src_path)
    hr = layout['header_row']
    score_cols = [c for c in layout['cols'].values() if c is not None]
    style = xlwt.easyxf('align: horiz center, vert center; '
                        'borders: left thin, right thin, top thin, bottom thin')
    for r in range(hr + 1, sh.nrows):
        sid = norm(rows[r][layout['sid_col']]) if layout['sid_col'] < len(rows[r]) else ''
        name = norm(rows[r][layout['name_col']]) if layout['name_col'] < len(rows[r]) else ''
        if not sid or not name:
            continue
        for c in score_cols:
            ws.write(r, c, '', style)
    wb.save(dst_path)


def fill_workbook(src_path, dst_path, score_map):
    """在学校原表上按学号回填成绩，保留名册与格式。

    score_map: {学号: {成绩列名: 分数}}，列名取 SCORE_COLS。
    返回 (写入人数, 有成绩但不在本班名册的学号列表)。
    """
    rb = xlrd.open_workbook(src_path, formatting_info=True)
    sh = rb.sheet_by_index(0)
    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    layout = _school_layout(src_path)
    hr, cols = layout['header_row'], layout['cols']
    sid_col = layout['sid_col']

    roster_sids = set()
    row_by_sid = {}
    for r in range(hr + 1, sh.nrows):
        sid = norm(rows[r][sid_col]) if sid_col < len(rows[r]) else ''
        name = norm(rows[r][layout['name_col']]) if layout['name_col'] < len(rows[r]) else ''
        if sid and name:
            roster_sids.add(sid)
            row_by_sid[sid] = r

    wb = xl_copy(rb)
    ws = wb.get_sheet(0)
    style = xlwt.easyxf('align: horiz center, vert center; '
                        'borders: left thin, right thin, top thin, bottom thin')
    written = 0
    for sid, scores in score_map.items():
        r = row_by_sid.get(sid)
        if r is None:
            continue
        written += 1
        for col_name, val in scores.items():
            c = cols.get(col_name)
            if c is not None and val is not None and val != '':
                ws.write(r, c, val, style)
    wb.save(dst_path)
    extra = sorted(set(score_map) - roster_sids)
    return written, extra


def roster_source_files():
    """花名册目录里可作为学校模板回填的 .xls 文件列表。"""
    out = []
    if os.path.isdir(ROSTER_DIR):
        for fn in sorted(os.listdir(ROSTER_DIR)):
            if fn.lower().endswith('.xls') and not fn.startswith('~$'):
                out.append(os.path.join(ROSTER_DIR, fn))
    return out


def class_template_map():
    """{行政班: 学校模板文件路径}。"""
    m = {}
    for path in roster_source_files():
        try:
            for _, rows in _iter_sheet_rows_xls(path):
                students, meta = _parse_rows(rows, os.path.basename(path))
                kls = meta.get('class') or (students[0]['class'] if students else '')
                if kls:
                    m.setdefault(kls, path)
        except Exception:
            continue
    return m
