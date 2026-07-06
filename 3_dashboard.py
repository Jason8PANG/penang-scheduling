#!/usr/bin/env python3
"""
Step 3: Create Dashboard HTML from Sum webpage data
- Reads the embedded SUM_DATA from the Sum HTML
- Generates Chart.js dashboard following 0630 template
"""
import datetime, os, re, json, base64, openpyxl

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SUM_DIR = SCRIPTS_DIR
today = datetime.datetime.now()
CUR_YEAR, CUR_MTH = today.year, today.month
M1, M2, M3 = CUR_MTH, CUR_MTH+1, CUR_MTH+2
WK_C = {1:5,2:4,3:5,4:5,5:5,6:5,7:5,8:6,9:5,10:5,11:5,12:5}
WK1, WK2, WK3 = WK_C.get(M1,5), WK_C.get(M2,6), WK_C.get(M3,5)
MON = {7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}
MN1, MN2, MN3 = MON[M1], MON[M2], MON[M3]
# PROJECTS read from SUM_DATA dynamically
TOTAL_WKS = WK1 + WK2 + WK3

print(f'=== Step 3: Dashboard === {MN1}({WK1}w)/{MN2}({WK2}w)/{MN3}({WK3}w)')

sfiles = [f for f in os.listdir(SCRIPTS_DIR) if f.startswith('Penang_Scheduling_WK') and f.endswith('_sum.html')]
if not sfiles: print('ERROR: No sum HTML'); exit(1)
latest = max(sfiles, key=lambda f: os.path.getmtime(os.path.join(SCRIPTS_DIR, f)))
WK_ID = re.search(r'WK(\d{4,8})_sum', latest).group(1)
print(f'  Using: {latest}')

# Read Sum HTML to extract SUM_DATA
with open(os.path.join(SCRIPTS_DIR, latest), 'r', encoding='utf-8') as f:
    sum_html = f.read()

m = re.search(r'var SUM_DATA=({.*?});', sum_html, re.DOTALL)
if not m: print('ERROR: SUM_DATA not found'); exit(1)
SD = json.loads(m.group(1))
PROJECTS = SD['pj']
N = len(PROJECTS)

# Build dashboard data arrays
# Chart 1: CR + FK Status (stacked bar per project per month)
# Chart 2: CR vs NAI per week
# Chart 3: OTDR % per week (drill-down)
# Chart 4: Project comparison

# MFS weekly Act/Fest split
# MFS data has: WK[0..WK1-1] | Tot | WK[WK1..WK1+WK2-1] | Tot | WK[WK1+WK2..] | Tot
mfs_w = SD['mfs_tot']  # MFS total row
mta = [0]*19; mtf = [0]*19
act_m1 = SD['act_m1']; act_m2 = SD['act_m2']; act_m3 = SD['act_m3']
fest_m1 = SD['fest_m1']; fest_m2 = SD['fest_m2']; fest_m3 = SD['fest_m3']
mta[5] = act_m1; mta[12] = act_m2; mta[18] = act_m3
mtf[5] = fest_m1; mtf[12] = fest_m2; mtf[18] = fest_m3

# Weekly split by ratio
# mfs_w indices: 0-4=W1, 5=T1, 6-11=W2, 12=T2, 13-17=W3, 18=T3
# But actual layout: WK1*WKs then Tot, WK2*WKs then Tot, WK3*WKs then Tot
# From sum table: MFS has no PD/Shipped, so first WK starts at index 0
mfs_flat = mfs_w  # Already a flat list
for mi_idx, (m, wkc) in enumerate([(M1,WK1),(M2,WK2),(M3,WK3)]):
    tot_idx = [5, 12, 18][mi_idx]
    w_start = [0, WK1+1, WK1+1+WK2+1][mi_idx]
    mth_total = mfs_flat[tot_idx] if tot_idx < len(mfs_flat) else 0
    if mth_total == 0: continue
    ar = mta[tot_idx] / mth_total
    fr = mtf[tot_idx] / mth_total
    for wi in range(wkc):
        wi_actual = w_start + wi
        if wi_actual < len(mfs_flat):
            wv = mfs_flat[wi_actual]
            if wv > 0:
                mta[w_start + wi] = round(wv * ar)
                mtf[w_start + wi] = round(wv * fr)

# Build project-based data for dashboard
# CR by project: [[project_data_per_col] for each project]
# CR total per project per month
cr_proj = []
for p in PROJECTS:
    idx = PROJECTS.index(p)
    row = SD['cr'][idx]
    cr_proj.append(row)

# NAI by project
nai_proj = []
for p in PROJECTS:
    idx = PROJECTS.index(p)
    nai_proj.append(SD['nai'][idx])

# OTDR by project (for drill-down: WK data only)
otdr_do = [[0]*TOTAL_WKS for _ in range(N)]
otdr_dc = [[0]*TOTAL_WKS for _ in range(N)]
for i, p in enumerate(PROJECTS):
    cr_row = SD['cr'][i]
    otdr_row = SD['otdr'][i]
    # CR: PD | W1xWK1 | Tot | W2xWK2 | Tot | W3xWK3 | Tot
    # OTDR: PD | W1xWK1 | Adv | Tot | PD | W2xWK2 | Adv | Tot | PD | W3xWK3 | Adv | Tot
    for w in range(WK1):
        otdr_do[i][w] = otdr_row[1+w] if len(otdr_row) > 1+w else 0  # WK cols after PD
        otdr_dc[i][w] = cr_row[1+w] if len(cr_row) > 1+w else 0  # CR WK cols
    for w in range(WK2):
        # OTDR: PD(1) + WK1 + Adv(1) + Tot(1) = 1+WK1+1+1 offset, then +w
        off = 1 + WK1 + 2  # PD + WKs + Adv + Tot
        if off + w < len(otdr_row):
            otdr_do[i][WK1 + w] = otdr_row[off + w]
            otdr_dc[i][WK1 + w] = cr_row[WK1 + 1 + w] if len(cr_row) > WK1 + 1 + w else 0
    for w in range(WK3):
        off = 1 + WK1 + 2 + 1 + WK2 + 2  # M1 block + M2 block
        if off + w < len(otdr_row):
            otdr_do[i][WK1 + WK2 + w] = otdr_row[off + w]
            otdr_dc[i][WK1 + WK2 + w] = cr_row[WK1 + 1 + WK2 + 1 + w] if len(cr_row) > WK1 + 1 + WK2 + 1 + w else 0

# Template
# Template: try own directory first, then other locations
if os.path.exists(os.path.join(SCRIPTS_DIR, 'Penang_Chart_Dashboard_WK0630.html')):
    TEMP = os.path.join(SCRIPTS_DIR, 'Penang_Chart_Dashboard_WK0630.html')
elif 'USERPROFILE' in os.environ:
    TEMP = os.path.join(os.environ['USERPROFILE'], 'AppData', 'Local', 'Temp', 'Penang_Chart_Dashboard_WK0630.html')
else:
    TEMP = os.path.join(SUM_DIR, 'Penang_Chart_Dashboard_WK0630.html')
if not os.path.exists(TEMP):
    print('ERROR: Template not found!')
    exit(1)

with open(TEMP, 'r', encoding='utf-8') as f:
    html = f.read()

# Inject Sum Table button before the WK div
html = html.replace('<div class="hb">WK0630</div>',
                    '<a href="/sum" class="btn" style="margin-right:12px;padding:5px 12px;background:#1a237e;color:#fff;text-decoration:none;border-radius:4px;font-size:12px">📊 Sum Table</a><div class="hb">WK0630</div>')

# ──────────────────────────────────────────────
# DATA MAPPING: 20-slot arrays (0-19) → 5/6/5 layout
# ct[1-5]=M1WKs, ct[6]=M1Tot, ct[7-12]=M2WKs, ct[13]=M2Tot, ct[14-18]=M3WKs, ct[19]=M3Tot
# ──────────────────────────────────────────────

# CR totals
cr_t = SD['cr_tot']  # 20-element: [PD, W1*5, T1, W2*6, T2, W3*5, T3]
ct = [0]*20
for w in range(WK1): ct[1+w] = round(cr_t[1+w])      # M1 WK1-5
ct[6] = round(cr_t[6])                                 # M1 Total
for w in range(WK2): ct[7+w] = round(cr_t[7+w])      # M2 WK1-6
ct[13] = round(cr_t[13])                               # M2 Total
for w in range(WK3): ct[14+w] = round(cr_t[14+w])    # M3 WK1-5
ct[19] = round(cr_t[19])                               # M3 Total

m1_cr, m2_cr, m3_cr = ct[6], ct[13], ct[19]

# MFS totals
mt = [0]*20
mfs_t = SD['mfs_tot']
for w in range(WK1): mt[1+w] = round(mfs_t[w]) if w < len(mfs_t) else 0
mt[6] = round(mfs_t[WK1]) if WK1 < len(mfs_t) else 0
for w in range(WK2): mt[7+w] = round(mfs_t[WK1+1+w]) if WK1+1+w < len(mfs_t) else 0
mt[13] = round(mfs_t[WK1+1+WK2]) if WK1+1+WK2 < len(mfs_t) else 0
for w in range(WK3): mt[14+w] = round(mfs_t[WK1+1+WK2+1+w]) if WK1+1+WK2+1+w < len(mfs_t) else 0
mt[19] = round(mfs_t[WK1+1+WK2+1+WK3]) if WK1+1+WK2+1+WK3 < len(mfs_t) else 0

# MFS Act/Fest (19-element)
mta_t = SD.get('mta', [0]*19)
mtf_t = SD.get('mtf', [0]*19)
mta_t = (mta_t + [0]*19)[:19]
mtf_t = (mtf_t + [0]*19)[:19]

# OTDR WK totals (per week, 20-slot)
ot_t = SD['otdr_tot']  # 25-element
ot_wk = [0]*20
for w in range(WK1): ot_wk[1+w] = round(ot_t[1+w])                         # M1 WK1-5
for w in range(WK2): ot_wk[7+w] = round(ot_t[1+WK1+2+1+w])                # M2 WK1-6
for w in range(WK3): ot_wk[14+w] = round(ot_t[1+WK1+2+1+WK2+2+1+w])       # M3 WK1-5

# NAI totals
nt = [0]*20
nai_t = SD['nai_tot']  # 20-element
for w in range(WK1): nt[1+w] = round(nai_t[1+w]) if 1+w < len(nai_t) else 0
nt[6] = round(nai_t[WK1+1]) if WK1+1 < len(nai_t) else 0
for w in range(WK2): nt[7+w] = round(nai_t[WK1+1+1+w]) if WK1+1+1+w < len(nai_t) else 0
nt[13] = round(nai_t[WK1+1+WK2+1]) if WK1+1+WK2+1 < len(nai_t) else 0
for w in range(WK3): nt[14+w] = round(nai_t[WK1+1+WK2+1+1+w]) if WK1+1+WK2+1+1+w < len(nai_t) else 0
nt[19] = round(nai_t[WK1+1+WK2+1+1+WK3]) if WK1+1+WK2+1+1+WK3 < len(nai_t) else 0

# OTDR Status % (16 elements for 5+6+5 weeks)
os_arr = []
os_raw = SD.get('os', [])  # 25-element matching OTDR table
for w in range(WK1):  # M1 WK1-5
    idx = 1 + w  # skip PD at 0
    if idx < len(os_raw) and os_raw[idx] != '' and os_raw[idx] is not None:
        os_arr.append(str(round(float(os_raw[idx]))))
    else: os_arr.append('')
for w in range(WK2):  # M2 WK1-6
    idx = 1 + WK1 + 2 + 1 + w  # skip M1 block (PD+WKs+Adv+Tot=1+WK1+2) + M2 PD
    if idx < len(os_raw) and os_raw[idx] != '' and os_raw[idx] is not None:
        os_arr.append(str(round(float(os_raw[idx]))))
    else: os_arr.append('')
for w in range(WK3):  # M3 WK1-5
    idx = 1 + WK1 + 2 + 1 + WK2 + 2 + 1 + w  # skip M1+M2 blocks + M3 PD
    if idx < len(os_raw) and os_raw[idx] != '' and os_raw[idx] is not None:
        os_arr.append(str(round(float(os_raw[idx]))))
    else: os_arr.append('')

# Build do/dc arrays (16 week slots = 5+6+5)
do_arr = SD.get('do', [[0]*16 for _ in range(N)])
dc_arr = SD.get('dc', [[0]*16 for _ in range(N)])

# Build data JSON for dashboard
DAT = json.dumps({
    'pj': PROJECTS,
    'cr': SD['cr'],
    'nai': SD['nai'],
    'otdr': SD['otdr'],
    'ct': ct,
    'nt': nt,
    'ot': ot_wk,
    'mfs': SD['mfs'],
    'mt': mt,
    'mta': mta_t,
    'mtf': mtf_t,
    'wk': WK_ID,
    'do': do_arr,
    'dc': dc_arr,
    'os': os_arr
})

# Replace in template
html = re.sub(r'var D = \{.*?\};', 'var D = ' + DAT + ';', html, flags=re.DOTALL)
html = re.sub(r"MON=\['.*?'\]", f"MON=['{MN1}','{MN2}','{MN3}']", html)
mthPos = f"mthPos=[{{l:'{MN1[:3]}',s:0,e:{WK1-1}}},{{l:'{MN2[:3]}',s:{WK1},e:{WK1+WK2-1}}},{{l:'{MN3[:3]}',s:{WK1+WK2},e:{WK1+WK2+WK3-1}}}]"
html = re.sub(r'mthPos=\[.*?\]', mthPos, html)
# osi array - sequential indices since D.os is already a flat 16-element WK array
osi_arr = ','.join(str(i) for i in range(WK1 + WK2 + WK3))
html = re.sub(r'var osi=\[.*?\]', f'var osi=[{osi_arr}]', html)

# WK labels
w1_s = ','.join([f"'W{i+1}'" for i in range(WK1)])
w2_s = ','.join([f"'W{i+1}'" for i in range(WK2)])
html = re.sub(r"W5=\['W1','W2','W3','W4','W5'\]", f"W5=[{w1_s}]", html)
html = re.sub(r"W6=\['W1','W2','W3','W4','W5','W6'\]", f"W6=[{w2_s}]", html)
wkl = []
for i in range(WK1): wkl.append(f"'W{i+1}'")
for i in range(WK2): wkl.append(f"'W{i+1}'")
for i in range(WK3): wkl.append(f"'W{i+1}'")
html = re.sub(r"var wkl=\[.*?\];", f"var wkl=[{','.join(wkl)}];", html)

# Logo
lp = os.path.join(SUM_DIR, 'nai_logo.jpg')
if os.path.exists(lp):
    b64 = base64.b64encode(open(lp,'rb').read()).decode()
    html = html.replace('src="nai_logo.jpg"', 'src="data:image/jpeg;base64,' + b64 + '"')

html = html.replace('WK0629', 'WK'+WK_ID); html = html.replace('WK0630', 'WK'+WK_ID)
html = html.replace('function fn(v){if(!v||isNaN(v))return"";return v.toLocaleString();}',
                    'function fn(v){if(!v||isNaN(v))return"";return Math.round(v).toLocaleString();}')

# Drill-down
old_d = '''    var pd=[];
    for(var i=0;i<P.length;i++){
      var wa=D.otdr[i]?D.otdr[i][wc]||0:0;
      var ca=D.cr[i]?D.cr[i][cc]||0:0;
      var p=ca>0?Math.min(Math.round(wa/ca*100),100):(wa>0?100:0);
      if(wa+ca>0)pd.push({l:P[i],p:p});
    }'''
new_d = '''    var pd=[];
    for(var i=0;i<P.length;i++){
      var wa=D.do?D.do[i][oW]||0:0;
      var ca=D.dc?D.dc[i][oW]||0:0;
      var p=ca>0?Math.min(Math.round(wa/ca*100),100):(wa>0?100:0);
      if(wa+ca>0 && p>0)pd.push({l:P[i],p:p});
    }'''
html = html.replace(old_d, new_d)

# l3d
old_end = '''        scales:{x:{beginAtZero:true,max:100,ticks:{callback:function(v){return v+'%';}}},y:{grid:{display:false}}}}});
  }
}
document.getElementById('cOS').onclick'''
new_end = '''        scales:{x:{beginAtZero:true,max:100,ticks:{callback:function(v){return v+'%';}}},y:{grid:{display:false}}}},
      plugins:[{id:'l3d',afterDraw:function(ch){
        var ctx=ch.ctx;ctx.save();var m=ch.getDatasetMeta(0);
        if(m.data)for(var i=0;i<m.data.length;i++){var t=pd[i].p;if(t>0){ctx.textAlign='right';ctx.textBaseline='middle';ctx.font='bold 11px Segoe UI';ctx.fillStyle='#1a237e';ctx.fillText(t+'%',m.data[i].x-4,m.data[i].y);}}
        ctx.restore();}}]})
  }
}
document.getElementById('cOS').onclick'''
html = html.replace(old_end, new_end)

out = os.path.join(SCRIPTS_DIR, f'Penang_Chart_Dashboard_WK{WK_ID}.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(html)

# Verify
js = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)[-1]
print(f'  Braces: {js.count("{")} vs {js.count("}")}')
print(f'  l3d: {"l3d" in js}  D.do: {"D.do" in js}')
print(f'[OK] Output: {os.path.basename(out)}')
