"""
凌云搜索 - Playwright 浏览器爬虫
用真实浏览器绕过反爬，搜百度+必应+Google
"""
import json, re, sys, asyncio, hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify, request
from playwright.async_api import async_playwright

app = Flask(__name__)

PAN_TYPES = {
    'pan.baidu.com': 'baidu', 'aliyundrive.com': 'aliyun', 'alipan.com': 'aliyun',
    'pan.quark.cn': 'quark', 'pan.xunlei.com': 'xunlei', 'cloud.189.cn': 'tianyi',
    'drive.uc.cn': 'uc', '115.com': '115', '123pan.com': '123', '123684.com': '123',
}

def parse_type(url):
    for k, v in PAN_TYPES.items():
        if k in url.lower(): return v
    return ''

# Thread-local browser instance
browser_instance = None
browser_lock = asyncio.Lock()

async def get_browser():
    global browser_instance
    if browser_instance is None:
        p = await async_playwright().start()
        browser_instance = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
        )
    return browser_instance

async def scrape_engine(page, url, keyword):
    """在搜索引擎页面提取网盘链接"""
    results = []
    try:
        await page.goto(url, timeout=15000, wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)  # 等JS渲染
        
        content = await page.content()
        # 提取所有链接
        urls = set()
        for k in PAN_TYPES:
            pattern = f'https?://[^\\s"\'<>]*{k}/[^\\s"\'<>]*'
            found = re.findall(pattern, content)
            urls.update(found)
        
        for u in urls:
            clean = re.sub(r'[?#].*$', '', u)
            pt = parse_type(clean)
            if pt:
                results.append({
                    'url': clean, 'note': f'{keyword} - 网盘资源',
                    'password': '', 'datetime': datetime.now().isoformat(), 'type': pt
                })
    except: pass
    return results

async def browser_search(keyword):
    browser = await get_browser()
    page = await browser.new_page()
    
    engines = [
        f'https://www.baidu.com/s?wd={keyword}+网盘资源&rn=10',
        f'https://cn.bing.com/search?q={keyword}+site:pan.quark.cn+OR+site:pan.baidu.com+OR+site:aliyundrive.com&count=10',
    ]
    
    all_results = []
    for url in engines:
        try:
            r = await scrape_engine(page, url, keyword)
            all_results.extend(r)
        except: pass
    
    await page.close()
    return all_results

def run_browser_search(keyword):
    return asyncio.new_event_loop().run_until_complete(browser_search(keyword))

# ===== Flask API =====

@app.route('/api/search')
def search():
    keyword = request.args.get('kw', '').strip()
    if len(keyword) < 2:
        return jsonify({'code': 0, 'data': {'merged_by_type': {}, 'total': 0}})
    
    results = []
    try:
        results = run_browser_search(keyword)
    except Exception as e:
        print(f"Browser error: {e}")
    
    # 去重
    seen = set()
    unique = []
    for r in results:
        h = hashlib.md5(r['url'].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(r)
    
    merged = {}
    for r in unique:
        t = r.pop('type', 'others')
        merged.setdefault(t, []).append(r)
    
    return jsonify({'code': 0, 'data': {'merged_by_type': merged, 'total': len(unique)}})

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'type': 'playwright'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, threaded=False)
