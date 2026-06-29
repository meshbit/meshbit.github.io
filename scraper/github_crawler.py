#!/usr/bin/env python3
"""
凌云搜索 - GitHub 爬虫
Awesome 列表 / Issues / Gist
用 GitHub API，反爬零成本
"""
import re, sys, os, hashlib
from crawler_base import *
from urllib.parse import quote
from datetime import datetime

GITHUB_API = 'https://api.github.com'
# 无认证：60 req/h，有认证：5000 req/h
_GH_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GH_HEADERS = HEADERS.copy()
GH_HEADERS['Accept'] = 'application/vnd.github.v3+json'
if _GH_TOKEN:
    GH_HEADERS['Authorization'] = f'token {_GH_TOKEN}'

def _gh_get(url, **kwargs):
    """GitHub API 带限流处理"""
    session = get_session()
    try:
        resp = session.get(url, headers=GH_HEADERS, timeout=15, **kwargs)
        if resp.status_code == 403 and 'rate limit' in resp.text.lower():
            print(f'  [GitHub] Rate limited, sleeping...', flush=True)
            time.sleep(60)
            return None
        if resp.status_code == 200:
            return resp
        return None
    except Exception as e:
        print(f'  [GitHub] ERR: {e}', flush=True)
    return None

# ============================================================
# Awesome 列表 — 搜索结果包含 awesome-xxx 仓库
# ============================================================
def scrape_awesome(keyword):
    """搜索 awesome-xxx 仓库的 README"""
    results = []
    try:
        # 搜索 awesome 仓库
        repos_url = f'{GITHUB_API}/search/repositories?q={quote(keyword)}+awesome+in:name&sort=stars&per_page=10'
        resp = _gh_get(repos_url)
        if not resp:
            return results
        repos = resp.json().get('items', [])

        for repo in repos[:5]:
            # 获取 README
            readme_url = f"{GITHUB_API}/repos/{repo['full_name']}/readme"
            rm = _gh_get(readme_url)
            if not rm:
                continue
            import base64
            try:
                content = base64.b64decode(rm.json().get('content', '')).decode('utf-8', errors='ignore')
                name = repo['full_name']
                results.extend(extract_links(content, f'Awesome:{name}'))
                time.sleep(0.3)
            except:
                pass
    except Exception as e:
        print(f'  [Awesome] ERR: {e}', flush=True)
    return results

# ============================================================
# Issues — 搜索 Issue 中的网盘链接
# ============================================================
def scrape_issues(keyword):
    """搜索 Issue 内容"""
    results = []
    try:
        # 全局搜索 Issues
        url = f'{GITHUB_API}/search/issues?q={quote(keyword + "+pan+OR+drive+OR+盘")}&sort=updated&per_page=10'
        resp = _gh_get(url)
        if not resp:
            return results
        issues = resp.json().get('items', [])

        for issue in issues[:10]:
            body = issue.get('body', '') or ''
            title = issue.get('title', '')
            results.extend(extract_links(body + ' ' + title, f"Issue:{keyword}"))
            time.sleep(0.2)
    except Exception as e:
        print(f'  [Issues] ERR: {e}', flush=True)
    return results

# ============================================================
# Gist — 搜索公开 Gist
# ============================================================
def scrape_gist(keyword):
    """搜索公开 Gist 内容"""
    results = []
    try:
        url = f'{GITHUB_API}/gists/public?per_page=30'
        resp = _gh_get(url)
        if not resp:
            return results
        gists = resp.json()

        # 过滤含关键词的 Gist
        for gist in gists:
            desc = (gist.get('description', '') or '').lower()
            files = gist.get('files', {})
            for fname, finfo in files.items():
                content = finfo.get('content', '') or ''
                if keyword.lower() in content.lower() or keyword.lower() in fname.lower():
                    results.extend(extract_links(content, f'Gist:{fname}'))
            time.sleep(0.15)
    except Exception as e:
        print(f'  [Gist] ERR: {e}', flush=True)
    return results

# ============================================================
# Awesome 全量爬取
# ============================================================
AWESOME_TOPICS = [
    'awesome-selfhosted', 'awesome-sysadmin', 'awesome-mac',
    'awesome-python', 'awesome-javascript', 'awesome-go',
    'free-programming-books', 'awesome-china',
    'awesome-software', 'awesome-tools', 'book',
    'pan', 'drive', 'resource',
]

def scrape_awesome_all():
    """全量抓取 awesome 相关仓库"""
    all_docs = []
    visited = set()

    for topic in AWESOME_TOPICS:
        print(f'[Awesome全量] topic={topic}', flush=True)
        try:
            url = f'{GITHUB_API}/search/repositories?q={quote(topic)}+awesome+in:name&sort=stars&per_page=20'
            resp = _gh_get(url)
            if not resp:
                continue
            repos = resp.json().get('items', [])

            for repo in repos:
                full_name = repo['full_name']
                if full_name in visited:
                    continue
                visited.add(full_name)

                print(f'  [{full_name}] readme...', flush=True)
                readme_url = f"{GITHUB_API}/repos/{full_name}/readme"
                rm = _gh_get(readme_url)
                if not rm:
                    continue

                import base64
                try:
                    content = base64.b64decode(rm.json().get('content', '')).decode('utf-8', errors='ignore')
                    docs = extract_links(content, f'Awesome:{full_name}')
                    if docs:
                        for d in docs:
                            d['keyword'] = topic
                            d['source'] = f'github-awesome:{full_name}'
                        save_all(docs)
                        all_docs.extend(docs)
                except:
                    pass
                time.sleep(0.5)
            time.sleep(1)
        except Exception as e:
            print(f'  [Awesome全量] ERR: {e}', flush=True)

    return all_docs

# ============================================================
SOURCES = [
    ('awesome', scrape_awesome),
    ('issues', scrape_issues),
    ('gist', scrape_gist),
]

if __name__ == '__main__':
    if '--all' in sys.argv:
        docs = scrape_awesome_all()
        print(f'[GitHub全量] {len(docs)}条', flush=True)
    else:
        kw = sys.argv[1] if len(sys.argv) > 1 else 'test'
        print(f'[GitHub] 搜索: {kw}', flush=True)
        all_results = []
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(fn, kw): name for name, fn in SOURCES}
            for f in as_completed(futures, timeout=20):
                try:
                    all_results.extend(f.result(timeout=15))
                except:
                    pass
        seen, unique = set(), []
        for r in all_results:
            h = r.get('url_hash', '')
            if h not in seen:
                seen.add(h)
                unique.append(r)
        print(f'[GitHub] 结果: {len(unique)}条', flush=True)
        if unique:
            save_all(unique)
