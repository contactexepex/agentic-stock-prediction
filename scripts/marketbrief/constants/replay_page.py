"""Stylesheet and script of the self-contained replay pages (rule replay and AI replay)."""

from __future__ import annotations


CSS = """
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--axis:#c3c2b7;--s1:#2a78d6;--s2:#eb6834;--ring:rgba(11,11,11,.10);--good:#006300;--bad:#d03b3b;--chip:#f0efec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;
--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--s1:#3987e5;--s2:#d95926;--ring:rgba(255,255,255,.10);
--good:#0ca30c;--bad:#e66767;--chip:#383835}}
:root[data-theme="dark"]{--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;
--axis:#383835;--s1:#3987e5;--s2:#d95926;--ring:rgba(255,255,255,.10);--good:#0ca30c;--bad:#e66767;--chip:#383835}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 8px}p,li{color:var(--ink2)}.sub{color:var(--muted);margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin:12px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile .v{font-size:30px;font-weight:600;color:var(--ink)}.tile .l{font-size:13px;color:var(--muted)}
.tile .n{font-size:13px;color:var(--ink2)}.summary li{margin:6px 0;color:var(--ink)}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid)}th{color:var(--muted);font-weight:600}
td:first-child,th:first-child{text-align:left}.scroll{overflow-x:auto}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin:4px 0 8px}
.sw{display:inline-block;width:10px;height:10px;border-radius:5px;margin-right:6px;vertical-align:middle}
.sw.line{height:2px;width:16px;border-radius:1px}.dash{border-top:2px dashed \
var(--muted);width:16px;display:inline-block;
margin-right:6px;vertical-align:middle}
svg{display:block;width:100%;height:auto}svg text{fill:var(--muted);font-size:11px}
.mark:hover{opacity:.75}.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);
border:1px solid var(--ring);border-radius:8px;padding:6px 9px;font-size:12.5px;box-shadow:0 2px 8px rgba(0,0,0,.15);
display:none;z-index:10;max-width:260px}select{font:inherit;padding:4px 8px;border-radius:8px;border:1px solid \
var(--axis);
background:var(--surface);color:var(--ink)}.bad{color:var(--bad)}.good{color:var(--good)}
.note{font-size:13px;color:var(--muted)}.caption{font-size:13.5px;color:var(--ink2);margin:8px 0 0}.top \
.answer{color:var(--ink);font-size:16px;margin:8px 0}details{background:var(--surface);border:1px solid \
var(--ring);border-radius:12px;padding:10px 16px;margin:10px \
0}summary{cursor:pointer;font-weight:600;color:var(--ink)}details[open] \
summary{margin-bottom:8px}code{background:var(--chip);padding:1px 4px;border-radius:4px}
"""

JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 el.addEventListener('mousemove',e=>{tip.style.display='block';tip.textContent=el.dataset.tip;
  const x=Math.min(e.clientX+14,window.innerWidth-270);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'});
 el.addEventListener('mouseleave',()=>{tip.style.display='none'});});
const sel=document.getElementById('sector');
if(sel){sel.addEventListener('change',()=>{document.querySelectorAll('#tickers tbody tr').forEach(r=>{
 r.style.display=(sel.value==='all'||r.dataset.sector===sel.value)?'':'none'})})}
"""
