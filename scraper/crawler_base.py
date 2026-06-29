#!/usr/bin/env python3
"""
凌云搜索 - 爬虫基类
所有新模块继承此类，统一：Session管理 / 链接提取 / 三库写入
"""
import re, json, hashlib, time, os, sys
from datetime import datetime
from urllib.parse import quote
import requests

# 禁用代理
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'NO_PROXY']:
    os.environ.pop(k, None)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

PAN_LINK_RE = re.compile(
    r'(?:https?://)?(?:www\.)?(?:'
    r'pan\.baidu\.com/s/[a-zA-Z0-9_-]{6,}|'
    r'aliyundrive\.com/s/[a-zA-Z0-9]{6,}|alipan\.com/s/[^\s"\'<>]+|'
    r'pan\.quark\.cn/s/[a-zA-Z0-9]{8,}|'
    r'pan\.xunlei\.com/s/[a-zA-Z0-9]+|'
    r'cloud\.189\.cn/[^\s"\'<>]+|'
    r'drive\.uc\.cn/[^\s"\'<>]+|'
    r'115\.com/s/[^\s"\'<>]+|'
    r'123pan\.com/s/[^\s"\'<>]+|123684\.com/s/[^\s"\'<>]+|'
    r'(?:www\.)?lanzou[a-z]*\.com/[^\s"\'<>]+|'
    r'mega\.nz/[^\s"\'<>]+|'
    r'drive\.google\.com/[^\s"\'<>]+'
    r')', re.IGNORECASE)

PAN_TYPES = {
    'pan.baidu.com': 'baidu', 'aliyundrive.com': 'aliyun', 'alipan.com': 'aliyun',
    'pan.quark.cn': 'quark', 'pan.xunlei.com': 'xunlei', 'cloud.189.cn': 'tianyi',
    'drive.uc.cn': 'uc', '115.com': '115', '123pan.com': '123', '123684.com': '123',
    'lanzou': 'lanzou', 'mega.nz': 'mega', 'drive.google.com': 'google',
}

# Meilisearch 配置
MEILI_URL = 'http://127.0.0.1:7700'
MEILI_KEY = 'pansou-meili-key'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_session = None
def get_session():
    """获取 Session — 不信任环境代理，走系统代理（v2rayN 10808）"""
    global _session
    if _session is None:
        _session = requests.Session()
        # 不使用 trust_env，让 Windows 系统代理自动生效
        _session.headers.update(HEADERS)
    return _session

_local_session = None
def get_local_session():
    """获取本地 Session — 不走代理，专用于 localhost 服务"""
    global _local_session
    if _local_session is None:
        _local_session = requests.Session()
        _local_session.trust_env = False
        _local_session.headers.update(HEADERS)
    return _local_session

def parse_type(url):
    url_lower = url.lower()
    for k, v in PAN_TYPES.items():
        if k in url_lower:
            return v
    return 'others'

def extract_links(html_or_text, source_name=''):
    """从HTML/文本中提取网盘链接"""
    results = []
    seen = set()
    for m in PAN_LINK_RE.finditer(html_or_text):
        url = m.group(0)
        if not url.startswith('http'):
            url = 'https://' + url
        # 去参数
        url_clean = re.sub(r'[?#].*$', '', url)
        if url_clean in seen:
            continue
        seen.add(url_clean)
        ptype = parse_type(url_clean)
        if ptype:
            results.append({
                'url': url_clean,
                'note': source_name[:200],
                'password': '',
                'datetime': datetime.now().isoformat(),
                'type': ptype,
                'source': source_name,
                'url_hash': hashlib.md5(url_clean.encode()).hexdigest(),
            })
    return results

def save_to_meili(docs):
    """写入 Meilisearch"""
    if not docs:
        return 0
    try:
        payload = [{k: v for k, v in d.items() if k != 'url_hash'} for d in docs]
        resp = get_local_session().post(
            f'{MEILI_URL}/indexes/resources/documents',
            headers={
                'Authorization': f'Bearer {MEILI_KEY}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code in (200, 202):
            return len(docs)
        print(f'  [Meili] {resp.status_code} {resp.text[:200]}', flush=True)
    except Exception as e:
        print(f'  [Meili] ERR: {e}', flush=True)
    return 0

def save_to_mysql(docs):
    """写入 MySQL"""
    if not docs:
        return 0
    try:
        import pymysql
        conn = pymysql.connect(
            host='127.0.0.1', port=3307, user='root',
            password='pansearch123', database='pansearch',
            charset='utf8mb4', connect_timeout=5,
        )
        inserted = 0
        with conn.cursor() as cursor:
            for doc in docs:
                try:
                    cursor.execute(
                        """INSERT IGNORE INTO resources (url, note, password, type, keyword, datetime)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (doc['url'], doc.get('note', ''),
                         doc.get('password', ''),
                         doc.get('type', 'others'),
                         doc.get('keyword', doc.get('source', '')),
                         doc.get('datetime', datetime.now().isoformat())),
                    )
                    if cursor.rowcount > 0:
                        inserted += 1
                except:
                    pass
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        if "'pymysql'" in str(e):
            pass  # pymysql not installed, skip MySQL
        else:
            print(f'  [MySQL] ERR: {e}', flush=True)
    return 0

def save_all(docs):
    """双库并发写入 Meilisearch + MySQL"""
    if not docs:
        return 0
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(save_to_meili, docs)
        f3 = ex.submit(save_to_mysql, docs)
        m, my = f1.result(), f3.result()
    total = len(docs)
    print(f'  Saved: Meili{m}/{total} MySQL{my}/{total}', flush=True)
    return total

def get_with_retry(url, max_retries=2, **kwargs):
    """带重试的 HTTP GET"""
    session = get_session()
    for i in range(max_retries):
        try:
            resp = session.get(url, timeout=15, **kwargs)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 404):
                return None
            time.sleep(1 + i)
        except Exception as e:
            if i == max_retries - 1:
                print(f'  [HTTP] ERR {url[:60]}: {e}', flush=True)
            time.sleep(1 + i)
    return None

if __name__ == '__main__':
    print('crawler_base.py loaded OK', flush=True)
