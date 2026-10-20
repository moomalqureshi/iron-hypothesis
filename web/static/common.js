const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, opts = {}) {
  const r = await fetch(path, {credentials: 'same-origin', ...opts,
    headers: {...(opts.json ? {'Content-Type': 'application/json'} : {}), ...(opts.headers || {})},
    body: opts.json ? JSON.stringify(opts.json) : opts.body});
  const text = await r.text();
  let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) throw Object.assign(new Error((data && data.detail) || r.statusText), {status: r.status});
  return data;
}
const COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)'];
// Line chart: series = [{name, points:[[x(Date|number), y]]}]
function lineChart(series, {w = 640, h = 220, pad = 34} = {}) {
  const pts = series.flatMap(s => s.points);
  if (!pts.length) return '<p class="muted">No data yet.</p>';
  const xs = pts.map(p => +p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(0, ...ys), y1 = Math.max(...ys, 1);
  const X = v => pad + (x1 === x0 ? 0 : (v - x0) / (x1 - x0)) * (w - pad - 8), Y = v => h - pad - (v - y0) / (y1 - y0) * (h - pad - 8);
  const grid = [0, .5, 1].map(f => { const v = y0 + f * (y1 - y0); return `<line x1="${pad}" x2="${w - 8}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${pad - 4}" y="${Y(v) + 4}" font-size="10" text-anchor="end" fill="var(--muted)">${v.toFixed(0)}</text>`; }).join('');
  const lines = series.map((s, i) => `<polyline fill="none" stroke="${COLORS[i % 4]}" stroke-width="2" points="${s.points.map(p => X(+p[0]) + ',' + Y(p[1])).join(' ')}"/>`).join('');
  const d = v => new Date(v).toISOString().slice(0, 10);
  return `<svg viewBox="0 0 ${w} ${h}" role="img">${grid}${lines}<text x="${pad}" y="${h - 8}" font-size="10" fill="var(--muted)">${d(x0)}</text><text x="${w - 8}" y="${h - 8}" font-size="10" text-anchor="end" fill="var(--muted)">${d(x1)}</text></svg>` + legend(series.map(s => s.name));
}
function legend(names) { return '<div class="legend">' + names.map((n, i) => `<span><i style="background:${COLORS[i % 4]}"></i>${esc(n)}</span>`).join('') + '</div>'; }
// Stacked weekly bars by sport
function volumeChart(rows, {w = 640, h = 220, pad = 34} = {}) {
  if (!rows.length) return '<p class="muted">No data yet.</p>';
  const sports = ['swim', 'bike', 'run'], weeks = [...new Set(rows.map(r => r.week_start))].sort();
  const tot = wk => rows.filter(r => r.week_start === wk).reduce((a, r) => a + r.hours, 0), max = Math.max(...weeks.map(tot), 1);
  const bw = (w - pad - 8) / weeks.length;
  const bars = weeks.map((wk, i) => { let y = h - pad; return sports.map((sp, j) => { const r = rows.find(r => r.week_start === wk && r.sport === sp); if (!r) return ''; const hh = r.hours / max * (h - pad - 8); y -= hh; return `<rect x="${pad + i * bw + 1}" y="${y}" width="${Math.max(bw - 2, 1)}" height="${hh}" fill="${COLORS[j]}"><title>${wk} ${sp}: ${r.hours.toFixed(1)} h</title></rect>`; }).join(''); }).join('');
  return `<svg viewBox="0 0 ${w} ${h}" role="img"><text x="${pad - 4}" y="14" font-size="10" text-anchor="end" fill="var(--muted)">${max.toFixed(0)}h</text>${bars}</svg>` + legend(sports);
}
const dur = s => `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`;
const DISCLAIMER = 'Training signals only, not medical advice.';
