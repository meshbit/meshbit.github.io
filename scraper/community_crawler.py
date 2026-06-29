#!/usr/bin/env python3
"""
凌云搜索 - 中文社区爬虫
V2EX 简书 掘金 少数派 酷安 NGA 吾爱 贴吧 博客园
纯 HTTP 请求，无反爬或反爬弱
"""
import re, sys, os
from crawler_base import *
from urllib.parse import quote

# ============================================================
# V2EX — 技术论坛，软件资源多
# ============================================================
def scrape_v2ex(keyword):
    results = []
    try:
        url = f'https://www.v2ex.com/search?q={quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if not resp:
            return results
        # 取搜索结果帖子链接
        post_ids = re.findall(r'/t/(\d+)', resp.text)
        visited = set()
        for pid in post_ids[:5]:
            if pid in visited:
                continue
            visited.add(pid)
            time.sleep(0.3)
            detail = get_with_retry(f'https://www.v2ex.com/t/{pid}')
            if detail:
                results.extend(extract_links(detail.text, f'V2EX:{keyword}'))
    except Exception as e:
        print(f'  [V2EX] ERR: {e}', flush=True)
    return results

# ============================================================
# 简书 — 资源博客，反爬比CSDN弱
# ============================================================
def scrape_jianshu(keyword):
    results = []
    try:
        url = f'https://www.jianshu.com/search?q={quote(keyword + " 网盘")}&page=1&type=note'
        resp = get_with_retry(url)
        if not resp:
            return results
        results.extend(extract_links(resp.text, f'简书:{keyword}'))
    except Exception as e:
        print(f'  [简书] ERR: {e}', flush=True)
    return results

# ============================================================
# 掘金 — 技术社区
# ============================================================
def scrape_juejin(keyword):
    results = []
    try:
        url = f'https://api.juejin.cn/search_api/v2/search'
        payload = {"query": keyword + " 网盘", "page": 1, "page_size": 10}
        resp = get_session().post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            return results
        data = resp.json()
        for item in data.get('data', []):
            content = item.get('article_info', {}).get('content', '')
            results.extend(extract_links(content, f'掘金:{keyword}'))
    except Exception as e:
        print(f'  [掘金] ERR: {e}', flush=True)
    return results

# ============================================================
# 少数派 — Mac/效率工具资源
# ============================================================
def scrape_sspai(keyword):
    results = []
    try:
        url = f'https://sspai.com/search/article?q={quote(keyword)}'
        resp = get_with_retry(url)
        if not resp:
            return results
        article_ids = re.findall(r'/post/(\d+)', resp.text)
        for aid in set(article_ids[:5]):
            time.sleep(0.3)
            detail = get_with_retry(f'https://sspai.com/post/{aid}')
            if detail:
                results.extend(extract_links(detail.text, f'少数派:{keyword}'))
    except Exception as e:
        print(f'  [少数派] ERR: {e}', flush=True)
    return results

# ============================================================
# 酷安 — Android社区
# ============================================================
def scrape_coolapk(keyword):
    results = []
    try:
        url = f'https://www.coolapk.com/search?q={quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if not resp:
            return results
        results.extend(extract_links(resp.text, f'酷安:{keyword}'))
    except Exception as e:
        print(f'  [酷安] ERR: {e}', flush=True)
    return results

# ============================================================
# NGA — 游戏/影视板块资源
# ============================================================
def scrape_nga(keyword):
    results = []
    try:
        # NGA 178
        url = f'https://bbs.nga.cn/search.php?key={quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if not resp:
            return results
        results.extend(extract_links(resp.text, f'NGA:{keyword}'))
    except Exception as e:
        print(f'  [NGA] ERR: {e}', flush=True)
    return results

# ============================================================
# 吾爱破解 — 软件资源质量极高
# ============================================================
def scrape_52pojie(keyword):
    results = []
    try:
        url = f'https://www.52pojie.cn/search.php?searchsubmit=yes&kw={quote(keyword)}'
        resp = get_with_retry(url)
        if not resp:
            return results
        thread_ids = re.findall(r'thread-(\d+)-', resp.text)
        for tid in set(thread_ids[:5]):
            time.sleep(0.3)
            detail = get_with_retry(f'https://www.52pojie.cn/thread-{tid}-1-1.html')
            if detail:
                results.extend(extract_links(detail.text, f'吾爱:{keyword}'))
    except Exception as e:
        print(f'  [吾爱] ERR: {e}', flush=True)
    return results

# ============================================================
# 贴吧 — 最大中文资源社区
# ============================================================
def scrape_tieba(keyword):
    results = []
    try:
        url = f'https://tieba.baidu.com/f/search/res?qw={quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if not resp:
            return results
        results.extend(extract_links(resp.text, f'贴吧:{keyword}'))
    except Exception as e:
        print(f'  [贴吧] ERR: {e}', flush=True)
    return results

# ============================================================
# 博客园 — 老牌技术博客
# ============================================================
def scrape_cnblogs(keyword):
    results = []
    try:
        url = f'https://zzk.cnblogs.com/s?w={quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if not resp:
            return results
        results.extend(extract_links(resp.text, f'博客园:{keyword}'))
    except Exception as e:
        print(f'  [博客园] ERR: {e}', flush=True)
    return results

# ============================================================
SOURCES = [
    ('v2ex', scrape_v2ex),
    ('jianshu', scrape_jianshu),
    ('juejin', scrape_juejin),
    ('sspai', scrape_sspai),
    ('coolapk', scrape_coolapk),
    ('nga', scrape_nga),
    ('52pojie', scrape_52pojie),
    ('tieba', scrape_tieba),
    ('cnblogs', scrape_cnblogs),
]

def crawl_keyword(keyword):
    """爬单个关键词，返回去重结果"""
    all_results = []
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fn, keyword): name for name, fn in SOURCES}
        for f in as_completed(futures):
            name = futures.get(f, '?')
            try:
                all_results.extend(f.result(timeout=10))
            except TimeoutError:
                pass
            except Exception:
                pass

    # URL 去重
    seen, unique = set(), []
    for r in all_results:
        h = r.get('url_hash', hashlib.md5(r['url'].encode()).hexdigest())
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique

if __name__ == '__main__':
    kw = sys.argv[1] if len(sys.argv) > 1 else '测试'
    print(f'[Community] 搜索: {kw}', flush=True)
    docs = crawl_keyword(kw)
    print(f'[Community] 结果: {len(docs)}条', flush=True)
    if docs:
        save_all(docs)
