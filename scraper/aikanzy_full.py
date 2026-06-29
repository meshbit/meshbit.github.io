#!/usr/bin/env python3
"""aikanzy full crawler"""
import re, json, hashlib, time, os, sys, argparse, signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from queue import Queue, Empty

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""

MEILI_URL = "http://127.0.0.1:7700"
MEILI_KEY = "5078ead29c1a6784d1b43ae67dfb1c4b17af875100bb14cb37a85dc4bbbeed03"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "aikanzy_full_progress.json")
CATEGORIES = ["dy", "dsj", "dmdh", "zy", "dj", "qt"]
CAT_NAMES = {"dy": "电影", "dsj": "电视剧", "dmdh": "动漫", "zy": "综艺", "dj": "短剧", "qt": "其他"}
BASE_URL = "https://www.aikanzy.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "zh-CN,zh;q=0.9"}
PAN_RE_STR = r'(?:https?://)?(?:www\.)?(pan\.baidu\.com/s/[a-zA-Z0-9_-]{6,}|aliyundrive\.com/s/[a-zA-Z0-9]{6,}|alipan\.com/s/[^\s"\'<>]+|pan\.quark\.cn/s/[a-zA-Z0-9]{8,}|pan\.xunlei\.com/s/[a-zA-Z0-9]+|cloud\.189\.cn/[^\s"\'<>]+|drive\.uc\.cn/[^\s"\'<>]+|115\.com/s/[^\s"\'<>]+|123pan\.com/s/[^\s"\'<>]+)'
print("Constants OK")

PAN_RE = re.compile(PAN_RE_STR, re.IGNORECASE)
PAN_TYPES = {"pan.baidu.com": "baidu", "aliyundrive.com": "aliyun", "alipan.com": "aliyun", "pan.quark.cn": "quark", "pan.xunlei.com": "xunlei", "cloud.189.cn": "tianyi", "drive.uc.cn": "uc", "115.com": "115", "123pan.com": "123"}

stop_flag = False
def on_signal(signum, frame):
    global stop_flag
    stop_flag = True
    print("\n[!] Signal received, finishing batch...", flush=True)
signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)

_session = None
def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.trust_env = False
        adapter = requests.adapters.HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=2)
        _session.mount("http://", adapter)
        _session.mount("https://", adapter)
    return _session

try:
    import pymysql
    MYSQL_POOL = Queue(maxsize=3)
    MYSQL_CONFIG = {"host": "127.0.0.1", "port": 3307, "user": "root", "password": "pansearch123", "database": "pansearch", "charset": "utf8mb4", "connect_timeout": 5}
    def get_mysql():
        try:
            conn = MYSQL_POOL.get_nowait()
            try: conn.ping(reconnect=True)
            except: conn = pymysql.connect(**MYSQL_CONFIG)
            return conn
        except Empty: return pymysql.connect(**MYSQL_CONFIG)
    def put_mysql(conn):
        try: MYSQL_POOL.put_nowait(conn)
        except: conn.close()
    for _ in range(2):
        try: MYSQL_POOL.put(pymysql.connect(**MYSQL_CONFIG))
        except: break
    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False
    print("[WARN] pymysql not installed", flush=True)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (data.get("cat_index", 0), data.get("id_start", 0), data.get("total_processed", 0), data.get("total_found", 0))
        except: pass
    return 0, 0, 0, 0

def save_progress(cat_index, id_start, total_processed, total_found):
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({"cat_index": cat_index, "id_start": id_start, "total_processed": total_processed, "total_found": total_found, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save progress: {e}", flush=True)

def extract_title(html):
    m = re.search(r"<title>(.+?)</title>", html, re.DOTALL)
    if m:
        title = m.group(1).strip()
        title = re.sub(r"\s*[-–—|]\s*爱看网.*$", "", title)
        return title[:200]
    return ""

def extract_pan_links(html):
    results = []
    seen = set()
    for m in PAN_RE.finditer(html):
        raw = m.group(0)
        domain_part = m.group(1)
        url_clean = raw if raw.startswith("http") else "https://" + raw
        if "?" not in domain_part:
            url_clean = re.sub(r"[?#].*$", "", url_clean)
        url_clean = url_clean.rstrip("'\")]>,;")
        if url_clean in seen: continue
        seen.add(url_clean)
        ptype = "others"
        for k, v in PAN_TYPES.items():
            if k in url_clean.lower(): ptype = v; break
        password = ""
        pos = m.start()
        context = html[max(0, pos-200):pos+len(m.group())+200]
        pwd_m = re.search(r"(?:密码|提取码|pwd|pass(?:word)?|访问码)[\s：:=]+([a-zA-Z0-9]{4,8})", context, re.IGNORECASE)
        if pwd_m: password = pwd_m.group(1)
        pwd_url = re.search(r"[?&]pwd=([a-zA-Z0-9]+)", url_clean)
        if pwd_url and not password: password = pwd_url.group(1)
        results.append({"url": url_clean, "password": password, "type": ptype})
    return results

def crawl_article(session, cat, aid):
    url = f"{BASE_URL}/{cat}/{aid}.html"
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 403:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            html = r.text
            if len(html) < 500:
                return None
            title = extract_title(html)
            if not title:
                return None
            pan_links = extract_pan_links(html)
            if not pan_links:
                return None
            date_m = re.search(r'"datePublished":\s*"([^"]+)"', html)
            dt = date_m.group(1) if date_m else datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
            return ({"title": title, "url": url, "datetime": dt, "cat": cat, "cat_name": CAT_NAMES.get(cat, cat)}, pan_links)
        except requests.exceptions.Timeout:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < 2:
                time.sleep(2)
                continue
            return None
    return None

def save_to_mysql(docs):
    if not docs or not HAS_MYSQL: return 0
    conn = None
    try:
        conn = get_mysql()
        cursor = conn.cursor()
        sql = "INSERT INTO resources (url, url_hash, note, password, type, source, keyword, datetime) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE note = IF(VALUES(note) != '', VALUES(note), note), updated_at = NOW()"
        inserted = 0
        for doc in docs:
            try:
                dt = doc.get("datetime", "")
                if dt: dt = dt.replace("Z", "").replace("T", " ")[:19]
                if len(dt) == 10: dt += " 00:00:00"
                else: dt = time.strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(sql, (doc["url"], doc["url_hash"], doc.get("note", "")[:500], doc.get("password", ""), doc["type"], "aikanzy", doc.get("keyword", ""), dt))
                inserted += 1
            except: pass
        conn.commit(); cursor.close()
        return inserted
    except Exception as e:
        print(f"  [MySQL] ERR: {e}", flush=True)
        return 0
    finally:
        if conn: put_mysql(conn)

def save_to_meili(docs):
    if not docs: return 0
    try:
        headers = {"Authorization": f"Bearer {MEILI_KEY}", "Content-Type": "application/json"}
        r = requests.post(f"{MEILI_URL}/indexes/resources/documents", headers=headers, json=docs, timeout=30)
        return len(docs) if r.status_code in (200, 202) else 0
    except Exception as e:
        print(f"  [Meili] ERR: {e}", flush=True)
        return 0

def main():
    parser = argparse.ArgumentParser(description="aikanzy full crawler")
    parser.add_argument("--chunk", type=int, default=500)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--start-cat", type=int, default=None)
    parser.add_argument("--start-id", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset and os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("[!] Progress reset")

    cat_idx, id_start, total_processed, total_found = load_progress()
    if args.start_cat is not None: cat_idx = args.start_cat
    if args.start_id is not None: id_start = args.start_id

    print(f"=== aikanzy full crawler {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"Chunk: {args.chunk} | Workers: {args.workers} | Delay: {args.delay}s")
    print(f"Resume: cat={CATEGORIES[cat_idx]}({cat_idx}) id_start={id_start} | Processed: {total_processed} Found: {total_found}")

    session = get_session()

    try:
        if HAS_MYSQL:
            conn = get_mysql()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM resources WHERE source='aikanzy'")
            print(f"MySQL aikanzy: {c.fetchone()[0]} records")
            put_mysql(conn)
    except Exception as e:
        print(f"MySQL check failed: {e}")

    try:
        r = session.get(f"{MEILI_URL}/indexes/resources/stats", headers={"Authorization": f"Bearer {MEILI_KEY}"}, timeout=5)
        print(f"Meilisearch: {r.json().get('numberOfDocuments', '?')} docs")
    except: pass

    MAX_ID_PER_CAT = 20000
    CONSECUTIVE_EMPTY_LIMIT = 200

    for ci in range(cat_idx, len(CATEGORIES)):
        cat = CATEGORIES[ci]
        if ci > cat_idx:
            id_start = 0
            save_progress(ci, 0, total_processed, total_found)

        consecutive_empty = 0
        aid = id_start

        while aid <= MAX_ID_PER_CAT and not stop_flag:
            batch_start = aid
            batch_end = min(aid + args.chunk, MAX_ID_PER_CAT + 1)
            batch_ids = list(range(batch_start, batch_end))

            print(f"\n[{cat}/{CAT_NAMES[cat]}] IDs {batch_start}-{batch_end-1} ...", flush=True)
            t0 = time.time()

            all_docs = []
            batch_processed = 0
            batch_found = 0

            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {}
                for bid in batch_ids:
                    if stop_flag: break
                    time.sleep(args.delay / max(args.workers, 1))
                    futures[executor.submit(crawl_article, session, cat, bid)] = bid

                for future in as_completed(futures):
                    if stop_flag: break
                    bid = futures[future]
                    try: result = future.result(timeout=30)
                    except: result = None
                    batch_processed += 1
                    if result is None:
                        consecutive_empty += 1
                    else:
                        consecutive_empty = 0
                        article_data, pan_links = result
                        batch_found += 1
                        for pl in pan_links:
                            url_hash = hashlib.md5(pl["url"].encode()).hexdigest()
                            all_docs.append({"url_hash": url_hash, "url": pl["url"], "note": article_data["title"][:500], "password": pl.get("password", ""), "datetime": article_data["datetime"], "type": pl["type"], "source": "aikanzy", "keyword": f"{article_data['cat_name']}/{article_data['title'][:50]}"})
                    if batch_processed % 50 == 0:
                        print(f"  ... {batch_processed}/{len(batch_ids)} done, {batch_found} articles, {len(all_docs)} links", flush=True)

            seen = set()
            unique_docs = [d for d in all_docs if d["url_hash"] not in seen and not seen.add(d["url_hash"])]

            if unique_docs:
                mysql_n = save_to_mysql(unique_docs)
                meili_n = save_to_meili(unique_docs)
                total_found += batch_found
                print(f"  OK {batch_found} articles -> {len(unique_docs)} links | MySQL:{mysql_n} Meili:{meili_n} ({time.time()-t0:.1f}s)", flush=True)
            else:
                print(f"  -- 0 articles ({time.time()-t0:.1f}s)", flush=True)

            total_processed += batch_processed
            aid = batch_end
            save_progress(ci, aid, total_processed, total_found)

            if consecutive_empty >= CONSECUTIVE_EMPTY_LIMIT:
                print(f"[!] {CONSECUTIVE_EMPTY_LIMIT} consecutive empty, next category", flush=True)
                break

            if stop_flag: break
        if stop_flag: break

    print(f"\n=== DONE ===")
    print(f"Total processed: {total_processed} | Articles found: {total_found}")

    if HAS_MYSQL:
        try:
            conn = get_mysql()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM resources WHERE source='aikanzy'")
            print(f"MySQL aikanzy total: {c.fetchone()[0]} records")
            put_mysql(conn)
        except: pass

if __name__ == "__main__":
    main()
