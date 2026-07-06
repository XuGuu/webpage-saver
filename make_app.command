#!/bin/bash
# 双击运行,把工具打包成 macOS 真 .app,可拖到 Applications 或 Dock。
# 用户可以放 assets/icon.png(1024x1024)自定义图标;没有就用默认渐变色。
set -e

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
APP_NAME="文章保存工具.app"
APP_PATH="$PROJECT_DIR/../$APP_NAME"

echo "→ 打包 $APP_NAME 到 $APP_PATH ..."

# 1. 清理旧 .app
rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# 2. 写 Info.plist
cat > "$APP_PATH/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>文章保存工具</string>
  <key>CFBundleDisplayName</key><string>文章保存工具</string>
  <key>CFBundleIdentifier</key><string>com.xugu.webpage-saver</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>run</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
PLIST

# 3. 写 launcher(项目路径 + python3 绝对路径都在打包时固化进去)
#    双击 .app 时 Finder 只给系统 PATH(/usr/bin:/bin:...),裸 `python3`
#    会解析到苹果自带、没装依赖的那个 → 启动即崩且无任何提示。
#    %q 让路径里的空格/引号/$ 都被安全转义,不会弄坏生成的脚本。
PYTHON_BIN="$(command -v python3 || true)"
RUN_FILE="$APP_PATH/Contents/MacOS/run"
{
  printf '%s\n' '#!/bin/bash'
  printf 'cd %q\n' "$PROJECT_DIR"
  printf 'PY=%q\n' "$PYTHON_BIN"
  cat <<'RUN'
export LANG="${LANG:-zh_CN.UTF-8}"
if [ ! -x "$PY" ]; then
  for CAND in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$CAND" ]; then PY="$CAND"; break; fi
  done
fi
if [ ! -x "$PY" ]; then
  osascript -e 'display dialog "没找到 Python3,无法启动。请先安装 Python 再试。" buttons {"知道了"} default button 1 with icon caution with title "文章保存工具"' >/dev/null 2>&1
  exit 1
fi
LOG="$HOME/Library/Logs/文章保存工具.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || LOG="${TMPDIR:-/tmp}/文章保存工具.log"
# 预检:依赖能否 import(gui.py 有 __main__ 守卫,import 无副作用);
# 失败就把日志末尾弹成系统对话框——绝不无声无息
if ! "$PY" -c "import gui" >"$LOG" 2>&1; then
  ERR=$(tail -n 2 "$LOG" | tr '\n' ' ' | tr '"\\' "''" | tail -c 300)
  osascript -e "display dialog \"文章保存工具启动失败:$ERR —— 完整日志在 $LOG\" buttons {\"知道了\"} default button 1 with icon caution with title \"文章保存工具\"" >/dev/null 2>&1
  exit 1
fi
# exec 让 python 顶替本进程:Dock 图标、Cmd-Q、退出登录信号都直达 GUI 本体
exec "$PY" gui.py >>"$LOG" 2>&1
RUN
} > "$RUN_FILE"
chmod +x "$RUN_FILE"

# 4. 图标:优先 assets/icon.png,没有就用 python 现场生成
#    (生成失败只影响图标,不能中断打包)
ICON_PNG="$PROJECT_DIR/assets/icon.png"
if [ ! -f "$ICON_PNG" ]; then
  if [ -n "$PYTHON_BIN" ]; then
    mkdir -p "$PROJECT_DIR/assets"
    echo "→ 生成默认蓝色渐变图标..."
    "$PYTHON_BIN" -c "
import sys
sys.path.insert(0, sys.argv[1])
from save_webpage import make_default_icon_png
open(sys.argv[2], 'wb').write(make_default_icon_png(1024))
" "$PROJECT_DIR" "$ICON_PNG" || echo "→ 图标生成失败,跳过(不影响使用)"
  else
    echo "→ 找不到 python3,跳过图标生成"
  fi
fi

# 5. PNG → iconset → icns(用 macOS 自带 sips + iconutil)
ICONSET="$APP_PATH/Contents/Resources/icon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
  sips -z $size $size "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1 || true
  sips -z $((size*2)) $((size*2)) "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || true
done
iconutil -c icns "$ICONSET" -o "$APP_PATH/Contents/Resources/icon.icns" 2>/dev/null || true
rm -rf "$ICONSET"
[ -f "$APP_PATH/Contents/Resources/icon.icns" ] || echo "→ 图标未能生成,App 将显示系统默认图标(不影响使用)"

echo "✓ 完成:$APP_PATH"
echo ""
echo "把它拖到「应用程序」或「程序坞」就可以像正常 App 一样用了。"
echo "首次双击若系统提示「无法验证开发者」,右键 → 打开 → 仍要打开。"
echo ""
read -n 1 -s -r -p "按任意键关闭..."
