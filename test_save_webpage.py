#!/usr/bin/env python3
"""save_webpage.py 的单元测试

运行: python3 -m unittest test_save_webpage -v
"""

import unittest

from save_webpage import (parse_wechat_html, generate_html, pick_url_from_clipboard,
                          split_urls, format_share_text, build_toc, build_index_html,
                          open_file, scan_saved_articles,
                          detect_site,
                          parse_weibo_html, parse_bili_html,
                          parse_juejin_html, parse_jianshu_html,
                          _build_chrome_pdf_cmd, generate_pdf,
                          make_default_icon_png, make_default_icon_ico,
                          _read_article_extra_stats, build_dashboard_html)


def make_page(content_html: str, title: str = "测试文章") -> str:
    """构造一个最小的公众号页面 HTML。"""
    return f'''<!DOCTYPE html>
<html>
<head><title>{title}</title></head>
<body>
<h1 id="activity-name">{title}</h1>
<div id="js_content">{content_html}</div>
</body>
</html>'''


class TestWechatMixedSection(unittest.TestCase):
    """核心 bug:整篇文章包在一个大 section 里(图文混排)时,文字不能丢。"""

    def setUp(self):
        # 模拟真实排版:一个顶层 section 同时包含文字段落和图片
        html = make_page("""
        <section>
            <p>第一段文字内容</p>
            <p><img data-src="https://mmbiz.qpic.cn/img_a/640?wx_fmt=png"></p>
            <p>第二段文字内容</p>
            <p><img data-src="https://mmbiz.qpic.cn/img_b/640?wx_fmt=png"></p>
            <p>第三段文字内容</p>
        </section>
        """)
        self.data = parse_wechat_html(html)

    def test_text_not_lost(self):
        """图文混排的盒子里,文字必须被提取出来(这是本次修复的 bug)。"""
        md = self.data["markdown"]
        self.assertIn("第一段文字内容", md)
        self.assertIn("第二段文字内容", md)
        self.assertIn("第三段文字内容", md)

    def test_images_extracted(self):
        """图片也要照常提取。"""
        self.assertEqual(len(self.data["images"]), 2)
        self.assertIn("img_a", self.data["images"][0])
        self.assertIn("img_b", self.data["images"][1])

    def test_order_preserved(self):
        """文字和图片按原文顺序交错排列。"""
        md = self.data["markdown"]
        pos_t1 = md.index("第一段文字内容")
        pos_i1 = md.index("img_a")
        pos_t2 = md.index("第二段文字内容")
        pos_i2 = md.index("img_b")
        pos_t3 = md.index("第三段文字内容")
        self.assertTrue(pos_t1 < pos_i1 < pos_t2 < pos_i2 < pos_t3)


class TestWechatFlatLayout(unittest.TestCase):
    """回归测试:原来能正常处理的'一段一个盒子'排版,修完不能坏。"""

    def setUp(self):
        html = make_page("""
        <p>甲段落</p>
        <p><img data-src="https://mmbiz.qpic.cn/img_c/640?wx_fmt=jpeg"></p>
        <section>乙段落</section>
        """)
        self.data = parse_wechat_html(html)

    def test_text_extracted(self):
        md = self.data["markdown"]
        self.assertIn("甲段落", md)
        self.assertIn("乙段落", md)

    def test_image_extracted(self):
        self.assertEqual(len(self.data["images"]), 1)
        self.assertIn("img_c", self.data["images"][0])


class TestWechatEdgeCases(unittest.TestCase):
    """边界情况。"""

    def test_title_extracted(self):
        data = parse_wechat_html(make_page("<p>正文</p>", title="我的标题"))
        self.assertEqual(data["title"], "我的标题")

    def test_non_mmbiz_images_ignored(self):
        """非公众号域名的图片(广告等)不收录。"""
        html = make_page("""
        <section>
            <p>正文文字</p>
            <p><img data-src="https://evil-ads.com/banner.png"></p>
        </section>
        """)
        data = parse_wechat_html(html)
        self.assertEqual(data["images"], [])
        self.assertIn("正文文字", data["markdown"])

    def test_deeply_nested_mixed(self):
        """多层嵌套的图文混排也不能丢文字。"""
        html = make_page("""
        <section>
            <section>
                <p>深层文字</p>
                <section><img data-src="https://mmbiz.qpic.cn/img_d/640"></section>
            </section>
        </section>
        """)
        data = parse_wechat_html(html)
        self.assertIn("深层文字", data["markdown"])
        self.assertEqual(len(data["images"]), 1)

    def test_fallback_without_js_content(self):
        """页面没有 js_content 容器时走 trafilatura 兜底,且接受 url 参数。"""
        html = '''<!DOCTYPE html><html>
        <head><title>兜底标题</title></head>
        <body><article><h1>兜底标题</h1><p>这是一段足够长的正文内容,用来让提取器有东西可提取。</p></article></body>
        </html>'''
        data = parse_wechat_html(html, url="https://mp.weixin.qq.com/s/test")
        self.assertEqual(data["title"], "兜底标题")

    def test_bare_text_in_section(self):
        """文字直接裸露在 section 里(没有 p 包裹)也要提取。"""
        html = make_page("""
        <section>
            裸露的文字
            <img data-src="https://mmbiz.qpic.cn/img_e/640">
        </section>
        """)
        data = parse_wechat_html(html)
        self.assertIn("裸露的文字", data["markdown"])
        self.assertEqual(len(data["images"]), 1)


class TestWechatHeadings(unittest.TestCase):
    """标题层级保留(设计文档 §1)。"""

    def test_h2_gets_markdown_prefix(self):
        """<h2> 输出为 '## 标题' 而非普通文本。"""
        data = parse_wechat_html(make_page("<h2>一、真正的问题</h2><p>正文</p>"))
        self.assertIn("## 一、真正的问题", data["markdown"])

    def test_heading_levels_mapped(self):
        """h1→#,h3→###,h5 封顶为 ####。"""
        data = parse_wechat_html(make_page(
            "<h1>大标题</h1><h3>三级</h3><h5>五级</h5>"))
        md = data["markdown"]
        self.assertIn("# 大标题", md)
        self.assertIn("### 三级", md)
        self.assertIn("#### 五级", md)
        self.assertNotIn("##### ", md)

    def test_heading_nested_in_boxes(self):
        """标题藏在无图嵌套盒子深处,也要保留层级(旧逻辑会被 get_text 拍平)。"""
        data = parse_wechat_html(make_page(
            "<section><section><h2>深层标题</h2><p>段落</p></section></section>"))
        self.assertIn("## 深层标题", data["markdown"])

    def test_heading_alongside_images(self):
        """图文混排的盒子里,标题和图片都按顺序保留。"""
        data = parse_wechat_html(make_page("""
        <section>
            <h2>章节标题</h2>
            <p><img data-src="https://mmbiz.qpic.cn/img_h/640"></p>
            <p>正文段落</p>
        </section>
        """))
        md = data["markdown"]
        self.assertIn("## 章节标题", md)
        self.assertEqual(len(data["images"]), 1)
        self.assertTrue(md.index("## 章节标题") < md.index("img_h") < md.index("正文段落"))


class TestWechatLists(unittest.TestCase):
    """列表保留(设计文档 §1)。"""

    def test_unordered_list(self):
        data = parse_wechat_html(make_page("<ul><li>甲条目</li><li>乙条目</li></ul>"))
        md = data["markdown"]
        self.assertIn("- 甲条目", md)
        self.assertIn("- 乙条目", md)

    def test_ordered_list(self):
        data = parse_wechat_html(make_page("<ol><li>第一步</li><li>第二步</li></ol>"))
        md = data["markdown"]
        self.assertIn("1. 第一步", md)
        self.assertIn("2. 第二步", md)

    def test_list_containing_image_keeps_image(self):
        """列表里夹图片时,图片不能丢(不丢图优先于保结构)。"""
        data = parse_wechat_html(make_page(
            '<ul><li>带图条目<img data-src="https://mmbiz.qpic.cn/img_l/640"></li></ul>'))
        self.assertEqual(len(data["images"]), 1)
        self.assertIn("带图条目", data["markdown"])


class TestWechatBlockquote(unittest.TestCase):
    """引用块保留(设计文档 §1)。"""

    def test_blockquote_prefix(self):
        data = parse_wechat_html(make_page("<blockquote>他山之石可以攻玉</blockquote>"))
        self.assertIn("> 他山之石可以攻玉", data["markdown"])


class TestWechatBold(unittest.TestCase):
    """行内加粗保留(设计文档 §1)。"""

    def test_strong_inline(self):
        data = parse_wechat_html(make_page("<p>前文<strong>重点内容</strong>后文</p>"))
        self.assertIn("**重点内容**", data["markdown"])

    def test_b_tag_inline(self):
        data = parse_wechat_html(make_page("<p>说明<b>加粗词</b>结尾</p>"))
        self.assertIn("**加粗词**", data["markdown"])

    def test_space_preserved_around_bold(self):
        """英文加粗前后的空格不能丢(评审确认项 #1)。"""
        data = parse_wechat_html(make_page("<p>foo <b>bar</b> baz</p>"))
        self.assertIn("foo **bar** baz", data["markdown"])

    def test_nested_bold_not_double_wrapped(self):
        """<strong><b> 嵌套不能产生 ****(评审确认项 #2)。"""
        data = parse_wechat_html(make_page("<p><strong><b>双重加粗</b></strong></p>"))
        self.assertIn("**双重加粗**", data["markdown"])
        self.assertNotIn("****", data["markdown"])


class TestGenerateHtmlStructures(unittest.TestCase):
    """generate_html 对新 Markdown 语法的转换(设计文档 §2)。"""

    def _html_for(self, md: str) -> str:
        data = {"title": "T", "author": "", "markdown": md, "site": "公众号", "images": []}
        return generate_html(data, [], "")

    def test_h4_converted(self):
        html = self._html_for("#### 四级标题")
        # 允许 heading 带 id 属性(TOC 锚点)
        self.assertRegex(html, r'<h4[^>]*>四级标题</h4>')

    def test_unordered_list_converted(self):
        html = self._html_for("- 甲\n- 乙")
        self.assertIn("<li>甲</li>", html)
        self.assertIn("<li>乙</li>", html)
        self.assertIn("<ul>", html)

    def test_ordered_list_converted(self):
        html = self._html_for("1. 第一\n2. 第二")
        self.assertIn("<li>第一</li>", html)
        self.assertIn("<ol>", html)

    def test_blockquote_converted(self):
        html = self._html_for("> 引用的话")
        self.assertIn("<blockquote>", html)
        self.assertIn("引用的话", html)

    def test_block_elements_not_wrapped_in_p(self):
        """块级元素不能包在 <p> 里(评审确认项 #3)。"""
        html = self._html_for("## 标题\n\n正文段落\n\n- 甲\n- 乙")
        self.assertNotIn("<p><h2", html)
        self.assertNotIn("<p><ul>", html)
        self.assertRegex(html, r'<h2[^>]*>标题</h2>')
        self.assertIn("<p>正文段落</p>", html)

    def test_no_stray_br_after_trailing_list(self):
        """文末列表后不能残留多余 <br>(评审确认项 #3)。"""
        html = self._html_for("正文\n\n- 甲\n- 乙")
        self.assertNotIn("</ul><br>", html)


class TestWechatLinks(unittest.TestCase):
    """公众号超链接保留(UX 增强 #1)。"""

    def test_link_preserved(self):
        data = parse_wechat_html(make_page(
            '<p>前文<a href="https://example.com/x">锚文字</a>后文</p>'))
        self.assertIn("[锚文字](https://example.com/x)", data["markdown"])

    def test_link_inside_paragraph_has_spacing(self):
        data = parse_wechat_html(make_page(
            '<p>see <a href="https://a.com">docs</a> for details</p>'))
        self.assertIn("see [docs](https://a.com) for details", data["markdown"])

    def test_anchor_link_ignored(self):
        """页内锚点(#xxx)不当作外链保留,直接输出文字。"""
        data = parse_wechat_html(make_page('<p><a href="#top">回顶部</a></p>'))
        md = data["markdown"]
        self.assertIn("回顶部", md)
        self.assertNotIn("](#top)", md)

    def test_javascript_link_ignored(self):
        data = parse_wechat_html(make_page(
            '<p><a href="javascript:void(0)">按钮</a></p>'))
        self.assertNotIn("javascript:", data["markdown"])


class TestWechatCode(unittest.TestCase):
    """公众号代码块保留(UX 增强 #2)。"""

    def test_pre_block_wrapped_in_fences(self):
        data = parse_wechat_html(make_page(
            "<pre><code>npm install foo\nnpm run build</code></pre>"))
        md = data["markdown"]
        self.assertIn("```", md)
        self.assertIn("npm install foo", md)
        self.assertIn("npm run build", md)

    def test_inline_code_wrapped_in_backticks(self):
        data = parse_wechat_html(make_page(
            "<p>运行 <code>python gui.py</code> 启动</p>"))
        self.assertIn("`python gui.py`", data["markdown"])

    def test_pre_block_html_renders(self):
        data = {"title": "T", "author": "", "site": "", "images": [],
                "markdown": "```\nhello world\n```"}
        html = generate_html(data, [], "")
        self.assertIn("<pre", html)
        self.assertIn("hello world", html)


class TestClipboardPick(unittest.TestCase):
    """剪贴板 URL 识别(UX 增强 #4)。纯函数,不真的读剪贴板。"""

    def test_http_url_picked(self):
        self.assertEqual(pick_url_from_clipboard("https://example.com/a"),
                         "https://example.com/a")

    def test_url_with_whitespace_trimmed(self):
        self.assertEqual(pick_url_from_clipboard("  https://example.com  "),
                         "https://example.com")

    def test_non_url_ignored(self):
        self.assertEqual(pick_url_from_clipboard("hello world"), "")

    def test_empty_ignored(self):
        self.assertEqual(pick_url_from_clipboard(""), "")


class TestSplitUrls(unittest.TestCase):
    """批量 URL 切分(UX 增强 #5)。"""

    def test_single_url(self):
        self.assertEqual(split_urls("https://a.com"), ["https://a.com"])

    def test_multiple_urls_by_newline(self):
        self.assertEqual(
            split_urls("https://a.com\nhttps://b.com\nhttps://c.com"),
            ["https://a.com", "https://b.com", "https://c.com"])

    def test_blank_lines_ignored(self):
        self.assertEqual(
            split_urls("\n\nhttps://a.com\n\n\nhttps://b.com\n"),
            ["https://a.com", "https://b.com"])

    def test_non_url_lines_ignored(self):
        """夹杂的备注文字不当 URL。"""
        self.assertEqual(
            split_urls("我的收藏\nhttps://a.com\nhttps://b.com\n请保存"),
            ["https://a.com", "https://b.com"])

    def test_space_separated_urls_on_one_line(self):
        """同一行用空格分隔的多个 URL 都拆出来(评审确认项)。"""
        self.assertEqual(
            split_urls("https://a.com https://b.com"),
            ["https://a.com", "https://b.com"])


class TestSecurityEscaping(unittest.TestCase):
    """HTML 转义与 XSS 防护(评审确认项)。"""

    def _html_for(self, md: str) -> str:
        data = {"title": "T", "author": "", "markdown": md, "site": "", "images": []}
        return generate_html(data, [], "")

    def test_script_tag_escaped(self):
        """markdown 里的 <script> 输出时必须被转义。"""
        html = self._html_for("讨论 <script>alert(1)</script> 用法")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_javascript_uppercase_href_blocked(self):
        """大写 JavaScript: 也要被过滤,防止 XSS。"""
        from save_webpage import parse_wechat_html
        data = parse_wechat_html(make_page(
            '<p><a href="JavaScript:alert(1)">按钮</a></p>'))
        self.assertNotIn("JavaScript:", data["markdown"])
        self.assertNotIn("javascript:", data["markdown"].lower())

    def test_data_uri_href_blocked(self):
        from save_webpage import parse_wechat_html
        data = parse_wechat_html(make_page(
            '<p><a href="data:text/html,<script>alert(1)</script>">点</a></p>'))
        self.assertNotIn("data:", data["markdown"])


class TestPreInStructure(unittest.TestCase):
    """pre 嵌套在结构容器里也要保留围栏(评审确认项)。"""

    def test_pre_nested_in_section_keeps_fence(self):
        from save_webpage import parse_wechat_html
        data = parse_wechat_html(make_page(
            "<section><pre>npm install foo</pre></section>"))
        self.assertIn("```", data["markdown"])
        self.assertIn("npm install foo", data["markdown"])


class TestInlineCodeWithBacktick(unittest.TestCase):
    """行内 code 内含反引号也不能破坏格式(评审确认项)。"""

    def test_backtick_in_code(self):
        from save_webpage import parse_wechat_html
        data = parse_wechat_html(make_page(
            "<p>命令 <code>echo `date`</code> 用来</p>"))
        # 用双反引号包住含反引号的行内代码
        md = data["markdown"]
        self.assertIn("echo `date`", md)
        # HTML 转换后不应该有裂开的空 <code>
        html = generate_html(
            {"title": "T", "author": "", "markdown": md, "site": "", "images": []},
            [], "")
        # 不能出现空的 <code></code>
        self.assertNotIn("<code></code>", html)


class TestMetadata(unittest.TestCase):
    """公众号元数据抽取(内容质量 #1)。"""

    def test_publish_date_from_ct(self):
        """从 var ct = "时间戳" 抽取发布日期。"""
        html = f'''<!DOCTYPE html><html><head><title>T</title></head><body>
<h1 id="activity-name">T</h1>
<div id="js_content"><p>正文</p></div>
<script>var ct = "1782462134";</script>
</body></html>'''
        data = parse_wechat_html(html)
        # 1782462134 = 2026-06-25 (UTC+8),允许 25/26 都算过
        self.assertRegex(data.get("date", ""), r"^2026-06-2[456]$")

    def test_no_date_when_missing(self):
        data = parse_wechat_html(make_page("<p>正文</p>"))
        self.assertEqual(data.get("date", ""), "")


class TestTables(unittest.TestCase):
    """表格保留(内容质量 #2)。"""

    def test_simple_table_to_markdown(self):
        data = parse_wechat_html(make_page(
            "<table><tr><th>姓名</th><th>年龄</th></tr>"
            "<tr><td>张三</td><td>25</td></tr>"
            "<tr><td>李四</td><td>30</td></tr></table>"))
        md = data["markdown"]
        self.assertIn("| 姓名 | 年龄 |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("| 张三 | 25 |", md)
        self.assertIn("| 李四 | 30 |", md)

    def test_table_first_row_as_header_when_no_th(self):
        data = parse_wechat_html(make_page(
            "<table><tr><td>甲</td><td>乙</td></tr>"
            "<tr><td>丙</td><td>丁</td></tr></table>"))
        md = data["markdown"]
        self.assertIn("| 甲 | 乙 |", md)
        self.assertIn("| --- | --- |", md)
        self.assertIn("| 丙 | 丁 |", md)

    def test_table_html_rendering(self):
        html = generate_html(
            {"title": "T", "author": "", "site": "", "images": [],
             "markdown": "| a | b |\n| --- | --- |\n| c | d |"},
            [], "")
        self.assertIn("<table>", html)
        self.assertIn("<th>a</th>", html)
        self.assertIn("<td>c</td>", html)


class TestImageRetry(unittest.TestCase):
    """图片下载失败重试(内容质量 #3)。"""

    def test_retries_on_network_error(self):
        """前 2 次失败,第 3 次成功。"""
        import tempfile
        from unittest.mock import patch
        import requests as req
        from save_webpage import download_image

        call_count = [0]

        def fake_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise req.ConnectionError("模拟网络错误")
            class R:
                content = b"fake image bytes"
                status_code = 200
                def raise_for_status(self): pass
            return R()

        with tempfile.TemporaryDirectory() as tmp:
            with patch("save_webpage.requests.get", side_effect=fake_get), \
                 patch("save_webpage.time.sleep"):  # 加速测试
                result = download_image("https://example.com/x.jpg", tmp, 0)

        self.assertEqual(call_count[0], 3)
        self.assertEqual(result, "img_0.jpg")

    def test_gives_up_after_max_retries(self):
        """连续失败达上限,返回 None。"""
        import tempfile
        from unittest.mock import patch
        import requests as req
        from save_webpage import download_image

        with tempfile.TemporaryDirectory() as tmp:
            with patch("save_webpage.requests.get",
                       side_effect=req.ConnectionError("总是失败")), \
                 patch("save_webpage.time.sleep"):
                result = download_image("https://example.com/x.jpg", tmp, 0)
        self.assertIsNone(result)


class TestFakeHeading(unittest.TestCase):
    """样式冒充的伪标题识别(内容质量 #4)。"""

    def test_bold_short_section_becomes_h3(self):
        """短加粗的 section → 作为三级标题。"""
        data = parse_wechat_html(make_page(
            '<section><strong>章节小标题</strong></section>'
            '<p>正文段落</p>'))
        self.assertIn("### 章节小标题", data["markdown"])

    def test_font_weight_style_becomes_h3(self):
        data = parse_wechat_html(make_page(
            '<section style="font-weight: 700;">另一小标题</section>'
            '<p>正文</p>'))
        self.assertIn("### 另一小标题", data["markdown"])

    def test_long_bold_paragraph_not_treated_as_heading(self):
        """长文本即使加粗也不当标题,避免误判。"""
        long = "这是一段很长的加粗段落," * 5  # >40 字
        data = parse_wechat_html(make_page(f"<section><strong>{long}</strong></section>"))
        md = data["markdown"]
        self.assertNotIn(f"### {long}", md)
        self.assertIn(long, md)  # 但内容要保留


class TestEmphasisStrikeUnderline(unittest.TestCase):
    """斜体、删除线、下划线保留(内容质量 #5)。"""

    def test_em_becomes_italic(self):
        data = parse_wechat_html(make_page("<p>前<em>斜体文字</em>后</p>"))
        self.assertIn("*斜体文字*", data["markdown"])

    def test_i_tag_also_italic(self):
        data = parse_wechat_html(make_page("<p>前<i>斜体</i>后</p>"))
        self.assertIn("*斜体*", data["markdown"])

    def test_del_becomes_strikethrough(self):
        data = parse_wechat_html(make_page("<p>前<del>删除的字</del>后</p>"))
        self.assertIn("~~删除的字~~", data["markdown"])

    def test_underline_survives_to_html(self):
        """下划线用 <u> 直通,最终 HTML 里保留 <u> 标签。"""
        data = parse_wechat_html(make_page("<p>前<u>下划线</u>后</p>"))
        html = generate_html(data, [], "")
        self.assertIn("<u>下划线</u>", html)

    def test_italic_html_conversion(self):
        html = generate_html(
            {"title": "T", "author": "", "site": "", "images": [],
             "markdown": "前 *斜体* 后"}, [], "")
        self.assertIn("<em>斜体</em>", html)

    def test_strike_html_conversion(self):
        html = generate_html(
            {"title": "T", "author": "", "site": "", "images": [],
             "markdown": "前 ~~删除线~~ 后"}, [], "")
        self.assertIn("<del>删除线</del>", html)


class TestBrAndAdjacentEmphasis(unittest.TestCase):
    """<br> 换行保留 + 相邻强调段防撞(2026-07-06 OPD 文章回归)。

    真实故障:论文作者/作者单位/论文出处三行(加粗斜体标签 + 斜体值,
    <br> 分隔)被拼成一行,星号相撞成 ****,markdown 语法碎裂、
    生成的 HTML 里星号字面可见。
    """

    URL = "https://mp.weixin.qq.com/s/x"

    def test_br_separates_inline_runs_opd_regression(self):
        """六段交替强调 + 两个 <br>:用 <br> 分行,星号不相撞(字节级)。

        换行标记用字面 <br> 而非物理换行:物理换行会让 # / - / 2. 开头的
        段内行被块级正则误判成标题/列表(评审确认的真实回归)。
        """
        html = make_page(
            '<p><strong><em>论文作者：</em></strong><em>Mingyang Song &amp;MaoZheng</em><br/>'
            '<strong><em>作者单位：</em></strong><em>Large Language Model Department，Tencent</em><br/>'
            '<strong><em>论文出处：</em></strong><em>arXiv:2604.00626 [cs.LG] 18 May 2026</em></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        expected = ("***论文作者：*** *Mingyang Song &MaoZheng*<br>"
                    "***作者单位：*** *Large Language Model Department，Tencent*<br>"
                    "***论文出处：*** *arXiv:2604.00626 [cs.LG] 18 May 2026*")
        self.assertEqual(md, expected)

    def test_bold_label_with_plain_value_gets_space(self):
        """同族缺口:值不带斜体时,***标签：***紧跟字母在 CommonMark 里
        无法闭合(闭合星号前是标点、后是字词)→ 必须补空格。"""
        html = make_page(
            '<p><strong><em>论文作者：</em></strong>Mingyang Song<br/>'
            '<strong><em>作者单位：</em></strong>Tencent</p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "***论文作者：*** Mingyang Song<br>***作者单位：*** Tencent")

    def test_emphasis_starting_with_punctuation_after_word(self):
        """镜像缺口:字词后紧跟以标点开头的斜体(如括号注释)同样无法开启。"""
        html = make_page("<p>见<em>（注释）</em>说明</p>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "见 *（注释）* 说明")

    def test_fragmented_em_inside_strong_merges(self):
        """微信编辑器把一个词拆成多个 <em>:加粗内全斜体片段合并成一个 ***…***。"""
        html = make_page("<p><strong><em>论文</em><em>作者</em></strong></p>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "***论文 作者***")

    def test_literal_stars_in_text_not_mutated(self):
        """防撞守卫不能碰原文内容:跨 span 断开的字面星号(2**32)不插空格。"""
        html = make_page("<p>2*<span>*32</span></p>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "2**32")

    def test_adjacent_bold_then_italic_gets_space(self):
        """相邻 <strong> 和 <em>(无 br):中间补一个空格防星号相撞。"""
        html = make_page("<p><strong>标签：</strong><em>取值</em></p>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "**标签：** *取值*")

    def test_br_inside_list_item_becomes_space(self):
        """列表项里的 <br> 降级为空格,列表结构不被撑破。"""
        html = make_page("<ul><li>第一行<br/>第二行</li><li>另一项</li></ul>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("- 第一行 第二行", md)
        self.assertIn("- 另一项", md)

    def test_br_inside_table_cell_becomes_space(self):
        """表格单元格里的 <br> 降级为空格,表格行保持单行。"""
        html = make_page(
            "<table><tr><th>列A</th><th>列B</th></tr>"
            "<tr><td>上半<br/>下半</td><td>x</td></tr></table>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("| 上半 下半 | x |", md)

    def test_br_inside_blockquote_keeps_lines(self):
        """引用块里的 <br>:保留为 <br> 硬换行,引用前缀完好。"""
        html = make_page("<blockquote>上一句<br/>下一句</blockquote>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("> 上一句<br>下一句", md)

    def test_generate_html_renders_bold_italic_and_hard_break(self):
        """***加粗斜体*** 渲染为 <strong><em>,<br> 标记直通为换行。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "***标签：*** *取值*<br>***标签二：*** *取值二*"
        html = generate_html(data, [], "")
        self.assertIn("<strong><em>标签：</em></strong>", html)
        self.assertIn("<em>取值</em>", html)
        self.assertIn("<br>", html)
        self.assertNotIn("***", html)
        self.assertNotIn("&lt;br&gt;", html)

    def test_br_line_not_promoted_to_block(self):
        """<br> 后以 # / 2. / - / > 开头的内容不得被误判成标题/列表/引用。

        评审确认的回归场景:'2026. 6. 25' 曾被列表正则重编号成 '1. 6. 25'。
        """
        html = make_page(
            "<p>发布时间<br/>2026. 6. 25 更新<br/># 这是注释<br/>- 不是列表项</p>")
        data = parse_wechat_html(html, self.URL)
        out = generate_html(data, [], "")
        body = out[out.index('<div class="content">'):]
        self.assertIn("2026. 6. 25 更新", body)
        self.assertNotIn("<ol>", body)
        self.assertNotIn("<ul>", body)
        self.assertNotIn("<h1># 这是注释</h1>", body)
        self.assertNotIn("<h1>这是注释</h1>", body)

    def test_unbalanced_bold_italic_not_scrambled(self):
        """两段「加粗内含斜体结尾」不平衡星号串不得被 *** 规则跨段错配。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "**a *b*** 中 **c *d***"
        html = generate_html(data, [], "")
        self.assertIn("中", html)
        self.assertNotIn("*b", html)
        self.assertNotIn("*d", html)

    def test_inline_code_protected_from_emphasis(self):
        """行内代码里的星号是字面内容,不得被加粗/斜体正则改写成标签。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "运行 `x***y***z` 即可"
        html = generate_html(data, [], "")
        self.assertIn("<code>x***y***z</code>", html)

    def test_code_with_newline_in_table_cell_stays_one_line(self):
        """<code> 内换行在表格单元格里折叠为空格,表格行不被撑破。"""
        html = make_page(
            "<table><tr><th>列</th></tr>"
            "<tr><td><code>x\ny</code></td></tr></table>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("| `x y` |", md)

    def test_end_to_end_no_literal_stars_in_html(self):
        """端到端:真实坏样本结构 → 生成 HTML 里不残留字面星号。"""
        html_in = make_page(
            '<p><strong><em>论文作者：</em></strong><em>Mingyang</em><br/>'
            '<strong><em>作者单位：</em></strong><em>Tencent</em></p>')
        data = parse_wechat_html(html_in, self.URL)
        html_out = generate_html(data, [], "")
        self.assertIn("<strong><em>论文作者：</em></strong>", html_out)
        self.assertIn("<em>Mingyang</em>", html_out)
        self.assertNotIn("***", html_out)
        self.assertNotIn("****", data["markdown"])


class TestPreLineStructure(unittest.TestCase):
    """<pre> 代码块的微信新版编辑器结构(2026-07-16 vLLM 文章回归)。

    真实故障:新版编辑器(带 md-src-pos)把换行渲染成 <br> 元素、
    缩进用 &nbsp;,相邻高亮词之间的空格甚至不在 DOM 文本里(只在
    md-src-pos 编号间隙里)。get_text() 提取导致:ASCII 架构图压成
    一行、async def 粘成 asyncdef。
    """

    URL = "https://mp.weixin.qq.com/s/x"

    def test_pre_br_elements_become_newlines(self):
        """<br> 元素 = 代码换行:ASCII 图的三行必须还原成三行。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="10..20"><span leaf="">┌────┐</span></span>'
            '<span md-src-pos="20..21"><span leaf=""><br/></span></span>'
            '<span md-src-pos="21..31"><span leaf="">│ 标题 │</span></span>'
            '<span md-src-pos="31..32"><span leaf=""><br/></span></span>'
            '<span md-src-pos="32..42"><span leaf="">└────┘</span></span>'
            '</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("┌────┐\n│ 标题 │\n└────┘", md)

    def test_pre_md_src_pos_gap_restores_swallowed_space(self):
        """相邻高亮词的空格被微信吞掉,从 md-src-pos 编号间隙还原。

        实测结构:async 占 7970..7975,def 占 7976..7979,
        间隙 7975→7976 正是被吞的那个空格。
        """
        html = make_page(
            '<pre><code md-src-pos="7922..8504">'
            '<span md-src-pos="7970..7975"><span leaf="">async</span></span>'
            '<span md-src-pos="7976..7979"><span leaf="">def</span></span>'
            '<span md-src-pos="7979..8026"><span leaf="">&nbsp;_create_completion(self):</span></span>'
            '</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("async def _create_completion(self):", md)

    def test_pre_nbsp_becomes_regular_space(self):
        """代码里的 &nbsp; 缩进转成普通空格(复制代码才能直接运行)。"""
        html = make_page(
            '<pre><code><span leaf="">if x:</span>'
            '<span leaf=""><br/></span>'
            '<span leaf="">&nbsp;&nbsp;&nbsp;&nbsp;return 1</span></code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("if x:\n    return 1", md)
        self.assertNotIn("\xa0", md)

    def test_pre_classic_plain_text_unchanged(self):
        """老编辑器的纯文本代码块(真实换行)原样直通——回归保护。"""
        html = make_page("<pre><code>def foo():\n    return 1</code></pre>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("def foo():\n    return 1", md)

    def test_bare_text_between_positioned_spans_no_phantom_space(self):
        """带位置 span 之间夹着真实文本时,不得再按编号间隙注入幻影空格。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="100..105"><span leaf="">async</span></span>'
            ' = '
            '<span md-src-pos="108..111"><span leaf="">foo</span></span>'
            '</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("async = foo", md)

    def test_bare_br_between_positioned_spans_no_phantom_indent(self):
        """裸 <br>(不带位置包装)之后不得注入幻影行首空格。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="10..15"><span leaf="">line1</span></span>'
            '<br/>'
            '<span md-src-pos="16..21"><span leaf="">line2</span></span>'
            '</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("line1\nline2", md)

    def test_nested_positioned_span_no_double_gap(self):
        """带位置元素嵌套带位置元素:间隙只按外层填一次。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="90..98"><span leaf="">prevtok!</span></span>'
            '<span md-src-pos="100..200">'
            '<span md-src-pos="100..105"><span leaf="">child</span></span>'
            '</span></code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("prevtok!  child", md)
        self.assertNotIn("prevtok!    child", md)

    def test_reversed_md_src_pos_ignored(self):
        """反向区间(200..100)是脏数据,不得成为间隙基准。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="200..100"><span leaf="">bad</span></span>'
            '<span md-src-pos="105..108"><span leaf="">tok</span></span>'
            '</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("badtok", md)

    def test_consecutive_br_spans_keep_blank_line(self):
        """连续两个 <br> 行 = 代码空行,原样保留(回归保险)。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="10..15"><span leaf="">line1</span></span>'
            '<span md-src-pos="15..16"><span leaf=""><br/></span></span>'
            '<span md-src-pos="16..17"><span leaf=""><br/></span></span>'
            '<span md-src-pos="17..22"><span leaf="">line2</span></span>'
            '</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("line1\n\nline2", md)

    def test_classic_code_snippet_each_code_is_a_line(self):
        """老版代码片段控件:每行一个 <code> 兄弟、行间零文本 → 按行还原。

        实测结构(2026-07-16,Loop Engineering 文章):
        <pre class="code-snippet__js"><code>1. …</code><code>2. …</code>…</pre>
        """
        html = make_page(
            '<pre class="code-snippet__js">'
            '<code>1.&nbsp;启动本地服务，用浏览器工具打开页面</code>'
            '<code>2.&nbsp;真实操作改动的控件</code>'
            '<code>3.&nbsp;刷新页面确认状态保留</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("1. 启动本地服务，用浏览器工具打开页面\n"
                      "2. 真实操作改动的控件\n"
                      "3. 刷新页面确认状态保留", md)

    def test_code_boundary_always_invalidates_gap_baseline(self):
        """code 边界无条件作废 md-src-pos 间隙基准:
        即使上一行已带换行,编号间隙也不得跨边界折算成幻影缩进。"""
        html = make_page(
            '<pre><code md-src-pos="10..20">line1\n</code>'
            '<code md-src-pos="25..35">line2</code></pre>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("line1\nline2", md)

    def test_code_siblings_with_whitespace_between_no_double_newline(self):
        """相邻 code 之间已有换行文本时不叠加换行(不出双空行)。"""
        html = make_page("<pre><code>a</code>\n<code>b</code></pre>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("a\nb", md)
        self.assertNotIn("a\n\nb", md)

    def test_pre_lines_survive_into_generated_html(self):
        """端到端:新版结构的代码块在生成的 HTML <pre> 里保持多行。"""
        html = make_page(
            '<pre><code>'
            '<span md-src-pos="10..20"><span leaf="">┌────┐</span></span>'
            '<span md-src-pos="20..21"><span leaf=""><br/></span></span>'
            '<span md-src-pos="21..31"><span leaf="">│ 标题 │</span></span>'
            '</code></pre>')
        data = parse_wechat_html(html, self.URL)
        out = generate_html(data, [], "")
        self.assertIn("┌────┐\n│ 标题 │", out)


class TestColorHighlight(unittest.TestCase):
    """颜色与高亮保真(2026-07-16 设计):只留刻意强调,滤掉排版噪音。

    判定规则:RGB 三通道差 ≥ 24 = 彩色(作者刻意)保留并规范化为 #hex;
    黑白灰/透明/关键字 = 噪音丢弃。高亮底→<mark>,彩字→<span>,写进 md。
    """

    URL = "https://mp.weixin.qq.com/s/x"

    # ---------- _keep_color 过滤器 ----------

    def test_keep_color_chromatic_kept_and_normalized(self):
        from save_webpage import _keep_color
        self.assertEqual(_keep_color("color: rgb(235, 87, 87);"),
                         {"color": "#eb5757"})
        self.assertEqual(_keep_color("background-color: rgb(253, 236, 200);"),
                         {"background-color": "#fdecc8"})

    def test_keep_color_grayscale_dropped(self):
        from save_webpage import _keep_color
        self.assertIsNone(_keep_color("color: rgb(55, 53, 47);"))
        self.assertIsNone(_keep_color("background-color: rgb(255,255,255);"))
        self.assertIsNone(_keep_color("color: #333;"))

    def test_keep_color_keywords_and_translucent_dropped(self):
        from save_webpage import _keep_color
        self.assertIsNone(_keep_color("background: none transparent !important;"))
        self.assertIsNone(_keep_color("background-color: rgba(135,131,120,0.15);"))
        self.assertIsNone(_keep_color("color: inherit;"))
        self.assertIsNone(_keep_color(""))
        self.assertIsNone(_keep_color(None))

    def test_keep_color_background_shorthand_and_hex_forms(self):
        from save_webpage import _keep_color
        self.assertEqual(_keep_color("background: rgb(253,236,200) left top;"),
                         {"background-color": "#fdecc8"})
        self.assertEqual(_keep_color("color: #EB5757;"), {"color": "#eb5757"})
        self.assertEqual(_keep_color("color: #e57;"), {"color": "#ee5577"})

    # ---------- 输出形态 ----------

    def test_highlight_span_becomes_mark(self):
        html = make_page(
            '<p><span style="background-color: rgb(253, 236, 200);">重点句</span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, '<mark style="background-color:#fdecc8">重点句</mark>')

    def test_colored_strong_wraps_outside_emphasis(self):
        html = make_page(
            '<p><strong style="color: rgb(235, 87, 87);">红色重点</strong></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, '<span style="color:#eb5757">**红色重点**</span>')

    def test_default_near_black_produces_no_tags(self):
        html = make_page('<p><span style="color: rgb(55, 53, 47);">普通文字</span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "普通文字")

    def test_colored_inline_code_keeps_color(self):
        html = make_page(
            '<p><code style="color: rgb(235, 87, 87);">grilling</code></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, '<span style="color:#eb5757">`grilling`</span>')

    def test_nested_same_color_not_doubled(self):
        html = make_page(
            '<p><span style="color: rgb(235,87,87);">'
            '<span style="color: rgb(235,87,87);">红</span></span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md.count("<span"), 1)

    def test_highlight_plus_text_color_merge_into_one_mark(self):
        html = make_page(
            '<p><span style="background-color: rgb(253,236,200); '
            'color: rgb(235,87,87);">双色</span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(
            md, '<mark style="background-color:#fdecc8;color:#eb5757">双色</mark>')

    # ---------- 渲染 ----------

    def test_generate_html_passes_mark_and_span_through(self):
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = ('<mark style="background-color:#fdecc8">重点</mark> 与 '
                            '<span style="color:#eb5757">**红字**</span>')
        html = generate_html(data, [], "")
        self.assertIn('<mark style="background-color:#fdecc8">重点</mark>', html)
        self.assertIn('<span style="color:#eb5757"><strong>红字</strong></span>', html)
        self.assertIn(".content mark", html)

    def test_malformed_rgba_does_not_crash(self):
        """畸形透明度值(1.2.3 / .)静默丢弃,绝不让整篇保存崩溃。"""
        from save_webpage import _keep_color
        self.assertIsNone(_keep_color("color: rgba(235,87,87,1.2.3);"))
        self.assertIsNone(_keep_color("color: rgba(235,87,87,.);"))

    def test_whitespace_only_colored_span_keeps_word_gap(self):
        """纯空白的彩色 span 不能被吞掉——英文词间距必须保住。"""
        html = make_page(
            '<p>left<span style="color: rgb(235,87,87);"> </span>right</p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "left right")

    def test_dark_background_not_marked(self):
        """浅色门槛:深色背景(徽章类)不算荧光笔,降级为无样式。"""
        from save_webpage import _keep_color
        self.assertIsNone(_keep_color("background-color: rgb(200,40,40);"))
        self.assertEqual(_keep_color("background-color: rgb(253,236,200);"),
                         {"background-color": "#fdecc8"})

    def test_nearest_ancestor_color_semantics(self):
        """就近祖先去重:红→蓝→红,最内层的红要重新生效。"""
        html = make_page(
            '<p><span style="color: rgb(235,87,87);">红'
            '<span style="color: rgb(60,120,216);">蓝'
            '<span style="color: rgb(235,87,87);">又红</span></span></span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn('<span style="color:#eb5757">又红</span>', md)

    def test_uppercase_rgb_kept_and_url_hex_ignored(self):
        from save_webpage import _keep_color
        self.assertEqual(_keep_color("color: RGB(235,87,87);"), {"color": "#eb5757"})
        self.assertIsNone(_keep_color("background: url(icons.svg#a1b2c3);"))

    def test_later_declaration_overrides_earlier(self):
        """CSS 语义:同属性后声明覆盖前声明(白色覆盖黄底 → 无高亮)。"""
        from save_webpage import _keep_color
        self.assertIsNone(
            _keep_color("background: rgb(253,236,200); background: white;"))

    def test_colored_span_next_to_emphasis_guards_intact(self):
        """色标签与星号防撞守卫共存:边界是 <>,不触发补空格。"""
        html = make_page(
            '<p><strong>加粗</strong><span style="color: rgb(235,87,87);">红</span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, '**加粗**<span style="color:#eb5757">红</span>')

    def test_nested_different_colors_compose(self):
        html = make_page(
            '<p><span style="background-color: rgb(253,236,200);">黄底'
            '<span style="color: rgb(235,87,87);">红字</span></span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, '<mark style="background-color:#fdecc8">黄底'
                             '<span style="color:#eb5757">红字</span></mark>')

    def test_dark_mode_mark_rule_present(self):
        """亮色与暗色主题各有一条 .content mark 深字规则。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "x"
        html = generate_html(data, [], "")
        self.assertEqual(html.count(".content mark"), 2)

    def test_paired_dark_bg_with_light_text_kept(self):
        """成对配色:深蓝底+白字(话题标签药丸)成对保留,不受浅色门槛限制。"""
        from save_webpage import _keep_color
        self.assertEqual(
            _keep_color("padding: 2px 8px;background: rgb(26, 115, 232);"
                        "color: rgb(255, 255, 255);border-radius: 10px;"),
            {"background-color": "#1a73e8", "color": "#ffffff"})

    def test_low_contrast_pair_falls_back_to_single_rules(self):
        """对比不足(亮度差<90)不成对:背景走浅色门槛被滤,彩字单独保留。"""
        from save_webpage import _keep_color
        self.assertEqual(
            _keep_color("background-color: rgb(120,150,255); color: rgb(140,160,240);"),
            {"color": "#8ca0f0"})

    def test_white_text_alone_still_dropped(self):
        """白字单独出现(没配背景)仍是噪音,过滤。"""
        from save_webpage import _keep_color
        self.assertIsNone(_keep_color("color: rgb(255,255,255);"))

    def test_adjacent_pills_get_space(self):
        """相邻药丸 mark 之间补一个空格,不再粘连。"""
        html = make_page(
            '<p><span style="background: rgb(26,115,232);color: rgb(255,255,255);">'
            'AI Coding</span>'
            '<span style="background: rgb(26,115,232);color: rgb(255,255,255);">'
            '工作流选型</span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(
            md,
            '<mark style="background-color:#1a73e8;color:#ffffff">AI Coding</mark> '
            '<mark style="background-color:#1a73e8;color:#ffffff">工作流选型</mark>')

    def test_nested_pill_inner_bg_restates_paired_text_color(self):
        """嵌套药丸:内层不同底色时,被去重的白字必须重申——
        绝不产出「只有深底没有字色」的不可读 mark。"""
        html = make_page(
            '<p><span style="background: rgb(26,115,232);color: rgb(255,255,255);">外'
            '<span style="background: rgb(200,0,80);color: rgb(255,255,255);">内</span>'
            '</span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn(
            '<mark style="background-color:#c80050;color:#ffffff">内</mark>', md)

    def test_pair_requires_intentional_text_color(self):
        """成对规则只认「刻意的」文字色(彩色或浅色);
        黄底 + 编辑器默认近黑字 → 只留黄底,不复活噪音字色。"""
        from save_webpage import _keep_color
        self.assertEqual(
            _keep_color("background-color: rgb(253,236,200); color: rgb(55,53,47);"),
            {"background-color": "#fdecc8"})

    def test_identical_nested_pill_still_deduped(self):
        """完全同色的嵌套药丸仍只包一层(回归保险)。"""
        html = make_page(
            '<p><span style="background: rgb(26,115,232);color: rgb(255,255,255);">'
            '<span style="background: rgb(26,115,232);color: rgb(255,255,255);">'
            '标签</span></span></p>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md.count("<mark"), 1)

    def test_literal_mark_text_does_not_trigger_gap(self):
        """正文里字面出现的 </mark><mark 是原文内容(非语法段),规则④不补空格。"""
        html = make_page("<p>a&lt;/mark&gt;&lt;mark b</p>")
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertEqual(md, "a</mark><mark b")

    def test_heading_intentional_color_kept(self):
        """标题自带彩色(如 #773098 紫)→ 标题文字包色标签。"""
        html = make_page('<h2 style="color: #773098;">第一阶段</h2>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn('## <span style="color:#773098">第一阶段</span>', md)

    def test_heading_default_color_stays_plain(self):
        """标题是默认黑灰色 → 照旧素面,不包标签。"""
        html = make_page('<h3 style="color: rgb(51,51,51);">普通标题</h3>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn("### 普通标题", md)
        self.assertNotIn("普通标题</span>", md)

    def test_heading_color_renders_and_toc_stays_plain(self):
        """端到端:标题颜色进正文 <h2>,浮动目录条目保持纯文字。"""
        data = parse_wechat_html(
            make_page('<h2 style="color: #773098;">第一阶段</h2><p>正文</p>'),
            self.URL)
        out = generate_html(data, [], "")
        self.assertIn('<span style="color:#773098">第一阶段</span>', out)
        nav = out[out.find("<nav"):out.find("</nav>") + 6]
        self.assertIn("第一阶段", nav)
        self.assertNotIn("<span style", nav)

    def test_heading_color_on_whole_text_inner_wrapper(self):
        """颜色藏在包住整个标题文字的内层元素(如 h4 里的 strong)也要接住。

        真实病例:示例文章 8 个 h4 自身素面,紫色在内层 strong 上。
        """
        html = make_page(
            '<h4><strong style="color: #773098;">训练期的工作流</strong></h4>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn('#### <span style="color:#773098">训练期的工作流</span>', md)

    def test_heading_interior_newline_normalized(self):
        """标题内部换行折叠为空格:不被块切分产生跨块的不闭合标签。"""
        html = make_page('<h2 style="color: #773098;">第一行\n第二行</h2>')
        md = parse_wechat_html(html, self.URL)["markdown"]
        self.assertIn('## <span style="color:#773098">第一行 第二行</span>', md)

    def test_heading_with_light_background_renders_mark(self):
        """标题带浅色高亮底:mark 形态穿过标题正则进 <h2>(回归保险)。"""
        data = parse_wechat_html(
            make_page('<h2 style="background-color: rgb(253,236,200);">高亮标题</h2>'),
            self.URL)
        out = generate_html(data, [], "")
        self.assertIn('<mark style="background-color:#fdecc8">高亮标题</mark>', out)

    def test_end_to_end_highlight_and_colored_code(self):
        html_in = make_page(
            '<p><span style="background-color: rgb(253, 236, 200);">'
            '<strong>grill-me 本身只是个门面</strong></span>'
            ',真正的机关藏在 <code style="color: rgb(235,87,87);">grilling</code> 里</p>')
        data = parse_wechat_html(html_in, self.URL)
        out = generate_html(data, [], "")
        self.assertIn('<mark style="background-color:#fdecc8">'
                      '<strong>grill-me 本身只是个门面</strong></mark>', out)
        self.assertIn('<span style="color:#eb5757"><code>grilling</code></span>', out)


class TestParserRobustness(unittest.TestCase):
    """建树健壮性(2026-07-18 GLM 文章正文全丢回归)。

    真实故障:微信页面模板(小说卡片组件)里一个裸 <img> 把标准库
    html.parser 的建树带偏,整篇正文(25 万字节)被塞进正文区某个
    img 元素的肚子——行走器把 img 当叶子,输出只剩 1 张图。
    修复双层:①建树优先 lxml(浏览器级容错);②img 肚里有内容时
    照样递归(纵深防御,任何解析器再犯错也不丢正文)。
    """

    URL = "https://mp.weixin.qq.com/s/x"

    # 最小病根夹具:裸 <img>(页面模板)+ 正常正文,html.parser 必现
    SICK = ('<html><head><title>t</title></head><body>'
            '<h1 id="activity-name">t</h1>'
            '<div class="novel-cover"><img>\n</div>'
            '<div id="js_content"><section>'
            '<img src="https://mmbiz.qpic.cn/a/640"/>'
            '<p>正文文字甲</p><h2>小节</h2><p>正文文字乙</p>'
            '</section></div></body></html>')

    def test_bare_img_chrome_does_not_swallow_body(self):
        """端到端:病根夹具下正文和图片都必须完整提取。"""
        data = parse_wechat_html(self.SICK, self.URL)
        self.assertIn("正文文字甲", data["markdown"])
        self.assertIn("## 小节", data["markdown"])
        self.assertIn("正文文字乙", data["markdown"])
        self.assertEqual(len(data["images"]), 1)

    def test_walker_recovers_content_swallowed_into_img(self):
        """纵深防御:就算树建错了(img 肚里有内容),行走器也要递归救回。"""
        from bs4 import BeautifulSoup
        import save_webpage as sw
        soup = BeautifulSoup(self.SICK, "html.parser")
        content = soup.find("div", id="js_content")
        if not any(im.find() is not None for im in content.find_all("img")):
            self.skipTest("此环境的 html.parser 未复现病态树")
        md_parts, imgs = [], []
        sw._collect_wechat_content(content, md_parts, imgs)
        joined = "\n\n".join(md_parts)
        self.assertIn("正文文字甲", joined)
        self.assertIn("正文文字乙", joined)
        self.assertEqual(len(imgs), 1)


class TestParserRobustnessHardening(unittest.TestCase):
    """建树健壮性打磨(评审跟进):裸文本肚 + 降级链路端到端。"""

    URL = "https://mp.weixin.qq.com/s/x"

    def test_walker_recovers_text_only_belly(self):
        """img 肚里只有裸文本(无任何标签)时同样救回。"""
        from bs4 import BeautifulSoup, NavigableString
        import save_webpage as sw
        soup = BeautifulSoup(
            '<div id="js_content"><img src="https://mmbiz.qpic.cn/a/640"/></div>',
            "html.parser")
        img = soup.find("img")
        img.append(NavigableString("被吞的正文"))
        md_parts, imgs = [], []
        sw._collect_wechat_content(soup.find("div"), md_parts, imgs)
        self.assertIn("被吞的正文", "\n\n".join(md_parts))

    def test_fallback_parser_end_to_end_when_lxml_missing(self):
        """lxml 缺席时:降级 html.parser + 纵深防御端到端救回正文(回归保险)。"""
        from unittest.mock import patch
        import bs4
        real = bs4.BeautifulSoup

        def fake(markup, features=None, **kw):
            if features == "lxml":
                raise bs4.FeatureNotFound("test: lxml blocked")
            return real(markup, features, **kw)

        with patch.object(bs4, "BeautifulSoup", fake):
            data = parse_wechat_html(TestParserRobustness.SICK, self.URL)
        self.assertIn("正文文字甲", data["markdown"])
        self.assertIn("正文文字乙", data["markdown"])
        self.assertEqual(len(data["images"]), 1)


class TestFormula(unittest.TestCase):
    """数学公式保真(2026-07-18 GLM 文章回归:72 个公式全丢)。

    微信公式组件把 LaTeX 源码存在 data-formula 属性里,svg 只是渲染
    结果(纯路径,遍历只漏出 lex/feas 文字残渣)。
    方案:.md 还原 $$块级$$/​$行内$ 标准数学语法;.html 按 LaTeX 查表
    嵌入原 svg(像素级一致,currentColor 自动适配暗色),配不上降级为
    样式化 LaTeX 文本;svg 严格消毒。
    """

    URL = "https://mp.weixin.qq.com/s/x"
    BLOCK = ('<span class="span-block-equation"><section class="block-equation" '
             'data-formula="W^* \\in \\arg\\max" data-formula-type="block-equation">'
             '<svg viewbox="0 0 10 10"><text>残渣lex</text><path d="M1 1"/></svg>'
             '</section></span>')
    INLINE = ('<p>方案 <span class="inline-equation" data-formula="W = (W^{(1)})" '
              'data-formula-type="inline-equation">'
              '<svg viewbox="0 0 5 5"><path d="M2 2"/></svg></span> 表示</p>')

    def test_block_equation_to_dollar_block(self):
        """块级公式 → $$LaTeX$$,svg 文字残渣清零。"""
        md = parse_wechat_html(make_page(self.BLOCK), self.URL)["markdown"]
        self.assertIn("$$W^* \\in \\arg\\max$$", md)
        self.assertNotIn("残渣", md)

    def test_inline_equation_in_paragraph(self):
        """行内公式 → $LaTeX$,与前后文字自然衔接。"""
        md = parse_wechat_html(make_page(self.INLINE), self.URL)["markdown"]
        self.assertEqual(md, "方案 $W = (W^{(1)})$ 表示")

    def test_formulas_collected_with_svg(self):
        """data['formulas'] 收集 (LaTeX, svg) 配对。"""
        data = parse_wechat_html(make_page(self.BLOCK + self.INLINE), self.URL)
        pairs = data["formulas"]
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][0], "W^* \\in \\arg\\max")
        self.assertIn("<svg", pairs[0][1])

    def test_html_embeds_svg_for_formulas(self):
        """HTML:块级公式嵌原 svg(居中块),行内公式嵌行内 svg。"""
        data = parse_wechat_html(make_page(self.BLOCK + self.INLINE), self.URL)
        out = generate_html(data, [], "")
        self.assertIn('class="formula formula-block"', out)
        self.assertIn('class="formula-inline"', out)
        self.assertEqual(out.count("<svg"), 2)
        self.assertNotIn("$$", out)

    def test_html_fallback_styled_latex_without_svg(self):
        """配不上 svg 的公式:降级为样式化 LaTeX 文本,不留裸 $ 符。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "能量 $E = mc^2$ 守恒"
        data["formulas"] = []
        out = generate_html(data, [], "")
        self.assertIn('class="formula-inline">E = mc^2</span>', out)
        self.assertNotIn("$E", out)

    def test_svg_with_script_rejected(self):
        """svg 带 <script> 或 on* 事件属性:拒收,公式走 LaTeX 降级。"""
        bad = ('<p><span data-formula="x^2" data-formula-type="inline-equation">'
               '<svg onload="evil()"><script>alert(1)</script><path d="M1 1"/>'
               '</svg></span></p>')
        data = parse_wechat_html(make_page(bad), self.URL)
        self.assertEqual(data["formulas"], [])
        out = generate_html(data, [], "")
        body = out[out.find('<div class="content">'):]
        self.assertNotIn("<script", body)
        self.assertIn('class="formula-inline">x^2</span>', out)

    def test_inline_formula_tight_after_cjk(self):
        """紧贴中文的行内公式(得分$\\bar{r}_t$)也要识别——
        前置守卫只挡 ASCII 字母数字(标识符/价格),不挡中文。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "得分$\\bar{r}_t$越高越好"
        data["formulas"] = []
        out = generate_html(data, [], "")
        self.assertIn('class="formula-inline">\\bar{r}_t</span>', out)

    def test_svg_style_element_rejected(self):
        """svg 内嵌 <style>(可注入全页 CSS/@import 外联)拒收。"""
        bad = ('<p><span data-formula="a" data-formula-type="inline-equation">'
               '<svg><style>@import url(https://evil/x.css);</style>'
               '<path d="M1 1"/></svg></span></p>')
        data = parse_wechat_html(make_page(bad), self.URL)
        self.assertEqual(data["formulas"], [])

    def test_svg_inline_style_url_rejected(self):
        """元素 style 属性含 url((外联画笔/追踪信标)拒收。"""
        bad = ('<p><span data-formula="a" data-formula-type="inline-equation">'
               '<svg><path style="fill:url(https://evil/p.png)" d="M1 1"/>'
               '</svg></span></p>')
        data = parse_wechat_html(make_page(bad), self.URL)
        self.assertEqual(data["formulas"], [])

    def test_svg_smil_animation_rejected(self):
        """SMIL 动画元素(可注入 onload/href 属性值)拒收——公式必然是静态的。"""
        bad = ('<p><span data-formula="a" data-formula-type="inline-equation">'
               '<svg><set attributeName="onload" to="evil()"/>'
               '<path d="M1 1"/></svg></span></p>')
        data = parse_wechat_html(make_page(bad), self.URL)
        self.assertEqual(data["formulas"], [])

    def test_inline_code_dollar_pair_stays_literal(self):
        """行内代码里的 $x$ 是字面内容:不被公式抢走,不留占位符残渣。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "运行 `$x$` 命令"
        data["formulas"] = []
        out = generate_html(data, [], "")
        self.assertIn("<code>$x$</code>", out)
        self.assertNotIn("", out)

    def test_stray_double_dollars_do_not_swallow_paragraphs(self):
        """孤立的 $$ 不得跨段落吞并正文(块级公式必须单行配对)。"""
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = "段一 $$\n\n中间段落\n\n$$ 段三"
        data["formulas"] = []
        out = generate_html(data, [], "")
        body = out[out.find('<div class="content">'):]
        self.assertIn("中间段落", body)
        self.assertNotIn("formula-block", body)

    def test_many_formulas_no_placeholder_collision(self):
        """公式数量上两位数时占位符不串号,正文里的 M1 字样不受牵连。"""
        parts = ["M1 芯片评测"]
        formulas = []
        for i in range(12):
            parts.append(f"指标$x_{{{i}}}$说明")
            formulas.append((f"x_{{{i}}}", f'<svg data-i="{i}"><path d="M1 1"/></svg>'))
        data = parse_wechat_html(make_page("<p>占位</p>"), self.URL)
        data["markdown"] = " ".join(parts)
        data["formulas"] = formulas
        out = generate_html(data, [], "")
        self.assertIn("M1 芯片评测", out)
        for i in range(12):
            self.assertIn(f'data-i="{i}"', out)

    def test_literal_dollar_prices_not_formula(self):
        """正文里的价格($100 和 $200)不被误判成公式。"""
        data = parse_wechat_html(
            make_page("<p>价格在 $100 和 $200 之间</p>"), self.URL)
        out = generate_html(data, [], "")
        body = out[out.find('<div class="content">'):]
        self.assertIn("$100 和 $200", body)
        self.assertNotIn("formula-inline", body)


class TestNestedList(unittest.TestCase):
    """嵌套列表(内容质量 #6)。"""

    def test_two_level_unordered(self):
        data = parse_wechat_html(make_page(
            "<ul><li>一级甲<ul><li>二级甲</li><li>二级乙</li></ul></li>"
            "<li>一级乙</li></ul>"))
        md = data["markdown"]
        self.assertIn("- 一级甲", md)
        self.assertIn("  - 二级甲", md)
        self.assertIn("  - 二级乙", md)
        self.assertIn("- 一级乙", md)

    def test_indented_list_in_html(self):
        html = generate_html(
            {"title": "T", "author": "", "site": "", "images": [],
             "markdown": "- 一\n  - 一点一\n  - 一点二\n- 二"}, [], "")
        # 嵌套要形成嵌套 <ul>
        self.assertIn("<ul>", html)
        # 二级子列表出现在一级 <li> 里
        self.assertRegex(html, r"<li>一<ul>.*?一点一.*?一点二.*?</ul></li>")

    def test_li_with_mixed_text_and_strong_preserves_bold(self):
        """<li>Prefix <strong>bold</strong> suffix</li> 里的加粗不能丢(评审确认)。"""
        data = parse_wechat_html(make_page(
            "<ul><li>Prefix <strong>bold</strong> suffix</li></ul>"))
        self.assertIn("**bold**", data["markdown"])


class TestReviewFixes(unittest.TestCase):
    """本轮 code-review 确认项集中回归测试。"""

    def _html_for(self, md: str, **extra) -> str:
        data = {"title": "T", "author": "", "site": "", "images": [], "markdown": md}
        data.update(extra)
        return generate_html(data, [], "")

    def test_table_not_wrapped_in_p(self):
        """<table> 不能嵌在 <p> 里(评审 E)。"""
        html = self._html_for("text\n\n| a | b |\n| --- | --- |\n| c | d |\n\nmore")
        self.assertNotIn("<p><table>", html)
        self.assertIn("<table>", html)

    def test_italic_regex_ignores_math_asterisks(self):
        """math: 2*3 = 6 and 4*5=20 不应被识别为斜体(评审 A/D)。"""
        html = self._html_for("math: 2*3 = 6 and 4*5=20")
        self.assertNotIn("<em>", html)

    def test_italic_regex_still_matches_normal_italic(self):
        """*正常斜体* 仍然生效。"""
        html = self._html_for("前 *正常斜体* 后")
        self.assertIn("<em>正常斜体</em>", html)

    def test_table_cell_pipe_unescaped(self):
        """含 | 的 cell (\\|) 要还原为 |(评审 A)。"""
        data = parse_wechat_html(make_page(
            "<table><tr><th>头</th><th>值</th></tr>"
            "<tr><td>a|b</td><td>c</td></tr></table>"))
        html = generate_html(data, [], "")
        # HTML 里 cell 应显示 'a|b' 完整一格,不是被切成两格
        self.assertIn("<td>a|b</td>", html)
        self.assertNotIn("<td>a\\</td>", html)

    def test_markdown_has_publish_header(self):
        """Markdown 开头有'发布于 X · 公众号:Y'(设计承诺,评审 C/I/J)。"""
        from save_webpage import generate_markdown
        data = {"title": "T", "author": "烨笙总Yes", "date": "2026-06-26",
                "site": "公众号", "markdown": "正文段落"}
        md = generate_markdown(data, [], "")
        self.assertIn("2026-06-26", md)
        self.assertIn("烨笙总Yes", md)

    def test_download_image_does_not_retry_on_404(self):
        """4xx 不重试(评审 B/C)。"""
        import tempfile
        from unittest.mock import patch
        from save_webpage import download_image

        call_count = [0]

        class R404:
            status_code = 404
            def raise_for_status(self):
                import requests
                raise requests.HTTPError("404")

        def fake_get(url, **kwargs):
            call_count[0] += 1
            return R404()

        with tempfile.TemporaryDirectory() as tmp:
            with patch("save_webpage.requests.get", side_effect=fake_get), \
                 patch("save_webpage.time.sleep"):
                result = download_image("https://example.com/x.jpg", tmp, 0)
        self.assertIsNone(result)
        self.assertEqual(call_count[0], 1)  # 只调用 1 次,不重试

    def test_utcfromtimestamp_no_deprecation_warning(self):
        """时间戳解析不应触发 DeprecationWarning(评审 D)。"""
        import warnings
        html = f'''<!DOCTYPE html><html><head><title>T</title></head><body>
<h1 id="activity-name">T</h1>
<div id="js_content"><p>正文</p></div>
<script>var ct = "1782462134";</script></body></html>'''
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            data = parse_wechat_html(html)  # 不应抛出
        self.assertRegex(data.get("date", ""), r"^2026-06-2[456]$")


class TestShareText(unittest.TestCase):
    """复制到剪贴板的文本格式(日常小舒适 #3)。"""

    def test_full_share_text(self):
        text = format_share_text({
            "title": "标题",
            "author": "作者名",
            "date": "2026-06-26",
        }, url="https://example.com/x")
        self.assertIn("标题", text)
        self.assertIn("作者名 · 2026-06-26", text)
        self.assertIn("https://example.com/x", text)

    def test_share_text_without_date(self):
        text = format_share_text({"title": "标题", "author": "作者"}, url="https://x.com")
        self.assertIn("标题", text)
        self.assertIn("作者", text)
        self.assertIn("https://x.com", text)
        # 没日期就不要留孤零零的 " · " 或空行
        self.assertNotIn("· ", text.replace(" · ", ""))

    def test_share_text_without_author(self):
        text = format_share_text({"title": "标题", "date": "2026-01-01"},
                                 url="https://x.com")
        self.assertIn("标题", text)
        self.assertIn("2026-01-01", text)

    def test_share_text_title_only(self):
        text = format_share_text({"title": "只有标题"}, url="https://x.com")
        self.assertIn("只有标题", text)
        self.assertIn("https://x.com", text)


class TestDatePrefixDir(unittest.TestCase):
    """文件夹名加日期前缀(日常小舒适 #2)。"""

    def test_date_prefix_prepends_date(self):
        """使用文章 date 时,目录名为 YYYY-MM-DD_标题。"""
        import tempfile
        from unittest.mock import patch
        from save_webpage import save_article

        with tempfile.TemporaryDirectory() as tmp:
            fake = {"title": "我的文章", "author": "A", "date": "2026-06-26",
                    "markdown": "正文", "images": [], "site": "公众号"}
            with patch("save_webpage.extract_wechat", return_value=fake), \
                 patch("save_webpage.detect_site", return_value="wechat"):
                result = save_article(
                    "https://mp.weixin.qq.com/s/x", tmp,
                    formats=["md"], use_subfolder=True, date_prefix=True)
            self.assertFalse(result.get("error"))
            files = result["files"]
            self.assertTrue(any("2026-06-26_我的文章" in f for f in files),
                            f"实际:{files}")

    def test_no_date_falls_back_to_today(self):
        """文章没 date 时用当天日期。"""
        import tempfile, re, datetime
        from unittest.mock import patch
        from save_webpage import save_article

        with tempfile.TemporaryDirectory() as tmp:
            fake = {"title": "无日期文章", "author": "A", "date": "",
                    "markdown": "正文", "images": [], "site": ""}
            with patch("save_webpage.extract_generic", return_value=fake), \
                 patch("save_webpage.detect_site", return_value="generic"):
                result = save_article(
                    "https://x.com/a", tmp,
                    formats=["md"], use_subfolder=True, date_prefix=True)
            today = datetime.date.today().strftime("%Y-%m-%d")
            self.assertTrue(any(f"{today}_无日期文章" in f for f in result["files"]))


class TestToc(unittest.TestCase):
    """HTML 侧边浮动导航(日常小舒适 #5)。"""

    def test_build_toc_extracts_headings(self):
        headings = build_toc("<h1>标题一</h1><p>正文</p><h2>子标题</h2><h3>更深</h3>")
        self.assertEqual(len(headings), 3)
        self.assertEqual(headings[0]["text"], "标题一")
        self.assertEqual(headings[0]["level"], 1)
        self.assertEqual(headings[1]["text"], "子标题")
        self.assertEqual(headings[1]["level"], 2)

    def test_html_output_contains_toc_panel(self):
        """生成的 HTML 里有 toc 面板。"""
        data = {"title": "T", "author": "", "site": "", "images": [],
                "markdown": "## 章一\n\n正文\n\n## 章二\n\n正文"}
        html = generate_html(data, [], "")
        self.assertIn('class="toc-panel"', html)
        self.assertIn("章一", html)
        self.assertIn("章二", html)

    def test_headings_get_anchor_ids(self):
        """每个 heading 有可跳转的 id。"""
        data = {"title": "T", "author": "", "site": "", "images": [],
                "markdown": "## 章一\n\n正文"}
        html = generate_html(data, [], "")
        # 有 id 就能锚点跳转
        import re
        self.assertRegex(html, r'<h2\s+id="[^"]+">章一</h2>')


class TestDarkMode(unittest.TestCase):
    """HTML 深色模式跟随系统(日常小舒适 #4)。"""

    def test_dark_mode_media_query_present(self):
        data = {"title": "T", "author": "", "site": "", "images": [], "markdown": "正文"}
        html = generate_html(data, [], "")
        self.assertIn("prefers-color-scheme: dark", html)


class TestIndex(unittest.TestCase):
    """保存目录里生成目录索引(日常小舒适 #6)。"""

    def test_build_index_scans_articles(self):
        """扫描根目录下所有子文件夹里的 HTML,提取标题/作者/日期。"""
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            # 造两篇文章
            for i, (title, author, date) in enumerate([
                ("文章甲", "A", "2026-06-26"),
                ("文章乙", "B", "2026-06-27"),
            ]):
                sub = os.path.join(root, title)
                os.makedirs(sub)
                fake_html = f'''<!DOCTYPE html><html><head><title>{title}</title></head>
<body>
<h1>{title}</h1>
<div class="meta"><span class="author">{author}</span> <span class="date">{date}</span></div>
</body></html>'''
                with open(os.path.join(sub, f"{title}.html"), "w", encoding="utf-8") as f:
                    f.write(fake_html)
                open(os.path.join(sub, ".saved-article"), "w").close()

            index_html = build_index_html(root)
            self.assertIn("文章甲", index_html)
            self.assertIn("文章乙", index_html)
            self.assertIn("A", index_html)
            self.assertIn("2026-06-27", index_html)


class TestOpenFile(unittest.TestCase):
    """跨平台打开文件(日常小舒适 #1)。"""

    def test_open_file_calls_platform_opener(self):
        """macOS 上应调用 open 命令。"""
        from unittest.mock import patch
        import platform
        if platform.system() != "Darwin":
            self.skipTest("仅在 macOS 测试 open 调用")
        with patch("save_webpage.subprocess.run") as mock_run:
            open_file("/tmp/x.html")
            self.assertTrue(mock_run.called)
            call_args = mock_run.call_args[0][0]
            self.assertIn("open", call_args[0])
            self.assertIn("/tmp/x.html", call_args)


class TestReview2Fixes(unittest.TestCase):
    """本轮 code-review 确认项集中回归测试。"""

    def test_title_html_escaped(self):
        """title 里的 <script> 不能穿透到生成 HTML(评审 A/D/E)。"""
        data = {"title": "<script>alert(1)</script>", "author": "作者",
                "date": "", "site": "", "images": [], "markdown": "正文"}
        html = generate_html(data, [], "")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_author_html_escaped(self):
        data = {"title": "T", "author": "<img src=x onerror=alert(1)>",
                "date": "", "site": "", "images": [], "markdown": "正文"}
        html = generate_html(data, [], "")
        self.assertNotIn("<img src=x onerror=", html)

    def test_index_html_escapes_metadata(self):
        """目录索引卡片里 title/author 也要转义。"""
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            sub = os.path.join(root, "文章甲")
            os.makedirs(sub)
            # 造一篇已含被转义的 title(generate_html 出来的)
            with open(os.path.join(sub, "文章甲.html"), "w", encoding="utf-8") as f:
                f.write('<!DOCTYPE html><html><head><title>&lt;script&gt;A&lt;/script&gt;</title></head>'
                        '<body><h1>&lt;script&gt;A&lt;/script&gt;</h1>'
                        '<div class="meta"><span class="author">&lt;img&gt;</span>'
                        '<span class="date">2026-01-01</span></div></body></html>')
            # 造一个 saved-article 标记,让它被扫到
            open(os.path.join(sub, ".saved-article"), "w").close()
            idx = build_index_html(root)
        # 索引里应保留转义形式,不能出现原始 <script>
        self.assertNotIn("<script>A</script>", idx)

    def test_index_only_includes_marked_dirs(self):
        """build_index_html 只扫描含 .saved-article 标记的子目录,避免桌面污染。"""
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            # 造 3 个目录:2 个是真文章(有标记),1 个是桌面上其他 html(无标记)
            for name in ("真文章A", "真文章B"):
                sub = os.path.join(root, name)
                os.makedirs(sub)
                open(os.path.join(sub, ".saved-article"), "w").close()
                with open(os.path.join(sub, f"{name}.html"), "w", encoding="utf-8") as f:
                    f.write(f'<html><head><title>{name}</title></head><body>'
                            f'<h1>{name}</h1></body></html>')
            noise = os.path.join(root, "iCloud备份")
            os.makedirs(noise)
            with open(os.path.join(noise, "sync.html"), "w", encoding="utf-8") as f:
                f.write("<html><body>不是保存的文章</body></html>")

            idx = build_index_html(root)
            self.assertIn("真文章A", idx)
            self.assertIn("真文章B", idx)
            self.assertNotIn("不是保存的文章", idx)

    def test_save_article_writes_marker(self):
        """save_article 成功时应在文章目录里写 .saved-article 标记。"""
        import tempfile, os
        from unittest.mock import patch
        from save_webpage import save_article
        with tempfile.TemporaryDirectory() as tmp:
            fake = {"title": "标记测试", "author": "A", "date": "2026-01-01",
                    "markdown": "正文", "images": [], "site": ""}
            with patch("save_webpage.extract_generic", return_value=fake), \
                 patch("save_webpage.detect_site", return_value="generic"):
                save_article("https://x.com/a", tmp,
                             formats=["md"], use_subfolder=True)
            marker = os.path.join(tmp, "标记测试", ".saved-article")
            self.assertTrue(os.path.exists(marker))

    def test_cli_supports_date_prefix_flag(self):
        """CLI 应支持 --date-prefix。"""
        import subprocess
        result = subprocess.run(
            ["python3", "save_webpage.py", "--help"],
            cwd="/Users/xugu/项目代码/webpage-saver",
            capture_output=True, text=True, timeout=15)
        self.assertIn("--date-prefix", result.stdout)


class TestBatchShareTracking(unittest.TestCase):
    """批量复制应保留所有成功的分享文本(纯逻辑测试,不动 GUI)。"""

    def test_batch_shares_joined_by_blank_line(self):
        """给一个成功列表,拼出的分享文本应用空行分隔。"""
        successes = [
            ("https://a.com", {"title": "甲", "author": "作者A", "date": "2026-01-01"}),
            ("https://b.com", {"title": "乙", "author": "作者B", "date": "2026-01-02"}),
        ]
        # 逻辑:每篇 format_share_text 后用 \n\n 分隔
        text = "\n\n".join(
            format_share_text(r, url=u) for u, r in successes)
        self.assertIn("甲", text)
        self.assertIn("乙", text)
        self.assertIn("https://a.com", text)
        self.assertIn("https://b.com", text)
        # 甲的最后一行(url)后应有空行然后是乙
        self.assertRegex(text, r"https://a\.com\n\n乙")


def _seed_saved_dir(root, name, author="A", date="2026-01-01"):
    """在 root 下造一篇带 .saved-article 标记的文章目录。"""
    import os
    sub = os.path.join(root, name)
    os.makedirs(sub)
    open(os.path.join(sub, ".saved-article"), "w").close()
    with open(os.path.join(sub, f"{name}.html"), "w", encoding="utf-8") as f:
        f.write(f'<!DOCTYPE html><html><head><title>{name}</title></head>'
                f'<body><h1>{name}</h1><div class="meta">'
                f'<span class="author">{author}</span>'
                f'<span class="date">{date}</span></div></body></html>')


class TestScanSavedArticles(unittest.TestCase):
    """扫描保存目录返回结构化元数据(知识库化 #3 复用)。"""

    def test_returns_list_of_dicts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "甲", "作者A", "2026-01-01")
            _seed_saved_dir(root, "乙", "作者B", "2026-06-15")
            arts = scan_saved_articles(root)
            self.assertEqual(len(arts), 2)
            self.assertTrue(all(isinstance(a, dict) for a in arts))
            titles = [a["title"] for a in arts]
            self.assertIn("甲", titles)
            self.assertIn("乙", titles)

    def test_result_has_expected_keys(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "甲", "A", "2026-01-01")
            arts = scan_saved_articles(root)
            self.assertGreaterEqual(len(arts), 1)
            for key in ("title", "author", "date", "html_path", "folder"):
                self.assertIn(key, arts[0])

    def test_skips_unmarked_dirs(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "真文章", "A", "2026-01-01")
            # 无标记目录
            os.makedirs(os.path.join(root, "杂物"))
            with open(os.path.join(root, "杂物", "foo.html"), "w") as f:
                f.write("<html>随便</html>")
            arts = scan_saved_articles(root)
            self.assertEqual(len(arts), 1)
            self.assertEqual(arts[0]["title"], "真文章")

    def test_sorted_by_mtime_desc(self):
        """新的在前。"""
        import tempfile, os, time
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "旧", "A", "2026-01-01")
            time.sleep(0.05)
            _seed_saved_dir(root, "新", "B", "2026-06-01")
            arts = scan_saved_articles(root)
            self.assertEqual(arts[0]["title"], "新")


class TestIndexSearch(unittest.TestCase):
    """目录索引里的搜索框(知识库化 #1)。"""

    def test_index_has_search_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "文章")
            idx = build_index_html(root)
            self.assertIn('type="search"', idx)

    def test_search_javascript_present(self):
        """需要有 JS 监听 input 事件来过滤 card。"""
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "文章")
            idx = build_index_html(root)
            # 简单验证:含 querySelectorAll .card 和 input 事件
            self.assertIn(".card", idx)
            self.assertRegex(idx, r'addEventListener\s*\(\s*[\'"]input[\'"]')


class TestIndexStats(unittest.TestCase):
    """索引顶部统计条(知识库化 #2)。"""

    def test_stats_shows_total_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "甲")
            _seed_saved_dir(root, "乙")
            _seed_saved_dir(root, "丙")
            idx = build_index_html(root)
            self.assertIn("共 3 篇", idx)

    def test_stats_shows_date_range(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_saved_dir(root, "甲", "A", "2026-01-01")
            _seed_saved_dir(root, "乙", "B", "2026-06-15")
            idx = build_index_html(root)
            self.assertIn("2026-01-01", idx)
            self.assertIn("2026-06-15", idx)

    def test_stats_shows_top_sources(self):
        """作者数量 Top 前几名要出现在统计里。"""
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            for i in range(3):
                _seed_saved_dir(root, f"甲{i}", "热门作者")
            _seed_saved_dir(root, "乙", "冷门作者")
            idx = build_index_html(root)
            # 热门作者应有 "3" 关联
            self.assertRegex(idx, r'热门作者.{0,10}3')

    def test_empty_dir_shows_no_stats(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            idx = build_index_html(root)
            self.assertNotIn("共 0 篇", idx)


class TestCsdnLoginWall(unittest.TestCase):
    """CSDN 登录墙抛出更友好的错误信息(知识库化 #4)。"""

    def test_login_wall_error_mentions_login_steps(self):
        """短内容 + 含'登录'字样应抛出带指引的错误。"""
        from save_webpage import _csdn_parse_html
        html = '<html><body><h1>标题</h1><p>短</p>登录后可查看全文</body></html>'
        with self.assertRaises(Exception) as ctx:
            _csdn_parse_html(html, "https://blog.csdn.net/x")
        msg = str(ctx.exception)
        self.assertIn("登录 CSDN", msg)
        self.assertIn("浏览器", msg)


class TestDetectSiteExpanded(unittest.TestCase):
    """detect_site 应识别新增的 5 类站点。"""

    def test_weibo(self):
        self.assertEqual(detect_site("https://weibo.com/ttarticle/p/show?id=1234"), "weibo")
        self.assertEqual(detect_site("https://m.weibo.cn/detail/5023456789"), "weibo")

    def test_bilibili_article(self):
        self.assertEqual(detect_site("https://www.bilibili.com/read/cv12345"), "bilibili")
        self.assertEqual(detect_site("https://www.bilibili.com/opus/9999"), "bilibili")

    def test_juejin(self):
        self.assertEqual(detect_site("https://juejin.cn/post/7401234567890"), "juejin")

    def test_jianshu(self):
        self.assertEqual(detect_site("https://www.jianshu.com/p/abc123"), "jianshu")

    def test_zhihu_question_page_still_maps_to_zhihu(self):
        """知乎问题页仍走 zhihu 分支,由 extract_zhihu 内部区分单/多答案。"""
        self.assertEqual(detect_site("https://www.zhihu.com/question/12345"), "zhihu")
        self.assertEqual(detect_site("https://www.zhihu.com/question/12/answer/67"), "zhihu")

    def test_weibo_card_domain(self):
        """微博文章卡片域名 card.weibo.com 也识别为 weibo。"""
        self.assertEqual(
            detect_site("https://card.weibo.com/article/m/show/id/1234"), "weibo")


class TestReview3Fixes(unittest.TestCase):
    """本轮 code-review 确认项集中回归测试。"""

    def test_weibo_selector_typo_fixed(self):
        """div.article-main(正确拼写)应能匹配。"""
        html = ('<html><body>'
                '<div class="article-main"><p>正文来自 article-main</p></div>'
                '</body></html>')
        data = parse_weibo_html(html, "https://weibo.com/x")
        self.assertIn("正文来自 article-main", data["markdown"])

    def test_external_image_not_dropped(self):
        """B 站文章里引用了外站(非 hdslb)的图片,也应该保留。"""
        html = ('<html><body>'
                '<div id="read-article-holder">'
                '<p>这是一段足够长的正文,能通过 selector 20 字长度检查。</p>'
                '<img src="https://example.com/external.jpg">'
                '<img src="https://i0.hdslb.com/native.jpg"></div></body></html>')
        data = parse_bili_html(html, "https://www.bilibili.com/read/cv1")
        # 两张图都应该在,不能只留 hdslb
        self.assertEqual(len(data["images"]), 2)


class TestPDF(unittest.TestCase):
    """PDF 导出(打包批次 #1)。"""

    def test_command_contains_expected_flags(self):
        cmd = _build_chrome_pdf_cmd("/usr/bin/chrome",
                                     "/tmp/x.html", "/tmp/x.pdf")
        self.assertEqual(cmd[0], "/usr/bin/chrome")
        self.assertIn("--headless", cmd)
        self.assertIn("--disable-gpu", cmd)
        joined = " ".join(cmd)
        self.assertIn("--print-to-pdf=/tmp/x.pdf", joined)
        self.assertIn("file:///tmp/x.html", joined)

    def test_generate_pdf_calls_subprocess(self):
        """generate_pdf 成功路径:mock subprocess 返回 0,写空 PDF 文件。"""
        import tempfile, os
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            html_path = os.path.join(tmp, "x.html")
            pdf_path = os.path.join(tmp, "x.pdf")
            open(html_path, "w").write("<html></html>")

            def fake_run(cmd, **kwargs):
                # 模拟 Chrome 写出了 PDF
                open(pdf_path, "wb").write(b"%PDF-1.4 fake\n")
                return MagicMock(returncode=0)

            with patch("save_webpage.get_chrome_path", return_value="/usr/bin/chrome"), \
                 patch("save_webpage.subprocess.run", side_effect=fake_run):
                ok = generate_pdf(html_path, pdf_path)
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(pdf_path))

    def test_generate_pdf_no_chrome_raises(self):
        """找不到 Chrome 时应抛出明确错误消息。"""
        from unittest.mock import patch
        with patch("save_webpage.get_chrome_path",
                   side_effect=FileNotFoundError("no chrome")):
            with self.assertRaises(Exception) as ctx:
                generate_pdf("/tmp/a.html", "/tmp/a.pdf")
            self.assertIn("Chrome", str(ctx.exception))


class TestDefaultIcon(unittest.TestCase):
    """.app 默认图标生成(打包批次 #2)。"""

    def test_png_signature(self):
        """生成的字节流应以 PNG magic number 开头。"""
        data = make_default_icon_png(1024)
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_size_encoded_in_header(self):
        """IHDR chunk 里的宽/高应等于请求的 size。"""
        data = make_default_icon_png(512)
        # IHDR 起点固定在 offset 16,后 8 字节是 width+height (big-endian uint32)
        import struct
        w, h = struct.unpack(">II", data[16:24])
        self.assertEqual(w, 512)
        self.assertEqual(h, 512)


class TestMakeAppScript(unittest.TestCase):
    """make_app.command 是否具备可执行属性并存在。"""

    def test_script_exists_and_executable(self):
        import os, save_webpage
        # 用 save_webpage.py 的位置定位仓库根,便于任何机器上跑
        repo_root = os.path.dirname(os.path.abspath(save_webpage.__file__))
        script = os.path.join(repo_root, "make_app.command")
        self.assertTrue(os.path.exists(script), "make_app.command 不存在")
        # 至少 rwxr-xr-x 或类似
        self.assertTrue(os.access(script, os.X_OK), "缺 x 位")

    def test_windows_bat_exists(self):
        import os, save_webpage
        repo_root = os.path.dirname(os.path.abspath(save_webpage.__file__))
        bat = os.path.join(repo_root, "make_app.bat")
        self.assertTrue(os.path.exists(bat), "make_app.bat 不存在")
        self.assertGreater(os.path.getsize(bat), 0, "空文件")


class TestAppLauncherFinderEnv(unittest.TestCase):
    """双击 .app 的真实场景:Finder 只给系统 PATH,启动器必须仍能启动。

    回归背景(2026-07-06):用户双击 文章保存工具.app 无反应——
    启动器写的是裸 `python3`,Finder 环境下解析到苹果自带的
    /usr/bin/python3(没装第三方依赖),启动即崩且无任何提示。
    修复要求:1) 打包时固化 python3 绝对路径;2) 启动失败要弹系统对话框;
    3) 正式启动必须 exec(python 顶替启动器进程,App 身份/退出事件才正确)。
    """

    FINDER_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

    @classmethod
    def setUpClass(cls):
        import os, shutil, subprocess, sys, tempfile, save_webpage
        if sys.platform != "darwin":
            raise unittest.SkipTest("仅 macOS(需要 sips/iconutil)")
        repo_root = os.path.dirname(os.path.abspath(save_webpage.__file__))
        cls.tmp = tempfile.mkdtemp(prefix="makeapp_test_")
        proj = os.path.join(cls.tmp, "project")
        os.makedirs(proj)
        shutil.copy(os.path.join(repo_root, "make_app.command"), proj)
        # 图标生成分支要 import save_webpage
        shutil.copy(os.path.join(repo_root, "save_webpage.py"), proj)
        # 桩 gui.py:import 一个系统 python 没有的依赖,复现真实故障面
        with open(os.path.join(proj, "gui.py"), "w", encoding="utf-8") as f:
            f.write("import requests\nprint('GUI_OK')\n")
        # python3 垫片:让打包烤进启动器的 python == 跑测试的解释器,
        # 测试才不随机器 PATH 第一个 python3 是谁而漂移
        buildbin = os.path.join(cls.tmp, "buildbin")
        os.makedirs(buildbin)
        with open(os.path.join(buildbin, "python3"), "w", encoding="utf-8") as f:
            f.write('#!/bin/bash\nexec "%s" "$@"\n' % sys.executable)
        os.chmod(os.path.join(buildbin, "python3"), 0o755)
        build_env = dict(os.environ)
        build_env["PATH"] = buildbin + os.pathsep + build_env.get("PATH", "")
        r = subprocess.run(["bash", os.path.join(proj, "make_app.command")],
                           input=b"x", capture_output=True, timeout=180,
                           env=build_env)
        cls.build_out = (r.stdout.decode("utf-8", "replace")
                         + r.stderr.decode("utf-8", "replace"))
        cls.app = os.path.join(cls.tmp, "文章保存工具.app")
        cls.run_path = os.path.join(cls.app, "Contents", "MacOS", "run")
        if r.returncode != 0 or not os.path.exists(cls.run_path):
            raise AssertionError(
                f"构建失败(exit={r.returncode}):\n" + cls.build_out)
        # 假 osascript:把收到的参数写进文件,证明弹窗被调用(不真弹、不阻塞)。
        # 所有会跑启动器的用例都要把它排到 PATH 最前,失败路径才不会卡住等人点按钮。
        cls.stub_dir = os.path.join(cls.tmp, "stubbin")
        os.makedirs(cls.stub_dir)
        cls.dialog_marker = os.path.join(cls.tmp, "dialog_args.txt")
        with open(os.path.join(cls.stub_dir, "osascript"), "w", encoding="utf-8") as f:
            # printf 而非 echo:echo 会把开头的 -e 参数当自己的选项吞掉
            f.write('#!/bin/bash\nprintf \'%%s\\n\' "$@" > "%s"\n' % cls.dialog_marker)
        os.chmod(os.path.join(cls.stub_dir, "osascript"), 0o755)
        # 系统 python 若被人装过 requests,缺依赖场景就无法复现,相关用例跳过
        probe = subprocess.run(["/usr/bin/python3", "-c", "import requests"],
                               capture_output=True)
        cls.system_py_has_requests = (probe.returncode == 0)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _launch_env(self):
        """Finder 双击等价环境:受限 PATH + 假 osascript 打头。"""
        return {"HOME": self.tmp,
                "PATH": self.stub_dir + ":" + self.FINDER_PATH,
                "LANG": "zh_CN.UTF-8"}

    def _clear_run_artifacts(self):
        import os
        for p in (os.path.join(self.tmp, "Library", "Logs", "文章保存工具.log"),
                  self.dialog_marker):
            if os.path.exists(p):
                os.remove(p)

    def _read_launch_log(self):
        import os
        log = os.path.join(self.tmp, "Library", "Logs", "文章保存工具.log")
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="replace") as f:
                return f.read()
        return ""

    def test_launch_with_finder_restricted_path(self):
        """核心回归:受限 PATH 下启动必须成功(exit 0 且 gui 真的跑了)。"""
        import subprocess
        if self.system_py_has_requests:
            self.skipTest("系统 /usr/bin/python3 装了 requests,场景无法复现")
        self._clear_run_artifacts()
        r = subprocess.run([self.run_path], env=self._launch_env(),
                           capture_output=True, timeout=60)
        out = (r.stdout.decode("utf-8", "replace")
               + r.stderr.decode("utf-8", "replace"))
        self.assertEqual(r.returncode, 0,
                         f"Finder 受限 PATH 下启动失败:\n{out}\n{self._read_launch_log()}")
        self.assertIn("GUI_OK", out + self._read_launch_log(),
                      "gui.py 没有真正跑起来")

    def test_launcher_bakes_absolute_python_path(self):
        """启动器必须固化 python3 绝对路径(%q 输出,无引号),并有弹窗和 exec。"""
        with open(self.run_path, encoding="utf-8") as f:
            content = f.read()
        self.assertRegex(content, r"(?m)^PY=/",
                         "启动器没有固化 python3 绝对路径")
        self.assertIn("osascript", content,
                      "启动失败时应有 osascript 弹窗,不能无声无息")
        self.assertRegex(content, r"(?m)^exec ",
                         "正式启动必须 exec,否则 App 身份留在 bash 上")

    def test_failure_shows_dialog(self):
        """把固化路径换成缺依赖的系统 python 模拟启动失败:必须弹对话框。"""
        import os, re, subprocess
        if self.system_py_has_requests:
            self.skipTest("系统 /usr/bin/python3 装了 requests,场景无法复现")
        self._clear_run_artifacts()
        with open(self.run_path, encoding="utf-8") as f:
            content = f.read()
        self.assertRegex(content, r"(?m)^PY=/", "启动器没有固化 python3 绝对路径")
        broken = re.sub(r"(?m)^PY=.*$", "PY=/usr/bin/python3", content, count=1)
        broken_run = os.path.join(self.tmp, "broken_run")
        with open(broken_run, "w", encoding="utf-8") as f:
            f.write(broken)
        os.chmod(broken_run, 0o755)
        r = subprocess.run([broken_run], env=self._launch_env(),
                           capture_output=True, timeout=60)
        self.assertNotEqual(r.returncode, 0, "缺依赖竟然启动成功了?")
        self.assertTrue(os.path.exists(self.dialog_marker),
                        "启动失败却没有调用 osascript 弹窗")
        with open(self.dialog_marker, encoding="utf-8", errors="replace") as f:
            dialog = f.read()
        self.assertIn("启动失败", dialog, f"弹窗内容不对: {dialog}")


class TestDefaultIconIco(unittest.TestCase):
    """默认 ICO 图标生成(Windows 打包用)。"""

    def test_ico_signature(self):
        """ICO 文件以 magic \\x00\\x00\\x01\\x00 开头(reserved=0, type=1 icon)。"""
        data = make_default_icon_ico()
        self.assertEqual(data[:4], b'\x00\x00\x01\x00')

    def test_ico_declares_one_image(self):
        """count 字段应为 1(单尺寸)。"""
        import struct
        data = make_default_icon_ico()
        count = struct.unpack("<H", data[4:6])[0]
        self.assertEqual(count, 1)

    def test_ico_embeds_png(self):
        """dir entry 指向的 offset 处应是 PNG 数据。"""
        import struct
        data = make_default_icon_ico()
        # dir entry: offset 6 起,image_offset 在 dir entry 的 +12 处
        image_offset = struct.unpack("<I", data[18:22])[0]
        self.assertTrue(data[image_offset:image_offset + 8]
                        == b'\x89PNG\r\n\x1a\n')

    def test_ico_size_field_matches_actual(self):
        """dir entry 里的 bytes_in_res 应等于内嵌 PNG 字节数。"""
        import struct
        data = make_default_icon_ico()
        declared = struct.unpack("<I", data[14:18])[0]
        image_offset = struct.unpack("<I", data[18:22])[0]
        actual = len(data) - image_offset
        self.assertEqual(declared, actual)


def _seed_full_article(root, name, author, date, site, body_words, img_count):
    """在 root 下造一篇完整的 saved 文章(带 site badge、内容字数、图片数量)。"""
    import os
    sub = os.path.join(root, name)
    os.makedirs(sub)
    open(os.path.join(sub, ".saved-article"), "w").close()
    body_text = "字" * body_words  # 用中文字构造精确字数
    imgs = "".join(f'<img src="/x{i}.jpg">' for i in range(img_count))
    html = f'''<!DOCTYPE html><html><head><title>{name}</title></head>
<body>
<h1>{name}</h1>
<div class="meta">
  <span class="badge">{site}</span>
  <span class="author">{author}</span>
  <span class="date">{date}</span>
</div>
<div class="content">
<p>{body_text}</p>
{imgs}
</div>
</body></html>'''
    with open(os.path.join(sub, f"{name}.html"), "w", encoding="utf-8") as f:
        f.write(html)


class TestArticleExtraStats(unittest.TestCase):
    """_read_article_extra_stats 从 HTML 里提取 site/word_count/image_count。"""

    def test_reads_site_from_badge(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "甲", "A", "2026-01-01", "公众号", 100, 2)
            html_path = os.path.join(root, "甲", "甲.html")
            stats = _read_article_extra_stats(html_path)
            self.assertEqual(stats["site"], "公众号")

    def test_reads_word_count_from_content(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "乙", "B", "2026-01-02", "B站专栏", 500, 3)
            stats = _read_article_extra_stats(os.path.join(root, "乙", "乙.html"))
            # 允许±20 字误差(HTML tag 计算)
            self.assertGreater(stats["word_count"], 480)
            self.assertLess(stats["word_count"], 520)

    def test_reads_image_count(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "丙", "C", "2026-01-03", "掘金", 100, 7)
            stats = _read_article_extra_stats(os.path.join(root, "丙", "丙.html"))
            self.assertEqual(stats["image_count"], 7)


class TestDashboard(unittest.TestCase):
    """build_dashboard_html 数据总览页(抓取统计仪表盘)。"""

    def test_empty_dir_shows_placeholder(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            html = build_dashboard_html(root)
            self.assertIn("还没", html)

    def test_shows_total_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "文1", "作者A", "2026-06-01", "公众号", 100, 1)
            _seed_full_article(root, "文2", "作者A", "2026-06-15", "公众号", 200, 2)
            _seed_full_article(root, "文3", "作者B", "2026-07-01", "掘金", 300, 0)
            html = build_dashboard_html(root)
            self.assertIn("3", html)  # 总篇数

    def test_shows_source_diversity(self):
        """含 2 个不同的 site 类型时应体现。"""
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "文1", "A", "2026-06-01", "公众号", 100, 1)
            _seed_full_article(root, "文2", "B", "2026-06-15", "掘金", 200, 2)
            html = build_dashboard_html(root)
            self.assertIn("公众号", html)
            self.assertIn("掘金", html)

    def test_uses_conic_gradient_for_type_distribution(self):
        """网站类型环形图用 CSS conic-gradient。"""
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "文1", "A", "2026-06-01", "公众号", 100, 1)
            _seed_full_article(root, "文2", "B", "2026-06-15", "掘金", 200, 2)
            html = build_dashboard_html(root)
            self.assertIn("conic-gradient", html)

    def test_shows_top_author(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            # 作者 A 三篇,作者 B 一篇 → A 排前
            _seed_full_article(root, "文1", "作者A", "2026-06-01", "公众号", 100, 0)
            _seed_full_article(root, "文2", "作者A", "2026-06-05", "公众号", 100, 0)
            _seed_full_article(root, "文3", "作者A", "2026-06-10", "公众号", 100, 0)
            _seed_full_article(root, "文4", "作者B", "2026-06-15", "掘金", 100, 0)
            html = build_dashboard_html(root)
            # 作者 A 应先于 作者 B 出现(排行榜按 count 降序)
            self.assertLess(html.find("作者A"), html.find("作者B"))

    def test_has_heatmap_grid(self):
        """365 天热力图 grid 存在。"""
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "甲", "A", "2026-01-01", "公众号", 100, 1)
            html = build_dashboard_html(root)
            self.assertIn("heatmap", html)

    def test_dark_mode_css_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            _seed_full_article(root, "甲", "A", "2026-01-01", "公众号", 100, 1)
            html = build_dashboard_html(root)
            self.assertIn("prefers-color-scheme: dark", html)


class TestParseWeibo(unittest.TestCase):
    """微博文章解析(用合成 fixture,不真的抓取)。"""

    def test_ttarticle_layout(self):
        html = '''<html><head>
<meta property="og:title" content="微博长文标题">
<title>标题 - 微博</title></head>
<body>
<div class="WB_editor_iframe_new">
  <p>第一段正文</p>
  <p>第二段正文</p>
  <p><img src="https://wx1.sinaimg.cn/large/img_a.jpg"></p>
</div>
</body></html>'''
        data = parse_weibo_html(html, "https://weibo.com/ttarticle/p/show?id=1")
        self.assertEqual(data["site"], "微博")
        self.assertIn("微博长文标题", data["title"])
        self.assertIn("第一段正文", data["markdown"])
        self.assertIn("第二段正文", data["markdown"])
        self.assertEqual(len(data["images"]), 1)


class TestParseBili(unittest.TestCase):
    """B 站专栏/opus 解析。"""

    def test_read_cv_layout(self):
        html = '''<html><head><title>专栏标题</title></head><body>
<h1 class="title">专栏标题</h1>
<div id="read-article-holder">
  <p>专栏正文 A</p>
  <p>专栏正文 B</p>
  <p><img data-src="https://i0.hdslb.com/bfs/pic1.jpg"></p>
</div>
</body></html>'''
        data = parse_bili_html(html, "https://www.bilibili.com/read/cv1")
        self.assertEqual(data["site"], "B站专栏")
        self.assertIn("专栏标题", data["title"])
        self.assertIn("专栏正文 A", data["markdown"])
        self.assertEqual(len(data["images"]), 1)

    def test_opus_layout(self):
        html = '''<html><head><title>动态</title></head><body>
<div class="opus-module-content">
  <p>动态第一段</p>
  <p>动态第二段</p>
</div>
</body></html>'''
        data = parse_bili_html(html, "https://www.bilibili.com/opus/1")
        self.assertIn("动态第一段", data["markdown"])


class TestParseJuejin(unittest.TestCase):
    """掘金文章解析。"""

    def test_markdown_body_layout(self):
        html = '''<html><head><title>掘金标题 - 掘金</title></head><body>
<h1 class="article-title">掘金标题</h1>
<div class="markdown-body">
  <h2>小节</h2>
  <p>正文内容第一段。</p>
  <p>正文内容第二段。</p>
  <p><img src="https://p3-juejin.byteimg.com/img_j.jpg"></p>
</div>
<div class="author-name">阿甲</div>
</body></html>'''
        data = parse_juejin_html(html, "https://juejin.cn/post/1")
        self.assertEqual(data["site"], "掘金")
        self.assertIn("掘金标题", data["title"])
        self.assertIn("正文内容第一段", data["markdown"])
        self.assertEqual(len(data["images"]), 1)


class TestParseJianshu(unittest.TestCase):
    """简书文章解析。"""

    def test_article_layout(self):
        html = '''<html><head><title>简书文章 - 简书</title></head><body>
<h1 class="title">简书文章</h1>
<article>
  <p>简书正文一。</p>
  <p>简书正文二。</p>
  <p><img data-original-src="https://upload-images.jianshu.io/img_s.jpg"></p>
</article>
<div class="author">作者阿乙</div>
</body></html>'''
        data = parse_jianshu_html(html, "https://www.jianshu.com/p/1")
        self.assertEqual(data["site"], "简书")
        self.assertIn("简书文章", data["title"])
        self.assertIn("简书正文一", data["markdown"])
        self.assertEqual(len(data["images"]), 1)


class TestZhihuMultiDetection(unittest.TestCase):
    """URL 判断:问题页(无 /answer/)应触发多答案模式。"""

    def test_is_question_page(self):
        from save_webpage import _zhihu_is_question_page
        self.assertTrue(_zhihu_is_question_page("https://www.zhihu.com/question/123"))
        self.assertTrue(_zhihu_is_question_page("https://www.zhihu.com/question/123/"))
        self.assertFalse(_zhihu_is_question_page("https://www.zhihu.com/question/123/answer/456"))
        self.assertFalse(_zhihu_is_question_page("https://zhuanlan.zhihu.com/p/123"))


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
        # 顺序钉死:发布于 · 作者 · 原文(评审跟进)
        self.assertTrue(first_line.endswith(data["url"]), f"实际:{first_line}")

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
        # url 为空串/None 同样不渲染(spec:无 url 键 / url 为空)
        for empty in ("", None):
            data["url"] = empty
            self.assertNotIn("原文:", generate_markdown(data, [], ""))

    def test_markdown_rejects_non_http_url(self):
        """javascript: 伪协议不进元信息头(守门)。"""
        from save_webpage import generate_markdown
        data = {"title": "T", "author": "", "date": "", "site": "",
                "markdown": "正文", "url": "javascript:alert(1)"}
        md = generate_markdown(data, [], "")
        self.assertNotIn("javascript:", md)
        self.assertNotIn("原文", md)

    # ---- HTML 侧 ----

    def test_html_meta_has_source_link(self):
        """meta 区有可点击的原文链接。"""
        data = {"title": "T", "author": "A", "markdown": "正文", "site": "公众号",
                "images": [], "url": "https://mp.weixin.qq.com/s/abc123"}
        html = generate_html(data, [], "")
        self.assertIn('class="src-link"', html)
        self.assertIn('href="https://mp.weixin.qq.com/s/abc123"', html)
        self.assertIn("原文链接", html)
        # 新标签页 + 防反向 tabnabbing,重构丢失会被抓住(最终评审跟进)
        self.assertIn('target="_blank" rel="noopener"', html)

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
        # url 为空串/None 同样不渲染(spec:无 url 键 / url 为空)
        for empty in ("", None):
            data["url"] = empty
            self.assertNotIn('class="src-link"', generate_html(data, [], ""))

    def test_html_rejects_non_http_url(self):
        """javascript: 伪协议不渲染成链接(守门)。"""
        data = {"title": "T", "author": "", "markdown": "正文", "site": "",
                "images": [], "url": "javascript:alert(1)"}
        html = generate_html(data, [], "")
        self.assertNotIn('class="src-link"', html)
        self.assertNotIn("javascript:alert", html)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
