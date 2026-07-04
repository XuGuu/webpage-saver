#!/usr/bin/env python3
"""save-webpage — 网页文章保存工具

把公众号、小红书、知乎、新闻站等文章保存为干净的 HTML + Markdown。
自动识别网站类型，选择最优抓取方式。

用法:
    python save_webpage.py <url>              保存文章（HTML + Markdown + 图片）
    python save_webpage.py <url> -o ./output  指定输出目录
    python save_webpage.py --launch-chrome    启动调试 Chrome（知乎等需要）
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import trafilatura

# ==================== 配置 ====================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

CDP_PORT = 9222


# ==================== 工具函数 ====================

def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    return name[:100].strip('_. ')


def human_size(n: int) -> str:
    if n < 1024: return f"{n} B"
    if n < 1024 * 1024: return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _is_http_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def pick_url_from_clipboard(text: str) -> str:
    """剪贴板内容里挑出 URL，不是 URL 就返回空串。GUI 启动时自动填用。"""
    if not text:
        return ""
    stripped = text.strip()
    if _is_http_url(stripped) and not any(c in stripped for c in " \t\n"):
        return stripped
    return ""


def split_urls(text: str) -> list[str]:
    """把多行输入切成 URL 列表，每行还可按空白拆多个 URL，非 URL 忽略。"""
    urls = []
    for line in text.splitlines():
        for token in line.split():
            if _is_http_url(token):
                urls.append(token)
    return urls


def detect_site(url: str) -> str:
    """识别网站类型，返回: wechat / xhs / zhihu / csdn / generic"""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "mp.weixin.qq.com" in host:
        return "wechat"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xhs"
    if "zhihu.com" in host:
        return "zhihu"
    if "csdn.net" in host:
        return "csdn"
    return "generic"


# ==================== 图片下载 ====================

def download_image(url: str, save_dir: str, idx: int, referer: str = "") -> str | None:
    """下载单张图片，返回本地文件名。"""
    try:
        ext = ".jpg"
        parsed = urllib.parse.urlparse(url)
        path_ext = os.path.splitext(parsed.path)[1].lower()
        if path_ext in (".png", ".gif", ".webp", ".jpeg", ".jpg"):
            ext = path_ext

        fname = f"img_{idx}{ext}"
        headers = {**HEADERS}
        if referer:
            headers["Referer"] = referer
        # CSDN 图片需要 Referer 头
        elif "csdn" in url or "alicdn" in url:
            headers["Referer"] = "https://blog.csdn.net/"
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        with open(os.path.join(save_dir, fname), "wb") as f:
            f.write(r.content)
        return fname
    except Exception:
        return None


def download_images(urls: list[str], save_dir: str, referer: str = "") -> list[str | None]:
    """并发下载图片，返回本地文件名列表。"""
    os.makedirs(save_dir, exist_ok=True)
    results = [None] * len(urls)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(download_image, u, save_dir, i, referer): i for i, u in enumerate(urls)}
        for f in as_completed(futures):
            idx = futures[f]
            results[idx] = f.result()
    return results


# ==================== 提取器：公众号 ====================

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_STRUCTURE_TAGS = _HEADING_TAGS + ("ul", "ol", "blockquote", "pre")


def _inline_md(el) -> str:
    """行内感知的文本提取：strong/b 包成 **加粗**，跳过脚本样式。

    空白折叠为单个空格（保住英文单词边界），调用方对结果 strip()。
    """
    from bs4 import NavigableString, Comment

    parts = []
    for child in el.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(re.sub(r'\s+', ' ', str(child)))
        elif child.name in ("script", "style"):
            continue
        elif child.name in ("strong", "b"):
            inner = _inline_md(child).strip()
            if not inner:
                continue
            if inner.startswith("**") and inner.endswith("**"):
                parts.append(inner)  # 嵌套加粗（strong 套 b）不重复包
            else:
                parts.append(f"**{inner}**")
        elif child.name == "code":
            inner = child.get_text().strip()
            if inner:
                # 含反引号时用双反引号避免 markdown 语法歧义
                fence = "``" if "`" in inner else "`"
                pad = " " if inner.startswith("`") or inner.endswith("`") else ""
                parts.append(f"{fence}{pad}{inner}{pad}{fence}")
        elif child.name == "a":
            href = (child.get("href") or "").strip()
            text = _inline_md(child).strip()
            # 跳过页内锚点和危险 URL scheme（case-insensitive）
            unsafe = ("#", "javascript:", "data:", "vbscript:")
            if href and text and not href.lower().startswith(unsafe):
                parts.append(f"[{text}]({href})")
            elif text:
                parts.append(text)
        else:
            parts.append(_inline_md(child))
    return "".join(parts)


def _collect_wechat_content(el, md_parts: list, img_urls: list):
    """按文档顺序递归收集文字和图片，保留标题/列表/引用/加粗结构。"""
    from bs4 import NavigableString, Comment

    for child in el.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            # 裸露在盒子里的文字（没有标签包裹）
            text = str(child).strip()
            if text:
                md_parts.append(text)
        elif child.name == "img":
            src = child.get("data-src") or child.get("src", "")
            if src and "mmbiz" in src and not src.startswith("data:"):
                img_urls.append(src)
                md_parts.append(f"![图片{len(img_urls)}]({src})")
        elif child.name in ("script", "style"):
            continue
        elif child.name == "pre":
            # 代码块：三反引号围栏，原样保留缩进和换行
            code = child.get_text()
            code = code.strip("\n")
            if code:
                md_parts.append(f"```\n{code}\n```")
        elif child.name in _HEADING_TAGS and child.find("img") is None:
            # 标题：h1→#、h2→##……h4 以下封顶为 ####
            text = child.get_text(strip=True)
            if text:
                level = min(int(child.name[1]), 4)
                md_parts.append("#" * level + " " + text)
        elif child.name in ("ul", "ol") and child.find("img") is None:
            # 列表：每个直接子条目一行
            items = []
            for i, li in enumerate(child.find_all("li", recursive=False), 1):
                t = _inline_md(li).strip()
                if t:
                    items.append(f"- {t}" if child.name == "ul" else f"{i}. {t}")
            if items:
                md_parts.append("\n".join(items))
        elif child.name == "blockquote" and child.find("img") is None:
            # 引用块：每行加 > 前缀
            text = _inline_md(child).strip()
            if text:
                md_parts.append("\n".join(
                    "> " + ln.strip() for ln in text.splitlines() if ln.strip()))
        elif child.find(["img", *_STRUCTURE_TAGS]) is not None:
            # 盒子里藏着图片或结构元素：递归深入按顺序收集
            # （含图的标题/列表/引用也走这里——不丢图优先于保结构）
            _collect_wechat_content(child, md_parts, img_urls)
        else:
            text = _inline_md(child).strip()
            if text:
                md_parts.append(text)


def parse_wechat_html(html: str, url: str = "") -> dict:
    """从公众号页面 HTML 解析出标题、作者、正文和图片。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # 标题
    title = ""
    for pattern in [
        r'class="js_title_inner"[^>]*>(.*?)</span>',
        r'id="activity-name"[^>]*>(.*?)</h1>',
        r'<title>(.*?)</title>',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if t and len(t) > 2:
                title = t
                break
    if not title:
        title = "无标题"

    # 作者
    author_m = re.search(r'id="js_name"[^>]*>(.*?)<', html, re.DOTALL)
    author = author_m.group(1).strip() if author_m else ""

    # 正文：从 HTML 中提取，保留图片位置
    content = soup.find("div", id="js_content")
    img_urls = []
    md_parts = []

    if content:
        _collect_wechat_content(content, md_parts, img_urls)
        md = "\n\n".join(md_parts)
    else:
        # 兜底：用 trafilatura
        md = trafilatura.extract(html, output_format="markdown", url=url or None,
                                 include_links=True, include_images=False) or ""
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src and "mmbiz" in src and not src.startswith("data:"):
                img_urls.append(src)

    return {"title": title, "author": author, "markdown": md, "images": img_urls, "site": "公众号"}


def extract_wechat(url: str) -> dict:
    """公众号文章提取：下载页面后交给 parse_wechat_html 解析。"""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if r.encoding and r.encoding.lower() != "utf-8":
        r.encoding = r.apparent_encoding
    return parse_wechat_html(r.text, url=url)


# ==================== 提取器：小红书 ====================

def extract_xhs(url: str) -> dict:
    """小红书笔记提取。"""
    from curl_cffi import requests as cffi_requests

    r = cffi_requests.get(url, impersonate="chrome", headers={
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if r.status_code != 200:
        raise Exception(f"小红书返回 {r.status_code}，可能被限制")

    # 提取 __INITIAL_STATE__
    state_m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(.+?)\s*</script>', r.text, re.DOTALL)
    if not state_m:
        raise Exception("未找到页面数据，可能需要登录或链接无效")

    raw = state_m.group(1)
    raw = re.sub(r'(?<=[:,\[{])\s*undefined\s*(?=[,\]}])', 'null', raw)
    data = json.loads(raw)

    note_map = data.get("note", {}).get("noteDetailMap", {})
    if not note_map:
        raise Exception("笔记数据为空，可能需要登录")

    for nid, detail in note_map.items():
        n = detail.get("note", {})
        title = n.get("title", "无标题")
        desc = n.get("desc", "")
        author = n.get("user", {}).get("nickname", "")
        imgs = n.get("imageList", [])
        img_urls = [img.get("urlDefault", img.get("url", "")) for img in imgs]

        # 构造 Markdown
        tags = re.findall(r'#(\S+?)(?:\[|\s|$)', desc)
        md = f"# {title}\n\n**作者: {author}**\n\n{desc}\n"

        interact = n.get("interactInfo", {})
        likes = interact.get("likedCount", 0)
        collects = interact.get("collectedCount", 0)
        comments = interact.get("commentCount", 0)
        md += f"\n---\n点赞 {likes} | 收藏 {collects} | 评论 {comments}\n"

        return {
            "title": title, "author": author, "markdown": md,
            "images": img_urls, "site": "小红书",
        }

    raise Exception("未找到笔记数据")


# ==================== 提取器：知乎 ====================

def extract_zhihu(url: str) -> dict:
    """知乎文章/回答提取（需要 Chrome 调试端口）。"""
    from DrissionPage import ChromiumPage, ChromiumOptions

    co = ChromiumOptions()
    co.set_local_port(CDP_PORT)
    page = ChromiumPage(co)

    try:
        page.get(url)
        import time
        time.sleep(4)

        title = page.title.split(" - ")[0].strip() if page.title else "无标题"

        # 尝试多种选择器
        content = ""
        selectors = [
            ".Post-RichTextContainer",  # 专栏文章
            ".RichContent-inner",       # 问答回答
            ".RichText",                # 通用
            "article",
        ]
        for sel in selectors:
            try:
                el = page.ele(f"css:{sel}", timeout=2)
                if el and len(el.text) > 30:
                    content = el.html
                    break
            except Exception:
                continue

        if not content:
            body = page.ele("css:body")
            raise Exception(f"未找到正文内容。页面文本: {body.text[:100]}")

        # 用 trafilatura 从提取到的 HTML 中获取 markdown
        md = trafilatura.extract(content, output_format="markdown", url=url,
                                 include_links=True) or ""
        if len(md) < 30:
            # trafilatura 提取失败，直接用文本
            text = re.sub(r'<[^>]+>', '', content)
            md = text.strip()

        # 图片
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        img_urls = []
        for img in soup.find_all("img"):
            src = img.get("data-original") or img.get("data-actualsrc") or img.get("src")
            if src and not src.startswith("data:") and "zhimg" in src:
                img_urls.append(src)

        # 作者
        author = ""
        try:
            author_el = page.ele("css:.AuthorInfo-name", timeout=2)
            if author_el:
                author = author_el.text.strip()
        except Exception:
            pass

        return {
            "title": title, "author": author, "markdown": md,
            "images": img_urls, "site": "知乎",
        }

    finally:
        page.quit()


# ==================== 提取器：CSDN ====================

def _csdn_extract_article_id(url: str) -> str | None:
    """从 CSDN URL 提取文章 ID。"""
    m = re.search(r'/article/details/(\d+)', url)
    return m.group(1) if m else None


def _csdn_try_api(article_id: str, url: str) -> dict | None:
    """尝试用 CSDN 编辑器 API 获取 Markdown 内容（可能需要 cookie）。"""
    try:
        api_url = f"https://blog-console-api.csdn.net/v1/editor/getArticle?id={article_id}"
        r = requests.get(api_url, headers={
            **HEADERS,
            "Referer": url,
        }, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 200 and data.get("data"):
                d = data["data"]
                md = d.get("markdowncontent", "") or d.get("content", "")
                if md and len(md) > 100:
                    title = d.get("title", "")
                    author = d.get("username", "")
                    return {"title": title, "author": author, "markdown": md, "images": [], "site": "CSDN"}
    except Exception:
        pass
    return None


def _csdn_parse_html(html: str, url: str) -> dict:
    """从 HTML 解析 CSDN 文章。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # 标题
    title = ""
    title_el = soup.select_one("h1.title-article") or soup.select_one("title")
    if title_el:
        title = title_el.get_text(strip=True)
        title = re.sub(r'\s*[-_|].*$', '', title)
    if not title:
        title = "无标题"

    # 作者
    author = ""
    author_el = soup.select_one("a.follow-nickName") or soup.select_one(".user-info .name")
    if author_el:
        author = author_el.get_text(strip=True)

    # 正文
    content_el = soup.select_one("#content_views") or soup.select_one("article")
    if content_el:
        for tag in content_el.select("script, style, .hide-article-box, .blog-tags-box, .hide-article-box-bg"):
            tag.decompose()
        content_html = str(content_el)
        md = trafilatura.extract(content_html, output_format="markdown", url=url,
                                 include_links=True, include_images=True) or ""
    else:
        md = ""

    if len(md) < 50 and content_el:
        md = content_el.get_text(separator="\n", strip=True)

    # 检测登录墙截断
    if len(md) < 200 and "登录" in html:
        raise Exception("CSDN 需要登录才能看全文，请在浏览器中登录 CSDN 后重试")

    # 图片
    img_urls = []
    if content_el:
        for img in content_el.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if src and not src.startswith("data:") and ("csdn" in src or "alicdn" in src):
                img_urls.append(src)
    seen = set()
    unique_imgs = [u for u in img_urls if not (u in seen or seen.add(u))]

    return {"title": title, "author": author, "markdown": md, "images": unique_imgs, "site": "CSDN"}


def extract_csdn(url: str) -> dict:
    """CSDN 博客文章提取。按优先级尝试多种方案。"""
    article_id = _csdn_extract_article_id(url)

    # 方案1：编辑器 API（最稳定，但可能需要 cookie）
    if article_id:
        result = _csdn_try_api(article_id, url)
        if result:
            # API 返回的 markdown 没有图片，从页面补充
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(r.text, "html.parser")
                    content_el = soup.select_one("#content_views") or soup.select_one("article")
                    if content_el:
                        for img in content_el.find_all("img"):
                            src = img.get("data-src") or img.get("src")
                            if src and not src.startswith("data:") and ("csdn" in src or "alicdn" in src):
                                result["images"].append(src)
            except Exception:
                pass
            return result

    # 方案2：手机版页面（登录墙较弱）
    mobile_url = url.replace("blog.csdn.net", "m.blog.csdn.net")
    try:
        r = requests.get(mobile_url, headers={
            **HEADERS,
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        }, timeout=15)
        if r.status_code == 200 and len(r.text) > 5000:
            result = _csdn_parse_html(r.text, url)
            if len(result["markdown"]) > 200:
                return result
    except Exception:
        pass

    # 方案3：curl_cffi 模拟浏览器指纹
    html = ""
    try:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, impersonate="chrome", headers={
            "Referer": "https://blog.csdn.net/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if r.status_code == 200:
            html = r.text
    except Exception:
        pass

    # 方案4：view_mode=print
    if not html:
        print_url = url.split("?")[0] + "?view_mode=print"
        try:
            r = requests.get(print_url, headers={
                **HEADERS,
                "Referer": "https://blog.csdn.net/",
            }, timeout=20)
            if r.status_code == 200:
                html = r.text
        except Exception:
            pass

    # 方案5：普通 requests + utm_source
    if not html:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20,
                             params={"utm_source": "app_visitor"})
            if r.status_code == 200:
                html = r.text
        except Exception:
            pass

    # 方案6：最基础的 requests
    if not html:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        html = r.text

    return _csdn_parse_html(html, url)


# ==================== 提取器：通用 ====================

def extract_generic(url: str) -> dict:
    """通用网站提取（requests + trafilatura）。"""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if r.encoding and r.encoding.lower() != "utf-8":
        r.encoding = r.apparent_encoding
    html = r.text

    # 用 trafilatura 提取
    md = trafilatura.extract(html, output_format="markdown", url=url,
                             include_links=True, include_images=True) or ""

    # 标题
    title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    title = title_m.group(1).strip() if title_m else "无标题"
    title = re.sub(r'\s*[-_|].*$', '', title)  # 去掉网站名后缀

    # 如果 trafilatura 提取失败，用 BeautifulSoup 提取正文
    if len(md) < 50:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # 移除 script/style
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        md = text[:5000]

    # 图片
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    img_urls = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and not src.startswith("data:"):
            full = urllib.parse.urljoin(url, src)
            img_urls.append(full)

    return {"title": title, "author": "", "markdown": md, "images": img_urls[:20], "site": ""}


# ==================== 输出生成 ====================

def _img_to_base64(img_path: str) -> str:
    """将图片文件转为 base64 data URL。"""
    import base64
    ext = os.path.splitext(img_path)[1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
    with open(img_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def generate_html(data: dict, img_files: list[str | None], img_dir: str, embed_images: bool = False) -> str:
    """生成干净可读的 HTML。

    Args:
        embed_images: True 时将图片转为 base64 嵌入 HTML（单文件，不依赖外部文件夹）
    """
    title = data["title"]
    author = data["author"]
    md = data["markdown"]
    site = data["site"]

    # 构建 URL -> 本地路径的映射
    url_to_local = {}
    for i, (orig_url, local_file) in enumerate(zip(data.get("images", []), img_files)):
        if local_file and orig_url:
            if embed_images:
                full_path = os.path.join(img_dir, local_file)
                url_to_local[orig_url] = _img_to_base64(full_path)
            else:
                url_to_local[orig_url] = f"images/{local_file}"

    # 替换 markdown 中的图片 URL 为本地路径
    def replace_img_url(m):
        alt = m.group(1)
        url = m.group(2)
        local = url_to_local.get(url)
        if local:
            return f'![{alt}]({local})'
        return m.group(0)

    md = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', replace_img_url, md)

    # 如果 markdown 中没有图片标记，但有图片，追加到末尾
    if "![" not in md and img_files and any(img_files):
        md += "\n\n## 图片\n\n"
        for i, (orig_url, local_file) in enumerate(zip(data.get("images", []), img_files)):
            if local_file:
                if embed_images:
                    full_path = os.path.join(img_dir, local_file)
                    src = _img_to_base64(full_path)
                    md += f"![图片{i + 1}]({src})\n\n"
                else:
                    md += f"![图片{i + 1}](images/{local_file})\n\n"

    # Markdown 转简单 HTML
    import html as _html_lib
    html_body = md
    # 代码块：先取出 ```...``` 块用占位符锁住，最后再放回，避免内容被后续规则污染
    code_blocks: list[str] = []
    _SENTINEL = "CODEBLOCK{}"  # 私用区码点，正文里绝对不会出现

    def _stash_code(m):
        code_blocks.append(m.group(1))
        return _SENTINEL.format(len(code_blocks) - 1)

    html_body = re.sub(r'```\n?(.*?)\n?```', _stash_code, html_body, flags=re.DOTALL)

    # XSS 防护：转义 markdown 里的裸文本 HTML 元字符（<script> 之类不能直通到输出）
    # 代码块已被占位符替换，转义不影响；后续 markdown 语法自己生成的 <h1><strong> 等标签
    # 是硬编码字面串，此后不会再被转义
    html_body = _html_lib.escape(html_body, quote=False)

    html_body = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_body, flags=re.MULTILINE)
    # 列表：连续的 "- " / "n. " 行转为 <ul>/<ol>
    html_body = re.sub(
        r'((?:^- .+(?:\n|$))+)',
        lambda m: "<ul>" + "".join(
            f"<li>{ln[2:]}</li>" for ln in m.group(1).strip().splitlines()) + "</ul>\n",
        html_body, flags=re.MULTILINE)
    html_body = re.sub(
        r'((?:^\d+\. .+(?:\n|$))+)',
        lambda m: "<ol>" + "".join(
            f"<li>{ln.split('. ', 1)[-1]}</li>" for ln in m.group(1).strip().splitlines()) + "</ol>\n",
        html_body, flags=re.MULTILINE)
    # 引用块：连续的 "> " 行转为 <blockquote>（此时 > 已被转义为 &gt;）
    html_body = re.sub(
        r'((?:^&gt; .+(?:\n|$))+)',
        lambda m: "<blockquote>" + "<br>".join(
            ln[5:] for ln in m.group(1).strip().splitlines()) + "</blockquote>\n",
        html_body, flags=re.MULTILINE)
    html_body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_body)
    # 行内代码：先双反引号（可含单反引号），再单反引号
    html_body = re.sub(r'``\s?(.+?)\s?``', r'<code>\1</code>', html_body)
    html_body = re.sub(r'`([^`]+)`', r'<code>\1</code>', html_body)
    html_body = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', r'<img src="\2" alt="\1" style="max-width:100%;border-radius:8px;margin:12px 0">', html_body)
    html_body = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html_body)
    html_body = re.sub(r'\n\n+', '</p><p>', html_body)
    html_body = f"<p>{html_body}</p>"
    html_body = html_body.replace('\n', '<br>')
    # 块级元素不该包在 <p> 里：清理块后多余的 <br>，再把 <p> 解包
    html_body = re.sub(r'(</(?:h[1-4]|ul|ol|blockquote)>)<br>', r'\1', html_body)
    html_body = re.sub(
        r'<p>((?:<(?:h[1-4]|ul|ol|blockquote)[^>]*>.*?</(?:h[1-4]|ul|ol|blockquote)>)+)</p>',
        r'\1', html_body)

    # 放回代码块（HTML 转义 & < >）
    def _restore_code(m):
        idx = int(m.group(1))
        escaped = _html_lib.escape(code_blocks[idx])
        return f"<pre><code>{escaped}</code></pre>"

    html_body = re.sub(r'CODEBLOCK(\d+)', _restore_code, html_body)
    # 代码块外面被段落包装的空 <p> 清理
    html_body = re.sub(r'<p>(<pre><code>.*?</code></pre>)</p>', r'\1',
                       html_body, flags=re.DOTALL)

    site_badge = f'<span class="badge">{site}</span>' if site else ""
    author_line = f'<span class="author">{author}</span>' if author else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
       max-width: 800px; margin: 40px auto; padding: 20px; background: #fff; color: #333; line-height: 1.8; }}
h1 {{ font-size: 22px; margin-bottom: 8px; color: #1a1a1a; }}
h2 {{ font-size: 18px; margin: 24px 0 12px; color: #333; }}
h3 {{ font-size: 16px; margin: 20px 0 8px; color: #555; }}
h4 {{ font-size: 15px; margin: 16px 0 8px; color: #555; }}
.content pre {{ background: #f6f8fa; padding: 12px 14px; border-radius: 6px;
                overflow-x: auto; font-size: 13px; line-height: 1.5; margin: 12px 0; }}
.content pre code {{ background: transparent; padding: 0; }}
.content ul, .content ol {{ margin: 12px 0; padding-left: 26px; }}
.content li {{ margin: 6px 0; }}
.content blockquote {{ border-left: 3px solid #ddd; margin: 12px 0; padding: 2px 16px;
                       color: #666; background: #fafafa; border-radius: 0 6px 6px 0; }}
.meta {{ color: #999; font-size: 13px; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #f0f0f0; }}
.meta span {{ margin-right: 12px; }}
.badge {{ background: #f0f0f0; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
.author {{ color: #333; font-weight: 500; }}
.content {{ font-size: 15px; color: #333; }}
.content p {{ margin: 12px 0; }}
.content strong {{ color: #1a1a1a; }}
.content code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 14px; }}
.content img {{ max-width: 100%; border-radius: 8px; margin: 12px 0; cursor: pointer; transition: transform 0.15s; }}
.content img:hover {{ transform: scale(1.02); }}
.footer {{ color: #bbb; font-size: 12px; margin-top: 32px; padding-top: 16px; border-top: 1px solid #f0f0f0; text-align: center; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
  {site_badge} {author_line}
</div>
<div class="content">
{html_body}
</div>
<div class="footer">保存自{site or "网页"} · {author}</div>
</body>
</html>'''


def generate_markdown(data: dict, img_files: list[str | None], img_dir_name: str) -> str:
    """生成给 LLM 用的 Markdown。"""
    md = data["markdown"]

    if not img_dir_name:
        # 图片未保留，移除 markdown 中的图片标记
        md = re.sub(r'!\[[^\]]*\]\([^\)]*\)\n*', '', md)
        return md

    # 替换图片路径为本地路径
    for i, fname in enumerate(img_files):
        if fname:
            md = re.sub(
                r'!\[([^\]]*)\]\([^\)]+\)',
                f'![\\1]({img_dir_name}/{fname})',
                md, count=1
            )

    # 如果 markdown 里没有图片标记，手动添加
    valid_imgs = [(i, f) for i, f in enumerate(img_files) if f]
    if valid_imgs and "![" not in md:
        md += "\n\n## 图片\n\n"
        for idx, fname in valid_imgs:
            md += f"![图片{idx + 1}]({img_dir_name}/{fname})\n\n"

    return md


# ==================== 主流程 ====================

def save_article(url: str, output_dir: str, formats: list[str] | None = None,
                 use_subfolder: bool = True, log_fn=None) -> dict:
    """保存文章，返回结果信息。

    Args:
        url: 文章 URL
        output_dir: 输出目录
        formats: 输出格式列表，可选 "html"、"md"、"images"，默认全部
        use_subfolder: 是否用文章标题创建子文件夹
        log_fn: 日志回调 log_fn(msg)

    Returns:
        {"files": [文件路径列表], "title": ..., "images": [图片文件列表], "error": ...}
    """
    if formats is None:
        formats = ["html", "md", "images"]

    def log(msg):
        if log_fn:
            log_fn(msg)

    site_type = detect_site(url)
    log(f"识别: {site_type} | {url}")

    # 提取内容
    try:
        if site_type == "wechat":
            data = extract_wechat(url)
        elif site_type == "xhs":
            data = extract_xhs(url)
        elif site_type == "zhihu":
            data = extract_zhihu(url)
        elif site_type == "csdn":
            data = extract_csdn(url)
        else:
            data = extract_generic(url)
    except Exception as e:
        return {"error": str(e)}

    title = data["title"]
    keep_images = "images" in formats  # 是否保留图片文件夹
    need_images = keep_images or "html" in formats or "md" in formats  # 是否需要下载图片
    log(f"标题: {title}")
    log(f"正文: {len(data['markdown'])} 字")
    log(f"图片: {len(data['images'])} 张")

    # 确定输出目录
    safe_title = safe_filename(title) or "article"
    if use_subfolder:
        article_dir = os.path.join(output_dir, safe_title)
    else:
        article_dir = output_dir
    os.makedirs(article_dir, exist_ok=True)

    img_dir = os.path.join(article_dir, "images")

    # 下载图片（HTML 和 MD 都需要图片）
    img_files = []
    if need_images and data["images"]:
        os.makedirs(img_dir, exist_ok=True)
        log("下载图片...")
        # CSDN 图片需要 Referer 头
        referer = "https://blog.csdn.net/" if site_type == "csdn" else ""
        img_files = download_images(data["images"], img_dir, referer=referer)
        ok = sum(1 for f in img_files if f)
        log(f"图片: {ok}/{len(data['images'])} 张下载成功")

    # 输出文件列表
    output_files = []
    img_dir_name = "images"

    # 生成 HTML
    if "html" in formats:
        embed = not keep_images  # 不保留图片文件夹时，图片嵌入 HTML
        html_content = generate_html(data, img_files, img_dir, embed_images=embed)
        html_path = os.path.join(article_dir, f"{safe_title}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        output_files.append(html_path)
        log(f"HTML: {html_path}")

    # 生成 Markdown
    if "md" in formats:
        md_img_dir = "images" if keep_images else ""
        md_content = generate_markdown(data, img_files, md_img_dir)
        md_path = os.path.join(article_dir, f"{safe_title}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        output_files.append(md_path)
        log(f"Markdown: {md_path}")

    # 如果不保留图片，删除 images 文件夹
    if not keep_images and os.path.isdir(img_dir):
        import shutil
        shutil.rmtree(img_dir, ignore_errors=True)
        log("临时图片已清理")

    return {
        "files": output_files,
        "title": title,
        "site": data.get("site", ""),
        "images": [f for f in img_files if f] if keep_images else [],
    }


# ==================== Chrome 管理 ====================

def get_chrome_path() -> str:
    system = platform.system()
    if system == "Windows":
        for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                   r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]:
            if os.path.exists(p): return p
    elif system == "Darwin":
        p = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(p): return p
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            path = shutil.which(name)
            if path: return path
    raise FileNotFoundError("未找到 Chrome")


def get_chrome_user_data_dir() -> str:
    system = platform.system()
    if system == "Windows":
        return os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "User Data")
    elif system == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:
        return os.path.expanduser("~/.config/google-chrome")


def launch_chrome_debug():
    """启动带调试端口的 Chrome，通过 junction 保留登录态。"""
    import tempfile
    chrome = get_chrome_path()
    real_dir = get_chrome_user_data_dir()
    link_dir = os.path.join(tempfile.gettempdir(), ".save-webpage-chrome")

    if not os.path.exists(real_dir):
        raise FileNotFoundError(f"Chrome 配置目录不存在: {real_dir}")

    # 清理旧链接
    system = platform.system()
    if os.path.exists(link_dir):
        if system == "Windows":
            subprocess.run(["cmd", "/c", "rmdir", link_dir], capture_output=True)
        else:
            os.unlink(link_dir)

    # 创建 junction/symlink
    if system == "Windows":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", link_dir, real_dir],
            capture_output=True, check=True,
        )
    else:
        os.symlink(real_dir, link_dir)

    subprocess.Popen(
        [chrome, f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={link_dir}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"Chrome 已启动（调试端口 {CDP_PORT}，登录态已保留）")


def check_cdp() -> bool:
    try:
        r = requests.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(description="网页文章保存工具")
    parser.add_argument("url", nargs="?", help="文章 URL")
    parser.add_argument("-o", "--output", default=".", help="输出目录（默认当前目录）")
    parser.add_argument("--html", action="store_true", default=True, help="保存 HTML（默认开启）")
    parser.add_argument("--md", action="store_true", default=True, help="保存 Markdown（默认开启）")
    parser.add_argument("--no-html", action="store_true", help="不保存 HTML")
    parser.add_argument("--no-md", action="store_true", help="不保存 Markdown")
    parser.add_argument("--no-images", action="store_true", help="不下载图片")
    parser.add_argument("--flat", action="store_true", help="不创建子文件夹，直接存到输出目录")
    parser.add_argument("--launch-chrome", action="store_true", help="启动调试 Chrome")
    args = parser.parse_args()

    if args.launch_chrome:
        try:
            launch_chrome_debug()
        except Exception as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    # 知乎需要 Chrome
    if detect_site(args.url) == "zhihu" and not check_cdp():
        print("知乎需要 Chrome 调试端口，请先运行: python save_webpage.py --launch-chrome", file=sys.stderr)
        sys.exit(1)

    # 构建格式列表
    formats = []
    if not args.no_html: formats.append("html")
    if not args.no_md: formats.append("md")
    if not args.no_images: formats.append("images")

    def log(msg):
        print(msg)

    result = save_article(
        args.url, args.output,
        formats=formats,
        use_subfolder=not args.flat,
        log_fn=log,
    )

    if result.get("error"):
        print(f"\n失败: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"\n完成!")


if __name__ == "__main__":
    main()
