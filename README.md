# 凌云搜索 - 聚合网盘搜索引擎

皮卡风格聚合网盘搜索引擎，基于 PanSou API。10000000+ 网盘资源免费分享。

在线演示：https://pan.okva.cc

## 项目结构

```
├── frontend/dist/
│   ├── index.html              # 千帆风格主页 (pan.okva.cc)
│   ├── pansou-qianfan.html     # 千帆风格备用前端
│   ├── pansou-search.html      # 搜索风格前端
│   └── assets/                 # JS/CSS/图标
├── docker-compose.yml          # Docker 一键部署
├── start.sh                    # 启动脚本 (含 Tunnel)
├── healthcheck.sh              # 健康检查
├── .env.example                # 环境变量模板
└── pansou.env                  # 渠道/插件配置 (加密)
```

## 功能特性

- 🔍 搜索框 + 13 种网盘类型下拉筛选
- 🏷️ 20+ 热门标签快捷搜索
- 📂 搜索结果按网盘类型分类切换
- 📋 一键复制链接 + 密码弹窗
- 🌓 双风格前端 (千帆 / 搜索)
- 📱 手机自适应
- 🌐 Cloudflare Tunnel 公网访问

## 快速部署

### 1. 启动 PanSou 后端

```bash
docker run -d --name pansou \
  -p 80:80 \
  --env-file pansou.env \
  --restart unless-stopped \
  ghcr.io/fish2018/pansou-web
```

### 2. 注入自定义前端

```bash
docker cp frontend/dist/index.html pansou:/app/frontend/dist/index.html
```

### 3. Cloudflare Tunnel (可选)

```bash
./start.sh
```

### 访问

- 本地：`http://localhost`
- 公网：`https://pan.okva.cc`

## 搜索源

- **159 个 Telegram 频道**：百度/阿里/夸克/迅雷/天翼/UC/115/PikPak
- **88 个搜索插件**：综合搜索 + 影视动漫 + 磁力 BT + 学习资源 + 论坛社区

## 技术栈

- 纯 HTML/CSS/JS 单页面
- PanSou REST API (`/api/search`)
- Docker + Cloudflare Tunnel
- 零构建工具

## 更新日志

见 [CHANGELOG.md](./CHANGELOG.md)
