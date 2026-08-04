# 真实 Web 工具：Jina AI + 百度千帆 + Readability 管道

用户将占位 web 工具替换为真实实现。

**架构**：
- `web_fetch` → Jina AI (`r.jina.ai`) 抓取原始 HTML → `readabilipy` 提取正文 → `markdownify` 转 Markdown → `Article.to_markdown()`
- `web_search` → 百度千帆 web_search API → `BaiduWebSearchResponse` dataclass → `format_results()` 生成结构化 Markdown
- Client 与 Tool 分离：`JinaClient` / `BaiduWebSearchClient` 是纯 HTTP 层，`web_fetch_tool` / `web_search_tool` 是 LangChain `@tool` 包装

**设计决策**：
- Jina AI 而非直接 httpx 抓取：Jina 处理 headless 渲染、反爬虫检测
- `HtmlReadabilityExtractor` 两阶段：先 Readability，失败回退无 Readability
- `asyncio.to_thread` 包裹 CPU-bound 的 HTML 解析，避免阻塞事件循环
- LLM 友好的输出格式：Markdown（而非 JSON 或原始 HTML）

**遇到的 bug**：`logger` 定义在文件末尾被上方引用、`JinaClient()` 每次调用重建、`print(e)` 裸打印。

**Evidence**: `tools/web_fetch.py` (77 行), `tools/web_search_client.py` (127 行), `utils/readability.py` (45 行)
