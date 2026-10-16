/* 学情看板 · 病史采集 / 病例分析
 *
 * 预览稿与教师后台共用这一份文件：
 *   · 正式页：BOARD.init({mode:'live'})  → fetch 后端 /admin/api/board
 *   · 预览稿：BOARD.init({mode:'static'}) → 读内嵌的 window.__BOARD_DATA__
 * CSS 也由本文件注入，保证两边样式不漂移。
 */
(function () {
  'use strict';

  var CSS = [
    '#boardRoot{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#222}',
    '#boardRoot *{box-sizing:border-box}',
    '.bd-bar{background:#fff;border-radius:12px;padding:12px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}',
    '.bd-bar label{font-size:13px;font-weight:700;color:#1B3A5C}',
    '.bd-bar select{padding:8px 11px;border:1.5px solid #cfd8e3;border-radius:8px;font-size:13px;font-family:inherit;background:#fff}',
    /* 主题：图标与选中态跟着走；默认暖青瓷，.bd-purple 切深紫 */
    '#boardRoot{--bd-accent:#2E7D8A;--bd-ring:#CFE3E6;--bd-accent-bg:#EAF3F4;--bd-accent-line:#8FBFC6}',
    '#boardRoot.bd-purple{--bd-accent:#5B4FCF;--bd-ring:#E8E4FB;--bd-accent-bg:#EFEDFC;--bd-accent-line:#B0A6EE}',
    '.bd-subjgroup{display:flex;gap:7px;flex-wrap:wrap}',
    '.bd-subj{display:flex;align-items:center;gap:6px;padding:5px 13px 5px 9px;border:1.5px solid #dde5ed;border-radius:10px;background:#fff;cursor:pointer;font-family:inherit;font-size:13px;font-weight:700;color:#5a6b7b;line-height:1;transition:all .15s}',
    '.bd-subj svg{width:26px;height:26px;flex:none;color:var(--bd-accent);opacity:.72;transition:opacity .15s}',
    '.bd-subj:hover{border-color:var(--bd-accent-line);color:#334}',
    '.bd-subj:hover svg{opacity:.85}',
    '.bd-subj.active{border-color:var(--bd-accent);background:var(--bd-accent-bg);color:var(--bd-accent)}',
    '.bd-subj.active svg{opacity:1}',
    '.bd-subj.plain{padding:9px 15px}',
    '.bd-btn{padding:9px 15px;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;color:#fff;background:linear-gradient(135deg,#2B7BEC,#1B3A5C);font-family:inherit}',
    '.bd-btn.g{background:linear-gradient(135deg,#27ae60,#1e8449)}',
    '.bd-btn[disabled]{opacity:.5;cursor:default}',
    '.bd-muted{color:#99a3ad;font-size:12px}',
    '#captureRoot{background:#eef2f7;padding:16px;border-radius:12px}',
    '.bd-head{background:linear-gradient(135deg,#16324f,#1f5f8b);color:#fff;border-radius:12px;padding:14px 18px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px}',
    '.bd-head .t{font-size:19px;font-weight:800}',
    '.bd-head .s{font-size:12px;opacity:.85;margin-top:3px}',
    '.bd-head .d{font-size:12px;opacity:.85}',
    '.bd-note{background:#fff8e1;border-left:4px solid #f39c12;border-radius:8px;padding:9px 12px;font-size:12.5px;color:#8a6100;margin-bottom:14px}',
    '.bd-panel{background:#fff;border-radius:12px;padding:14px 16px;margin-bottom:14px}',
    '.bd-panel h3{font-size:14px;color:#1B3A5C;margin:0 0 12px;border-left:4px solid #1f5f8b;padding-left:8px;font-weight:700}',
    '.bd-panel h3 small{font-weight:400;color:#99a3ad;font-size:11.5px;margin-left:6px}',
    '.bd-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px}',
    '.bd-kpi{background:#f7f9fc;border:1px solid #e8eef5;border-radius:10px;padding:11px 13px}',
    '.bd-kpi .v{font-size:23px;font-weight:800;color:#1B3A5C;line-height:1.15}',
    '.bd-kpi .l{font-size:11.5px;color:#8a97a5;margin-top:3px}',
    '.bd-kpi .x{font-size:11px;color:#99a3ad;margin-top:3px}',
    '.bd-2col{display:grid;grid-template-columns:1fr 1fr;gap:14px}',
    '@media(max-width:840px){.bd-2col{grid-template-columns:1fr}}',
    '.bd-dist{margin:0}',
    '.bd-distrow{display:flex;align-items:center;margin:7px 0;font-size:12.5px}',
    '.bd-distrow .lab{width:62px;text-align:right;padding-right:9px;color:#5a6b7b;flex:none}',
    '.bd-distrow .track{flex:1;height:22px;background:#f0f3f7;border-radius:11px;overflow:hidden}',
    '.bd-distrow .fill{height:100%;border-radius:11px;transition:width .5s;min-width:2px}',
    '.bd-distrow .cnt{width:66px;padding-left:9px;color:#2C3E50;font-weight:700;flex:none}',
    '.bd-empty{padding:34px 10px;text-align:center;color:#99a3ad;font-size:13.5px}',
    '.bd-weak{margin:0}',
    '.bd-weakrow{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f2f5f9;font-size:12.5px}',
    '.bd-weakrow:last-child{border-bottom:none}',
    '.bd-weakrow .rk{width:22px;height:22px;line-height:22px;text-align:center;border-radius:50%;font-size:11px;font-weight:700;color:#fff;background:#c7ced6;flex:none}',
    '.bd-weakrow .rk.t3{background:#c0392b}',
    '.bd-weakrow .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#2C3E50}',
    '.bd-weakrow .nm b{font-weight:700}',
    '.bd-weakrow .track{width:170px;height:9px;background:#f0f3f7;border-radius:5px;overflow:hidden;flex:none}',
    '.bd-weakrow .fill{height:100%;border-radius:5px;background:#e67e22}',
    '.bd-weakrow .fill.hi{background:#c0392b}.bd-weakrow .fill.lo{background:#27ae60}',
    '.bd-weakrow .sc{width:118px;text-align:right;color:#5a6b7b;flex:none}',
    '.bd-weakrow .sc b{color:#1B3A5C;font-size:13.5px}',
    '.bd-tag{display:inline-block;font-size:10.5px;background:#eef4ff;color:#2B7BEC;border-radius:9px;padding:1px 7px;margin-left:5px;vertical-align:1px}',
    '.bd-tbl{width:100%;border-collapse:collapse;font-size:12.5px}',
    '.bd-tbl th,.bd-tbl td{padding:7px 6px;border-bottom:1px solid #eef1f5;text-align:center}',
    '.bd-tbl th{background:#1B3A5C;color:#fff;font-weight:700}',
    '.bd-tbl td.l,.bd-tbl th.l{text-align:left}',
    '.bd-foot{font-size:11.5px;color:#99a3ad;line-height:1.75;padding:0 4px}',
    '.bd-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:rgba(27,58,92,.94);color:#fff;font-size:13px;padding:9px 18px;border-radius:20px;z-index:99;display:none}'
  ].join('\n');

  // 三科室图标：唯一来源是 static/js/subject_icons.js（教师端与学生端共用）
  var ICONS = window.SUBJECT_ICONS || {};


  var STATE = { mode: 'live', root: null, api: '', data: null, classes: [], sections: [], cur: { class: '', section: 'history' }, last: null };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v, d) { return (v === null || v === undefined) ? '—' : v; }
  function toast(msg, ms) {
    var t = document.getElementById('bdToast');
    if (!t) { t = document.createElement('div'); t.id = 'bdToast'; t.className = 'bd-toast'; document.body.appendChild(t); }
    t.textContent = msg; t.style.display = 'block';
    clearTimeout(t._tm); t._tm = setTimeout(function () { t.style.display = 'none'; }, ms || 2600);
  }

  // ── 局部渲染 ──────────────────────────────────────────
  function renderKPI(p) {
    var k = p.kpi, best = k.best && k.best.avg;
    var cards = [
      ['参评 / 名册', k.scored + ' / ' + k.roster, null],
      ['平均分', num(k.avg), '个人各例均分再按班平均'],
      ['及格率 ≥60', k.pass_rate === null ? '—' : k.pass_rate + '%', null],
      ['优秀率 ≥85', k.excellent_rate === null ? '—' : k.excellent_rate + '%', null],
      ['人均完成', num(k.avg_cases) + ' 例', null],
      ['最高 / 最低', num(k.max) + ' / ' + num(k.min), '按个人平均分'],
      ['单例最高均分', num(best), '每人最高的那一例，仅供参考']
    ];
    return '<div class="bd-panel"><h3>班级总览</h3><div class="bd-kpis">' + cards.map(function (c) {
      return '<div class="bd-kpi"><div class="v">' + esc(c[1]) + '</div><div class="l">' + esc(c[0]) + '</div>' +
        (c[2] ? '<div class="x">' + esc(c[2]) + '</div>' : '') + '</div>';
    }).join('') + '</div></div>';
  }

  function renderDist(p) {
    var max = Math.max.apply(null, p.dist.map(function (d) { return d.n; }).concat([1]));
    var total = p.dist.reduce(function (a, d) { return a + d.n; }, 0);
    var rows = p.dist.map(function (d) {
      var w = Math.round(d.n / max * 100);
      return '<div class="bd-distrow"><div class="lab">' + esc(d.label) + '</div>' +
        '<div class="track">' + (d.n ? '<div class="fill" style="width:' + w + '%;background:' + d.color + '"></div>' : '') + '</div>' +
        '<div class="cnt">' + d.n + ' 人</div></div>';
    }).join('');
    return '<div class="bd-panel"><h3>分数段分布<small>按个人平均分 · 共 ' + total + ' 人</small></h3>' +
      '<div class="bd-dist">' + rows + '</div></div>';
  }

  function renderCurve(p) {
    var c = p.curve || [];
    if (c.length < 2) return '<div class="bd-panel"><h3>练习曲线</h3><div class="bd-empty">作答次数不足，暂无曲线</div></div>';
    var W = 560, H = 190, PL = 34, PR = 12, PT = 12, PB = 40;
    var iw = W - PL - PR, ih = H - PT - PB;
    var x = function (i) { return PL + (c.length === 1 ? iw / 2 : iw * i / (c.length - 1)); };
    var y = function (v) { return PT + ih * (1 - v / 100); };
    var grid = '';
    [0, 25, 50, 75, 100].forEach(function (v) {
      grid += '<line x1="' + PL + '" y1="' + y(v) + '" x2="' + (W - PR) + '" y2="' + y(v) + '" stroke="#e8eef5"/>' +
        '<text x="' + (PL - 6) + '" y="' + (y(v) + 3.5) + '" text-anchor="end" font-size="9.5" fill="#a8b3bf">' + v + '</text>';
    });
    var pts = c.map(function (o, i) { return x(i) + ',' + y(o.avg); }).join(' ');
    var dots = c.map(function (o, i) {
      return '<circle cx="' + x(i) + '" cy="' + y(o.avg) + '" r="3.4" fill="#2B7BEC"/>' +
        '<text x="' + x(i) + '" y="' + (y(o.avg) - 8) + '" text-anchor="middle" font-size="9.5" fill="#1B3A5C">' + o.avg + '</text>' +
        '<text x="' + x(i) + '" y="' + (H - PB + 14) + '" text-anchor="middle" font-size="9.5" fill="#8a97a5">第' + o.i + '次</text>' +
        '<text x="' + x(i) + '" y="' + (H - PB + 26) + '" text-anchor="middle" font-size="9" fill="#b9c3cd">n=' + o.n + '</text>';
    }).join('');
    var tail = c.length > 3 ? '<div class="bd-muted" style="margin-top:6px;line-height:1.6">注：曲线随作答次数递减，做得越多的人本身越投入、越强（自我选择偏差），后段 n 很小，只作趋势参考，不能当作教学效果的严格证据。</div>' : '';
    return '<div class="bd-panel"><h3>练习曲线<small>第 N 次作答的全班均分</small></h3>' +
      '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto">' + grid +
      '<polyline points="' + pts + '" fill="none" stroke="#2B7BEC" stroke-width="2.2" stroke-linejoin="round"/>' +
      dots + '</svg>' + tail + '</div>';
  }

  function renderWeak(p) {
    var w = p.weak;
    if (!w.items.length) {
      var why = w.skipped ? '本班有作答的病例都不到 ' + w.min_cases + ' 人，样本太少暂不排行。' : '本班暂无该板块的作答记录。';
      return '<div class="bd-panel"><h3>' + esc(w.title) + '</h3><div class="bd-empty">' + why + '</div></div>';
    }
    var maxLoss = w.items[0].loss || 1;
    var rows = w.items.map(function (it, i) {
      var fill = it.loss >= 30 ? 'hi' : (it.loss < 15 ? 'lo' : '');
      return '<div class="bd-weakrow"><div class="rk' + (i < 3 ? ' t3' : '') + '">' + (i + 1) + '</div>' +
        '<div class="nm"><b>' + esc(it.name) + '</b>' + (it.subject ? '<span class="bd-tag">' + esc(it.subject) + '</span>' : '') + '</div>' +
        '<div class="track"><div class="fill ' + fill + '" style="width:' + Math.round(it.loss / maxLoss * 100) + '%"></div></div>' +
        '<div class="sc">均 <b>' + it.avg + '</b> · 失分 ' + it.loss + '% · n=' + it.n + '</div></div>';
    }).join('');
    var skip = w.skipped ? '<div class="bd-muted" style="margin-top:8px">另有 ' + w.skipped + ' 个病例完成人数不足 ' + w.min_cases + ' 人，未进榜。</div>' : '';
    var strong = (w.strong && w.strong.length) ? '<div class="bd-muted" style="margin-top:8px">做得最好的三例：' +
      w.strong.map(function (s) { return esc(s.name) + '（均 ' + s.avg + '）'; }).join('　') + '</div>' : '';
    return '<div class="bd-panel"><h3>' + esc(w.title) + '<small>按该例全班平均分升序 · 最该先讲</small></h3>' +
      '<div class="bd-weak">' + rows + '</div>' + skip + strong + '</div>';
  }

  function renderSubjects(p) {
    if (!p.subjects || !p.subjects.length) return '';
    var rows = p.subjects.map(function (s) {
      var ok = s.avg_final !== null && s.avg_done >= s.threshold;
      return '<tr><td class="l"><b>' + esc(s.name) + '</b></td><td>' + s.done_students + '</td>' +
        '<td>' + num(s.avg_done) + '</td><td>' + s.threshold + '</td>' +
        '<td style="color:' + (s.avg_final === null ? '#b9c3cd' : (ok ? '#27ae60' : '#c0392b')) + '"><b>' + num(s.avg_final) + '</b></td></tr>';
    }).join('');
    return '<div class="bd-panel"><h3>病例分析 · 按科目<small>折算分＝均分×min(完成数÷门槛,1)</small></h3>' +
      '<table class="bd-tbl"><thead><tr><th class="l">科目</th><th>完成人数</th><th>人均完成例数</th><th>门槛</th><th>平均折算分</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  // 科目按钮组：口内/口外/口修 各带自己的科室图标，选中态用主题色
  function subjGroup(p) {
    var cur = p.subject || '';
    var list = p.subject_options || [{ key: '', name: '全部科目' }];
    return '<div class="bd-subjgroup">' + list.map(function (o) {
      var ic = ICONS[o.key];
      return '<button class="bd-subj' + (ic ? '' : ' plain') + (o.key === cur ? ' active' : '') +
        '" data-sub="' + esc(o.key) + '" title="' + esc(o.name) + '">' +
        (ic ? '<svg viewBox="0 0 120 120">' + ic + '</svg>' : '') +
        '<span>' + esc(ic ? o.name : '全部') + '</span></button>';
    }).join('') + '</div>';
  }

  // 主题：默认暖青瓷，'purple' 切深紫（图标与选中态一起变）
  function setTheme(t) {
    var r = STATE.root || document.getElementById('boardRoot');
    if (!r) return;
    r.classList.toggle('bd-purple', t === 'purple');
    STATE.theme = t || 'teal';
  }

  // ── 整页渲染 ──────────────────────────────────────────
  function render(p) {
    STATE.last = p;
    var root = STATE.root;
    var opts = function (list, cur, key) {
      return list.map(function (o) {
        return '<option value="' + esc(o.key) + '"' + (o.key === cur ? ' selected' : '') + '>' + esc(o.name) + '</option>';
      }).join('');
    };
    var bar = '<div class="bd-bar">' +
      '<label>班级</label><select id="bdClass">' + opts([{ key: '', name: '全部班级' }].concat(p.classes.map(function (c) { return { key: c, name: c }; })), p['class'], '') + '</select>' +
      '<label>板块</label><select id="bdSection">' + opts(p.sections, p.section, '') + '</select>' +
      '<label>科目</label>' + subjGroup(p) +
      '<button class="bd-btn" id="bdPng">📥 导出 PNG</button>' +
      '<button class="bd-btn g" id="bdPdf">📥 导出 PDF</button>' +
      '<span class="bd-muted" id="bdTip"></span></div>';

    var body;
    if (p.empty) {
      body = '<div class="bd-panel"><div class="bd-empty">' + esc(p.sample_note || '暂无数据') + '</div></div>';
    } else {
      body = renderKPI(p) +
        '<div class="bd-2col">' + renderDist(p) + renderCurve(p) + '</div>' +
        renderWeak(p) + renderSubjects(p);
    }
    // 空态时提示语已在空态面板里说过一次，不再重复一条提示条
    var note = (!p.empty && p.sample_note) ? '<div class="bd-note">' + esc(p.sample_note) + '</div>' : '';
    var today = new Date();
    var stamp = today.getFullYear() + '-' + ('0' + (today.getMonth() + 1)).slice(-2) + '-' + ('0' + today.getDate()).slice(-2);
    var head = '<div class="bd-head"><div><div class="t">' + esc(p.title) + '</div>' +
      '<div class="s">学情看板 · 主口径：每人各例平均分</div></div>' +
      '<div class="d">生成时间 ' + stamp + '</div></div>';
    var foot = '<div class="bd-foot">说明：① 分数取每位学生在该板块各病例成绩的平均分，不取历史最高分（反复练习会虚高）。' +
      '② 病例榜按全班平均分升序，最上面是最该补讲的一例。' +
      '③ 练习曲线的样本数 n 随次数递减，后段只作趋势参考。</div>';

    root.innerHTML = bar + '<div id="captureRoot">' + head + note + body + foot + '</div>';

    function curSub() {
      var a = root.querySelector('.bd-subj.active');
      return a ? a.dataset.sub : '';
    }
    document.getElementById('bdClass').onchange = function () {
      load(this.value, document.getElementById('bdSection').value, curSub());
    };
    document.getElementById('bdSection').onchange = function () {
      // 换板块时科目回到「全部」，因为两个板块的科目覆盖面不同
      load(document.getElementById('bdClass').value, this.value, '');
    };
    Array.prototype.forEach.call(root.querySelectorAll('.bd-subj'), function (b) {
      b.onclick = function () {
        load(document.getElementById('bdClass').value, document.getElementById('bdSection').value, this.dataset.sub);
      };
    });
    document.getElementById('bdPng').onclick = exportPNG;
    document.getElementById('bdPdf').onclick = exportPDF;
  }

  // ── 取数 ──────────────────────────────────────────────
  function load(klass, section, subject) {
    subject = subject || '';
    STATE.cur = { 'class': klass, 'section': section, subject: subject };
    var tip = document.getElementById('bdTip');
    if (STATE.mode === 'static') {
      var p = (STATE.data || {})[klass + '||' + section + '||' + subject];
      if (!p) { if (tip) tip.textContent = '预览数据里没有这个组合'; return; }
      render(p);
      return;
    }
    if (tip) tip.textContent = '读取中…';
    // 用字符串拼接 + 引号紧跟括号，兼容 nginx 子路径代理的响应改写
    fetch(STATE.api + '?class=' + encodeURIComponent(klass) + '&section=' + encodeURIComponent(section) +
          '&subject=' + encodeURIComponent(subject))
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (p.error) { if (tip) tip.textContent = p.error; return; }
        if (tip) tip.textContent = '';
        render(p);
      })
      .catch(function () { if (tip) tip.textContent = '网络异常，请重试'; });
  }

  // ── 导出 ──────────────────────────────────────────────
  function snap() {
    var el = document.getElementById('captureRoot');
    if (!window.html2canvas) { toast('截图组件未加载，无法导出'); return null; }
    return window.html2canvas(el, { scale: 2, useCORS: true, backgroundColor: '#eef2f7', logging: false });
  }
  function fname(ext) {
    var p = STATE.last || {};
    return '学情看板_' + (p.section_name || '') + '_' + (p['class'] || '全部班级') +
      (p.subject ? '_' + p.subject : '') + '.' + ext;
  }
  function exportPNG() {
    var t = document.getElementById('bdTip'); if (t) t.textContent = '生成图片中…';
    var pr = snap();
    if (!pr) return;
    pr.then(function (canvas) {
      var a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = fname('png');
      a.click();
      if (t) t.textContent = '已导出 PNG';
    });
  }
  function exportPDF() {
    var t = document.getElementById('bdTip');
    if (!window.html2pdf) { toast('PDF 组件未加载，无法导出'); return; }
    if (t) t.textContent = '生成 PDF 中…';
    window.html2pdf().set({
      margin: 6,
      filename: fname('pdf'),
      image: { type: 'jpeg', quality: 0.95 },
      html2canvas: { scale: 2, useCORS: true, backgroundColor: '#eef2f7', logging: false },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
    }).from(document.getElementById('captureRoot')).save().then(function () {
      if (t) t.textContent = '已导出 PDF';
    });
  }

  // ── 入口 ──────────────────────────────────────────────
  function init(o) {
    o = o || {};
    if (!document.getElementById('bdStyle')) {
      var st = document.createElement('style');
      st.id = 'bdStyle'; st.textContent = CSS;
      document.head.appendChild(st);
    }
    STATE.mode = o.mode || 'live';
    STATE.data = o.data || window.__BOARD_DATA__ || null;
    STATE.root = o.root || document.getElementById('boardRoot');
    setTheme(o.theme || 'teal');
    // API 路径：优先 data-api，否则从本页地址推导（子路径代理下自动跟着走）
    STATE.api = o.api || STATE.root.getAttribute('data-api') ||
      location.pathname.replace(/\/+$/, '').replace(/\/board$/, '/api/board');

    if (STATE.mode === 'static') {
      var keys = Object.keys(STATE.data || {});
      if (!keys.length) { STATE.root.innerHTML = '<div class="bd-panel"><div class="bd-empty">预览数据为空</div></div>'; return; }
      var first = keys[0].split('||');
      load(first[0], first[1], first[2] || '');
      return;
    }
    // live：先空拉一次拿班级/板块列表
    STATE.root.innerHTML = '<div class="bd-panel"><div class="bd-empty">加载中…</div></div>';
    fetch(STATE.api)
      .then(function (r) { return r.json(); })
      .then(function (p) { load(p['class'], p.section, p.subject || ''); })
      .catch(function () { STATE.root.innerHTML = '<div class="bd-panel"><div class="bd-empty">加载失败，请刷新重试</div></div>'; });
  }

  window.BOARD = { init: init, load: load, render: render, setTheme: setTheme };
})();
