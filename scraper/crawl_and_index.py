"""
凌云搜索 - 定时爬虫脚本 (v3)
每天定时拉取热门关键词 → Python Proxy API → Meilisearch + MySQL + Elasticsearch
Session 复用 + 连接池，避免套接字耗尽
"""
import json, hashlib, time, requests, sys, os
import pymysql
from queue import Queue, Empty

# 禁用系统代理
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

MEILI_URL = 'http://127.0.0.1:7700'
MEILI_KEY = '5078ead29c1a6784d1b43ae67dfb1c4b17af875100bb14cb37a85dc4bbbeed03'
PROXY_API = 'http://localhost:5003/api/search'
ES_URL = 'http://127.0.0.1:9200'

# HTTP Session 复用
_session = None
def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=5, pool_maxsize=5, max_retries=2
        )
        _session.mount('http://', adapter)
    return _session

# MySQL 连接池
MYSQL_POOL = Queue(maxsize=3)
MYSQL_CONFIG = {
    'host': '127.0.0.1', 'port': 3307, 'user': 'root',
    'password': 'pansearch123', 'database': 'pansearch',
    'charset': 'utf8mb4', 'connect_timeout': 5,
}

def _get_mysql():
    try:
        conn = MYSQL_POOL.get_nowait()
        try: conn.ping(reconnect=True)
        except: conn = pymysql.connect(**MYSQL_CONFIG)
        return conn
    except Empty:
        return pymysql.connect(**MYSQL_CONFIG)

def _put_mysql(conn):
    try: MYSQL_POOL.put_nowait(conn)
    except: conn.close()

# 预热连接池
for _ in range(2):
    try: MYSQL_POOL.put(pymysql.connect(**MYSQL_CONFIG))
    except: break

HOT_KEYWORDS = [
    '流浪地球', '庆余年', '凡人修仙传', '三体', '长相思', '鬼灭之刃',
    '繁花', '狂飙', '甄嬛传', '琅琊榜', '武林外传', '长安十二时辰',
    '盗墓笔记', '鬼吹灯', '大江大河', '人民的名义', '斗罗大陆',
    '进击的巨人', '海贼王', '火影忍者', '名侦探柯南', '咒术回战',
    'Photoshop', 'Python', 'Windows', 'Office', 'CAD',
    '周杰伦', 'Taylor Swift', '林俊杰',
    '英语', '考研', '公务员', '教师资格证',
    '电子书', '小说', '经济学',
]

def save_to_mysql(docs):
    if not docs:
        return 0
    conn = None
    try:
        conn = _get_mysql()
        cursor = conn.cursor()
        sql = """
            INSERT INTO resources (url, url_hash, note, password, type, source, keyword, datetime)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                note = IF(VALUES(note) != '', VALUES(note), note),
                updated_at = NOW()
        """
        inserted = 0
        for doc in docs:
            try:
                dt = doc.get('datetime', '')
                if dt:
                    dt = dt.replace('Z', '').replace('T', ' ')
                    if len(dt) == 10:
                        dt += ' 00:00:00'
                else:
                    dt = time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(sql, (
                    doc['url'], doc['url_hash'], doc['note'], doc['password'],
                    doc['type'], doc.get('source', 'pansou'), doc.get('keyword', ''),
                    dt
                ))
                inserted += 1
            except Exception as e:
                pass
        conn.commit()
        cursor.close()
        return inserted
    except Exception as e:
        print(f'  [MySQL] ERROR: {e}')
        return 0
    finally:
        if conn:
            _put_mysql(conn)

def save_to_es(docs):
    """Elasticsearch bulk 索引"""
    if not docs:
        return 0
    try:
        body = ''
        for doc in docs:
            action = json.dumps({"index": {"_index": "resources", "_id": doc['url_hash']}})
            source = {k: doc[k] for k in ('url', 'note', 'password', 'type', 'keyword', 'datetime') if k in doc}
            body += action + '\n' + json.dumps(source, ensure_ascii=False) + '\n'
        resp = _get_session().post(
            f'{ES_URL}/_bulk',
            data=body.encode('utf-8'),
            headers={'Content-Type': 'application/x-ndjson'},
            timeout=30
        )
        result = resp.json()
        if result.get('errors'):
            err_count = sum(1 for item in result.get('items', []) if 'error' in item.get('index', {}))
            print(f'  [ES] 部分失败: {err_count}/{len(docs)}', flush=True)
        else:
            print(f'  [ES] {len(docs)}条', flush=True)
        return len(docs)
    except Exception as e:
        print(f'  [ES] ERROR: {e}', flush=True)
        return 0

def search_and_index(keyword):
    try:
        session = _get_session()
        resp = session.get(f'{PROXY_API}?kw={keyword}', timeout=120)
        data = resp.json().get('data', {}).get('merged_by_type', {})
        docs = []
        seen = set()
        for ptype, items in data.items():
            for item in items:
                url = item.get('url', '').strip()
                if not url:
                    continue
                url_hash = hashlib.md5(url.encode()).hexdigest()
                if url_hash in seen:
                    continue
                seen.add(url_hash)
                docs.append({
                    'url_hash': url_hash, 'url': url,
                    'note': item.get('note', '')[:500],
                    'password': item.get('password', ''),
                    'datetime': item.get('datetime', ''),
                    'type': ptype, 'source': 'pansou', 'keyword': keyword,
                })

        if docs:
            # Meilisearch 索引
            meili_headers = {
                'Authorization': f'Bearer {MEILI_KEY}',
                'Content-Type': 'application/json',
            }
            r = session.post(
                f'{MEILI_URL}/indexes/resources/documents',
                headers=meili_headers, json=docs, timeout=30
            )
            task_uid = r.json().get('taskUid', '?')

            # MySQL 入库
            mysql_count = save_to_mysql(docs)

            # ES 入库
            es_count = save_to_es(docs)

            print(f'  [{keyword}] Meili:{len(docs)} MySQL:{mysql_count} ES:{es_count}')
            session.close()
            return len(docs)
        else:
            print(f'  [{keyword}] 0条')
            return 0
    except Exception as e:
        print(f'  [{keyword}] ERR: {e}')
        return 0

def backfill_es_from_mysql():
    """从 MySQL 全量回填 ES"""
    print('=== ES 回填: MySQL → ES ===')
    conn = _get_mysql()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM resources")
    total_rows = cursor.fetchone()[0]
    cursor.execute("SELECT url, url_hash, note, password, type, keyword, datetime FROM resources")
    
    batch = []
    count = 0
    for row in cursor:
        url, url_hash, note, pwd, ptype, kw, dt = row
        batch.append({
            'url_hash': url_hash, 'url': url,
            'note': note or '', 'password': pwd or '',
            'type': ptype or 'others', 'keyword': kw or '',
            'datetime': str(dt) if dt else '',
        })
        if len(batch) >= 500:
            count += save_to_es(batch)
            batch = []
            time.sleep(0.5)
    if batch:
        count += save_to_es(batch)
    
    cursor.close()
    _put_mysql(conn)
    print(f'=== ES 回填完成: {count}/{total_rows} ===')

def main():
    print(f'=== 凌云爬虫 v3 {time.strftime("%Y-%m-%d %H:%M:%S")} ===')

    # 检查 MySQL
    try:
        conn = _get_mysql()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM resources")
        total = c.fetchone()[0]
        print(f'MySQL 现有: {total}条')
        _put_mysql(conn)
    except Exception as e:
        print(f'MySQL 连接失败: {e}')
        return

    # ES 回填 (如果是首次运行，ES 数据少)
    try:
        es_count = requests.get(f'{ES_URL}/resources/_count', timeout=5).json().get('count', 0)
        print(f'ES 现有: {es_count}条')
        if es_count < total:
            backfill_es_from_mysql()
    except Exception as e:
        print(f'ES 连接失败: {e}')

    total = 0
    for i, kw in enumerate(HOT_KEYWORDS):
        total += search_and_index(kw)
        time.sleep(3 if i % 5 != 0 else 5)

    print(f'=== 完成: {total}条入库 ===')

    # 统计
    try:
        conn = _get_mysql()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COUNT(DISTINCT keyword) FROM resources")
        cnt, kws = c.fetchone()
        print(f'MySQL 总计: {cnt}条 / {kws}关键词')
        _put_mysql(conn)
    except: pass

    try:
        stats = requests.get(f'{MEILI_URL}/indexes/resources/stats',
            headers={'Authorization': f'Bearer {MEILI_KEY}'}, timeout=5).json()
        print(f'Meilisearch: {stats.get("numberOfDocuments", "?")} 文档')
    except: pass

    try:
        cnt = requests.get(f'{ES_URL}/resources/_count', timeout=5).json().get('count', '?')
        print(f'Elasticsearch: {cnt} 文档')
    except: pass

if __name__ == '__main__':
    main()
