# -*- coding: utf-8 -*-
"""考试内容自动播种：公网 git pull + Reload 后，启动时把内置的考试
（题目JSON+X光片）复制进 exam_data/，无需在 PythonAnywhere 手动传文件。

- 只在 exam_data 中尚不存在该考试时播种，已存在/已有提交都不覆盖；
- 种子放在仓库 seed/ 目录，随 git 一起部署。
"""
import os
import json
import shutil

import exams

SEED_DIR = os.path.join(exams.BASE, 'seed')


def seed_all():
    if not os.path.isdir(SEED_DIR):
        return
    for sub in sorted(os.listdir(SEED_DIR)):
        src = os.path.join(SEED_DIR, sub)
        exam_json = os.path.join(src, 'exam.json')
        if not os.path.exists(exam_json):
            continue
        try:
            data = json.load(open(exam_json, encoding='utf-8'))
        except Exception:
            continue
        exam_list = data if isinstance(data, list) else [data]
        all_exams = exams.list_exams()
        existing = {e.get('id') for e in all_exams}

        for exam in exam_list:
            eid = exam.get('id')
            if not eid or eid in existing:
                continue
            # 影片：种子 film.jpg → exam_data/films/{exam 记录的文件名}
            film_name = exam.get('film')
            if film_name:
                src_film = os.path.join(src, 'film.jpg')
                if os.path.exists(src_film):
                    shutil.copyfile(src_film, os.path.join(exams.FILM_DIR, film_name))
            # 写入考试配置（追加，不动其他考试）
            merged = all_exams + [exam]
            exams._save_json(exams.EXAMS_FILE, merged)
            all_exams = merged
            print(f'🌱 已播种考试: {exam.get("name")} ({eid})')


seed_all()
