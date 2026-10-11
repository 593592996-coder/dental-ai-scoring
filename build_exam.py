# -*- coding: utf-8 -*-
"""口腔内科学实验考核试卷生成器（2024级口腔医学）

结构（满分100）：
  理论部分 60 分 —— 题干取自临床思维训练 case001「36慢性牙髓炎急性发作」
    一、单项选择 10×2 = 20
    二、判断     5×2 = 10
    三、病例分析      = 30（诊断8 / 依据10 / 鉴别6 / 治疗6）
  操作部分 40 分 —— II类洞制备，10个评分维度（与AI评分系统同口径折算）
  后附：参考答案与评分标准（另起一页，教师用）

用法：python3 build_exam.py [输出html]
"""
import os, sys, json
from datetime import datetime

# ───────── 病例题干 ─────────
CASE_MATERIAL = """患者男，35岁。主诉：左下后牙疼痛3天，昨晚加重，夜间痛明显，一夜未眠。
现病史：3天前进食冷饮时左下后牙酸软，未在意；昨夜突发疼痛，阵发性、针刺样，向左侧太阳穴放射，
冷热刺激诱发并持续，夜间及躺下加重。自服布洛芬稍缓解但不持久。
既往史：高血压5年，口服氨氯地平；否认药物过敏；吸烟十余年。
口腔检查：36颌面深大龋洞、食物嵌塞，探痛(+)、可及疑似穿髓点；垂直叩痛(±)、侧方(-)，
扪(-)，不松动，牙龈无红肿瘘管。
牙髓检查：冷测锐痛持续约30秒（对照牙3～5秒消退）；热测迟缓性持续痛；电活力测试有反应。
X线：36颌面透射影达髓腔，近中邻面低密度影达釉牙本质界；根尖周未见明显透射影，牙周膜稍增宽。"""

# ───────── 选择题 ─────────
SINGLE = [
    ("该患者最可能的诊断是",
     ["急性牙髓炎（36慢性牙髓炎急性发作）", "急性根尖周炎", "三叉神经痛", "急性龈乳头炎"], 0),
    ("下列哪项不是急性牙髓炎的典型疼痛特点",
     ["自发性、阵发性痛", "夜间痛加重", "向同侧头面部放射", "能明确定位、咬合痛剧烈"], 3),
    ("患牙冷测锐痛并持续约30秒，提示",
     ["可复性牙髓炎", "不可复性牙髓炎", "牙髓坏死", "牙本质过敏症"], 1),
    ("电活力测试患牙“有反应”，说明该牙",
     ["为死髓牙", "为活髓牙", "已发生根尖周炎", "存在深牙周袋"], 1),
    ("需与本病鉴别的三叉神经痛，其典型表现是",
     ["持续钝痛、夜间加重", "电击样骤痛、有扳机点、与温度刺激无关",
      "冷热刺激迟缓持续痛", "牙龈红肿、咬合时痛"], 1),
    ("急性龈乳头炎与急性牙髓炎的关键鉴别点是",
     ["龈乳头红肿、食物嵌塞性触痛，无自发夜间放射痛、牙髓活力正常",
      "患牙电活力无反应", "X线根尖区有透射影", "患牙Ⅲ度松动"], 0),
    ("急性上颌窦炎引起的牵涉痛特点是",
     ["下颌后牙夜间痛", "上颌后牙多牙胀痛，伴鼻塞、弯腰时加重",
      "单牙冷热迟缓痛", "针刺样、有扳机点"], 1),
    ("该患牙（36）首选的治疗方案是",
     ["直接垫底充填", "拔除患牙", "根管治疗术", "单纯口服抗生素观察"], 2),
    ("该患牙不能“直接补牙”而需根管治疗，是因为",
     ["龋洞过大无法充填", "不可复性牙髓炎且疑已穿髓，牙髓不能保留",
      "患牙松动", "咬合痛明显"], 1),
    ("关于抗生素治疗本病，正确的认识是",
     ["足量、长期抗生素即可治愈", "抗生素能进入髓腔杀灭牙髓细菌",
      "抗生素难以进入封闭髓腔和感染牙髓，仅能暂时缓解，清除感染须靠根管治疗",
      "抗生素可替代根管治疗"], 2),
]

JUDGE = [
    ("急性牙髓炎患者通常能明确定位指出患牙。", False),
    ("冷热刺激去除后疼痛仍持续较长时间，提示不可复性牙髓炎。", True),
    ("急性牙髓炎只要早期、足量服用抗生素即可治愈，无需局部处理。", False),
    ("本病例患牙叩痛明显且X线片可见根尖区明显透射影。", False),
    ("不可复性牙髓炎的首选根治方法是根管治疗术。", True),
]

# ───────── 病例分析评分点（参考答案） ─────────
DIAGNOSIS = "36慢性牙髓炎急性发作（亦称急性牙髓炎、不可复性牙髓炎）"
BASIS_POINTS = [
    "有自发痛、阵发性、针刺样痛，夜间痛、放射至同侧头面部；",
    "冷热刺激诱发并迟缓持续痛（冷测持续约30秒），属不可复性；",
    "36颌面深大龋洞、探痛(+)、可及疑似穿髓点，存在龋源性感染通路；",
    "电活力测试有反应，为活髓牙；",
    "叩痛(±)、不松动、X线根尖周未见透射，提示病变尚在牙髓、根尖周未受累。",
]
DIFFERENTIAL = [
    ("急性龈乳头炎", "龈乳头红肿、定位性触痛、食物嵌塞，无自发夜间放射痛，牙髓活力正常。"),
    ("三叉神经痛", "电击样骤痛、有扳机点、骤发骤停，与温度刺激无关，牙体多正常。"),
    ("急性上颌窦炎", "上颌后牙多牙胀痛，伴感冒鼻塞、弯腰时加重；本病例为下颌牙，不支持。"),
    ("急性根尖周炎（临床鉴别）", "多有咬合痛、死髓、根尖区透射；本病例为活髓、咬合不痛、根尖无透射。"),
]
TREATMENT = [
    ("根管治疗术（3分）", "开髓引流、拔髓、根管预备、消毒、根管充填。"),
    ("冠部修复（2分）", "根管治疗后行树脂充填／嵌体／全冠修复，恢复形态功能。"),
    ("卫生宣教与戒烟（1分）", "口腔卫生指导，建议戒烟，定期复查。"),
]

# ───────── 操作评分表（II类洞，40分） ─────────
SKILL = [
    ("外形轮廓与洞形", 8, "洞形轮廓清晰、线角圆钝，按II类洞设计，扩展至自洁区、避开咬合接触区。",
     "轮廓不规范、未达自洁区或位于咬合受力点，酌情扣1～4分。"),
    ("鸠尾峡部", 6, "合面鸠尾位于颊舌尖之间，峡部宽度适当（约颊舌尖间距的1/4～1/3），具固位抗力、防水平脱位。",
     "峡部过宽削弱牙体或过窄易折裂、位置不当，扣1～4分。"),
    ("洞深", 4, "深入牙本质，深度约1.5～2 mm（釉牙本质界下0.5～1 mm），保证充填体厚度与抗力。",
     "过浅固位抗力不足或过深伤髓，扣1～3分。"),
    ("髓壁平面度", 3, "髓壁平坦、与牙长轴垂直。", "髓壁不平、倾斜，扣0.5～2分。"),
    ("侧壁垂直度", 3, "侧壁直、与髓壁垂直，方向符合釉柱走行。", "侧壁内倾/外敞、方向不当，扣0.5～2分。"),
    ("点线角", 4, "点线角清楚而圆钝，既明确固位又避免应力集中。", "点线角模糊或过锐造成应力集中，扣1～3分。"),
    ("邻面盒形", 4, "颊舌壁向外敞开至自洁区，龈壁平整位于接触区龈方，轴壁随邻面外形微凸，呈盒形。",
     "盒形不完整、龈壁悬空或台阶不清，扣1～3分。"),
    ("洞缘光滑度", 2, "洞缘无悬空釉柱、修整连续光滑。", "洞缘粗糙、有悬空釉质，扣0.5～1.5分。"),
    ("邻牙与软组织保护", 4, "支点稳，不损伤邻牙及牙龈等软组织。", "划伤邻牙/牙龈，每次扣1分。"),
    ("操作规范与术区整洁", 2, "器械握持、支点、操作规范，术区清洁、视野清楚。", "操作不规范、视野不清，扣0.5～1.5分。"),
]

# ───────── HTML ─────────
def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def options_block(items):
    h = []
    for i, (q, opts, ans) in enumerate(items):
        h.append(f'<div class="q"><div class="qstem"><b>{i+1}.</b> {esc(q)}（&nbsp;&nbsp;）</div>')
        h.append('<div class="opts">' + ''.join(
            f'<div class="opt"><span class="key">{chr(65+j)}.</span> {esc(o)}</div>'
            for j, o in enumerate(opts)) + '</div></div>')
    return '\n'.join(h)


def judge_block(items):
    h = []
    for i, (q, ans) in enumerate(items):
        h.append(f'<div class="q judge"><b>{i+1}.</b> {esc(q)}'
                 f'<span class="paren">（&nbsp;&nbsp;&nbsp;&nbsp;）</span></div>')
    return '\n'.join(h)


def skill_table(for_answer=False):
    rows = ['<table class="skill"><thead><tr>'
            '<th style="width:44px">序号</th><th style="width:130px">评分项目</th>'
            '<th style="width:50px">分值</th><th>评分要点与扣分标准</th>'
            '<th style="width:56px">得分</th></tr></thead><tbody>']
    for i, (name, sc, good, deduct) in enumerate(SKILL):
        rows.append(f'<tr><td class="c">{i+1}</td><td><b>{esc(name)}</b></td>'
                    f'<td class="c">{sc}</td><td><div class="good">✓ {esc(good)}</div>'
                    f'<div class="deduct">扣：{esc(deduct)}</div></td><td></td></tr>')
    rows.append(f'<tr class="sum"><td colspan="2" class="c">合&nbsp;计</td><td class="c">40</td>'
                f'<td>总分 = 各维度实得分之和</td><td></td></tr>')
    rows.append('</tbody></table>')
    return '\n'.join(rows)


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>口腔内科学实验考核试卷（2024级）</title>
<style>
@page{size:A4;margin:16mm 15mm}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Songti SC","SimSun",serif;color:#000;font-size:12.5px;line-height:1.7}
.sans{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.sheet{max-width:800px;margin:0 auto;padding:8px 4px}

.exam-head{text-align:center;border-bottom:2.5px solid #0F766E;padding-bottom:10px;margin-bottom:6px}
.school{font-size:15px;letter-spacing:3px;font-family:"PingFang SC",sans-serif}
.papertitle{font-size:24px;font-weight:700;letter-spacing:2px;margin:6px 0;color:#115E59;
  font-family:"PingFang SC","Microsoft YaHei",sans-serif}
.papersub{font-size:12.5px;color:#334155;font-family:"PingFang SC",sans-serif}

.meta{display:flex;justify-content:space-between;align-items:center;
  font-size:12px;margin:8px 2px 14px;font-family:"PingFang SC",sans-serif;color:#1f2937}
.meta .fill{border-bottom:1px solid #333;display:inline-block;min-width:74px;text-align:center}
.notice{background:#F0FDFA;border:1px solid #99F6E4;border-radius:6px;padding:7px 12px;
  font-size:11.5px;color:#134E4A;margin-bottom:14px;font-family:"PingFang SC",sans-serif}

.part{margin:16px 0 8px;font-size:14px;font-weight:700;color:#115E59;
  font-family:"PingFang SC",sans-serif;border-left:4px solid #0F766E;padding-left:9px}
.part .sc{color:#B45309;font-weight:600;font-size:12px;margin-left:6px}

.q{margin:9px 0;page-break-inside:avoid}
.qstem{font-weight:600;margin-bottom:3px}
.opts{display:grid;grid-template-columns:1fr 1fr;gap:2px 18px;margin:3px 0 0 20px;font-size:12px}
.opt{padding:1px 0}
.key{font-weight:700;margin-right:3px}
.judge{font-size:12.5px}
.paren{margin-left:6px;font-weight:700}

.casebox{border:1.5px solid #0F766E;border-radius:8px;overflow:hidden;margin:6px 0 12px}
.casebox .cap{background:#0F766E;color:#fff;padding:5px 12px;font-size:12.5px;
  font-family:"PingFang SC",sans-serif}
.casebox .body{padding:10px 14px;white-space:pre-wrap;font-size:12.5px;line-height:1.85}

.analyze-q{margin:10px 0}
.analyze-q .aq-t{font-weight:700;margin-bottom:2px}
.analyze-q .aq-t .pts{color:#B45309}
.anslines{margin:2px 0 0 8px}
.ansline{border-bottom:1px dashed #94A3B8;height:26px}

table.skill{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px}
table.skill th{background:#0F766E;color:#fff;border:1px solid #0F766E;padding:5px 6px;
  font-family:"PingFang SC",sans-serif;font-weight:600}
table.skill td{border:1px solid #CBD5E1;padding:5px 7px;vertical-align:top;line-height:1.55}
table.skill td.c{text-align:center;vertical-align:middle}
table.skill .good{color:#134E4A}
table.skill .deduct{color:#B91C1C;margin-top:2px;font-size:10.5px}
table.skill tr.sum td{background:#F0FDFA;font-weight:700}

.answer-page{page-break-before:always}
.answer-banner{background:linear-gradient(135deg,#115E59,#0F766E);color:#fff;border-radius:10px;
  padding:14px 18px;text-align:center;margin-bottom:14px}
.answer-banner h2{font-size:20px;font-family:"PingFang SC",sans-serif;letter-spacing:2px}
.answer-banner .s{font-size:12px;opacity:.9;margin-top:3px;font-family:"PingFang SC",sans-serif}
.asec{margin:14px 0 8px;font-size:13.5px;font-weight:700;color:#115E59;
  font-family:"PingFang SC",sans-serif;border-left:4px solid #0F766E;padding-left:9px}
.akey{margin:5px 0 5px 14px;font-size:12px}
.akey .ans{display:inline-block;background:#F0FDFA;border:1px solid #5EEAD4;border-radius:5px;
  padding:0 9px;font-weight:700;color:#115E59;font-family:"PingFang SC",sans-serif;margin-right:8px}
.akey .why{color:#475569}
.diag-ans{background:#FEF3C7;border:1px solid #FCD34D;border-radius:6px;padding:8px 12px;
  font-size:12.5px;margin:4px 0 8px}
.bp{margin:4px 0 4px 14px;font-size:12px}
.bp b{color:#B45309}
.df{margin:4px 0 4px 14px;font-size:12px}
.df .nm{font-weight:700}
.df .pt{color:#475569}
.tr{margin:4px 0 4px 14px;font-size:12px}
.endmark{text-align:center;color:#94A3B8;font-size:11px;margin-top:30px;
  font-family:"PingFang SC",sans-serif}
@media print{.noprint{display:none}}
</style></head>
<body><div class="sheet">

<!-- ============ 学生卷 ============ -->
<div class="exam-head">
  <div class="school">楚雄医药高等专科学校</div>
  <div class="papertitle">口腔内科学实验考核试卷</div>
  <div class="papersub">2024级口腔医学专业　|　理论 + 操作　|　满分 100 分　|　考核时间 90 分钟</div>
</div>

<div class="meta">
  <div>班级：<span class="fill"></span>　　姓名：<span class="fill"></span>　　学号：<span class="fill" style="min-width:140px"></span></div>
  <div>总分：<span class="fill" style="min-width:48px"></span></div>
</div>

<div class="notice">
  <b>考生须知：</b>本试卷分理论（60分）与操作（40分）两部分。选择题将答案字母填入题干括号；
  判断题正确填“√”、错误填“×”；病例分析与操作考核按要求作答。字迹清楚，卷面整洁。
</div>

<div class="part">第一部分　理论考核 <span class="sc">共 60 分</span></div>

<div class="part" style="font-size:13px">一、单项选择题 <span class="sc">每题 2 分，共 20 分</span></div>
__SINGLE__

<div class="part" style="font-size:13px">二、判断题 <span class="sc">每题 2 分，共 10 分；正确“√”，错误“×”</span></div>
__JUDGE__

<div class="part" style="font-size:13px">三、病例分析 <span class="sc">共 30 分</span></div>
<div class="casebox"><div class="cap">病例资料（请阅读后作答）</div>
<div class="body">__CASE__</div></div>

<div class="analyze-q">
  <div class="aq-t">1. 作出初步诊断。<span class="pts">（8分）</span></div>
  <div class="anslines"><div class="ansline"></div><div class="ansline"></div></div>
</div>
<div class="analyze-q">
  <div class="aq-t">2. 列出诊断依据。<span class="pts">（10分）</span></div>
  <div class="anslines"><div class="ansline"></div><div class="ansline"></div>
  <div class="ansline"></div><div class="ansline"></div></div>
</div>
<div class="analyze-q">
  <div class="aq-t">3. 需与哪些疾病鉴别？（至少列举3项并说明鉴别要点）<span class="pts">（6分）</span></div>
  <div class="anslines"><div class="ansline"></div><div class="ansline"></div><div class="ansline"></div></div>
</div>
<div class="analyze-q">
  <div class="aq-t">4. 拟定治疗计划。<span class="pts">（6分）</span></div>
  <div class="anslines"><div class="ansline"></div><div class="ansline"></div><div class="ansline"></div></div>
</div>

<div class="part">第二部分　操作考核 <span class="sc">共 40 分 · II类洞制备</span></div>
<div style="font-size:11.5px;color:#475569;font-family:'PingFang SC',sans-serif;margin-bottom:4px">
 在仿真头模/离体牙上完成后牙邻合面（II类）洞制备，由考核教师依据下列标准逐项评分。</div>
__SKILL_STUDENT__

<div class="endmark">—— 试卷结束 · 以下为参考答案与评分标准（教师用） ——</div>

<!-- ============ 参考答案与评分标准 ============ -->
<div class="answer-page">
<div class="answer-banner">
  <h2>参考答案与评分标准</h2>
  <div class="s">2024级口腔医学专业 · 口腔内科学实验考核（教师用，请勿发给学生）</div>
</div>

<div class="asec">一、单项选择题答案（每题2分，共20分）</div>
__ANS_SINGLE__

<div class="asec">二、判断题答案（每题2分，共10分）</div>
__ANS_JUDGE__

<div class="asec">三、病例分析评分标准（共30分）</div>

<div class="bp"><b>1. 诊断（8分）</b></div>
<div class="diag-ans">参考答案：__DIAGNOSIS__
答“急性牙髓炎／慢性牙髓炎急性发作／不可复性牙髓炎／牙髓炎（36）”均认可。
评分：诊断正确且牙位正确给8分；诊断正确、牙位错误或笼统给5分；仅答“牙痛/龋病”等不给分。</div>

<div class="bp"><b>2. 诊断依据（10分，每点2分，答出5点即满分）</b></div>
__ANS_BASIS__

<div class="bp"><b>3. 鉴别诊断（6分）</b></div>
<div style="font-size:11.5px;color:#475569;margin:2px 0 0 14px">每列举1项并正确说明鉴别要点给2分，
答满3项即满分；只写病名、无要点每项给1分。参考答案：</div>
__ANS_DIFF__

<div class="bp"><b>4. 治疗计划（6分）</b></div>
__ANS_TREAT__

<div class="asec">四、操作考核评分标准（II类洞制备，共40分）</div>
__SKILL_ANSWER__
<div style="font-size:11px;color:#B91C1C;margin-top:6px;font-family:'PingFang SC',sans-serif">
 评分说明：各维度在分值内按完成质量给分，出现伤及髓腔、穿通髓壁等严重失误，相应维度计0分；
 总分=各维度实得分之和，满分40分。</div>

<div class="endmark" style="margin-top:26px">命题/阅卷教师：____________　　教研室审核：____________　　日期：____________</div>
</div>

</div></body></html>
"""


def build():
    ans_single = []
    letters = 'ABCD'
    single_why = [
        "症状（自发夜间放射痛+活髓+深龋穿髓）符合急性牙髓炎。",
        "急性牙髓炎疼痛不能自行定位、多无明显咬合痛，D为根尖周炎/咬合创伤表现。",
        "冷测疼痛持续约30秒为迟缓持续痛，提示不可复性牙髓炎。",
        "电活力有反应＝活髓；无反应才提示死髓。",
        "三叉神经痛为电击样骤痛、有扳机点、骤发骤停、与温度无关。",
        "龈乳头炎病损在龈乳头、有食物嵌塞触痛，牙髓活力正常、无自发夜间放射痛。",
        "上颌窦炎牵涉上颌后牙，多牙胀痛，伴鼻塞、体位（弯腰）加重。",
        "不可复性牙髓炎首选根管治疗。",
        "牙髓不可复、疑已穿髓，不能保留活髓，故须根管治疗而非直接充填。",
        "抗生素难入封闭髓腔，只能暂时缓解，根管治疗才能清除感染。",
    ]
    for i, (q, opts, ans) in enumerate(SINGLE):
        ans_single.append(f'<div class="akey"><b>{i+1}.</b> '
                          f'<span class="ans">{letters[ans]}</span>'
                          f'<span class="why">{esc(single_why[i])}</span></div>')

    ans_judge = []
    judge_why = [
        "错。急性牙髓炎放射痛，患者常不能明确定位患牙。",
        "对。刺激去除后迟缓持续痛是不可复性牙髓炎的重要标志。",
        "错。抗生素不能根治，需根管治疗清除感染牙髓。",
        "错。本病例叩痛(±)、根尖周无透射，根尖周未受累。",
        "对。根管治疗是不可复性牙髓炎的首选根治方法。",
    ]
    for i, (q, ans) in enumerate(JUDGE):
        ans_judge.append(f'<div class="akey"><b>{i+1}.</b> '
                         f'<span class="ans">{"√" if ans else "×"}</span>'
                         f'<span class="why">{esc(judge_why[i])}</span></div>')

    ans_basis = ''.join(f'<div class="bp">（{i+1}）{esc(t)}</div>'
                        for i, t in enumerate(BASIS_POINTS))
    ans_diff = ''.join(f'<div class="df"><span class="nm">{esc(n)}：</span>'
                       f'<span class="pt">{esc(p)}</span></div>' for n, p in DIFFERENTIAL)
    ans_treat = ''.join(f'<div class="tr"><b>{esc(n)}</b> {esc(p)}</div>'
                        for n, p in TREATMENT)

    html = (PAGE
            .replace('__SINGLE__', options_block(SINGLE))
            .replace('__JUDGE__', judge_block(JUDGE))
            .replace('__CASE__', esc(CASE_MATERIAL))
            .replace('__SKILL_STUDENT__', skill_table())
            .replace('__ANS_SINGLE__', '\n'.join(ans_single))
            .replace('__ANS_JUDGE__', '\n'.join(ans_judge))
            .replace('__DIAGNOSIS__', esc(DIAGNOSIS))
            .replace('__ANS_BASIS__', ans_basis)
            .replace('__ANS_DIFF__', ans_diff)
            .replace('__ANS_TREAT__', ans_treat)
            .replace('__SKILL_ANSWER__', skill_table()))
    return html


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.expanduser('~'), 'Downloads', '口腔内科学实验考核试卷_2024级.html')
    open(out, 'w', encoding='utf-8').write(build())
    print('已生成:', out)
