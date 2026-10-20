const main = $('#main');
const params = new URLSearchParams(location.search);
const viewerToken = params.get('t') || sessionStorage.getItem('viewer');
if (params.get('t')) sessionStorage.setItem('viewer', params.get('t'));
const authHdr = viewerToken ? {Authorization: 'Bearer ' + viewerToken} : {};
const A = (p, o = {}) => api(p, {...o, headers: {...authHdr, ...(o.headers || {})}});

async function boot() {
  try { var me = await A('/api/me'); } catch { return loginView(); }
  $('#who').textContent = me.role === 'owner' ? 'owner' : 'viewer (read-only)';
  if (me.role === 'owner') { $('#logout').hidden = false; $('#logout').onclick = async () => { await api('/api/auth/logout', {method: 'POST'}); location.reload(); }; }
  dashboard(me);
}
function loginView(msg = '') {
  main.innerHTML = `<div class="card" style="max-width:420px"><h2>Owner login</h2>
    <form id="f"><label>Password</label><input type="password" id="pw" required autocomplete="current-password" style="width:100%">
    <label>Authenticator code</label><input id="totp" inputmode="numeric" autocomplete="one-time-code" style="width:100%">
    <button>Log in</button> <button type="button" class="secondary" id="setup">First-time setup</button></form><p class="err">${esc(msg)}</p></div>`;
  $('#f').onsubmit = async e => { e.preventDefault(); try { await api('/api/auth/login', {method: 'POST', json: {password: $('#pw').value, totp: $('#totp').value}}); boot(); } catch (x) { loginView(x.message); } };
  $('#setup').onclick = async () => { try { const r = await api('/api/auth/setup', {method: 'POST', json: {password: $('#pw').value}}); main.innerHTML = `<div class="card"><h2>Add to your authenticator app</h2><p>Scan or paste this URI into an authenticator, then log in.</p><textarea readonly style="width:100%" rows="3">${esc(r.totp_uri)}</textarea><button onclick="location.reload()">Continue</button></div>`; } catch (x) { loginView(x.message); } };
}
async function dashboard(me) {
  const owner = me.role === 'owner', can = s => me.scope.includes(s);
  const [fit, vol, goal, wk] = await Promise.all([
    can('metrics') ? A('/api/metrics/fitness') : [], can('metrics') ? A('/api/metrics/volume') : [],
    can('metrics') ? A('/api/metrics/goal') : null, can('workouts') ? A('/api/workouts?limit=15') : []]);
  const last = fit.at(-1);
  main.innerHTML = `
  <div class="grid"><div class="card"><h2>Fitness (CTL)</h2><div class="stat">${last ? last.ctl.toFixed(0) : '-'}</div><div class="muted">fatigue ${last ? last.atl.toFixed(0) : '-'}, form ${last ? last.tsb.toFixed(0) : '-'}</div></div>
  <div class="card"><h2>Race goal</h2>${goal ? `<b>${esc(goal.name)}</b><div class="muted">${goal.race_date}, ${goal.weeks_remaining} weeks. CTL ${goal.current_ctl.toFixed(0)} / ${goal.target_ctl ?? '?'} (${goal.percent_of_target ?? '-'}%)</div>` : '<div class="muted">No goal set</div>'}</div></div>
  <div class="card"><h2>Fitness, fatigue, form</h2>${lineChart([{name: 'CTL', points: fit.map(r => [new Date(r.day), r.ctl])}, {name: 'ATL', points: fit.map(r => [new Date(r.day), r.atl])}, {name: 'TSB', points: fit.map(r => [new Date(r.day), r.tsb])}])}</div>
  <div class="card"><h2>Weekly volume (hours)</h2>${volumeChart(vol)}</div>
  <div class="card"><h2>Recent workouts</h2><table><tr><th>Date</th><th>Sport</th><th>Time</th><th>km</th><th>TSS</th><th>Src</th></tr>${wk.map(w => `<tr><td>${w.start_time.slice(0, 10)}</td><td>${w.sport}</td><td>${dur(w.duration_s)}</td><td>${w.distance_m ? (w.distance_m / 1000).toFixed(1) : ''}</td><td>${w.tss != null ? w.tss.toFixed(0) + ' <span class="muted">' + w.tss_method + '</span>' : '<span class="err" title="' + esc(w.flagged) + '">flagged</span>'}</td><td>${w.source}</td></tr>`).join('')}</table></div>
  ${can('predictions') || can('plans') ? '<div class="card" id="insights"><h2>Insights and plan</h2><p class="muted">Loading...</p></div>' : ''}
  ${owner ? ownerTools() : ''}
  <p class="muted">${DISCLAIMER}</p>`;
  if (can('predictions') || can('plans')) insights(owner, can);
  if (owner) wireOwner();
}
const fmtT = s => `${Math.floor(s / 3600)}h${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`;
async function insights(owner, can) {
  const el = $('#insights'); let h = '';
  try {
    if (can('predictions')) {
      const [risk, rt, fc, an] = await Promise.all([A('/api/predictions/risk'), A('/api/predictions/race-time'), A('/api/predictions/forecast'), A('/api/predictions/anomalies')]);
      h += `<div>Overtraining risk: <span class="pill">${esc(risk.level)}</span> <span class="muted">${esc((risk.factors || []).join('; '))}</span></div>`;
      h += `<div>Race-time estimate: ${rt.status === 'ok' ? `<b>${fmtT(rt.finish_seconds)}</b> <span class="muted">(${fmtT(rt.range_seconds[0])} to ${fmtT(rt.range_seconds[1])}, ${rt.model})</span>` : `<span class="muted">${esc(rt.status)}: ${esc(rt.note || '')}</span>`}</div>`;
      h += `<div>Race-day form if load holds: ${fc.forecast ? `CTL ${fc.forecast.race_day.ctl}, TSB ${fc.forecast.race_day.tsb} <span class="muted">(${fc.forecast.assumed_weekly_tss} TSS/week)</span>` : '<span class="muted">set a race goal and sync data</span>'}</div>`;
      h += `<div>Anomalies: ${an.status === 'ok' ? an.flagged.length + ' flagged' : '<span class="muted">' + esc(an.status) + '</span>'}</div>`;
    }
    if (can('plans')) {
      const plans = await A('/api/plans');
      const p = plans[0];
      h += `<h2 style="margin-top:12px">Latest weekly plan</h2>` + (p ? `<div class="muted">week of ${p.week_start}, ${p.plan.planned_tss} TSS planned</div><table>${p.plan.sessions.map(s => `<tr><td>${s.day}</td><td>${s.sport}</td><td>${s.minutes} min</td><td>${s.intensity}</td><td>${esc(s.intent)}</td></tr>`).join('')}</table>${p.adjustments.length ? '<div class="muted">Safety adjustments: ' + esc(p.adjustments.map(a => a.detail).join('; ')) + '</div>' : ''}` : '<div class="muted">No plan yet.</div>');
    }
    if (owner) h += '<button id="gen">Generate next week\'s plan</button> <span id="genmsg" class="muted"></span>';
    h += `<p class="muted">${DISCLAIMER}</p>`;
    el.innerHTML = h;
    if (owner) $('#gen').onclick = async () => { $('#genmsg').textContent = 'Generating...'; try { await A('/api/plans/generate', {method: 'POST', json: {}}); boot(); } catch (e) { $('#genmsg').textContent = e.message; $('#genmsg').className = 'err'; } };
  } catch (e) { el.innerHTML = `<h2>Insights and plan</h2><p class="err">${esc(e.message)}</p>`; }
}
function ownerTools() {
  return `<div class="grid">
  <div class="card"><h2>Strava</h2><p class="muted">Connect your account, then sync. Needs IRONMAN_STRAVA_CLIENT_ID/SECRET.</p><button id="sconn">Connect Strava</button> <button class="secondary" id="ssync">Sync now</button><p id="smsg" class="muted"></p></div>
  <div class="card"><h2>Upload FIT / GPX</h2><input type="file" id="up" accept=".fit,.gpx"><br><select id="upsport"><option>other</option><option>swim</option><option>bike</option><option>run</option></select> <button id="upb">Upload</button><p id="upmsg" class="muted"></p></div>
  <div class="card"><h2>Thresholds</h2><form id="th">
    <label>Effective from</label><input type="date" name="effective_from" required><label>FTP (W)</label><input name="ftp" type="number" step="any">
    <label>Run threshold pace (s/km)</label><input name="run_threshold_pace" type="number" step="any"><label>Swim CSS (s/100m)</label><input name="swim_css" type="number" step="any">
    <label>Max HR</label><input name="max_hr" type="number" step="any"><label>Threshold HR</label><input name="lthr" type="number" step="any"><button>Save</button> <span id="thmsg" class="muted"></span></form></div>
  <div class="card"><h2>Race goal</h2><form id="gl"><label>Name</label><input name="name" required><label>Date</label><input type="date" name="race_date" required>
    <label>Target finish (seconds)</label><input name="target_seconds" type="number"><label>Target CTL</label><input name="target_ctl" type="number" step="any"><button>Save</button> <span id="glmsg" class="muted"></span></form></div>
  <div class="card"><h2>Share with a coach</h2><label>Scope</label><select id="lsc" multiple size="4"><option selected>metrics</option><option>workouts</option><option>plans</option><option>predictions</option></select>
    <label>Valid for (days)</label><input id="ld" type="number" value="14"><button id="lnew">Create link</button><div id="lout" class="muted"></div><table id="llist"></table></div></div>`;
}
function num(fd) { const o = {}; for (const [k, v] of fd) o[k] = v === '' ? null : (k === 'effective_from' || k === 'race_date' || k === 'name') ? v : +v; return o; }
async function wireOwner() {
  const msg = (id, t, bad) => { const e = $(id); e.textContent = t; e.className = bad ? 'err' : 'ok'; };
  $('#sconn').onclick = async () => { try { location = (await A('/api/strava/connect')).url; } catch (e) { msg('#smsg', e.message, 1); } };
  $('#ssync').onclick = async () => { try { await A('/api/strava/sync', {method: 'POST'}); msg('#smsg', 'Sync queued; refresh in a minute.'); } catch (e) { msg('#smsg', e.message, 1); } };
  $('#upb').onclick = async () => { const f = $('#up').files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f); try { const r = await A('/api/workouts/upload?sport=' + $('#upsport').value, {method: 'POST', body: fd}); msg('#upmsg', r.outcome); setTimeout(boot, 500); } catch (e) { msg('#upmsg', e.message, 1); } };
  $('#th').onsubmit = async e => { e.preventDefault(); try { await A('/api/thresholds', {method: 'PUT', json: num(new FormData(e.target))}); msg('#thmsg', 'Saved, workouts rescored'); setTimeout(boot, 500); } catch (x) { msg('#thmsg', x.message, 1); } };
  $('#gl').onsubmit = async e => { e.preventDefault(); try { await A('/api/goal', {method: 'PUT', json: num(new FormData(e.target))}); msg('#glmsg', 'Saved'); setTimeout(boot, 500); } catch (x) { msg('#glmsg', x.message, 1); } };
  const links = async () => { const l = await A('/api/share-links'); $('#llist').innerHTML = l.map(x => `<tr><td>${esc(x.scope.join(','))}</td><td>${x.expires_at.slice(0, 10)}</td><td>${x.revoked_at ? 'revoked' : `<a href="#" data-id="${x.id}">revoke</a>`}</td></tr>`).join(''); $('#llist').querySelectorAll('a').forEach(a => a.onclick = async ev => { ev.preventDefault(); await A('/api/share-links/' + a.dataset.id, {method: 'DELETE'}); links(); }); };
  $('#lnew').onclick = async () => { const r = await A('/api/share-links', {method: 'POST', json: {scope: [...$('#lsc').selectedOptions].map(o => o.value), days: +$('#ld').value}}); $('#lout').innerHTML = 'Share URL (shown once): <code>' + esc(location.origin + '/?t=' + r.token) + '</code>'; links(); };
  links();
}
boot();
