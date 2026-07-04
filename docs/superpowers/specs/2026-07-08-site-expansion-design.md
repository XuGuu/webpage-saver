# 站点扩展批次(5 项)设计

日期:2026-07-08
状态:Auto Mode 下用户已批准整批,直接实施

## 目标

覆盖国内几大常用平台,减少"这个站抓不了"的挫败。

## 设计原则

每个站点新增两层函数(和现有 wechat/csdn 一致):
- `parse_<site>_html(html, url) -> dict` — 纯函数,可单测
- `extract_<site>(url) -> dict` — 负责抓取,委托给 parse

`detect_site` 新增 5 个域名识别分支。

## 决策记录

### 1. 微博(m.weibo.cn 头条文章)

- 支持 URL:`weibo.com/ttarticle/*`、`card.weibo.com/article/m/show/id/*`、`m.weibo.cn/status/*`、`m.weibo.cn/detail/*`(status/detail 是短博文,ttarticle 是长文)
- 抓取:`curl_cffi` 伪装 Chrome,先请求 m 版页面
- 解析:提取 `<meta property="og:title">` 作标题,寻找 `render_data` / `$render_data` JS 变量的 JSON 拿正文
- 兜底:`trafilatura` 从 HTML 提正文
- 反爬极强,失败率会高,给出明确错误信息

### 2. B 站专栏

- 支持 URL:`bilibili.com/read/cv*`、`read.bilibili.com/cv*`、`www.bilibili.com/opus/*`
- 抓取:`requests` + UA 伪装
- 解析:`<div id="read-article-holder">` 或 `<div class="article-holder">` 内的文章内容;标题从 `<title>` 或 `.article-title` 拿
- 图片:`<img data-src>` 懒加载属性
- 反爬弱,应稳定可用

### 3. 掘金

- 支持 URL:`juejin.cn/post/*`
- 抓取:`requests` + UA 伪装
- 解析:优先从 `__NEXT_DATA__` JSON 里提取正文和元数据;兜底 `<div class="markdown-body">`
- 反爬中等,应稳定

### 4. 简书

- 支持 URL:`jianshu.com/p/*`
- 抓取:`curl_cffi` 伪装(简书有基础反爬)
- 解析:`<article>` 或 `<div class="_2rhmJa">` 里正文;`<h1 class="_1RuRku">` 作标题;`.author .name` 作者
- CSS 类名可能变化,退回 `<article>` 兜底

### 5. 知乎多答案

- 支持 URL:`zhihu.com/question/{id}`(URL 里没 `/answer/`,是问题页)
- 单答案 URL(`.../question/xxx/answer/yyy`)保持现有 extract_zhihu 逻辑
- 多答案实现:
  - 沿用 DrissionPage,进问题页
  - 遍历 `.List-item` 元素
  - 对每个回答提取 `.AuthorInfo-name` 作者 + `.RichContent-inner` 正文
  - 拼接成一个 markdown:`# 问题标题\n\n## 回答者 A\n\n答案A正文\n\n## 回答者 B\n\n答案B正文`
- 图片:所有回答的图片扁平化收集
- 遍历上限:默认 10 个回答(避免无限滚动,YAGNI)

### `detect_site` 新增判断

```
"weibo.com" / "weibo.cn" → "weibo"
"bilibili.com" (含 /read/ 或 /opus/) → "bilibili"
"juejin.cn" → "juejin"
"jianshu.com" → "jianshu"
"zhihu.com/question/" (末尾无 answer) → "zhihu_question"(新类型)
```

## 测试

每个站点一组 parse 测试(用真实抓下来的 HTML 剪成的 fixture,精简到 <10KB),断言 title/正文子串/图片数量。

detect_site 加对应识别测试。

真实网络端到端测试用户手工验证。现有 105 个测试不许坏。

## 明确不做(YAGNI)

微博视频/相册解析、B 站视频(是视频不是文章)、掘金评论区、简书专题/收藏夹、知乎无限滚动加载全部答案、知乎盐选专栏付费文章、多回答自动去广告。

## README 更新

支持的网站表格里新增 5 行,标注反爬难度和登录需求。

## 评审后修正(2026-07-08 code review)

- 修正 selector typo:`div.artical-main` → `div.article-main`(拼写错,原本永远不匹配)
- 图片过滤策略调整:content_el 里的所有图都保留(已经限定在正文范围),
  只在 fallback 走整页 scope 时才用 img_domain_marker 过滤——避免正文里外链图被误丢
- `_fetch_and_parse` 里 curl_cffi 非 200 状态改为抛出带状态码的错误,不再静默变"页面为空"
