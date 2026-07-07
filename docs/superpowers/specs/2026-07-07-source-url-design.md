# 保存的文章带原文链接 设计

日期:2026-07-07
状态:用户已批准(brainstorming 两轮确认:范围=文章内两项;HTML 位置=meta 区)

## 目标

每篇新保存的文章(HTML + Markdown)都记录原文 URL。起因:调试 OPD 文章解析 bug 时,想重新抓取原文却发现保存的文件里没有链接,只能让用户手动提供。

## 范围

- 做:HTML meta 区加「原文链接」超链接;Markdown 元信息头追加原文 URL
- 不做:目录页(目录.html)每张卡片加原文跳转——卡片整体已是一个 `<a>` 链接,HTML 不允许链接嵌套,做的话要重构卡片结构、牵动 3 组测试。核心痛点靠文章内两项已解决(目录页点进文章一眼可见),此项留待真有需要再单独立项
- 不做:旧文章迁移——已保存的文章不回填 URL,重新保存即可补上

## 决策记录

### URL 注入点(方案 A,单点注入)

- `save_article(url, ...)` 在提取成功后执行 `data["url"] = url`
- 两个生成函数用 `data.get("url", "")` 读取,没有就不渲染
- 备选方案 B(改 9 个提取器)、C(改生成函数签名)均被否:改动面大且无额外收益;方案 A 对直接调用生成函数的现有测试完全向后兼容

### HTML 侧(generate_html)

- meta 区(站点徽章 · 作者 · 日期)末尾追加:
  `<span><a class="src-link" href="{转义后URL}" target="_blank" rel="noopener">原文链接↗</a></span>`
- URL 经 `html.escape`(quote=True)转义后进 href 属性,与 title/author 同一套 XSS 防护
- 新增 `.src-link` 样式:灰色小链接,悬停变深;深色模式配色与现有 meta 一致
- PDF 由该 HTML 生成,自动带上,零额外改动

### Markdown 侧(generate_markdown)

- 元信息头追加一段:`> 发布于 2026-07-01 · 公众号:某作者 · 原文: https://...`
- URL 作为 meta_bits 的一员,日期/作者都空时输出 `> 原文: https://...`(现有 `if meta_bits:` 逻辑自动覆盖)
- URL 以纯文本形式写入(不用 `[原文](url)` 链接语法,规避 URL 含括号时的转义坑;主流渲染器会自动把裸 URL 变成可点击链接)

### 安全守门

- 仅当 URL 通过 `_is_http_url`(`http://`/`https://` 开头)才输出,HTML 与 Markdown 两侧一致
- 防的是 `javascript:` 伪协议这类脏数据混进 href

## 测试计划(TDD,先写失败测试)

新增 `TestSourceUrl` 测试类,8 项(落地为 9 个测试方法:第 4 项拆 MD/HTML 两侧各一):

1. generate_html:data 带 url → 输出含 `class="src-link"` 且 href 为该 URL
2. generate_html:URL 含 `"` 与 `&` → 属性值被转义(XSS)
3. generate_html:data 无 url 键 / url 为空 → 不渲染 src-link 链接元素(向后兼容;`.src-link` CSS 样式规则常驻 `<style>`,与 `.badge`/`.author` 一致,不在断言范围内)
4. `javascript:` 伪协议 → generate_html 不渲染链接,generate_markdown 头部不输出「原文」(两侧守门一致)
5. generate_markdown:带 url → 元信息头含 `原文: https://...`
6. generate_markdown:日期/作者全空仅有 url → 仍输出 `> 原文: ...` 行
7. generate_markdown:无 url → 头部不出现「原文」
8. save_article 端到端:mock 提取器,保存后 HTML 与 MD 文件内容均含原文 URL

现有 158 项测试保持全绿。已知风险点:若 `TestMetadata` 等对 meta 区有精确匹配断言,可能需要同步微调断言(TDD 运行即暴露)。

## 验收标准

- 保存任一文章,打开 HTML 首屏 meta 区能点「原文链接↗」跳回原文
- 打开 MD,元信息头能复制到原文 URL
- `python3 -m unittest test_save_webpage` 全绿(158 旧 + 9 新 = 167,实施时验收通过)
