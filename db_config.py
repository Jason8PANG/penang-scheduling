"""
Shared MySQL database configuration for Production Planning Kanban
All scripts import from here for DB connection
Reads from environment variables (set via .env file)
"""
import os, pymysql

DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', '10.0.6.86'),
    'port': int(os.environ.get('MYSQL_PORT', 33306)),
    'user': os.environ.get('MYSQL_USER', 'powerbi'),
    'password': os.environ.get('MYSQL_PASSWORD', '!Q1234567'),
    'database': os.environ.get('MYSQL_DATABASE', 'productionplanningkanban'),
    'charset': 'utf8mb4'
}

TABLE_NAME = os.environ.get('MYSQL_TABLE', 'covswo_data')

COLUMNS = [
    'Site', 'Order', 'Order_Date', 'Line', 'Item', 'Due_Date', 'Request_Date',
    'Project_code', 'Sales_price', 'Sales_amount', 'FK_date', 'pick_up_date', 'FG_stock',
    'Source_Number',
    'CR_Month', 'CR_WK', 'MFS_TYPE', 'MFS_MTH', 'MFS_WK',
    'NAI_MTH', 'NAI_WK', 'OTDR_MTH', 'OTDR_WK', 'OTDR_ACCU_MTH', 'OTDR_ACCU_WK',
    'Data_Source'
]


def get_conn():
    return pymysql.connect(**DB_CONFIG)
