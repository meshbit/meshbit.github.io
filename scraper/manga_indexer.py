"""
漫画索引器 — baozimh.org → 凌云搜索三库
读 manga.db SQLite → 写 MySQL + ES + Meilisearch
"""
import asyncio, aiohttp, json, hashlib, time, sqlite3, os, re
from concurrent.futures import ThreadPoolExecutor
import pymysql
from queue import Queue, Empty

os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

MEILI_URL = 'http://127.0.0.1:7700'
MEILI_KEY = '5078ead29c1a6784d1b43ae67dfb1c4b17af875100bb14cb37a85dc4bbbeed03'
ES_URL = 'http://127.0.0.1:9200'
MANGA_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'manga-site', 'manga.db')
BASE_URL = 'https://baozimh.org'

MYSQL_POOL = Queue(maxsize=5)
MYSQL_CONFIG = {
    'host': '127.0.0.1', 'port': 3307, 'user': 'root',
    'password': 'pansearch123', 'database': 'pansearch',
    'charset': 'utf8mb4', 'connect_timeout': 5,
}

def _get_mysql():
    try:
        conn = MYSQL_POOL.get_nowait()
        try: conn.ping()
        except: conn = pymysql.connect(**MYSQL_CONFIG)
        return conn
    except Empty:
        return pymysql.connect(**MYSQL_CONFIG)

def _put_mysql(conn):
    try: MYSQL_POOL.put_nowait(conn)
    except: conn.close()

for _ in range(3):
    try: MYSQL_POOL.put(pymysql.connect(**MYSQL_CONFIG))
    except: break

executor = ThreadPoolExecutor(max_workers=4)

def read_manga_db():
    """读取漫画数据库"""
    db_path = MANGA_DB
    if not os.path.exists(db_path):
        # try alternate paths
        alt = r'D:\manga-site\manga.db'
        if os.path.exists(alt):
            db_path = alt
        else:
            print(f'❌ 漫画数据库未找到: {MANGA_DB}')
            return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT m.slug, m.title, m.cover, m.author, m.status, m.description,
               m.tags, m.updated_at, MAX(c.number) as latest_ch
        FROM manga m
        LEFT JOIN chapters c ON c.manga_id = m.id
        WHERE m.title IS NOT NULL AND m.title != ''
        GROUP BY m.id
        ORDER BY m.updated_at DESC
    ''').fetchall()
    conn.close()

    manga_list = []
    for r in rows:
        note_parts = [r['title']]
        if r['author']: note_parts.append(f"作者:{r['author']}")
        if r['status']: note_parts.append(r['status'])
        if r['latest_ch']: note_parts.append(f"更新至第{r['latest_ch']}话")
        if r['tags']: note_parts.append(f"#{r['tags']}")

        note = ' | '.join(note_parts)
        url = f"{BASE_URL}/manga/{r['slug']}"

        manga_list.append({
            'url': url,
            'note': note[:500],
            'type': 'manga',
            'source': 'baozimh',
            'keyword': ' '.join(filter(None, [r['title'], r['author'] or '', r['tags'] or ''])),
            'datetime': r['updated_at'] or time.strftime('%Y-%m-%d'),
            'slug': r['slug'],
        })
    return manga_list


def save_to_mysql_sync(docs):
    if not docs: return 0
    conn = _get_mysql()
    try:
        cursor = conn.cursor()
        sql = """
            INSERT INTO resources (url, url_hash, note, password, type, source, keyword, datetime)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                note = IF(VALUES(note) != '', VALUES(note), note), updated_at = NOW()
        """
        inserted = 0
        for doc in docs:
            try:
                url_hash = hashlib.md5(doc['url'].encode()).hexdigest()
                cursor.execute(sql, (doc['url'], url_hash, doc['note'][:500], '',
                    doc['type'], doc['source'], doc['keyword'][:200], doc['datetime']))
                inserted += 1
            except: pass
        conn.commit()
        cursor.close()
        return inserted
    except Exception as e:
        print(f'[MySQL] ERR: {e}')
        return 0
    finally:
        _put_mysql(conn)

async def save_to_mysql(docs):
    return await asyncio.get_event_loop().run_in_executor(executor, save_to_mysql_sync, docs)

async def save_to_meili(session, docs):
    if not docs: return 0
    try:
        meili_docs = []
        for doc in docs:
            url_hash = hashlib.md5(doc['url'].encode()).hexdigest()
            meili_docs.append({
                'url_hash': url_hash, 'url': doc['url'],
                'note': doc['note'][:500], 'password': '',
                'type': doc['type'], 'source': doc['source'],
                'keyword': doc['keyword'][:200], 'datetime': doc['datetime'],
            })
        headers = {'Authorization': f'Bearer {MEILI_KEY}', 'Content-Type': 'application/json'}
        async with session.post(f'{MEILI_URL}/indexes/resources/documents',
                                headers=headers, json=meili_docs,
                                timeout=aiohttp.ClientTimeout(30)) as resp:
            return len(meili_docs)
    except Exception as e:
        print(f'[Meili] ERR: {e}')
        return 0

async def save_to_es(session, docs):
    if not docs: return 0
    try:
        body = ''
        for doc in docs:
            url_hash = hashlib.md5(doc['url'].encode()).hexdigest()
            action = json.dumps({"index": {"_index": "resources", "_id": url_hash}})
            source = {'url': doc['url'], 'note': doc['note'][:500],
                      'type': doc['type'], 'keyword': doc['keyword'][:200],
                      'datetime': doc['datetime']}
            body += action + '\n' + json.dumps(source, ensure_ascii=False) + '\n'
        async with session.post(f'{ES_URL}/_bulk', data=body.encode('utf-8'),
                                headers={'Content-Type': 'application/x-ndjson'},
                                timeout=aiohttp.ClientTimeout(30)) as resp:
            return len(docs)
    except Exception as e:
        print(f'[ES] ERR: {e}')
        return 0

async def main():
    print(f'=== 漫画索引器 {time.strftime("%Y-%m-%d %H:%M:%S")} ===')

    manga_list = read_manga_db()
    if not manga_list:
        print('❌ 无漫画数据')
        return

    print(f'📚 {len(manga_list)} 部漫画')

    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60),
        connector=aiohttp.TCPConnector(limit=10)
    )

    # 分批写入
    batch_size = 100
    total_inserted = 0
    for i in range(0, len(manga_list), batch_size):
        batch = manga_list[i:i+batch_size]
        mysql_r, meili_r, es_r = await asyncio.gather(
            save_to_mysql(batch),
            save_to_meili(session, batch),
            save_to_es(session, batch),
        )
        total_inserted += len(batch)
        pct = min(i+batch_size, len(manga_list))
        print(f'  [{pct}/{len(manga_list)}] MySQL:{mysql_r} Meili:{meili_r} ES:{es_r}')

    print(f'\n✅ {total_inserted} 部漫画已索引入凌云搜索')
    print(f'   搜索试试: pan.okva.cc → 搜 "一人之下" 或 "漫画"')

    await session.close()

if __name__ == '__main__':
    asyncio.run(main())
