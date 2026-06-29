# 分享投稿功能

## 概述
凌云搜索首页支持用户投稿分享网盘链接，投稿数据存储在 `subs.json`。

## 架构

```
浏览器 → pan.okva.cc/submit (POST) → Go代理(:8081) → subs.json
```

## 前端
- `proxy/frontend/dist/index.html`
- 弹窗表单 → `POST /submit`，body: `{"links": "链接内容..."}`

## Go 后端
- `/submit` 端点（`main.go` L217-250）
- 支持 GET/POST，最少 10 字符
- 直写 `subs.json`，避免经 Python 代理的 JSON 转义问题

## 数据格式 (`subs.json`)
```json
[
  {
    "name": "匿名投稿",
    "time": "2026-06-30 15:04:05",
    "content": "https://pan.baidu.com/s/xxx ..."
  }
]
```

## 后台管理
- 访问 `/admin/` → 登录 → 📮 投稿
- 可查看、删除投稿
- API: `GET/POST /admin/api/subs`

## 投稿接口
```bash
# 提交
curl -X POST https://pan.okva.cc/submit \
  -H "Content-Type: application/json" \
  -d '{"links":"https://pan.baidu.com/s/test 分享说明"}'

# 响应
{"code":0,"msg":"投稿成功！感谢分享 🎉"}
```
