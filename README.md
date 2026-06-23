# 凌云搜索 - 聚合网盘搜索引擎

全网网盘链接实现秒级检索，精益求精做最硬核的搜盘神器！

在线演示：https://pan.okva.cc

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | HTML + CSS + JS (Tailwind CDN) |
| 代理 | Go 高性能反向代理 + 缓存 |
| 后端 | PanSou Docker (174频道 + 88插件) |
| 隧道 | Cloudflare Tunnel |

## 项目结构

```
├── frontend/dist/
│   └── index.html          # 凌云搜索前端
├── proxy/
│   └── main.go             # Go 代理源码
└── README.md
```

## 部署

1. Docker: `docker run -d --name pansou -p 8081:80 --env-file pansou.env ghcr.io/fish2018/pansou-web`
2. Go 代理: `cd proxy && go build -o proxy.exe && PORT=8080 STATIC_DIR=../frontend/dist ./proxy.exe`
3. Tunnel: Cloudflare Tunnel → localhost:8080

## 功能

- 聚合搜索 (174个TG频道 + 88个爬虫插件)
- 网盘类型筛选 (夸克/百度/阿里/迅雷/天翼/UC/115)
- 文件类型筛选 (视频/文档/压缩包/软件)
- 结果按日期排序
- 关键词高亮 + 复制链接
- 10分钟搜索缓存
- 内置后台管理 (/admin/)
- 链接失效自动检测
- 手机端自适应
