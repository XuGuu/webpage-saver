# save-webpage — 文章保存工具

看到好文章，粘贴链接，一键保存为干净的 HTML 和 Markdown。
自动识别公众号、小红书、知乎等网站，选择最优抓取方式。

## 安装

**Mac：** 双击 `setup_mac.sh`，自动安装依赖并启动

**Windows：** 双击 `setup_windows.bat`，自动安装依赖并启动

手动安装：

```bash
pip install -r requirements.txt
```

## 使用

### 图形界面（推荐）

```bash
python gui.py
```

粘贴链接 → 选保存格式 → 点「开始保存」。保存目录和格式偏好会自动记住。

### 命令行

```bash
# 公众号（不需要登录）
python save_webpage.py "https://mp.weixin.qq.com/s/xxx"

# 小红书（不需要登录）
python save_webpage.py "https://www.xiaohongshu.com/explore/xxx"

# 知乎（需要先启动 Chrome）
python save_webpage.py --launch-chrome
python save_webpage.py "https://zhuanlan.zhihu.com/p/xxx"

# CSDN（不需要登录）
python save_webpage.py "https://blog.csdn.net/username/article/details/xxx"

# 指定输出目录
python save_webpage.py "https://xxx" -o ./output

# 只保存 Markdown，不下载图片
python save_webpage.py "https://xxx" --no-html --no-images

# 不建子文件夹，直接存到输出目录
python save_webpage.py "https://xxx" --flat
```

## 输出效果

默认输出（HTML + Markdown + 图片）：

```
你选的目录/
  文章标题/
    文章标题.html       ← 打开就能看，有排版有图片
    文章标题.md         ← 复制给 LLM，token 省 80%
    images/
      img_1.jpg
      img_2.jpg
```

图片处理逻辑：
- **不勾选「图片」**：图片以 base64 嵌入 HTML 内部，单个文件自包含，双击直接看
- **勾选「图片」**：HTML 引用外部 `images/` 文件夹，同时保留图片文件

## 支持的网站

| 网站 | 方式 | 需要登录 |
|------|------|---------|
| 公众号 | requests + trafilatura | 不需要 |
| 小红书 | curl_cffi | 不需要 |
| 知乎 | DrissionPage + Chrome | 部分页面需要 |
| CSDN | 多方案自动降级（API → 手机版 → curl_cffi → print 模式） | 部分文章需要 |
| IT之家 | requests + trafilatura | 不需要 |
| 其他新闻站 | requests + trafilatura | 不需要 |

公众号和小红书直接粘链接就能抓，不需要任何登录操作。知乎需要先点「启动 Chrome」并在 Chrome 中登录知乎。

## 为什么同时输出 HTML 和 Markdown？

- **HTML**：给你看，有排版、有图片、好看
- **Markdown**：给 LLM 用，纯文本结构，token 效率比 HTML 高 80%

## 常见问题

**Q: 小红书抓不到内容？**
A: 小红书反爬较强，偶尔会被限制。等几分钟重试即可。

**Q: 知乎提示需要 Chrome？**
A: 知乎有 JS 挑战，必须用真实浏览器。点「启动 Chrome」，然后在弹出的 Chrome 中登录知乎。

**Q: CSDN 抓不到全文？**
A: CSDN 部分文章需要登录才能看全文。工具会自动尝试多种方案绕过，如果仍然失败，会在日志中提示。

**Q: Mac 能用吗？**
A: 能。Chrome 路径会自动检测，安装方式一样。

**Q: 只选 HTML，图片能看吗？**
A: 能。图片会以 base64 嵌入 HTML 内部，单个文件打开就能看到所有图片。

**Q: 图片没保存？**
A: 勾选「图片」才会保留 images/ 文件夹。不勾选时图片嵌入 HTML 后自动清理。
