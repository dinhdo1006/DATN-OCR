// Vẽ sơ đồ khối bằng SVG cho báo cáo. Hình được chèn rộng 439 pt, nên với W = 880 px thì
// cỡ chữ in ra = px × 0,5 pt: chữ 16 px ≈ 8 pt, 14 px ≈ 7 pt (mức nhỏ nhất).
const PAL = {
  gray: ['#f1f1f1', '#666'], blue: ['#dbe8f6', '#2f5d8a'], green: ['#e3f1df', '#4a8a3c'],
  orange: ['#fbe5d0', '#c0702a'], yellow: ['#fdf3d0', '#b8921e'], purple: ['#ece5f6', '#7a5aa8'],
  red: ['#fbe3e3', '#c0504d'], white: ['#ffffff', '#555']
};
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function Dg(W, H, font) {
  this.W = W; this.H = H; this.p = []; this.font = font || "Arial, 'Segoe UI', sans-serif";
}
// Khung chữ nhật có chữ nhiều dòng; dòng đầu đậm nếu o.title !== false và có nhiều dòng
Dg.prototype.box = function (x, y, w, h, lines, o = {}) {
  const [fill, stroke] = PAL[o.c || 'blue'];
  const rx = o.rx === undefined ? 8 : o.rx, fs = o.fs || 17, lh = o.lh || fs * 1.25;
  this.p.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${o.fill || fill}" stroke="${o.stroke || stroke}" stroke-width="${o.sw || 2}"${o.dash ? ' stroke-dasharray="7 5"' : ''}/>`);
  lines = [].concat(lines);
  const n = lines.length, cx = o.align === 'left' ? x + 12 : x + w / 2, anchor = o.align === 'left' ? 'start' : 'middle';
  const y0 = o.top ? y + o.top : y + h / 2 - (n - 1) * lh / 2 + fs * 0.35;
  lines.forEach((t, i) => {
    const bold = (i === 0 && n > 1 && o.title !== false) || o.bold;
    const sz = (i > 0 && o.sub) ? o.sub : fs;
    this.p.push(`<text x="${cx}" y="${y0 + i * lh}" text-anchor="${anchor}" font-size="${sz}"${bold ? ' font-weight="700"' : ''} fill="${o.color || '#111'}"${o.mono ? ' font-family="Consolas, monospace"' : ''}>${esc(t)}</text>`);
  });
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2, r: x + w, b: y + h };
};
Dg.prototype.ellipse = function (cx, cy, rx, ry, lines, o = {}) {
  const [fill, stroke] = PAL[o.c || 'yellow'], fs = o.fs || 16, lh = fs * 1.2;
  this.p.push(`<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`);
  lines = [].concat(lines);
  lines.forEach((t, i) => this.p.push(`<text x="${cx}" y="${cy - (lines.length - 1) * lh / 2 + fs * 0.35 + i * lh}" text-anchor="middle" font-size="${fs}"${o.bold ? ' font-weight="700"' : ''} fill="#111">${esc(t)}</text>`));
  return { cx, cy, rx, ry, x: cx - rx, r: cx + rx, y: cy - ry, b: cy + ry };
};
Dg.prototype.text = function (x, y, s, o = {}) {
  const lines = [].concat(s), fs = o.fs || 15, lh = o.lh || fs * 1.25;
  lines.forEach((t, i) => this.p.push(`<text x="${x}" y="${y + i * lh}" text-anchor="${o.a || 'start'}" font-size="${fs}"${o.bold ? ' font-weight="700"' : ''}${o.italic ? ' font-style="italic"' : ''} fill="${o.color || '#222'}"${o.mono ? ' font-family="Consolas, monospace"' : ''}${o.halo ? ' paint-order="stroke" stroke="#fff" stroke-width="5" stroke-linejoin="round"' : ''}>${esc(t)}</text>`));
};
// Đường nối qua các điểm, mũi tên ở cuối (o.end = 'fill' | 'open' | 'none'), o.start cho mũi tên hai đầu
Dg.prototype.line = function (pts, o = {}) {
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ',' + p[1]).join(' ');
  const end = o.end || 'fill';
  this.p.push(`<path d="${d}" fill="none" stroke="${o.color || '#333'}" stroke-width="${o.sw || 2}"${o.dash ? ' stroke-dasharray="7 5"' : ''}${end !== 'none' ? ` marker-end="url(#m_${end})"` : ''}${o.start ? ` marker-start="url(#s_${o.start})"` : ''}/>`);
  if (o.label) {
    const [lx, ly] = o.at || [(pts[0][0] + pts[pts.length - 1][0]) / 2, (pts[0][1] + pts[pts.length - 1][1]) / 2 - 8];
    this.text(lx, ly, o.label, { fs: o.lfs || 14, a: o.la || 'middle', halo: true, italic: o.litalic, color: o.lcolor });
  }
};
Dg.prototype.raw = function (s) { this.p.push(s); };
Dg.prototype.render = function () {
  const defs = `<defs>
  <marker id="m_fill" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker>
  <marker id="m_open" viewBox="0 0 12 12" refX="11" refY="6" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" orient="auto-start-reverse"><path d="M0,0 L11,6 L0,12" fill="none" stroke="#333" stroke-width="1.6"/></marker>
  <marker id="m_tri" viewBox="0 0 12 12" refX="11" refY="6" markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="16" orient="auto-start-reverse"><path d="M0,0 L11,6 L0,12 z" fill="#fff" stroke="#333" stroke-width="1.4"/></marker>
  <marker id="s_fill" viewBox="0 0 10 10" refX="1" refY="5" markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker>
  </defs>`;
  document.body.style.margin = '0';
  document.body.style.background = '#fff';
  document.body.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="${this.W}" height="${this.H}" viewBox="0 0 ${this.W} ${this.H}" font-family="${this.font}">${defs}${this.p.join('\n')}</svg>`;
};
// Ký pháp Gane–Sarson cho biểu đồ luồng dữ liệu: tiến trình là hình chữ nhật bo góc có dải số hiệu ở trên,
// tác nhân ngoài là hình chữ nhật có bóng đổ (kho dữ liệu là hộp hở cạnh phải có ô mã, vẽ trong từng hình)
Dg.prototype.gsProc = function (cx, cy, w, h, id, lines, o = {}) {
  const x = cx - w / 2, y = cy - h / 2, band = o.band || 26, fs = o.fs || 16, lh = fs * 1.2;
  this.p.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="#e3f1df" stroke="#4a8a3c" stroke-width="2"/>`);
  this.p.push(`<line x1="${x}" y1="${y + band}" x2="${x + w}" y2="${y + band}" stroke="#4a8a3c" stroke-width="1.6"/>`);
  this.text(cx, y + band - 7, id, { fs, a: 'middle', bold: true });
  lines = [].concat(lines);
  const y0 = y + band + (h - band) / 2 - (lines.length - 1) * lh / 2 + fs * 0.35;
  lines.forEach((t, i) => this.text(cx, y0 + i * lh, t, { fs, a: 'middle', bold: o.bold }));
  return { cx, cy, x, y, r: x + w, b: y + h, w, h };
};
Dg.prototype.gsEnt = function (x, y, w, h, lines, o = {}) {
  this.p.push(`<rect x="${x + 6}" y="${y + 6}" width="${w}" height="${h}" fill="#9a9a9a" stroke="none"/>`);
  return this.box(x, y, w, h, lines, { c: 'gray', rx: 0, ...o });
};
