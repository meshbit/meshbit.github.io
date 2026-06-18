#!/bin/bash
# 健康检查脚本 - 检查nginx和后端服务是否正常

# 环境变量默认值
PANSOU_HOST=${PANSOU_HOST:-127.0.0.1}
PANSOU_PORT=${PANSOU_PORT:-8888}
HEALTH_CHECK_TIMEOUT=${HEALTH_CHECK_TIMEOUT:-10}

# 检查nginx是否运行
if ! pgrep nginx >/dev/null 2>&1; then
    echo "❌ Nginx进程不存在"
    exit 1
fi

# 检查nginx是否响应（通过80端口）
if ! curl -sf --max-time ${HEALTH_CHECK_TIMEOUT} http://localhost/api/health >/dev/null 2>&1; then
    echo "❌ Nginx无法访问健康检查端点"
    exit 1
fi

# 检查后端服务是否响应
if ! curl -sf --max-time ${HEALTH_CHECK_TIMEOUT} http://${PANSOU_HOST}:${PANSOU_PORT}/api/health >/dev/null 2>&1; then
    echo "❌ 后端服务健康检查失败"
    exit 1
fi

# 所有检查通过
exit 0
