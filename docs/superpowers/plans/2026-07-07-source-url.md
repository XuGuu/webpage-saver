# 保存的文章带原文链接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每篇新保存的文章(HTML + Markdown)都记录原文 URL——HTML meta 区可点击「原文链接↗」,Markdown 元信息头带 `原文: URL`。

**Architecture:** `save_article(url, ...)` 在提取成功后单点注入 `data["url"] = url`;`generate_html`/`generate_markdown` 用 `data.get("url")` 读取,经 `_is_http_url` 守门(仅 http/https 才渲染,防 `javascript:` 伪协议),HTML 侧 URL 过 `html.escape`(quote=True)后进 href。无 url 键时两侧都不渲染,现有调用方零破坏。

**Tech Stack:** Python 3.10+ 标准库(re / html / unittest / unittest.mock),无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-07-source-url-design.md`

**基线:** 实施前 `python3 -m unittest test_save_webpage` = 158 项全绿。spec 列 8 项测试,落到 9 个测试方法(spec 第 4 项「伪协议两侧守门」拆成 MD/HTML 各一个方法)。完成后应为 167 项全绿。

**工作目录:** 所有命令在 `/Users/xugu/项目代码/webpage-saver` 下执行。

---

## 现状导读(改哪里)

- `save_webpage.py:261` — `_is_http_url(s)`:已存在,直接复用
- `save_webpage.py:1520-1535` — `generate_markdown` 元信息头:`meta_bits` 列表拼 `> 发布于 X · 公众号:Y`
- `save_webpage.py:1421-1430` — `generate_html` 元数据转义区(`_e = _html_lib.escape`,quote=True)与 `site_badge/author_line/date_line` 构造
- `save_webpage.py:1509-1511` — HTML 模板 meta 区 `<div class="meta">`(注意:整个模板是 f-string,CSS 花括号写成 `{{ }}`)
- `save_webpage.py:1458-1461` — `.meta`/`.badge`/`.author` 样式;`save_webpage.py:1494-1496` — 深色模式对应样式
- `save_webpage.py:1589-1611` — `save_article` 提取 try/except 块,成功后 `title = data["title"]`
- `test_save_webpage.py` — 新测试类插在文件末尾的 `if __name__ == "__main__":` 块**之前**;在方法内 `from save_webpage import ...`(现有惯例,见 `test_markdown_has_publish_header`,line 800)

---

### Task 1: generate_markdown 元信息头带原文 URL

**Files:**
- Modify: `save_webpage.py:1524-1535`(generate_markdown 元数据头)
- Test: `test_save_webpage.py`(文件末尾新增 TestSourceUrl 类)

- [ ] **Step 1.1: 写失败测试——在 test_save_webpage.py 末尾 `if __name__ == "__main__":` 块之前插入**

```python
class TestSourceUrl(unittest.TestCase):
    """保存的文章带原文链接(设计 2026-07-07)。"""

    # ---- Markdown 侧 ----

    def test_markdown_header_has_source_url(self):
        """元信息头末尾带「原文: URL」。"""
        from save_webpage import generate_markdown
        data = {"title": "T", "author": "某作者", "date": "2026-07-01",
                "site": "公众号", "markdown": "正文段落",
                "url": "https://mp.weixin.qq.com/s/abc123"}
        md = generate_markdown(data, [], "")
        first_line = md.splitlines()[0]
        self.assertTrue(first_line.startswith("> "))
        self.assertIn("原文: https://mp.weixin.qq.com/s/abc123", first_line)

    def test_markdown_url_only_still_outputs_header(self):
        """日期/作者全空,仅有 url 也输出元信息头。"""
        from save_webpage import generate_markdown
        data = {"title": "T", "author": "", "date": "", "site": "",
                "markdown": "正文", "url": "https://example.com/a"}
        md = generate_markdown(data, [], "")
        self.assertTrue(md.startswith("> 原文: https://example.com/a"))

    def test_markdown_no_url_no_source_line(self):
        """没有 url 键时头部不出现「原文」(向后兼容)。"""
        from save_webpage import generate_markdown
        data = {"title": "T", "author": "A", "date": "2026-07-01",
                "site": "公众号", "markdown": "正文"}
        md = generate_markdown(data, [], "")
        self.assertNotIn("原文:", md)

    def test_markdown_rejects_non_http_url(self):
        """javascript: 伪协议不进元信息头(守门)。"""
        from save_webpage import generate_markdown
        data = {"title": "T", "author": "", "date": "", "site": "",
                "markdown": "正文", "url": "javascript:alert(1)"}
        md = generate_markdown(data, [], "")
        self.assertNotIn("javascript:", md)
        self.assertNotIn("原文", md)
```

- [ ] **Step 1.2: 运行确认失败**

Run: `python3 -m unittest test_save_webpage.TestSourceUrl -v`
Expected: 4 项里 **2 失败 2 通过**——`test_markdown_header_has_source_url` 与 `test_markdown_url_only_still_outputs_header` FAIL(功能未实现);两个「不渲染」测试(no_url / rejects_non_http)现在就通过,它们是防回归的负向断言,属正常。若失败数不符,停下检查测试代码本身。

- [ ] **Step 1.3: 最小实现——修改 save_webpage.py 的 generate_markdown**

把(line 1524-1535):

```python
    # 元数据头:发布日期 + 作者/公众号
    date = data.get("date", "")
    author = data.get("author", "")
    site = data.get("site", "")
    meta_bits = []
    if date:
        meta_bits.append(f"发布于 {date}")
    if author:
        label = f"{site}:{author}" if site else author
        meta_bits.append(label)
    if meta_bits:
        md = "> " + " · ".join(meta_bits) + "\n\n" + md
```

改为(注释同步更新;URL 用纯文本而非 `[原文](url)`,规避 URL 含括号时破坏链接语法):

```python
    # 元数据头:发布日期 + 作者/公众号 + 原文链接
    date = data.get("date", "")
    author = data.get("author", "")
    site = data.get("site", "")
    meta_bits = []
    if date:
        meta_bits.append(f"发布于 {date}")
    if author:
        label = f"{site}:{author}" if site else author
        meta_bits.append(label)
    src_url = data.get("url") or ""
    if _is_http_url(src_url):
        meta_bits.append(f"原文: {src_url}")
    if meta_bits:
        md = "> " + " · ".join(meta_bits) + "\n\n" + md
```

- [ ] **Step 1.4: 运行确认通过**

Run: `python3 -m unittest test_save_webpage.TestSourceUrl -v`
Expected: 4 项全 PASS。

Run: `python3 -m unittest test_save_webpage`
Expected: `Ran 162 tests ... OK`(158 + 4)。

- [ ] **Step 1.5: Commit**

```bash
git add save_webpage.py test_save_webpage.py
git commit -m "feat: generate_markdown 元信息头追加原文 URL(http 守门)"
```

---

### Task 2: generate_html meta 区加「原文链接↗」

> **修订(2026-07-07,实施中发现):** 原版负向测试断言 `assertNotIn("src-link", html)` 与常驻 `<style>` 里的 `.src-link` CSS 规则矛盾(实现后永远失败)。已收紧为 `assertNotIn('class="src-link"', html)`——只匹配真实链接元素,不碰 CSS。CSS 常驻是有意设计,与 `.badge`/`.author` 一致。

**Files:**
- Modify: `save_webpage.py:1421-1430`(元数据转义区)、`save_webpage.py:1509-1511`(meta 区模板)、`save_webpage.py:1458-1461` 与 `1494-1496`(样式)
- Test: `test_save_webpage.py`(TestSourceUrl 类内追加)

- [ ] **Step 2.1: 写失败测试——在 TestSourceUrl 类内、Markdown 侧方法之后追加**

```python
    # ---- HTML 侧 ----

    def test_html_meta_has_source_link(self):
        """meta 区有可点击的原文链接。"""
        data = {"title": "T", "author": "A", "markdown": "正文", "site": "公众号",
                "images": [], "url": "https://mp.weixin.qq.com/s/abc123"}
        html = generate_html(data, [], "")
        self.assertIn('class="src-link"', html)
        self.assertIn('href="https://mp.weixin.qq.com/s/abc123"', html)
        self.assertIn("原文链接", html)

    def test_html_url_special_chars_escaped(self):
        """URL 里的 & 和 \" 要转义,不能破坏 href 属性(XSS)。"""
        data = {"title": "T", "author": "", "markdown": "正文", "site": "",
                "images": [],
                "url": 'https://example.com/a?x=1&y=2"onmouseover="alert(1)'}
        html = generate_html(data, [], "")
        self.assertIn("x=1&amp;y=2&quot;onmouseover=", html)
        self.assertNotIn('y=2"onmouseover', html)

    def test_html_no_url_no_source_link(self):
        """没有 url 键时不出现 src-link(向后兼容)。"""
        data = {"title": "T", "author": "A", "markdown": "正文", "site": "公众号",
                "images": []}
        html = generate_html(data, [], "")
        self.assertNotIn('class="src-link"', html)
        self.assertNotIn("原文链接", html)

    def test_html_rejects_non_http_url(self):
        """javascript: 伪协议不渲染成链接(守门)。"""
        data = {"title": "T", "author": "", "markdown": "正文", "site": "",
                "images": [], "url": "javascript:alert(1)"}
        html = generate_html(data, [], "")
        self.assertNotIn('class="src-link"', html)
        self.assertNotIn("javascript:alert", html)
```

- [ ] **Step 2.2: 运行确认失败**

Run: `python3 -m unittest test_save_webpage.TestSourceUrl -v`
Expected: 8 项里 **2 失败 6 通过**——`test_html_meta_has_source_link` 与 `test_html_url_special_chars_escaped` FAIL;两个 HTML 负向测试现在就通过(正常),Task 1 的 4 项保持 PASS。

- [ ] **Step 2.3: 实现——save_webpage.py 三处改动**

**(a) 元数据转义区**(现 line 1421-1430),在 `date_line = ...` 之后追加 `src_link` 构造:

```python
    _e = _html_lib.escape
    _title_html = _e(title)
    _author_html = _e(author)
    _date_html = _e(data.get("date", ""))
    _site_html = _e(site)
    site_badge = f'<span class="badge">{_site_html}</span>' if site else ""
    author_line = f'<span class="author">{_author_html}</span>' if author else ""
    date_line = f'<span class="date">{_date_html}</span>' if data.get("date") else ""
    src_url = data.get("url") or ""
    src_link = (f'<span><a class="src-link" href="{_e(src_url)}" target="_blank" '
                f'rel="noopener">原文链接↗</a></span>') if _is_http_url(src_url) else ""
```

**(b) meta 区模板**(现 line 1509-1511,在返回的 f-string 里),把:

```html
<div class="meta">
  {site_badge} {author_line} {date_line}
</div>
```

改为:

```html
<div class="meta">
  {site_badge} {author_line} {date_line} {src_link}
</div>
```

**(c) 样式**(模板 f-string 内,CSS 花括号必须写成双花括号 `{{ }}`)。

浅色:在 `.author {{ color: #333; font-weight: 500; }}`(现 line 1461)之后加两行:

```
.src-link {{ color: #999; text-decoration: none; border-bottom: 1px dotted #ccc; }}
.src-link:hover {{ color: #333; }}
```

深色:在深色模式块 `.badge {{ background: #2a2a2a; color: #ccc; }}`(现 line 1496)之后加两行:

```
  .src-link {{ color: #888; border-bottom-color: #555; }}
  .src-link:hover {{ color: #ddd; }}
```

- [ ] **Step 2.4: 运行确认通过**

Run: `python3 -m unittest test_save_webpage.TestSourceUrl -v`
Expected: 8 项全 PASS。

Run: `python3 -m unittest test_save_webpage`
Expected: `Ran 166 tests ... OK`(158 + 8)。

- [ ] **Step 2.5: Commit**

```bash
git add save_webpage.py test_save_webpage.py
git commit -m "feat: HTML meta 区加原文链接(html.escape 转义 + http 守门)"
```

---

### Task 3: save_article 单点注入 data["url"] + 端到端测试

**Files:**
- Modify: `save_webpage.py:1608-1611`(提取 except 块之后)
- Test: `test_save_webpage.py`(TestSourceUrl 类内追加)

- [ ] **Step 3.1: 写失败测试——在 TestSourceUrl 类内、HTML 侧方法之后追加**

注意:fake 字典**故意不含 "url" 键**,以证明是 save_article 注入的,而不是提取器给的。

```python
    # ---- 端到端 ----

    def test_save_article_files_contain_source_url(self):
        """保存后 HTML 与 MD 文件里都能找到原文 URL。"""
        import tempfile
        from unittest.mock import patch
        from save_webpage import save_article

        url = "https://mp.weixin.qq.com/s/abc123"
        with tempfile.TemporaryDirectory() as tmp:
            fake = {"title": "带链文章", "author": "A", "date": "2026-07-01",
                    "markdown": "正文", "images": [], "site": "公众号"}
            with patch("save_webpage.extract_wechat", return_value=fake), \
                 patch("save_webpage.detect_site", return_value="wechat"):
                result = save_article(url, tmp, formats=["html", "md"],
                                      use_subfolder=True)
            self.assertFalse(result.get("error"))
            html_file = next(f for f in result["files"] if f.endswith(".html"))
            md_file = next(f for f in result["files"] if f.endswith(".md"))
            with open(html_file, encoding="utf-8") as f:
                self.assertIn(f'href="{url}"', f.read())
            with open(md_file, encoding="utf-8") as f:
                self.assertIn(f"原文: {url}", f.read())
```

- [ ] **Step 3.2: 运行确认失败**

Run: `python3 -m unittest test_save_webpage.TestSourceUrl.test_save_article_files_contain_source_url -v`
Expected: FAIL——`AssertionError` 于 `assertIn(f'href="{url}"' ...)`(data 里没有 url 键,生成的文件不含链接)。

- [ ] **Step 3.3: 实现——save_article 注入**

在 save_webpage.py 提取 try/except 块之后(现 line 1608-1611),把:

```python
    except Exception as e:
        return {"error": str(e)}

    title = data["title"]
```

改为:

```python
    except Exception as e:
        return {"error": str(e)}

    data["url"] = url  # 原文链接随文章落盘(HTML meta 区 / MD 元信息头读取)

    title = data["title"]
```

- [ ] **Step 3.4: 运行确认通过 + 全量回归**

Run: `python3 -m unittest test_save_webpage.TestSourceUrl -v`
Expected: 9 项全 PASS。

Run: `python3 -m unittest test_save_webpage`
Expected: `Ran 167 tests ... OK`(158 + 9)。

- [ ] **Step 3.5: Commit**

```bash
git add save_webpage.py test_save_webpage.py
git commit -m "feat: save_article 注入 data[\"url\"],保存的文章带原文链接"
```

---

### Task 4: 收尾验证(不产生新代码)

**Files:** 无新改动;只跑验证。

- [ ] **Step 4.1: 全量测试**

Run: `python3 -m unittest test_save_webpage`
Expected: `Ran 167 tests ... OK`。

- [ ] **Step 4.2: 真实冒烟(可选但推荐,验收标准第 1/2 条)**

用一篇真实公众号文章跑一次保存(或用 Step 3.1 的 mock 方式手动生成一份),打开生成的 HTML:
- meta 区末尾可见「原文链接↗」,点击新标签页打开原文
- 深色模式下链接可读(灰色,悬停变亮)
- 打开 MD,首行元信息头形如 `> 发布于 2026-07-01 · 公众号:某作者 · 原文: https://...`

- [ ] **Step 4.3: 对照 spec 验收标准逐条打勾**

`docs/superpowers/specs/2026-07-07-source-url-design.md` 的「验收标准」三条全部满足后,进入 verification-before-completion 与 requesting-code-review 环节(由主会话执行,不在本计划内)。
