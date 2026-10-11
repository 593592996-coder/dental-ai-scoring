# -*- coding: utf-8 -*-
"""过程性综合成绩看板：把「AI实操练习 / 摸底考试 / 临床思维」三环节按
权重合成，渲染成单个自包含 HTML（不依赖外网和服务，双击即看）。

口径（2026-10-03 她拍板）：
  过程性综合成绩 = AI实操练习×40% + 摸底考试×20% + 临床思维×40%
  · 练习分 = 6 个操作板块（不含思维）各板块历史最高分之均分，缺板块不计；
  · 摸底分 = 考试名称含"摸底"的各场考试，取最高一场（锁分成绩）；
  · 思维分 = 思维训练病史30%/分析30%/推理40%合成的 final；
  · 某环节缺做时，按已做环节的权重重新折算，不按 0 计；三环节全缺则留空。

用法：python3 process_dashboard.py [输出html路径]
"""
import os
import sys
import json
import html

from gradebook import collect, SCORING_MODULES
import exams

BASE = os.path.dirname(os.path.abspath(__file__))

W_PRACTICE, W_BASELINE, W_THINKING = 0.4, 0.2, 0.4


def baseline_scores():
    """{学号: 摸底最高分}：遍历名称含"摸底"的考试，每人取最高一场。"""
    out = {}
    exam_names = {}
    for e in exams.list_exams():
        if '摸底' not in (e.get('name') or ''):
            continue
        for s in exams.list_submissions(e['id']):
            if s.get('is_teacher'):
                continue
            t = s.get('total_score')
            if not isinstance(t, (int, float)):
                continue
            sid = str(s.get('sid') or '').strip()
            if not sid:
                continue
            if sid not in out or t > out[sid]:
                out[sid] = round(float(t), 1)
                exam_names[sid] = e['name']
    return out, exam_names


def build_rows():
    rows_agg, _, _ = collect()
    baseline, baseline_exam = baseline_scores()
    out = []
    for sid, r in rows_agg.items():
        mods = r.get('modules', {})

        pv = [m['best'] for k, m in mods.items()
              if k in SCORING_MODULES and m.get('best') is not None]
        practice = round(sum(pv) / len(pv), 1) if pv else None
        base = baseline.get(sid)
        thinking = mods.get('thinking', {}).get('best')

        wsum, tot = 0, 0.0
        for val, w in ((practice, W_PRACTICE), (base, W_BASELINE),
                       (thinking, W_THINKING)):
            if val is not None:
                tot += val * w
                wsum += w
        final = round(tot / wsum, 1) if wsum else None

        out.append({
            'sid': sid, 'name': r.get('name', ''),
            'klass': r.get('class', '') or '未分班',
            'org': r.get('org', ''), 'role': r.get('role', ''),
            'practice': practice, 'baseline': base, 'thinking': thinking,
            'final': final,
            'baseline_exam': baseline_exam.get(sid, ''),
            'n_practice_mods': len(pv),
        })
    out.sort(key=lambda x: (x['klass'], x['sid']))
    return out


def grade_of(score):
    if score is None:
        return ''
    if score >= 90:
        return '优'
    if score >= 80:
        return '良'
    if score >= 70:
        return '中'
    if score >= 60:
        return '及格'
    return '不及格'


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>过程性综合成绩看板</title>
<style>
:root{
  --teal:#0F766E; --teal-d:#115E59; --teal-l:#CCFBF1;
  --amber:#B45309; --amber-l:#FEF3C7;
  --blue:#1D4ED8; --blue-l:#DBEAFE;
  --purple:#6D28D9; --purple-l:#EDE9FE;
  --ink:#134E4A; --gray:#64748B; --line:#E2E8F0; --bg:#F1F5F9;
  --red:#DC2626;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:#0F172A;padding:22px}
.wrap{max-width:1180px;margin:0 auto}
header{background:linear-gradient(135deg,var(--teal-d),var(--teal));
  color:#fff;border-radius:16px;padding:22px 26px;box-shadow:0 6px 20px rgba(15,118,110,.25)}
header h1{font-size:22px;display:flex;align-items:center;gap:10px}
header .sub{margin-top:6px;font-size:13px;opacity:.9}
.formula{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;align-items:center}
.fchip{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.35);
  border-radius:999px;padding:5px 14px;font-size:13px}
.fchip b{font-size:15px}
.fop{font-size:15px;opacity:.85}

.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:18px 0}
.kpi{background:#fff;border-radius:14px;padding:16px 18px;border:1px solid var(--line)}
.kpi .lab{font-size:13px;color:var(--gray)}
.kpi .num{font-size:30px;font-weight:700;margin-top:4px;color:var(--teal-d)}
.kpi .hint{font-size:12px;color:var(--gray);margin-top:2px}
.kpi.practice .num{color:var(--teal)}
.kpi.baseline .num{color:var(--amber)}
.kpi.thinking .num{color:var(--purple)}
.kpi.final .num{color:var(--blue)}

.panels{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:18px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.card h3{font-size:15px;color:var(--ink);margin-bottom:14px}

.bar-row{display:flex;align-items:center;gap:10px;margin:9px 0;font-size:13px}
.bar-row .lab{width:64px;color:var(--gray);text-align:right;flex:none}
.bar-track{flex:1;background:#F1F5F9;border-radius:6px;height:20px;position:relative;overflow:hidden}
.bar-fill{height:100%;border-radius:6px;background:var(--teal);
  display:flex;align-items:center;justify-content:flex-end;padding-right:7px;
  color:#fff;font-size:11px;min-width:30px;transition:width .4s}

.histo{display:flex;align-items:flex-end;gap:10px;height:150px;padding-top:10px}
.hcol{flex:1;display:flex;flex-direction:column;align-items:center;gap:5px;height:100%;justify-content:flex-end}
.hcol .col{width:100%;border-radius:6px 6px 0 0;background:linear-gradient(180deg,#2DD4BF,var(--teal));min-height:2px;position:relative}
.hcol .cv{font-size:11px;color:var(--gray);position:absolute;top:-16px;left:50%;transform:translateX(-50%)}
.hcol .cl{font-size:11px;color:var(--gray)}

.controls{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.tabs{display:flex;gap:6px}
.tab{border:1px solid var(--line);background:#fff;border-radius:999px;
  padding:6px 16px;font-size:13px;cursor:pointer;color:var(--gray)}
.tab.on{background:var(--teal);color:#fff;border-color:var(--teal)}
input.search{border:1px solid var(--line);border-radius:999px;padding:7px 16px;
  font-size:13px;width:200px;outline:none}
input.search:focus{border-color:var(--teal)}
.count{font-size:13px;color:var(--gray);margin-left:auto}

table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#F8FAFC;text-align:left;padding:10px 12px;color:var(--gray);
  font-weight:600;border-bottom:1px solid var(--line);white-space:nowrap;cursor:pointer;user-select:none}
th:hover{color:var(--teal)}
td{padding:10px 12px;border-bottom:1px solid #F1F5F9}
tr:hover td{background:#FAFDFC}
.num-cell{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600}
.p-优{background:var(--teal-l);color:var(--teal-d)}
.p-良{background:var(--blue-l);color:var(--blue)}
.p-中{background:var(--amber-l);color:var(--amber)}
.p-及格{background:#FEF9C3;color:#A16207}
.p-不及格{background:#FEE2E2;color:var(--red)}
.miss{color:#CBD5E1}
.mini{font-size:11px;color:var(--gray)}

.empty{text-align:center;padding:60px 20px;color:var(--gray)}
.empty .big{font-size:40px;margin-bottom:10px}

footer{margin-top:16px;font-size:12px;color:var(--gray);line-height:1.8;
  background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 18px}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}.panels{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>📊 过程性综合成绩看板</h1>
  <div class="sub">三环节全程留痕 · 数据生成于 __GENERATED__</div>
  <div class="formula">
    <span class="fchip">AI实操练习 <b>40%</b></span><span class="fop">+</span>
    <span class="fchip">摸底考试 <b>20%</b></span><span class="fop">+</span>
    <span class="fchip">临床思维 <b>40%</b></span>
  </div>
</header>

<div class="kpis" id="kpis"></div>

<div class="panels">
  <div class="card">
    <h3>各环节参与人数</h3>
    <div id="envBars"></div>
  </div>
  <div class="card">
    <h3>过程性综合分分布</h3>
    <div class="histo" id="histo"></div>
  </div>
</div>

<div class="card">
  <div class="controls">
    <div class="tabs" id="tabs"></div>
    <input class="search" id="search" placeholder="搜学号 / 姓名">
    <span class="count" id="count"></span>
  </div>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th data-k="sid">学号</th><th data-k="name">姓名</th><th data-k="klass">班级</th>
      <th data-k="practice" class="num-cell">实操练习(40%)</th>
      <th data-k="baseline" class="num-cell">摸底(20%)</th>
      <th data-k="thinking" class="num-cell">临床思维(40%)</th>
      <th data-k="final" class="num-cell">过程性综合分</th>
      <th data-k="grade">等级</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  </div>
  <div class="empty" id="empty" style="display:none">
    <div class="big">📭</div>
    <div>当前筛选下暂无学生成绩</div>
    <div class="mini" style="margin-top:6px">真实成绩同步后重新生成本看板即可</div>
  </div>
</div>

<footer>
  <b>计算口径：</b>① 实操练习＝II类洞/开髓术/X光片/前牙冠/后牙冠/印模 6 个板块各取<b>历史最高分</b>后均分（缺板块不计）；
  ② 摸底＝考试名含"摸底"的锁分考试取最高一场；③ 思维＝病史30%＋分析30%＋推理40%合成；
  ④ 某环节缺做时按<b>已做环节权重重新折算</b>（不按0分），三环节全缺者综合分留空。
  等级：≥90优 / ≥80良 / ≥70中 / ≥60及格 / &lt;60不及格。
</footer>
</div>

<script>
const DATA = __DATA__;
let curClass='ALL', kw='', sortK='sid', sortAsc=true;

const classes=[...new Set(DATA.map(d=>d.klass))].sort();
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function avg(xs){return xs.length?Math.round(xs.reduce((a,b)=>a+b,0)/xs.length*10)/10:null}
function pct(n,d){return d?Math.round(n/d*100):0}

function renderKpis(){
  const n=DATA.length;
  const np=DATA.filter(d=>d.practice!==null), nb=DATA.filter(d=>d.baseline!==null),
        nt=DATA.filter(d=>d.thinking!==null), nf=DATA.filter(d=>d.final!==null);
  const items=[
    ['','花名册人数',n,''],
    ['practice','AI实操练习',np.length, '均分 '+(avg(np.map(d=>d.practice))??'—')],
    ['baseline','摸底考试',nb.length, '均分 '+(avg(nb.map(d=>d.baseline))??'—')],
    ['thinking','临床思维',nt.length, '均分 '+(avg(nt.map(d=>d.thinking))??'—')],
    ['final','过程性综合分',nf.length, '均分 '+(avg(nf.map(d=>d.final))??'—')],
  ];
  document.getElementById('kpis').innerHTML=items.map(([c,l,v,h])=>
    `<div class="kpi ${c}"><div class="lab">${l}</div><div class="num">${v}</div><div class="hint">${h}</div></div>`).join('');

  const envs=[['实操练习',np.length,'var(--teal)'],['摸底考试',nb.length,'var(--amber)'],['临床思维',nt.length]];
  document.getElementById('envBars').innerHTML=envs.map(([l,v,col])=>
    `<div class="bar-row"><div class="lab">${l}</div>
     <div class="bar-track"><div class="bar-fill" style="width:${pct(v,n)}%;background:${col}">${v}人 · ${pct(v,n)}%</div></div></div>`).join('');

  const bins=[[0,60,'<60'],[60,70,'60+'],[70,80,'70+'],[80,90,'80+'],[90,101,'90+']];
  const bc=bins.map(([a,b])=>nf.filter(d=>d.final>=a&&d.final<b).length);
  const mx=Math.max(1,...bc);
  document.getElementById('histo').innerHTML=bins.map((b,i)=>
    `<div class="hcol"><div class="col" style="height:${bc[i]/mx*100}%">${bc[i]?`<span class="cv">${bc[i]}</span>`:''}</div><div class="cl">${b[2]}</div></div>`).join('');
}

function renderTabs(){
  const all=['ALL',...classes];
  document.getElementById('tabs').innerHTML=all.map(c=>{
    const n=c==='ALL'?DATA.length:DATA.filter(d=>d.klass===c).length;
    return `<div class="tab ${c===curClass?'on':''}" data-c="${esc(c)}">${c==='ALL'?'全部':esc(c)} ${n}</div>`}).join('');
  document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{curClass=t.dataset.c;render()});
}

function scoreCell(v,sub){
  if(v===null)return `<td class="num-cell miss">—</td>`;
  return `<td class="num-cell">${v}${sub?`<div class="mini">${sub}</div>`:''}</td>`;
}

function render(){
  renderTabs();
  let rows=DATA.filter(d=>(curClass==='ALL'||d.klass===curClass)
    &&(!kw||d.sid.includes(kw)||d.name.includes(kw)));
  rows.sort((a,b)=>{
    let x=a[sortK],y=b[sortK];
    if(x===null)x=-1;if(y===null)y=-1;
    if(typeof x==='string')return sortAsc?x.localeCompare(y,'zh'):y.localeCompare(x,'zh');
    return sortAsc?x-y:y-x;
  });
  document.getElementById('count').textContent=`显示 ${rows.length} 人`;
  document.getElementById('empty').style.display=rows.length?'none':'block';
  document.getElementById('tbody').innerHTML=rows.map(d=>`<tr>
    <td>${esc(d.sid)}</td><td>${esc(d.name)}</td><td>${esc(d.klass)}</td>
    ${scoreCell(d.practice,d.practice!==null?d.n_practice_mods+'/6板块':'')}
    ${scoreCell(d.baseline,d.baseline!==null?esc(d.baseline_exam):'')}
    ${scoreCell(d.thinking)}
    <td class="num-cell"><b>${d.final??'<span class="miss">—</span>'}</b></td>
    <td>${d.final!==null?`<span class="pill p-${gradeOf(d.final)}">${gradeOf(d.final)}</span>`:'<span class="miss">—</span>'}</td>
  </tr>`).join('');
}
function gradeOf(s){if(s>=90)return'优';if(s>=80)return'良';if(s>=70)return'中';if(s>=60)return'及格';return'不及格'}

document.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;
  if(sortK===k)sortAsc=!sortAsc;else{sortK=k;sortAsc=true}
  render();
});
document.getElementById('search').oninput=e=>{kw=e.target.value.trim();render()};

renderKpis();render();
</script>
</body>
</html>
"""


def render_html():
    rows = build_rows()
    from datetime import datetime
    return (PAGE
            .replace('__DATA__', json.dumps(rows, ensure_ascii=False))
            .replace('__GENERATED__', datetime.now().strftime('%Y-%m-%d %H:%M')))


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.expanduser('~'), 'Downloads', '过程性综合成绩看板.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(render_html())
    print('已生成:', out)
