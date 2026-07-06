#!/usr/bin/env python3
"""Step 2: Read MySQL export → Build HTML Sum webpage"""
import datetime, os, re, json, openpyxl, calendar, itertools, base64, sys, pymysql
import db_config

DIR = os.path.dirname(os.path.abspath(__file__))
files = [f for f in os.listdir(DIR) if f.startswith('MySQL_WK') and f.endswith('_export.xlsx')]
if not files: print('ERROR: No MySQL export found'); exit(1)
SRC = os.path.join(DIR, max(files, key=lambda f: os.path.getmtime(os.path.join(DIR, f))))

MON = {1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',
       7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}

m = re.search(r'WK(\d{4})', os.path.basename(SRC))
WK_ID = m.group(1) if m else '0702'
CUR_MTH = int(WK_ID[:2])
now = datetime.datetime.now()
CUR_YEAR = now.year
if CUR_MTH <= now.month - 6: CUR_YEAR += 1

M1,M2,M3 = CUR_MTH, CUR_MTH+1, CUR_MTH+2
if M2>12: M2-=12; M3-=12
if M3>12: M3-=12

def month_wks(y,m):
    cal=calendar.Calendar()
    return sum(1 for w in cal.monthdayscalendar(y,m) if any(d>0 for d in w))

y1=CUR_YEAR; y2=y1+(1 if M3<=M1 else 0); y3=y2
WK1=month_wks(y1,M1); WK2=month_wks(y2,M2); WK3=month_wks(y3,M3)
CUTOFF=datetime.datetime(y1,M1,1)
CUTOFF_SEP=datetime.datetime(y3+1 if M3==12 else y3,1 if M3==12 else M3+1,1)
MN1,MN2,MN3=MON[M1],MON[M2],MON[M3]
TW=WK1+WK2+WK3
print(f'2_sum: WK{WK_ID} ({CUR_YEAR}) {MN1}({WK1}w)/{MN2}({WK2}w)/{MN3}({WK3}w)')

wb=openpyxl.load_workbook(SRC,data_only=True)
ws=wb.active
rows=list(ws.iter_rows(values_only=True))
print(f'  Rows: {len(rows)}')

# ── Load WIP data for station tracking ──
wip_cfg=dict(db_config.DB_CONFIG)
wip_cfg['database']='wiptrack'
try:
    wip_conn=pymysql.connect(**wip_cfg)
    wip_cur=wip_conn.cursor()
    # site_station order
    wip_cur.execute("SELECT Station FROM site_station WHERE SiteRef='NAIGROUP_PROD_410' ORDER BY id")
    stations=[r[0] for r in wip_cur.fetchall()]
    stn_next={stations[i]:stations[i+1] for i in range(len(stations)-1)}
    # All wip_exceptions
    wip_cur.execute("SELECT Job,Station,description,start_time,end_time FROM wip_exceptions WHERE SiteRef='NAIGROUP_PROD_410'")
    exc_rows=wip_cur.fetchall()
    wip_exc={}; wip_exc_resolved={}
    for j,s,d,st,et in exc_rows:
        if et is None: wip_exc[j]=[s,d,st,None]  # active
        else: wip_exc_resolved[j]=[s,d,st,et]     # resolved
    # All production_records (latest per job)
    wip_cur.execute("SELECT Job,Station,CompleteDate FROM production_records WHERE SiteRef='NAIGROUP_PROD_410' ORDER BY CompleteDate DESC")
    pr_rows=wip_cur.fetchall()
    wip_pr={}
    for j,s,cd in pr_rows:
        if j not in wip_pr:
            wip_pr[j]=[s,cd]  # first (latest) per job
    wip_cur.close(); wip_conn.close()
    print(f'  WIP: {len(stations)} stations, {len(wip_exc)} active exceptions, {len(wip_pr)} jobs tracked')
except Exception as e:
    print(f'  WIP load failed: {e}, continuing without station data')
    stations=[]; stn_next={}; wip_exc={}; wip_exc_resolved={}; wip_pr={}

# Load site_station → find "包装 Package" as final station
FINAL_STN='包装 Package'

def get_wip_status(src_no):
    """Return (station, exception, start_time) for a Source_Number.
    Logic:
      1. Get latest production_records station.
      2. If station == FINAL_STN → return (station, '', CompleteDate).
      3. Else check wip_exceptions:
         a) Active (end_time NULL): return (exc_station, exc_desc, exc_start_time)
         b) Resolved (end_time exists): return (next after exc_station, '', exc_end_time)
         c) No exception: return (next after current_station, '', CompleteDate)
    """
    job=f'{src_no}-0000'
    if job not in wip_pr:
        return ('','','')
    cur_stn, comp_dt = wip_pr[job]
    cur_stn = cur_stn or ''
    cd_str = str(comp_dt)[:19] if comp_dt else ''
    # Final station → done
    if cur_stn == FINAL_STN:
        return (cur_stn, '', cd_str)
    # Check exceptions
    if job in wip_exc:
        s,d,st,_ = wip_exc[job]
        return (s or '', d or '', str(st)[:19] if st else '')
    if job in wip_exc_resolved:
        s,_,st,et = wip_exc_resolved[job]
        next_s = stn_next.get(s, '')
        return (next_s, '', str(et)[:19] if et else '')
    # No exception: next station from current
    next_s = stn_next.get(cur_stn, '')
    return (next_s, '', cd_str)

def normalize_pj(s):
    """Normalize project name: keep company name as-is, fix Semi-conductor/Copper casing"""
    parts=s.strip().split()
    if len(parts)>=2:
        company=' '.join(parts[:-1])
        suffix=parts[-1].lower()
        if suffix=='copper': return company+' Copper'
        if suffix in ('semi-conductor','semiconductor','semi-conductor'):
            return company+' Semi-conductor'
    return s.strip()

# Dynamic PROJECTS: auto-detect from WK0703 data only (Copper / Semi-conductor)
raw_pjs={}
for row in rows[1:]:
    v=row[8]
    if v:
        ds=str(row[28] or '').strip().lower()
        if ds!=f'wk{WK_ID}': continue  # Only current WK data
        s=str(v).strip()
        if ('copper' in s.lower() or 'semi' in s.lower()):
            normalized=normalize_pj(s)
            raw_pjs[normalized]=True
PROJECTS=sorted(raw_pjs.keys())
N=len(PROJECTS)
print(f'  Projects ({N}): {PROJECTS}')

def sf(v):
    if v is None: return 0
    if isinstance(v,(int,float)): return float(v)
    try: return float(str(v).replace(',',''))
    except: return 0
def si(v):
    if v is None: return None
    if isinstance(v,int): return v
    if isinstance(v,(float,str)):
        try: return int(float(v))
        except: return None
    return None
def npj(v):
    if not v: return None
    return normalize_pj(v)

# Accumulators
cr={p:{'pd':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
nai={p:{'sh':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
mfs={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
mfa={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
mff={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
otdr={p:{f'{M1}_pd':0,M1:[0]*WK1,f'{M1}_adv':0,f'{M2}_pd':0,M2:[0]*WK2,f'{M2}_adv':0,f'{M3}_pd':0,M3:[0]*WK3,f'{M3}_adv':0} for p in PROJECTS}
otdd={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
real={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}

# NAI order tracking for drill-down: nai_orders[pj][month][week] = [order1, order2, ...]
nai_orders={p:{M1:{wk:[] for wk in range(WK1)},M2:{wk:[] for wk in range(WK2)},M3:{wk:[] for wk in range(WK3)},"sh":[]} for p in PROJECTS}
# OTDR order tracking for Pass Due drill-down
otdr_orders={p:{f'{M1}_pd':[],f'{M2}_pd':[],f'{M3}_pd':[]} for p in PROJECTS}

for row in rows[1:]:
    if len(row)<30: continue
    pj=npj(row[8]); sa=sf(row[10]); sq=sf(row[14]); ord_no=row[2]  # Order number at index 2
    ds_l=str(row[28] or '').strip().lower()
    if not pj or sa<=0: continue
    if ds_l!=f'wk{WK_ID}': continue
    cm=row[15]; cw=row[16]; mt=row[17]; mm=row[18]; mw=row[19]
    nm=row[20]; nw=row[21]; om=row[22]; ow=row[23]; oam=row[24]; oaw=row[25]
    rm=row[26]; rw=row[27]
    cmi=si(cm); cwi=si(cw); mmi=si(mm); mwi=si(mw); nmi=si(nm)
    omi=si(om); owi=si(ow); oami=si(oam); oawi=si(oaw)
    rmi=si(rm); rwi=si(rw)

    cw_l=str(cw).strip().lower() if cw else ''
    if cw_l in ('backlog','pass due'): cr[pj]['pd']+=sa
    elif cmi==M1 and cwi and 1<=cwi<=WK1: cr[pj][M1][cwi-1]+=sa
    elif cmi==M2 and cwi and 1<=cwi<=WK2: cr[pj][M2][cwi-1]+=sa
    elif cmi==M3 and cwi and 1<=cwi<=WK3: cr[pj][M3][cwi-1]+=sa

    # NAI: use NAI_WK (nwi) for week index
    nw_l=str(nw).strip().lower() if nw else ''
    nwi=si(nw)  # parse NAI_WK as number
    src_no=str(row[11] or ''); req_dt=str(row[7] or ''); due_dt=str(row[6] or '')
    stn,exc,st_time=get_wip_status(src_no)
    ord_info=(str(ord_no), src_no, round(sa,2), req_dt[:10], due_dt[:10], stn, exc, st_time)
    if nw_l=='shipped': 
        nai[pj]['sh']+=sa
        nai_orders[pj]["sh"].append(ord_info)
    elif nmi==M1 and nwi and 1<=nwi<=WK1: 
        nai[pj][M1][nwi-1]+=sa
        nai_orders[pj][M1][nwi-1].append(ord_info)
    elif nmi==M2 and nwi and 1<=nwi<=WK2: 
        nai[pj][M2][nwi-1]+=sa
        nai_orders[pj][M2][nwi-1].append(ord_info)
    elif nmi==M3 and nwi and 1<=nwi<=WK3: 
        nai[pj][M3][nwi-1]+=sa
        nai_orders[pj][M3][nwi-1].append(ord_info)

    # FK Status: based on MFS_MTH and MFS_WK only
    mt_l=str(mt).strip().lower() if mt else ''
    is_act=mt_l in ('act','actual','shipped')
    tg=mfa[pj] if is_act else mff[pj]
    if mmi==M1: wi=(mwi-1) if(mwi and 1<=mwi<=WK1) else 0; mfs[pj][M1][wi]+=sa; tg[M1][wi]+=sa
    elif mmi==M2: wi=(mwi-1) if(mwi and 1<=mwi<=WK2) else 0; mfs[pj][M2][wi]+=sa; tg[M2][wi]+=sa
    elif mmi==M3: wi=(mwi-1) if(mwi and 1<=mwi<=WK3) else 0; mfs[pj][M3][wi]+=sa; tg[M3][wi]+=sa

    ow_l=str(ow).strip() if ow else ''
    if omi==M1:
        if ow_l=='Pass Due': otdr[pj][f'{M1}_pd']+=sa; otdr_orders[pj][f'{M1}_pd'].append(ord_info)
        elif ow_l=='Advanced': otdr[pj][f'{M1}_adv']+=sa
        elif owi and 1<=owi<=WK1: otdr[pj][M1][owi-1]+=sa
    elif omi==M2:
        if ow_l=='Pass Due': otdr[pj][f'{M2}_pd']+=sa; otdr_orders[pj][f'{M2}_pd'].append(ord_info)
        elif ow_l=='Advanced': otdr[pj][f'{M2}_adv']+=sa
        elif owi and 1<=owi<=WK2: otdr[pj][M2][owi-1]+=sa
    elif omi==M3:
        if ow_l=='Pass Due': otdr[pj][f'{M3}_pd']+=sa; otdr_orders[pj][f'{M3}_pd'].append(ord_info)
        elif ow_l=='Advanced': otdr[pj][f'{M3}_adv']+=sa
        elif owi and 1<=owi<=WK3: otdr[pj][M3][owi-1]+=sa

    if oami==M1 and oawi and 1<=oawi<=WK1: otdd[pj][M1][oawi-1]+=sa
    elif oami==M2 and oawi and 1<=oawi<=WK2: otdd[pj][M2][oawi-1]+=sa
    elif oami==M3 and oawi and 1<=oawi<=WK3: otdd[pj][M3][oawi-1]+=sa

    if rmi==M1 and rwi and 1<=rwi<=WK1: real[pj][M1][rwi-1]+=sa
    elif rmi==M2 and rwi and 1<=rwi<=WK2: real[pj][M2][rwi-1]+=sa
    elif rmi==M3 and rwi and 1<=rwi<=WK3: real[pj][M3][rwi-1]+=sa

# Remove projects with no data in target months
active_pjs=[]
for p in PROJECTS:
    cr_t=cr[p]['pd']+sum(cr[p][M1])+sum(cr[p][M2])+sum(cr[p][M3])
    nai_t=nai[p]['sh']+sum(nai[p][M1])+sum(nai[p][M2])+sum(nai[p][M3])
    mfs_t=sum(mfs[p][M1])+sum(mfs[p][M2])+sum(mfs[p][M3])
    if cr_t>0 or nai_t>0 or mfs_t>0:
        active_pjs.append(p)
if len(active_pjs)<len(PROJECTS):
    removed=[p for p in PROJECTS if p not in active_pjs]
    print(f'  Removed empty projects: {removed}')
    PROJECTS=active_pjs
    N=len(PROJECTS)

# Build arrays
ca=[]; ct=None
for p in PROJECTS:
    d=cr[p]
    ca.append([d['pd']]+d[M1]+[d['pd']+sum(d[M1])]+d[M2]+[sum(d[M2])]+d[M3]+[sum(d[M3])])
ct=[sum(ca[i][j] for i in range(N)) for j in range(len(ca[0]))]

na=[]
for p in PROJECTS:
    d=nai[p]
    na.append([d['sh']]+d[M1]+[d['sh']+sum(d[M1])]+d[M2]+[sum(d[M2])]+d[M3]+[sum(d[M3])])
nt=[sum(na[i][j] for i in range(N)) for j in range(len(na[0]))]

ma=[]
for p in PROJECTS:
    d=mfs[p]
    ma.append(d[M1]+[sum(d[M1])]+d[M2]+[sum(d[M2])]+d[M3]+[sum(d[M3])])
mt_=[sum(ma[i][j] for i in range(N)) for j in range(len(ma[0]))]

oa=[]
for p in PROJECTS:
    d=otdr[p]
    oa.append([d[f'{M1}_pd']]+d[M1]+[d[f'{M1}_adv']]+[d[f'{M1}_pd']+sum(d[M1])+d[f'{M1}_adv']]+
              [d[f'{M2}_pd']]+d[M2]+[d[f'{M2}_adv']]+[d[f'{M2}_pd']+sum(d[M2])+d[f'{M2}_adv']]+
              [d[f'{M3}_pd']]+d[M3]+[d[f'{M3}_adv']]+[d[f'{M3}_pd']+sum(d[M3])+d[f'{M3}_adv']])
ot=[sum(oa[i][j] for i in range(N)) for j in range(len(oa[0]))]

otd=[]
for p in PROJECTS:
    d=otdd[p]
    otd.append([0]+d[M1]+[0]+[sum(d[M1])]+[0]+d[M2]+[0]+[sum(d[M2])]+[0]+d[M3]+[0]+[sum(d[M3])])
ott=[sum(otd[i][j] for i in range(N)) for j in range(len(otd[0]))]

nt[WK1+1]=ot[WK1+2]; nt[WK1+WK2+2]=ot[WK1+WK2+5]; nt[WK1+WK2+WK3+3]=ot[WK1+WK2+WK3+8]

os_=['']*len(ott)
for w in range(WK1):
    ci,ti=1+w,1+w
    if ci<len(ct) and ti<len(ott) and ct[ci]>0: os_[ti]=min(round(ott[ti]/ct[ci]*100),100)
for w in range(WK2):
    ci,ti=2+WK1+w,4+WK1+w
    if ci<len(ct) and ti<len(ott) and ct[ci]>0: os_[ti]=min(round(ott[ti]/ct[ci]*100),100)
for w in range(WK3):
    ci,ti=3+WK1+WK2+w,6+WK1+WK2+1+w
    if ci<len(ct) and ti<len(ott) and ct[ci]>0: os_[ti]=min(round(ott[ti]/ct[ci]*100),100)

real_25=[0]*len(ott)
ri=1
for w in range(WK1): real_25[ri]=round(sum(real[p][M1][w] for p in PROJECTS)); ri+=1
ri+=2; ri+=1
for w in range(WK2): real_25[ri]=round(sum(real[p][M2][w] for p in PROJECTS)); ri+=1
ri+=2; ri+=1
for w in range(WK3): real_25[ri]=round(sum(real[p][M3][w] for p in PROJECTS)); ri+=1

rs=['']*len(real_25)
for w in range(WK1):
    ci,ti=1+w,1+w
    if ci<len(ct) and ct[ci]>0 and real_25[ti]>0: rs[ti]=min(round(real_25[ti]/ct[ci]*100),100)
for w in range(WK2):
    ci,ti=4+WK1+w,4+WK1+w
    if ci<len(ct) and ct[ci]>0 and real_25[ti]>0: rs[ti]=min(round(real_25[ti]/ct[ci]*100),100)
for w in range(WK3):
    ci,ti=6+WK1+WK2+1+w,6+WK1+WK2+1+w
    if ci<len(ct) and ct[ci]>0 and real_25[ti]>0: rs[ti]=min(round(real_25[ti]/ct[ci]*100),100)

am1=round(sum(sum(mfa[p][M1]) for p in PROJECTS))
am2=round(sum(sum(mfa[p][M2]) for p in PROJECTS))
am3=round(sum(sum(mfa[p][M3]) for p in PROJECTS))
fm1=round(sum(sum(mff[p][M1]) for p in PROJECTS))
fm2=round(sum(sum(mff[p][M2]) for p in PROJECTS))
fm3=round(sum(sum(mff[p][M3]) for p in PROJECTS))
mta=[0]*19; mtf=[0]*19
for w in range(WK1): mta[w]=round(sum(mfa[p][M1][w] for p in PROJECTS)); mtf[w]=round(sum(mff[p][M1][w] for p in PROJECTS))
mta[5]=am1; mtf[5]=fm1
for w in range(WK2): mta[6+w]=round(sum(mfa[p][M2][w] for p in PROJECTS)); mtf[6+w]=round(sum(mff[p][M2][w] for p in PROJECTS))
mta[12]=am2; mtf[12]=fm2
for w in range(WK3): mta[13+w]=round(sum(mfa[p][M3][w] for p in PROJECTS)); mtf[13+w]=round(sum(mff[p][M3][w] for p in PROJECTS))
mta[18]=am3; mtf[18]=fm3

do_,dc_=[],[]
for p in PROJECTS:
    dr_,dcr_=[],[]; cd=cr[p]; od=otdd[p]
    for w in range(TW):
        if w<WK1: dr_.append(round(od[M1][w])); dcr_.append(round(cd[M1][w]))
        elif w<WK1+WK2: dr_.append(round(od[M2][w-WK1])); dcr_.append(round(cd[M2][w-WK1]))
        else: dr_.append(round(od[M3][w-WK1-WK2])); dcr_.append(round(cd[M3][w-WK1-WK2]))
    do_.append(dr_); dc_.append(dcr_)

# Build NAI + OTDR orders JSON for drill-down
# Format: [order_no, source_number, amount, request_date, due_date, station, exception, start_time]
def build_orders_json(orders_dict, has_months=True):
    result={}
    for pi,p in enumerate(PROJECTS):
        d=orders_dict[p]
        month_data={}
        mths=[(M1,WK1),(M2,WK2),(M3,WK3)] if has_months else [(f'{M1}_pd',),(f'{M2}_pd',),(f'{M3}_pd',)]
        for mth_key in mths:
            if has_months:
                mth,wks=mth_key[0],mth_key[1]
                wl=[]
                for wk in range(wks):
                    seen={}
                    for o,sn,a,rd,dd,stn,exc,st_ in d[mth][wk]:
                        if o not in seen: seen[o]=[o,sn,a,rd,dd,stn,exc,st_]
                        else: seen[o][2]+=a
                    wl.append([[o,sn,round(a,2),rd,dd,stn,exc,st_] for o,sn,a,rd,dd,stn,exc,st_ in seen.values()])
                month_data[str(mth)]=wl
                seen_tot={}
                for wk in range(wks):
                    for o,sn,a,rd,dd,stn,exc,st_ in d[mth][wk]:
                        if o not in seen_tot: seen_tot[o]=[o,sn,a,rd,dd,stn,exc,st_]
                        else: seen_tot[o][2]+=a
                if 'tot' not in month_data: month_data['tot']={}
                month_data['tot'][str(mth)]=[[o,sn,round(a,2),rd,dd,stn,exc,st_] for o,sn,a,rd,dd,stn,exc,st_ in seen_tot.values()]
            else:
                mth_key=mth_key[0]
                seen={}
                for o,sn,a,rd,dd,stn,exc,st_ in d[mth_key]:
                    if o not in seen: seen[o]=[o,sn,a,rd,dd,stn,exc,st_]
                    else: seen[o][2]+=a
                month_data[mth_key]=[[o,sn,round(a,2),rd,dd,stn,exc,st_] for o,sn,a,rd,dd,stn,exc,st_ in seen.values()]
        if has_months:
            seen={}
            for o,sn,a,rd,dd,stn,exc,st_ in d['sh']:
                if o not in seen: seen[o]=[o,sn,a,rd,dd,stn,exc,st_]
                else: seen[o][2]+=a
            month_data['sh']=[[o,sn,round(a,2),rd,dd,stn,exc,st_] for o,sn,a,rd,dd,stn,exc,st_ in seen.values()]
        result[str(pi)]=month_data
    return result

nai_orders_json=build_orders_json(nai_orders, has_months=True)
otdr_orders_json=build_orders_json(otdr_orders, has_months=False)

print(f'  CR: ${sum(ct):,.0f}')

# ─── HTML ───
def fmtv(v):
    if v and isinstance(v,(int,float)) and round(v)!=0: return f'${round(v):,}'
    return ''

w1=[f'W{i+1}' for i in range(WK1)]
w2=[f'W{i+1}' for i in range(WK2)]
w3=[f'W{i+1}' for i in range(WK3)]

H='''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Penang WK'''+WK_ID+'''</title>
<style>
body{font-family:Segoe UI,sans-serif;font-size:11px;margin:20px;background:#f5f5f5}
h1{color:#1a237e;font-size:20px}
table{border-collapse:collapse;margin-bottom:15px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.12)}
td,th{border:1px solid #bbb;padding:2px 5px;white-space:nowrap;text-align:right}
.pj{text-align:left;font-weight:600;color:#1a237e;min-width:120px;background:#fafafa}
.d{min-width:48px;cursor:default}
.dc{cursor:pointer !important;color:#1565c0 !important;text-decoration:underline !important}
.dc:hover{background:#e3f2fd !important}
.ttl td{font-weight:700;background:#e8eaf6}
.rttl td{font-weight:700;background:#e3f2fd}
.tt{text-align:center;font-weight:700;font-size:13px;color:#fff;background:#1a237e;padding:4px 10px}
.mh{font-weight:700;font-size:10px;background:#e8eaf6;color:#1a237e;text-align:center}
.sh{font-weight:600;font-size:10px;background:#f5f5f5;text-align:center}
.st{font-weight:700;font-size:10px;background:#fff3e0;text-align:center;color:#e65100}
.pct{color:#1565c0;font-weight:600}
.btn{background:#1a237e;color:#fff;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:12px;border:none}
.hdr{display:flex;align-items:center;margin-bottom:10px}
.modal{display:none;position:fixed;z-index:999;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.4)}
.modal-content{background:#fff;margin:5% auto;padding:20px;border-radius:6px;width:85%;max-height:75vh;overflow:auto;box-shadow:0 4px 20px rgba(0,0,0,.2)}
.modal-content table{width:100%;margin:0;box-shadow:none;white-space:nowrap}
.modal-content td, .modal-content th{padding:3px 5px;font-size:11px}
.modal-content thead th{position:sticky;top:0;background:#d9e1f2;z-index:1}
.close{float:right;font-size:24px;font-weight:bold;cursor:pointer;color:#666}
.close:hover{color:#000}
</style></head><body>
<div class="hdr"><h1 style="margin:0">Penang Production Scheduling &mdash; WK'''+WK_ID+'''</h1>
<button class="btn" onclick="exportExcel()">Export Sum Excel</button>
<button class="btn" style="margin-left:15px" onclick="downloadMySQL()">Download '''+os.path.basename(SRC)+'''</button></div>
<p style="color:#666">'''+datetime.datetime.now().strftime("%Y-%m-%d %H:%M")+''' | '''+MN1+'''('''+str(WK1)+'''w)/'''+MN2+'''('''+str(WK2)+'''w)/'''+MN3+'''('''+str(WK3)+'''w)</p>
<div id="orderModal" class="modal"><div class="modal-content"><span class="close" onclick="closeModal()">&times;</span>
<button class="btn" style="float:right;margin-right:30px;margin-top:10px" onclick="exportPopup()">Export Excel</button>
<div id="orderList"></div></div></div>'''

def tbl(title,cols,h1,data,tot,clickable=False,nai_mode=False):
    h=f'<table><tr><td class="tt" colspan="{cols}">{title}</td></tr><tr>'
    for v,s in h1: h+=f'<th class="mh" {"rowspan=2" if s==1 else f"colspan={s}"}>{v}</th>'
    h+='</tr><tr>'
    for _,wc in [(MN1,WK1),(MN2,WK2),(MN3,WK3)]:
        for i in range(wc): h+=f'<th class="sh">W{i+1}</th>'
        h+='<th class="sh">Total</th>'
    h+='</tr>'
    for i,p in enumerate(PROJECTS):
        h+=f'<tr><td class="pj">{p}</td>'
        for ci,v in enumerate(data[i]):
            # Determine Total columns
            tot_cols = {0, WK1+1, WK1+WK2+2, WK1+WK2+WK3+3}
            if clickable and ci>0 and ci not in tot_cols:
                if 1<=ci<=WK1: m_,w_=str(M1),ci-1
                elif WK1+2<=ci<=WK1+1+WK2: m_,w_=str(M2),ci-(WK1+2)
                elif WK1+WK2+3<=ci<=WK1+WK2+WK3+2: m_,w_=str(M3),ci-(WK1+WK2+3)
                else: m_,w_=None,None
                if m_ is not None:
                    h+=f'<td class="d dc" onclick="showOrders({i},{m_},{w_})">{fmtv(v)}</td>'
                else:
                    h+=f'<td class="d">{fmtv(v)}</td>'
            elif clickable and nai_mode and ci in tot_cols:
                if ci==0: m_=None  # Shipped Total
                elif ci==WK1+1: m_=str(M1)
                elif ci==WK1+WK2+2: m_=str(M2)
                elif ci==WK1+WK2+WK3+3: m_=str(M3)
                else: m_=None
                if m_: h+=f'<td class="d dc" onclick="showOrders({i},{m_},-1)">{fmtv(v)}</td>'
                else: h+=f'<td class="d">{fmtv(v)}</td>'
            else:
                h+=f'<td class="d">{fmtv(v)}</td>'
        h+='</tr>'
    # Total row - make ALL cells clickable for NAI
    if nai_mode:
        h+=f'<tr class=ttl><td class=pj>Total</td>'
        for ci,v in enumerate(tot):
            tot_cols = {0, WK1+1, WK1+WK2+2, WK1+WK2+WK3+3}
            # Determine month and week for this column
            if ci==0: m_,w_=None,None  # Shipped - not clickable
            elif 1<=ci<=WK1: m_,w_=str(M1),ci-1
            elif ci==WK1+1: m_,w_=str(M1),-1  # M1 Total
            elif WK1+2<=ci<=WK1+1+WK2: m_,w_=str(M2),ci-(WK1+2)
            elif ci==WK1+WK2+2: m_,w_=str(M2),-1  # M2 Total
            elif WK1+WK2+3<=ci<=WK1+WK2+WK3+2: m_,w_=str(M3),ci-(WK1+WK2+3)
            elif ci==WK1+WK2+WK3+3: m_,w_=str(M3),-1  # M3 Total
            else: m_,w_=None,None
            if m_ and w_ is not None:
                h+=f'<td class="d dc" onclick="showOrdersAll({m_},{w_})">{fmtv(v)}</td>'
            elif m_=='sh':
                h+=f'<td class="d dc" onclick="showOrdersAll(\'sh\',-1)">{fmtv(v)}</td>'
            else:
                h+=f'<td class="d">{fmtv(v)}</td>'
        h+='</tr></table>'
    else:
        h+=f'<tr class=ttl><td class=pj>Total</td>'+''.join(f'<td class=d>{fmtv(v)}</td>' for v in tot)+'</tr></table>'
    return h

H+=tbl(f'Customer Request (WK{WK_ID})',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Pass Due',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ca,ct)
H+=tbl('Material FK status',1+WK1+1+WK2+1+WK3+1,[('Project code',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ma,mt_)
H+=tbl('NAI Production (Commit)',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Shipped',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],na,nt,clickable=True,nai_mode=True)

otdr_cols=1+(WK1+3)*3
H+=f'<table><tr><td class=tt colspan={otdr_cols}>OTDR</td></tr><tr>'
H+=f'<th class=mh rowspan=2 style="min-width:120px">Project code</th>'
H+=f'<th class=mh colspan={WK1+3}>{MN1}</th><th class=mh colspan={WK2+3}>{MN2}</th><th class=mh colspan={WK3+3}>{MN3}</th></tr><tr>'
H+='<th class=st>Pass Due</th>'+''.join(f'<th class=sh>{w}</th>' for w in w1)+'<th class=st>Advanced</th><th class=sh>Total</th>'
H+='<th class=st>Pass Due</th>'+''.join(f'<th class=sh>{w}</th>' for w in w2)+'<th class=st>Advanced</th><th class=sh>Total</th>'
H+='<th class=st>Pass Due</th>'+''.join(f'<th class=sh>{w}</th>' for w in w3)+'<th class=st>Advanced</th><th class=sh>Total</th></tr>'
for i,p in enumerate(PROJECTS):
    H+=f'<tr><td class=pj>{p}</td>'
    for ci,v in enumerate(oa[i]):
        if ci==0:  # Only M1 Pass Due is clickable
            if v and isinstance(v,(int,float)) and round(v)!=0:
                H+=f'<td class="d dc" onclick="showOTDR({i},\'{M1}_pd\')">{fmtv(v)}</td>'
            else:
                H+=f'<td class=d>{fmtv(v)}</td>'
        else:
            H+=f'<td class=d>{fmtv(v)}</td>'
    H+='</tr>'
# OTDR Total row - July PD clickable
H+='<tr class=ttl><td class=pj>Total</td>'
for ci,v in enumerate(ot):
    if ci==0 and v and isinstance(v,(int,float)) and round(v)!=0:
        H+=f'<td class="d dc" onclick="showOTDRAll()">{fmtv(v)}</td>'
    else:
        H+=f'<td class=d>{fmtv(v)}</td>'
H+='</tr></table>'

# Summary table
sum_cols=1+WK1+WK2+WK3
H+=f'<table><tr><td class=tt colspan={sum_cols}>OTDR Real Summary</td></tr><tr>'
H+=f'<th class=mh rowspan=2 style="min-width:120px">Category</th>'
H+=f'<th class=mh colspan={WK1}>{MN1}</th><th class=mh colspan={WK2}>{MN2}</th><th class=mh colspan={WK3}>{MN3}</th></tr><tr>'
H+=''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK1))
H+=''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK2))
H+=''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK3))
H+='</tr>'

def sum_row(label,data,clr):
    wks=[]; off=1
    for wc in [WK1, WK2, WK3]:
        wks.extend(data[off:off+wc]); off+=wc+3
    h=f'<tr class=rttl><td class=pj style="background:{clr};color:#1565c0">{label}</td>'
    for v in wks:
        s=f'style="background:{clr}"'
        if v!='' and isinstance(v,int) and v>0:
            h+=f'<td class="d pct" {s}>{v}%</td>' if 'Status' in label else f'<td class=d {s}>{fmtv(v)}</td>'
        else: h+=f'<td class=d {s}>{fmtv(v)}</td>'
    h+='</tr>'
    return h

H+=sum_row('OTDR Total',ott,'#e3f2fd')
H+=sum_row('OTDR Status',os_,'#e3f2fd')
H+=sum_row('Real Total',real_25,'#fff3e0')
H+=sum_row('Real Status',rs,'#fff3e0')
H+='</table>'

sd=json.dumps({'pj':PROJECTS,'WK1':WK1,'WK2':WK2,'WK3':WK3,'wk':WK_ID,
    'cr':[[round(v) if isinstance(v,(int,float)) else v for v in r] for r in ca],
    'cr_tot':[round(v) if isinstance(v,(int,float)) else v for v in ct],
    'mfs':[[round(v) if isinstance(v,(int,float)) else v for v in r] for r in ma],
    'mfs_tot':[round(v) if isinstance(v,(int,float)) else v for v in mt_],
    'nai':[[round(v) if isinstance(v,(int,float)) else v for v in r] for r in na],
    'nai_tot':[round(v) if isinstance(v,(int,float)) else v for v in nt],
    'otdr':[[round(v) if isinstance(v,(int,float)) else v for v in r] for r in oa],
    'otdr_tot':[round(v) if isinstance(v,(int,float)) else v for v in ot],
    'os':os_,'otdr_total':otd,'otdr_total_tot':ott,
    'real_total':real_25,'real_stat':rs,
    'do':do_,'dc':dc_,
    'act_m1':am1,'act_m2':am2,'act_m3':am3,'fest_m1':fm1,'fest_m2':fm2,'fest_m3':fm3,
    'mta':mta,'mtf':mtf})

H+=f'<script>var SUM_DATA={sd};'
H+=f'var NAO={json.dumps(nai_orders_json)};'
H+=f'var ODR={json.dumps(otdr_orders_json)};</script>'
H+='''<script>
var gPopupTitle='';var gPopupCols=[];var gPopupData=[];

function buildOrdersHtml(list, pj, t, isMulti){
  gPopupTitle=t;
  gPopupCols=['Order','Source_Number','Request_Date','Due_Date','Sales_amount','Station','Exception'];
  var prefixCols=isMulti?['Project']:[];
  gPopupCols=prefixCols.concat(gPopupCols);
  var h="<h3 style='margin-top:0'>"+t+"</h3><table><thead><tr>"+gPopupCols.map(function(c){return '<th>'+c+'</th>';}).join('')+'</tr></thead><tbody>';
  var rows=[];
  list.forEach(function(o){
    var off=isMulti?1:0;
    var exc=o[off+6]||'';
    var st_=o[off+7]||'';
    var excStr=exc&&st_?(exc+' / '+st_):(exc||st_);
    var row=[o[off],o[off+1],o[off+3],o[off+4],o[off+2],o[off+5]||'',excStr];
    if(isMulti) row=[o[0]].concat(row);
    rows.push(row);
  });
  gPopupData=rows;
  var tot=0;
  rows.forEach(function(r){
    var amt=r[prefixCols.length+4];
    tot+=Number(amt)||0;
    h+='<tr>'+r.map(function(v,i){
      var isNum=(i===prefixCols.length+4);
      return '<td'+(isNum?' style="text-align:right"':'')+'>'+(isNum?Number(v).toLocaleString():v||'')+'</td>';
    }).join('')+'</tr>';
  });
  h+='<tr style="font-weight:700;background:#e8eaf6"><td colspan="'+(gPopupCols.length-1)+'">'+list.length+' order(s)</td><td style="text-align:right">$'+Number(tot).toLocaleString()+'</td></tr></tbody></table>';
  document.getElementById("orderList").innerHTML=h;
  document.getElementById("orderModal").style.display="block";
}

function showOrders(pi,mth,wk){
  var orders=NAO[String(pi)];
  var list;
  if(wk===-1){
    if(!orders||!orders['tot']||!orders['tot'][String(mth)]){list=[];}
    else{list=orders['tot'][String(mth)];}
  } else {
    if(!orders||!orders[String(mth)]||!orders[String(mth)][wk]){list=[];}
    else{list=orders[String(mth)][wk];}
  }
  if(list.length===0){
    document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";
    document.getElementById("orderModal").style.display="block";return;
  }
  var pj=SUM_DATA.pj[pi];
  var t=wk===-1?(pj+" - Month "+mth+" (All Weeks)"):(pj+" - Month "+mth+" W"+(wk+1));
  buildOrdersHtml(list,pj,t,false);
}

function showOTDR(pi,mkey){
  var orders=ODR[String(pi)];
  if(!orders||!orders[mkey]||orders[mkey].length===0){
    document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";
    document.getElementById("orderModal").style.display="block";return;
  }
  var pj=SUM_DATA.pj[pi];
  var t=pj+" - OTDR "+mkey;
  buildOrdersHtml(orders[mkey],pj,t,false);
}
function showOTDRAll(){
'''+f"  var mkey='{M1}_pd';"+'''
  var list=[];
  for(var pi=0;pi<SUM_DATA.pj.length;pi++){
    var orders=ODR[String(pi)];
    if(!orders||!orders[mkey]) continue;
    for(var i=0;i<orders[mkey].length;i++){
      list.push([SUM_DATA.pj[pi]].concat(orders[mkey][i]));
    }
  }
  if(list.length===0){
    document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";
    document.getElementById("orderModal").style.display="block";return;
  }
  buildOrdersHtml(list,'',"All Projects - OTDR "+mkey,true);
}
function closeModal(){document.getElementById("orderModal").style.display="none";}
function showOrdersAll(mth,wk){
  var list=[];var tot=0;
  for(var pi=0;pi<SUM_DATA.pj.length;pi++){
    var orders=NAO[String(pi)];
    var ol;
    if(mth==='sh'){
      if(!orders||!orders['sh']) continue; ol=orders['sh'];
    } else if(wk===-1||wk===-2){
      if(!orders||!orders['tot']||!orders['tot'][String(mth)]) continue; ol=orders['tot'][String(mth)];
    } else {
      if(!orders||!orders[String(mth)]||!orders[String(mth)][wk]) continue; ol=orders[String(mth)][wk];
    }
    for(var i=0;i<ol.length;i++){
      list.push([SUM_DATA.pj[pi]].concat(ol[i]));
    }
  }
  if(list.length===0){
    document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";
    document.getElementById("orderModal").style.display="block";return;
  }
  var t=mth==='sh'?"All Projects - Shipped":(wk===-1||wk===-2)?("All Projects - Month "+mth+" (Total)"):("All Projects - Month "+mth+" W"+(wk+1));
  buildOrdersHtml(list,'',t,true);
}
function exportPopup(){
  if(!gPopupData||gPopupData.length===0)return;
  var BOM=String.fromCharCode(0xFEFF),NL=String.fromCharCode(10);
  var csv=BOM+gPopupCols.join(',')+NL;
  gPopupData.forEach(function(r){
    csv+=r.map(function(v){
      var s=String(v||'');if(s.indexOf(',')>=0||s.indexOf('"')>=0||s.indexOf(NL)>=0)s='"'+s.replace(/"/g,'""')+'"';return s;
    }).join(',')+NL;
  });
  var b=new Blob([csv],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download='NAI_Orders_WK'''+WK_ID+'''.csv';a.click();
}
function exportExcel(){
  var raw=atob(SUM_XLSX_B64);var arr=new Uint8Array(raw.length);
  for(var i=0;i<raw.length;i++)arr[i]=raw.charCodeAt(i);
  var b=new Blob([arr],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  var a=document.createElement('a');a.href=URL.createObjectURL(b);
  a.download='Penang_Sum_WK'''+WK_ID+'''.xlsx';a.click();
}
window.onclick=function(e){if(e.target==document.getElementById("orderModal"))closeModal();};
</script>'''

# Embed MySQL Excel as base64 for download button
with open(SRC,'rb') as f:
    mysql_b64=base64.b64encode(f.read()).decode()
H+=f'<script>var MySQL_B64="{mysql_b64}";var MySQL_FN="{os.path.basename(SRC)}";'
H+='''function downloadMySQL(){
var raw=atob(MySQL_B64);var arr=new Uint8Array(raw.length);
for(var i=0;i<raw.length;i++)arr[i]=raw.charCodeAt(i);
var b=new Blob([arr],{type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});
var a=document.createElement("a");a.href=URL.createObjectURL(b);a.download=MySQL_FN;a.click();}
</script></body></html>'''

out=os.path.join(DIR,f'Penang_Scheduling_WK{WK_ID}_sum.html')

# Generate Sum export as real .xlsx FIRST, then embed base64
xlfile=os.path.join(DIR,f'Penang_Sum_WK{WK_ID}.xlsx')
wbx=openpyxl.Workbook()
wsx=wbx.active; wsx.title='Sum'
def xl_row(ws,r,v):
    for c,val in enumerate(v,1):
        cell=ws.cell(r,c,val); cell.font=openpyxl.styles.Font(name='Times New Roman',size=12)
        cell.border=openpyxl.styles.Border(left=openpyxl.styles.Side(style='thin'),right=openpyxl.styles.Side(style='thin'),top=openpyxl.styles.Side(style='thin'),bottom=openpyxl.styles.Side(style='thin'))

# CR table
wsx.append(['Customer Request']+['']*(len(ca[0])))
wsx.merge_cells(start_row=1,start_column=1,end_row=1,end_column=len(ca[0])+1)
xl_row(wsx,2,['Project','Pass Due']+w1+['Total']+w2+['Total']+w3+['Total'])
for i,p in enumerate(PROJECTS):
    xl_row(wsx,3+i,[p]+[round(v) if isinstance(v,(int,float)) else v for v in ca[i]])
xl_row(wsx,3+N,['Total']+[round(v) if isinstance(v,(int,float)) else v for v in ct])
wsx.append([])

# MFS table
sr=wsx.max_row+1
wsx.append(['Material FK Status']+['']*(len(ma[0])))
wsx.merge_cells(start_row=sr,start_column=1,end_row=sr,end_column=len(ma[0])+1)
xl_row(wsx,sr+1,['Project']+w1+['Total']+w2+['Total']+w3+['Total'])
for i,p in enumerate(PROJECTS):
    xl_row(wsx,sr+2+i,[p]+[round(v) if isinstance(v,(int,float)) else v for v in ma[i]])
xl_row(wsx,sr+2+N,['Total']+[round(v) if isinstance(v,(int,float)) else v for v in mt_])
wsx.append([])

# NAI table
sr=wsx.max_row+1
wsx.append(['NAI Production']+['']*(len(na[0])))
wsx.merge_cells(start_row=sr,start_column=1,end_row=sr,end_column=len(na[0])+1)
xl_row(wsx,sr+1,['Project','Shipped']+w1+['Total']+w2+['Total']+w3+['Total'])
for i,p in enumerate(PROJECTS):
    xl_row(wsx,sr+2+i,[p]+[round(v) if isinstance(v,(int,float)) else v for v in na[i]])
xl_row(wsx,sr+2+N,['Total']+[round(v) if isinstance(v,(int,float)) else v for v in nt])
wsx.append([])

# OTDR table
sr=wsx.max_row+1
wsx.append(['OTDR']+['']*(oa[0].__len__()-1 if oa else 10))
wsx.merge_cells(start_row=sr,start_column=1,end_row=sr,end_column=len(oa[0])+1)
for i,p in enumerate(PROJECTS):
    xl_row(wsx,sr+1+i,[p]+[round(v) if isinstance(v,(int,float)) else v for v in oa[i]])
xl_row(wsx,sr+1+N,['Total']+[round(v) if isinstance(v,(int,float)) else v for v in ot])
wsx.append([])

# Summary table
sr=wsx.max_row+1
wsx.append(['OTDR Real Summary']+['']*(WK1+WK2+WK3))
wsx.merge_cells(start_row=sr,start_column=1,end_row=sr,end_column=WK1+WK2+WK3+1)
xl_row(wsx,sr+1,['Category']+[f'W{i+1}' for i in range(WK1+WK2+WK3)])
# OTDR Total/Status, Real Total/Status
for label,data in [('OTDR Total',ott),('OTDR Status',os_),('Real Total',real_25),('Real Status',rs)]:
    wks=[]; off=1
    for wc in [WK1,WK2,WK3]: wks.extend(data[off:off+wc]); off+=wc+3
    xl_row(wsx,wsx.max_row+1,[label]+wks)

for col in range(1,wsx.max_column+1): wsx.column_dimensions[openpyxl.utils.get_column_letter(col)].width=20
wbx.save(xlfile)
print(f'  Sum XLSX: {os.path.basename(xlfile)} ({os.path.getsize(xlfile)//1024}KB)')

# Embed Sum XLSX as base64 for download button
with open(xlfile,'rb') as f:
    sum_b64=base64.b64encode(f.read()).decode()
H+=f'<script>var SUM_XLSX_B64="{sum_b64}";</script>'

with open(out,'w',encoding='utf-8') as f: f.write(H)
print(f'  OK {os.path.basename(out)} ({len(H)} bytes)')
