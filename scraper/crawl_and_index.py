"""
凌云搜索 - 定时爬虫脚本 (v3)
每天定时拉取热门关键词 → Python Proxy API → Meilisearch + MySQL
Session 复用 + 连接池，避免套接字耗尽
"""
import json, hashlib, time, requests, sys, os
from urllib.parse import quote
import pymysql
from queue import Queue, Empty

# 禁用系统代理
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

MEILI_URL = 'http://127.0.0.1:7700'
MEILI_KEY = 'pansou-meili-key'
PROXY_API = 'http://localhost:5003/api/search'

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
    # === 影视剧 ===
    '流浪地球', '庆余年', '凡人修仙传', '三体', '长相思', '狂飙', '繁花',
    '甄嬛传', '琅琊榜', '武林外传', '长安十二时辰', '人民的名义', '大江大河',
    '漫长的季节', '人世间', '开端', '县委大院', '去有风的地方',
    '莲花楼', '云之羽', '宁安如梦', '一念关山', '与凤行',
    '知否', '知否知否应是绿肥红瘦', '甄嬛传全集', '如懿传',
    # === 动漫 ===
    '鬼灭之刃', '进击的巨人', '海贼王', '火影忍者', '名侦探柯南', '咒术回战',
    '一人之下', '斗破苍穹', '完美世界', '吞噬星空', '仙逆', '遮天',
    '星辰变', '全职高手', '狐妖小红娘', '镖人', '镇魂街', '秦时明月',
    '画江湖之不良人', '伍六七', '一念永恒', '元龙', '斗罗大陆',
    '葬送的芙莉莲', '间谍过家家', '我推的孩子', '电锯人', '咒术回战第二季',
    '死神千年血战篇', '蓝锁', '怪兽8号', '迷宫饭',
    # === 电影 ===
    '奥本海默', '芭比', '封神第一部', '孤注一掷', '消失的她',
    '满江红', '流浪地球2', '深海', '长安三万里', '八角笼中',
    '周处除三害', '你想活出怎样的人生', '哥斯拉大战金刚2', '沙丘2',
    '年会不能停', '热辣滚烫', '飞驰人生2', '第二十条',
    # === 软件/工具 ===
    'Photoshop', 'Python', 'Windows', 'Office', 'CAD', 'Adobe',
    'Premiere', 'After Effects', 'Illustrator', 'MATLAB', 'SolidWorks',
    'C4D', 'Blender', 'VS Code', 'PyCharm', 'Final Cut Pro',
    # === 音乐 ===
    '周杰伦', 'Taylor Swift', '林俊杰', '陈奕迅', '邓紫棋',
    '薛之谦', '李荣浩', '五月天', '张杰', '王菲',
    # === 学习/考试 ===
    '英语', '考研', '公务员', '教师资格证', '司法考试', 'CPA',
    '一建', '二建', '造价工程师', '消防工程师', '中级会计',
    '雅思', '托福', 'GRE', '高考', '中考',
    # === 电子书/小说 ===
    '电子书', '小说', '经济学', '心理学', '历史', '哲学',
    '三体全集', '平凡的世界', '活着', '百年孤独', '明朝那些事儿',
    '盗墓笔记', '鬼吹灯', '斗罗大陆小说', '全职高手小说',
    # === 游戏 ===
    '老头环', '塞尔达', '原神', '崩坏星穹铁道', '黑神话悟空',
    'GTA5', '赛博朋克2077', '荒野大镖客2', '我的世界',
    '只狼', '地平线', '对马岛之鬼', '最终幻想',
    # === 资源类型 ===
    '4K电影', '4K动漫', '4K电视剧', '蓝光原盘', 'REMUX',
    '无损音乐', 'Hi-Res', 'DSD', 'PDF电子书', 'epub',
    '简历模板', 'PPT模板', 'AI绘画', 'AI教程',
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

def search_and_index(keyword):
    try:
        session = _get_session()
        resp = session.get(f'{PROXY_API}?kw={quote(keyword)}', timeout=120)
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

            print(f'  [{keyword}] Meili:{len(docs)} MySQL:{mysql_count}')
            session.close()
            return len(docs)
        else:
            print(f'  [{keyword}] 0条')
            return 0
    except Exception as e:
        print(f'  [{keyword}] ERR: {e}')
        return 0

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

    # 检查 Meilisearch
    try:
        stats = requests.get(f'{MEILI_URL}/indexes/resources/stats',
            headers={'Authorization': f'Bearer {MEILI_KEY}'}, timeout=5).json()
        print(f'Meilisearch: {stats.get("numberOfDocuments", "?")} 文档')
    except: pass

    total_new = 0
    for i, kw in enumerate(HOT_KEYWORDS):
        print(f'[{i+1}/{len(HOT_KEYWORDS)}]', end=' ', flush=True)
        total_new += search_and_index(kw)

    print(f'\n=== 完成: 新增 {total_new} 条 ===')

    # 最终统计
    try:
        conn = _get_mysql()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM resources")
        print(f'MySQL 总量: {c.fetchone()[0]}条')
        _put_mysql(conn)
    except: pass

    try:
        stats = requests.get(f'{MEILI_URL}/indexes/resources/stats',
            headers={'Authorization': f'Bearer {MEILI_KEY}'}, timeout=5).json()
        print(f'Meilisearch 总量: {stats.get("numberOfDocuments", "?")} 文档')
    except: pass

if __name__ == '__main__':
    main()
