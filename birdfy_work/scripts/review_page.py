"""Build an HTML page for David to check sampled clips against our scores.

usage: review_page.py [IOA_DIR]   (default birdfy_work/ioa)

Reads IOA_DIR/ioa_sample.csv and scores/scores_*.csv, and writes
IOA_DIR/review.html. The page plays IOA_DIR/clips/<clip> next to our values,
pre-filled in editable fields. David confirms a clip or types the correct
values; work is kept in the browser (localStorage) and exported as
birdfy_review_<range>.csv to the Downloads folder.
"""
import csv, glob, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIELDS = ["species", "left_pecks", "right_pecks", "left_time_s", "right_time_s"]
KEEP = FIELDS + ["individual", "peck_times_s", "peck_range", "confidence", "guessed_time_s",
                 "time_censored", "time_note", "notes", "sex_if_known"]


def main(ioa_dir):
    ioa = Path(ioa_dir)
    sample = list(csv.DictReader(open(ioa / "ioa_sample.csv")))
    want = {r["clip"] for r in sample}
    scores = {}
    for f in sorted(glob.glob(str(HERE / "scores" / "scores_*.csv"))):
        for r in csv.DictReader(open(f)):
            if r["file"] in want and r["individual"] not in ("", "0"):
                scores.setdefault(r["file"], []).append({k: r.get(k, "") for k in KEEP})
    clips = [{"clip": s["clip"], "date": s["date"], "start": s["clip_start"], "dur": float(s["duration_s"]),
              "rows": sorted(scores.get(s["clip"], []), key=lambda r: int(r["individual"]))} for s in sample]
    missing = [c["clip"] for c in clips if not c["rows"]]
    if missing:
        raise SystemExit(f"no scores for {missing}")
    rng = f"{clips[0]['date']}_to_{clips[-1]['date']}"
    html = TEMPLATE.replace("__DATA__", json.dumps(clips)).replace("__RANGE__", rng).replace("__FIELDS__", json.dumps(FIELDS))
    (ioa / "review.html").write_text(html)
    print(f"{len(clips)} clips -> {ioa / 'review.html'}")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Birdfy clip review __RANGE__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2430;--muted:#667085;--line:#d9dee7;--accent:#2563eb;--ok:#15803d;--edit:#b45309;--warn:#fef3c7}
*{box-sizing:border-box}body{margin:0;font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;align-items:center;gap:16px;padding:10px 16px;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2}
header h1{font-size:16px;margin:0}header .sp{flex:1}
button{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--card);cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}button.ok{background:var(--ok);border-color:var(--ok);color:#fff}
main{display:grid;grid-template-columns:230px 1fr;height:calc(100vh - 53px)}
nav{overflow:auto;border-right:1px solid var(--line);background:var(--card)}
nav .day{padding:8px 12px 4px;font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase}
nav a{display:flex;justify-content:space-between;padding:5px 12px;color:var(--ink);text-decoration:none;cursor:pointer}
nav a.cur{background:#e8efff}nav a .st{font-size:12px;color:var(--muted)}nav a .st.done{color:var(--ok)}nav a .st.edited{color:var(--edit)}
section{overflow:auto;padding:16px;display:grid;grid-template-columns:minmax(0,1.6fr) minmax(340px,1fr);gap:16px;align-content:start}
.vid{position:relative;background:#000;border-radius:8px;overflow:hidden}.vid video{width:100%;display:block}
.vid .mid{position:absolute;top:0;bottom:0;left:50%;width:2px;background:rgba(0,220,255,.8);pointer-events:none}
.vid .lab{position:absolute;top:6px;padding:2px 6px;font-size:12px;color:#fff;background:rgba(0,0,0,.55);border-radius:4px}
.ctl{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:8px}.ctl .t{font-variant-numeric:tabular-nums;color:var(--muted);margin-left:auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px}
.card h2{font-size:15px;margin:0 0 8px}.meta{color:var(--muted);font-size:12px;margin-bottom:8px}
.ind{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.ind:first-of-type{border-top:0;margin-top:0;padding-top:0}
.ind h3{font-size:13px;margin:0 0 6px;display:flex;justify-content:space-between}
.grid{display:grid;grid-template-columns:110px 1fr 90px;gap:4px 8px;align-items:center}
.grid .ours{color:var(--muted);font-size:12px;text-align:right}
input,textarea{font:inherit;width:100%;padding:4px 6px;border:1px solid var(--line);border-radius:5px}
input.changed{background:var(--warn);border-color:var(--edit)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}.chip{font-size:12px;padding:1px 6px;border:1px solid var(--line);border-radius:10px;cursor:pointer;background:#f3f5f8}
details{margin-top:6px;color:var(--muted);font-size:12px}
.actions{display:flex;gap:8px;margin-top:12px;align-items:center}.actions .s{color:var(--muted);font-size:12px}
.help{font-size:12px;color:var(--muted);margin-top:8px}kbd{border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 4px;font-size:11px;background:#fff}
</style></head><body>
<header><h1>Birdfy clip review __RANGE__</h1><span id="prog"></span><span class="sp"></span>
<button onclick="exportCsv()" class="primary">Export CSV</button></header>
<main><nav id="nav"></nav><section id="pane"></section></main>
<script>
const CLIPS=__DATA__, FIELDS=__FIELDS__, KEY="birdfy_review___RANGE__";
const LABEL={species:"Species",left_pecks:"Left pecks",right_pecks:"Right pecks",left_time_s:"Left time (s)",right_time_s:"Right time (s)"};
let state=JSON.parse(localStorage.getItem(KEY)||"{}"), cur=0;
function save(){localStorage.setItem(KEY,JSON.stringify(state));renderNav();}
function st(c){return state[c.clip]||{status:"pending",rows:c.rows.map(r=>Object.fromEntries(FIELDS.map(f=>[f,r[f]]))),extra:[],comment:""};}
function edited(c){const s=st(c);return s.extra.length>0||s.rows.some((r,i)=>FIELDS.some(f=>String(r[f]).trim()!==String(c.rows[i][f]).trim()));}
function renderNav(){let h="",day="",done=0;CLIPS.forEach((c,i)=>{if(c.date!==day){day=c.date;h+=`<div class="day">${day}</div>`;}
 const s=st(c);if(s.status!=="pending")done++;const lab=s.status==="pending"?"to do":(s.status==="edited"?"corrected":"confirmed");
 h+=`<a class="${i===cur?"cur":""}" onclick="go(${i})"><span>${c.start}</span><span class="st ${s.status==="pending"?"":(s.status==="edited"?"edited":"done")}">${lab}</span></a>`;});
 document.getElementById("nav").innerHTML=h;document.getElementById("prog").textContent=`${done} of ${CLIPS.length} reviewed`;}
function go(i){cur=Math.max(0,Math.min(CLIPS.length-1,i));render();}
function fieldRow(ci,ri,f,ours,val,extra){const ch=String(val).trim()!==String(ours).trim();
 return `<label>${LABEL[f]}</label><input class="${ch&&!extra?"changed":""}" value="${String(val).replace(/"/g,"&quot;")}" oninput="setv(${ci},${ri},'${f}',this.value,${extra})"><span class="ours">${extra?"":"ours: "+(ours===""?"blank":ours)}</span>`;}
function render(){const c=CLIPS[cur],s=st(c);let h=`<div><div class="vid"><video id="v" src="clips/${c.clip}" controls preload="auto"></video><div class="mid"></div>
 <span class="lab" style="left:6px">image-left = FEEDER RIGHT</span><span class="lab" style="right:6px">image-right = FEEDER LEFT</span></div>
 <div class="ctl"><button onclick="step(-1)">&#9664; frame</button><button onclick="step(1)">frame &#9654;</button>
 <button onclick="rate(0.25)">0.25x</button><button onclick="rate(0.5)">0.5x</button><button onclick="rate(1)">1x</button><span class="t" id="t"></span></div>
 <div class="help"><kbd>space</kbd> play/pause &nbsp;<kbd>,</kbd>/<kbd>.</kbd> frame back/forward &nbsp;<kbd>[</kbd>/<kbd>]</kbd> previous/next clip &nbsp;<kbd>Enter</kbd> confirm or save and go to next. Click a peck time to jump there. The cyan line is the side boundary.</div></div>
 <div class="card"><h2>${c.clip}</h2><div class="meta">${c.date} ${c.start} &middot; ${c.dur.toFixed(1)} s</div>`;
 c.rows.forEach((r,ri)=>{const v=s.rows[ri];h+=`<div class="ind"><h3><span>Animal ${r.individual}</span><span class="ours">${r.confidence} confidence</span></h3><div class="grid">`;
  FIELDS.forEach(f=>h+=fieldRow(cur,ri,f,r[f],v[f],false));h+=`</div>`;
  const pts=(r.peck_times_s||"").split(";").filter(x=>x.trim());if(pts.length)h+=`<div class="chips">${pts.map(p=>`<span class="chip" onclick="seek(${parseFloat(p)})">${parseFloat(p).toFixed(2)} s</span>`).join("")}</div>`;
  h+=`<details><summary>our notes${r.peck_range?" (peck range "+r.peck_range+")":""}</summary><p>${r.notes||""}</p><p><b>Side time:</b> ${r.time_note||""} ${r.guessed_time_s?"("+r.guessed_time_s+" s guessed)":""}</p></details></div>`;});
 s.extra.forEach((v,ei)=>{h+=`<div class="ind"><h3><span>Animal you added</span><button onclick="delExtra(${ei})">remove</button></h3><div class="grid">`;FIELDS.forEach(f=>h+=fieldRow(cur,ei,f,"",v[f],true));h+=`</div></div>`;});
 h+=`<div class="actions"><button onclick="addExtra()">+ animal we missed</button></div>
 <label class="help" style="display:block;margin-top:10px">Comment<textarea rows="2" oninput="setc(this.value)">${s.comment||""}</textarea></label>
 <div class="actions"><button class="ok" onclick="finish()">${edited(c)?"Save corrections and next":"Confirm and next"}</button><span class="s">${s.status==="pending"?"not reviewed yet":"saved as "+(s.status==="edited"?"corrected":"confirmed")}</span></div></div>`;
 document.getElementById("pane").innerHTML=h;const v=document.getElementById("v");v.ontimeupdate=()=>{document.getElementById("t").textContent=v.currentTime.toFixed(2)+" s";};renderNav();}
function touch(){const c=CLIPS[cur];if(!state[c.clip])state[c.clip]=st(c);return state[c.clip];}
function setv(ci,ri,f,val,extra){const s=touch();(extra?s.extra:s.rows)[ri][f]=val;localStorage.setItem(KEY,JSON.stringify(state));
 const b=document.querySelector(".actions .ok");if(b)b.textContent=edited(CLIPS[cur])?"Save corrections and next":"Confirm and next";
 if(!extra){const inp=event.target;inp.classList.toggle("changed",String(val).trim()!==String(CLIPS[cur].rows[ri][f]).trim());}}
function setc(v){touch().comment=v;localStorage.setItem(KEY,JSON.stringify(state));}
function addExtra(){touch().extra.push(Object.fromEntries(FIELDS.map(f=>[f,""])));save();render();}
function delExtra(i){touch().extra.splice(i,1);save();render();}
function finish(){const s=touch();s.status=edited(CLIPS[cur])?"edited":"confirmed";save();go(cur+1);}
function step(n){const v=document.getElementById("v");v.pause();v.currentTime=Math.max(0,v.currentTime+n/15);}
function rate(r){document.getElementById("v").playbackRate=r;}
function seek(t){const v=document.getElementById("v");v.pause();v.currentTime=Math.max(0,t-0.4);}
document.addEventListener("keydown",e=>{if(["INPUT","TEXTAREA"].includes(e.target.tagName)){if(e.key==="Enter"&&e.target.tagName==="INPUT"){e.preventDefault();finish();}return;}
 const v=document.getElementById("v");if(e.key===" "){e.preventDefault();v.paused?v.play():v.pause();}else if(e.key===",")step(-1);else if(e.key===".")step(1);
 else if(e.key==="[")go(cur-1);else if(e.key==="]")go(cur+1);else if(e.key==="Enter")finish();});
function q(x){x=String(x??"");return /[",\n]/.test(x)?'"'+x.replace(/"/g,'""')+'"':x;}
function exportCsv(){const out=[["clip","date","individual","status","field","ours","david","comment"]];
 CLIPS.forEach(c=>{const s=st(c);c.rows.forEach((r,i)=>FIELDS.forEach(f=>out.push([c.clip,c.date,r.individual,s.status,f,r[f],s.rows[i][f],s.comment])));
  s.extra.forEach((v,i)=>FIELDS.forEach(f=>out.push([c.clip,c.date,"added"+(i+1),s.status,f,"",v[f],s.comment])));});
 const blob=new Blob([out.map(r=>r.map(q).join(",")).join("\n")],{type:"text/csv"});const a=document.createElement("a");
 a.href=URL.createObjectURL(blob);a.download="birdfy_review___RANGE__.csv";a.click();}
renderNav();render();
</script></body></html>
"""

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "ioa"))
