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
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
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


def build_toc(html_body: str) -> list:
    """从生成的 HTML body 里提取标题层级,做 TOC 数据。"""
    tocs = []
    for m in re.finditer(r'<h([1-4])\b[^>]*>(.*?)</h\1>', html_body, re.DOTALL):
        level = int(m.group(1))
        text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if text:
            tocs.append({"level": level, "text": text})
    return tocs


def format_share_text(data: dict, url: str = "") -> str:
    """构造复制到剪贴板的分享文本。空字段自动省略,不留孤零零的分隔符。"""
    lines = []
    title = (data.get("title") or "").strip()
    if title:
        lines.append(title)
    meta_bits = []
    for key in ("author", "date"):
        v = (data.get(key) or "").strip()
        if v:
            meta_bits.append(v)
    if meta_bits:
        lines.append(" · ".join(meta_bits))
    if url:
        lines.append(url)
    return "\n".join(lines)


def scan_saved_articles(root_dir: str) -> list:
    """扫描 root_dir 下含 .saved-article 标记的子文件夹,返回文章元数据列表。

    每项: {"title","author","date","html_path","folder","mtime"}。按 mtime 倒序(新的在前)。
    """
    result = []
    if not os.path.isdir(root_dir):
        return result
    for name in os.listdir(root_dir):
        sub = os.path.join(root_dir, name)
        if not os.path.isdir(sub):
            continue
        if not os.path.exists(os.path.join(sub, ".saved-article")):
            continue
        html_path = None
        for f in os.listdir(sub):
            if f.endswith(".html"):
                html_path = os.path.join(sub, f)
                break
        if not html_path:
            continue
        try:
            with open(html_path, encoding="utf-8") as fh:
                html = fh.read()
        except Exception:
            continue
        title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else name
        author_m = re.search(r'<span class="author">(.*?)</span>', html)
        author = author_m.group(1).strip() if author_m else ""
        date_m = re.search(r'<span class="date">(.*?)</span>', html)
        date = date_m.group(1).strip() if date_m else ""
        result.append({
            "title": title,
            "author": author,
            "date": date,
            "html_path": html_path,
            "folder": name,
            "mtime": os.path.getmtime(html_path),
        })
    result.sort(key=lambda x: x["mtime"], reverse=True)
    return result


def _build_stats_bar(articles: list) -> str:
    """构造统计条 HTML。"""
    import html as _h
    if not articles:
        return ""
    total = len(articles)
    dates = sorted(a["date"] for a in articles if a["date"])
    date_range = ""
    if dates:
        if dates[0] == dates[-1]:
            date_range = dates[0]
        else:
            date_range = f'{dates[0]} → {dates[-1]}'
    # Top 3 作者
    from collections import Counter
    author_counts = Counter(a["author"] for a in articles if a["author"])
    top = author_counts.most_common(3)
    top_html = " · ".join(f'{_h.escape(a)} {n}' for a, n in top) if top else ""

    parts = [f'<span class="stat"><strong>共 {total} 篇</strong></span>']
    if date_range:
        parts.append(f'<span class="stat">{date_range}</span>')
    if top_html:
        parts.append(f'<span class="stat">Top: {top_html}</span>')
    return '<div class="stats-bar">' + "".join(parts) + '</div>'


def build_index_html(root_dir: str) -> str:
    """生成目录索引 HTML(含搜索框、统计条、卡片列表)。"""
    import html as _h
    articles = scan_saved_articles(root_dir)
    cards = []
    for a in articles:
        rel_href = urllib.parse.quote(f"{a['folder']}/{os.path.basename(a['html_path'])}")
        title_esc = _h.escape(a["title"])
        meta_line = _h.escape(" · ".join(x for x in (a["author"], a["date"]) if x))
        cards.append(f'''
<a class="card" href="{rel_href}">
  <div class="card-title">{title_esc}</div>
  <div class="card-meta">{meta_line}</div>
</a>''')
    stats_bar = _build_stats_bar(articles)
    search_input = ('<input type="search" class="search" placeholder="搜索标题或作者..." autofocus>'
                    if articles else "")

    body = "".join(cards) if cards else '<p class="empty">还没有保存过文章</p>'
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>我的文章目录</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
       max-width: 800px; margin: 40px auto; padding: 20px;
       background: #fff; color: #333; }}
h1 {{ font-size: 22px; margin-bottom: 12px; }}
.stats-bar {{ font-size: 13px; color: #666; margin-bottom: 16px;
              padding: 10px 14px; background: #f6f8fa; border-radius: 6px; }}
.stats-bar .stat {{ margin-right: 16px; }}
.search {{ width: 100%; box-sizing: border-box; padding: 10px 14px; margin-bottom: 16px;
           font-size: 14px; border: 1px solid #ddd; border-radius: 6px;
           background: #fff; color: #333; outline: none; }}
.search:focus {{ border-color: #999; }}
.card {{ display: block; padding: 14px 16px; margin: 10px 0;
        background: #fafafa; border-radius: 8px; border: 1px solid #eee;
        text-decoration: none; color: inherit; transition: background 0.15s; }}
.card:hover {{ background: #f0f0f0; }}
.card-title {{ font-size: 15px; font-weight: 500; color: #1a1a1a; margin-bottom: 4px; }}
.card-meta {{ font-size: 12px; color: #888; }}
.empty {{ color: #999; text-align: center; padding: 40px; }}
.no-match {{ color: #999; text-align: center; padding: 20px; display: none; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a1a; color: #d4d4d4; }}
  h1 {{ color: #f0f0f0; }}
  .stats-bar {{ background: #222; color: #aaa; }}
  .search {{ background: #222; border-color: #333; color: #d4d4d4; }}
  .search:focus {{ border-color: #666; }}
  .card {{ background: #222; border-color: #333; }}
  .card:hover {{ background: #2a2a2a; }}
  .card-title {{ color: #f0f0f0; }}
  .card-meta {{ color: #888; }}
}}
</style>
</head>
<body>
<h1>我的文章目录</h1>
{stats_bar}
{search_input}
<div class="cards">{body}</div>
<div class="no-match">没有匹配的文章</div>
<script>
const input = document.querySelector('.search');
const cards = document.querySelectorAll('.card');
const noMatch = document.querySelector('.no-match');
if (input) {{
  input.addEventListener('input', () => {{
    const q = input.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach(card => {{
      const text = (card.querySelector('.card-title').textContent + ' '
                    + card.querySelector('.card-meta').textContent).toLowerCase();
      const show = !q || text.includes(q);
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    noMatch.style.display = visible === 0 ? 'block' : 'none';
  }});
}}
</script>
</body>
</html>'''


def open_file(path: str) -> bool:
    """跨平台在系统默认程序里打开文件。成功返回 True,失败静默返回 False。"""
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", path], check=False)
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


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
    """识别网站类型，返回: wechat / xhs / zhihu / csdn / weibo / bilibili / juejin / jianshu / generic"""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "mp.weixin.qq.com" in host:
        return "wechat"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xhs"
    if "zhihu.com" in host:
        return "zhihu"
    if "csdn.net" in host:
        return "csdn"
    if "weibo.com" in host or "weibo.cn" in host:
        return "weibo"
    if "bilibili.com" in host and ("/read/" in url or "/opus/" in url):
        return "bilibili"
    if "juejin.cn" in host:
        return "juejin"
    if "jianshu.com" in host:
        return "jianshu"
    return "generic"


def _zhihu_is_question_page(url: str) -> bool:
    """判断是否知乎问题页(应该抓所有答案)。/answer/ 结尾是单答案。"""
    parsed = urllib.parse.urlparse(url)
    return "/question/" in parsed.path and "/answer/" not in parsed.path


# ==================== 图片下载 ====================

def download_image(url: str, save_dir: str, idx: int, referer: str = "") -> str | None:
    """下载单张图片，返回本地文件名。网络异常最多重试 2 次（共 3 次）。"""
    ext = ".jpg"
    parsed = urllib.parse.urlparse(url)
    path_ext = os.path.splitext(parsed.path)[1].lower()
    if path_ext in (".png", ".gif", ".webp", ".jpeg", ".jpg"):
        ext = path_ext

    fname = f"img_{idx}{ext}"
    headers = {**HEADERS}
    if referer:
        headers["Referer"] = referer
    elif "csdn" in url or "alicdn" in url:
        headers["Referer"] = "https://blog.csdn.net/"

    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code >= 400:
                return None  # 4xx/5xx 直接放弃,不重试
            with open(os.path.join(save_dir, fname), "wb") as f:
                f.write(r.content)
            return fname
        except requests.RequestException:
            # 只在连接/超时等网络类异常重试
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return None
        except Exception:
            return None
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
_STRUCTURE_TAGS = _HEADING_TAGS + ("ul", "ol", "blockquote", "pre", "table")


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
        elif child.name in ("em", "i"):
            inner = _inline_md(child).strip()
            if inner and not (inner.startswith("*") and inner.endswith("*")):
                parts.append(f"*{inner}*")
            elif inner:
                parts.append(inner)
        elif child.name in ("del", "s", "strike"):
            inner = _inline_md(child).strip()
            if inner:
                parts.append(f"~~{inner}~~")
        elif child.name == "u":
            inner = _inline_md(child).strip()
            if inner:
                # markdown 无原生下划线，用 HTML 标签直通（generate_html 会保护）
                parts.append(f"<u>{inner}</u>")
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


def _render_list(list_el, depth: int) -> list:
    """渲染 ul/ol，子列表递归缩进（每层 2 空格）。"""
    lines = []
    indent = "  " * depth
    for i, li in enumerate(list_el.find_all("li", recursive=False), 1):
        # 先把子 ul/ol 摘出去，避免它们被当作 li 文本一起渲染
        sub_lists = []
        for sub in li.find_all(["ul", "ol"], recursive=False):
            sub_lists.append(sub.extract())
        # 剩下的整个 li 交给 _inline_md 处理,保留内嵌 strong/em/code 等格式
        text = _inline_md(li).strip()
        prefix = "- " if list_el.name == "ul" else f"{i}. "
        if text:
            lines.append(indent + prefix + text)
        elif sub_lists:
            # li 只含子列表、无文字时,仍保留空的父层标记以维持嵌套结构
            lines.append(indent + prefix)
        for sub in sub_lists:
            lines.extend(_render_list(sub, depth + 1))
    return lines


def _is_fake_heading(el) -> bool:
    """判断 <section>/<p> 是不是靠样式冒充的伪标题。保守:短 + 加粗 + 无裸文字/其他子标签。"""
    from bs4 import NavigableString

    # 只判定 <section>：<p> 里的 <strong> 是行内加粗，不是标题
    if el.name != "section":
        return False
    if el.find(["img", *_STRUCTURE_TAGS, "a", "code", "em", "i", "u", "del", "s"]):
        return False
    text = el.get_text(strip=True)
    if not text or len(text) >= 40:
        return False

    bare_text = 0
    tag_children = []
    for c in el.children:
        if isinstance(c, NavigableString):
            if str(c).strip():
                bare_text += 1
        elif getattr(c, "name", None):
            tag_children.append(c)

    # 条件 A：整个元素就是一个 <strong>/<b>，其他什么都没有
    if bare_text == 0 and len(tag_children) == 1 and tag_children[0].name in ("strong", "b"):
        return True
    # 条件 B：style 里 font-weight: bold/>=600,且元素结构简单（无子标签或只一个）
    style = (el.get("style") or "").lower()
    m = re.search(r'font-weight\s*:\s*(\w+)', style)
    if m:
        val = m.group(1)
        if (val in ("bold", "bolder") or (val.isdigit() and int(val) >= 600)) \
                and len(tag_children) <= 1:
            return True
    return False


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
        elif _is_fake_heading(child):
            # 样式冒充的伪标题（短 + 加粗）→ 三级标题
            text = child.get_text(strip=True)
            if text:
                md_parts.append("### " + text)
        elif child.name in ("ul", "ol") and child.find("img") is None:
            # 列表：每个直接子条目一行，子列表加 2 空格缩进
            lines = _render_list(child, depth=0)
            if lines:
                md_parts.append("\n".join(lines))
        elif child.name == "table" and child.find("img") is None:
            # 表格：首行当表头
            rows = []
            for tr in child.find_all("tr"):
                cells = [_inline_md(c).strip().replace("|", "\\|")
                         for c in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                header = rows[0] + [""] * (width - len(rows[0]))
                lines = ["| " + " | ".join(header) + " |",
                         "| " + " | ".join(["---"] * width) + " |"]
                for r in rows[1:]:
                    r = r + [""] * (width - len(r))
                    lines.append("| " + " | ".join(r) + " |")
                md_parts.append("\n".join(lines))
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

    # 发布日期：公众号 2026 起把 publish_time 从 DOM 里去掉，改从 var ct 时间戳取
    date = ""
    ct_m = re.search(r'var\s+ct\s*=\s*"(\d+)"', html)
    if ct_m:
        try:
            ts = int(ct_m.group(1))
            # 公众号服务器在北京时区(UTC+8)
            tz = datetime.timezone(datetime.timedelta(hours=8))
            date = datetime.datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            pass

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

    return {"title": title, "author": author, "date": date, "markdown": md,
            "images": img_urls, "site": "公众号"}


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
    """知乎文章/回答/问题页提取（需要 Chrome 调试端口）。"""
    from DrissionPage import ChromiumPage, ChromiumOptions
    from bs4 import BeautifulSoup
    import time

    co = ChromiumOptions()
    co.set_local_port(CDP_PORT)
    page = ChromiumPage(co)

    try:
        page.get(url)
        time.sleep(4)

        # 问题页:遍历所有 .List-item 收集回答
        if _zhihu_is_question_page(url):
            title = page.title.split(" - ")[0].strip() if page.title else "问题"
            answers = page.eles("css:.List-item", timeout=3)
            if not answers:
                # 兜底:某个回答框仍然出现
                answers = page.eles("css:.AnswerItem", timeout=2)
            parts = [f"# {title}\n"]
            img_urls = []
            for i, item in enumerate(answers[:10], 1):  # 最多 10 条,YAGNI
                try:
                    author_el = item.ele("css:.AuthorInfo-name", timeout=1)
                    ans_author = author_el.text.strip() if author_el else f"匿名{i}"
                except Exception:
                    ans_author = f"匿名{i}"
                content_el = None
                for sel in (".RichContent-inner", ".RichText"):
                    try:
                        content_el = item.ele(f"css:{sel}", timeout=1)
                        if content_el and len(content_el.text) > 30:
                            break
                    except Exception:
                        continue
                if not content_el:
                    continue
                ans_html = content_el.html
                ans_md = trafilatura.extract(ans_html, output_format="markdown",
                                             include_links=True) or content_el.text
                parts.append(f"\n## 回答者:{ans_author}\n\n{ans_md}\n")
                # 图片
                soup = BeautifulSoup(ans_html, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("data-original") or img.get("data-actualsrc") or img.get("src")
                    if src and not src.startswith("data:") and "zhimg" in src:
                        img_urls.append(src)
            if len(parts) == 1:
                raise Exception("未找到任何回答,可能需要登录或页面结构变化")
            return {"title": title, "author": "多位知乎作者",
                    "markdown": "\n".join(parts), "images": img_urls,
                    "site": "知乎", "date": ""}

        # 单答案/专栏文章:原逻辑
        title = page.title.split(" - ")[0].strip() if page.title else "无标题"
        content = ""
        selectors = [".Post-RichTextContainer", ".RichContent-inner", ".RichText", "article"]
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

        md = trafilatura.extract(content, output_format="markdown", url=url,
                                 include_links=True) or ""
        if len(md) < 30:
            md = re.sub(r'<[^>]+>', '', content).strip()

        soup = BeautifulSoup(content, "html.parser")
        img_urls = []
        for img in soup.find_all("img"):
            src = img.get("data-original") or img.get("data-actualsrc") or img.get("src")
            if src and not src.startswith("data:") and "zhimg" in src:
                img_urls.append(src)

        author = ""
        try:
            author_el = page.ele("css:.AuthorInfo-name", timeout=2)
            if author_el:
                author = author_el.text.strip()
        except Exception:
            pass

        return {"title": title, "author": author, "markdown": md,
                "images": img_urls, "site": "知乎", "date": ""}

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

    # 检测登录墙截断,给出更明确的引导步骤
    if len(md) < 200 and "登录" in html:
        raise Exception(
            "CSDN 文章需要登录才能看全文。\n"
            "解决办法:\n"
            "1. 用浏览器打开该文章\n"
            "2. 登录 CSDN 账号(免费)\n"
            "3. 回到本工具重新点「开始保存」")

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


# ==================== 提取器:微博/B站/掘金/简书(fixture 可测) ====================

def _extract_by_selectors(html: str, url: str, site: str,
                          content_selectors: list, title_selectors: list,
                          author_selectors: list = None,
                          img_domain_marker: str = "") -> dict:
    """通用"选择器优先 + trafilatura 兜底"提取器。fixture 可单测。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # 标题:先按 selector,后 og:title,最后 <title>
    title = ""
    for sel in title_selectors:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(strip=True)
            if t and len(t) > 1:
                title = t
                break
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        tl = soup.find("title")
        if tl:
            title = re.sub(r'\s*[-|_].*$', '', tl.get_text(strip=True))
    if not title:
        title = "无标题"

    # 作者
    author = ""
    for sel in (author_selectors or []):
        el = soup.select_one(sel)
        if el:
            author = el.get_text(strip=True)
            if author:
                break

    # 正文:按 selector 找第一个非空容器
    content_el = None
    for sel in content_selectors:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 20:
            content_el = el
            break

    if content_el:
        content_html = str(content_el)
        md = trafilatura.extract(content_html, output_format="markdown", url=url,
                                 include_links=True, include_images=False) or ""
        if len(md) < 30:
            md = content_el.get_text(separator="\n", strip=True)
    else:
        # 兜底:整页 trafilatura
        md = trafilatura.extract(html, output_format="markdown", url=url,
                                 include_links=True, include_images=False) or ""

    # 图片:content_el 里所有图都收(已经限定在正文范围);
    # 兜底 scope=整页时才用 img_domain_marker 过滤,避免收头像/按钮之类
    img_urls = []
    if content_el:
        for img in content_el.find_all("img"):
            src = (img.get("data-src") or img.get("data-original-src")
                   or img.get("data-original") or img.get("src") or "").strip()
            if src and not src.startswith("data:"):
                img_urls.append(src)
    else:
        for img in soup.find_all("img"):
            src = (img.get("data-src") or img.get("data-original-src")
                   or img.get("data-original") or img.get("src") or "").strip()
            if src and not src.startswith("data:"):
                if not img_domain_marker or img_domain_marker in src:
                    img_urls.append(src)

    return {"title": title, "author": author, "markdown": md,
            "images": img_urls, "site": site, "date": ""}


def parse_weibo_html(html: str, url: str) -> dict:
    return _extract_by_selectors(
        html, url, "微博",
        content_selectors=["div.WB_editor_iframe_new", "article", "div.article-main",
                           "div.wbpro-feed-content"],
        title_selectors=["h1.title", "meta[property='og:title']"],
        author_selectors=["a.author", ".user-info .name"],
        img_domain_marker="sinaimg")


def parse_bili_html(html: str, url: str) -> dict:
    return _extract_by_selectors(
        html, url, "B站专栏",
        content_selectors=["div#read-article-holder", "div.opus-module-content",
                           "div.article-holder", "article"],
        title_selectors=["h1.title", "h1.opus-title"],
        author_selectors=["a.author", ".up-name"],
        img_domain_marker="hdslb")


def parse_juejin_html(html: str, url: str) -> dict:
    return _extract_by_selectors(
        html, url, "掘金",
        content_selectors=["div.markdown-body", "article.article"],
        title_selectors=["h1.article-title", "h1"],
        author_selectors=["a.author-name", ".author-name"],
        img_domain_marker="juejin")


def parse_jianshu_html(html: str, url: str) -> dict:
    return _extract_by_selectors(
        html, url, "简书",
        content_selectors=["article", "div._2rhmJa", "div.show-content"],
        title_selectors=["h1.title", "h1._1RuRku", "h1"],
        author_selectors=[".author .name", "a.author"],
        img_domain_marker="jianshu")


def _fetch_and_parse(url: str, parse_fn, use_cffi: bool = False) -> dict:
    """通用抓取+解析:先请求,再交给 parse_fn。"""
    if use_cffi:
        from curl_cffi import requests as cffi_requests
        r = cffi_requests.get(url, impersonate="chrome",
                              headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        if r.status_code != 200:
            raise Exception(f"抓取返回 {r.status_code}(可能被反爬拦截或需要登录)")
        html = r.text
    else:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        if r.encoding and r.encoding.lower() != "utf-8":
            r.encoding = r.apparent_encoding
        html = r.text
    if not html:
        raise Exception("抓取失败,页面为空")
    return parse_fn(html, url)


def extract_weibo(url: str) -> dict:
    return _fetch_and_parse(url, parse_weibo_html, use_cffi=True)


def extract_bili(url: str) -> dict:
    return _fetch_and_parse(url, parse_bili_html, use_cffi=False)


def extract_juejin(url: str) -> dict:
    return _fetch_and_parse(url, parse_juejin_html, use_cffi=False)


def extract_jianshu(url: str) -> dict:
    return _fetch_and_parse(url, parse_jianshu_html, use_cffi=True)


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

    # 允许列表标签直通：把 <u>…</u> 先保护成占位符，转义后再放回
    inline_html: list[str] = []

    def _stash_inline(m):
        inline_html.append(m.group(0))
        return f"\uE010UTAG{len(inline_html) - 1}\uE011"

    html_body = re.sub(r'</?u>', _stash_inline, html_body)

    # XSS 防护：转义 markdown 里的裸文本 HTML 元字符（<script> 之类不能直通到输出）
    # 代码块已被占位符替换，转义不影响；后续 markdown 语法自己生成的 <h1><strong> 等标签
    # 是硬编码字面串，此后不会再被转义
    html_body = _html_lib.escape(html_body, quote=False)

    html_body = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_body, flags=re.MULTILINE)
    # 列表：连续的 "- " 或 "n. " 行(允许 2 空格缩进的嵌套)转为 <ul>/<ol>
    def _render_md_list(lines: list, base_indent: int, ordered: bool) -> str:
        """把嵌套缩进的 markdown 列表转成嵌套 <ul>/<ol>。"""
        tag = "ol" if ordered else "ul"
        html = f"<{tag}>"
        i = 0
        while i < len(lines):
            ln = lines[i]
            m = re.match(r'( *)(-|\d+\.) +(.*)', ln)
            if not m or len(m.group(1)) != base_indent:
                break
            content = m.group(3)
            # 找同一 <li> 的嵌套子列表(缩进更深的连续行)
            sub = []
            j = i + 1
            while j < len(lines):
                nested = re.match(r'( *)(-|\d+\.) +', lines[j])
                if not nested or len(nested.group(1)) <= base_indent:
                    break
                sub.append(lines[j])
                j += 1
            html += f"<li>{content}"
            if sub:
                sub_indent = len(re.match(r'( *)', sub[0]).group(1))
                sub_ordered = bool(re.match(r' *\d+\. ', sub[0]))
                html += _render_md_list(sub, sub_indent, sub_ordered)
            html += "</li>"
            i = j
        html += f"</{tag}>"
        return html

    def _list_block_sub(m):
        block = m.group(1).strip()
        lines = block.splitlines()
        ordered = bool(re.match(r'\d+\.', lines[0]))
        return _render_md_list(lines, 0, ordered) + "\n"

    html_body = re.sub(
        r'((?:^(?: *(?:-|\d+\.) +).+(?:\n|$))+)',
        _list_block_sub, html_body, flags=re.MULTILINE)
    # 表格：连续的 "| … |" 行转为 <table>；分隔行 "| --- | … |" 之前的是表头
    def _table_sub(m):
        rows = [ln.strip() for ln in m.group(1).strip().splitlines()]
        def cells_of(ln):
            # 用负向前瞻切分 '|',跳过被 '\' 转义的 '\|',然后把 '\|' 还原为 '|'
            parts = re.split(r'(?<!\\)\|', ln.strip('|'))
            return [c.strip().replace('\\|', '|') for c in parts]
        head = cells_of(rows[0])
        body_rows = [cells_of(r) for r in rows[2:]]
        thead = "<thead><tr>" + "".join(f"<th>{c}</th>" for c in head) + "</tr></thead>"
        tbody = "<tbody>" + "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
            for r in body_rows) + "</tbody>"
        return f"<table>{thead}{tbody}</table>\n"
    html_body = re.sub(
        r'((?:^\|.+\|(?:\n|$))+)',
        lambda m: _table_sub(m) if '| --- |' in m.group(0) or '|---|' in m.group(0)
                                    or '| ---' in m.group(0) else m.group(0),
        html_body, flags=re.MULTILINE)
    # 引用块：连续的 "> " 行转为 <blockquote>（此时 > 已被转义为 &gt;）
    html_body = re.sub(
        r'((?:^&gt; .+(?:\n|$))+)',
        lambda m: "<blockquote>" + "<br>".join(
            ln[5:] for ln in m.group(1).strip().splitlines()) + "</blockquote>\n",
        html_body, flags=re.MULTILINE)
    html_body = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_body)
    # 斜体、删除线（在 ** 之后，避免 * 被误当成一半的 **;两侧要非字/非星，避免误吞乘号）
    html_body = re.sub(r'(?<![\*\w])\*([^\*\n]+?)\*(?![\*\w])', r'<em>\1</em>', html_body)
    html_body = re.sub(r'~~(.+?)~~', r'<del>\1</del>', html_body)
    # 行内代码：先双反引号（可含单反引号），再单反引号
    html_body = re.sub(r'``\s?(.+?)\s?``', r'<code>\1</code>', html_body)
    html_body = re.sub(r'`([^`]+)`', r'<code>\1</code>', html_body)
    html_body = re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', r'<img src="\2" alt="\1" style="max-width:100%;border-radius:8px;margin:12px 0">', html_body)
    html_body = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html_body)
    html_body = re.sub(r'\n\n+', '</p><p>', html_body)
    html_body = f"<p>{html_body}</p>"
    html_body = html_body.replace('\n', '<br>')
    # 块级元素不该包在 <p> 里：清理块后多余的 <br>，再把 <p> 解包
    html_body = re.sub(r'(</(?:h[1-4]|ul|ol|blockquote|table)>)<br>', r'\1', html_body)
    html_body = re.sub(
        r'<p>((?:<(?:h[1-4]|ul|ol|blockquote|table)[^>]*>.*?</(?:h[1-4]|ul|ol|blockquote|table)>)+)</p>',
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
    # 放回被保护的 <u> 标签
    html_body = re.sub(
        r'UTAG(\d+)',
        lambda m: inline_html[int(m.group(1))], html_body)

    # 给标题加锚点 id 并构造侧边 TOC
    _anchor_counter = [0]

    def _add_anchor(m):
        _anchor_counter[0] += 1
        return f'<h{m.group(1)} id="toc-{_anchor_counter[0]}">{m.group(2)}</h{m.group(1)}>'

    html_body = re.sub(r'<h([1-4])>(.*?)</h\1>', _add_anchor, html_body, flags=re.DOTALL)
    tocs = build_toc(html_body)
    if tocs:
        toc_items = []
        for i, h in enumerate(tocs, 1):
            toc_items.append(
                f'<a href="#toc-{i}" class="toc-l{h["level"]}">{h["text"]}</a>')
        toc_panel = ('<nav class="toc-panel"><div class="toc-title">目录</div>'
                     + "".join(toc_items) + '</nav>')
    else:
        toc_panel = ""

    # HTML 转义元数据,防止 title/author/date/site 里的 < > & 破坏页面或 XSS
    _e = _html_lib.escape
    _title_html = _e(title)
    _author_html = _e(author)
    _date_html = _e(data.get("date", ""))
    _site_html = _e(site)
    site_badge = f'<span class="badge">{_site_html}</span>' if site else ""
    author_line = f'<span class="author">{_author_html}</span>' if author else ""
    date_line = f'<span class="date">{_date_html}</span>' if data.get("date") else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_title_html}</title>
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
.content table {{ border-collapse: collapse; margin: 16px 0; width: 100%; font-size: 14px; }}
.content th, .content td {{ border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; }}
.content th {{ background: #f6f8fa; font-weight: 600; }}
.content tbody tr:nth-child(even) {{ background: #fafbfc; }}
.content u {{ text-decoration: underline; }}
.content em {{ font-style: italic; }}
.content del {{ text-decoration: line-through; color: #999; }}
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
.toc-panel {{ position: fixed; top: 40px; right: 24px; width: 200px; max-height: 80vh;
              overflow-y: auto; font-size: 13px; color: #666; background: #fafafa;
              padding: 12px 14px; border-radius: 8px; border: 1px solid #eee; }}
.toc-panel .toc-title {{ font-weight: 600; margin-bottom: 8px; color: #333; }}
.toc-panel a {{ display: block; text-decoration: none; color: #666; padding: 3px 0;
                line-height: 1.4; border-radius: 3px; }}
.toc-panel a:hover {{ color: #1a1a1a; background: #f0f0f0; padding-left: 4px; }}
.toc-panel .toc-l1 {{ padding-left: 0; font-weight: 500; }}
.toc-panel .toc-l2 {{ padding-left: 12px; }}
.toc-panel .toc-l3 {{ padding-left: 24px; font-size: 12px; }}
.toc-panel .toc-l4 {{ padding-left: 36px; font-size: 12px; color: #999; }}
@media (max-width: 1100px) {{ .toc-panel {{ display: none; }} }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #1a1a1a; color: #d4d4d4; }}
  h1, .content strong {{ color: #f0f0f0; }}
  h2, h3, h4 {{ color: #ccc; }}
  .content code {{ background: #2d2d2d; color: #e4a4a4; }}
  .content pre {{ background: #0d1117; }}
  .content pre code {{ color: #d4d4d4; }}
  .content blockquote {{ border-color: #444; background: #222; color: #aaa; }}
  .content table {{ }}
  .content th {{ background: #2a2a2a; color: #eee; }}
  .content th, .content td {{ border-color: #333; }}
  .content tbody tr:nth-child(even) {{ background: #222; }}
  .content del {{ color: #666; }}
  .meta {{ color: #999; border-color: #333; }}
  .author {{ color: #ccc; }}
  .badge {{ background: #2a2a2a; color: #ccc; }}
  .footer {{ color: #555; border-color: #333; }}
  .toc-panel {{ background: #202020; border-color: #333; color: #aaa; }}
  .toc-panel .toc-title {{ color: #ddd; }}
  .toc-panel a {{ color: #999; }}
  .toc-panel a:hover {{ color: #f0f0f0; background: #2a2a2a; }}
  .content a {{ color: #7db8ff; }}
}}
</style>
</head>
<body>
{toc_panel}
<h1>{_title_html}</h1>
<div class="meta">
  {site_badge} {author_line} {date_line}
</div>
<div class="content">
{html_body}
</div>
<div class="footer">保存自{_site_html or "网页"} · {_author_html}</div>
</body>
</html>'''


def generate_markdown(data: dict, img_files: list[str | None], img_dir_name: str) -> str:
    """生成给 LLM 用的 Markdown。"""
    md = data["markdown"]

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
                 use_subfolder: bool = True, log_fn=None,
                 date_prefix: bool = False) -> dict:
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
        elif site_type == "weibo":
            data = extract_weibo(url)
        elif site_type == "bilibili":
            data = extract_bili(url)
        elif site_type == "juejin":
            data = extract_juejin(url)
        elif site_type == "jianshu":
            data = extract_jianshu(url)
        else:
            data = extract_generic(url)
    except Exception as e:
        return {"error": str(e)}

    title = data["title"]
    keep_images = "images" in formats  # 是否保留图片文件夹
    # HTML/MD/PDF 都要图;PDF 单独选中时也需要下载,让 embed_images 有素材
    need_images = keep_images or "html" in formats or "md" in formats or "pdf" in formats
    log(f"标题: {title}")
    log(f"正文: {len(data['markdown'])} 字")
    log(f"图片: {len(data['images'])} 张")

    # 确定输出目录
    safe_title = safe_filename(title) or "article"
    if date_prefix and use_subfolder:
        d = data.get("date") or datetime.date.today().strftime("%Y-%m-%d")
        folder_name = f"{d}_{safe_title}"
    else:
        folder_name = safe_title
    if use_subfolder:
        article_dir = os.path.join(output_dir, folder_name)
    else:
        article_dir = output_dir
    os.makedirs(article_dir, exist_ok=True)

    # 标记文件:build_index_html 靠它区分本工具保存的文章 vs 其他 HTML 目录
    if use_subfolder:
        try:
            open(os.path.join(article_dir, ".saved-article"), "w").close()
        except Exception:
            pass

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
        html_path = os.path.join(article_dir, f"{folder_name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        output_files.append(html_path)
        log(f"HTML: {html_path}")

    # 生成 Markdown
    if "md" in formats:
        md_img_dir = "images" if keep_images else ""
        md_content = generate_markdown(data, img_files, md_img_dir)
        md_path = os.path.join(article_dir, f"{folder_name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        output_files.append(md_path)
        log(f"Markdown: {md_path}")

    # 生成 PDF(需要先有 HTML)
    if "pdf" in formats:
        # PDF 需要一个含图片(base64 内嵌)的 HTML 源
        html_for_pdf = generate_html(data, img_files, img_dir, embed_images=True)
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                        encoding="utf-8") as tmp:
            tmp.write(html_for_pdf)
            tmp_html = tmp.name
        pdf_path = os.path.join(article_dir, f"{folder_name}.pdf")
        try:
            if generate_pdf(tmp_html, pdf_path):
                output_files.append(pdf_path)
                log(f"PDF: {pdf_path}")
            else:
                log("PDF: 生成失败(Chrome 未产出文件)")
        except Exception as e:
            log(f"PDF: 失败 - {e}")
        finally:
            try:
                os.unlink(tmp_html)
            except Exception:
                pass

    # 如果不保留图片，删除 images 文件夹
    if not keep_images and os.path.isdir(img_dir):
        import shutil
        shutil.rmtree(img_dir, ignore_errors=True)
        log("临时图片已清理")

    return {
        "files": output_files,
        "title": title,
        "author": data.get("author", ""),
        "date": data.get("date", ""),
        "site": data.get("site", ""),
        "images": [f for f in img_files if f] if keep_images else [],
    }


# ==================== Chrome 管理 ====================

def _build_chrome_pdf_cmd(chrome: str, html_path: str, pdf_path: str) -> list:
    """构造 Chrome headless 导出 PDF 的命令行参数。"""
    # URL 编码:避免路径含空格/中文时 Chrome 拒绝
    file_url = "file://" + urllib.parse.quote(html_path, safe="/")
    return [
        chrome, "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        file_url,
    ]


def generate_pdf(html_path: str, pdf_path: str, timeout: int = 60) -> bool:
    """用 Chrome headless 把 HTML 转成 PDF。成功返回 True,失败抛出带错误信息的异常。"""
    try:
        chrome = get_chrome_path()
    except FileNotFoundError:
        raise Exception("PDF 需要 Google Chrome。请先安装 Chrome 后再试。")
    cmd = _build_chrome_pdf_cmd(chrome, html_path, pdf_path)
    result = subprocess.run(cmd, timeout=timeout, capture_output=True)
    # 兜三重检查:退出码 + 文件存在 + 文件非空
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="ignore")[:500]
        raise Exception(f"Chrome PDF 生成失败(退出码 {result.returncode}):{stderr}")
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
        return False
    return True


def make_default_icon_png(size: int = 1024) -> bytes:
    """零依赖构造一个渐变蓝色纯色 PNG(可当默认 App 图标)。"""
    import struct, zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    # IHDR: size×size, 8 bit, RGB(color type 2)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    # 生成像素:从上到下蓝色渐变(顶部浅、底部深)
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter=none per row
        r = 90 + (y * 40 // size)
        g = 130 + (y * 20 // size)
        b = 230 - (y * 60 // size)
        raw.extend(bytes([r, g, b]) * size)
    idat = zlib.compress(bytes(raw))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', idat)
            + chunk(b'IEND', b''))


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
    parser.add_argument("--date-prefix", action="store_true", help="文件夹名前加日期前缀 YYYY-MM-DD_")
    parser.add_argument("--pdf", action="store_true", help="额外生成 PDF(需 Chrome)")
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
    if args.pdf: formats.append("pdf")

    def log(msg):
        print(msg)

    result = save_article(
        args.url, args.output,
        formats=formats,
        use_subfolder=not args.flat,
        log_fn=log,
        date_prefix=args.date_prefix,
    )

    if result.get("error"):
        print(f"\n失败: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"\n完成!")


if __name__ == "__main__":
    main()
