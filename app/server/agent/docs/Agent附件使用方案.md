# Agent 附件使用方案

## 1. 目标

让 Agent 能够在不撑大模型上下文的前提下，理解和使用用户上传的多个、较长的附件。

核心原则：**系统提示词只注入文件索引，正文内容由 Agent 按需读取和检索。**

## 2. 职责边界

### 2.1 文件服务

文件服务负责文件的上传、保存、显式内容源构建和读取，各阶段通过 `file_id` 衔接。

- 每个文件保存到 `data/uploads/{file_id}/`。
- 源文件保存为 `original.xxx`。
- `/file/upload` 只保存原文件并返回 `file_id`，不会执行内容解析。
- Agent 附件前端在上传后显式调用 `/file/parse`，PDF 优先通过 MinerU 转换为 `content.md`。
- 纯文本、代码等文件直接以源文件作为内容源。
- 图片暂不提取文字；扫描型 PDF 由 MinerU 处理。

### 2.2 文件上下文中间件

`FileContextMiddleware` 负责在 Agent 本次运行的首次模型调用前，构建并注入文件索引。

中间件只提供：

- `file_id`
- 原始文件名和类型
- 文件大小
- 文档目录（标题与行号）
- 无标题文件的前几行预览
- 截断和省略提示

中间件**不注入全文**，也不提供 `list_uploaded_files` 工具。因为本次请求可访问的文件清单已经在提示词中，额外的列表工具会造成重复。

### 2.3 Agent 工具

附件工具只允许访问本次 `file_ids` 中明确授权的文件。

| 工具 | 作用 | 是否已有 |
| --- | --- | --- |
| `read_uploaded_file` | 按 `file_id` 和行号范围读取单份文件正文 | 是 |
| `search_uploaded_files` | 在本次附件集合中按关键词检索，返回命中文件、行号和上下文摘要 | 是 |

## 3. 上下文压缩策略

### 3.1 单文件目录上限

每份文件最多注入前 `50` 条标题，但会同时统计文档总行数、标题总数和省略标题数量。若目录超过上限，提示词必须明确说明：

```text
文档总长度：5800 行；标题总数：126；已展示：50 个标题。
目录已截断，后续还有 76 个标题未展示；请使用 start_line、end_line 分段读取。
```

没有 Markdown 标题的纯文本、代码等文件，降级为展示前 `5` 行非空预览。

### 3.2 多文件上限

一次 Agent Run 最多展示 `10` 份文件的详细索引。其余文件不展开目录，只汇总数量和类型，例如：

```text
本次还有 47 个附件未展开：30 个 PDF、15 个 DOCX、2 个 CSV。
如需定位相关内容，请使用 search_uploaded_files 检索关键词。
```

详细展示文件的排序规则第一版保持简单：

1. 文件名或扩展名与用户问题有直接匹配的文件优先。
2. 未匹配时按本次请求中 `file_ids` 的传入顺序展示。
3. 后续接入知识库和向量能力后，再考虑语义相关性排序。

### 3.3 单次读取上限

`read_uploaded_file` 默认只返回有限行数，并限制最大输出字符数。超过限制时返回截断提示，引导 Agent 继续使用更精确的行号范围读取。

## 4. search_uploaded_files 设计

### 4.1 工具定位

`search_uploaded_files` 是跨附件定位工具，不负责返回全文。它用于让 Agent 从被省略的文件或长文档中找到相关位置，再调用 `read_uploaded_file` 精读。

### 4.2 建议参数

```json
{
  "keyword": "RAG",
  "file_ids": ["由 ToolRuntime 自动注入，不由模型传入"],
  "max_results": 20,
  "context_lines": 2
}
```

模型只需要提供 `keyword`，可选提供 `max_results` 和 `context_lines`。文件白名单必须从 `ToolRuntime.context.file_ids` 获取，不能相信模型自行传入的文件标识。

### 4.3 建议返回

```json
{
  "keyword": "RAG",
  "matches": [
    {
      "file_id": "file_001",
      "file_name": "AI岗位JD.pdf",
      "line_number": 82,
      "snippet": "理解 RAG 基本原理，并能够实现基础检索增强生成流程。"
    }
  ],
  "truncated": false
}
```

检索范围只能是本次 Agent 请求传入的附件内容源。工具结果仍需限制命中数量和字符数。

## 5. Agent 使用流程

```text
用户上传附件
  -> 文件服务保存 original.xxx
  -> 前端获得 file_id
  -> 前端调用 /file/parse 显式构建内容源
  -> 调用 /agent/messages 时传入 file_ids
  -> FileContextMiddleware 注入文件索引
  -> Agent 根据目录判断需要阅读的文件
  -> read_uploaded_file 分段精读
  -> 如需跨文件定位，调用 search_uploaded_files
  -> 再按 file_id 和行号精读命中片段
  -> 生成最终回答
```

## 6. 示例

用户上传 `岗位JD.pdf`、`候选人简历.pdf` 和 30 份项目材料，提问：

> 根据岗位 JD 和简历分析匹配度，并重点查看 RAG 项目经验。

Agent 首先看到的只是两个优先文件的目录，以及“还有 30 个文件未展开”的说明。

随后执行：

1. 调用 `read_uploaded_file` 阅读岗位 JD 的任职要求章节。
2. 调用 `read_uploaded_file` 阅读候选人简历的项目经历章节。
3. 调用 `search_uploaded_files(keyword="RAG")`，在所有本次上传文件中定位 RAG 相关项目材料。
4. 根据返回的 `file_id`、`line_number`，继续调用 `read_uploaded_file` 精读命中内容。
5. 基于证据生成匹配度分析。

## 7. 安全与限制

- 所有附件工具都只能读取 `ToolRuntime.context.file_ids` 白名单内的文件。
- 不允许通过文件名、磁盘路径或通配符越过 `file_id` 授权边界。
- 文件全文不进入系统提示词，避免上下文膨胀和不必要的数据暴露。
- 以后若接入 OCR、知识库、向量检索，只扩展文件服务和工具实现，不改变 Agent 的“索引 -> 检索 -> 精读”工作方式。
