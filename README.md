# 凌云搜索 — 聚合网盘搜索引擎

> 全网网盘链接实现秒级检索，精益求精做最硬核的搜盘神器！

**在线演示:** [https://pan.okva.cc](https://pan.okva.cc)

---

## 📋 目录

- [架构设计](#架构设计)
- [搜索数据流](#搜索数据流)
- [写入数据流](#写入数据流)
- [项目结构](#项目结构)
- [文件清单](#文件清单)
- [基础设施](#基础设施)
- [API 文档](#api-文档)
- [本地部署](#本地部署)
- [维护指南](#维护指南)

---

## 🏗️ 架构设计

```
                              pan.okva.cc (Cloudflare Tunnel)
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    Go 代理 :8080                              │
│  • 静态文件服务 (frontend/dist/)                              │
│  • 10分钟内存缓存                                             │
│  • 失效链接过滤                                               │
│  • 后台管理系统 (/admin/)                                     │
└───────────────────────────┬──────────────────────────────────┘
                            │ /api/search
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              Python Proxy :5003 (Waitress 8线程)              │
│                                                              │
│  搜索优先级:                                                  │
│   1️⃣ SQLite 缓存 (0ms, 命中直接返回)                         │
│   2️⃣ MySQL + ES 快速路径 (ms, ≥50条秒回)                     │
│   3️⃣ Meilisearch 补充 (ms, 200K索引)                        │
│   4️⃣ PanSou 实时降级 (~4s, 最后兜底)                        │
│                                                              │
│  ┌─────────┐  ┌─────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ MySQL   │  │ ES 7.17 │  │ Meilisearch  │  │ PanSou    │  │
│  │ :3307   │  │ :9200   │  │ :7700        │  │ :8081     │  │
│  │ 8.3K行  │  │ 8.3K文档│  │ 200K 文档    │  │ 174频道   │  │
│  └────┬────┘  └────┬────┘  └──────┬───────┘  │ 88插件    │  │
│       │            │              │           └───────────┘  │
│       └────────────┴──────────────┘                          │
│                    ▲ 只读                                    │
│                    │                                         │
│              ┌─────┴─────┐                                   │
│              │ 爬虫 v3   │ (每6h定时)                        │
│              │ 三写      │                                   │
│              │ MySQL+ES  │                                   │
│              │ +Meili    │                                   │
│              └───────────┘                                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔍 搜索数据流

```
用户输入 "庆余年"
  │
  ├─→ Go 代理检查内存缓存 (10分钟TTL) ──→ 命中? 直接返回
  │
  └─→ Python Proxy :5003
        │
        ├─→ 1. SQLite cache.db ──→ 命中? 返回 (X-Cache: HIT)
        │
        ├─→ 2. MySQL (LIKE搜索) + ES (multi_match全文)
        │      │
        │      └─→ 两库合并去重 ≥ 50条? → 直接返回 (X-Source: mysql+es) ⚡
        │
        ├─→ 3. Meilisearch 全文索引 ──→ 补充结果
        │
        ├─→ 4. PanSou 实时聚合 (174频道+88插件) ──→ 补充结果
        │
        └─→ 5. 合并去重 → save_results() → SQLite缓存 → 返回JSON
```

### 性能对比

| 搜索路径 | 耗时 | 触发条件 |
|---------|------|---------|
| Go 内存缓存 | < 10ms | 10分钟内重复搜索 |
| SQLite 缓存 | < 5ms | 历史搜索过 |
| MySQL+ES 快速路径 | ~100ms | 数据≥50条 |
| Meilisearch | ~50ms | 补充索引 |
| PanSou 实时 | ~4s | 未命中本地库 |

---

## ✍️ 写入数据流 (离线预建索引)

```
定时任务 (每6小时)
  │
  ▼
crawl_and_index.py (爬虫 v3)
  │
  ├─→ 读取 36 个热门关键词
  │
  ├─→ 调用 Python Proxy API 获取搜索结果
  │
  ├─→ 去重 (按 url_hash)
  │
  ├─→ 三写:
  │     ├─→ MySQL   INSERT ... ON DUPLICATE KEY UPDATE
  │     ├─→ ES      POST /_bulk (NDJSON)
  │     └─→ Meili   POST /indexes/resources/documents
  │
  └─→ 统计报告 (三库文档数)
```

### 读写分离

| 组件 | 搜索时 (Proxy) | 爬虫时 (Crawler) |
|------|:---:|:---:|
| **SQLite** | ✅ 读写 | ❌ 不碰 |
| **MySQL** | 🔍 只读 | ✍️ 只写 |
| **ES** | 🔍 只读 | ✍️ 只写 |
| **Meilisearch** | 🔍 只读 | ✍️ 只写 |
| **PanSou** | 🔍 只读 | ❌ 不碰 |

---

## 📁 项目结构

```
凌云搜索/
│
├── pansou-repo/                         # 主仓库
│   ├── proxy/
│   │   └── main.go                      # Go 代理源码 (~340行)
│   │
│   ├── frontend/dist/
│   │   └── index.html                   # SPA 前端 (首页+搜索)
│   │
│   ├── docker-compose.yml               # Docker 编排 (PanSou + MySQL + ES + Redis)
│   ├── pansou.env                       # PanSou 配置 (频道 + 插件)
│   │
│   ├── mysql_data/                      # MySQL 持久化数据 (gitignore)
│   ├── es_data/                         # Elasticsearch 持久化数据 (gitignore)
│   └── data/                            # PanSou 运行时数据 (gitignore)
│
├── scraper/                             # Python 爬虫 + 代理
│   ├── proxy.py                         # Python 搜索代理 (Waitress, 三源合并)
│   ├── db.py                            # SQLite 缓存读写
│   ├── crawl_and_index.py              # 主爬虫 (三写: MySQL+ES+Meili)
│   ├── expand.py                        # 关键词扩展 (同义词/拼音/简繁)
│   ├── keyword_factory.py              # 关键词工厂 (热门词生成)
│   │
│   ├── warm_crawler.py                 # 预热爬虫
│   ├── massive_crawler.py              # 大规模爬虫
│   ├── share_crawler.py                # 分享链接爬虫
│   ├── sitemap_scraper.py              # 站点地图爬虫
│   ├── bilibili_scraper.py             # B站爬虫
│   ├── aikanzy_crawler.py              # 爱看资源爬虫
│   ├── aikanzy_full.py                 # 爱看全量爬虫
│   ├── competitor_crawler.py           # 竞品爬虫
│   │
│   ├── social.py                       # 社交平台爬虫 (7平台)
│   ├── browser.py                      # Playwright 浏览器自动化
│   ├── run_all.py                      # 一键启动所有爬虫
│   │
│   ├── keywords_massive.json           # 关键词库 (3MB, 海量词条)
│   └── cache.db                        # SQLite 搜索缓存
│
└── D:\proxy\                            # 运行时配置目录
    ├── auth.json                        # 后台登录密码
    ├── ads.json                         # 首页广告位
    ├── nav.json                         # 导航链接
    ├── subs.json                        # 用户投稿
    ├── site_config.json                 # 站点配置
    └── link_status.json                 # 链接失效检测
```

---

## 📄 文件清单

### Go 代理 (`pansou-repo/proxy/`)

| 文件 | 行数 | 说明 |
|------|------|------|
| `main.go` | 436 | Go 代理：路由、缓存、后台API、静态文件 |

### Python 代理 + 爬虫 (`scraper/`)

| 文件 | 行数 | 说明 |
|------|------|------|
| `proxy.py` | 414 | Python 搜索代理，合并 MySQL+ES+Meilisearch+PanSou |
| `db.py` | 53 | SQLite 缓存 (`save_results` / `query_local`) |
| `crawl_and_index.py` | 216 | 主爬虫，定时三写 MySQL+ES+Meilisearch |
| `expand.py` | 180 | 关键词扩展 (简繁/拼音/英文/同义词) |
| `keyword_factory.py` | 230 | 关键词库生成 (热门/长尾/竞品词) |
| `social.py` | 520 | 社交平台爬虫 (微博/知乎/贴吧/豆瓣/小红书/B站/抖音) |
| `browser.py` | 380 | Playwright 浏览器爬虫模板 |
| `warm_crawler.py` | 480 | 预热爬虫 (保持索引热度) |
| `massive_crawler.py` | 180 | 大规模批量爬虫 |
| `share_crawler.py` | 300 | 分享链接抓取器 |
| `sitemap_scraper.py` | 180 | 站点地图爬虫 |
| `bilibili_scraper.py` | 160 | B站专项爬虫 |
| `aikanzy_crawler.py` | 120 | 爱看资源站爬虫 |
| `aikanzy_full.py` | 170 | 爱看全量采集 |
| `competitor_crawler.py` | 70 | 竞品数据采集 |
| `run_all.py` | 30 | 一键启动所有爬虫 |

### 配置文件

| 文件 | 路径 | 说明 |
|------|------|------|
| `docker-compose.yml` | `pansou-repo/` | 4个Docker服务编排 |
| `pansou.env` | `pansou-repo/` | PanSou 频道+插件列表 |
| `auth.json` | `D:\proxy\` | 后台密码 (默认: admin123) |
| `ads.json` | `D:\proxy\` | 首页广告位 |
| `nav.json` | `D:\proxy\` | 导航链接 |
| `subs.json` | `D:\proxy\` | 用户投稿 |
| `site_config.json` | `D:\proxy\` | 站点配置 |
| `link_status.json` | `D:\proxy\` | 失效链接检测结果 |

---

## 🖥️ 基础设施

### Docker 容器

| 容器名 | 镜像 | 端口 | 说明 |
|--------|------|------|------|
| `pansou` | `ghcr.io/fish2018/pansou-web` | 8081:80 | PanSou 搜索引擎 |
| `pansou-mysql` | `mysql:8.0` | 3307:3306 | 本地资源仓库 |
| `pansou-es` | `elasticsearch:7.17.25` | 9200:9200 | 全文搜索索引 |
| `pansou-redis` | `redis:7-alpine` | 6380:6379 | 缓存/队列 (备用) |

### 外部服务

| 服务 | 端口 | 说明 |
|------|------|------|
| **Meilisearch** | 7700 | Windows 原生运行，搜索引擎 |
| **Go 代理** | 8080 | 编译为 proxy.exe，反向代理 |
| **Python Proxy** | 5003 | Waitress WSGI 服务器，搜索合并引擎 |
| **Cloudflare Tunnel** | — | 内网穿透，公网访问 pan.okva.cc |
| **nginx** | 80 | 备用 (历史遗留) |

### 定时任务

| 任务 | 频率 | 脚本 |
|------|------|------|
| 凌云爬虫 | 每 6 小时 | `python crawl_and_index.py` |
| 链接检测 | 每天 03:00 | Go 代理内置 |

---

## 📡 API 文档

### 公开接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/search?kw=关键词` | GET | 搜索网盘资源 |
| `/api/health` | GET | 服务健康检查 |
| `/api/navlinks` | GET | 导航链接列表 |

### 搜索响应格式

```json
{
  "code": 0,
  "data": {
    "total": 501,
    "merged_by_type": {
      "quark": [
        {
          "url": "https://pan.quark.cn/s/xxx",
          "note": "庆余年 第二季 (2024)",
          "password": "",
          "datetime": "2026-06-23"
        }
      ],
      "aliyun": [...],
      "baidu": [...],
      "xunlei": [...],
      "tianyi": [...],
      "uc": [...],
      "115": [...],
      "123": [...]
    }
  }
}
```

### 响应头

| Header | 值 | 说明 |
|--------|-----|------|
| `X-Cache` | `HIT 2ms` | SQLite 缓存命中 |
| `X-Source` | `mysql+es` | MySQL+ES 快速路径命中 |
| `Server` | `waitress` | Python 代理 |

---

## 🚀 本地部署

### 环境要求

- Windows 10/11 (x64)
- Docker Desktop
- Python 3.11+ (`pip install waitress pymysql requests`)
- Go 1.22+ (编译代理)
- Meilisearch (Windows 原生)
- Cloudflare Tunnel (公网访问)

### 1. 启动 Docker 服务

```bash
cd D:\pansou-repo
docker compose up -d
# 启动: PanSou + MySQL + ES + Redis
```

### 2. 初始化 MySQL 表

```sql
CREATE TABLE IF NOT EXISTS resources (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(200),
    source VARCHAR(100) DEFAULT 'pansou',
    url VARCHAR(2048),
    url_hash VARCHAR(32),
    note TEXT,
    password VARCHAR(100),
    type VARCHAR(50),
    datetime VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_url_hash (url_hash),
    KEY idx_keyword (keyword),
    KEY idx_type (type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3. 启动 Python 代理

```bash
cd D:\scraper
python proxy.py
# Waitress 生产模式: threads=8, conn_limit=100
```

### 4. 编译并启动 Go 代理

```bash
cd D:\pansou-repo\proxy
go build -o proxy.exe main.go

# Windows 启动
set PORT=8080
set STATIC_DIR=D:\pansou-repo\frontend\dist
proxy.exe
```

### 5. 运行爬虫 (首次)

```bash
cd D:\scraper
python crawl_and_index.py
# 首次运行自动回填 ES (从 MySQL 全量同步)
```

### 6. Cloudflare Tunnel

```yaml
# ~/.cloudflared/config.yml
tunnel: <tunnel-id>
credentials-file: ~/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: pan.okva.cc
    service: http://localhost:8080
  - service: http_status:404
```

---

## 🔧 维护指南

### 日常检查

```bash
# 服务健康
curl http://localhost:5003/api/health
# {"elasticsearch":"connected","meilisearch":"connected","mysql":"connected","status":"ok"}

# 数据统计
docker exec pansou-mysql mysql -uroot -ppansearch123 -e "SELECT COUNT(*) FROM pansearch.resources;"
curl http://localhost:9200/resources/_count
curl http://localhost:7700/indexes/resources/stats -H "Authorization: Bearer <key>"
```

### 添加搜索关键词

编辑 `scraper/crawl_and_index.py` 中的 `HOT_KEYWORDS` 列表。

### 清缓存

```bash
# 清 Python 代理缓存
rm D:\scraper\cache.db

# 清 Go 代理内存缓存
curl http://localhost:8080/admin/api/cache/clear
```

### 手动回填 ES

```bash
cd D:\scraper
python -c "from crawl_and_index import backfill_es_from_mysql; backfill_es_from_mysql()"
```

---

## 📊 数据规模 (截至部署日)

| 数据源 | 文档数 | 存储大小 |
|--------|--------|---------|
| Meilisearch | 200,662 | ~670 MB |
| MySQL | 8,355 | ~10 MB |
| Elasticsearch | 8,355 | ~2 MB |
| PanSou 频道 | 174 个 | — |
| PanSou 插件 | 88 个 | — |
| 关键词 | 36 个热门 | — |

---

## 🔐 安全

- 后台密码: `D:\proxy\auth.json` (默认 `admin123`)
- MySQL 密码: `pansearch123` (仅本地访问)
- Meilisearch Master Key: 配置文件内 (仅本地访问)
- ES 安全: `xpack.security.enabled=false` (仅本地访问)
- Cloudflare Tunnel: 自动 HTTPS

---

## 📌 路线图

- [x] MySQL 本地仓库
- [x] Elasticsearch 全文索引
- [x] Meilisearch 最大索引
- [x] 爬虫三写 (MySQL+ES+Meili)
- [x] Waitress 生产部署
- [x] MySQL+ES 快速路径
- [x] 搜索缓存 (SQLite + 内存)
- [ ] 爬虫 IP 代理池 (反爬)
- [ ] 搜索结果分页性能优化
- [ ] ES 中文分词 (IK)
- [ ] 增量爬取 (非全量)
- [ ] 监控告警
