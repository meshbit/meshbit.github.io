# 凌云搜索 MySQL 全文索引

## 环境
- MySQL 8.0 Docker (`pansou-mysql`)
- 端口 3306
- 数据库 `pansearch`，用户 `root`，密码 `pansearch123`

## 全文索引 DDL

```sql
-- 创建全文索引（在 pan_resources 表的 note 字段上）
ALTER TABLE pan_resources ADD FULLTEXT INDEX ft_note (note);

-- 查询示例
SELECT *, MATCH(note) AGAINST('人工智能' IN NATURAL LANGUAGE MODE) AS score
FROM pan_resources
WHERE MATCH(note) AGAINST('人工智能' IN NATURAL LANGUAGE MODE)
ORDER BY score DESC LIMIT 50;
```

## Python 调用
`proxy.py` 中 `search_mysql()` 函数通过 `MATCH ... AGAINST` 实现中文全文搜索，与 Meilisearch 合并后返回。

## 恢复步骤
```bash
# 1. 启动 Docker Desktop
# 2. 容器自动启动 pansou-mysql
# 3. 重启 Python 代理
cd "D:/网站/凌云搜索/scraper"
python3 -u proxy.py
```
