#!/usr/bin/env python3
"""Flask — dynamic Sum + Dashboard: direct DB query -> original UI"""
from flask import Flask
from engine import build_all

app = Flask(__name__)

@app.route('/')
def index():
    s, d = build_all()
    return d

@app.route('/sum')
def sum_page():
    s, d = build_all()
    return s

if __name__ == '__main__':
    print('Penang Scheduling (real-time DB -> original UI)')
    print('  http://0.0.0.0:8080')
    app.run(host='0.0.0.0', port=8080, debug=False)
