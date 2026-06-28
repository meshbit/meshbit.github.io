"""
本地 SQLite 缓存 — 搜过就存，下次秒出
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache.db')

def init_db():
    """建表（幂等）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS search_cache (
            keyword TEXT NOT NULL,
            results_json TEXT NOT NULL,
            total INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (keyword)
        )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_keyword ON search_cache(keyword)')
    conn.commit()
    conn.close()
    print(f"[DB] init OK: {DB_PATH}")

def save_results(keyword, merged_by_type):
    """存结果，keyword 去重"""
    if not merged_by_type:
        return
    total = sum(len(v) for v in merged_by_type.values())
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT OR REPLACE INTO search_cache (keyword, results_json, total, updated_at)
        VALUES (?, ?, ?, ?)
    ''', (keyword, json.dumps(merged_by_type, ensure_ascii=False), total, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def query_local(keyword):
    """查本地缓存，有就返回，没有返回 None"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT results_json, total FROM search_cache WHERE keyword = ?', (keyword,)
    ).fetchone()
    conn.close()
    if row:
        merged = json.loads(row['results_json'])
        return {'code': 0, 'data': {'merged_by_type': merged, 'total': row['total']}}
    return None
