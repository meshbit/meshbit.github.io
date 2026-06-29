#!/usr/bin/env python3
"""
凌云搜索 - 文档平台爬虫
语雀 Notion 飞书 HackMD 腾讯文档 石墨文档
大量公开文档，整理好的资源合集，竞争空白
"""
import re, sys, os
from crawler_base import *
from urllib.parse import quote

# ============================================================
# 语雀公开文档
# ============================================================
def scrape_yuque(keyword):
    """搜索语雀公开知识库"""
    results = []
    try:
        url = f'https://www.yuque.com/search?q={quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, f'语雀:{keyword}'))
    except Exception as e:
        print(f'  [语雀] ERR: {e}', flush=True)
    return results

def scrape_yuque_public():
    """抓取语雀公开文档广场"""
    results = []
    try:
        url = 'https://www.yuque.com/explore'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, '语雀广场'))
    except Exception as e:
        print(f'  [语雀广场] ERR: {e}', flush=True)
    return results

# ============================================================
# Notion 公开页
# ============================================================
NOTION_QUERIES = [
    '资源导航', '网盘资源', '软件推荐', '工具合集',
    '电影资源', '书籍资源', '学习资料',
]

def scrape_notion_public():
    """抓取 Notion 公开分享页"""
    results = []
    try:
        # Notion 没有统一搜索 API，用 Google 搜
        for q in NOTION_QUERIES:
            url = f'https://www.google.com/search?q=site:notion.so+{quote(q)}'
            resp = get_with_retry(url)
            if resp:
                # 提取 notion.so 链接
                notion_links = re.findall(r'https?://[^\s"\'<>]*?notion\.so/[^\s"\'<>]+', resp.text)
                for link in set(notion_links[:5]):
                    time.sleep(0.3)
                    detail = get_with_retry(link)
                    if detail:
                        results.extend(extract_links(detail.text, f'Notion:{q}'))
    except Exception as e:
        print(f'  [Notion] ERR: {e}', flush=True)
    return results

# ============================================================
# 飞书公开文档
# ============================================================
def scrape_feishu_public():
    """抓取飞书公开文档"""
    results = []
    try:
        for q in ['资源', '网盘', '工具']:
            url = f'https://www.google.com/search?q=site:feishu.cn+{quote(q)}'
            resp = get_with_retry(url)
            if resp:
                links = re.findall(r'https?://[^\s"\'<>]*?feishu\.cn/[^\s"\'<>]+', resp.text)
                for link in set(links[:5]):
                    time.sleep(0.3)
                    detail = get_with_retry(link)
                    if detail:
                        results.extend(extract_links(detail.text, f'飞书:{q}'))
    except Exception as e:
        print(f'  [飞书] ERR: {e}', flush=True)
    return results

# ============================================================
# HackMD 公开 Markdown
# ============================================================
def scrape_hackmd(keyword):
    """抓取 HackMD 公开文档"""
    results = []
    try:
        url = f'https://hackmd.io/api/overview/recent?sort=title'
        resp = get_with_retry(url, headers={**HEADERS, 'Accept': 'application/json'})
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                for item in data[:20]:
                    title = item.get('title', '')
                    if keyword.lower() in title.lower():
                        pid = item.get('id', '')
                        detail_url = f'https://hackmd.io/{pid}'
                        detail = get_with_retry(detail_url)
                        if detail:
                            results.extend(extract_links(detail.text, f'HackMD:{title}'))
            except:
                pass
    except Exception as e:
        print(f'  [HackMD] ERR: {e}', flush=True)
    return results

# ============================================================
# 腾讯文档 / 石墨文档 — 通过搜索
# ============================================================
def scrape_tencent_docs(keyword):
    results = []
    try:
        url = f'https://www.google.com/search?q=site:docs.qq.com+{quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, f'腾讯文档:{keyword}'))
    except Exception as e:
        print(f'  [腾讯文档] ERR: {e}', flush=True)
    return results

def scrape_shimo_docs(keyword):
    results = []
    try:
        url = f'https://www.google.com/search?q=site:shimo.im+{quote(keyword + " 网盘")}'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, f'石墨:{keyword}'))
    except Exception as e:
        print(f'  [石墨] ERR: {e}', flush=True)
    return results

# ============================================================
SOURCES = [
    ('yuque', lambda kw: scrape_yuque(kw)),
    ('hackmd', scrape_hackmd),
    ('tencent', scrape_tencent_docs),
    ('shimo', scrape_shimo_docs),
]

BULK_SOURCES = [
    ('yuque_public', scrape_yuque_public),
    ('notion', scrape_notion_public),
    ('feishu', scrape_feishu_public),
]

def crawl_keyword(keyword):
    all_results = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fn, keyword): name for name, fn in SOURCES if fn}
        for f in as_completed(futures, timeout=20):
            try:
                all_results.extend(f.result(timeout=15))
            except:
                pass
    seen, unique = set(), []
    for r in all_results:
        h = r.get('url_hash', hashlib.md5(r['url'].encode()).hexdigest())
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique

def crawl_bulk():
    """全量爬取（不需要关键词的）"""
    all_results = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fn): name for name, fn in BULK_SOURCES}
        for f in as_completed(futures, timeout=30):
            name = futures[f]
            try:
                r = f.result(timeout=25)
                all_results.extend(r)
                print(f'  [{name}] {len(r)}条', flush=True)
            except Exception as e:
                print(f'  [{name}] ERR: {e}', flush=True)
    seen, unique = set(), []
    for r in all_results:
        h = r.get('url_hash', hashlib.md5(r['url'].encode()).hexdigest())
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique

if __name__ == '__main__':
    if '--bulk' in sys.argv:
        print('[文档全量] 开始...', flush=True)
        docs = crawl_bulk()
        print(f'[文档全量] {len(docs)}条', flush=True)
        if docs:
            save_all(docs)
    else:
        kw = sys.argv[1] if len(sys.argv) > 1 else '测试'
        print(f'[文档平台] 搜索: {kw}', flush=True)
        docs = crawl_keyword(kw)
        print(f'[文档平台] 结果: {len(docs)}条', flush=True)
        if docs:
            save_all(docs)
