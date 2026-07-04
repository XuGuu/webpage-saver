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

# 3. 写 launcher(把项目绝对路径固化进去)
cat > "$APP_PATH/Contents/MacOS/run" <<RUN
#!/bin/bash
cd "$PROJECT_DIR"
exec python3 gui.py
RUN
chmod +x "$APP_PATH/Contents/MacOS/run"

# 4. 图标:优先 assets/icon.png,没有就用 python 现场生成
ICON_PNG="$PROJECT_DIR/assets/icon.png"
if [ ! -f "$ICON_PNG" ]; then
  mkdir -p "$PROJECT_DIR/assets"
  echo "→ 生成默认蓝色渐变图标..."
  python3 -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
from save_webpage import make_default_icon_png
open('$ICON_PNG', 'wb').write(make_default_icon_png(1024))
"
fi

# 5. PNG → iconset → icns(用 macOS 自带 sips + iconutil)
ICONSET="$APP_PATH/Contents/Resources/icon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 64 128 256 512; do
  sips -z $size $size "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1
  sips -z $((size*2)) $((size*2)) "$ICON_PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1
done
iconutil -c icns "$ICONSET" -o "$APP_PATH/Contents/Resources/icon.icns" 2>/dev/null || true
rm -rf "$ICONSET"

echo "✓ 完成:$APP_PATH"
echo ""
echo "把它拖到「应用程序」或「程序坞」就可以像正常 App 一样用了。"
echo "首次双击若系统提示「无法验证开发者」,右键 → 打开 → 仍要打开。"
echo ""
read -n 1 -s -r -p "按任意键关闭..."
