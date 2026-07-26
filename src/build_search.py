"""Build a standalone, offline search page over the whole archive.

Produces a single self-contained HTML file — no server, no internet, no API
key. Every paragraph of every transcript and news file is embedded with its
citation, so searching is instant and the result you see carries its source.

Deliberately NOT committed to the archive (~20 MB, and it changes wholesale
every day — committing it daily would add gigabytes of git history a year).
Regenerate it instead: refresh-search.bat pulls the archive and rebuilds.

Usage:  python src/build_search.py [--archive PATH] [--out PATH]
"""

import argparse
import json
import re
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

# Kinds, in the order they appear as filters. (key, label, colour, short tag) —
# colours match the briefing email's lane palette so the two feel like one product.
KINDS = [
    ("transcript", "Podcast transcripts", "#1f3a5f", "podcast"),
    ("politico", "Politico newsletters", "#9b2c2c", "politico"),
    ("news", "BBC news", "#2f6b4f", "news"),
    ("inprint", "In print", "#4a5763", "in print"),
    ("constituency", "Constituency Watch", "#b1621a", "local"),
]

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _iso_date(raw: str, path: Path) -> str:
    """Archive files date themselves inconsistently: transcripts and BBC use
    ISO, Constituency Watch keeps the raw RSS string ("Tue, 30 Jun 2026 …").
    Normalise, falling back to the filename, which always starts ISO."""
    raw = (raw or "").strip()
    if ISO_RE.match(raw):
        return raw[:10]
    if raw:
        try:
            return parsedate_to_datetime(raw).date().isoformat()
        except (TypeError, ValueError):
            pass
    return path.name[:10] if ISO_RE.match(path.name) else ""

TS_RE = re.compile(r"^\*\*\[(\d+:\d+(?::\d+)?)\]\*\*\s*(.*)$", re.S)
BULLET_RE = re.compile(r"^-\s+\*\*(.+?):\*\*\s*(.*)$")


def _parse(path: Path) -> tuple[dict, list[tuple[str | None, str]]]:
    """One archive .md file -> (metadata, [(timestamp|None, paragraph)])."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    title = ""
    meta: dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        m = BULLET_RE.match(line.strip())
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()
            continue
        if line.strip() == "## Transcript":
            body_start = i + 1
            break
        if title and meta and line.strip() and not line.startswith(("-", "#")):
            body_start = i
            break
    else:
        body_start = len(lines)

    paras = []
    for chunk in "\n".join(lines[body_start:]).split("\n\n"):
        chunk = chunk.strip()
        if len(chunk) < 40:
            continue
        m = TS_RE.match(chunk)
        if m:
            paras.append((m.group(1), " ".join(m.group(2).split())))
        else:
            paras.append((None, " ".join(chunk.split())))
    return {"title": title, **meta}, paras


def _classify(rel: str) -> str:
    if rel.startswith("transcripts/"):
        return "transcript"
    if "/politico/" in rel:
        return "politico"
    if "/in-print/" in rel:
        return "inprint"
    if "/constituency-watch/" in rel:
        return "constituency"
    return "news"


def collect(archive: Path) -> tuple[list[dict], list[list]]:
    docs, paras = [], []
    files = sorted(archive.glob("transcripts/*/*.md")) + sorted(archive.glob("news/**/*.md"))
    for path in files:
        rel = path.relative_to(archive).as_posix()
        meta, body = _parse(path)
        if not body:
            continue
        kind = _classify(rel)
        source = meta.get("show") or meta.get("source") or "Unknown"
        source = re.sub(r"\s*\(.*?\)\s*$", "", source).strip()  # drop "(reported news)"
        docs.append(
            {
                "s": source,
                "t": meta.get("title", path.stem),
                "d": _iso_date(meta.get("published") or meta.get("date", ""), path),
                "k": kind,
                "u": meta.get("url", ""),
                "a": meta.get("host/author (from feed)") or meta.get("from", ""),
                "n": meta.get("watch note") or meta.get("briefing note", ""),
            }
        )
        di = len(docs) - 1
        for ts, txt in body:
            paras.append([di, ts or "", txt])
    return docs, paras


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archive search — podcast briefing</title>
<style>
:root{--ink:#1d2a35;--body:#2f3a44;--muted:#6b7783;--faint:#98a2ad;--rule:#e3e7ea;
--bg:#fff;--panel:#f7f9fa;--accent:#24425c;--mark:#ffe9a8}
@media (prefers-color-scheme:dark){:root{--ink:#e8edf2;--body:#c8d2db;--muted:#8b97a3;
--faint:#6b7783;--rule:#2a3540;--bg:#141a20;--panel:#1b232b;--accent:#7fa8cc;--mark:#5c4a1a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--body);
font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:20px 18px 60px}
h1{font:700 20px/1.3 Georgia,serif;color:var(--ink);margin:0 0 2px}
.sub{font-size:12.5px;color:var(--faint);margin-bottom:16px}
#q{width:100%;padding:13px 14px;font-size:17px;border:2px solid var(--rule);border-radius:6px;
background:var(--bg);color:var(--ink)}
#q:focus{outline:none;border-color:var(--accent)}
.hint{font-size:12px;color:var(--faint);margin:7px 0 14px}
.hint code{background:var(--panel);padding:1px 5px;border-radius:3px;font-size:11.5px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px;
padding-bottom:12px;border-bottom:1px solid var(--rule)}
.chip{font-size:12px;padding:5px 10px;border:1px solid var(--rule);border-radius:14px;
cursor:pointer;user-select:none;color:var(--muted);background:var(--bg)}
.chip.on{color:#fff;border-color:transparent}
select,input[type=date]{font-size:12px;padding:5px 7px;border:1px solid var(--rule);
border-radius:5px;background:var(--bg);color:var(--body)}
#count{font-size:13px;color:var(--muted);margin:14px 0 10px}
.hit{padding:13px 0;border-bottom:1px solid var(--rule)}
.txt{font:16px/1.62 Georgia,serif;color:var(--body);margin:0 0 7px}
mark{background:var(--mark);color:inherit;padding:0 2px;border-radius:2px}
.cite{font-size:12.5px;color:var(--muted)}
.cite b{color:var(--body);font-weight:600}
.cite a{color:var(--accent)}
.tag{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.8px;
text-transform:uppercase;color:#fff;padding:2px 6px;border-radius:3px;margin-right:7px;
vertical-align:1px}
.tools{margin-top:6px}
button.link{background:none;border:none;color:var(--accent);font-size:12px;cursor:pointer;
padding:0;margin-right:14px;font-family:inherit}
.ctx{background:var(--panel);border-left:3px solid var(--rule);padding:10px 13px;margin:9px 0 0;
font:15px/1.6 Georgia,serif;color:var(--muted);display:none}
.ctx.open{display:block}
.ctx p{margin:0 0 9px}.ctx p.self{color:var(--ink)}
#more{margin:18px 0;padding:10px 16px;font-size:14px;border:1px solid var(--rule);
border-radius:6px;background:var(--panel);color:var(--body);cursor:pointer;font-family:inherit}
.empty{color:var(--faint);padding:26px 0;font-size:15px}
#stale{display:none;background:#fdf3e3;color:#8a5a1b;border:1px solid #e8d4ac;
border-radius:6px;padding:11px 14px;margin:0 0 14px;font-size:13.5px;line-height:1.5}
@media (prefers-color-scheme:dark){#stale{background:#2e2412;color:#e0b878;border-color:#4a3a1c}}
#stale b{font-weight:700}
</style></head><body><div class="wrap">
<h1>Archive search</h1>
<div class="sub">__SUB__</div>
<div id="stale"></div>
<input id="q" placeholder="Search the archive…" autofocus autocomplete="off">
<div class="hint">Whole words, combined with AND. Use <code>,</code> for alternatives
(<code>zonal, REMA, locational</code>), <code>"quotes"</code> for an exact phrase,
<code>*</code> to match a stem (<code>wind*</code> finds windfarm).</div>
<div class="filters" id="kinds"></div>
<div class="filters">
<select id="src"><option value="">All sources</option></select>
<input type="date" id="from" title="From"><input type="date" id="to" title="To">
<span class="chip" id="reset">Reset</span></div>
<div id="count"></div><div id="out"></div>
<button id="more" style="display:none">Show more results</button>
</div>
<script>
const BUILT="__BUILT__";
// The page is a snapshot on disk, so a bookmark can silently show old data.
// Say so plainly once it's more than a day behind.
(function(){
  const days=Math.floor((Date.now()-Date.parse(BUILT+"T00:00:00"))/86400000);
  if(days<2)return;
  const el=document.getElementById('stale');
  el.innerHTML='<b>This page is '+days+' days old.</b> It was built on '+BUILT+
    ' and does not include anything since. To bring it up to date, double-click '+
    '<b>refresh-search.bat</b> in your podcast-briefing folder.';
  el.style.display='block';
})();
const DOCS=__DOCS__,P=__PARAS__,KINDS=__KINDS__;
const LOW=P.map(r=>r[2].toLowerCase());
const K=Object.fromEntries(KINDS.map(k=>[k[0],k]));
let shown=0,hits=[],active=new Set(KINDS.map(k=>k[0]));
const $=i=>document.getElementById(i);

const kw=$('kinds');
KINDS.forEach(([key,label,col])=>{const c=document.createElement('span');
c.className='chip on';c.style.background=col;c.textContent=label;c.dataset.k=key;
c.onclick=()=>{active.has(key)?active.delete(key):active.add(key);
c.classList.toggle('on');c.style.background=active.has(key)?col:'';run()};kw.appendChild(c)});

[...new Set(DOCS.map(d=>d.s))].sort().forEach(s=>{
const o=document.createElement('option');o.value=s;o.textContent=s;$('src').appendChild(o)});

function rx(term){
  // Whole-word matching, so "REMA" doesn't match "remember" and "AR7" doesn't
  // match "AR7x". A trailing * relaxes it to a stem match.
  const stem=term.endsWith('*');
  const core=(stem?term.slice(0,-1):term).replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');
  if(!core)return null;
  const lead=/^[a-z0-9]/i.test(core)?'\\\\b':'';
  const tail=stem?'':(/[a-z0-9]$/i.test(core)?'\\\\b':'');
  return new RegExp(lead+core+tail,'i');
}
function parseQuery(q){
  const groups=[];
  for(const part of q.split(',')){
    const t=part.trim();if(!t)continue;
    const terms=[];const re=/"([^"]+)"|(\\S+)/g;let m;
    while((m=re.exec(t))){
      const raw=(m[1]||m[2]).toLowerCase();
      const r=rx(raw);
      if(r)terms.push({raw:raw.replace(/\\*$/,''),re:r});
    }
    if(terms.length)groups.push(terms);
  }
  return groups;
}
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function highlight(text,terms){
  let out=esc(text);
  const seen=new Set();
  for(const t of [...terms].sort((a,b)=>b.raw.length-a.raw.length)){
    if(seen.has(t.raw))continue;seen.add(t.raw);
    out=out.replace(new RegExp(t.re.source,'gi'),'<mark>$&</mark>');
  }
  return out;
}
function run(){
  const q=$('q').value.trim();const groups=parseQuery(q);
  const src=$('src').value,from=$('from').value,to=$('to').value;
  hits=[];shown=0;
  if(!groups.length&&!src&&!from&&!to){
    $('count').textContent='';$('out').innerHTML='<div class="empty">Type a word to search '+
    P.length.toLocaleString()+' paragraphs.</div>';$('more').style.display='none';return}
  for(let i=0;i<P.length;i++){
    const d=DOCS[P[i][0]];
    if(!active.has(d.k))continue;
    if(src&&d.s!==src)continue;
    if(from&&d.d<from)continue;
    if(to&&d.d>to)continue;
    if(groups.length){
      const t=LOW[i];
      let ok=false;
      // Cheap substring pre-filter first, then confirm on word boundaries —
      // keeps 23k paragraphs searchable as you type.
      for(const g of groups){
        if(g.every(term=>t.includes(term.raw)&&term.re.test(t))){ok=true;break}
      }
      if(!ok)continue;
    }
    hits.push(i);
  }
  const terms=groups.flat();
  $('count').textContent=hits.length.toLocaleString()+' matching paragraph'+
    (hits.length===1?'':'s')+(hits.length>400?' — showing the first 200 at a time':'');
  $('out').innerHTML='';render(terms);
}
function render(terms){
  const frag=document.createDocumentFragment();
  const end=Math.min(shown+200,hits.length);
  for(let n=shown;n<end;n++){
    const i=hits[n],[di,ts,txt]=P[i],d=DOCS[di],k=K[d.k];
    const el=document.createElement('div');el.className='hit';
    const cite=[d.a?'<b>'+esc(d.s)+'</b>':'<b>'+esc(d.s)+'</b>',
      d.t?'“'+esc(d.t)+'”':'',d.d,ts?'~'+ts:''].filter(Boolean).join(' · ');
    el.innerHTML='<p class="txt">'+highlight(txt,terms)+'</p><div class="cite">'+
      '<span class="tag" style="background:'+k[2]+'">'+k[3]+'</span>'+cite+
      (d.u?' · <a href="'+esc(d.u)+'" target="_blank" rel="noopener">link</a>':'')+
      '</div><div class="tools"><button class="link" data-i="'+i+'">Show context</button>'+
      '<button class="link" data-c="'+i+'">Copy citation</button></div>'+
      '<div class="ctx" id="c'+i+'"></div>';
    frag.appendChild(el);
  }
  $('out').appendChild(frag);shown=end;
  $('more').style.display=shown<hits.length?'block':'none';
}
$('out').onclick=e=>{
  const i=e.target.dataset.i,c=e.target.dataset.c;
  if(i!==undefined){
    const box=$('c'+i);
    if(!box.innerHTML){
      const di=P[i][0];let s=+i,t=+i;
      while(s>0&&P[s-1][0]===di&&+i-s<2)s--;
      while(t<P.length-1&&P[t+1][0]===di&&t-+i<2)t++;
      let h='';for(let n=s;n<=t;n++)h+='<p'+(n==i?' class="self"':'')+'>'+
        (P[n][1]?'<b>['+P[n][1]+']</b> ':'')+esc(P[n][2])+'</p>';
      box.innerHTML=h;
    }
    box.classList.toggle('open');
    e.target.textContent=box.classList.contains('open')?'Hide context':'Show context';
  }
  if(c!==undefined){
    const [di,ts,txt]=P[c],d=DOCS[di];
    const cite='“'+txt+'” — '+d.s+(d.t?' · “'+d.t+'”':'')+' · '+d.d+(ts?' · ~'+ts:'')+
      (d.u?' · '+d.u:'');
    navigator.clipboard.writeText(cite).then(()=>{e.target.textContent='Copied';
      setTimeout(()=>e.target.textContent='Copy citation',1400)});
  }
};
$('more').onclick=()=>render(parseQuery($('q').value.trim()).flat());
$('reset').onclick=()=>{$('q').value='';$('src').value='';$('from').value='';$('to').value='';
  active=new Set(KINDS.map(k=>k[0]));
  [...kw.children].forEach(c=>{c.classList.add('on');c.style.background=K[c.dataset.k][2]});run()};
let timer;$('q').oninput=()=>{clearTimeout(timer);timer=setTimeout(run,140)};
['src','from','to'].forEach(id=>$(id).onchange=run);
run();
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default=r"C:\Users\Dom's PC\code\podcast-archive")
    ap.add_argument("--out", default=None, help="defaults to <archive>/search.html")
    args = ap.parse_args()

    archive = Path(args.archive)
    out = Path(args.out) if args.out else archive / "search.html"

    docs, paras = collect(archive)
    counts: dict[str, int] = {}
    for d in docs:
        counts[d["k"]] = counts.get(d["k"], 0) + 1
    dates = sorted(d["d"] for d in docs if d["d"])
    sub = (
        f"{len(paras):,} paragraphs from {len(docs):,} documents · "
        f"{dates[0]} to {dates[-1]} · built {date.today().isoformat()} · "
        "everything is local; nothing leaves this machine"
    )

    html = (
        PAGE.replace("__DOCS__", json.dumps(docs, ensure_ascii=False, separators=(",", ":")))
        .replace("__PARAS__", json.dumps(paras, ensure_ascii=False, separators=(",", ":")))
        .replace("__KINDS__", json.dumps(KINDS))
        .replace("__BUILT__", date.today().isoformat())
        .replace("__SUB__", sub)
    )
    out.write_text(html, encoding="utf-8")
    mb = out.stat().st_size / 1_048_576
    print(f"[search] {len(docs):,} docs, {len(paras):,} paragraphs -> {out} ({mb:.1f} MB)")
    for key, label, *_ in KINDS:
        print(f"[search]   {label}: {counts.get(key, 0):,} documents")


if __name__ == "__main__":
    main()
