# 日常小舒适批次(7 项)设计

日期:2026-07-06
状态:Auto Mode 下用户已批准整批,直接实施

## 目标

每次保存文章的日常流程少几步、看着更舒服、翻旧文更快。

## 决策记录

### #1 保存后自动打开 HTML

- GUI 加 checkbox「保存完自动打开」,默认开
- 保存成功后调用 `subprocess.run(["open", html_path])`(mac)/ `os.startfile`(win)/ `xdg-open`(linux)
- 抽一个 `open_file(path)` 助手,平台无关
- **批量模式**:只打开最后一个成功的 HTML(避免弹一堆窗口)
- 首选打开 HTML(不选 HTML 时打开 MD)
- 偏好持久化到 config.json

### #2 文件夹命名加日期前缀

- GUI 加 checkbox「按日期归档(YYYY-MM-DD_ 前缀)」,默认关(保守)
- 开启后:`文章标题/` → `2026-06-26_文章标题/`
- 日期取 `data.get("date")`;无日期时用当前抓取日期
- 传参数 `date_prefix: bool` 给 `save_article`,不硬改现有行为
- 偏好持久化

### #3 复制"标题+作者+日期+链接"到剪贴板

- 保存成功后 GUI 显示按钮「📋 复制标题/作者/链接」,点击复制多行文本:

```
{title}
{author} · {date}
{url}
```

- 无日期/作者的行自动省略
- 用 tkinter 的 `root.clipboard_clear() + clipboard_append`
- 批量模式:按钮点击复制所有成功的(每篇之间空行分隔)

### #4 HTML 深色模式跟随系统

- 生成的 HTML CSS 补一段 `@media (prefers-color-scheme: dark)` 覆盖颜色
- 调色板:背景 `#1a1a1a`、正文 `#d4d4d4`、标题 `#f0f0f0`、code `#2d2d2d`、pre 保持,blockquote 微调、边框 `#333`
- 图片、图标不加滤镜
- 表格 header 深色 `#2a2a2a`,斑马纹 `#222`

### #5 HTML 里浮动侧边导航

- generate_html 后处理:扫描 `<h1>~<h4>` 收集为 TOC
- 生成 `<div class="toc-panel">` 固定在右侧
- 给每个 heading 加 `id="toc-N"`(N 递增),TOC 里的链接指向它
- 桌面(> 900px):固定右侧,宽 200px,`position: fixed`
- 窄屏:隐藏(YAGNI,不做移动折叠)
- 深色模式下同步换色

### #6 保存目录里生成目录索引 HTML

- 保存成功后调用 `rebuild_index(output_dir)`
- 扫描 `output_dir` 下所有直接子目录,读每个 HTML(找 `<h1>` + meta `.author` `.date`)
- 生成 `output_dir/目录.html`,倒序排列(按 mtime,足够可靠)
- 每篇卡片:标题、作者、日期、点击跳转
- 使用与文章一致的样式(深色/浅色同步)
- GUI 加按钮「打开目录」

### #7 失败重试队列

- 批量结束时,把失败的 URL + 原因保存到 GUI 的 `self.failed_urls` 列表
- 若非空,启用一个「🔁 重试失败」按钮
- 点击后只跑那批 URL,用现有 `_do_save` 逻辑
- 每次重试前清空当前状态,新一轮失败继续入队

## 测试

- 每项一组单测(能自动测的:剪贴板文本格式、日期前缀命名、TOC 生成、目录索引扫描;不能自动测的:UI 按钮显隐、subprocess 弹窗——用 mock)
- 现有 75 个测试不许坏
- 真实文章端到端

## 明确不做(YAGNI)

- 窄屏侧栏折叠动画;目录索引搜索/筛选;打开时的窗口位置控制;跨机器同步偏好;Linux 平台自动打开的桌面环境兼容测试。
