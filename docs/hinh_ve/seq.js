// Vẽ biểu đồ tuần tự UML từ mô tả: participants, steps (msg | frag-start | frag-end).
// msg: {f, t, l, k}: k = 'sync' (gọi, mũi tên đặc), 'ret' (trả về, nét đứt), 'async' (gửi bất đồng bộ, mũi tên mở), 'self'
const HALO = `paint-order="stroke" stroke="#fff" stroke-width="6" stroke-linejoin="round"`;
function drawSeq(spec) {
  const P = spec.participants, W = spec.width || 1160, colW = (W - 60) / P.length, ROW = spec.row || 46, TOP = 110;
  const X = i => 30 + colW * (i + 0.5);
  const idx = n => P.indexOf(n);
  let y = TOP, svg = [], frags = [], open = [], acts = {};
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // tính trước tọa độ
  const rows = [];
  for (const s of spec.steps) {
    if (s.frag) { open.push({ ...s, y0: y + 6 }); y += 40; continue; }
    if (s.end) { const f = open.pop(); f.y1 = y + 4; frags.push(f); y += 18; continue; }
    rows.push({ ...s, y: y + 30 }); y += s.k === 'self' ? ROW + 18 : ROW;
  }
  const H = y + 30;
  svg.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Arial, 'Segoe UI', sans-serif">`);
  svg.push(`<defs><marker id="fill" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="10" markerHeight="10" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#222"/></marker>
  <marker id="open" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="11" markerHeight="11" orient="auto"><path d="M0,0 L11,6 L0,12" fill="none" stroke="#222" stroke-width="1.6"/></marker></defs>`);
  // khung loop/opt (vẽ trước để nằm dưới)
  // khung ngoài vẽ trước khung lồng bên trong; inset thụt khung lồng vào so với khung ngoài
  frags.sort((p, q) => p.y0 - q.y0 || (q.y1 - q.y0) - (p.y1 - p.y0));
  for (const f of frags) {
    const xs = f.over.map(n => X(idx(n))), ins = f.inset || 0;
    const x0 = Math.min(...xs) - colW * 0.42 + ins, x1 = Math.max(...xs) + colW * 0.42 - ins;
    svg.push(`<rect x="${x0}" y="${f.y0}" width="${x1 - x0}" height="${f.y1 - f.y0}" fill="#fafafa" stroke="#888" stroke-width="1.5"/>`);
    const tw = 18 + f.frag.length * 11;
    svg.push(`<path d="M${x0},${f.y0} h${tw} v16 l-8,8 h${-(tw - 8)} z" fill="#eee" stroke="#888" stroke-width="1.2"/>`);
    svg.push(`<text x="${x0 + 6}" y="${f.y0 + 18}" font-size="17" font-weight="700" fill="#333">${f.frag}</text>`);
    svg.push(`<text x="${x0 + tw + 10}" y="${f.y0 + 19}" font-size="17" fill="#333" font-style="italic">[${esc(f.cond)}]</text>`);
  }
  // đường đời
  P.forEach((p, i) => {
    svg.push(`<line x1="${X(i)}" y1="${TOP - 20}" x2="${X(i)}" y2="${H - 10}" stroke="#999" stroke-width="1.6" stroke-dasharray="7 6"/>`);
    // tác nhân (spec.actors) vẽ hình người thay cho hộp
    if ((spec.actors || []).includes(p)) {
      const x = X(i);
      svg.push(`<g stroke="#222" stroke-width="2.2" fill="none"><circle cx="${x}" cy="28" r="10" fill="#fff"/><line x1="${x}" y1="38" x2="${x}" y2="62"/><line x1="${x - 16}" y1="46" x2="${x + 16}" y2="46"/><line x1="${x}" y1="62" x2="${x - 13}" y2="80"/><line x1="${x}" y1="62" x2="${x + 13}" y2="80"/></g>`);
      svg.push(`<text x="${x}" y="100" text-anchor="middle" font-size="19" font-weight="700" fill="#111" ${HALO}>${esc(p)}</text>`);
      return;
    }
    const bw = Math.min(colW - 16, 210);
    svg.push(`<rect x="${X(i) - bw / 2}" y="20" width="${bw}" height="70" rx="8" fill="#dbe8f6" stroke="#2f5d8a" stroke-width="2.2"/>`);
    const parts = p.split('\n');
    parts.forEach((t, k) => svg.push(`<text x="${X(i)}" y="${55 + (k - (parts.length - 1) / 2) * 23 + 7}" text-anchor="middle" font-size="20" font-weight="700" fill="#111">${esc(t)}</text>`));
  });
  // thanh kích hoạt
  for (const a of (spec.acts || [])) {
    const r0 = rows[a[1]].y - 6, r1 = rows[a[2]].y + 6, x = X(idx(a[0]));
    svg.push(`<rect x="${x - 7}" y="${r0}" width="14" height="${r1 - r0}" fill="#fff" stroke="#555" stroke-width="1.5"/>`);
  }
  // thông điệp
  for (const m of rows) {
    const a = X(idx(m.f)), b = X(idx(m.t));
    if (m.k === 'self') {
      svg.push(`<path d="M${a + 7},${m.y - 8} h48 v26 h-44" fill="none" stroke="#222" stroke-width="2" marker-end="url(#fill)"/>`);
      const last = idx(m.f) === P.length - 1;
      svg.push(`<text x="${last ? a - 14 : a + 62}" y="${m.y + 10}" font-size="19" fill="#111" text-anchor="${last ? "end" : "start"}" ${HALO}>${esc(m.l)}</text>`);
      continue;
    }
    const dir = b > a ? 1 : -1, x1 = a + dir * 7, x2 = b - dir * 7;
    const dash = m.k === 'ret' ? 'stroke-dasharray="9 6"' : '';
    const mk = m.k === 'sync' ? 'url(#fill)' : 'url(#open)';
    svg.push(`<line x1="${x1}" y1="${m.y}" x2="${x2}" y2="${m.y}" stroke="#222" stroke-width="2" ${dash} marker-end="${mk}"/>`);
    svg.push(`<text x="${(a + b) / 2}" y="${m.y - 8}" text-anchor="middle" font-size="19" fill="#111" ${HALO}>${esc(m.l)}</text>`);
  }
  svg.push('</svg>');
  document.body.innerHTML = svg.join('\n');
  document.body.style.margin = '0';
  document.title = `${W}x${H}`;
}
