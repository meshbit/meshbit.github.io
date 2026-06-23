"""
凌云搜索 - 社交平台爬虫
爬取 微博/豆瓣/推特 中的网盘分享链接
"""
import re, json, hashlib, time
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
           'Accept-Language': 'zh-CN,zh;q=0.9'}
TIMEOUT = 8

PAN_TYPES = {
    'pan.baidu.com': 'baidu', 'aliyundrive.com': 'aliyun', 'alipan.com': 'aliyun',
    'pan.quark.cn': 'quark', 'pan.xunlei.com': 'xunlei', 'cloud.189.cn': 'tianyi',
    'drive.uc.cn': 'uc', '115.com': '115', '123pan.com': '123',
}

def parse_type(url):
    for k, v in PAN_TYPES.items():
        if k in url.lower(): return v
    return 'others'

def make_result(url, note, ptype, dt=None):
    return {'url': url, 'note': note[:200], 'password': '',
            'datetime': (dt or datetime.now()).isoformat(), 'type': ptype}

PAN_LINK_RE = re.compile(
    r'https?://[^\s<>"\'\\u4e00-\\u9fff]*?('
    r'pan\.baidu\.com/s/[a-zA-Z0-9_-]{6,}|'
    r'aliyundrive\.com/s/[a-zA-Z0-9]{6,}|alipan\.com/s/[^\s]+|'
    r'pan\.quark\.cn/s/[a-zA-Z0-9]{8,}|'
    r'pan\.xunlei\.com/s/[a-zA-Z0-9]+|'
    r'cloud\.189\.cn/[^\s"\']+|'
    r'drive\.uc\.cn/[^\s"\']+|'
    r'115\.com/s/[^\s"\']+|'
    r'123pan\.com/s/[^\s"\']+'
    r')', re.IGNORECASE)

# ===== 豆瓣爬虫 =====
def scrape_douban(keyword):
    results = []
    try:
        # 搜索豆瓣小组
        url = f'https://www.douban.com/search?q={quote(keyword + " 网盘")}&cat=1013'
        r = requests.get(url, headers={**HEADERS, 'Referer': 'https://www.douban.com'}, timeout=TIMEOUT)
        if r.status_code != 200: return results
        
        # 提取话题链接
        topic_ids = re.findall(r'/group/topic/(\\d+)', r.text)
        for tid in set(topic_ids[:5]):
            try:
                detail = requests.get(f'https://www.douban.com/group/topic/{tid}/',
                    headers={**HEADERS, 'Referer': url}, timeout=TIMEOUT)
                links = PAN_LINK_RE.findall(detail.text)
                title = re.search(r'<title>(.+?)</title>', detail.text)
                title_text = title.group(1).strip()[:150] if title else keyword
                for link in links[:3]:
                    url_clean = re.sub(r'[?#].*$', '', link[0] if isinstance(link, tuple) else link)
                    pt = parse_type(url_clean)
                    if pt:
                        results.append(make_result(url_clean, title_text, pt))
                time.sleep(0.3)
            except: pass
    except: pass
    return results

# ===== 微博爬虫 =====
def scrape_weibo_extra(keyword):
    """微博移动版搜索（PanSou 有 weibo 插件, 这是补充）"""
    results = []
    try:
        url = f'https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D1%26q%3D{quote(keyword + " 网盘")}&page=1'
        r = requests.get(url, headers={**HEADERS, 'Referer': 'https://m.weibo.cn'}, timeout=TIMEOUT)
        data = r.json()
        cards = data.get('data', {}).get('cards', [])
        for card in cards[:10]:
            text = card.get('mblog', {}).get('text', '')
            # Clean HTML
            text = re.sub(r'<[^>]+>', '', text)
            links = PAN_LINK_RE.findall(text)
            for link in links[:3]:
                url_clean = link[0] if isinstance(link, tuple) else link
                pt = parse_type(url_clean)
                if pt:
                    results.append(make_result(url_clean, text[:150], pt,
                        card.get('mblog',{}).get('created_at','')))
    except: pass
    return results

# ===== 推特爬虫（通过 Nitter 镜像）=====
def scrape_twitter(keyword):
    results = []
    # Nitter 是推特的轻量级前端，不需要 API
    mirrors = ['https://nitter.net', 'https://nitter.poast.org']
    for mirror in mirrors:
        try:
            url = f'{mirror}/search?f=tweets&q={quote(keyword + " pan OR 网盘 OR 链接")}'
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200: continue
            tweets = re.findall(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', r.text, re.DOTALL)
            for tweet in tweets[:10]:
                text = re.sub(r'<[^>]+>', '', tweet)
                links = PAN_LINK_RE.findall(text)
                for link in links[:3]:
                    url_clean = link[0] if isinstance(link, tuple) else link
                    pt = parse_type(url_clean)
                    if pt:
                        results.append(make_result(url_clean, text[:150], pt))
            break  # Use first working mirror
        except: continue
    return results

# ===== 知乎爬虫 =====
def scrape_zhihu(keyword):
    results = []
    try:
        url = f'https://www.zhihu.com/search?type=content&q={quote(keyword + " 网盘 链接")}'
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        PAN_RE = re.compile(r'(pan\.baidu\.com/s/\\w{6,}|aliyundrive\.com/s/\\w{6,}|pan\.quark\.cn/s/\\w{8,})', re.I)
        links = PAN_RE.findall(r.text)
        for link in set(links)[:10]:
            pt = parse_type(link)
            results.append(make_result(link, f'{keyword} - 知乎分享', pt))
    except: pass
    return results

# ===== Reddit 爬虫 =====
def scrape_reddit(keyword):
    results = []
    try:
        url = f'https://old.reddit.com/search?q={quote(keyword + " pan OR drive")}&sort=new'
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        PAN_RE = re.compile(r'(https?://[^\\s<>"]*?(?:pan\\.baidu\\.com|aliyundrive\\.com|pan\\.quark\\.cn|mega\\.nz|drive\\.google\\.com)/[^\\s<>"]*)', re.I)
        links = PAN_RE.findall(r.text)
        for link in set(links)[:10]:
            pt = parse_type(link)
            if pt: results.append(make_result(link, f'{keyword} - Reddit', pt))
    except: pass
    return results

# ===== 小红书爬虫 =====
def scrape_xiaohongshu(keyword):
    results = []
    try:
        url = f'https://www.xiaohongshu.com/search_result?keyword={quote(keyword + " 网盘")}&source=web_search_result_notes'
        r = requests.get(url, headers={**HEADERS, 'Referer': 'https://www.xiaohongshu.com'}, timeout=TIMEOUT)
        PAN_RE = re.compile(r'(pan\\.baidu\\.com/s/\\w{6,}|aliyundrive\\.com/s/\\w{6,}|pan\\.quark\\.cn/s/\\w{8,})', re.I)
        links = PAN_RE.findall(r.text)
        for link in set(links)[:10]:
            pt = parse_type(link)
            results.append(make_result(link, f'{keyword} - 小红书分享', pt))
    except: pass
    return results


# ===== Facebook爬虫 =====
def scrape_facebook(keyword):
    results = []
    try:
        url = f"https://mbasic.facebook.com/public/{keyword} pan OR drive"
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        links = PAN_LINK_RE.findall(r.text)
        for link in set(links[:10]):
            pt = parse_type(link[0] if isinstance(link, tuple) else link)
            if pt: results.append(make_result(link[0] if isinstance(link, tuple) else link, f"{keyword} - Facebook", pt))
    except: pass
    return results

SOURCES = [scrape_douban, scrape_weibo_extra, scrape_twitter, scrape_zhihu, scrape_reddit, scrape_xiaohongshu, scrape_facebook]

@app.route('/api/search')
def search():
    keyword = request.args.get('kw', '').strip()
    if len(keyword) < 2:
        return jsonify({'code': 0, 'data': {'total': 0}})
    
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fn, keyword): fn for fn in SOURCES}
        for future in as_completed(futures, timeout=10):
            try:
                results.extend(future.result(timeout=8))
            except: pass
    
    print(f"[爬虫] {keyword}: {len(results)}条")
    
    seen = set()
    data = []
    for r in results:
        h = hashlib.md5(r['url'].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            data.append(r)
    
    return jsonify({'code': 0, 'data': {'total': len(data), 'items': data}})

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, threaded=False)
