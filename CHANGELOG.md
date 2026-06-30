## 2026-06-30
- 重构凌云搜索架构：Go代理接管8081端口（原PanSou Docker），统一前后端入口
  - PanSou Docker 停用，Go代理直接提供前端 + 后台 + API
  - 后台管理 /admin/ + 登录 /login.html 恢复正常
  - 分享投稿 /submit API 恢复正常
- 修复 proxy.py MYSQL_CONFIG 端口 3306→3307
- MySQL FULLTEXT 索引重建为 ngram parser（支持中文分词）
- 启动脚本 lingyun-proxy.bat 适配新端口和架构

## 2026-06-29
- 修复 Meilisearch 密钥: 4个文件统一为 pansou-meili-key
- 修复中文关键词 URL 编码: crawl_and_index.py / crawl_and_index_v4.py 加入 quote()
- MySQL 新增 FULLTEXT 索引 ft_search(keyword, note)，替代全表扫描
- proxy.py MySQL 搜索从 LIKE '%...%' 改为 MATCH AGAINST (IN BOOLEAN MODE)
- 工具站迁移 Linear 设计系统 (awesome-design-md)

## 2026-06-28
- v5.4: 移除 Elasticsearch，双写架构 MySQL + Meilisearch
- MySQL 198,048 行 ↔ Meilisearch 198,048 docs

## 2025-06-20
- 合并部署文件(docker-compose, healthcheck, start.sh)
- 新增千帆风格前端 pansou-qianfan.html
- 新增搜索前端 pansou-search.html
- 整理 .gitignore

## 2025-06-20 (下午)
- 更新 README.md：补充项目结构、双前端说明、在线演示链接、部署步骤
