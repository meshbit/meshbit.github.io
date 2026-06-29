#!/usr/bin/env python3
"""
凌云搜索网盘链接失效检测器
从 Meilisearch 抽取样本 URL，并发检测失效情况，写 link_status.json
用法: python check_dead_links.py [--sample N] [--workers W] [--timeout T]
"""

import requests
import json
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from collections import Counter

MEILI_KEY = 'pansou-meili-key'
MEILI_URL = 'http://localhost:7700'
STATUS_FILE = r'D:\proxy\link_status.json'

# 网盘服务通常的特征码 — 即使返回 200 也是失效的
DEAD_PATTERNS = [
    '分享的文件已经被取消',
    '分享的文件已经被删除',
    '分享已过期',
    '分享已失效',
    '链接已失效',
    '文件已删除',
    '你来晚了',
    '已被删除',
    '分享文件不存在',
    '页面不存在',
    '该分享已被取消',
    '分享链接已过期',
    '文件已被上传者删除',
    '该链接已超过有效期',
    '哦豁，页面跑丢了',
    '文件暂时无法访问',
    '此链接分享内容可能因为涉及',
    '分享者已取消分享',
    '啊哦，你来晚了',
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def check_url(url, timeout=10):
    """检查单个 URL 是否有效，返回 (url, status, detail)"""
    try:
        # 跳过非 HTTP URL
        if not url.startswith('http'):
            return (url, 'skip', 'non-http')

        # 尝试 HEAD 先
        try:
            resp = requests.head(url, timeout=timeout, headers=HEADERS,
                                 allow_redirects=True, verify=False)
        except:
            # HEAD 失败降级 GET
            resp = requests.get(url, timeout=timeout, headers=HEADERS,
                                allow_redirects=True, verify=False, stream=True)

        status_code = resp.status_code

        # 明确的错误状态码
        if status_code in (404, 410):
            return (url, 'dead', f'HTTP {status_code}')
        if status_code >= 500:
            return (url, 'dead', f'HTTP {status_code}')
        if status_code == 403:
            # 403 可能是反爬，不算 dead
            return (url, 'unknown', f'HTTP 403 (可能反爬)')

        # 对于 200，检查页面内容是否包含失效特征
        if status_code == 200:
            content = resp.text[:3000] if hasattr(resp, 'text') else ''
            for pattern in DEAD_PATTERNS:
                if pattern in content:
                    return (url, 'dead', f'内容匹配: {pattern}')
            resp.close()
            return (url, 'ok', f'HTTP 200')

        return (url, 'unknown', f'HTTP {status_code}')

    except requests.exceptions.Timeout:
        return (url, 'dead', '超时')
    except requests.exceptions.ConnectionError as e:
        return (url, 'dead', f'连接失败: {str(e)[:50]}')
    except requests.exceptions.SSLError:
        return (url, 'unknown', 'SSL错误')
    except Exception as e:
        return (url, 'unknown', f'异常: {str(e)[:50]}')


def get_sample_urls(sample_size=500):
    """从 Meilisearch 随机取样 unique URLs"""
    seen = set()
    urls = []
    offset = 0
    batch_size = 1000
    max_pages = sample_size * 3 // batch_size + 5

    print(f'[采集] 从 Meilisearch 采样 {sample_size} 個 URL...')

    for page in range(max_pages):
        try:
            resp = requests.post(
                f'{MEILI_URL}/indexes/resources/search',
                headers={'Authorization': f'Bearer {MEILI_KEY}'},
                json={
                    'q': '',
                    'limit': batch_size,
                    'offset': offset,
                    'attributesToRetrieve': ['url'],
                },
                timeout=15,
            )
            hits = resp.json().get('hits', [])
            if not hits:
                break

            for h in hits:
                url = h['url']
                # 标准化 URL (去 query string 后的 hash)
                base_url = url.split('#')[0]
                if base_url not in seen:
                    seen.add(base_url)
                    urls.append(base_url)
                    if len(urls) >= sample_size:
                        break

            if len(urls) >= sample_size:
                break

            offset += batch_size
            print(f'  已扫描 {offset} 文档，收集 {len(urls)} 唯一 URL...')

        except Exception as e:
            print(f'  Meilisearch 查詢出错 (offset={offset}): {e}')
            break

    print(f'[采集] 完成: {len(urls)} 唯一 URL')
    return urls


def run_checks(urls, workers=10, timeout=10):
    """并发检查 URL"""
    stats = Counter()
    results = {}

    total = len(urls)
    print(f'\n[检测] 开始检查 {total} 個链接 (并行 {workers}, 超时 {timeout}s)...')
    start = time.time()

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(check_url, url, timeout): url for url in urls}

        for future in as_completed(futures):
            url, status, detail = future.result()
            stats[status] += 1
            results[url] = {'status': status, 'detail': detail}
            completed += 1

            if completed % 100 == 0 or completed == total:
                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 else 0
                print(f'  进度 {completed}/{total} ({completed*100//total}%) '
                      f'| ✅{stats["ok"]} ❌{stats["dead"]} ❓{stats["unknown"]} '
                      f'⏭{stats["skip"]} | {rate:.1f} url/s')

    elapsed = time.time() - start
    print(f'\n[完成] 耗时 {elapsed:.1f}s')

    return results, stats


def save_results(results, stats, total_urls):
    """保存结果到 link_status.json"""
    output = {
        'total': total_urls,
        'ok': stats.get('ok', 0),
        'dead': stats.get('dead', 0),
        'unknown': stats.get('unknown', 0),
        'skip': stats.get('skip', 0),
        'updated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'results': results,
    }

    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f'[保存] 结果已写入 {STATUS_FILE}')


def print_domain_breakdown(results):
    """按域名统计失效情况"""
    domain_stats = {}
    for url, info in results.items():
        try:
            domain = urlparse(url).netloc or '(空)'
        except:
            domain = '(解析失败)'

        if domain not in domain_stats:
            domain_stats[domain] = Counter()
        domain_stats[domain][info['status']] += 1

    print('\n📊 按域名统计:')
    print(f'{"域名":<30} {"总数":>6} {"✅有效":>6} {"❌失效":>6} {"❓未知":>6} {"失效率":>8}')
    print('-' * 70)
    for domain in sorted(domain_stats, key=lambda d: -sum(domain_stats[d].values())):
        s = domain_stats[domain]
        total = sum(s.values())
        dead = s.get('dead', 0)
        rate = f'{dead/total*100:.1f}%' if total > 0 else 'N/A'
        print(f'{domain:<30} {total:>6} {s.get("ok",0):>6} {dead:>6} {s.get("unknown",0):>6} {rate:>8}')


def main():
    sample_size = 500
    workers = 10
    timeout = 10

    # 解析参数
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--sample' and i + 1 < len(args):
            sample_size = int(args[i + 1]); i += 2
        elif args[i] == '--workers' and i + 1 < len(args):
            workers = int(args[i + 1]); i += 2
        elif args[i] == '--timeout' and i + 1 < len(args):
            timeout = int(args[i + 1]); i += 2
        else:
            i += 1

    print('=' * 60)
    print('  凌云搜索 - 网盘链接失效检测')
    print(f'  采样: {sample_size} URL | 并行: {workers} | 超时: {timeout}s')
    print('=' * 60)

    # 1. 采样
    urls = get_sample_urls(sample_size)

    if not urls:
        print('[错误] 未获取到 URL')
        return

    # 2. 检测
    results, stats = run_checks(urls, workers=workers, timeout=timeout)

    # 3. 保存
    save_results(results, stats, len(urls))

    # 4. 报告
    print('\n' + '=' * 60)
    print('  检测报告')
    print('=' * 60)
    total = len(urls)
    ok = stats.get('ok', 0)
    dead = stats.get('dead', 0)
    unknown = stats.get('unknown', 0)
    skip = stats.get('skip', 0)

    print(f'  总检测: {total}')
    print(f'  ✅ 有效: {ok} ({ok/total*100:.1f}%)')
    print(f'  ❌ 失效: {dead} ({dead/total*100:.1f}%)')
    print(f'  ❓ 未知: {unknown} ({unknown/total*100:.1f}%)')
    print(f'  ⏭ 跳过: {skip}')

    # 域名分解
    print_domain_breakdown(results)

    # 展示部分失效链接
    dead_urls = [(u, i['detail']) for u, i in results.items() if i['status'] == 'dead']
    if dead_urls:
        print(f'\n📋 前10个失效链接:')
        for url, detail in dead_urls[:10]:
            print(f'  ❌ [{detail}] {url[:100]}')

    print('\n✅ 检测完成!')


if __name__ == '__main__':
    main()
