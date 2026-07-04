#!/usr/bin/env python3
"""save_webpage.py 的单元测试

运行: python3 -m unittest test_save_webpage -v
"""

import unittest

from save_webpage import parse_wechat_html, generate_html, pick_url_from_clipboard, split_urls


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
        self.assertIn("<h4>四级标题</h4>", self._html_for("#### 四级标题"))

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
        self.assertNotIn("<p><h2>", html)
        self.assertNotIn("<p><ul>", html)
        self.assertIn("<h2>标题</h2>", html)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
