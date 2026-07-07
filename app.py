"""
TI Diode Cross-Reference Tool — local Flask web app.

Run:  python app.py    (then open http://127.0.0.1:5050)

One input box handles all three:
  • a single competitor part            e.g.  PESD12VW1BCSF
  • a list of parts                      e.g.  SMBJ33A, DF2B7ASL, PESD5V0X1BSF
  • a pasted sales email / BOM table     (parts are auto-extracted)
"""
import os
import pandas as pd
from flask import Flask, request, render_template_string, jsonify

from crossref import lookup_competitor
from crossref.data_layer import build_manual_specs
from crossref.engine import find_alternatives, load_ti_pool
from crossref.emailparse import extract_parts
from crossref.compare import analyze

app = Flask(__name__)

RTYPE_CLASS = {"Drop-in replacement": "drop", "P2P": "p2p",
               "Functional": "func", "Functional (closest)": "func"}
# Only "better" is highlighted (green). Everything else stays neutral (no red).
VERDICT_CLASS = {"better": "v-better", "equal": "", "worse": "", "na": ""}


def build_table(a):
    cols = a["columns"]
    if not cols:
        return None
    labels = [r["label"] for r in cols[0]["diff"]]
    rows = []
    for i, label in enumerate(labels):
        comp = cols[0]["diff"][i]["comp"]
        cells = [{"ti": c["diff"][i]["ti"], "verdict": VERDICT_CLASS[c["diff"][i]["verdict"]]}
                 for c in cols]
        rows.append({"label": label, "comp": comp, "cells": cells})
    return rows


def process(text, mfr=""):
    resolved, unresolved, mfrs = extract_parts(text, global_mfr=mfr)
    items = []
    for r in resolved:
        a = analyze(r["specs"])
        for c in a["columns"]:
            c["rclass"] = RTYPE_CLASS.get(c["rtype"], "func")
        items.append({
            "input": r["input"], "mfr": r["mfr"], "specs": r["specs"],
            "best": a["best"], "columns": a["columns"], "table": build_table(a),
            "found": a["found"],
        })
    return {"items": items, "unresolved": unresolved, "mfrs": mfrs}


PAGE = r"""
<!doctype html><html><head><meta charset="utf-8">
<title>TI Cross-Reference</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{--red:#e00000;--ink:#1d1d1f;--mut:#6e6e73;--line:#e2e2e7;--bg:#fbfbfd;
   --card:#fff;--good-bg:#e3f6ea;--good:#1a7f43;}
 *{box-sizing:border-box} html,body{margin:0}
 body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif;
   background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;line-height:1.5}
 a{color:inherit}
 header{background:rgba(255,255,255,.82);backdrop-filter:saturate(180%) blur(16px);
   border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
 .hd{max-width:1120px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;gap:14px}
 .home{display:flex;align-items:center;gap:13px;text-decoration:none;color:inherit}
 .logo{background:var(--red);color:#fff;font-weight:800;font-size:15px;letter-spacing:.5px;padding:6px 9px;border-radius:7px}
 .hd h1{font-size:17px;margin:0;font-weight:600;letter-spacing:-.01em}
 .newsearch{margin-left:auto;font-size:13.5px;text-decoration:none;color:var(--red);font-weight:600;
   border:1px solid var(--line);padding:8px 14px;border-radius:9px;background:#fff}
 .newsearch:hover{background:#fafafa}
 .wrap{max-width:1120px;margin:0 auto;padding:30px 24px 80px}
 .hero{text-align:center;margin:14px 0 26px}
 .hero h2{font-size:30px;font-weight:650;letter-spacing:-.02em;margin:0 0 6px}
 .hero p{color:var(--mut);font-size:15px;margin:0}
 form.search{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px;
   box-shadow:0 6px 24px rgba(0,0,0,.05)}
 textarea{width:100%;border:0;outline:0;resize:vertical;font:inherit;font-size:16px;min-height:52px;padding:10px 12px;background:transparent}
 .rowline{display:flex;gap:10px;align-items:center;border-top:1px solid var(--line);padding-top:12px;margin-top:6px}
 .rowline input{flex:1;border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:inherit;font-size:14px}
 button{background:var(--red);color:#fff;border:0;padding:12px 24px;border-radius:11px;font:inherit;font-weight:600;font-size:15px;cursor:pointer;transition:.15s}
 button:hover{filter:brightness(.94)}
 .hint{color:var(--mut);font-size:12.5px;text-align:center;margin-top:12px}
 .ex{display:inline-block;background:#f0f0f3;border-radius:20px;padding:3px 11px;margin:3px;font-size:12.5px;color:#333;text-decoration:none}
 .detected{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:26px 0 6px;color:var(--mut);font-size:13px}
 .pill{background:#eef;border:1px solid #dde;border-radius:20px;padding:3px 11px;font-size:12px;color:#334}
 .pill.mut{background:#f2f2f5;border-color:#e5e5ea;color:#666}
 .summary{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;margin:10px 0 26px}
 .summary th{background:#0b0b0f;color:#fff;text-align:left;font-weight:600;font-size:12px;letter-spacing:.03em;text-transform:uppercase;padding:12px 16px}
 .summary td{padding:13px 16px;border-top:1px solid var(--line);font-size:14px}
 .summary tr:first-child td{border-top:0}
 .summary .opn{font-weight:650;color:var(--red)}
 .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 24px;margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.03)}
 .card .h{display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap}
 .card .comp-pn{font-size:19px;font-weight:650;letter-spacing:-.01em}
 .card .comp-meta{color:var(--mut);font-size:13px;margin-top:2px}
 .arrow{color:var(--mut);font-size:20px;margin:0 4px}
 .card .best{margin-left:auto;text-align:right}
 .card .best .lbl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
 .card .best .opn{font-size:20px;font-weight:700;color:var(--red);letter-spacing:-.01em}
 .badge{display:inline-block;font-size:11px;font-weight:700;padding:5px 10px;border-radius:20px;margin-top:5px}
 .badge.drop{background:var(--good-bg);color:var(--good)}
 .badge.p2p{background:#e6efff;color:#1257c9}
 .badge.func{background:#fdf0dd;color:#a5620a}
 .toolbar{display:flex;justify-content:flex-end;margin-top:16px}
 .copybtn{background:#fff;color:var(--ink);border:1px solid var(--line);font-size:12.5px;font-weight:600;
   padding:7px 13px;border-radius:9px;cursor:pointer}
 .copybtn:hover{background:#f6f6f8;filter:none}
 .tablewrap{border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-top:9px}
 table.diff{width:100%;border-collapse:collapse;font-size:13.5px}
 table.diff th,table.diff td{padding:10px 14px;text-align:left;border-bottom:1px solid #eeeef1;border-right:1px solid #f3f3f5}
 table.diff th:last-child,table.diff td:last-child{border-right:0}
 table.diff tr:last-child td{border-bottom:0}
 table.diff thead th{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.03em;font-weight:600;vertical-align:bottom;background:#fafafc}
 table.diff thead th.ti .op{color:var(--red);font-weight:700;text-transform:none;font-size:14px;letter-spacing:0}
 table.diff td.lab{color:var(--mut);width:210px}
 table.diff td.comp{font-weight:500}
 table.diff td.ti{font-weight:600}
 td.v-better{background:var(--good-bg);color:var(--good)}
 .tag{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px}
 .tag.drop{background:var(--good-bg);color:var(--good)} .tag.p2p{background:#e6efff;color:#1257c9} .tag.func{background:#fdf0dd;color:#a5620a}
 .unres{background:#fff;border:1px dashed #d9c2c2;border-radius:12px;padding:14px 18px;margin:14px 0 0;color:#8a5}
 .unres b{color:#a1442e}
 .muted{color:var(--mut);font-size:13px}
</style></head><body>
<header><div class="hd">
  <a class="home" href="/"><span class="logo">TI</span><h1>Diode Cross-Reference</h1></a>
  {% if results or manual %}<a class="newsearch" href="/">＋ New search</a>{% endif %}
</div></header>
<div class="wrap">

 {% if not results and not manual %}
 <div class="hero">
   <h2>Find the best TI cross</h2>
   <p>Enter a competitor part, a list, or paste a sales email — we’ll extract the parts and cross them.</p>
 </div>
 {% endif %}

 <form class="search" method="post" action="/">
   <textarea name="q" placeholder="e.g.  PESD12VW1BCSF     —or paste a list, or an entire email / BOM table…">{{q or ''}}</textarea>
   <div class="rowline">
     <input name="mfr" value="{{mfr or ''}}" placeholder="Manufacturer (optional — helps disambiguate)">
     <button type="submit">Cross-reference</button>
   </div>
 </form>
 {% if not results and not manual %}
 <div class="hint">Try:
   <a class="ex" href="/?q=PESD12VW1BCSF">PESD12VW1BCSF</a>
   <a class="ex" href="/?q=DF2B7ASL">DF2B7ASL</a>
   <a class="ex" href="/?q=SMBJ33A, PESD5V0X1BSF, SP1003-01ETG">a small list</a>
   · or paste an email into the box above.
 </div>
 {% endif %}

 {% if results %}
   <div class="detected">
     <span class="pill">{{results['items']|length}} part{{'' if results['items']|length==1 else 's'}} crossed</span>
     {% for m in results['mfrs'] %}<span class="pill mut">{{m}}</span>{% endfor %}
     {% if results['unresolved'] %}<span class="pill mut">{{results['unresolved']|length}} not matched</span>{% endif %}
   </div>

   {% if results['items']|length > 1 %}
   <table class="summary">
     <thead><tr><th>Competitor</th><th>Best TI cross</th><th>Replacement</th><th>Notes</th></tr></thead>
     <tbody>
     {% for it in results['items'] %}
       <tr>
         <td>{{it['input']}}<div class="muted">{{it['mfr']}}</div></td>
         <td class="opn">{{it['best']['opn'] if it['best'] else '—'}}</td>
         <td>{% if it['best'] %}<span class="tag {{it['columns'][0]['rclass']}}">{{it['best']['rtype']}}</span>{% else %}—{% endif %}</td>
         <td class="muted">{{it['specs']['Vrwm']}} · {{it['specs']['Package']}} · {{it['specs']['Direction']}}</td>
       </tr>
     {% endfor %}
     </tbody>
   </table>
   {% endif %}

   {% for it in results['items'] %}
   <div class="card">
     <div class="h">
       <div>
         <div class="comp-pn">{{it['input']}} <span class="arrow">→</span>
           <span style="color:var(--red)">{{it['best']['opn'] if it['best'] else '—'}}</span></div>
         <div class="comp-meta">{{it['specs']['Manufacturer'] or it['mfr']}} · matched {{it['specs']['Device Name']}} · {{it['specs']['Type']}}</div>
       </div>
       {% if it['best'] %}
       <div class="best">
         <div class="lbl">Best TI cross</div>
         <div class="opn">{{it['best']['opn']}}</div>
         <span class="badge {{it['columns'][0]['rclass']}}">{{it['best']['rtype']}}</span>
       </div>
       {% endif %}
     </div>

     {% if it['table'] %}
     <div class="toolbar"><button type="button" class="copybtn" onclick="copyTable('tbl{{loop.index}}',this)">⧉ Copy table</button></div>
     <div class="tablewrap">
     <table class="diff" id="tbl{{loop.index}}">
       <thead><tr>
         <th>Spec</th>
         <th>{{it['input']}}</th>
         {% for c in it['columns'] %}<th class="ti"><span class="op">{{c['opn']}}</span></th>{% endfor %}
       </tr></thead>
       <tbody>
       {% for row in it['table'] %}
         <tr>
           <td class="lab">{{row['label']}}</td>
           <td class="comp">{{row['comp']}}</td>
           {% for cell in row['cells'] %}<td class="ti {{cell['verdict']}}">{{cell['ti']}}</td>{% endfor %}
         </tr>
       {% endfor %}
       </tbody>
     </table>
     </div>
     {% else %}
       <div class="muted" style="margin-top:12px">No TI cross met the crossing criteria for this part.</div>
     {% endif %}
   </div>
   {% endfor %}

   {% if results['unresolved'] %}
   <div class="unres">
     <b>Not matched ({{results['unresolved']|length}}):</b>
     {% for u in results['unresolved'] %}{{u['input']}}{{ ", " if not loop.last }}{% endfor %}.
     <div class="muted" style="margin-top:4px">Not found in the competitor database (new/unstocked part, a zener/Schottky outside ESD-TVS scope, or not a part number). Add the manufacturer, or enter specs manually below.</div>
     <form class="search" method="get" action="/" style="margin-top:12px;box-shadow:none">
       <input type="hidden" name="m" value="1">
       <div class="rowline" style="border-top:0;padding-top:0;flex-wrap:wrap">
         <input name="part" placeholder="Part #" value="{{results['unresolved'][0]['input']}}" style="max-width:160px">
         <input name="vrwm" placeholder="Vrwm (V)" style="max-width:110px">
         <input name="pkg" placeholder="Package" style="max-width:150px">
         <input name="cap" placeholder="Cap (pF)" style="max-width:110px">
         <select name="dir" style="max-width:150px;padding:10px"><option>Unidirectional</option><option>Bidirectional</option></select>
         <button type="submit">Cross by specs</button>
       </div>
     </form>
   </div>
   {% endif %}
 {% endif %}

 {% if manual %}
   <div class="detected"><span class="pill">manual specs</span></div>
   <div class="card">
     <div class="h"><div><div class="comp-pn">{{manual['input']}} <span class="arrow">→</span>
       <span style="color:var(--red)">{{manual['best']['opn'] if manual['best'] else '—'}}</span></div>
       <div class="comp-meta">manual entry</div></div></div>
     {% if manual['table'] %}
     <div class="toolbar"><button type="button" class="copybtn" onclick="copyTable('tblm',this)">⧉ Copy table</button></div>
     <div class="tablewrap"><table class="diff" id="tblm"><thead><tr><th>Spec</th><th>{{manual['input']}}</th>
       {% for c in manual['columns'] %}<th class="ti"><span class="op">{{c['opn']}}</span></th>{% endfor %}
     </tr></thead><tbody>
       {% for row in manual['table'] %}<tr><td class="lab">{{row['label']}}</td><td class="comp">{{row['comp']}}</td>
         {% for cell in row['cells'] %}<td class="ti {{cell['verdict']}}">{{cell['ti']}}</td>{% endfor %}</tr>{% endfor %}
     </tbody></table></div>
     {% endif %}
   </div>
 {% endif %}
</div>
<script>
function copyTable(id, btn){
  var src=document.getElementById(id); if(!src) return;
  var t=src.cloneNode(true);
  t.style.borderCollapse='collapse'; t.style.border='1px solid #cfcfd6';
  t.style.fontFamily='Arial,Helvetica,sans-serif'; t.style.fontSize='13px';
  var cells=t.querySelectorAll('th,td');
  for(var i=0;i<cells.length;i++){var c=cells[i];
    c.style.border='1px solid #cfcfd6'; c.style.padding='6px 10px';
    c.style.textAlign='left'; c.style.verticalAlign='top';}
  var heads=t.querySelectorAll('thead th');
  for(var j=0;j<heads.length;j++){heads[j].style.background='#111';heads[j].style.color='#fff';}
  var greens=t.querySelectorAll('.v-better');
  for(var k=0;k<greens.length;k++){greens[k].style.background='#e3f6ea';greens[k].style.color='#1a7f43';}
  var box=document.createElement('div'); box.appendChild(t);
  var html=box.innerHTML, text=src.innerText;
  function done(){var o=btn.textContent; btn.textContent='✓ Copied'; setTimeout(function(){btn.textContent=o;},1500);}
  if(navigator.clipboard && window.ClipboardItem){
    navigator.clipboard.write([new ClipboardItem({
      'text/html':new Blob([html],{type:'text/html'}),
      'text/plain':new Blob([text],{type:'text/plain'})})]).then(done,function(){
        navigator.clipboard.writeText(text).then(done);});
  } else { navigator.clipboard.writeText(text).then(done); }
}
</script>
</body></html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    q = (request.values.get("q") or "").strip()
    mfr = (request.values.get("mfr") or "").strip()
    results = manual = None

    if request.args.get("m") == "1":
        specs = build_manual_specs(
            vrwm=request.args.get("vrwm", ""), package=request.args.get("pkg", ""),
            capacitance=request.args.get("cap", ""), direction=request.args.get("dir", "Unidirectional"),
            channels=request.args.get("ch", "1"), grade=request.args.get("grade", "Commercial"),
            vclamp=request.args.get("vclamp", ""), name=request.args.get("part", "(manual entry)"))
        a = analyze(specs)
        for c in a["columns"]:
            c["rclass"] = RTYPE_CLASS.get(c["rtype"], "func")
        manual = {"input": request.args.get("part", "(manual)"), "best": a["best"],
                  "columns": a["columns"], "table": build_table(a)}
    elif q:
        results = process(q, mfr)

    return render_template_string(PAGE, q=q, mfr=mfr, results=results, manual=manual)


@app.route("/api/cross")
def api_cross():
    r = process((request.args.get("part") or "").strip(), (request.args.get("mfr") or "").strip())
    out = []
    for it in r["items"]:
        out.append({"competitor": it["input"], "matched": it["specs"]["Device Name"],
                    "best_ti": it["best"]["opn"] if it["best"] else None,
                    "replacement": it["best"]["rtype"] if it["best"] else None,
                    "options": [{"opn": c["opn"], "type": c["rtype"], "tier": c["tier"]} for c in it["columns"]]})
    return jsonify({"crosses": out, "unresolved": [u["input"] for u in r["unresolved"]], "manufacturers": r["mfrs"]})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))  # 5000 is used by macOS AirPlay
    print("Loading data (first run indexes the 94k master, ~5s)…")
    load_ti_pool()
    print(f"\n  ►  Open your browser to:  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
