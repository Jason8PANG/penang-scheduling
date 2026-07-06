#!/usr/bin/env python3
"""Flask — runs original pipeline automatically, serves original sum/dashboard"""
import os, subprocess, threading, sys
from flask import Flask

DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
LOCK = threading.Lock()
CACHE = {'ready': False, 'sum': '', 'dash': '', 'log': ''}

def run_pipeline():
    with LOCK:
        logs = []
        for script in ['1_detail.py', '2_sum.py', '3_dashboard.py']:
            sp = os.path.join(DIR, script)
            if not os.path.exists(sp):
                logs.append(f'[SKIP] {script}')
                continue
            r = subprocess.run([PYTHON, sp], capture_output=True, text=True, cwd=DIR, timeout=300)
            logs.append(f'[{script}] {"OK" if r.returncode==0 else "FAIL"}')
            if r.returncode != 0:
                logs.append(r.stderr.strip()[:300])
        sum_html = ''; dash_html = ''
        for f in sorted(os.listdir(DIR), reverse=True):
            if f.startswith('Penang_Scheduling_WK') and f.endswith('_sum.html') and not sum_html:
                with open(os.path.join(DIR, f), encoding='utf-8') as fh: sum_html = fh.read()
            if f.startswith('Penang_Chart_Dashboard_WK') and f.endswith('.html') and not dash_html:
                with open(os.path.join(DIR, f), encoding='utf-8') as fh: dash_html = fh.read()
        CACHE['sum'] = sum_html
        CACHE['dash'] = dash_html
        CACHE['log'] = '\n'.join(logs)
        CACHE['ready'] = True

app = Flask(__name__)

@app.before_request
def ensure():
    if not CACHE.get('ready'):
        run_pipeline()

@app.route('/')
def index():
    return CACHE.get('dash', '<h1>Building...</h1><meta http-equiv="refresh" content="5">')

@app.route('/sum')
def sum_page():
    return CACHE.get('sum', '<h1>Building...</h1><meta http-equiv="refresh" content="5">')

@app.route('/rebuild')
def rebuild():
    run_pipeline()
    return '<html><body><h1>OK</h1><a href="/">← Back</a></body></html>'

if __name__ == '__main__':
    print('Penang Scheduling (original pipeline runner)')
    print(f'  http://0.0.0.0:8080')
    run_pipeline()
    app.run(host='0.0.0.0', port=8080, debug=False)
