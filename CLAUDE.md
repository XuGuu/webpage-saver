# save-webpage 项目

## 用途

把公众号、小红书、知乎、CSDN、新闻站的文章保存为干净的 HTML + Markdown。
核心场景：看到好文章 → 保存 → 交给 LLM 总结归纳。

## 技术栈

- Python 3.10+
- requests + trafilatura（公众号、新闻站）
- curl_cffi（小红书，模拟 TLS 指纹绕过反爬）
- DrissionPage（知乎，接管用户 Chrome）
- requests + BeautifulSoup + trafilatura（CSDN，多方案自动降级）
- tkinter（GUI，Python 内置）

## 文件结构

```
save_webpage.py       核心逻辑（提取、下载、生成）
gui.py                图形界面（格式选择、目录记忆）
requirements.txt      依赖清单
setup_windows.bat     Windows 一键启动
setup_mac.sh          Mac 一键启动
config.json           GUI 自动生成的用户偏好（保存目录、格式选择）
README.md             使用说明
CLAUDE.md             本文件
```

## 设计原则

- 自动识别网站，用户不需要选模式
- 公众号、小红书不需要登录，零门槛；CSDN 多数文章不需要登录，部分需要
- 同时输出 HTML（给人看）和 Markdown（给 LLM 用）
- 图片自动下载：不勾选「图片」时以 base64 嵌入 HTML（单文件自包含）；勾选时保留 images/ 文件夹
- 保存目录和格式偏好持久化到 config.json
