# -*- coding: utf-8 -*-
"""56 道「病例分析」题库（口内/口外/口修）。

来源：~/Downloads/56道病例分析.docx（执业医师题型，含标准答案）
转换：2026-10-14，用 glm-5.3-flash 结构化（材料清洗 + 得分点关键词抽取）
数据在 analysis_cases_56.json，本文件只负责加载。

每个病例字段：
  subject            口内 / 口外 / 口修
  title              教师看的标题（含诊断，不下发给学生）
  module_tag         病种
  level              难度 1-3
  brief              学生卡片标题（不含诊断名）
  chief_complaint    主诉（卡片副标题）
  in_scope           是否在考纲内
  analysis           {material, diagnosis, acceptable_diag, basis_points,
                      differential_exam, differential_clinical, treatment_points}
    其中 basis_points / differential_exam / treatment_points 每项带 keywords，
    供 /train/api/analysis/score/<id> 做关键词匹配评分。
"""
import json as _json
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
with open(_os.path.join(_HERE, 'analysis_cases_56.json'), encoding='utf-8') as _f:
    ANALYSIS_CASES_56 = _json.load(_f)
