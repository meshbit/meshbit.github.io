#!/usr/bin/env python3
import re, json, hashlib, time, os, sys, argparse
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

for k in ["HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"]:
    os.environ.pop(k,None)

import requests

# Import from crawler_base
from crawler_base import (
    PAN_LINK_RE, PAN_TYPES, HEADERS,
    MEILI_URL, MEILI_KEY,
    parse_type, extract_links as base_extract_links,
    save_to_meili,
    save_all
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

BILIBILI_KEYWORDS = [
    "百度网盘",
    "阿里云盘",
    "夸克网盘",
    "迅雷云盘",
    "天翼云盘",
    "115网盘",
    "123网盘",
    "蓝奏云",
    "mega网盘",
    "资源分享",
    "资源下载",
    "学习资源",
    "软件资源",
    "影视资源",
    "漫画资源",
    "小说资源",
    "课程资源",
    "4K资源",
    "1080P",
    "2160P",
    "蓝光",
    "高清资源",
    "合集",
    "全集",
    "完整版",
    "未删减",
    "电子书",
    "教程",
    "破解版",
    "绿色版",
    "Photoshop",
    "Python教程",
    "考研资料",
    "周杰伦",
    "动漫资源",
    "纪录片资源",
    "电影资源",
]

def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    })
    s.trust_env = False
    return s

def get_local_session():
    s = requests.Session()
    s.trust_env = False
    return s

def search_bilibili(keyword, page=1, page_size=20):
    sess = get_session()
    encoded_kw = quote(keyword)
    url = "https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=" + encoded_kw + "&page=" + str(page) + "&page_size=" + str(page_size)
    try:
        resp = sess.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if data.get("code") != 0:
            return []
        return data.get("data", {}).get("result", [])
    except:
        return []

def get_video_desc(bvid):
    sess = get_session()
    url = "https://api.bilibili.com/x/web-interface/view?bvid=" + bvid
    try:
        resp = sess.get(url, timeout=10)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        if data.get("code") != 0:
            return ""
        return data.get("data", {}).get("desc", "")
    except:
        return ""

def process_video(video, keyword):
    results = []
    bvid = video.get("bvid", "")
    title = video.get("title", "")
    import re as _re
    title = _re.sub(r"<[^>]+>", "", title)
    desc = video.get("description", "")
    author = video.get("author", "")
    tag = video.get("tag", "")
    tag_list = tag.split(",") if tag else []
    all_text = title + chr(10) + desc + chr(10) + " ".join(tag_list)
    if len(desc) < 80 and bvid:
        time.sleep(0.3)
        full_desc = get_video_desc(bvid)
        if full_desc:
            all_text += chr(10) + full_desc
    note = "B站-" + author + ": " + title[:150]
    links = base_extract_links(all_text, note)
    for link in links:
        link["source"] = "bilibili"
    return links

def get_storage_stats():
    stats = {}
    try:
        import pymysql
        conn = pymysql.connect(host="127.0.0.1", port=3307, user="root",
                               password="pansearch123", database="pansearch",
                               charset="utf8mb4", connect_timeout=5)
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COUNT(DISTINCT keyword) FROM resources")
        cnt, kws = c.fetchone()
        stats["mysql"] = {"total": cnt, "unique_keywords": kws}
        conn.close()
    except:
        stats["mysql"] = None
    try:
        r = get_local_session().get(
            MEILI_URL + "/indexes/resources/stats",
            headers={"Authorization": "Bearer " + MEILI_KEY}, timeout=5)
        stats["meili"] = r.json().get("numberOfDocuments", 0)
    except:
        stats["meili"] = None
    try:
        stats["es"] = r.json().get("count", 0)
    except:
        stats["es"] = None
    return stats
def main():
    parser = argparse.ArgumentParser(description="B站UP主资源抓取")
    parser.add_argument("--chunk", type=int, default=100)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=== B站UP主资源抓取 " + ts + " ===")
    print("Chunk: " + str(args.chunk) + " | Delay: " + str(args.delay) + "s", flush=True)

    stats_before = get_storage_stats()
    mb = stats_before.get("mysql", {})
    mysql_before = mb.get("total", 0) if mb else 0
    print("MySQL初始: " + str(mysql_before), flush=True)

    progress_file = os.path.join(SCRIPT_DIR, "bilibili_progress.json")
    start_idx = 0
    if not args.reset and os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                p = json.load(f)
            start_idx = p.get("last_index", 0)
        except:
            pass

    total_kws = len(BILIBILI_KEYWORDS)
    chunk = min(args.chunk, total_kws)
    end_idx = min(start_idx + chunk, total_kws)
    batch_kws = BILIBILI_KEYWORDS[start_idx:end_idx]
    print("关键词: " + str(start_idx+1) + "-" + str(end_idx) + "/" + str(total_kws) + " (" + str(len(batch_kws)) + ")", flush=True)

    all_docs = []
    seen_urls = set()

    for i, kw in enumerate(batch_kws):
        if i % 5 == 0:
            print("  [" + str(i+1) + "/" + str(len(batch_kws)) + "] " + kw, flush=True)
        videos = search_bilibili(kw)
        if not videos:
            time.sleep(args.delay)
            continue
        kw_count = 0
        for video in videos[:10]:
            try:
                links = process_video(video, kw)
                for link in links:
                    if link["url_hash"] not in seen_urls:
                        seen_urls.add(link["url_hash"])
                        all_docs.append(link)
                        kw_count += 1
            except:
                pass
            time.sleep(0.3)
        if kw_count > 0:
            print("  [" + str(i+1) + "] " + kw + " => " + str(kw_count) + " links", flush=True)
        time.sleep(args.delay)

    print("")
    print("提取 " + str(len(all_docs)) + " 条去重链接", flush=True)
    if all_docs:
        for i in range(0, len(all_docs), 50):
            save_all(all_docs[i:i+50])

    new_last = end_idx if end_idx < total_kws else 0
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump({"last_index": new_last, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=2)

    time.sleep(1)
    stats_after = get_storage_stats()
    ma = stats_after.get("mysql", {})
    mysql_after = ma.get("total", 0) if ma else 0
    mysql_new = mysql_after - mysql_before

    print("")
    print("=" * 60)
    print("B站UP主资源抓取报告")
    print("=" * 60)
    print("时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("搜索关键词: " + str(len(batch_kws)))
    print("提取链接: " + str(len(all_docs)) + " (去重)")
    print("MySQL新增: " + str(mysql_new))
    print("[存储] MySQL:" + str(mysql_after) + " Meili:" + str(stats_after.get("meili","N/A")) + " ES:" + str(stats_after.get("es","N/A")))
    print("=" * 60)
    print("[完成]")

if __name__ == "__main__":
    main()