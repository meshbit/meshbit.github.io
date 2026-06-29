"""
凌云搜索 - 定时爬虫 v4 (async)
七项全改版: asyncio并行 + aiohttp异步 + 随机节奏 + 双写MySQL/Meili
"""
import asyncio, aiohttp, json, hashlib, time, os, random
from concurrent.futures import ThreadPoolExecutor
import pymysql
from queue import Queue, Empty

os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

MEILI_URL = 'http://127.0.0.1:7700'
MEILI_KEY = '5078ead29c1a6784d1b43ae67dfb1c4b17af875100bb14cb37a85dc4bbbeed03'
PROXY_API = 'http://localhost:5003/api/search'

# ============================================================
# 7. 章节级并行 — 关键词同时开工
# ============================================================
MAX_CONCURRENT = 3  # 同时爬3个关键词

# ============================================================
# 4. 请求节奏控制 — 随机间隔
# ============================================================
def random_delay():
    delay = random.uniform(0.5, 3.0)
    time.sleep(delay)
    return delay

# ============================================================
# 1. 持久 Session (Cookie复用)
# ============================================================
_session = None
def _get_session():
    global _session
    if _session is None:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120),
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5)
        )
    return _session

# MySQL 连接池
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

HOT_KEYWORDS = [
    '流浪地球', '庆余年', '凡人修仙传', '三体', '长相思', '鬼灭之刃',
    '繁花', '狂飙', '甄嬛传', '琅琊榜', '武林外传', '长安十二时辰',
    '盗墓笔记', '鬼吹灯', '大江大河', '人民的名义', '斗罗大陆',
    '进击的巨人', '海贼王', '火影忍者', '名侦探柯南', '咒术回战',
    'Photoshop', 'Python', 'Windows', 'Office', 'CAD',
    '周杰伦', 'Taylor Swift', '林俊杰',
    '英语', '考研', '公务员', '教师资格证',
    '电子书', '小说', '经济学',
    # +++ 漫画关键词 +++
    '一人之下', '斗破苍穹', '完美世界', '吞噬星空', '仙逆',
    '遮天', '星辰变', '全职高手', '狐妖小红娘', '镖人',
    '镇魂街', '秦时明月', '画江湖之不良人', '伍六七',
    '一念永恒', '元龙', '凡人修仙传动漫', '斗罗大陆动漫',
]

# ============================================================
# 5. 战术切换 — 失败重试
# ============================================================
async def fetch_with_retry(session, url, max_retries=3):
    """隐身(默认) → 加UA伪装 → 投降"""
    for attempt in range(max_retries):
        try:
            async with session.get(url) as resp:
                return await resp.json()
        except Exception as e:
            if attempt == max_retries - 1:
                print(f'  ⚠️ {url[-30:]}: {e}', flush=True)
                return None
            await asyncio.sleep(2 ** attempt + random.uniform(0, 1))

# ============================================================
# MySQL 同步写入 (线程池)
# ============================================================
executor = ThreadPoolExecutor(max_workers=4)

def save_to_mysql_sync(docs):
    if not docs: return 0
    conn = None
    try:
        conn = _get_mysql()
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
                dt = doc.get('datetime', '')
                if dt:
                    dt = dt.replace('Z', '').replace('T', ' ')[:19]
                    if len(dt) == 10: dt += ' 00:00:00'
                else:
                    dt = time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(sql, (
                    doc['url'], doc['url_hash'], doc.get('note','')[:500],
                    doc.get('password',''), doc['type'],
                    doc.get('source','pansou'), doc.get('keyword',''), dt
                ))
                inserted += 1
            except: pass
        conn.commit()
        cursor.close()
        return inserted
    except Exception as e:
        print(f'  [MySQL] ERR: {e}', flush=True)
        return 0
    finally:
        if conn: _put_mysql(conn)

async def save_to_mysql(docs):
    return await asyncio.get_event_loop().run_in_executor(executor, save_to_mysql_sync, docs)

# ============================================================
# 6. aiohttp 双写 — Meili 异步
# ============================================================
async def save_to_meili(session, docs):
    if not docs: return 0
    try:
        headers = {'Authorization': f'Bearer {MEILI_KEY}', 'Content-Type': 'application/json'}
        async with session.post(f'{MEILI_URL}/indexes/resources/documents',
                                headers=headers, json=docs, timeout=aiohttp.ClientTimeout(30)) as resp:
            return len(docs)
    except Exception as e:
        print(f'  [Meili] ERR: {e}', flush=True)
        return 0


# ============================================================
# 核心
# ============================================================
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def crawl_keyword(session, keyword, idx, total):
    async with semaphore:
        # 4. 随机节奏
        if idx > 0:
            d = random.uniform(0.5, 3.0)
            await asyncio.sleep(d)

        t0 = time.time()
        data = await fetch_with_retry(session, f'{PROXY_API}?kw={keyword}')

        if not data or not data.get('data'):
            print(f'  [{keyword}] 0条', flush=True)
            return 0

        merged = data['data'].get('merged_by_type', {})
        docs = []; seen = set()
        for ptype, items in merged.items():
            for item in items:
                url = item.get('url', '').strip()
                if not url: continue
                url_hash = hashlib.md5(url.encode()).hexdigest()
                if url_hash in seen: continue
                seen.add(url_hash)
                docs.append({
                    'url_hash': url_hash, 'url': url,
                    'note': item.get('note', '')[:500],
                    'password': item.get('password', ''),
                    'datetime': item.get('datetime', ''),
                    'type': ptype, 'source': 'pansou', 'keyword': keyword,
                })

        if docs:
            # 双写并发
            meili_task = save_to_meili(session, docs)
            mysql_task = save_to_mysql(docs)
            meili_n, mysql_n = await asyncio.gather(meili_task, mysql_task)
            elapsed = time.time() - t0
            print(f'  [{idx+1}/{total}] {keyword[:12]:12s} Meili:{len(docs)} MySQL:{mysql_n} ({elapsed:.1f}s)', flush=True)
            return len(docs)
        else:
            print(f'  [{keyword}] 0条', flush=True)
            return 0

# ============================================================
# 主流程
# ============================================================
async def main():
    print(f'=== 凌云爬虫 v4 {time.strftime("%Y-%m-%d %H:%M:%S")} ===')
    print(f'⏱  {len(HOT_KEYWORDS)} 关键词 | 并行 {MAX_CONCURRENT} | aiohttp异步')

    session = _get_session()

    # 检查 MySQL
    try:
        conn = _get_mysql()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM resources")
        print(f'MySQL 现有: {c.fetchone()[0]}条')
        _put_mysql(conn)
    except Exception as e:
        print(f'MySQL 连接失败: {e}'); return

    try:
        async with session.get(f'{MEILI_URL}/indexes/resources/stats',
                               headers={'Authorization': f'Bearer {MEILI_KEY}'},
                               timeout=aiohttp.ClientTimeout(5)) as resp:
            stats = await resp.json()
            print(f'Meilisearch: {stats.get("numberOfDocuments", "?")} 文档')
    except: pass

    # === 关键词并行 ===
    t0 = time.time()
    tasks = [crawl_keyword(session, kw, i, len(HOT_KEYWORDS)) for i, kw in enumerate(HOT_KEYWORDS)]
    total = sum(await asyncio.gather(*tasks))
    elapsed = time.time() - t0

    print(f'\n=== 完成: {total}条 | {elapsed:.1f}s ===')

    # 统计
    try:
        conn = _get_mysql()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COUNT(DISTINCT keyword) FROM resources")
        cnt, kws = c.fetchone()
        print(f'MySQL: {cnt}条 / {kws}关键词')
        _put_mysql(conn)
    except: pass

    await session.close()

if __name__ == '__main__':
    asyncio.run(main())
