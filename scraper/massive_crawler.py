#!/usr/bin/env python3
import json, hashlib, time, requests, sys, os, argparse, signal
from datetime import datetime
from queue import Queue, Empty

os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""

MEILI_URL = "http://127.0.0.1:7700"
MEILI_KEY = "5078ead29c1a6784d1b43ae67dfb1c4b17af875100bb14cb37a85dc4bbbeed03"
PROXY_API = "http://localhost:5003/api/search"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.path.join(SCRIPT_DIR, "keywords_massive.json")
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "massive_progress.json")

halt = False
def on_signal(signum, frame):
    global halt
    halt = True
    print(chr(10) + "[!] Signal received, finishing batch...", flush=True)
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
            return data.get("last_index", 0), data.get("total_processed", 0), data.get("round", 0)
        except: pass
    return 0, 0, 0

def save_progress(last_index, total_processed, round_num):
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_index": last_index, "total_processed": total_processed, "round": round_num, "updated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] save progress: {e}", flush=True)

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
                if dt:
                    dt = dt.replace("Z", "").replace("T", " ")
                    if len(dt) == 10: dt += " 00:00:00"
                else: dt = time.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(sql, (doc["url"], doc["url_hash"], doc["note"], doc["password"], doc["type"], doc.get("source", "pansou"), doc.get("keyword", ""), dt))
                inserted += 1
            except: pass
        conn.commit()
        cursor.close()
        return inserted
    except Exception as e:
        print(f"  [MySQL] ERROR: {e}", flush=True)
        return 0
    finally:
        if conn: put_mysql(conn)

def search_and_index(keyword):
    try:
        sess = get_session()
        resp = sess.get(f"{PROXY_API}?kw={keyword}", timeout=120)
        data = resp.json().get("data", {}).get("merged_by_type", {})
        docs = []
        seen = set()
        for ptype, items in data.items():
            for item in items:
                url = item.get("url", "").strip()
                if not url: continue
                url_hash = hashlib.md5(url.encode()).hexdigest()
                if url_hash in seen: continue
                seen.add(url_hash)
                docs.append({"url_hash": url_hash, "url": url, "note": item.get("note", "")[:500], "password": item.get("password", ""), "datetime": item.get("datetime", ""), "type": ptype, "source": "pansou", "keyword": keyword})
        if docs:
            meili_headers = {"Authorization": f"Bearer {MEILI_KEY}", "Content-Type": "application/json"}
            try: sess.post(f"{MEILI_URL}/indexes/resources/documents", headers=meili_headers, json=docs, timeout=30)
            except: pass
            mysql_count = save_to_mysql(docs)
            return len(docs), mysql_count
        else: return 0, 0
    except: return 0, 0

def get_storage_stats():
    stats = {}
    if HAS_MYSQL:
        try:
            conn = get_mysql()
            c = conn.cursor()
            c.execute("SELECT COUNT(*), COUNT(DISTINCT keyword) FROM resources")
            cnt, kws = c.fetchone()
            stats["mysql"] = {"total": cnt, "unique_keywords": kws}
            put_mysql(conn)
        except: stats["mysql"] = None
    try:
        r = requests.get(f"{MEILI_URL}/indexes/resources/stats", headers={"Authorization": f"Bearer {MEILI_KEY}"}, timeout=5)
        stats['meili'] = r.json().get("numberOfDocuments", 0)
    except: stats['meili'] = None
    return stats

def print_summary(total_processed, round_new_docs):
    hdr = "=" * 60
    print(f"{chr(10)}{hdr}{chr(10)}End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{chr(10)}Round new: {round_new_docs}{chr(10)}Total processed: {total_processed}{chr(10)}[Storage]")
    stats = get_storage_stats()
    m = stats.get("mysql")
    if m:
        print(f"  MySQL: {m['total']} rows / {m['unique_keywords']} keywords")
    print(f"  Meilisearch: {stats['meili']} docs")
    print(hdr)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk", type=int, default=5000)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    print(f"=== Massive Warmer {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"Chunk: {args.chunk} | Delay: {args.delay}s", flush=True)
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            keywords = json.load(f)
    except FileNotFoundError:
        alt = "D:/" + chr(32593) + chr(31449) + "/" + chr(20940) + chr(20113) + chr(25628) + chr(32034) + "/scraper/keywords_massive.json"
        with open(alt, "r", encoding="utf-8") as f:
            keywords = json.load(f)
    total_keywords = len(keywords)
    print(f"Total keywords: {total_keywords}", flush=True)
    if args.reset:
        last_index = 0; total_processed = 0; round_num = 0
        save_progress(0, 0, 0)
    elif args.start is not None:
        last_index = args.start; total_processed = 0; round_num = 0
    else:
        last_index, total_processed, round_num = load_progress()
        if last_index > 0:
            print(f"Resume: idx={last_index}, processed={total_processed}, round={round_num+1}")
        else: print("Fresh start")
    round_new_docs = 0
    while not halt:
        actual_start = last_index
        end_index = min(last_index + args.chunk, total_keywords)
        batch_kws = keywords[actual_start:end_index]
        if not batch_kws:
            round_num += 1; last_index = 0; round_new_docs = 0
            save_progress(0, total_processed, round_num)
            print(f"{chr(10)}=== Round {round_num} complete! Total processed: {total_processed} ===")
            continue
        batch_size = len(batch_kws)
        print(f"{chr(10)}--- Round {round_num+1} [{actual_start+1}-{end_index}/{total_keywords}] {batch_size}w ---")
        print(f"Start: {datetime.now().strftime('%H:%M:%S')}")
        batch_start = time.time()
        batch_docs = 0; batch_mysql = 0; success_count = 0; zero_count = 0; err_count = 0
        for i, kw in enumerate(batch_kws):
            if halt:
                save_progress(actual_start + i, total_processed, round_num)
                print(f"{chr(10)}[!] Interrupted. Resume at idx={actual_start + i + 1}")
                print_summary(total_processed, round_new_docs)
                return
            docs, mysql_count = search_and_index(kw)
            total_processed += 1; round_new_docs += docs; batch_docs += docs; batch_mysql += mysql_count
            if docs > 0: success_count += 1
            elif mysql_count == 0: zero_count += 1
            else: err_count += 1
            if (i + 1) % 100 == 0 or i == batch_size - 1:
                elapsed = time.time() - batch_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                pct = (actual_start + i + 1) / total_keywords * 100
                print(f"  [{actual_start+i+1}/{total_keywords} {pct:.1f}%] new={batch_docs} rate={rate:.1f}w/s hit={success_count} miss={zero_count} err={err_count}", flush=True)
            time.sleep(args.delay)
        batch_elapsed = time.time() - batch_start
        print(f"Batch done! {batch_elapsed:.1f}s | New: {batch_docs} (MySQL:{batch_mysql}) | Hit:{success_count} Miss:{zero_count} Err:{err_count}")
        last_index = end_index
        if last_index >= total_keywords: last_index = 0; round_num += 1
        save_progress(last_index, total_processed, round_num)
        stats = get_storage_stats()
        print(f"[Storage] MySQL: {stats['mysql']} | Meili: {stats['meili']} | ES: {stats['es']}")
    print_summary(total_processed, round_new_docs)

if __name__ == "__main__":
    main()
