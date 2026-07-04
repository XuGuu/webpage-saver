# Windows 侧打包设计(make_app.bat + 桌面快捷方式)

日期:2026-07-09
状态:Auto Mode 下用户已批准整批,直接实施

## 目标

Windows 用户也能像 macOS `make_app.command` 一样双击一次,生成带自定义图标的、双击就启动的桌面入口——不需要装 PyInstaller、不需要额外依赖。

## 决策记录

### 打包形态:桌面快捷方式(.lnk)

不做 `.exe` 打包(PyInstaller 会把 Python 解释器打进去,几十 MB;项目用户既然已装 Python,再打一份浪费)。选桌面快捷方式:

- Windows 原生支持
- 可自定义图标(.ico)
- 目标是 `pythonw.exe`(和 python 不同:后者带控制台黑窗,前者纯 GUI)
- 双击体验和真 .exe 无差别

### 生成流程(`make_app.bat`)

1. `cd` 到脚本所在目录(项目根)
2. 如果 `assets/icon.ico` 不存在,用 Python 生成默认 ICO
3. 用 PowerShell 通过 `WScript.Shell` COM 对象创建桌面 `.lnk`,指向:
   - TargetPath: `pythonw.exe`
   - Arguments: `"{PROJECT}\gui.py"`
   - WorkingDirectory: 项目根
   - IconLocation: `{PROJECT}\assets\icon.ico`
4. 用户桌面上出现「文章保存工具」快捷方式

### 图标:`make_default_icon_ico(size=256)`

在 save_webpage.py 加一个纯 stdlib 函数:

- 复用现有的 `make_default_icon_png(size)`
- 手工构造 ICO 容器格式(6 字节 header + 16 字节 dir entry + PNG 数据)
- Windows Vista+ 支持 ICO 里直接内嵌 PNG(不需要 BMP 转换)
- 单尺寸 256×256 即可,Windows 会自动缩放到 16/32/48

**ICO 二进制布局**:

```
offset 0    uint16 reserved   = 0
offset 2    uint16 type       = 1 (icon)
offset 4    uint16 count      = 1
offset 6    uint8  width      = 0 (0 表示 256)
offset 7    uint8  height     = 0
offset 8    uint8  colors     = 0
offset 9    uint8  reserved   = 0
offset 10   uint16 planes     = 1
offset 12   uint16 bitcount   = 32
offset 14   uint32 size       = len(png_bytes)
offset 18   uint32 offset     = 22
offset 22   ... PNG data ...
```

### 用户自定义

替换 `assets/icon.ico` 为自己喜欢的图,重跑 `make_app.bat`——快捷方式指向的是文件路径,Windows 会自动加载新图标(可能需要清 icon cache 或右键"刷新")。

## 测试

- `test_make_default_icon_ico_signature`:输出以 ICO magic `\x00\x00\x01\x00` 开头
- `test_make_default_icon_ico_embeds_png`:offset 22 处能找到 PNG magic `\x89PNG`
- `test_make_app_bat_exists`:文件存在且非空(不需要在 macOS 上跑 bat 才是可测的)

现有 125 个测试不许坏。

## 明确不做(YAGNI)

- 多尺寸 ICO(单 256×256 够用);开始菜单入口(桌面 + 手动固定到任务栏就够);.msi/.exe 安装包(用户已装 Python 就行);更新工具(手动 git pull 简单直接)。

## README 更新

「打包成 macOS App」下方新增「打包成 Windows 快捷方式」小节。
