#!/usr/bin/env python3
"""save_webpage.py 的单元测试

运行: python3 -m unittest test_save_webpage -v
"""

import unittest

from save_webpage import parse_wechat_html


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
