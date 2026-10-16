/* 学生身份门：进门先选机构 → 机构决定登录方式
   学校：学号+姓名（有花名册时与名册核对）；门诊/校外：手机号+姓名自助登记。
   用法：页面引入本脚本即可自动拦截；登录成功会调用 window.onIdentified(me)（若有），否则刷新。
   身份条：Identity.chip(容器元素) 渲染“姓名·账号·班级 / 退出”。 */
(function () {
  const ID_BG = 'linear-gradient(135deg,#1B3A5C,#2B7BEC)';
  // 机构选项：school=医专（学号登录）；其余手机号登录；other=其他机构（再填机构名）
  const ORGS = [
    { v: '楚雄医药高等专科学校', t: '🏫 楚雄医药高等专科学校', phone: false },
    { v: '艾美口腔', t: '🦷 艾美口腔', phone: true },
    { v: '周朝美口腔', t: '🦷 周朝美口腔', phone: true },
    { v: '__other__', t: '🏢 其他机构（校外人员）', phone: true, custom: true }
  ];

  function injectStyle() {
    const css = `
#idMask{position:fixed;inset:0;background:rgba(20,40,70,.55);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px)}
#idCard{background:#fff;border-radius:18px;padding:28px 30px;width:360px;max-width:92vw;box-shadow:0 18px 60px rgba(0,0,0,.3)}
#idCard h2{font-size:19px;color:#1B3A5C;margin-bottom:4px;text-align:center}
#idCard p.sub{font-size:12px;color:#888;text-align:center;margin-bottom:18px;line-height:1.6}
#idCard label{display:block;font-size:13px;font-weight:700;color:#1B3A5C;margin:12px 0 4px}
#idCard input,#idCard select{width:100%;padding:11px 13px;border:1.8px solid #cfd8e3;border-radius:9px;font-size:15px;box-sizing:border-box;background:#fff}
#idCard input:focus,#idCard select:focus{outline:none;border-color:#2B7BEC}
#idBtn{width:100%;margin-top:20px;padding:12px;border:none;border-radius:9px;color:#fff;font-size:15px;font-weight:700;cursor:pointer;background:${ID_BG}}
#idBtn:disabled{opacity:.5}
#idErr{color:#c0392b;font-size:12.5px;margin-top:10px;min-height:16px;text-align:center}
.idchip{display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.15);border-radius:20px;padding:4px 8px 4px 12px;font-size:12px}
.idchip b{font-weight:700}
.idchip a{color:#fff;opacity:.9;cursor:pointer;text-decoration:underline;background:rgba(0,0,0,.12);border-radius:20px;padding:2px 9px}
`;
    const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s);
  }

  function api(url, opts) {
    return fetch(url, opts).then(r => r.json());
  }

  /* 三科室图标（static/js/subject_icons.js）。登录门被 9 个页面共用，
     与其让每个页面都引一遍，不如这里按需加载；取不到就回落原来的 emoji。 */
  function withIcons(cb) {
    if (window.SUBJECT_ICONS) { cb(); return; }
    const s = document.createElement('script');
    s.src = '/static/js/subject_icons.js';
    s.onload = cb; s.onerror = cb;
    document.head.appendChild(s);
  }
  function subjectLogoSvg() {
    const ic = (window.SUBJECT_ICONS || {})['口内'];
    if (!ic) return '🦷';
    return '<svg viewBox="0 0 120 120" style="width:30px;height:30px;flex:none;color:#2E7D8A;--bd-ring:#CFE3E6">' + ic + '</svg>';
  }

  function showForm(roster) {
    const mask = document.createElement('div');
    mask.id = 'idMask';
    mask.innerHTML = `
      <div id="idCard">
        <h2 style="display:flex;align-items:center;justify-content:center;gap:8px"><span id="idLogo">🦷</span>口腔临床训练</h2>
        <p class="sub" id="idSub">在校学生请用<b>学号 + 姓名</b>登录，系统与班级名册核对</p>
        <label>所属机构</label>
        <select id="idOrg">${ORGS.map(o => `<option value="${o.v}">${o.t}</option>`).join('')}</select>
        <div id="idOrgNameWrap" style="display:none">
          <label>机构名称</label><input id="idOrgName" autocomplete="off" placeholder="如：XX医院口腔科 / XX口腔诊所">
        </div>
        <label id="idAccountLabel">学号</label><input id="idAccount" autocomplete="off" placeholder="请输入学号">
        <label>姓名</label><input id="idName" autocomplete="off" placeholder="请输入真实姓名">
        <div id="idClassWrap" ${roster ? 'style="display:none"' : ''}>
          <label>班级</label><input id="idClass" autocomplete="off" placeholder="如：2025级口腔医学1班">
        </div>
        <div id="idErr"></div>
        <button id="idBtn">进 入</button>
        <div style="text-align:center;margin-top:16px;padding-top:13px;border-top:1px solid #eef2f7">
          <a href="/admin/login" style="font-size:12.5px;color:#9aa7b4;text-decoration:none">教师入口</a>
        </div>
      </div>`;
    document.body.appendChild(mask);
    // 图标加载完再替换成真图标（取不到就保留 emoji）
    withIcons(() => {
      const logo = mask.querySelector('#idLogo');
      if (logo && window.SUBJECT_ICONS) logo.innerHTML = subjectLogoSvg();
    });
    const $ = id => mask.querySelector(id);
    const orgEl = $('#idOrg'), orgNameEl = $('#idOrgName'), accountEl = $('#idAccount'),
          accountLabel = $('#idAccountLabel'), nameEl = $('#idName'), classEl = $('#idClass'),
          orgNameWrap = $('#idOrgNameWrap'), classWrap = $('#idClassWrap'),
          errEl = $('#idErr'), btn = $('#idBtn'), subEl = $('#idSub');
    setTimeout(() => accountEl.focus(), 50);

    function curOrg() { return ORGS.find(o => o.v === orgEl.value); }

    function syncMode() {
      const o = curOrg();
      orgNameWrap.style.display = o.custom ? 'block' : 'none';
      // 班级只在“学校 + 无花名册”时需要；手机号登录没有班级
      classWrap.style.display = (!o.phone && !roster) ? 'block' : 'none';
      accountLabel.textContent = o.phone ? '手机号' : '学号';
      accountEl.placeholder = o.phone ? '请输入11位手机号' : '请输入学号';
      subEl.innerHTML = o.phone
        ? '门诊及校外人员用 <b>手机号 + 姓名</b> 自助登记，无需审核'
        : (roster ? '请用<b>学号 + 姓名</b>登录，系统与班级名册核对<br>姓名、班级自动带出'
                  : '请填写本人信息后进入（首次登记）');
    }
    orgEl.addEventListener('change', syncMode);
    syncMode();

    function submit() {
      const o = curOrg();
      const account = accountEl.value.trim(), name = nameEl.value.trim(),
            klass = classEl ? classEl.value.trim() : '';
      const isTeacher = account.toLowerCase() === 'abc123';
      let org = o.v, orgName = orgNameEl.value.trim();

      if (isTeacher) {
        // 教师试用账号：直接走学校学号通道
      } else if (o.phone) {
        if (o.custom && !orgName) { errEl.textContent = '请填写机构名称'; return; }
        if (!/^1\d{10}$/.test(account)) { errEl.textContent = '请输入正确的11位手机号'; return; }
        if (!name) { errEl.textContent = '请输入姓名'; return; }
        if (o.custom) org = orgName;
      } else {
        if (!account) { errEl.textContent = '请输入学号'; return; }
        if (!name || (!roster && !klass)) { errEl.textContent = roster ? '请输入学号和姓名' : '请把学号、姓名、班级填齐'; return; }
      }

      const payload = isTeacher
        ? { student_number: account, name, class_name: klass, org: '', account_type: 'sid' }
        : { org, account_type: o.phone ? 'phone' : 'sid', account,
            name, class_name: klass };
      btn.disabled = true; btn.textContent = '核对中…'; errEl.textContent = '';
      api('/train/api/identify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(d => {
        if (d.ok) { mask.remove(); window.Identity.me = d; applyIdentity(d); if (typeof window.onIdentified === 'function') window.onIdentified(d); }
        else { errEl.textContent = d.error || '登录失败'; btn.disabled = false; btn.textContent = '进 入'; }
      }).catch(() => { errEl.textContent = '网络错误，请重试'; btn.disabled = false; btn.textContent = '进 入'; });
    }
    btn.addEventListener('click', submit);
    [orgNameEl, accountEl, nameEl, classEl].forEach(el => el && el.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); }));
  }

  function applyIdentity(me) {
    // 评分页：自动带入姓名/班级并锁定（登录后不可改，防止替考/错填）
    const nameEl = document.getElementById('studentName');
    const classEl = document.getElementById('studentClass');
    const numEl = document.getElementById('studentNumber');
    if (nameEl) { nameEl.value = me.name || ''; nameEl.readOnly = true; nameEl.style.background = '#f0f4f8'; }
    if (classEl) { classEl.value = me.class_name || ''; classEl.readOnly = true; classEl.style.background = '#f0f4f8'; }
    if (numEl) numEl.value = me.account || me.student_number || '';
    // 身份条：有专用槽位用槽位，否则固定悬浮右上角
    let slot = document.getElementById('idChipSlot');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'idChipSlot';
      slot.style.cssText = 'position:fixed;top:10px;right:12px;z-index:9998';
      document.body.appendChild(slot);
    }
    Identity.chip(slot);
  }

  const Identity = {
    me: null,
    gate() {
      injectStyle();
      return api('/train/api/me').then(d => {
        if (d.identified) { this.me = d; applyIdentity(d); if (typeof window.onIdentified === 'function') window.onIdentified(d); return d; }
        showForm(!!d.roster);
        return null;
      });
    },
    chip(el) {
      if (!el || !this.me) return;
      const m = this.me;
      const acct = m.account || m.student_number;
      el.innerHTML = `<span class="idchip"><b>${m.name}</b> ${acct}${m.org ? ' · ' + m.org : (m.class_name ? ' · ' + m.class_name : '')}<a id="idLogout">退出</a></span>`;
      el.querySelector('#idLogout').addEventListener('click', () => {
        api('/train/api/logout', { method: 'POST' }).then(() => location.reload());
      });
    }
  };
  window.Identity = Identity;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => Identity.gate());
  else Identity.gate();
})();
