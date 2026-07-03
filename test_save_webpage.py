#!/usr/bin/env python3
"""save_webpage.py 的单元测试

运行: python3 -m unittest test_save_webpage -v
"""

import unittest

from save_webpage import parse_wechat_html, generate_html


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
