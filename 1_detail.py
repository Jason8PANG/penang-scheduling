#!/usr/bin/env python3
"""Step 1: Export MySQL covswo_data → MySQL_WK{MMDD}_export.xlsx (current WK only, Source_Type=Job)"""
import datetime, os, sys, pymysql, openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_config

DIR = os.path.dirname(os.path.abspath(__file__))
cfg = db_config.DB_CONFIG
tbl = db_config.TABLE_NAME

# Determine current WK from today's date
today = datetime.datetime.now()
cur_mth = today.month
cur_day = today.day
# WK format: MMDD (same as MRP file naming)
wk_id = f'{cur_mth:02d}{cur_day:02d}'

print(f'1_detail: Today={today.strftime("%Y-%m-%d")}, WK={wk_id}')

# Connect to MySQL
print(f'Connecting to MySQL {cfg["host"]}:{cfg["port"]}...')
conn = pymysql.connect(**cfg)
cur = conn.cursor()

# Get table columns
cur.execute(f'DESCRIBE {tbl}')
all_cols = [r[0] for r in cur.fetchall()]
print(f'Table columns: {len(all_cols)}')

# Get distinct Data_Source values to find matching WK
cur.execute(f'SELECT DISTINCT Data_Source FROM {tbl}')
ds_values = [r[0] for r in cur.fetchall()]
print(f'Data_Source values: {ds_values}')

# Find matching Data_Source for current WK
target_ds = None
for ds in ds_values:
    if ds and f'WK{wk_id}' in str(ds):
        target_ds = ds
        break

if not target_ds:
    print(f'ERROR: No data found for WK{wk_id}')
    cur.close()
    conn.close()
    exit(1)

print(f'  Matched Data_Source: {target_ds}')

# Export data: filter by Data_Source = target_ds AND Source_Type = 'Job'
# Source_Type is the last column
srctype_col = all_cols[-1]  # 'Source_Type'
datasrc_col = all_cols[-2]  # 'Data_Source'

cur.execute(f'SELECT COUNT(*) FROM {tbl} WHERE `{datasrc_col}` = %s AND `{srctype_col}` = %s', (target_ds, 'Job'))
job_count = cur.fetchone()[0]
print(f'  Rows (Data_Source={target_ds}, Source_Type=Job): {job_count}')

if job_count == 0:
    print(f'ERROR: No Job-type rows for {target_ds}')
    cur.close()
    conn.close()
    exit(1)

# Fetch all matching rows
cur.execute(f'SELECT * FROM {tbl} WHERE `{datasrc_col}` = %s AND `{srctype_col}` = %s', (target_ds, 'Job'))
rows = cur.fetchall()
print(f'  Fetched: {len(rows)} rows')

# Create Excel with numeric formatting
wb = openpyxl.Workbook()
ws = wb.active
ws.title = 'data'

# Write headers
ws.append(all_cols)

# Numeric column indices (0-based after 'id' at [0])
# Sales_price=9, Sales_amount=10, FG_stock=14, CR_Month=15, MFS_MTH=18, MFS_WK=19,
# NAI_MTH=20, NAI_WK=21, OTDR_MTH=22, OTDR_ACCU_MTH=24, OTDR_ACCU_WK=25,
# Real_Production_MTH=26, Real_Production_WK=27
NUM_COLS = {9, 10, 14, 15, 18, 19, 20, 21, 22, 24, 25, 26, 27}
# Text columns that should not be converted: CR_WK=16, MFS_TYPE=17, OTDR_WK=23
TEXT_COLS = {16, 17, 23}

for row in rows:
    r = list(row)
    for c_idx, val in enumerate(r):
        if c_idx in TEXT_COLS:
            continue
        if c_idx in NUM_COLS:
            try:
                s = str(val).strip() if val else ''
                if not s or 'Not' in s:
                    continue
                r[c_idx] = float(s)
            except:
                pass
    ws.append(r)

# Format Sales_amount and Sales_price columns as numbers
for c in (10, 11):  # col J, K (1-indexed)
    for r_idx in range(2, ws.max_row + 1):
        cell = ws.cell(r_idx, c)
        if isinstance(cell.value, (int, float)):
            cell.number_format = '#,##0.00'

out_file = os.path.join(DIR, f'MySQL_WK{wk_id}_export.xlsx')
wb.save(out_file)
sz = os.path.getsize(out_file)
print(f'Saved: {os.path.basename(out_file)} ({ws.max_row} rows x {ws.max_column} cols, {sz//1024}KB)')

cur.close()
conn.close()
print('Done')
