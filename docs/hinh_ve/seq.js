// Vẽ biểu đồ tuần tự theo ký pháp UML 2.5.1 từ mô tả: participants, steps (msg | frag-start | frag-end).
// msg: {f, t, l, k}: k = 'sync' (gọi đồng bộ: nét liền, đầu tam giác đặc), 'async' (gửi bất đồng bộ: nét liền,
// đầu mở), 'ret' (trả về: nét đứt, đầu mở), 'self' (lời gọi tự thân, có thanh kích hoạt lồng).
// Thanh kích hoạt: bên nhận lời gọi đồng bộ được vẽ tự động tới mũi tên trả về tương ứng (tìm trong 6 thông điệp
// kế tiếp, không có thì vẽ thanh ngắn); spec.acts = [[tên, hàng đầu, hàng cuối]] là thanh của bên chủ động xử lý.
const HALO = `paint-order="stroke" stroke="#fff" stroke-width="6" stroke-linejoin="round"`;
function drawSeq(spec) {
  const P = spec.participants, W = spec.width || 1160, colW = (W - 60) / P.length, ROW = spec.row || 48, TOP = 110;
  const FS = spec.fs || 21;
  const X = i => 30 + colW * (i + 0.5);
  const idx = n => P.indexOf(n);
  let y = TOP, svg = [], frags = [], open = [];
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // tính trước tọa độ
  const rows = [];
  for (const s of spec.steps) {
    if (s.frag) { open.push({ ...s, y0: y + 6 }); y += 42; continue; }
    if (s.end) { const f = open.pop(); f.y1 = y + 4; frags.push(f); y += 18; continue; }
    rows.push({ ...s, y: y + 30 }); y += s.k === 'self' ? ROW + 20 : ROW;
  }
  const LEG = spec.legend === false ? 0 : 74;
  const H = y + 30 + LEG;
  svg.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Arial, 'Segoe UI', sans-serif">`);
  svg.push(`<defs><marker id="fill" viewBox="0 0 10 10" refX="10" refY="5" markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="16" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#222"/></marker>
  <marker id="open" viewBox="0 0 12 12" refX="11.5" refY="6" markerUnits="userSpaceOnUse" markerWidth="17" markerHeight="17" orient="auto"><path d="M0,0.5 L11.5,6 L0,11.5" fill="none" stroke="#222" stroke-width="1.7"/></marker></defs>`);
  // khung loop/opt (vẽ trước để nằm dưới); khung ngoài vẽ trước khung lồng, inset thụt khung lồng vào
  frags.sort((p, q) => p.y0 - q.y0 || (q.y1 - q.y0) - (p.y1 - p.y0));
  for (const f of frags) {
    const xs = f.over.map(n => X(idx(n))), ins = f.inset || 0;
    const x0 = Math.min(...xs) - colW * 0.42 + ins, x1 = Math.max(...xs) + colW * 0.42 - ins;
    svg.push(`<rect x="${x0}" y="${f.y0}" width="${x1 - x0}" height="${f.y1 - f.y0}" fill="#fafafa" stroke="#888" stroke-width="1.5"/>`);
    f.x0 = x0;
  }
  // nhãn khung vẽ sau cùng (trên thanh kích hoạt), có viền trắng
  const fragLabels = frags.map(f => {
    const tw = 20 + f.frag.length * 12;
    return `<path d="M${f.x0},${f.y0} h${tw} v18 l-8,8 h${-(tw - 8)} z" fill="#eee" stroke="#888" stroke-width="1.2"/>` +
      `<text x="${f.x0 + 6}" y="${f.y0 + 20}" font-size="19" font-weight="700" fill="#333">${f.frag}</text>` +
      `<text x="${f.x0 + tw + 10}" y="${f.y0 + 21}" font-size="19" fill="#333" font-style="italic" ${HALO}>[${esc(f.cond)}]</text>`;
  });
  // đường đời và đầu đường đời
  P.forEach((p, i) => {
    svg.push(`<line x1="${X(i)}" y1="${TOP - 20}" x2="${X(i)}" y2="${H - 10 - LEG}" stroke="#999" stroke-width="1.6" stroke-dasharray="7 6"/>`);
    if ((spec.actors || []).includes(p)) {
      const x = X(i);
      svg.push(`<g stroke="#222" stroke-width="2.2" fill="none"><circle cx="${x}" cy="28" r="10" fill="#fff"/><line x1="${x}" y1="38" x2="${x}" y2="62"/><line x1="${x - 16}" y1="46" x2="${x + 16}" y2="46"/><line x1="${x}" y1="62" x2="${x - 13}" y2="80"/><line x1="${x}" y1="62" x2="${x + 13}" y2="80"/></g>`);
      svg.push(`<text x="${x}" y="100" text-anchor="middle" font-size="21" font-weight="700" fill="#111" ${HALO}>${esc(p)}</text>`);
      return;
    }
    const bw = Math.min(colW - 16, 210);
    svg.push(`<rect x="${X(i) - bw / 2}" y="20" width="${bw}" height="70" rx="8" fill="#dbe8f6" stroke="#2f5d8a" stroke-width="2.2"/>`);
    const parts = p.split('\n');
    parts.forEach((t, k) => svg.push(`<text x="${X(i)}" y="${55 + (k - (parts.length - 1) / 2) * 24 + 7}" text-anchor="middle" font-size="21" font-weight="700" fill="#111">${esc(t)}</text>`));
  });
  // thanh kích hoạt: thanh của bên chủ động (spec.acts), thanh của bên nhận lời gọi đồng bộ, thanh lồng của lời gọi tự thân
  const bars = [];
  for (const a of (spec.acts || [])) bars.push({ p: a[0], y0: rows[a[1]].y - 8, y1: rows[a[2]].y + 8, lv: 0 });
  rows.forEach((m, i) => {
    if (m.k !== 'sync' || m.f === m.t) return;
    let j = -1;
    for (let k = i + 1; k < Math.min(rows.length, i + 7); k++) {
      if (rows[k].f === m.f && rows[k].t === m.t) break;  // lời gọi mới giữa cùng hai bên: lời gọi trước không có trả về
      if (rows[k].k === 'ret' && rows[k].f === m.t && rows[k].t === m.f) { j = k; break; }
    }
    const y0 = m.y - 4, y1 = j >= 0 ? rows[j].y + 4 : m.y + 16;
    if (bars.some(b => b.p === m.t && b.y0 <= y0 && b.y1 >= y1)) return;
    bars.push({ p: m.t, y0, y1, lv: 0 });
  });
  rows.forEach(m => { if (m.k === 'self') bars.push({ p: m.f, y0: m.y - 2, y1: m.y + 26, lv: 1 }); });
  for (const b of bars) {
    const x = X(idx(b.p)) + b.lv * 8;
    svg.push(`<rect x="${x - 7}" y="${b.y0}" width="14" height="${b.y1 - b.y0}" fill="#fff" stroke="#555" stroke-width="1.5"/>`);
  }
  // thông điệp
  for (const m of rows) {
    const a = X(idx(m.f)), b = X(idx(m.t));
    if (m.k === 'self') {
      svg.push(`<path d="M${a + 7},${m.y - 8} h52 v24 h-${52 - 8}" fill="none" stroke="#222" stroke-width="2" marker-end="url(#fill)"/>`);
      const last = idx(m.f) === P.length - 1;
      svg.push(`<text x="${last ? a - 14 : a + 68}" y="${m.y + 10}" font-size="${FS}" fill="#111" text-anchor="${last ? "end" : "start"}" ${HALO}>${esc(m.l)}</text>`);
      continue;
    }
    const dir = b > a ? 1 : -1, x1 = a + dir * 7, x2 = b - dir * 7;
    const dash = m.k === 'ret' ? 'stroke-dasharray="10 6"' : '';
    const mk = m.k === 'sync' ? 'url(#fill)' : 'url(#open)';
    svg.push(`<line x1="${x1}" y1="${m.y}" x2="${x2}" y2="${m.y}" stroke="#222" stroke-width="2" ${dash} marker-end="${mk}"/>`);
    svg.push(`<text x="${(a + b) / 2}" y="${m.y - 9}" text-anchor="middle" font-size="${FS}" fill="#111" ${HALO}>${esc(m.l)}</text>`);
  }
  svg.push(...fragLabels);
  // chú giải ký pháp: mỗi mục rộng theo độ dài chữ
  if (LEG) {
    const ly = H - LEG + 18, lh = 44, items = [
      ['sync', 'gọi đồng bộ (bên gọi chờ kết quả)'], ['async', 'gửi bất đồng bộ (không chờ)'], ['ret', 'trả về']];
    svg.push(`<rect x="30" y="${ly - 6}" width="${W - 60}" height="${lh + 12}" fill="#fff" stroke="#bbb" stroke-width="1.2"/>`);
    svg.push(`<text x="44" y="${ly + 27}" font-size="18" font-weight="700" fill="#333">UML 2.5.1:</text>`);
    let x = 160;
    for (const [k, t] of items) {
      svg.push(`<line x1="${x}" y1="${ly + 21}" x2="${x + 50}" y2="${ly + 21}" stroke="#222" stroke-width="2" ${k === 'ret' ? 'stroke-dasharray="10 6"' : ''} marker-end="url(#${k === 'sync' ? 'fill' : 'open'})"/>`);
      svg.push(`<text x="${x + 60}" y="${ly + 27}" font-size="18" fill="#222">${esc(t)}</text>`);
      x += 60 + t.length * 9.4 + 40;
    }
  }
  svg.push('</svg>');
  document.body.innerHTML = svg.join('\n');
  document.body.style.margin = '0';
  document.title = `${W}x${H}`;
}
