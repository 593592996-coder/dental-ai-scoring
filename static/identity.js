/* 学生身份门：进门先“学号+姓名”登录（有花名册时与名册核对）。
   用法：页面引入本脚本即可自动拦截；登录成功会调用 window.onIdentified(me)（若有），否则刷新。
   身份条：Identity.chip(容器元素) 渲染“姓名·学号·班级 / 退出”。 */
(function () {
  const ID_BG = 'linear-gradient(135deg,#1B3A5C,#2B7BEC)';

  function injectStyle() {
    const css = `
#idMask{position:fixed;inset:0;background:rgba(20,40,70,.55);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(2px)}
#idCard{background:#fff;border-radius:18px;padding:28px 30px;width:360px;max-width:92vw;box-shadow:0 18px 60px rgba(0,0,0,.3)}
#idCard h2{font-size:19px;color:#1B3A5C;margin-bottom:4px;text-align:center}
#idCard p.sub{font-size:12px;color:#888;text-align:center;margin-bottom:18px;line-height:1.6}
#idCard label{display:block;font-size:13px;font-weight:700;color:#1B3A5C;margin:12px 0 4px}
#idCard input{width:100%;padding:11px 13px;border:1.8px solid #cfd8e3;border-radius:9px;font-size:15px;box-sizing:border-box}
#idCard input:focus{outline:none;border-color:#2B7BEC}
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

  function showForm(roster) {
    const mask = document.createElement('div');
    mask.id = 'idMask';
    mask.innerHTML = `
      <div id="idCard">
        <h2>🦷 口腔临床训练</h2>
        <p class="sub">${roster ? '请用<b>学号 + 姓名</b>登录，系统与班级名册核对<br>姓名、班级自动带出' : '请填写本人信息后进入（首次登记）'}</p>
        <label>学号</label><input id="idSid" autocomplete="off" placeholder="请输入学号">
        <label>姓名</label><input id="idName" autocomplete="off" placeholder="请输入真实姓名">
        <div id="idClassWrap" ${roster ? 'style="display:none"' : ''}>
          <label>班级</label><input id="idClass" autocomplete="off" placeholder="如：2025级口腔医学1班">
        </div>
        <div id="idErr"></div>
        <button id="idBtn">进 入</button>
      </div>`;
    document.body.appendChild(mask);
    const $ = id => mask.querySelector(id);
    const sidEl = $('#idSid'), nameEl = $('#idName'), classEl = $('#idClass'),
          errEl = $('#idErr'), btn = $('#idBtn');
    setTimeout(() => sidEl.focus(), 50);

    function submit() {
      const sid = sidEl.value.trim(), name = nameEl.value.trim(),
            klass = classEl ? classEl.value.trim() : '';
      const isTeacher = sid.toLowerCase() === 'abc123';
      if (!sid) { errEl.textContent = '请输入学号'; return; }
      if (!isTeacher && (!name || (!roster && !klass))) { errEl.textContent = roster ? '请输入学号和姓名' : '请把学号、姓名、班级填齐'; return; }
      btn.disabled = true; btn.textContent = '核对中…'; errEl.textContent = '';
      api('/train/api/identify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_number: sid, name, class_name: klass })
      }).then(d => {
        if (d.ok) { mask.remove(); window.Identity.me = d; applyIdentity(d); if (typeof window.onIdentified === 'function') window.onIdentified(d); }
        else { errEl.textContent = d.error || '登录失败'; btn.disabled = false; btn.textContent = '进 入'; }
      }).catch(() => { errEl.textContent = '网络错误，请重试'; btn.disabled = false; btn.textContent = '进 入'; });
    }
    btn.addEventListener('click', submit);
    [sidEl, nameEl, classEl].forEach(el => el && el.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); }));
  }

  function applyIdentity(me) {
    // 评分页：自动带入姓名/班级并锁定（学号登录后不可改，防止替考/错填）
    const nameEl = document.getElementById('studentName');
    const classEl = document.getElementById('studentClass');
    const numEl = document.getElementById('studentNumber');
    if (nameEl) { nameEl.value = me.name || ''; nameEl.readOnly = true; nameEl.style.background = '#f0f4f8'; }
    if (classEl) { classEl.value = me.class_name || ''; classEl.readOnly = true; classEl.style.background = '#f0f4f8'; }
    if (numEl) numEl.value = me.student_number || '';
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
      el.innerHTML = `<span class="idchip"><b>${m.name}</b> ${m.student_number}${m.class_name ? ' · ' + m.class_name : ''}<a id="idLogout">退出</a></span>`;
      el.querySelector('#idLogout').addEventListener('click', () => {
        api('/train/api/logout', { method: 'POST' }).then(() => location.reload());
      });
    }
  };
  window.Identity = Identity;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => Identity.gate());
  else Identity.gate();
})();
