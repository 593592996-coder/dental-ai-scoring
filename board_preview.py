# -*- coding: utf-8 -*-
"""学情看板 · 预览稿生成器（一次性脚本，不上云）

把真实数据 + board.js + 截图组件全部内联成一个自包含 HTML，
双击即开、离线可用、班级/板块可切、导出按钮可用 —— 先看效果，再接进教师后台。

用法：python3 board_preview.py
产出：~/Downloads/学情看板_预览.html
"""
import os
import json

import board_data
import analysis_subjects

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser('~/Downloads/学情看板_预览.html')


def build_data():
    """[班级 × 板块 × 科目] 全组合调真实数据层，key = '班级||板块||科目'。"""
    data, classes = {}, [''] + board_data.classes()
    subs = [''] + list(analysis_subjects.SUBJECT_ORDER)
    for sec, sname in board_data.SECTIONS:
        for kl in classes:
            for sub in subs:
                data[kl + '||' + sec + '||' + sub] = board_data.board(kl, sec, sub)
                print('  已生成 %-22s %-6s %s' % (kl or '全部班级', sname, sub or '全部科目'))
    return data


def read(path):
    with open(os.path.join(BASE, path), encoding='utf-8') as f:
        return f.read()


def main():
    print('· 生成数据（读 scores/ 与成绩册）…')
    data = build_data()

    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>学情看板 · 预览稿</title>
<style>
body{margin:0;background:#e7edf4;font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#222}
.pv-top{background:linear-gradient(135deg,#16324f,#1f5f8b);color:#fff;padding:14px 22px}
.pv-top h1{margin:0;font-size:17px;font-weight:700}
.pv-top p{margin:5px 0 0;font-size:12.5px;opacity:.9;line-height:1.7}
.pv-wrap{max-width:1180px;margin:0 auto;padding:16px}
</style>
</head>
<body>
<div class="pv-top">
  <h1>学情看板 · 预览稿</h1>
  <p>这是预览，<b>还没有接进教师后台</b>。班级 / 板块用下拉切换，<b>科目是图标按钮</b>（口内 / 口外 / 口修，暖青瓷配色），
     右上角可试导出 PNG / PDF。数据读的是本地真实的 scores/ 成绩文件，与线上一致。</p>
</div>
<div class="pv-wrap">
  <div id="boardRoot"></div>
</div>

<script>window.__BOARD_DATA__ = __PAYLOAD__;</script>
<script>__ICONS__</script>
<script>__HTML2CANVAS__</script>
<script>__HTML2PDF__</script>
<script>__BOARDJS__</script>
<script>BOARD.init({mode:'static', theme:'teal'});</script>
</body>
</html>
'''
    html = (html
            .replace('__PAYLOAD__', payload)
            .replace('__ICONS__', read('static/js/subject_icons.js'))
            .replace('__HTML2CANVAS__', read('static/vendor/html2canvas.min.js'))
            .replace('__HTML2PDF__', read('static/vendor/html2pdf.bundle.min.js'))
            .replace('__BOARDJS__', read('static/js/board.js')))

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print('\n✅ 已生成：%s  (%.1f MB)' % (OUT, os.path.getsize(OUT) / 1024 / 1024))


if __name__ == '__main__':
    main()
