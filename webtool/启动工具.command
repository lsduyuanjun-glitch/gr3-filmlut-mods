#!/bin/bash
# GR3 胶片滤镜工具 —— 启动脚本（自愈版）
# 双击运行，自动校验页面完整性 + 启动服务 + 打开浏览器

cd "$(dirname "$0")"

echo "=========================================="
echo "  GR III 胶片滤镜工具"
echo "=========================================="
echo ""

# —— 可移植 Python 探测：优先本包自带 runtime，否则用系统 python3 ——
PY=""
if [ -f "$(pwd)/runtime/bin/python3" ]; then
  PY="$(pwd)/runtime/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "❌ 找不到 Python 环境。请确认已安装 Python 3（或本包 runtime 目录完整）。"
  exit 1
fi

# —— 自愈：如果 index.html 是旧版（缺功能标记），自动从备份恢复 ——
if ! grep -q "renderDetail" index.html 2>/dev/null; then
  if [ -f index_full.bak.html ]; then
    echo "⚠️ 检测到页面被旧版覆盖，正在自动恢复…"
    cp index_full.bak.html index.html
    echo "✅ 已恢复完整版页面"
  else
    echo "❌ 页面异常且无备份，请联系 Duccio 的 AI 助手重建"
    exit 1
  fi
fi

# 端口被占时先清理（可能上次卡死的进程）
if ! curl -s --noproxy '*' --max-time 2 -o /dev/null http://127.0.0.1:8310/status; then
  pkill -9 -f "gr3-flash-tool/server.py" 2>/dev/null
  sleep 1
fi

echo "正在启动… 浏览器将自动打开 http://localhost:8310"
echo "关闭此窗口即可停止工具"
echo ""

( sleep 1 && open "http://localhost:8310" ) &

exec "$PY" server.py
