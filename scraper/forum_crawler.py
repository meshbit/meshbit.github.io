#!/usr/bin/env python3
"""
凌云搜索 - 论坛爬虫
Chiphell Stage1st Hostloc
纯 HTTP 解析，反爬弱
"""
import re, sys, os
from crawler_base import *
from urllib.parse import quote

# ============================================================
# Chiphell — 硬件/软件资源
# ============================================================
def scrape_chiphell(keyword):
    results = []
    try:
        url = f'https://www.chiphell.com/search.php?mod=forum&searchsubmit=yes&srchtxt={quote(keyword)}'
        resp = get_with_retry(url)
        if not resp:
            return results
        thread_ids = re.findall(r'thread-(\d+)-', resp.text)
        for tid in set(thread_ids[:5]):
            time.sleep(0.3)
            detail = get_with_retry(f'https://www.chiphell.com/thread-{tid}-1-1.html')
            if detail:
                results.extend(extract_links(detail.text, f'Chiphell:{keyword}'))
    except Exception as e:
        print(f'  [Chiphell] ERR: {e}', flush=True)
    return results

# ============================================================
# Stage1st — ACG社区，动漫资源
# ============================================================
def scrape_s1(keyword):
    results = []
    try:
        url = f'https://bbs.saraba1st.com/2b/search.php?searchsubmit=yes&kw={quote(keyword)}'
        resp = get_with_retry(url)
        if not resp:
            return results
        results.extend(extract_links(resp.text, f'Stage1st:{keyword}'))
    except Exception as e:
        print(f'  [S1] ERR: {e}', flush=True)
    return results

# ============================================================
# Hostloc — 站长圈，工具类资源
# ============================================================
def scrape_hostloc(keyword):
    results = []
    try:
        url = f'https://hostloc.com/search.php?mod=forum&searchsubmit=yes&srchtxt={quote(keyword)}'
        resp = get_with_retry(url)
        if not resp:
            return results
        thread_ids = re.findall(r'thread-(\d+)-', resp.text)
        for tid in set(thread_ids[:5]):
            time.sleep(0.3)
            detail = get_with_retry(f'https://hostloc.com/thread-{tid}-1-1.html')
            if detail:
                results.extend(extract_links(detail.text, f'Hostloc:{keyword}'))
    except Exception as e:
        print(f'  [Hostloc] ERR: {e}', flush=True)
    return results

# ============================================================
SOURCES = [
    ('chiphell', scrape_chiphell),
    ('s1', scrape_s1),
    ('hostloc', scrape_hostloc),
]

if __name__ == '__main__':
    kw = sys.argv[1] if len(sys.argv) > 1 else '测试'
    print(f'[论坛] 搜索: {kw}', flush=True)
    all_results = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fn, kw): name for name, fn in SOURCES}
        for f in as_completed(futures, timeout=20):
            name = futures[f]
            try:
                r = f.result(timeout=15)
                all_results.extend(r)
                print(f'  [{name}] {len(r)}条', flush=True)
            except:
                pass
    seen, unique = set(), []
    for r in all_results:
        h = r.get('url_hash', hashlib.md5(r['url'].encode()).hexdigest())
        if h not in seen:
            seen.add(h)
            unique.append(r)
    print(f'[论坛] 总计: {len(unique)}条', flush=True)
    if unique:
        save_all(unique)
