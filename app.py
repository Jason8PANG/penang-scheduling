#!/usr/bin/env python3
"""Flask — dynamic Sum + Dashboard: direct DB query -> original UI"""
import csv, io
from flask import Flask, Response
from engine import build_all, conn_db, fetch_rows, get_latest_ds

app = Flask(__name__)

@app.route('/')
def index():
    s, d = build_all()
    return d

@app.route('/sum')
def sum_page():
    s, d = build_all()
    return s

@app.route('/export/mysql')
def export_mysql():
    ds = get_latest_ds()
    rows = fetch_rows(ds)
    if not rows:
        return 'No data', 404
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Site','Order','Order_Date','Line','Item','Due_Date','Request_Date',
                 'Project_code','Sales_price','Sales_amount','Source_Number','FK_date',
                 'pick_up_date','FG_stock','CR_Month','CR_WK','MFS_TYPE','MFS_MTH','MFS_WK',
                 'NAI_MTH','NAI_WK','OTDR_MTH','OTDR_WK','OTDR_ACCU_MTH','OTDR_ACCU_WK',
                 'Real_Production_MTH','Real_Production_WK','Data_Source'])
    for r in rows:
        cw.writerow(r[1:29])
    return Response(si.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=mysql_export.csv'})

if __name__ == '__main__':
    print('Penang Scheduling (real-time DB -> original UI)')
    print('  http://0.0.0.0:8080')
    app.run(host='0.0.0.0', port=8080, debug=False)
