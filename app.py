#!/usr/bin/env python3
"""Flask — Penang Scheduling: Sum + Dashboard, direct DB query"""
import os, re, json, datetime, calendar, pymysql

from flask import Flask
import db_config

app = Flask(__name__)
MON = {1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',
       7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}

# ── DB helpers ──
def get_latest_ds():
    cur = get_conn(); cur.execute('SELECT DISTINCT Data_Source FROM covswo_data ORDER BY Data_Source DESC LIMIT 1')
    r = cur.fetchone(); cur.close()
    return r[0] if r else None

def get_conn():
    return pymysql.connect(**db_config.DB_CONFIG)

def fetch_rows(ds):
    cur = get_conn()
    cur.execute('SELECT * FROM covswo_data WHERE Data_Source=%s AND Source_Type=%s', (ds, 'Job'))
    r = cur.fetchall(); cur.close()
    return r

def sf(v):
    if v is None: return 0
    if isinstance(v,(int,float)): return float(v)
    try: return float(str(v).replace(',',''))
    except: return 0

def sf_int(v):
    if v is None: return 0
    if isinstance(v,(int,float)): return round(v)
    try: return round(float(str(v).replace(',','')))
    except: return 0

def si(v):
    if v is None: return None
    if isinstance(v,int): return v
    if isinstance(v,(float,str)):
        try: return int(float(v))
        except: return None
    return None

def fmtv(v):
    if v is None or v=='': return ''
    if isinstance(v,(int,float)):
        if v==0 and not isinstance(v,bool): return ''
        return f'{v:,.0f}' if abs(v)>=1000 else str(int(v))
    return str(v)

def normalize_pj(s):
    parts=s.strip().split()
    if len(parts)>=2:
        c=' '.join(parts[:-1])
        sfx=parts[-1].lower()
        if sfx=='copper': return c+' Copper'
        if sfx in ('semi-conductor','semiconductor'): return c+' Semi-conductor'
    return s.strip()

# ── Load WIP data (cached) ──
WIP_CACHE = None
def get_wip():
    global WIP_CACHE
    if WIP_CACHE is not None: return WIP_CACHE
    cfg=dict(db_config.DB_CONFIG); cfg['database']='wiptrack'
    stn={}; exc={}; exc_r={}; pr={}
    try:
        c=pymysql.connect(**cfg); cur=c.cursor()
        cur.execute("SELECT Station FROM site_station WHERE SiteRef='NAIGROUP_PROD_410' ORDER BY id")
        ss=[r[0] for r in cur.fetchall()]
        stn={ss[i]:ss[i+1] for i in range(len(ss)-1)}
        cur.execute("SELECT Job,Station,description,start_time,end_time FROM wip_exceptions WHERE SiteRef='NAIGROUP_PROD_410'")
        for j,s,d,st,et in cur.fetchall():
            if et is None: exc[j]=[s,d,st]
            else: exc_r[j]=[s,d,st,et]
        cur.execute("SELECT Job,Station,CompleteDate FROM production_records WHERE SiteRef='NAIGROUP_PROD_410' ORDER BY CompleteDate DESC")
        for j,s,cd in cur.fetchall():
            if j not in pr: pr[j]=[s,cd]
        cur.close(); c.close()
    except:
        pass
    WIP_CACHE=(ss, stn, exc, exc_r, pr)
    return WIP_CACHE

def wip_status(src):
    _,stn,exc,exc_r,pr=get_wip()
    job=f'{src}-0000'
    if job not in pr: return ('','','')
    cur_s,cd=pr[job]; cur_s=cur_s or ''; cd_s=str(cd)[:19] if cd else ''
    if cur_s=='包装 Package': return (cur_s,'',cd_s)
    if job in exc: s,d,st=exc[job]; return (s or '',d or '',str(st)[:19] if st else '')
    if job in exc_r: s,_,st,et=exc_r[job]; return (stn.get(s,''),'',str(et)[:19] if et else '')
    return (stn.get(cur_s,''),'',cd_s)

# ── Build Dashboard ──
def build_dash():
    ds=get_latest_ds()
    if not ds: return '<h1>No data available</h1>'
    m=re.search(r'WK(\d{4,8})',ds); WK_ID=m.group(1) if m else '0000'
    rows=fetch_rows(ds)

    # same logic as original
    M1=int(WK_ID[:2]); M2=M1+1; M3=M1+2
    if M2>12: M2-=12; M3-=12
    if M3>12: M3-=12
    y1=datetime.datetime.now().year; y2=y1+(1 if M3<=M1 else 0); y3=y2
    def mwks(y,m):
        c=calendar.Calendar(); return sum(1 for w in c.monthdayscalendar(y,m) if any(d>0 for d in w))
    WK1,WK2,WK3=mwks(y1,M1),mwks(y2,M2),mwks(y3,M3)
    MN1,MN2,MN3=MON[M1],MON[M2],MON[M3]
    w1=[f'W{i+1}' for i in range(WK1)]
    w2=[f'W{i+1}' for i in range(WK2)]
    w3=[f'W{i+1}' for i in range(WK3)]

    raw={}
    for row in rows:
        v=row[8]
        if v:
            s=str(v).strip()
            if 'copper' in s.lower() or 'semi' in s.lower():
                raw[normalize_pj(s)]=True
    PROJECTS=sorted(raw.keys()); N=len(PROJECTS)

    cr={p:{'pd':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai={p:{'sh':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mfs={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    otdr={p:{f'{M1}_pd':0,M1:[0]*WK1,f'{M1}_adv':0,f'{M2}_pd':0,M2:[0]*WK2,f'{M2}_adv':0,f'{M3}_pd':0,M3:[0]*WK3,f'{M3}_adv':0} for p in PROJECTS}
    otdd={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    real={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai_orders={p:{M1:{w:[] for w in range(WK1)},M2:{w:[] for w in range(WK2)},M3:{w:[] for w in range(WK3)},"sh":[]} for p in PROJECTS}
    otdr_orders={p:{f'{M1}_pd':[],f'{M2}_pd':[],f'{M3}_pd':[]} for p in PROJECTS}

    for row in rows:
        pj=normalize_pj(str(row[8] or '')); sa=sf(row[10])
        if pj not in PROJECTS: continue
        cw_l=str(row[16] or '').strip().lower() if len(row)>16 else ''
        cmi=si(row[15] if len(row)>15 else None); cwi=si(row[16] if len(row)>16 else None)
        if cw_l in ('backlog','pass due'): cr[pj]['pd']+=sa
        elif cmi==M1 and cwi and 1<=cwi<=WK1: cr[pj][M1][cwi-1]+=sa
        elif cmi==M2 and cwi and 1<=cwi<=WK2: cr[pj][M2][cwi-1]+=sa
        elif cmi==M3 and cwi and 1<=cwi<=WK3: cr[pj][M3][cwi-1]+=sa
        nw_l=str(row[21] or '').strip().lower() if len(row)>21 else ''
        nwi=si(row[21] if len(row)>21 else None); nmi=si(row[20] if len(row)>20 else None)
        src_no=str(row[11] or '') if len(row)>11 else ''
        stn,exc,st_time=wip_status(src_no)
        oi=(str(row[1] or ''), src_no, round(sa,2), str(row[6] or '')[:10], str(row[5] or '')[:10], stn, exc, st_time)
        if nw_l=='shipped': nai[pj]['sh']+=sa; nai_orders[pj]['sh'].append(oi)
        elif nmi==M1 and nwi and 1<=nwi<=WK1: nai[pj][M1][nwi-1]+=sa; nai_orders[pj][M1][nwi-1].append(oi)
        elif nmi==M2 and nwi and 1<=nwi<=WK2: nai[pj][M2][nwi-1]+=sa; nai_orders[pj][M2][nwi-1].append(oi)
        elif nmi==M3 and nwi and 1<=nwi<=WK3: nai[pj][M3][nwi-1]+=sa; nai_orders[pj][M3][nwi-1].append(oi)
        omi=si(row[22] if len(row)>22 else None); owi=si(row[23] if len(row)>23 else None)
        ow_l=str(row[23] or '').strip() if len(row)>23 else ''
        if omi==M1:
            if ow_l=='Pass Due': otdr[pj][f'{M1}_pd']+=sa; otdr_orders[pj][f'{M1}_pd'].append(oi)
            elif ow_l=='Advanced': otdr[pj][f'{M1}_adv']+=sa
            elif owi and 1<=owi<=WK1: otdr[pj][M1][owi-1]+=sa
        elif omi==M2:
            if ow_l=='Pass Due': otdr[pj][f'{M2}_pd']+=sa; otdr_orders[pj][f'{M2}_pd'].append(oi)
            elif ow_l=='Advanced': otdr[pj][f'{M2}_adv']+=sa
            elif owi and 1<=owi<=WK2: otdr[pj][M2][owi-1]+=sa
        elif omi==M3:
            if ow_l=='Pass Due': otdr[pj][f'{M3}_pd']+=sa; otdr_orders[pj][f'{M3}_pd'].append(oi)
            elif ow_l=='Advanced': otdr[pj][f'{M3}_adv']+=sa
            elif owi and 1<=owi<=WK3: otdr[pj][M3][owi-1]+=sa
        oami=si(row[24] if len(row)>24 else None); oawi=si(row[25] if len(row)>25 else None)
        if oami==M1 and oawi and 1<=oawi<=WK1: otdd[pj][M1][oawi-1]+=sa
        elif oami==M2 and oawi and 1<=oawi<=WK2: otdd[pj][M2][oawi-1]+=sa
        elif oami==M3 and oawi and 1<=oawi<=WK3: otdd[pj][M3][oawi-1]+=sa
        rmi=si(row[26] if len(row)>26 else None); rwi=si(row[27] if len(row)>27 else None)
        if rmi==M1 and rwi and 1<=rwi<=WK1: real[pj][M1][rwi-1]+=sa
        elif rmi==M2 and rwi and 1<=rwi<=WK2: real[pj][M2][rwi-1]+=sa
        elif rmi==M3 and rwi and 1<=rwi<=WK3: real[pj][M3][rwi-1]+=sa

    active=[]
    for p in PROJECTS:
        if sum(cr[p]['pd'] for _ in [1])+sum(cr[p][M1])+sum(cr[p][M2])+sum(cr[p][M3])+sum(nai[p]['sh'] for _ in [1])+sum(nai[p][M1])+sum(nai[p][M2])+sum(nai[p][M3])+sum(mfs[p][M1])+sum(mfs[p][M2])+sum(mfs[p][M3])>0:
            active.append(p)
    PROJECTS=active; N=len(PROJECTS)

    ca=[]
    for p in PROJECTS:
        d=cr[p]; ca.append([d['pd']]+d[M1]+[sf_int(d['pd']+sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    ct=[sf_int(sum(ca[i][j] for i in range(N))) for j in range(len(ca[0]))]
    na=[]
    for p in PROJECTS:
        d=nai[p]; na.append([d['sh']]+d[M1]+[sf_int(sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    nt=[sf_int(sum(na[i][j] for i in range(N))) for j in range(len(na[0]))]
    oa=[]
    for p in PROJECTS:
        d=otdr[p]
        oa.append([d[f'{M1}_pd']]+d[M1]+[d[f'{M1}_adv']]+[sf_int(sum(d[M1])+d[f'{M1}_adv'])]+[d[f'{M2}_pd']]+d[M2]+[d[f'{M2}_adv']]+[sf_int(sum(d[M2])+d[f'{M2}_adv'])]+[d[f'{M3}_pd']]+d[M3]+[d[f'{M3}_adv']]+[sf_int(sum(d[M3])+d[f'{M3}_adv'])])
    ot=[sf_int(sum(oa[i][j] for i in range(N))) for j in range(len(oa[0]))]

    # OTDR Real Summary data
    real_25=['']*25
    for w in range(WK1): v=sum(real[p][M1][w] for p in PROJECTS); real_25[w]=sf_int(v) if v else ''
    for w in range(WK2): v=sum(real[p][M2][w] for p in PROJECTS); real_25[5+w]=sf_int(v) if v else ''
    for w in range(WK3): v=sum(real[p][M3][w] for p in PROJECTS); real_25[11+w]=sf_int(v) if v else ''
    rs=['']*len(real_25)
    for w in range(WK1): ci=1+w; rs[w]=min(round(real_25[w]/ct[ci]*100),100) if ci<len(ct) and ct[ci] and real_25[w]!='' and real_25[w] else ''
    for w in range(WK2): ci=4+WK1+w; rs[5+w]=min(round(real_25[5+w]/ct[ci]*100),100) if ci<len(ct) and ct[ci] and real_25[5+w]!='' and real_25[5+w] else ''
    for w in range(WK3): ci=6+WK1+WK2+1+w; rs[11+w]=min(round(real_25[11+w]/ct[ci]*100),100) if ci<len(ct) and ct[ci] and real_25[11+w]!='' and real_25[11+w] else ''
    ott=[0]*len(oa[0])
    for j in range(len(oa[0])):
        v=0
        for p in PROJECTS:
            if j==0: v+=otdr[p][f'{M1}_pd']
            elif 1<=j<=WK1: v+=otdr[p][M1][j-1]
            elif j==WK1+1: v+=otdr[p][f'{M1}_adv']
            elif WK1+3<=j<=WK1+2+WK2: v+=otdr[p][M2][j-(WK1+3)]
            elif j==WK1+WK2+3: v+=otdr[p][f'{M2}_adv']
            elif WK1+WK2+5<=j<=WK1+WK2+4+WK3: v+=otdr[p][M3][j-(WK1+WK2+5)]
            elif j==WK1+WK2+WK3+5: v+=otdr[p][f'{M3}_adv']
        ott[j]=sf_int(v)

    # Build JSON data
    sd=json.dumps({
        'pj':PROJECTS,'WK1':WK1,'WK2':WK2,'WK3':WK3,'wk':WK_ID,
        'cr':[[sf_int(v) for v in r] for r in ca],
        'nai':[[sf_int(v) for v in r] for r in na],
        'nai_tot':[sf_int(v) for v in nt],
        'otdr':[[sf_int(v) for v in r] for r in oa],
        'otdr_tot':[sf_int(v) for v in ot],
        'otdr_stat':rs,'real_total':real_25,'real_stat':rs,
        'do':[],'dc':[],
        'act_m1':0,'act_m2':0,'act_m3':0,'fest_m1':0,'fest_m2':0,'fest_m3':0,
        'mta':[],'mtf':[],
        'ott':ott
    })

    TW=WK1+WK2+WK3
    wklbl=[f'W{i+1}' for i in range(TW)]
    dash_html= f'''<!DOCTYPE html>
<html lang=en><head><meta charset=UTF-8><title>Penang Dashboard WK{WK_ID}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
body{{font-family:Segoe UI,sans-serif;margin:20px;background:#f5f5f5}}
h1{{color:#1a237e;font-size:20px}}h2{{color:#1a237e;font-size:16px;margin:20px 0 10px;border-bottom:2px solid #1a237e;padding-bottom:5px}}
.chart-row{{display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px}}
.chart-box{{flex:1 1 400px;background:#fff;padding:15px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.chart-box canvas{{width:100%!important;max-height:320px}}
table{{border-collapse:collapse;margin-bottom:15px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
td,th{{border:1px solid #ccc;padding:3px 6px;text-align:center;font-size:11px}}
.pj{{text-align:left;font-weight:600;min-width:120px}}
.mh{{font-weight:700;background:#e8eaf6;color:#1a237e}}.d{{background:#fff}}
.ttl td{{background:#e8eaf6;font-weight:700;color:#1a237e}}
.btn{{background:#1a237e;color:#fff;padding:6px 16px;border:0;border-radius:4px;cursor:pointer;font-size:12px;text-decoration:none;display:inline-block;margin:2px}}
</style></head><body>
<h1>Penang Production Scheduling &mdash; WK{WK_ID} Dashboard</h1>
<div style="margin-bottom:15px"><a href="/sum" class=btn>📊 Sum Table</a> <a href="/rebuild" class=btn>🔄 Refresh</a></div>
<p style=color:#666>{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} | Data from MySQL: {ds}</p>
<div class=chart-row>
<div class=chart-box><canvas id=crChart></canvas></div>
<div class=chart-box><canvas id=naiChart></canvas></div>
</div>
<div class=chart-row>
<div class=chart-box><canvas id=otdrChart></canvas></div>
<div class=chart-box><canvas id=realChart></canvas></div>
</div>
<h2>Project Summary</h2>
<div id=projTable></div>
<script>
var D={sd};
var pj=D.pj,N=pj.length,WK1=D.WK1,WK2=D.WK2,WK3=D.WK3,TW=WK1+WK2+WK3;
var wklbl={json.dumps(wklbl)};
var crData=[];pj.forEach(function(p,pi){{var v=[];var o=1;for(var w=0;w<WK1;w++)v.push(D.cr[pi][o+w]);o=7;for(var w=0;w<WK2;w++)v.push(D.cr[pi][o+w]);o=14;for(var w=0;w<WK3;w++)v.push(D.cr[pi][o+w]);crData.push({{label:p,data:v,borderWidth:1,pointRadius:3}});}});
new Chart(document.getElementById('crChart'),{{type:'bar',data:{{labels:wklbl,datasets:crData}},options:{{plugins:{{legend:{{labels:{{font:{{size:9}}}}}},title:{{display:true,text:'Customer Request WK'+D.wk}}}},scales:{{x:{{stacked:true}},y:{{stacked:true,beginAtZero:true}}}}}}}});
var naiData=[];pj.forEach(function(p,pi){{var t=0,t2=0;for(var w=0;w<TW;w++)t2+=D.nai[pi][1+w];t+=D.nai[pi][0]+t2;if(t>0)naiData.push({{label:p,data:t}});}});
new Chart(document.getElementById('naiChart'),{{type:'doughnut',data:{{labels:naiData.map(function(d){{return d.label}}),datasets:[{{data:naiData.map(function(d){{return d.data}})}}]}},options:{{plugins:{{title:{{display:true,text:'NAI Production'}}}}}}}});
var otdrData=[];pj.forEach(function(p,pi){{var v=D.otdr[pi][0];if(v>0)otdrData.push({{label:p,data:v}});}});
new Chart(document.getElementById('otdrChart'),{{type:'pie',data:{{labels:otdrData.map(function(d){{return d.label}}),datasets:[{{data:otdrData.map(function(d){{return d.data}})}}]}},options:{{plugins:{{title:{{display:true,text:'OTDR Pass Due'}}}}}}}});
var rData=[];for(var w=0;w<TW;w++){{var v=D.real_total[w];if(v&&v!=='')rData.push({{label:wklbl[w],data:v}});}}
new Chart(document.getElementById('realChart'),{{type:'bar',data:{{labels:rData.map(function(d){{return d.label}}),datasets:[{{label:'Real Production',data:rData.map(function(d){{return d.data}}),backgroundColor:'#1565c0'}}]}},options:{{plugins:{{title:{{display:true,text:'Real Production by Week'}}}},scales:{{y:{{beginAtZero:true}}}}}}}});
var ht='<table><tr><th class=tt colspan=6>Project Summary</th></tr><tr><th class=mh>Project</th><th class=mh style=text-align:right>CR Total</th><th class=mh style=text-align:right>Pass Due</th><th class=mh style=text-align:right>NAI Shipped</th><th class=mh style=text-align:right>NAI Total</th><th class=mh style=text-align:right>OTDR PD</th></tr>';
pj.forEach(function(p,pi){{var crT=0;var crPd=D.cr[pi][0]||0;for(var j=1;j<D.cr[pi].length;j++)crT+=D.cr[pi][j]||0;var nSh=D.nai[pi][0]||0;var nTot=nSh;for(var j=1;j<D.nai[pi].length;j++)nTot+=D.nai[pi][j]||0;var oPd=D.otdr[pi][0]||0;ht+='<tr><td class=pj>'+p+'</td><td style=text-align:right>$'+Number(crT+crPd).toLocaleString()+'</td><td style=text-align:right>$'+crPd.toLocaleString()+'</td><td style=text-align:right>$'+nSh.toLocaleString()+'</td><td style=text-align:right>$'+nTot.toLocaleString()+'</td><td style=text-align:right>$'+oPd.toLocaleString()+'</td></tr>';}});
ht+='</table>';document.getElementById('projTable').innerHTML=ht;
</script></body></html>'''
    return dash_html

# ── Build Sum ──
def build_sum():
    ds=get_latest_ds()
    if not ds: return '<h1>No data available</h1>'
    m=re.search(r'WK(\d{4,8})',ds); WK_ID=m.group(1) if m else '0000'
    rows=fetch_rows(ds)
    M1=int(WK_ID[:2]); M2=M1+1; M3=M1+2
    if M2>12: M2-=12; M3-=12
    if M3>12: M3-=12
    y1=datetime.datetime.now().year; y2=y1+(1 if M3<=M1 else 0); y3=y2
    def mwks(y,m):
        c=calendar.Calendar(); return sum(1 for w in c.monthdayscalendar(y,m) if any(d>0 for d in w))
    WK1,WK2,WK3=mwks(y1,M1),mwks(y2,M2),mwks(y3,M3)
    MN1,MN2,MN3=MON[M1],MON[M2],MON[M3]

    raw={}
    for r in rows:
        v=r[8]
        if v:
            s=str(v).strip()
            if 'copper' in s.lower() or 'semi' in s.lower():
                raw[normalize_pj(s)]=True
    PROJECTS=sorted(raw.keys()); N=len(PROJECTS)

    cr={p:{'pd':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai={p:{'sh':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mfs={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    otdr={p:{f'{M1}_pd':0,M1:[0]*WK1,f'{M1}_adv':0,f'{M2}_pd':0,M2:[0]*WK2,f'{M2}_adv':0,f'{M3}_pd':0,M3:[0]*WK3,f'{M3}_adv':0} for p in PROJECTS}
    otdd={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    real={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai_orders={p:{M1:{w:[] for w in range(WK1)},M2:{w:[] for w in range(WK2)},M3:{w:[] for w in range(WK3)},'sh':[]} for p in PROJECTS}
    otdr_orders={p:{f'{M1}_pd':[],f'{M2}_pd':[],f'{M3}_pd':[]} for p in PROJECTS}

    for r in rows:
        pj=normalize_pj(str(r[8] or '')); sa=sf(r[10])
        if pj not in PROJECTS: continue
        cmi=si(r[15] if len(r)>15 else None); cwi=si(r[16] if len(r)>16 else None)
        cwl=str(r[16] or '').strip().lower() if len(r)>16 else ''
        if cwl in ('backlog','pass due'): cr[pj]['pd']+=sa
        elif cmi==M1 and cwi and 1<=cwi<=WK1: cr[pj][M1][cwi-1]+=sa
        elif cmi==M2 and cwi and 1<=cwi<=WK2: cr[pj][M2][cwi-1]+=sa
        elif cmi==M3 and cwi and 1<=cwi<=WK3: cr[pj][M3][cwi-1]+=sa
        nwl=str(r[21] or '').strip().lower() if len(r)>21 else ''
        nwi=si(r[21] if len(r)>21 else None); nmi=si(r[20] if len(r)>20 else None)
        src_no=str(r[11] or '') if len(r)>11 else ''
        stn,exc,st_time=wip_status(src_no)
        oi=(str(r[1] or ''), src_no, round(sa,2), str(r[6] or '')[:10], str(r[5] or '')[:10], stn, exc, st_time)
        if nwl=='shipped': nai[pj]['sh']+=sa; nai_orders[pj]['sh'].append(oi)
        elif nmi==M1 and nwi and 1<=nwi<=WK1: nai[pj][M1][nwi-1]+=sa; nai_orders[pj][M1][nwi-1].append(oi)
        elif nmi==M2 and nwi and 1<=nwi<=WK2: nai[pj][M2][nwi-1]+=sa; nai_orders[pj][M2][nwi-1].append(oi)
        elif nmi==M3 and nwi and 1<=nwi<=WK3: nai[pj][M3][nwi-1]+=sa; nai_orders[pj][M3][nwi-1].append(oi)
        omi=si(r[22] if len(r)>22 else None); owi=si(r[23] if len(r)>23 else None)
        owl=str(r[23] or '').strip() if len(r)>23 else ''
        if omi==M1:
            if owl=='Pass Due': otdr[pj][f'{M1}_pd']+=sa; otdr_orders[pj][f'{M1}_pd'].append(oi)
            elif owl=='Advanced': otdr[pj][f'{M1}_adv']+=sa
            elif owi and 1<=owi<=WK1: otdr[pj][M1][owi-1]+=sa
        elif omi==M2:
            if owl=='Pass Due': otdr[pj][f'{M2}_pd']+=sa; otdr_orders[pj][f'{M2}_pd'].append(oi)
            elif owl=='Advanced': otdr[pj][f'{M2}_adv']+=sa
            elif owi and 1<=owi<=WK2: otdr[pj][M2][owi-1]+=sa
        elif omi==M3:
            if owl=='Pass Due': otdr[pj][f'{M3}_pd']+=sa; otdr_orders[pj][f'{M3}_pd'].append(oi)
            elif owl=='Advanced': otdr[pj][f'{M3}_adv']+=sa
            elif owi and 1<=owi<=WK3: otdr[pj][M3][owi-1]+=sa

    active=[]
    for p in PROJECTS:
        if sum(cr[p]['pd'] for _ in [1])+sum(cr[p][M1])+sum(cr[p][M2])+sum(cr[p][M3])>0:
            active.append(p)
    PROJECTS=active; N=len(PROJECTS)

    ca=[];
    for p in PROJECTS:
        d=cr[p]; ca.append([d['pd']]+d[M1]+[sf_int(d['pd']+sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    ct=[sf_int(sum(ca[i][j] for i in range(N))) for j in range(len(ca[0]))]
    ma=[]
    for p in PROJECTS: d=mfs[p]; ma.append(d[M1]+[sf_int(sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    mt_=[sf_int(sum(ma[i][j] for i in range(N))) for j in range(len(ma[0]))]
    na=[]
    for p in PROJECTS: d=nai[p]; na.append([d['sh']]+d[M1]+[sf_int(sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    nt=[sf_int(sum(na[i][j] for i in range(N))) for j in range(len(na[0]))]
    oa=[]
    for p in PROJECTS:
        d=otdr[p]; oa.append([d[f'{M1}_pd']]+d[M1]+[d[f'{M1}_adv']]+[sf_int(sum(d[M1])+d[f'{M1}_adv'])]+[d[f'{M2}_pd']]+d[M2]+[d[f'{M2}_adv']]+[sf_int(sum(d[M2])+d[f'{M2}_adv'])]+[d[f'{M3}_pd']]+d[M3]+[d[f'{M3}_adv']]+[sf_int(sum(d[M3])+d[f'{M3}_adv'])])
    ot=[sf_int(sum(oa[i][j] for i in range(N))) for j in range(len(oa[0]))]

    def tbl(title,cols,hdr,data,tot,nai_mode=False):
        h=f'<table><tr><td class=tt colspan={cols}>{title}</td></tr><tr>'
        for v,s in hdr: h+=f'<th class=mh {"rowspan=2" if s==1 else f"colspan={s}"}>{v}</th>'
        h+='</tr><tr>'
        for _,wc in [(MN1,WK1),(MN2,WK2),(MN3,WK3)]:
            for i in range(wc): h+=f'<th class=sh>W{i+1}</th>'
            h+='<th class=sh>Total</th>'
        h+='</tr>'
        for i,p in enumerate(PROJECTS):
            h+=f'<tr><td class=pj>{p}</td>'
            for ci,v in enumerate(data[i]):
                h+=f'<td class=d>{fmtv(v)}</td>'
            h+='</tr>'
        h+=f'<tr class=ttl><td class=pj>Total</td>'+''.join(f'<td class=d>{fmtv(v)}</td>' for v in tot)+'</tr></table>'
        return h

    w1=[f'W{i+1}' for i in range(WK1)]; w2=[f'W{i+1}' for i in range(WK2)]; w3=[f'W{i+1}' for i in range(WK3)]
    H=f'''<!DOCTYPE html><html lang=en><head><meta charset=UTF-8><title>Penang Scheduling WK{WK_ID}</title>
<style>
body{{font-family:Segoe UI,sans-serif;font-size:11px;margin:20px;background:#f5f5f5}}
h1{{color:#1a237e;font-size:20px}}table{{border-collapse:collapse;margin-bottom:15px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
td,th{{border:1px solid #ccc;padding:3px 6px;text-align:center;vertical-align:middle}}
.pj{{text-align:left;font-weight:600;background:#fff;min-width:140px}}
.d{{background:#fff;min-width:50px}}
.tt{{text-align:center;font-weight:700;font-size:13px;color:#fff;background:#1a237e;padding:4px 10px}}
.mh{{font-weight:700;font-size:10px;background:#e8eaf6;color:#1a237e;text-align:center}}
.sh{{font-weight:600;font-size:10px;background:#f5f5f5;text-align:center}}
.st{{font-weight:700;font-size:10px;background:#fff3e0;text-align:center;color:#e65100}}
.ttl td{{background:#e8eaf6;font-weight:700;color:#1a237e}}
.btn{{background:#1a237e;color:#fff;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:12px;border:none;text-decoration:none;display:inline-block}}
.hdr{{display:flex;align-items:center;margin-bottom:10px}}
</style></head><body>
<div class=hdr><h1 style="margin:0">Penang Production Scheduling &mdash; WK{WK_ID}</h1><a href="/" class=btn style="margin-left:15px">📈 Dashboard</a></div>
<p style=color:#666>{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} | {MN1}({WK1}w)/{MN2}({WK2}w)/{MN3}({WK3}w)</p>
{tbl(f'Customer Request (WK{WK_ID})',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Pass Due',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ca,ct)}
{tbl('Material FK status',1+WK1+1+WK2+1+WK3+1,[('Project code',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ma,mt_)}
{tbl('NAI Production (Commit)',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Shipped',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],na,nt)}
<table><tr><td class=tt colspan={1+(WK1+3)*3}>OTDR</td></tr><tr>
<th class=mh rowspan=2 style="min-width:120px">Project code</th>
<th class=mh colspan={WK1+3}>{MN1}</th><th class=mh colspan={WK2+3}>{MN2}</th><th class=mh colspan={WK3+3}>{MN3}</th></tr><tr>
<th class=st>Pass Due</th>{''.join(f'<th class=sh>{w}</th>' for w in w1)}<th class=st>Advanced</th><th class=sh>Total</th>
<th class=st>Pass Due</th>{''.join(f'<th class=sh>{w}</th>' for w in w2)}<th class=st>Advanced</th><th class=sh>Total</th>
<th class=st>Pass Due</th>{''.join(f'<th class=sh>{w}</th>' for w in w3)}<th class=st>Advanced</th><th class=sh>Total</th></tr>'''
    for i,p in enumerate(PROJECTS):
        H+=f'<tr><td class=pj>{p}</td>'+''.join(f'<td class=d>{fmtv(v)}</td>' for v in oa[i])+'</tr>'
    H+=f'<tr class=ttl><td class=pj>Total</td>'+''.join(f'<td class=d>{fmtv(v)}</td>' for v in ot)+'</tr></table>'

    sum_cols=1+WK1+WK2+WK3
    H+=f'''<table><tr><td class=tt colspan={sum_cols}>OTDR Real Summary</td></tr><tr>
<th class=mh rowspan=2 style="min-width:120px">Category</th>
<th class=mh colspan={WK1}>{MN1}</th><th class=mh colspan={WK2}>{MN2}</th><th class=mh colspan={WK3}>{MN3}</th></tr><tr>
{''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK1))}
{''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK2))}
{''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK3))}
</tr>'''
    def sum_row(label,data,clr):
        wks=[]
        off=1
        for wc in [WK1,WK2,WK3]: wks.extend(data[off:off+wc]); off+=wc+3
        hx=f'<tr><td class=pj style="background:{clr};color:#1565c0">{label}</td>'
        for v in wks:
            s=f'style="background:{clr}"'
            if v!='' and isinstance(v,int) and v>0:
                hx+=f'<td class="d" {s}>{fmtv(v)}</td>'
            else: hx+=f'<td class=d {s}>{fmtv(v)}</td>'
        return hx+'</tr>'
    H+=sum_row('OTDR Total',ott,'#e3f2fd')
    H+=sum_row('Real Total',real_25,'#fff3e0')
    H+='</table></body></html>'
    return H

# ── Flask Routes ──
@app.route('/')
def index():
    return build_dash()

@app.route('/sum')
def sum_page():
    return build_sum()

@app.route('/rebuild')
def rebuild():
    # Clear WIP cache so it re-fetches
    global WIP_CACHE
    WIP_CACHE=None
    return '<html><body><h1>Refreshed</h1><a href="/">← Back</a></body></html>'

if __name__=='__main__':
    print('Penang Scheduling Web (direct DB)')
    print('  http://0.0.0.0:8080')
    app.run(host='0.0.0.0',port=8080,debug=False)
