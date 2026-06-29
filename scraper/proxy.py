"""
凌云搜索 - 中间层代理
查 Meilisearch + MySQL本地库 + PanSou + 爬虫，合并去重后返回
"""
import re, json, time, hashlib, subprocess, sys, os
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
import requests
import pymysql
from flask import Flask, jsonify, request
from db import init_db, save_results, query_local
from expand import expand, normalize_note

# 禁用系统代理
os.environ['HTTP_PROXY'] = ''
os.environ['HTTPS_PROXY'] = ''

app = Flask(__name__)
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
TIMEOUT = 10
PANSOU_API = 'http://localhost:8081/api/search'

# browser.py 路径
BROWSER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'browser.py')
PYTHON = sys.executable

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
        try: conn.ping(reconnect=True)
        except: conn = pymysql.connect(**MYSQL_CONFIG)
        return conn
    except Empty:
        return pymysql.connect(**MYSQL_CONFIG)

def _put_mysql(conn):
    try: MYSQL_POOL.put_nowait(conn)
    except: conn.close()

def _fill_pool():
    for _ in range(3):
        try:
            conn = pymysql.connect(**MYSQL_CONFIG)
            MYSQL_POOL.put(conn)
        except: break
_fill_pool()

def parse_pan_type(url):
    url_l = url.lower()
    if 'pan.baidu.com' in url_l: return 'baidu'
    if 'aliyundrive.com' in url_l or 'alipan.com' in url_l: return 'aliyun'
    if 'pan.quark.cn' in url_l: return 'quark'
    if 'pan.xunlei.com' in url_l: return 'xunlei'
    if 'cloud.189.cn' in url_l: return 'tianyi'
    if 'drive.uc.cn' in url_l: return 'uc'
    if '115.com' in url_l: return '115'
    if '123pan.com' in url_l or '123684.com' in url_l: return '123'
    return None

def make_result(url, note, ptype, pwd=''):
    return {'url': url, 'note': note[:200], 'password': pwd,
            'datetime': datetime.now().isoformat(), 'type': ptype}

# ===== 爬虫源 =====

def scrape_browser(keyword):
    results = []
    try:
        proc = subprocess.run(
            [PYTHON, BROWSER_SCRIPT, '--search', keyword],
            capture_output=True, text=True, timeout=90,
            cwd=os.path.dirname(BROWSER_SCRIPT),
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            merged = data.get('data', {}).get('merged_by_type', {})
            for ptype, items in merged.items():
                for item in items:
                    item['type'] = ptype
                    results.append(item)
    except: pass
    return results

def scrape_from_panshare(keyword):
    results = []
    try:
        url = f'https://www.baidu.com/s?wd={quote(keyword + " 百度网盘")}&rn=15'
        resp = requests.get(url, headers={**HEADERS, 'Accept-Language': 'zh-CN,zh'}, timeout=TIMEOUT)
        links = re.findall(r'https?://pan\.baidu\.com/s/[a-zA-Z0-9_-]{6,}', resp.text)
        for link in set(links)[:10]:
            results.append(make_result(link, f'{keyword} - 百度网盘', 'baidu'))
    except: pass
    return results

def scrape_quark_share(keyword):
    results = []
    try:
        url = f'https://www.baidu.com/s?wd={quote(keyword + " 夸克网盘")}&rn=15'
        resp = requests.get(url, headers={**HEADERS, 'Accept-Language': 'zh-CN,zh'}, timeout=TIMEOUT)
        links = re.findall(r'https?://pan\.quark\.cn/s/[a-zA-Z0-9]{8,}', resp.text)
        for link in set(links)[:10]:
            results.append(make_result(link, f'{keyword} - 夸克网盘', 'quark'))
    except: pass
    return results

def scrape_aliyun_share(keyword):
    results = []
    try:
        url = f'https://www.baidu.com/s?wd={quote(keyword + " 阿里云盘")}&rn=10'
        resp = requests.get(url, headers={**HEADERS, 'Accept-Language': 'zh-CN,zh'}, timeout=TIMEOUT)
        links = re.findall(r'https?://(?:www\.)?aliyundrive\.com/s/[a-zA-Z0-9]{6,}', resp.text)
        for link in set(links)[:10]:
            results.append(make_result(link, f'{keyword} - 阿里云盘', 'aliyun'))
    except: pass
    return results

SOURCES = [scrape_browser, scrape_from_panshare, scrape_quark_share, scrape_aliyun_share]

# ===== Meilisearch =====
MEILI_URL = 'http://127.0.0.1:7700'
MEILI_KEY = 'pansou-meili-key'

_meili_session = None
def _get_meili_session():
    global _meili_session
    if _meili_session is None:
        _meili_session = requests.Session()
        _meili_session.trust_env = False
        _meili_session.headers.update({
            'Authorization': f'Bearer {MEILI_KEY}',
            'Content-Type': 'application/json',
            'Connection': 'keep-alive',
        })
        adapter = requests.adapters.HTTPAdapter(pool_connections=3, pool_maxsize=3, max_retries=1)
        _meili_session.mount('http://', adapter)
    return _meili_session

def search_meili(keywords):
    if isinstance(keywords, str):
        keywords = [keywords]
    merged = {}
    seen_urls = set()
    seen_notes = {}
    session = _get_meili_session()
    try:
        for kw in keywords:
            resp = session.post(
                f'{MEILI_URL}/indexes/resources/search',
                json={'q': kw, 'limit': 500},
                timeout=5,
            )
            hits = resp.json().get('hits', [])
            for h in hits:
                url = h['url']
                url_clean = re.sub(r'[?#].*$', '', url)
                if url_clean in seen_urls:
                    continue
                seen_urls.add(url_clean)
                ptype = h.get('type', 'others')
                note = normalize_note(h.get('note', ''))
                if note and len(note) > 3:
                    if note in seen_notes:
                        continue
                    seen_notes[note] = True
                merged.setdefault(ptype, []).append({
                    'url': url, 'note': h.get('note', ''),
                    'password': h.get('password', ''),
                    'datetime': h.get('datetime', ''),
                })
        total = sum(len(v) for v in merged.values())
        if total > 0:
            return {'code': 0, 'data': {'merged_by_type': merged, 'total': total}}
    except Exception as e:
        print(f"[Meili] ERROR: {e}", flush=True)
    return None

# ===== MySQL 本地库搜索 =====
def search_mysql(keyword):
    """搜 MySQL 本地库（FULLTEXT 索引，ms级返回）"""
    merged = {}
    seen_urls = set()
    conn = None
    try:
        conn = _get_mysql()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT url, note, password, type, datetime FROM resources "
            "WHERE MATCH(keyword, note) AGAINST(%s IN BOOLEAN MODE) LIMIT 500",
            (keyword,)
        )
        for url, note, pwd, ptype, dt in cursor.fetchall():
            url_clean = re.sub(r'[?#].*$', '', url)
            if url_clean in seen_urls:
                continue
            seen_urls.add(url_clean)
            merged.setdefault(ptype or 'others', []).append({
                'url': url, 'note': note or '',
                'password': pwd or '',
                'datetime': str(dt) if dt else '',
            })
        total = sum(len(v) for v in merged.values())
        if total > 0:
            print(f"[MySQL] '{keyword}': {total}条", flush=True)
            return {'code': 0, 'data': {'merged_by_type': merged, 'total': total}}
    except Exception as e:
        print(f"[MySQL] ERROR: {e}", flush=True)
    finally:
        if conn:
            _put_mysql(conn)
    return None

# ===== API =====

@app.route('/api/search')
def search():
    keyword = request.args.get('kw', '').strip()
    try:
        fixed = keyword.encode('latin-1').decode('utf-8')
        if fixed != keyword:
            keyword = fixed
    except (UnicodeError, LookupError):
        pass
    if not keyword or len(keyword) < 2:
        return jsonify({'code': 0, 'data': {'merged_by_type': {}, 'total': 0}})

    import time as _time
    _t0 = _time.time()
    variants = expand(keyword)

    # 1. SQLite 缓存 (0ms)
    cached = query_local(keyword)
    _t1 = _time.time()
    if cached and cached['data']['total'] > 0:
        resp = jsonify(cached)
        resp.headers['X-Cache'] = f'HIT {int((_t1-_t0)*1000)}ms'
        return resp

    # 2. MySQL 快速路径 — 离线预建索引，够50条直接秒回
    mysql_result = search_mysql(keyword)
    mysql_data = mysql_result['data']['merged_by_type'] if mysql_result else {}
    mysql_total = mysql_result['data']['total'] if mysql_result else 0

    if mysql_total >= 50:
        resp = jsonify({'code': 0, 'data': {'merged_by_type': mysql_data, 'total': mysql_total}})
        resp.headers['X-Source'] = 'mysql'
        return resp

    # 3. Meilisearch (ms级)
    meili_result = search_meili(variants)
    meili_data = meili_result['data']['merged_by_type'] if meili_result else {}
    meili_total = meili_result['data']['total'] if meili_result else 0
    print(f"[Meili] '{keyword}': {meili_total}条", flush=True)

    # 4. 合并 Meili + MySQL
    merged = dict(meili_data)
    seen_urls = set()
    for items in merged.values():
        for item in items:
            url_clean = re.sub(r'[?#].*$', '', item.get('url', ''))
            seen_urls.add(url_clean)
    mysql_new = 0
    for t, items in mysql_data.items():
        for item in items:
            url_clean = re.sub(r'[?#].*$', '', item.get('url', ''))
            if url_clean not in seen_urls:
                seen_urls.add(url_clean)
                merged.setdefault(t, []).append(item)
                mysql_new += 1
    if mysql_total > 0:
        print(f"[MySQL] +{mysql_new}条(去重后)", flush=True)

    # 5. PanSou 实时聚合
    ps_total = 0
    try:
        resp = requests.get(f'{PANSOU_API}?kw={quote(keyword)}', timeout=8)
        if resp.status_code == 200:
            pansou_data = resp.json().get('data', {}).get('merged_by_type', {})
            for t, items in pansou_data.items():
                for item in items:
                    url_clean = re.sub(r'[?#].*$', '', item.get('url', ''))
                    if url_clean in seen_urls:
                        continue
                    seen_urls.add(url_clean)
                    merged.setdefault(t, []).append(item)
                    ps_total += 1
    except: pass
    print(f"[PanSou] '{keyword}': +{ps_total}条", flush=True)

    # 6. 爬虫源 (容错: 超时不阻断搜索)
    try:
        scraper_results = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(fn, keyword): fn for fn in SOURCES}
            for future in as_completed(futures, timeout=15):
                try:
                    scraper_results.extend(future.result(timeout=10))
                except: pass
        for r in scraper_results:
            url_clean = re.sub(r'[?#].*$', '', r['url'])
            if url_clean not in seen_urls:
                seen_urls.add(url_clean)
                t = r.pop('type', 'others')
                merged.setdefault(t, []).append(r)
    except Exception:
        pass

    total = sum(len(v) for v in merged.values())
    print(f"[Merge] '{keyword}': Meili{meili_total} + MySQL{mysql_new} + PanSou{ps_total} + 爬虫 → {total}条", flush=True)
    save_results(keyword, merged)
    return jsonify({'code': 0, 'data': {'merged_by_type': merged, 'total': total}})

@app.route('/api/debug/cache')
def debug_cache():
    import sqlite3, os
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache.db')
    conn = sqlite3.connect(db_path)
    rows = conn.execute('SELECT keyword, total, updated_at FROM search_cache ORDER BY updated_at DESC LIMIT 10').fetchall()
    conn.close()
    return jsonify({'entries': [{'kw': r[0], 'total': r[1], 'updated': r[2]} for r in rows]})

@app.route('/api/health')
def health():
    meili_ok = mysql_ok = False
    try:
        r = requests.get(f'{MEILI_URL}/health', timeout=2)
        meili_ok = r.status_code == 200
    except: pass
    try:
        conn = _get_mysql()
        conn.ping()
        mysql_ok = True
        _put_mysql(conn)
    except: pass
    return jsonify({
        'status': 'ok' if (meili_ok and mysql_ok) else 'degraded',
        'mysql': 'connected' if mysql_ok else 'disconnected',
        'meilisearch': 'connected' if meili_ok else 'disconnected',
    })


@app.route('/api/feedback', methods=['POST'])
def feedback():
    """接收用户投稿分享"""
    try:
        data = request.get_json(force=True)
        links = (data.get('links') or '').strip()
        if not links or len(links) < 10:
            return jsonify({'code': 1, 'msg': '请至少输入一个有效链接'})
        # 写入 submissions.json
        sub_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'submissions.json')
        entry = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'links': links[:5000],
            'ip': request.remote_addr or 'unknown'
        }
        subs = []
        if os.path.exists(sub_file):
            try:
                with open(sub_file, 'r', encoding='utf-8') as f:
                    subs = json.load(f)
            except: pass
        subs.append(entry)
        with open(sub_file, 'w', encoding='utf-8') as f:
            json.dump(subs, f, ensure_ascii=False, indent=2)
        print(f'[反馈] 收到投稿 {len(links)}字', flush=True)
        return jsonify({'code': 0, 'msg': '投稿成功！感谢分享 🎉'})
    except Exception as e:
        return jsonify({'code': 1, 'msg': f'提交失败: {str(e)[:80]}'})

if __name__ == '__main__':
    from waitress import serve
    init_db()
    print("[Waitress] 生产模式启动 (threads=8, conn_limit=100)", flush=True)
    serve(app, host='0.0.0.0', port=5003, threads=8,
          connection_limit=100, channel_timeout=30)
