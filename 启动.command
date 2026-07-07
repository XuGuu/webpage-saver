#!/bin/bash
# 双击这个文件即可启动文章保存工具。
# 首次使用如果 macOS 提示"无法验证开发者",到「系统设置 → 隐私与安全性」点「仍要打开」。
cd "$(dirname "$0")"
if command -v python3 &>/dev/null; then
    exec python3 gui.py
elif command -v python &>/dev/null; then
    exec python gui.py
else
    echo "错误:找不到 Python。请先安装 Python 3.10+。"
    echo "推荐:brew install python@3.12"
    read -n 1 -s -r -p "按任意键关闭..."
    exit 1
fi
