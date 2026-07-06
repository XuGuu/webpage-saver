# 打包批次(PDF + macOS .app)设计

日期:2026-07-09
状态:Auto Mode 下用户已批准整批,直接实施

## 目标

让工具生成 PDF、且能像正常 App 一样双击打开(而不是 .command 脚本)。

## 决策记录

### #1 PDF 导出

- 保存格式多一个「PDF」选项(GUI checkbox,CLI `--pdf`)
- 实现:先生成 HTML,再用 Chrome headless 转 PDF
  - 命令:`{chrome} --headless --disable-gpu --no-sandbox --print-to-pdf={out.pdf} --print-to-pdf-no-header file://{html_path}`
  - 复用现有 `get_chrome_path()` 找 Chrome 二进制位置
- Chrome 未安装 → 抛出明确错误:「PDF 需要 Google Chrome。请先安装 Chrome 后再试。」
- 抽出函数 `generate_pdf(html_path: str, pdf_path: str) -> bool`(可 mock 单测)
- config.json 里持久化用户偏好

**为什么 Chrome 而不是 weasyprint/pdfkit**:
- 项目已经依赖 Chrome(知乎抓取用)
- weasyprint 需要 pango/cairo 等系统库,门槛高
- Chrome headless 输出质量最好、字体渲染 100% 一致

### #2 macOS .app 包装

- 新增双击运行的 `make_app.command`(shell 脚本)
- 运行后在项目目录旁生成 `文章保存工具.app/`:

```
文章保存工具.app/Contents/
  Info.plist           # bundle 元数据(CFBundleName、CFBundleExecutable、CFBundleIconFile)
  MacOS/run            # 启动器:cd 到项目 && python3 gui.py(带 chmod +x)
  Resources/icon.icns  # 图标
```

**图标生成**:
- 优先用 `assets/icon.png`(用户可自己放,1024×1024)
- 若无:make_app 用 Python 零依赖生成一个简单默认图(带渐变背景 + emoji-like 形状)——手工构造 PNG(struct + zlib)
- 用 macOS 自带 `sips` 生成多尺寸 PNG,`iconutil` 转 .icns
- 用户可随时替换 `assets/icon.png` 后重跑 `make_app.command` 更新

**为什么不用 py2app**:
- py2app 生成的 bundle 会打包 Python 解释器,>100MB
- 项目用户已装 Python,launcher 只需 4 行 shell 就够
- 目录结构简单,可读可改

### CLI 补 `--pdf` 保持对等

`main()` argparse 加 `--pdf`,默认关闭。

### GUI checkbox

保存格式区新增「PDF」checkbox,和 HTML/Markdown/图片同一行。持久化偏好 `pdf: bool`。

## 测试

- 命令构造:测试 `_build_chrome_pdf_cmd(chrome, html, out)` 返回正确参数列表(用真实 Chrome 路径或 mock)
- 找不到 Chrome:测试 `generate_pdf` 抛出预期错误消息(用 monkeypatch 模拟 FileNotFoundError)
- 图标生成:测试 `make_default_icon_png(1024)` 返回合法 PNG 字节流(以 `\x89PNG` 开头)
- 现有 119 个测试不许坏

## 明确不做(YAGNI)

- 页眉页脚、水印;.app 里嵌 Python(离线用户装 Python 就行);py2app 打自解压;.app 自动更新;PDF 密码保护;更多 PDF 格式选项(A4/Letter 页面尺寸——默认即可)。

## README 更新

「使用」章节:CLI 加 `--pdf` 示例;新增「打包成 macOS App」小节说明 `make_app.command`。

## 评审后修正(2026-07-09 code review)

- `need_images` 判断补齐 `"pdf" in formats`(否则 PDF-only 时图片不下载,导致 tmp html embed 为空)
- `_build_chrome_pdf_cmd` 用 `urllib.parse.quote` 编码 file:// URL,兼容路径含空格/中文
- `generate_pdf` 检查 subprocess 退出码 + 文件大小,失败时抛出带 stderr 的错误(不再静默)
- gui.py 自动打开时:优先 HTML,其次 PDF(修 PDF-only 保存不弹窗)
- 测试脚本路径从硬编码 `/Users/xugu/…` 改为 `os.path.dirname(save_webpage.__file__)`,可在任何机器上跑
- README:补 `--pdf` CLI 示例 + 「打包成 macOS App」小节
- CLAUDE.md 文件清单:补 `make_app.command`

## 实战修正(2026-07-06,用户实测双击无反应)

上文「launcher 只需 4 行 shell」的设计**已作废**:裸 `python3` 在 Finder 的受限
PATH(`/usr/bin:/bin:...`)下解析到苹果自带、没装依赖的解释器,启动即崩且无提示。
launcher 现为 ~25 行(make_app.command 打包时生成),要点:

- 打包时用 `printf %q` 固化 `command -v python3` 的**绝对路径**(路径特殊字符安全)
- 运行时若固化路径失效,按 homebrew → /usr/local → 系统 python3 顺序回退
- 预检 `"$PY" -c "import gui"`(gui.py 有 `__main__` 守卫,import 无副作用),
  失败把日志末尾用 osascript 弹成对话框——绝不无声无息
- 预检通过后 `exec "$PY" gui.py`:python 顶替启动器进程,App 身份/Dock/退出事件正确
- 日志固定写 `~/Library/Logs/文章保存工具.log`(HOME 不可写时降级 TMPDIR)
- 回归测试:test_save_webpage.TestAppLauncherFinderEnv(沙盒真实打包 + 受限 PATH 启动)
