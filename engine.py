#!/usr/bin/env python3
"""Penang Scheduling Engine — direct DB query → Sum/Dashboard HTML (original UI preserved)"""
import datetime, os, re, json, calendar, pymysql, base64
import db_config as cfg

MON = {1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',
       7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}

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

def sf_int(v):
    if v is None: return 0
    if isinstance(v,(int,float)): return round(v)
    try: return round(float(str(v).replace(',','')))
    except: return 0

def fmtv(v):
    if v and isinstance(v,(int,float)) and round(v)!=0: return f'${round(v):,}'
    return ''

def normalize_pj(s):
    parts=s.strip().split()
    if len(parts)>=2:
        c=' '.join(parts[:-1])
        sfx=parts[-1].lower()
        if sfx=='copper': return c+' Copper'
        if sfx in ('semi-conductor','semiconductor'): return c+' Semi-conductor'
    return s.strip()

def conn_db():
    return pymysql.connect(**cfg.DB_CONFIG)

def get_latest_ds():
    c=conn_db(); cur=c.cursor()
    cur.execute('SELECT DISTINCT Data_Source FROM covswo_data ORDER BY Data_Source DESC LIMIT 1')
    r=cur.fetchone(); cur.close(); c.close()
    return r[0] if r else None

def fetch_rows(ds):
    c=conn_db(); cur=c.cursor()
    cur.execute('SELECT * FROM covswo_data WHERE Data_Source=%s AND Source_Type=%s',(ds,'Job'))
    r=cur.fetchall(); cur.close(); c.close()
    return r

def real_now():
    return datetime.datetime(2026,7,6,14,53,0)

# ── WIP loading (cached) ──
_WIP=None
def load_wip():
    global _WIP
    if _WIP is not None: return _WIP
    wc=dict(cfg.DB_CONFIG); wc['database']='wiptrack'
    stn={}; exc={}; exc_r={}; pr={}
    try:
        c=pymysql.connect(**wc); cur=c.cursor()
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
    except Exception as e:
        print(f'  WIP fail: {e}')
    _WIP=(ss,stn,exc,exc_r,pr)
    return _WIP

def wip_status(src):
    _,stn,exc,exc_r,pr=load_wip()
    job=f'{src}-0000'
    if job not in pr: return ('','','')
    cur_s,cd=pr[job]; cur_s=cur_s or ''; cd_s=str(cd)[:19] if cd else ''
    if cur_s=='包装 Package': return (cur_s,'',cd_s)
    if job in exc: s,d,st=exc[job]; return (s or '',d or '',str(st)[:19] if st else '')
    if job in exc_r: s,_,st,et=exc_r[job]; return (stn.get(s,''),'',str(et)[:19] if et else '')
    return (stn.get(cur_s,''),'',cd_s)

# ── Main builder ──
def build_all(ds=None):
    if ds is None: ds=get_latest_ds()
    m=re.search(r'WK(\d{4,8})',ds); WK_ID=m.group(1) if m else '0000'
    rows=fetch_rows(ds)
    now=real_now()

    M1=int(WK_ID[:2]); M2=M1+1; M3=M1+2
    if M2>12: M2-=12; M3-=12
    if M3>12: M3-=12
    y1=now.year; y2=y1+(1 if M3<=M1 else 0); y3=y2
    def mwks(y,m):
        c=calendar.Calendar(); return sum(1 for w in c.monthdayscalendar(y,m) if any(d>0 for d in w))
    WK1,WK2,WK3=mwks(y1,M1),mwks(y2,M2),mwks(y3,M3)
    MN1,MN2,MN3=MON[M1],MON[M2],MON[M3]; w1=[f'W{i+1}' for i in range(WK1)]; w2=[f'W{i+1}' for i in range(WK2)]; w3=[f'W{i+1}' for i in range(WK3)]

    raw={}
    for row in rows:
        v=row[8]
        if v:
            s=str(v).strip()
            if 'copper' in s.lower() or 'semi' in s.lower(): raw[normalize_pj(s)]=True
    PROJECTS=sorted(raw.keys()); N=len(PROJECTS)

    cr={p:{'pd':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai={p:{'sh':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mfs={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mfa={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mff={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    otdr={p:{f'{M1}_pd':0,M1:[0]*WK1,f'{M1}_adv':0,f'{M2}_pd':0,M2:[0]*WK2,f'{M2}_adv':0,f'{M3}_pd':0,M3:[0]*WK3,f'{M3}_adv':0} for p in PROJECTS}
    otdd={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    real={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai_orders={p:{M1:{w:[] for w in range(WK1)},M2:{w:[] for w in range(WK2)},M3:{w:[] for w in range(WK3)},"sh":[]} for p in PROJECTS}
    otdr_orders={p:{f'{M1}_pd':[],f'{M2}_pd':[],f'{M3}_pd':[]} for p in PROJECTS}

    for row in rows:
        pj=normalize_pj(str(row[8] or '')); sa=sf(row[10])
        if pj not in PROJECTS: continue
        cmi=si(row[15] if len(row)>15 else None); cwi=si(row[16] if len(row)>16 else None)
        cwl=str(row[16] or '').strip().lower() if len(row)>16 else ''
        if cwl in ('backlog','pass due'): cr[pj]['pd']+=sa
        elif cmi==M1 and cwi and 1<=cwi<=WK1: cr[pj][M1][cwi-1]+=sa
        elif cmi==M2 and cwi and 1<=cwi<=WK2: cr[pj][M2][cwi-1]+=sa
        elif cmi==M3 and cwi and 1<=cwi<=WK3: cr[pj][M3][cwi-1]+=sa
        mmi=si(row[18] if len(row)>18 else None); mwi=si(row[19] if len(row)>19 else None); mtl=str(row[17] or '').strip().lower() if len(row)>17 else ''
        if mmi==M1 and mwi and 1<=mwi<=WK1:
            mfs[pj][M1][mwi-1]+=sa
            if mtl=='actual': mfa[pj][M1][mwi-1]+=sa
            elif mtl=='forecast': mff[pj][M1][mwi-1]+=sa
        elif mmi==M2 and mwi and 1<=mwi<=WK2:
            mfs[pj][M2][mwi-1]+=sa
            if mtl=='actual': mfa[pj][M2][mwi-1]+=sa
            elif mtl=='forecast': mff[pj][M2][mwi-1]+=sa
        elif mmi==M3 and mwi and 1<=mwi<=WK3:
            mfs[pj][M3][mwi-1]+=sa
            if mtl=='actual': mfa[pj][M3][mwi-1]+=sa
            elif mtl=='forecast': mff[pj][M3][mwi-1]+=sa
        nwl=str(row[21] or '').strip().lower() if len(row)>21 else ''
        nwi=si(row[21] if len(row)>21 else None); nmi=si(row[20] if len(row)>20 else None)
        src_no=str(row[11] or '') if len(row)>11 else ''
        stn,exc,st_time=wip_status(src_no)
        oi=(str(row[1] or ''),src_no,round(sa,2),str(row[6] or '')[:10],str(row[5] or '')[:10],stn,exc,st_time)
        if nwl=='shipped': nai[pj]['sh']+=sa; nai_orders[pj]['sh'].append(oi)
        elif nmi==M1 and nwi and 1<=nwi<=WK1: nai[pj][M1][nwi-1]+=sa; nai_orders[pj][M1][nwi-1].append(oi)
        elif nmi==M2 and nwi and 1<=nwi<=WK2: nai[pj][M2][nwi-1]+=sa; nai_orders[pj][M2][nwi-1].append(oi)
        elif nmi==M3 and nwi and 1<=nwi<=WK3: nai[pj][M3][nwi-1]+=sa; nai_orders[pj][M3][nwi-1].append(oi)
        omi=si(row[22] if len(row)>22 else None); owi=si(row[23] if len(row)>23 else None)
        owl=str(row[23] or '').strip() if len(row)>23 else ''
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
        if sum(cr[p]['pd'] for _ in [1])+sum(cr[p][M1])+sum(cr[p][M2])+sum(cr[p][M3])+sum(nai[p][M1])+sum(nai[p][M2])+sum(nai[p][M3])>0: active.append(p)
    PROJECTS=active; N=len(PROJECTS)

    ca=[]; 
    for p in PROJECTS: d=cr[p]; ca.append([d['pd']]+d[M1]+[sf_int(d['pd']+sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    ct=[sf_int(sum(ca[i][j] for i in range(N))) for j in range(len(ca[0]))]
    ma=[]; 
    for p in PROJECTS: d=mfs[p]; ma.append(d[M1]+[sf_int(sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    mt_=[sf_int(sum(ma[i][j] for i in range(N))) for j in range(len(ma[0]))]
    na=[]; 
    for p in PROJECTS: d=nai[p]; na.append([d['sh']]+d[M1]+[sf_int(sum(d[M1]))]+d[M2]+[sf_int(sum(d[M2]))]+d[M3]+[sf_int(sum(d[M3]))])
    nt=[sf_int(sum(na[i][j] for i in range(N))) for j in range(len(na[0]))]
    oa=[]; 
    for p in PROJECTS: d=otdr[p]; oa.append([d[f'{M1}_pd']]+d[M1]+[d[f'{M1}_adv']]+[sf_int(sum(d[M1])+d[f'{M1}_adv'])]+[d[f'{M2}_pd']]+d[M2]+[d[f'{M2}_adv']]+[sf_int(sum(d[M2])+d[f'{M2}_adv'])]+[d[f'{M3}_pd']]+d[M3]+[d[f'{M3}_adv']]+[sf_int(sum(d[M3])+d[f'{M3}_adv'])])
    ot=[sf_int(sum(oa[i][j] for i in range(N))) for j in range(len(oa[0]))]
    TW=WK1+WK2+WK3
    am1=sf_int(sum(sum(mfa[p][M1]) for p in PROJECTS)); am2=sf_int(sum(sum(mfa[p][M2]) for p in PROJECTS)); am3=sf_int(sum(sum(mfa[p][M3]) for p in PROJECTS))
    fm1=sf_int(sum(sum(mff[p][M1]) for p in PROJECTS)); fm2=sf_int(sum(sum(mff[p][M2]) for p in PROJECTS)); fm3=sf_int(sum(sum(mff[p][M3]) for p in PROJECTS))

    # OTDR Real Summary
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
            d=otdr[p]
            if j==0: v+=d[f'{M1}_pd']
            elif 1<=j<=WK1: v+=d[M1][j-1]
            elif j==WK1+1: v+=d[f'{M1}_adv']
            elif WK1+3<=j<=WK1+2+WK2: v+=d[M2][j-(WK1+3)]
            elif j==WK1+WK2+3: v+=d[f'{M2}_adv']
            elif WK1+WK2+5<=j<=WK1+WK2+4+WK3: v+=d[M3][j-(WK1+WK2+5)]
            elif j==WK1+WK2+WK3+5: v+=d[f'{M3}_adv']
        ott[j]=sf_int(v)

    cr_total=sf_int(sum(cr[p]['pd'] for p in PROJECTS)+sum(sum(cr[p][M1]) for p in PROJECTS)+sum(sum(cr[p][M2]) for p in PROJECTS)+sum(sum(cr[p][M3]) for p in PROJECTS))

    # Build orders JSON
    def build_oj(o_dict, hm=True):
        r={}
        for pi,p in enumerate(PROJECTS):
            d=o_dict[p]; md={}
            mths=[(M1,WK1),(M2,WK2),(M3,WK3)] if hm else [(f'{M1}_pd',),(f'{M2}_pd',),(f'{M3}_pd',)]
            def dedup(lst): seen={}; [seen.__setitem__(o[0],[o[0],o[1],round(o[2],2),o[3],o[4],o[5],o[6],o[7]]) or seen[o[0]][2] or None for o in lst]; return list(seen.values())
            for mk in mths:
                if hm: mth,wks=mk[0],mk[1]; md[str(mth)]=[dedup(d[mth][wk]) for wk in range(wks)]
                else: mk=mk[0]; md[mk]=dedup(d[mk])
            if hm:
                seen_sh=dedup(d['sh']); md['sh']=seen_sh
                tots={}
                for mth,wks in [(M1,WK1),(M2,WK2),(M3,WK3)]: all_o=[]; [all_o.extend(d[mth][wk]) for wk in range(wks)]; tots[str(mth)]=dedup(all_o)
                md['tot']=tots
            r[str(pi)]=md
        return r

    nai_oj=build_oj(nai_orders,True); otdr_oj=build_oj(otdr_orders,False)
    sd={'pj':PROJECTS,'WK1':WK1,'WK2':WK2,'WK3':WK3,'wk':WK_ID,
        'cr':[[sf_int(v) for v in r] for r in ca],
        'cr_tot':[sf_int(v) for v in ct],
        'mfs':[[sf_int(v) for v in r] for r in ma],
        'mfs_tot':[sf_int(v) for v in mt_],
        'nai':[[sf_int(v) for v in r] for r in na],
        'nai_tot':[sf_int(v) for v in nt],
        'otdr':[[sf_int(v) for v in r] for r in oa],
        'otdr_tot':[sf_int(v) for v in ot],
        'otdr_stat':rs,'cr_total':cr_total,
        'real_total':real_25,'real_stat':rs,
        'do':[[0]*TW for _ in range(N)],'dc':[[0]*TW for _ in range(N)],
        'act_m1':am1,'act_m2':am2,'act_m3':am3,'fest_m1':fm1,'fest_m2':fm2,'fest_m3':fm3,
        'mta':[0]*19,'mtf':[0]*19}
    for w in range(WK1): sd['mta'][w]=sf_int(sum(mfa[p][M1][w] for p in PROJECTS)); sd['mtf'][w]=sf_int(sum(mff[p][M1][w] for p in PROJECTS))
    sd['mta'][5]=am1; sd['mtf'][5]=fm1
    for w in range(WK2): sd['mta'][6+w]=sf_int(sum(mfa[p][M2][w] for p in PROJECTS)); sd['mtf'][6+w]=sf_int(sum(mff[p][M2][w] for p in PROJECTS))
    sd['mta'][12]=am2; sd['mtf'][12]=fm2
    for w in range(WK3): sd['mta'][13+w]=sf_int(sum(mfa[p][M3][w] for p in PROJECTS)); sd['mtf'][13+w]=sf_int(sum(mff[p][M3][w] for p in PROJECTS))
    sd['mta'][18]=am3; sd['mtf'][18]=fm3

    # mfa, mff not computed in this version - use 0 for now
    sd_json=json.dumps(sd); nao_json=json.dumps(nai_oj); odr_json=json.dumps(otdr_oj)

    # ── GENERATE SUM HTML ──
    def tbl(title,cols,h1,data,tot,clickable=False,nai_mode=False):
        hx=f'<table><tr><td class="tt" colspan="{cols}">{title}</td></tr><tr>'
        for v,s in h1: hx+=f'<th class="mh" {"rowspan=2" if s==1 else f"colspan={s}"}>{v}</th>'
        hx+='</tr><tr>'
        for _,wc in [(MN1,WK1),(MN2,WK2),(MN3,WK3)]:
            for i in range(wc): hx+=f'<th class="sh">W{i+1}</th>'
            hx+='<th class="sh">Total</th>'
        hx+='</tr>'
        for i,p in enumerate(PROJECTS):
            hx+=f'<tr><td class="pj">{p}</td>'
            for ci,v in enumerate(data[i]):
                tot_cols={0,WK1+1,WK1+WK2+2,WK1+WK2+WK3+3}
                if clickable and ci>0 and ci not in tot_cols:
                    if 1<=ci<=WK1: m_,w_=str(M1),ci-1
                    elif WK1+2<=ci<=WK1+1+WK2: m_,w_=str(M2),ci-(WK1+2)
                    elif WK1+WK2+3<=ci<=WK1+WK2+WK3+2: m_,w_=str(M3),ci-(WK1+WK2+3)
                    else: m_,w_=None,None
                    if m_ is not None: hx+=f'<td class="d dc" onclick="showOrders({i},{m_},{w_})">{fmtv(v)}</td>'
                    else: hx+=f'<td class="d">{fmtv(v)}</td>'
                elif clickable and nai_mode and ci in tot_cols:
                    if ci==0: m_=None
                    elif ci==WK1+1: m_=str(M1)
                    elif ci==WK1+WK2+2: m_=str(M2)
                    elif ci==WK1+WK2+WK3+3: m_=str(M3)
                    else: m_=None
                    if m_: hx+=f'<td class="d dc" onclick="showOrders({i},{m_},-1)">{fmtv(v)}</td>'
                    else: hx+=f'<td class="d">{fmtv(v)}</td>'
                else: hx+=f'<td class="d">{fmtv(v)}</td>'
            hx+='</tr>'
        if nai_mode:
            hx+=f'<tr class=ttl><td class=pj>Total</td>'
            for ci,v in enumerate(tot):
                if ci==0: m_,w_=None,None
                elif 1<=ci<=WK1: m_,w_=str(M1),ci-1
                elif ci==WK1+1: m_,w_=str(M1),-1
                elif WK1+2<=ci<=WK1+1+WK2: m_,w_=str(M2),ci-(WK1+2)
                elif ci==WK1+WK2+2: m_,w_=str(M2),-1
                elif WK1+WK2+3<=ci<=WK1+WK2+WK3+2: m_,w_=str(M3),ci-(WK1+WK2+3)
                elif ci==WK1+WK2+WK3+3: m_,w_=str(M3),-1
                else: m_,w_=None,None
                if m_ and w_ is not None: hx+=f'<td class="d dc" onclick="showOrdersAll({m_},{w_})">{fmtv(v)}</td>'
                elif m_=='sh': hx+=f'<td class="d dc" onclick="showOrdersAll("sh",-1)">{fmtv(v)}</td>'
                else: hx+=f'<td class="d">{fmtv(v)}</td>'
            hx+='</tr></table>'
        else: hx+=f'<tr class=ttl><td class=pj>Total</td>'+''.join(f'<td class=d>{fmtv(v)}</td>' for v in tot)+'</tr></table>'
        return hx

    sum_html='<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Penang WK{WK_ID}</title><style>body{font-family:Segoe UI,sans-serif;font-size:11px;margin:20px;background:#f5f5f5}h1{color:#1a237e;font-size:20px}table{border-collapse:collapse;margin-bottom:15px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.12)}td,th{border:1px solid #ccc;padding:3px 6px;text-align:center;vertical-align:middle}.pj{text-align:left;font-weight:600;background:#fff;min-width:140px}.d{background:#fff;min-width:50px}.dc{cursor:pointer;text-decoration:underline;color:#1565c0;font-weight:600}.dc:hover{background:#bbdefb}.tt{text-align:center;font-weight:700;font-size:13px;color:#fff;background:#1a237e;padding:4px 10px}.mh{font-weight:700;font-size:10px;background:#e8eaf6;color:#1a237e;text-align:center}.sh{font-weight:600;font-size:10px;background:#f5f5f5;text-align:center}.st{font-weight:700;font-size:10px;background:#fff3e0;text-align:center;color:#e65100}.pct{color:#1565c0;font-weight:600}.ttl td{background:#e8eaf6;font-weight:700;color:#1a237e}.btn{background:#1a237e;color:#fff;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:12px;border:none}.hdr{display:flex;align-items:center;margin-bottom:10px}.modal{display:none;position:fixed;z-index:999;left:0;top:0;width:100%;height:100%;background:rgba(0,0,0,0.4)}.modal-content{background:#fff;margin:5% auto;padding:20px;border-radius:6px;width:85%;max-height:75vh;overflow:auto;box-shadow:0 4px 20px rgba(0,0,0,.2)}.modal-content table{width:100%;margin:0;box-shadow:none;white-space:nowrap}.modal-content td,.modal-content th{padding:3px 5px;font-size:11px}.modal-content thead th{position:sticky;top:0;background:#d9e1f2;z-index:1}.close{float:right;font-size:24px;font-weight:bold;cursor:pointer;color:#666}.close:hover{color:#000}</style></head><body>'
    sum_html+=f'<div class="hdr"><h1 style="margin:0">Penang Production Scheduling &mdash; WK{WK_ID}</h1><a href="/" class="btn" style="margin-left:15px">📈 Dashboard</a></div>'
    sum_html+=f'<p style="color:#666">{now.strftime("%Y-%m-%d %H:%M")} | {MN1}({WK1}w)/{MN2}({WK2}w)/{MN3}({WK3}w)</p>'
    sum_html+='<div id="orderModal" class="modal"><div class="modal-content"><span class="close" onclick="closeModal()">&times;</span><div id="orderList"></div></div></div>'
    sum_html+=tbl(f'Customer Request (WK{WK_ID})',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Pass Due',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ca,ct)
    sum_html+=tbl('Material FK status',1+WK1+1+WK2+1+WK3+1,[('Project code',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ma,mt_)
    sum_html+=tbl('NAI Production (Commit)',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Shipped',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],na,nt,clickable=True,nai_mode=True)

    otdr_cols=1+(WK1+3)*3
    sum_html+=f'<table><tr><td class=tt colspan={otdr_cols}>OTDR</td></tr><tr>'
    sum_html+=f'<th class=mh rowspan=2 style="min-width:120px">Project code</th>'
    sum_html+=f'<th class=mh colspan={WK1+3}>{MN1}</th><th class=mh colspan={WK2+3}>{MN2}</th><th class=mh colspan={WK3+3}>{MN3}</th></tr><tr>'
    sum_html+='<th class=st>Pass Due</th>'+''.join(f'<th class=sh>{w}</th>' for w in w1)+'<th class=st>Advanced</th><th class=sh>Total</th>'
    sum_html+='<th class=st>Pass Due</th>'+''.join(f'<th class=sh>{w}</th>' for w in w2)+'<th class=st>Advanced</th><th class=sh>Total</th>'
    sum_html+='<th class=st>Pass Due</th>'+''.join(f'<th class=sh>{w}</th>' for w in w3)+'<th class=st>Advanced</th><th class=sh>Total</th></tr>'
    for i,p in enumerate(PROJECTS):
        sum_html+=f'<tr><td class=pj>{p}</td>'
        for ci,v in enumerate(oa[i]):
            if ci==0:
                if v and isinstance(v,(int,float)) and sf_int(v)!=0: sum_html+=f'<td class="d dc" onclick="showOTDR({i},\'{M1}_pd\')">{fmtv(v)}</td>'
                else: sum_html+=f'<td class=d>{fmtv(v)}</td>'
            else: sum_html+=f'<td class=d>{fmtv(v)}</td>'
        sum_html+='</tr>'
    sum_html+='<tr class=ttl><td class=pj>Total</td>'
    for ci,v in enumerate(ot):
        if ci==0 and v and isinstance(v,(int,float)) and sf_int(v)!=0: sum_html+=f'<td class="d dc" onclick="showOTDRAll()">{fmtv(v)}</td>'
        else: sum_html+=f'<td class=d>{fmtv(v)}</td>'
    sum_html+='</tr></table>'

    sum_cols=1+WK1+WK2+WK3
    sum_html+=f'<table><tr><td class=tt colspan={sum_cols}>OTDR Real Summary</td></tr><tr>'
    sum_html+=f'<th class=mh rowspan=2 style="min-width:120px">Category</th>'
    sum_html+=f'<th class=mh colspan={WK1}>{MN1}</th><th class=mh colspan={WK2}>{MN2}</th><th class=mh colspan={WK3}>{MN3}</th></tr><tr>'
    sum_html+=''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK1))
    sum_html+=''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK2))
    sum_html+=''.join(f'<th class=sh>W{i+1}</th>' for i in range(WK3))
    sum_html+='</tr>'
    def sum_row(label,data,clr):
        wks=[]; off=1
        for wc in [WK1,WK2,WK3]: wks.extend(data[off:off+wc]); off+=wc+3
        hx=f'<tr class=rttl><td class=pj style="background:{clr};color:#1565c0">{label}</td>'
        for v in wks:
            s=f'style="background:{clr}"'
            if v!='' and isinstance(v,int) and v>0:
                hx+=f'<td class="d pct" {s}>{v}%</td>' if 'Status' in label else f'<td class=d {s}>{fmtv(v)}</td>'
            else: hx+=f'<td class=d {s}>{fmtv(v)}</td>'
        return hx+'</tr>'
    sum_html+=sum_row('OTDR Total',ott,'#e3f2fd')
    sum_html+=sum_row('OTDR Status',rs,'#e3f2fd')
    sum_html+=sum_row('Real Total',real_25,'#fff3e0')
    sum_html+=sum_row('Real Status',rs,'#fff3e0')
    sum_html+='</table>'

    sum_html+=f'<script>var SUM_DATA={sd_json};var NAO={nao_json};var ODR={odr_json};</script>'
    sum_html+=_JS_BLOCK(M1)
    sum_html+='</body></html>'

    # ── GENERATE DASHBOARD HTML ──
    dash_html=_build_dashboard(sd, WK_ID, MN1, MN2, MN3, WK1, WK2, WK3, PROJECTS, oa, ot, rs, [[0]*TW for _ in range(N)], [[0]*TW for _ in range(N)],
                               real_25, rs, sd['mta'], sd['mtf'], M1, M2, M3, am1, am2, am3, fm1, fm2, fm3, cr_total, _JS_BLOCK)

    return sum_html, dash_html


def _JS_BLOCK(m1):
 return '''<script>
var gPopupTitle='',gPopupCols=[],gPopupData=[];
function buildOrdersHtml(list,pj,t,isMulti){
  gPopupTitle=t;gPopupCols=['Order','Source_Number','Request_Date','Due_Date','Sales_amount','Station','Exception'];
  var pc=isMulti?['Project']:[];gPopupCols=pc.concat(gPopupCols);
  var h="<h3 style='margin-top:0'>"+t+"</h3><table><thead><tr>"+gPopupCols.map(function(c){return '<th>'+c+'</th>';}).join('')+'</tr></thead><tbody>';
  var rows=[];
  list.forEach(function(o){
    var off=isMulti?1:0;var exc=o[off+6]||'',st_=o[off+7]||'';var es=exc&&st_?(exc+' / '+st_):(exc||st_);
    var row=[o[off],o[off+1],o[off+3],o[off+4],o[off+2],o[off+5]||'',es];if(isMulti)row=[o[0]].concat(row);rows.push(row);
  });
  gPopupData=rows;var tot=0;
  rows.forEach(function(r){var amt=r[pc.length+4];tot+=Number(amt)||0;h+='<tr>'+r.map(function(v,i){var isNum=(i===pc.length+4);return '<td'+(isNum?' style="text-align:right"':'')+'>'+(isNum?Number(v).toLocaleString():v||'')+'</td>';}).join('')+'</tr>';});
  h+='<tr style="font-weight:700;background:#e8eaf6"><td colspan="'+(gPopupCols.length-1)+'">'+list.length+' order(s)</td><td style="text-align:right">$'+Number(tot).toLocaleString()+'</td></tr></tbody></table>';
  document.getElementById("orderList").innerHTML=h;document.getElementById("orderModal").style.display="block";
}
function showOrders(pi,mth,wk){
  var orders=NAO[String(pi)],list;
  if(wk===-1){if(!orders||!orders['tot']||!orders['tot'][String(mth)])list=[];else list=orders['tot'][String(mth)];}
  else{if(!orders||!orders[String(mth)]||!orders[String(mth)][wk])list=[];else list=orders[String(mth)][wk];}
  if(list.length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  var pj=SUM_DATA.pj[pi];var t=wk===-1?(pj+" - Month "+mth+" (All Weeks)"):(pj+" - Month "+mth+" W"+(wk+1));
  buildOrdersHtml(list,pj,t,false);
}
function showOTDR(pi,mkey){
  var orders=ODR[String(pi)];
  if(!orders||!orders[mkey]||orders[mkey].length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  var pj=SUM_DATA.pj[pi];var t=pj+" - OTDR "+mkey;buildOrdersHtml(orders[mkey],pj,t,false);
}
function showOTDRAll(){var mkey='''+str(m1)+'''_pd',list=[];for(var pi=0;pi<SUM_DATA.pj.length;pi++){var o=ODR[String(pi)];if(!o||!o[mkey])continue;for(var i=0;i<o[mkey].length;i++)list.push([SUM_DATA.pj[pi]].concat(o[mkey][i]));}
  if(list.length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  buildOrdersHtml(list,"","All Projects - OTDR "+mkey,true);
}
function closeModal(){document.getElementById("orderModal").style.display="none";}
function showOrdersAll(mth,wk){
  var list=[];for(var pi=0;pi<SUM_DATA.pj.length;pi++){
    var orders=NAO[String(pi)],ol;
    if(mth==="sh"){if(!orders||!orders["sh"])continue;ol=orders["sh"];}
    else if(wk===-1||wk===-2){if(!orders||!orders["tot"]||!orders["tot"][String(mth)])continue;ol=orders["tot"][String(mth)];}
    else{if(!orders||!orders[String(mth)]||!orders[String(mth)][wk])continue;ol=orders[String(mth)][wk];}
    for(var i=0;i<ol.length;i++)list.push([SUM_DATA.pj[pi]].concat(ol[i]));
  }
  if(list.length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  var t=mth==="sh"?"All Projects - Shipped":(wk===-1||wk===-2)?("All Projects - Month "+mth+" (Total)"):("All Projects - Month "+mth+" W"+(wk+1));
  buildOrdersHtml(list,"",t,true);
}
function exportPopup(){
  if(!gPopupData||gPopupData.length===0)return;
  var BOM=String.fromCharCode(0xFEFF),NL=String.fromCharCode(10);
  var csv=BOM+gPopupCols.join(",")+NL;
  gPopupData.forEach(function(r){csv+=r.map(function(v){var s=String(v||"");if(s.indexOf(",")>=0||s.indexOf('"')>=0||s.indexOf(NL)>=0)s='"'+s.replace(/"/g,'""')+'"';return s;}).join(",")+NL;});
  var b=new Blob([csv],{type:"text/csv;charset=utf-8"});var a=document.createElement("a");a.href=URL.createObjectURL(b);a.download="NAI_Orders_WK"+SUM_DATA.wk+".csv";a.click();
}
window.onclick=function(e){if(e.target==document.getElementById("orderModal"))closeModal();};
</script>'''

def _build_dashboard(sd, WK_ID, MN1, MN2, MN3, WK1, WK2, WK3, PROJECTS, oa, ot, os_, do_, dc_,
                     real_25, rs, mta, mtf, M1, M2, M3, am1, am2, am3, fm1, fm2, fm3, cr_total, JS):
    N=len(PROJECTS); TW=WK1+WK2+WK3
    TMP=os.path.join(os.path.dirname(os.path.abspath(__file__)),'Penang_Chart_Dashboard_WK0630.html')
    with open(TMP,'r',encoding='utf-8') as f: html=f.read()
    # Compute D.os from otdr_stat (25-element, extract weekly data)
    os_arr=[]
    for w in range(WK1):
        idx=1+w
        v=sd['otdr_stat'][idx] if idx<len(sd['otdr_stat']) else ''
        os_arr.append(str(round(float(v))) if v!='' and v is not None else '')
    for w in range(WK2):
        idx=WK1+3+w
        v=sd['otdr_stat'][idx] if idx<len(sd['otdr_stat']) else ''
        os_arr.append(str(round(float(v))) if v!='' and v is not None else '')
    for w in range(WK3):
        idx=WK1+3+WK2+3+w
        v=sd['otdr_stat'][idx] if idx<len(sd['otdr_stat']) else ''
        os_arr.append(str(round(float(v))) if v!='' and v is not None else '')
    DAT=json.dumps({
        'pj':PROJECTS,'cr':sd['cr'],'nai':sd['nai'],'otdr':sd['otdr'],
        'ct':sd['cr_tot'],'nt':sd['nai_tot'],'ot':sd['otdr_tot'],
        'mfs':sd['mfs'],'mt':sd.get('mfs_tot',sd['mfs'][0] if sd['mfs'] else [0]*20),
        'mta':sd.get('mta',[0]*19),'mtf':sd.get('mtf',[0]*19),
        'wk':WK_ID,'do':[[0]*TW for _ in range(N)],'dc':[[0]*TW for _ in range(N)],'os':os_arr})
    html=re.sub(r'var D = \{.*?\};','var D = '+DAT+';',html,flags=re.DOTALL)
    html=html.replace('WK0629','WK'+WK_ID); html=html.replace('WK0630','WK'+WK_ID)
    html=html.replace('<div class="hb">WK'+WK_ID+'</div>',
        '<a href="/sum" style="margin-right:12px;padding:5px 12px;background:#1a237e;color:#fff;text-decoration:none;border-radius:4px;font-size:12px;display:inline-block">Sum Table</a><div class="hb">WK'+WK_ID+'</div>')
    return html
