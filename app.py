#!/usr/bin/env python3
"""Flask web service — auto-fetches latest DB data for Sum + Dashboard"""
import os, re, datetime, threading
from flask import Flask, send_file, abort
import penang_builder

app = Flask(__name__)
build_lock = threading.Lock()
cache = {'ds': None, 'sum': None, 'dash': None, 'updated': None}

def auto_build():
    """Check DB for latest Data_Source, rebuild if changed"""
    try:
        ds = penang_builder.get_latest_data_source()
        if ds is None:
            print('  No Data_Source in DB')
            return
        with build_lock:
            if cache['ds'] == ds:
                return  # already up-to-date
            print(f'  Building for {ds}...')
            sum_h, dash_h = penang_builder.build_all(ds)
            cache['ds'] = ds
            cache['sum'] = sum_h
            cache['dash'] = dash_h
            cache['updated'] = datetime.datetime.now()
            print(f'  Done: {ds}')
    except Exception as e:
        print(f'  Build error: {e}')

@app.before_request
def ensure_built():
    """Auto-build on first request if cache is empty"""
    if cache['sum'] is None:
        threading.Thread(target=auto_build).start()
        auto_build()
    else:
        # Check if new data exists once per 10 min
        now = datetime.datetime.now()
        if cache['updated'] and (now - cache['updated']).seconds > 600:
            t = threading.Thread(target=auto_build)
            t.daemon = True
            t.start()

@app.route('/')
def index():
    ds = cache['ds'] or 'N/A'
    updated = cache['updated'].strftime('%Y-%m-%d %H:%M') if cache['updated'] else '—'
    return f'''<html><head><meta charset=utf-8><title>Penang Scheduling</title>
<style>body{{font-family:Segoe UI,sans-serif;margin:40px;background:#f5f5f5}}
h1{{color:#1a237e}}a{{display:inline-block;padding:14px 28px;margin:10px;background:#1a237e;color:#fff;
text-decoration:none;border-radius:6px;font-size:15px;font-weight:600}}
a:hover{{background:#283593}}.info{{color:#666;margin:20px 0}}</style></head><body>
<h1>Penang Production Scheduling</h1>
<p class=info>Latest Data_Source: <b>{ds}</b> | Updated: {updated}</p>
<a href="/sum">📊  Sum Table</a>
<a href="/dashboard">📈  Dashboard</a>
<a href="/rebuild">🔄  Force Rebuild</a>
</body></html>'''

@app.route('/sum')
def sum_table():
    with build_lock:
        if cache['sum'] is None:
            auto_build()
    return cache.get('sum', '<h1>No data yet</h1><p>Try the rebuild button.</p>')

@app.route('/dashboard')
def dashboard():
    with build_lock:
        if cache['dash'] is None:
            auto_build()
    return cache.get('dash', '<h1>No data yet</h1><p>Try the rebuild button.</p>')

@app.route('/rebuild')
def rebuild():
    auto_build()
    return '<html><body><h1>Rebuild triggered</h1><p>Check <a href="/">home page</a> for updated status.</p></body></html>'

if __name__ == '__main__':
    print('Penang Scheduling Web Service (auto-refresh)')
    print(f'  Port: 8080')
    print(f'  Open: http://127.0.0.1:8080')
    auto_build()
    app.run(host='0.0.0.0', port=8080, debug=False)
