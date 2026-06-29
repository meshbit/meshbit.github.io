#!/usr/bin/env python3
"""
凌云搜索 - 网盘直爬
阿里云盘/夸克/天翼/UC/迅雷/123/蓝奏 — 从分享广场直接爬
"""
import re, sys, os
from crawler_base import *
from urllib.parse import quote

# ============================================================
# 阿里云盘资源广场
# ============================================================
def scrape_aliyun_share():
    """阿里云盘公开分享浏览"""
    results = []
    try:
        # 阿里云盘资源广场
        urls = [
            'https://www.aliyundrive.com/discover',
            f'https://api.aliyundrive.com/adrive/v4/share/list?pageSize=50&page=1',
        ]
        for url in urls:
            resp = get_with_retry(url)
            if resp:
                results.extend(extract_links(resp.text, '阿里资源广场'))
                time.sleep(0.5)
    except Exception as e:
        print(f'  [阿里] ERR: {e}', flush=True)
    return results

# ============================================================
# 夸克网盘资源广场
# ============================================================
def scrape_quark_share():
    """夸克公开分享浏览"""
    results = []
    try:
        urls = [
            'https://pan.quark.cn/share',
            'https://pan.quark.cn/list#/share',
        ]
        for url in urls:
            resp = get_with_retry(url)
            if resp:
                results.extend(extract_links(resp.text, '夸克分享广场'))
                time.sleep(0.5)
    except Exception as e:
        print(f'  [夸克] ERR: {e}', flush=True)
    return results

# ============================================================
# 天翼云盘分享
# ============================================================
def scrape_tianyi_share():
    results = []
    try:
        url = 'https://cloud.189.cn/share'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, '天翼分享'))
    except Exception as e:
        print(f'  [天翼] ERR: {e}', flush=True)
    return results

# ============================================================
# UC网盘资源
# ============================================================
def scrape_uc_share():
    results = []
    try:
        url = 'https://drive.uc.cn/share'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, 'UC分享'))
    except Exception as e:
        print(f'  [UC] ERR: {e}', flush=True)
    return results

# ============================================================
# 迅雷云盘分享
# ============================================================
def scrape_xunlei_share():
    results = []
    try:
        url = 'https://pan.xunlei.com/share'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, '迅雷分享'))
    except Exception as e:
        print(f'  [迅雷] ERR: {e}', flush=True)
    return results

# ============================================================
# 123云盘
# ============================================================
def scrape_123pan_share():
    results = []
    try:
        url = 'https://www.123pan.com/share'
        resp = get_with_retry(url)
        if resp:
            results.extend(extract_links(resp.text, '123分享'))
    except Exception as e:
        print(f'  [123] ERR: {e}', flush=True)
    return results

# ============================================================
# 蓝奏云最新
# ============================================================
def scrape_lanzou_recent():
    results = []
    try:
        urls = [
            'https://www.lanzou.com',
            'https://www.lanzous.com',
        ]
        for url in urls:
            resp = get_with_retry(url)
            if resp:
                results.extend(extract_links(resp.text, '蓝奏云'))
                time.sleep(0.5)
    except Exception as e:
        print(f'  [蓝奏] ERR: {e}', flush=True)
    return results

# ============================================================
SOURCES = [
    ('aliyun', scrape_aliyun_share),
    ('quark', scrape_quark_share),
    ('tianyi', scrape_tianyi_share),
    ('uc', scrape_uc_share),
    ('xunlei', scrape_xunlei_share),
    ('123pan', scrape_123pan_share),
    ('lanzou', scrape_lanzou_recent),
]

if __name__ == '__main__':
    print('[网盘直爬] 开始...', flush=True)
    all_results = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fn): name for name, fn in SOURCES}
        for f in as_completed(futures, timeout=20):
            name = futures[f]
            try:
                r = f.result(timeout=15)
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
    print(f'[网盘直爬] 总计: {len(unique)}条', flush=True)
    if unique:
        save_all(unique)
