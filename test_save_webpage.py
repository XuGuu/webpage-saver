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


if __name__ == "__main__":
    unittest.main(verbosity=2)
