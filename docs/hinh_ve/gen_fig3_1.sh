#!/bin/bash
# Dựng Hình 3-1 từ kết quả thật của docker compose ps (ps.txt)
cd "$(dirname "$0")"
CMD='docker compose ps --format "table {{.Name}}\t{{.Image}}\t{{.Status}}"'
{
printf '%s' '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#fff}.t{display:inline-block;background:#0c0c0c;border-radius:8px;padding:0 0 14px;font:19px/1.45 Consolas,"Courier New",monospace;color:#cccccc}.bar{background:#2b2b2b;color:#ddd;font:15px Arial,sans-serif;padding:7px 14px;border-radius:8px 8px 0 0}pre{margin:10px 18px 0 18px;padding-right:18px;font:inherit;white-space:pre}.c{color:#f9f1a5}.h{color:#fff;font-weight:700}.u{color:#16c60c}</style></head><body><div class="t"><div class="bar">Windows PowerShell</div><pre>'
printf '%s' 'PS ...\OCR_pipeline&gt; <span class="c">'
printf '%s' "$CMD" | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g'
printf '%s\n' '</span>'
head -1 ps.txt | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g;s/^/<span class="h">/;s/$/<\/span>/'
tail -n +2 ps.txt | sed 's/&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g' | sed -E 's/(Up .*)$/<span class="u">\1<\/span>/'
printf '%s\n' '</pre></div></body></html>'
} > fig3_1.html
