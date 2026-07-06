"""Core builder: query MySQL dynamically, generate Sum + Dashboard HTML"""
import os, re, json, datetime, calendar, io, base64
import pymysql, openpyxl

import db_config

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = {}  # {wk_id: {'sum': html, 'dashboard': html, 'updated': ts}}

MON = {1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',
       7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}

def get_latest_data_source():
    """Query DB for the latest Data_Source value"""
    cfg = db_config.DB_CONFIG
    conn = pymysql.connect(**cfg)
    cur = conn.cursor()
    cur.execute(f'SELECT DISTINCT Data_Source FROM covswo_data ORDER BY Data_Source DESC LIMIT 1')
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row: return None
    return row[0]

def fetch_rows(data_source):
    """Fetch all rows for a given Data_Source"""
    cfg = db_config.DB_CONFIG
    tbl = db_config.TABLE_NAME
    conn = pymysql.connect(**cfg)
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM {tbl} WHERE Data_Source=%s AND Source_Type=%s', (data_source, 'Job'))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

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
    if v is None or v=='': return ''
    if isinstance(v,(int,float)):
        if v==0 and not isinstance(v,bool): return ''
        return f'{v:,.0f}' if abs(v)>=1000 else str(int(v))
    return str(v)

def build_all(ds=None):
    """Build Sum HTML + Dashboard HTML for the given (or latest) Data_Source"""
    if ds is None:
        ds = get_latest_data_source()
    if not ds:
        return '<h1>No data available</h1>', '<h1>No data available</h1>'

    m = re.search(r'WK(\d{4,8})', ds)
    WK_ID = m.group(1) if m else '0000'
    CUR_MTH = int(WK_ID[:2])
    now = datetime.datetime.now()
    CUR_YEAR = now.year
    if CUR_MTH <= now.month - 6: CUR_YEAR += 1
    M1, M2, M3 = CUR_MTH, CUR_MTH+1, CUR_MTH+2
    if M2>12: M2-=12; M3-=12
    if M3>12: M3-=12

    def mwks(y,m):
        c=calendar.Calendar()
        return sum(1 for w in c.monthdayscalendar(y,m) if any(d>0 for d in w))
    y1=CUR_YEAR; y2=y1+(1 if M3<=M1 else 0); y3=y2
    WK1=mwks(y1,M1); WK2=mwks(y2,M2); WK3=mwks(y3,M3)
    CUTOFF=datetime.datetime(y1,M1,1)
    CUTOFF_SEP=datetime.datetime(y3+1 if M3==12 else y3,1 if M3==12 else M3+1,1)
    MN1,MN2,MN3=MON[M1],MON[M2],MON[M3]
    TW=WK1+WK2+WK3
    w1=[f'W{i+1}' for i in range(WK1)]
    w2=[f'W{i+1}' for i in range(WK2)]
    w3=[f'W{i+1}' for i in range(WK3)]

    rows = fetch_rows(ds)  # list of tuples
    print(f'  Fetched {len(rows)} rows')

    # WIP data
    wip_cfg=dict(db_config.DB_CONFIG)
    wip_cfg['database']='wiptrack'
    stations=[]; stn_next={}; wip_exc={}; wip_exc_resolved={}; wip_pr={}
    try:
        wip_conn=pymysql.connect(**wip_cfg)
        wip_cur=wip_conn.cursor()
        wip_cur.execute("SELECT Station FROM site_station WHERE SiteRef='NAIGROUP_PROD_410' ORDER BY id")
        stations=[r[0] for r in wip_cur.fetchall()]
        stn_next={stations[i]:stations[i+1] for i in range(len(stations)-1)}
        wip_cur.execute("SELECT Job,Station,description,start_time,end_time FROM wip_exceptions WHERE SiteRef='NAIGROUP_PROD_410'")
        for j,s,d,st,et in wip_cur.fetchall():
            if et is None: wip_exc[j]=[s,d,st,None]
            else: wip_exc_resolved[j]=[s,d,st,et]
        wip_cur.execute("SELECT Job,Station,CompleteDate FROM production_records WHERE SiteRef='NAIGROUP_PROD_410' ORDER BY CompleteDate DESC")
        for j,s,cd in wip_cur.fetchall():
            if j not in wip_pr: wip_pr[j]=[s,cd]
        wip_cur.close(); wip_conn.close()
    except Exception as e:
        print(f'  WIP load failed: {e}')

    FINAL_STN='包装 Package'
    def get_wip_status(src_no):
        job=f'{src_no}-0000'
        if job not in wip_pr: return ('','','')
        cur_stn,comp_dt=wip_pr[job]; cur_stn=cur_stn or ''; cd_str=str(comp_dt)[:19] if comp_dt else ''
        if cur_stn==FINAL_STN: return (cur_stn,'',cd_str)
        if job in wip_exc: s,d,st,_=wip_exc[job]; return (s or '',d or '',str(st)[:19] if st else '')
        if job in wip_exc_resolved: s,_,st,et=wip_exc_resolved[job]; return (stn_next.get(s,''),'',str(et)[:19] if et else '')
        return (stn_next.get(cur_stn,''),'',cd_str)

    def normalize_pj(s):
        parts=s.strip().split()
        if len(parts)>=2:
            company=' '.join(parts[:-1])
            suffix=parts[-1].lower()
            if suffix=='copper': return company+' Copper'
            if suffix in ('semi-conductor','semiconductor'): return company+' Semi-conductor'
        return s.strip()

    # Dynamic PROJECTS
    raw_pjs={}
    for row in rows:
        v=row[8]
        if v:
            s=str(v).strip()
            if 'copper' in s.lower() or 'semi' in s.lower():
                raw_pjs[normalize_pj(s)]=True
    PROJECTS=sorted(raw_pjs.keys())
    N=len(PROJECTS)

    # Accumulators
    TW=WK1+WK2+WK3
    cr={p:{'pd':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai={p:{'sh':0,M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mfs={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mfa={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    mff={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    otdr={p:{f'{M1}_pd':0,M1:[0]*WK1,f'{M1}_adv':0,f'{M2}_pd':0,M2:[0]*WK2,f'{M2}_adv':0,f'{M3}_pd':0,M3:[0]*WK3,f'{M3}_adv':0} for p in PROJECTS}
    otdd={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    real={p:{M1:[0]*WK1,M2:[0]*WK2,M3:[0]*WK3} for p in PROJECTS}
    nai_orders={p:{M1:{wk:[] for wk in range(WK1)},M2:{wk:[] for wk in range(WK2)},M3:{wk:[] for wk in range(WK3)},"sh":[]} for p in PROJECTS}
    otdr_orders={p:{f'{M1}_pd':[],f'{M2}_pd':[],f'{M3}_pd':[]} for p in PROJECTS}

    # Column mapping (0-indexed)
    COL_TP = 1   # Order
    COL_DT = 5   # Due_Date  
    COL_RDT = 6  # Request_Date
    COL_PC = 8   # Project_code
    COL_SA = 10  # Sales_amount
    COL_SN = 11  # Source_Number
    COL_CM = 15  # CR_Month
    COL_CW = 16  # CR_WK
    COL_MT = 17  # MFS_TYPE
    COL_MM = 18  # MFS_MTH
    COL_MW = 19  # MFS_WK
    COL_NM = 20  # NAI_MTH
    COL_NW = 21  # NAI_WK
    COL_OM = 22  # OTDR_MTH
    COL_OW = 23  # OTDR_WK
    COL_RM = 26  # Real_Production_MTH
    COL_RW = 27  # Real_Production_WK
    COL_DS = 28  # Data_Source

    for row in rows:
        ord_no = str(row[COL_TP] or '')
        pj = normalize_pj(str(row[COL_PC] or ''))
        if pj not in PROJECTS: continue
        sa = sf(row[COL_SA] if len(row)>COL_SA else 0)
        cmi = si(row[COL_CM] if len(row)>COL_CM else None)
        cwi = si(row[COL_CW] if len(row)>COL_CW else None)
        cw_l = str(row[COL_CW] or '').strip().lower() if len(row)>COL_CW else ''
        if cw_l in ('backlog','pass due'): cr[pj]['pd']+=sa
        elif cmi==M1 and cwi and 1<=cwi<=WK1: cr[pj][M1][cwi-1]+=sa
        elif cmi==M2 and cwi and 1<=cwi<=WK2: cr[pj][M2][cwi-1]+=sa
        elif cmi==M3 and cwi and 1<=cwi<=WK3: cr[pj][M3][cwi-1]+=sa

        # MFS
        mmi=si(row[COL_MM] if len(row)>COL_MM else None)
        mwi=si(row[COL_MW] if len(row)>COL_MW else None)
        mt_l=str(row[COL_MT] or '').strip().lower() if len(row)>COL_MT else ''
        if mmi==M1 and mwi and 1<=mwi<=WK1:
            mfs[pj][M1][mwi-1]+=sa
            if mt_l=='actual': mfa[pj][M1][mwi-1]+=sa
            elif mt_l=='forecast': mff[pj][M1][mwi-1]+=sa
        elif mmi==M2 and mwi and 1<=mwi<=WK2:
            mfs[pj][M2][mwi-1]+=sa; mfa[pj][M2][mwi-1]+=sa if mt_l=='actual' else 0; mff[pj][M2][mwi-1]+=sa if mt_l=='forecast' else 0 
            if mt_l=='actual': mfa[pj][M2][mwi-1]+=sa
            elif mt_l=='forecast': mff[pj][M2][mwi-1]+=sa
        elif mmi==M3 and mwi and 1<=mwi<=WK3:
            mfs[pj][M3][mwi-1]+=sa
            if mt_l=='actual': mfa[pj][M3][mwi-1]+=sa
            elif mt_l=='forecast': mff[pj][M3][mwi-1]+=sa

        # NAI
        nw_l=str(row[COL_NW] or '').strip().lower() if len(row)>COL_NW else ''
        nwi=si(row[COL_NW] if len(row)>COL_NW else None)
        nmi=si(row[COL_NM] if len(row)>COL_NM else None)
        src_no=str(row[COL_SN] or '') if len(row)>COL_SN else ''
        req_dt=str(row[COL_RDT] or '')[:10] if len(row)>COL_RDT else ''
        due_dt=str(row[COL_DT] or '')[:10] if len(row)>COL_DT else ''
        stn,exc,st_time=get_wip_status(src_no)
        ord_info=(str(ord_no),src_no,round(sa,2),req_dt[:10],due_dt[:10],stn,exc,st_time)
        if nw_l=='shipped':
            nai[pj]['sh']+=sa; nai_orders[pj]["sh"].append(ord_info)
        elif nmi==M1 and nwi and 1<=nwi<=WK1: nai[pj][M1][nwi-1]+=sa; nai_orders[pj][M1][nwi-1].append(ord_info)
        elif nmi==M2 and nwi and 1<=nwi<=WK2: nai[pj][M2][nwi-1]+=sa; nai_orders[pj][M2][nwi-1].append(ord_info)
        elif nmi==M3 and nwi and 1<=nwi<=WK3: nai[pj][M3][nwi-1]+=sa; nai_orders[pj][M3][nwi-1].append(ord_info)

        # OTDR
        omi=si(row[COL_OM] if len(row)>COL_OM else None)
        owi=si(row[COL_OW] if len(row)>COL_OW else None)
        ow_l=str(row[COL_OW] or '').strip() if len(row)>COL_OW else ''
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

        # OTDR Due/M3 check
        oami=si(row[24] if len(row)>24 else None); oawi=si(row[25] if len(row)>25 else None)
        if oami==M1 and oawi and 1<=oawi<=WK1: otdd[pj][M1][oawi-1]+=sa
        elif oami==M2 and oawi and 1<=oawi<=WK2: otdd[pj][M2][oawi-1]+=sa
        elif oami==M3 and oawi and 1<=oawi<=WK3: otdd[pj][M3][oawi-1]+=sa

        rmi=si(row[COL_RM] if len(row)>COL_RM else None); rwi=si(row[COL_RW] if len(row)>COL_RW else None)
        if rmi==M1 and rwi and 1<=rwi<=WK1: real[pj][M1][rwi-1]+=sa
        elif rmi==M2 and rwi and 1<=rwi<=WK2: real[pj][M2][rwi-1]+=sa
        elif rmi==M3 and rwi and 1<=rwi<=WK3: real[pj][M3][rwi-1]+=sa

    # Remove empty projects
    active_pjs=[]
    for p in PROJECTS:
        cr_t=cr[p]['pd']+sum(cr[p][M1])+sum(cr[p][M2])+sum(cr[p][M3])
        nai_t=nai[p]['sh']+sum(nai[p][M1])+sum(nai[p][M2])+sum(nai[p][M3])
        mfs_t=sum(mfs[p][M1])+sum(mfs[p][M2])+sum(mfs[p][M3])
        if cr_t>0 or nai_t>0 or mfs_t>0: active_pjs.append(p)
    PROJECTS=active_pjs; N=len(PROJECTS)

    # Build arrays
    ca=[]
    for p in PROJECTS:
        d=cr[p]; ca.append([d['pd']]+d[M1]+[d['pd']+sum(d[M1])]+d[M2]+[sum(d[M2])]+d[M3]+[sum(d[M3])])
    ct=[sum(ca[i][j] for i in range(N)) for j in range(len(ca[0]))]

    ma=[]
    for p in PROJECTS:
        d=mfs[p]; ma.append(d[M1]+[sum(d[M1])]+d[M2]+[sum(d[M2])]+d[M3]+[sum(d[M3])])
    mt_=[sum(ma[i][j] for i in range(N)) for j in range(len(ma[0]))]

    na=[]
    for p in PROJECTS:
        d=nai[p]; na.append([d['sh']]+d[M1]+[sum(d[M1])]+d[M2]+[sum(d[M2])]+d[M3]+[sum(d[M3])])
    nt=[sum(na[i][j] for i in range(N)) for j in range(len(na[0]))]

    oa=[]
    for p in PROJECTS:
        d=otdr[p]
        oa.append([d[f'{M1}_pd']]+d[M1]+[d[f'{M1}_adv']]+[sum(d[M1])+d[f'{M1}_adv']]+[d[f'{M2}_pd']]+d[M2]+[d[f'{M2}_adv']]+[sum(d[M2])+d[f'{M2}_adv']]+[d[f'{M3}_pd']]+d[M3]+[d[f'{M3}_adv']]+[sum(d[M3])+d[f'{M3}_adv']])
    ot=[sum(oa[i][j] for i in range(N)) for j in range(len(oa[0]))]

    otdr_pd_totals=[sum(otdr[p][f'{M1}_pd'] for p in PROJECTS),sum(otdr[p][f'{M2}_pd'] for p in PROJECTS),sum(otdr[p][f'{M3}_pd'] for p in PROJECTS)]
    oa_pd=[sum(otdr[p][f'{M1}_pd'] for p in PROJECTS),sum(otdr[p][f'{M2}_pd'] for p in PROJECTS),sum(otdr[p][f'{M3}_pd'] for p in PROJECTS)]

    ott=[sum(otr[p][f'{M1}_pd']+sum(otr[p][M1])+otr[p][f'{M1}_adv'] for p in PROJECTS) for otr in [otdr]][0]; ott=[0]*len(oa[0])
    for j in range(len(oa[0])):
        v=0
        for p in PROJECTS:
            idx=j
            if idx==0: v+=otdr[p][f'{M1}_pd']
            elif 1<=idx<=WK1: v+=otdr[p][M1][idx-1]
            elif idx==WK1+1: v+=otdr[p][f'{M1}_adv']
            elif idx==WK1+2: v=0  # M1 total, skip
            elif WK1+3<=idx<=WK1+2+WK2: v+=otdr[p][M2][idx-(WK1+3)]
            elif idx==WK1+WK2+3: v+=otdr[p][f'{M2}_adv']
            elif idx==WK1+WK2+4: v=0
            elif WK1+WK2+5<=idx<=WK1+WK2+4+WK3: v+=otdr[p][M3][idx-(WK1+WK2+5)]
            elif idx==WK1+WK2+WK3+5: v+=otdr[p][f'{M3}_adv']
        ott[j]=v
    os_=['']*len(ott)
    for j in range(len(ott)):
        if j in (WK1+2, WK1+WK2+4): continue  # total columns
        if ott[j] and ct and j<len(ct) and ct[j]>0: os_[j]=min(round(ott[j]/ct[j]*100),100)

    real_25=['']*25
    for w in range(WK1):
        v=sum(real[p][M1][w] for p in PROJECTS)
        if v>0: real_25[w]=sf_int(v)
    for w in range(WK2):
        v=sum(real[p][M2][w] for p in PROJECTS)
        if v>0: real_25[5+w]=sf_int(v)
    for w in range(WK3):
        v=sum(real[p][M3][w] for p in PROJECTS)
        if v>0: real_25[11+w]=sf_int(v)

    rs=['']*len(real_25)
    for w in range(WK1):
        ci=1+w
        if ci<len(ct) and ct[ci]>0 and real_25[w]!='' and real_25[w]>0: rs[w]=min(round(real_25[w]/ct[ci]*100),100)
    for w in range(WK2):
        ci=4+WK1+w
        if ci<len(ct) and ct[ci]>0 and real_25[5+w]!='' and real_25[5+w]>0: rs[5+w]=min(round(real_25[5+w]/ct[ci]*100),100)
    for w in range(WK3):
        ci=6+WK1+WK2+1+w
        if ci<len(ct) and ct[ci]>0 and real_25[11+w]!='' and real_25[11+w]>0: rs[11+w]=min(round(real_25[11+w]/ct[ci]*100),100)

    cr_total=sf_int(sum(cr[p]['pd'] for p in PROJECTS)+sum(sum(cr[p][M1]) for p in PROJECTS)+sum(sum(cr[p][M2]) for p in PROJECTS)+sum(sum(cr[p][M3]) for p in PROJECTS))

    # ── Build Sum HTML ──
    am1=sf_int(sum(sum(mfa[p][M1]) for p in PROJECTS))
    am2=sf_int(sum(sum(mfa[p][M2]) for p in PROJECTS))
    am3=sf_int(sum(sum(mfa[p][M3]) for p in PROJECTS))
    fm1=sf_int(sum(sum(mff[p][M1]) for p in PROJECTS))
    fm2=sf_int(sum(sum(mff[p][M2]) for p in PROJECTS))
    fm3=sf_int(sum(sum(mff[p][M3]) for p in PROJECTS))
    mta=[0]*19; mtf=[0]*19
    for w in range(WK1): mta[w]=sf_int(sum(mfa[p][M1][w] for p in PROJECTS)); mtf[w]=sf_int(sum(mff[p][M1][w] for p in PROJECTS))
    mta[5]=am1; mtf[5]=fm1
    for w in range(WK2): mta[6+w]=sf_int(sum(mfa[p][M2][w] for p in PROJECTS)); mtf[6+w]=sf_int(sum(mff[p][M2][w] for p in PROJECTS))
    mta[12]=am2; mtf[12]=fm2
    for w in range(WK3): mta[13+w]=sf_int(sum(mfa[p][M3][w] for p in PROJECTS)); mtf[13+w]=sf_int(sum(mff[p][M3][w] for p in PROJECTS))
    mta[18]=am3; mtf[18]=fm3

    do_,dc_=[],[]
    for p in PROJECTS:
        dr_,dcr_=[],[]; cd=cr[p]; od=otdd[p]
        for w in range(TW):
            if w<WK1: dr_.append(sf_int(od[M1][w])); dcr_.append(sf_int(cd[M1][w]))
            elif w<WK1+WK2: dr_.append(sf_int(od[M2][w-WK1])); dcr_.append(sf_int(cd[M2][w-WK1]))
            else: dr_.append(sf_int(od[M3][w-WK1-WK2])); dcr_.append(sf_int(cd[M3][w-WK1-WK2]))
        do_.append(dr_); dc_.append(dcr_)

    # Build orders JSON
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

    sd_data={
        'pj':PROJECTS,'WK1':WK1,'WK2':WK2,'WK3':WK3,'wk':WK_ID,
        'cr':[[sf_int(v) for v in r] for r in ca],
        'cr_tot':[sf_int(v) for v in ct],
        'mfs':[[sf_int(v) for v in r] for r in ma],
        'mfs_tot':[sf_int(v) for v in mt_],
        'nai':[[sf_int(v) for v in r] for r in na],
        'nai_tot':[sf_int(v) for v in nt],
        'otdr':[[sf_int(v) for v in r] for r in oa],
        'otdr_tot':[sf_int(v) for v in ot],
        'otdr_stat':os_,'cr_total':cr_total,
        'real_total':real_25,'real_stat':rs,
        'do':do_,'dc':dc_,
        'act_m1':am1,'act_m2':am2,'act_m3':am3,'fest_m1':fm1,'fest_m2':fm2,'fest_m3':fm3,
        'mta':mta,'mtf':mtf
    }
    sd_json=json.dumps(sd_data)
    nao_json=json.dumps(nai_orders_json)
    odr_json=json.dumps(otdr_orders_json)

    # ── Build Sum HTML ──
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
                tot_cols={0,WK1+1,WK1+WK2+2,WK1+WK2+WK3+3}
                if clickable and ci>0 and ci not in tot_cols:
                    if 1<=ci<=WK1: m_,w_=str(M1),ci-1
                    elif WK1+2<=ci<=WK1+1+WK2: m_,w_=str(M2),ci-(WK1+2)
                    elif WK1+WK2+3<=ci<=WK1+WK2+WK3+2: m_,w_=str(M3),ci-(WK1+WK2+3)
                    else: m_,w_=None,None
                    if m_ is not None: h+=f'<td class="d dc" onclick="showOrders({i},{m_},{w_})">{fmtv(v)}</td>'
                    else: h+=f'<td class="d">{fmtv(v)}</td>'
                elif clickable and nai_mode and ci in tot_cols:
                    if ci==0: m_=None
                    elif ci==WK1+1: m_=str(M1)
                    elif ci==WK1+WK2+2: m_=str(M2)
                    elif ci==WK1+WK2+WK3+3: m_=str(M3)
                    else: m_=None
                    if m_: h+=f'<td class="d dc" onclick="showOrders({i},{m_},-1)">{fmtv(v)}</td>'
                    else: h+=f'<td class="d">{fmtv(v)}</td>'
                else: h+=f'<td class="d">{fmtv(v)}</td>'
            h+='</tr>'
        if nai_mode:
            h+=f'<tr class=ttl><td class=pj>Total</td>'
            for ci,v in enumerate(tot):
                if ci==0: m_,w_=None,None
                elif 1<=ci<=WK1: m_,w_=str(M1),ci-1
                elif ci==WK1+1: m_,w_=str(M1),-1
                elif WK1+2<=ci<=WK1+1+WK2: m_,w_=str(M2),ci-(WK1+2)
                elif ci==WK1+WK2+2: m_,w_=str(M2),-1
                elif WK1+WK2+3<=ci<=WK1+WK2+WK3+2: m_,w_=str(M3),ci-(WK1+WK2+3)
                elif ci==WK1+WK2+WK3+3: m_,w_=str(M3),-1
                else: m_,w_=None,None
                if m_ and w_ is not None: h+=f'<td class="d dc" onclick="showOrdersAll({m_},{w_})">{fmtv(v)}</td>'
                else: h+=f'<td class="d">{fmtv(v)}</td>'
            h+='</tr></table>'
        else:
            h+=f'<tr class=ttl><td class=pj>Total</td>'+''.join(f'<td class=d>{fmtv(v)}</td>' for v in tot)+'</tr></table>'
        return h

    hdr=f'<div class="hdr"><h1 style="margin:0">Penang Production Scheduling &mdash; WK{WK_ID}</h1></div>'
    H='<!DOCTYPE html><html lang=en><head><meta charset=UTF-8><title>Penang Scheduling WK{}</title><style>body{{font-family:Segoe UI,sans-serif;font-size:11px;margin:20px;background:#f5f5f5}}h1{{color:#1a237e;font-size:20px}}table{{border-collapse:collapse;margin-bottom:15px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}td,th{{border:1px solid #ccc;padding:3px 6px;text-align:center;vertical-align:middle}}.pj{{text-align:left;font-weight:600;background:#fff;min-width:140px}}.d{{background:#fff;min-width:50px}}.dc{{cursor:pointer;text-decoration:underline;color:#1565c0;font-weight:600}}.dc:hover{{background:#bbdefb}}.tt{{text-align:center;font-weight:700;font-size:13px;color:#fff;background:#1a237e;padding:4px 10px}}.mh{{font-weight:700;font-size:10px;background:#e8eaf6;color:#1a237e;text-align:center}}.sh{{font-weight:600;font-size:10px;background:#f5f5f5;text-align:center}}.st{{font-weight:700;font-size:10px;background:#fff3e0;text-align:center;color:#e65100}}.pct{{color:#1565c0;font-weight:600}}.ttl td{{background:#e8eaf6;font-weight:700;color:#1a237e}}.btn{{background:#1a237e;color:#fff;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:12px;border:none}}.hdr{{display:flex;align-items:center;margin-bottom:10px}}'.format(WK_ID)

    H+=hdr
    H+=f'<p style="color:#666">{datetime.datetime.now().strftime("%Y-%m-%d %H:%M")} | {MN1}({WK1}w)/{MN2}({WK2}w)/{MN3}({WK3}w)</p>'
    H+=tbl(f'Customer Request (WK{WK_ID})',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Pass Due',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ca,ct)
    H+=tbl('Material FK status',1+WK1+1+WK2+1+WK3+1,[('Project code',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],ma,mt_)
    H+=tbl('NAI Production (Commit)',1+1+WK1+1+WK2+1+WK3+1,[('Project code',1),('Shipped',1),(MN1,WK1+1),(MN2,WK2+1),(MN3,WK3+1)],na,nt,clickable=True,nai_mode=True)

    otr=otdr
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
            if ci==0:
                if v and isinstance(v,(int,float)) and sf_int(v)!=0:
                    H+=f'<td class="d dc" onclick="showOTDR({i},\'{M1}_pd\')">{fmtv(v)}</td>'
                else: H+=f'<td class=d>{fmtv(v)}</td>'
            else: H+=f'<td class=d>{fmtv(v)}</td>'
        H+='</tr>'
    H+='<tr class=ttl><td class=pj>Total</td>'
    for ci,v in enumerate(ot):
        if ci==0 and v and isinstance(v,(int,float)) and sf_int(v)!=0:
            H+=f'<td class="d dc" onclick="showOTDRAll()">{fmtv(v)}</td>'
        else: H+=f'<td class=d>{fmtv(v)}</td>'
    H+='</tr></table>'

    # Summary
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
        for wc in [WK1,WK2,WK3]: wks.extend(data[off:off+wc]); off+=wc+3
        hx=f'<tr class=rttl><td class=pj style="background:{clr};color:#1565c0">{label}</td>'
        for v in wks:
            s=f'style="background:{clr}"'
            if v!='' and isinstance(v,int) and v>0:
                hx+=f'<td class="d pct" {s}>{v}%</td>' if 'Status' in label else f'<td class=d {s}>{fmtv(v)}</td>'
            else: hx+=f'<td class=d {s}>{fmtv(v)}</td>'
        return hx+'</tr>'
    H+=sum_row('OTDR Total',ott,'#e3f2fd')
    H+=sum_row('OTDR Status',os_,'#e3f2fd')
    H+=sum_row('Real Total',real_25,'#fff3e0')
    H+=sum_row('Real Status',rs,'#fff3e0')
    H+='</table>'

    H+=f'<script>var SUM_DATA={sd_json};var NAO={nao_json};var ODR={odr_json};</script>'
    H+='<script>'+_BUILD_JS+'</script></body></html>'

    sum_html = H

    # ── Build Dashboard HTML ──
    dash_html = _build_dashboard(sd_data, WK_ID, MN1, MN2, MN3, WK1, WK2, WK3, PROJECTS, oa, ot, os_, do_, dc_,
                                real_25, rs, mta, mtf, M1, M2, M3, am1, am2, am3, fm1, fm2, fm3, cr_total, _BUILD_JS)

    return sum_html, dash_html


_BUILD_JS = '''
var gPopupTitle='',gPopupCols=[],gPopupData=[];
function buildOrdersHtml(list,pj,t,isMulti){
  gPopupTitle=t;
  gPopupCols=['Order','Source_Number','Request_Date','Due_Date','Sales_amount','Station','Exception'];
  var pc=isMulti?['Project']:[];gPopupCols=pc.concat(gPopupCols);
  var h="<h3 style='margin-top:0'>"+t+"</h3><table><thead><tr>"+gPopupCols.map(function(c){return '<th>'+c+'</th>';}).join('')+'</tr></thead><tbody>';
  var rows=[];
  list.forEach(function(o){
    var off=isMulti?1:0;
    var exc=o[off+6]||'',st_=o[off+7]||'';
    var es=exc&&st_?(exc+' / '+st_):(exc||st_);
    var row=[o[off],o[off+1],o[off+3],o[off+4],o[off+2],o[off+5]||'',es];
    if(isMulti)row=[o[0]].concat(row);
    rows.push(row);
  });
  gPopupData=rows;
  var tot=0;
  rows.forEach(function(r){
    var amt=r[pc.length+4];tot+=Number(amt)||0;
    h+='<tr>'+r.map(function(v,i){var isNum=(i===pc.length+4);return '<td'+(isNum?' style="text-align:right"':'')+'>'+(isNum?Number(v).toLocaleString():v||'')+'</td>';}).join('')+'</tr>';
  });
  h+='<tr style="font-weight:700;background:#e8eaf6"><td colspan="'+(gPopupCols.length-1)+'">'+list.length+' order(s)</td><td style="text-align:right">$'+Number(tot).toLocaleString()+'</td></tr></tbody></table>';
  document.getElementById("orderList").innerHTML=h;document.getElementById("orderModal").style.display="block";
}
function showOrders(pi,mth,wk){
  var orders=NAO[String(pi)],list;
  if(wk===-1){if(!orders||!orders['tot']||!orders['tot'][String(mth)])list=[];else list=orders['tot'][String(mth)];}
  else{if(!orders||!orders[String(mth)]||!orders[String(mth)][wk])list=[];else list=orders[String(mth)][wk];}
  if(list.length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  var pj=SUM_DATA.pj[pi];
  var t=wk===-1?(pj+" - Month "+mth+" (All Weeks)"):(pj+" - Month "+mth+" W"+(wk+1));
  buildOrdersHtml(list,pj,t,false);
}
function showOTDR(pi,mkey){
  var orders=ODR[String(pi)];
  if(!orders||!orders[mkey]||orders[mkey].length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  var pj=SUM_DATA.pj[pi];var t=pj+" - OTDR "+mkey;
  buildOrdersHtml(orders[mkey],pj,t,false);
}
function showOTDRAll(){
  var mkey="7_pd",list=[];
  for(var pi=0;pi<SUM_DATA.pj.length;pi++){
    var o=ODR[String(pi)];if(!o||!o[mkey])continue;
    for(var i=0;i<o[mkey].length;i++)list.push([SUM_DATA.pj[pi]].concat(o[mkey][i]));
  }
  if(list.length===0){document.getElementById("orderList").innerHTML="<p style='color:#999'>No order details available</p>";document.getElementById("orderModal").style.display="block";return;}
  buildOrdersHtml(list,"","All Projects - OTDR "+mkey,true);
}
function closeModal(){document.getElementById("orderModal").style.display="none";}
function showOrdersAll(mth,wk){
  var list=[];
  for(var pi=0;pi<SUM_DATA.pj.length;pi++){
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
'''


def _build_dashboard(sd, WK_ID, MN1, MN2, MN3, WK1, WK2, WK3, PROJECTS, oa, ot, os_, do_, dc_,
                     real_25, rs, mta, mtf, M1, M2, M3, am1, am2, am3, fm1, fm2, fm3, cr_total, JS):
    import io as _io
    N=len(PROJECTS); TW=WK1+WK2+WK3
    sd_json=json.dumps(sd)

    H='''
<!DOCTYPE html><html lang=en><head><meta charset=UTF-8><title>Penang Dashboard WK'''+WK_ID+'''</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<style>
body{font-family:Segoe UI,sans-serif;margin:20px;background:#f5f5f5}
h1{color:#1a237e;font-size:20px;margin-bottom:5px}
h2{color:#1a237e;font-size:16px;margin:20px 0 10px 0;border-bottom:2px solid #1a237e;padding-bottom:5px}
.chart-row{display:flex;flex-wrap:wrap;gap:15px;margin-bottom:20px}
.chart-box{flex:1 1 400px;background:#fff;padding:15px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.chart-box canvas{width:100%!important;max-height:320px}
table{border-collapse:collapse;margin-bottom:15px;box-shadow:0 1px 3px rgba(0,0,0,.1);width:auto}
td,th{border:1px solid #ccc;padding:3px 6px;text-align:center;vertical-align:middle;font-size:11px}
.pj{text-align:left;font-weight:600;background:#fff;min-width:120px}
.tt{text-align:center;font-weight:700;font-size:12px;color:#fff;background:#1a237e;padding:4px 10px}
.mh{font-weight:700;background:#e8eaf6;color:#1a237e}.sh{font-weight:600;background:#f5f5f5}
.d{background:#fff}.pct{color:#1565c0;font-weight:600}
.ttl td{background:#e8eaf6;font-weight:700;color:#1a237e}
.btn{background:#1a237e;color:#fff;padding:6px 16px;border:0;border-radius:4px;cursor:pointer;font-size:12px}
</style></head><body>
<h1>Penang Production Scheduling &mdash; WK'''+WK_ID+''' Dashboard</h1>
<p style=color:#666>'''+datetime.datetime.now().strftime("%Y-%m-%d %H:%M")+''' | Data auto-refreshed from MySQL</p>
<div class=chart-row>
<div class=chart-box><canvas id=crChart></canvas></div>
<div class=chart-box><canvas id=mfsChart></canvas></div>
</div>
<div class=chart-row>
<div class=chart-box><canvas id=naiChart></canvas></div>
<div class=chart-box><canvas id=otdrChart></canvas></div>
</div>
<div class=chart-row>
<div class=chart-box><canvas id=realPie></canvas></div>
<div class=chart-box><canvas id=summaryChart></canvas></div>
</div>
<h2>Project Data</h2>
<div id=projectTable></div>
<script>var SD='''+sd_json+''';</script>
<script>
var D=JSON.parse(SD);
var pj=D.pj,N=pj.length,WK1=D.WK1,WK2=D.WK2,WK3=D.WK3,TW=WK1+WK2+WK3;
var wklbl=[];
for(var i=0;i<WK1;i++)wklbl.push("W"+(i+1));
for(var i=0;i<WK2;i++)wklbl.push("W"+(i+1));
for(var i=0;i<WK3;i++)wklbl.push("W"+(i+1));
var col_to_wk={};
for(var i=0;i<TW;i++)col_to_wk[i]=wklbl[i];
var dw={labels:wklbl};

// CR chart
dw.crDatasets=[];
pj.forEach(function(p,pi){
  var vals=[];var off=1;
  for(var w=0;w<WK1;w++){vals.push(D.cr[pi][off+w]);}
  off=7;
  for(var w=0;w<WK2;w++){vals.push(D.cr[pi][off+w]);}
  off=14;
  for(var w=0;w<WK3;w++){vals.push(D.cr[pi][off+w]);}
  dw.crDatasets.push({label:p,data:vals,borderWidth:1,pointRadius:3});
});
new Chart(document.getElementById("crChart"),{type:"bar",data:{labels:wklbl,datasets:dw.crDatasets},options:{responsive:true,plugins:{legend:{labels:{font:{size:9}}},title:{display:true,text:"Customer Request (WK"+D.wk+")"}},scales:{x:{stacked:true},y:{stacked:true,beginAtZero:true}}}});

// MFS chart
var mfsLabels=[];for(var i=0;i<WK1;i++)mfsLabels.push("W"+(i+1));
var mfsActData=[];var mfsFctData=[];
for(var i=0;i<WK1;i++){mfsActData.push(D.act_m1?D.mta[i]||0:0);mfsFctData.push(D.fest_m1?D.mtf[i]||0:0);}
new Chart(document.getElementById("mfsChart"),{type:"bar",data:{labels:mfsLabels,datasets:[{label:"Actual",data:mfsActData,backgroundColor:"#4caf50"},{label:"Forecast",data:mfsFctData,backgroundColor:"#ff9800"}]},options:{responsive:true,plugins:{title:{display:true,text:"Material FK Status - "+"'''+MN1+'''"}},scales:{y:{beginAtZero:true}}}});

// NAI chart
var naiLabels=[];var naiData=[];
for(var i=0;i<N;i++){var tot=0;var off=1;for(var w=0;w<WK1;w++)tot+=D.nai[i][off+w];off=7;for(var w=0;w<WK2;w++)tot+=D.nai[i][off+w];off=14;for(var w=0;w<WK3;w++)tot+=D.nai[i][off+w];tot+=D.nai[i][0];if(tot>0){naiLabels.push(pj[i]);naiData.push(tot);}}
new Chart(document.getElementById("naiChart"),{type:"doughnut",data:{labels:naiLabels,datasets:[{data:naiData,backgroundColor:["#1565c0","#ffc107","#4caf50","#ff5722","#9c27b0","#00bcd4","#e91e63","#607d8b"]}]},options:{responsive:true,plugins:{title:{display:true,text:"NAI Production by Project"}}}});

// OTDR chart
var otdrLabels=[];var otdrData=[];
for(var i=0;i<N;i++){var v=D.otdr[i][0]||0;if(v>0){otdrLabels.push(pj[i]);otdrData.push(v);}}
new Chart(document.getElementById("otdrChart"),{type:"pie",data:{labels:otdrLabels,datasets:[{data:otdrData,backgroundColor:["#ff5722","#ffc107","#4caf50","#1565c0","#9c27b0","#00bcd4","#e91e63","#607d8b"]}]},options:{responsive:true,plugins:{title:{display:true,text:"OTDR Pass Due ("+"'''+str(M1)+'''+")"}}}});

// Real Production Summary
var realPieLabels=[];var realPieData=[];
var realWk=[];
for(var w=0;w<TW;w++){
  var v=D.real_total[w];
  if(v&&v!==""&&v>0){realPieLabels.push(wklbl[w]);realPieData.push(v);}
}
new Chart(document.getElementById("realPie"),{type:"bar",data:{labels:realPieLabels,datasets:[{label:"Real Production",data:realPieData,backgroundColor:"#1565c0"}]},options:{responsive:true,plugins:{title:{display:true,text:"Real Production by Week"}},scales:{y:{beginAtZero:true}}}});

// Summary chart
new Chart(document.getElementById("summaryChart"),{type:"line",data:{labels:wklbl,datasets:[{label:"Real Total",data:D.real_total.slice(0,TW),borderColor:"#1565c0",fill:false},{label:"OTDR Total",data:D.otdr_tot.slice(0,TW),borderColor:"#ff5722",fill:false}]},options:{responsive:true,plugins:{title:{display:true,text:"Real vs OTDR Comparison"}},scales:{y:{beginAtZero:true}}}});

// Project table
var th="<table><tr><th class=tt colspan=12>Project Summary</th></tr><tr><th class=mh>Project</th><th class=mh>CR Total</th><th class=mh>Pass Due</th><th class=mh>NAI Shipped</th><th class=mh>NAI Total</th><th class=mh>OTDR PD</th></tr>";
pj.forEach(function(p,pi){
  var crT=0;var crPd=D.cr[pi][0]||0;
  for(var j=1;j<D.cr[pi].length;j++)crT+=D.cr[pi][j]||0;
  var naiSh=D.nai[pi][0]||0;var naiTot=0;
  for(var j=1;j<D.nai[pi].length;j++)naiTot+=D.nai[pi][j]||0;naiTot+=naiSh;
  var otdrPd=D.otdr[pi][0]||0;
  th+="<tr><td class=pj>"+p+"</td><td class=d>$"+(crT+crPd).toLocaleString()+"</td><td class=d>$"+crPd.toLocaleString()+"</td><td class=d>$"+naiSh.toLocaleString()+"</td><td class=d>$"+naiTot.toLocaleString()+"</td><td class=d>$"+otdrPd.toLocaleString()+"</td></tr>";
});
th+="</table>";
document.getElementById("projectTable").innerHTML=th;
</script>
</body></html>'''
    return H
