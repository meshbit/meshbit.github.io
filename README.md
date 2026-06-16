# 盘搜 - PanSou 千帆风格前端

千帆搜索 (pan.qianfan.app) 风格的聚合网盘搜索引擎前端，基于 [PanSou API](https://github.com/fish2018/pansou)。

## 效果预览

- 🔍 搜索框 + 13 种网盘类型下拉筛选
- 🏷️ 20+ 热门标签快捷搜索
- 📂 搜索结果按网盘类型分类切换
- 📋 一键复制链接 + 密码弹窗
- 📱 手机自适应
- 🎨 千帆白色简约风格

## 部署方式

### 1. 启动 PanSou 后端

```bash
docker run -d --name pansou -p 80:80 --env-file pansou.env --restart unless-stopped ghcr.io/fish2018/pansou-web
```

### 2. 替换前端首页

```bash
docker cp index.html pansou:/app/frontend/dist/index.html
```

### 3. 访问

打开 `http://localhost` 或 `http://你的IP`

## 搜索源配置

- **159 个 Telegram 频道**：覆盖百度/阿里/夸克/迅雷/天翼/UC/115/PikPak 等网盘资源频道
- **88 个搜索插件**：综合网盘搜索 + 影视动漫 + 磁力 BT + 学习资源 + 论坛社区

## 技术栈

- 纯 HTML/CSS/JS 单页面
- 调用 PanSou REST API (`/api/search`)
- 无需任何构建工具，即拷即用
