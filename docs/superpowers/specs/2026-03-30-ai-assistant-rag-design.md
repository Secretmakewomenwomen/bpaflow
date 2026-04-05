# AI 助手第一阶段设计

## 背景

当前系统已经具备以下能力：

- Vue 3 + Ant Design Vue 的工作台界面
- 顶部 `AppHeader`、左侧文档栏、中间画布的工作区布局
- 登录鉴权与按用户隔离的数据访问
- 文件上传到 OSS
- 文件元信息写入 PostgreSQL
- 文本内容异步向量化并写入 pgvector 表

本次新增一个面向工作台用户的 AI 助手入口，挂载在页面左上角。AI 助手后续会支持两类能力：

1. RAG 检索并返回相关 OSS 文件
2. 基于检索结果生成 XML

第一阶段只实现第 1 类能力，但接口和编排结构需要为第 2 类能力预留扩展点。

## 目标

第一阶段交付后，用户可以在工作台顶部点击 AI 标识，打开一个高度撑满可用视口的 Popover 面板，输入自然语言问题。系统先识别意图：

- 如果识别为 `rag_retrieval`，返回答案摘要、命中文本片段、相关 OSS 文件
- 如果识别为 `generate_xml`，返回结构化提示，告知该能力暂未开放

第一阶段只检索当前登录用户自己上传且文本向量化成功的文件。

## 非目标

本阶段不做以下内容：

- XML 生成执行能力
- 多轮会话与会话持久化
- 历史记录列表
- 图片向量检索
- 混合召回、重排、查询改写
- 流式输出
- AI 助手独立页面

## 用户体验

### 入口位置

- 在顶部 `AppHeader` 左侧品牌区增加 AI 标识按钮
- AI 标识与现有工作台品牌信息同层展示
- 点击按钮打开 AI Popover

### Popover 形态

- 视觉上使用“从 AI 标识弹出的浮层面板”
- 实现上不使用 Ant Design Vue 原生 `Popover` 气泡层，而使用挂载到页面头部附近的自定义浮层容器
- 浮层锚定在左上角 AI 标识附近展开
- 浮层垂直方向撑满工作区可用高度
- 浮层内部包含固定的头部、输入区和滚动结果区
- 点击 AI 标识、关闭按钮或浮层外区域可收起
- 第一阶段不加全局遮罩，保持工作台仍可见

### 面板内容

面板内至少包含：

1. 标题区，显示 AI 助手状态
2. 问题输入框
3. 提交按钮
4. 当前请求加载态
5. 意图识别结果提示
6. 答案摘要
7. 命中文本片段列表
8. 相关文件列表

### 结果展示规则

- 摘要回答放在结果顶部
- 文本片段按相关性排序
- 每条片段展示文件名、片段文本、页码范围、相关度
- 相关文件去重后展示
- 每个文件提供下载入口

### 异常与空态

- 未输入问题时禁止提交
- 请求中禁用重复提交
- 未命中资料时展示空结果文案，而不是报错
- 意图识别为 `generate_xml` 时显示“该能力将在下一阶段开放”
- 后端错误时展示统一错误提示

## 意图模型

第一阶段只区分两个意图：

- `rag_retrieval`
- `generate_xml`

不识别业务子意图，也不做复杂分类层级。分类目标是为后续工作流分流，而不是做业务标签体系。

### 分类策略

第一阶段使用 LangGraph 中的 `classify_intent` 节点完成分类。实现上允许使用 LLM 或规则+LLM 混合方式，但对外只暴露稳定的二分类结果。

为降低误分流成本，默认策略如下：

- 明确包含“生成 XML、输出 xml、产出流程 xml”等表达时，判定为 `generate_xml`
- 其他问题默认判定为 `rag_retrieval`

这样即便分类能力较弱，也不会阻断主流程。

## 系统设计

### 前端组件拆分

新增组件：

- `AiAssistantPopover.vue`

调整组件：

- `AppHeader.vue`
- `CanvasPage.vue`

职责划分：

- `AppHeader.vue` 负责展示 AI 按钮并抛出打开/关闭事件
- `CanvasPage.vue` 负责维护 AI 助手面板开关和查询状态
- `AiAssistantPopover.vue` 负责渲染输入、结果、错误态和加载态
- `AiAssistantPopover.vue` 内部负责滚动容器边界，结果区独立滚动，头部和输入区固定

### 后端模块拆分

新增 API 路由：

- `POST /api/ai/assistant/query`

建议新增文件：

- `backend/app/api/routes/ai.py`
- `backend/app/schemas/ai.py`
- `backend/app/services/ai_assistant_service.py`
- `backend/app/services/ai_rag_service.py`
- `backend/app/services/langgraph_assistant.py`

职责划分：

- `ai.py` 负责鉴权、请求响应映射
- `schemas/ai.py` 定义稳定的请求响应模型
- `ai_assistant_service.py` 作为接口门面，调用 LangGraph 工作流
- `langgraph_assistant.py` 定义状态、节点与图
- `ai_rag_service.py` 负责向量检索、结果聚合、答案生成、文件去重与下载链接组装

## LangGraph 工作流

### 第一阶段图结构

第一阶段图结构保持极简：

1. `classify_intent`
2. 条件分支
3. `retrieve_documents`
4. `synthesize_answer`
5. `build_response`

### 状态定义

图状态至少包括：

- `user_id`
- `query`
- `intent`
- `retrieved_chunks`
- `answer`
- `snippets`
- `related_files`
- `error`

### 节点行为

`classify_intent`

- 输入用户问题
- 输出二分类意图

`retrieve_documents`

- 仅在 `rag_retrieval` 下执行
- 使用与文本向量化完全相同的 `EmbeddingService` 生成查询 embedding
- 复用当前文本 embedding 模型、归一化逻辑、向量维度和余弦距离假设，禁止单独切换查询模型
- 在 pgvector 文本表中检索当前用户可访问的文本块
- 拉取对应文件元信息

`synthesize_answer`

- 根据检索到的大块/小块内容生成简洁摘要
- 若未命中文档，返回空摘要和空结果列表

`build_response`

- 统一输出给 API
- 如果意图是 `generate_xml`，返回占位响应
- `generate_xml` 在第一阶段从 `classify_intent` 后直接进入 `build_response`

## 数据检索设计

### 检索范围

第一阶段仅检索：

- 当前登录用户上传的文件
- `text_vector_status = VECTORIZED`

不检索：

- 其他用户文件
- 纯图片语义向量
- 向量化失败或处理中记录

### 检索数据源

复用当前 PostgreSQL + pgvector 文本表，不新增向量数据库。检索主表为配置中的 `pgvector_text_table`。

### 关联条件

文本向量表本身不包含 `user_id`，因此检索 SQL 需要联结 `uploaded_file` 表，通过以下条件限制数据域：

- `uploaded_file.id = vector_table.file_id`
- `uploaded_file.user_id = :user_id`
- `uploaded_file.text_vector_status = 'VECTORIZED'`

### 返回粒度

检索命中以文本 chunk 为基本粒度，响应中返回的 `snippets` 直接来源于命中的文本块。`snippets[].text` 固定映射自 `small_chunk_text`，用于短片段展示。摘要生成优先使用命中的 `large_chunk_text` 作为上文，避免只基于过短片段生成。

对于定位信息：

- `pdf` 和可分页来源返回 `page_start`、`page_end`
- `docx`、`png OCR` 等无稳定页码来源时，`page_start`、`page_end` 返回 `null`
- 所有片段统一返回 `small_chunk_index`，作为非分页来源的定位兜底字段

### 排序与去重

- 检索 SQL 使用 pgvector 距离升序排序
- API 响应中的 `score` 统一定义为 `similarity_score`，取值范围 `0` 到 `1`
- 第一阶段固定使用余弦距离口径，与当前 `EmbeddingService` 的 L2 归一化和 `vector_cosine_ops` 配置保持一致
- `similarity_score` 的换算公式固定为 `1 - cosine_distance`
- 若换算结果超出区间，按 `0` 到 `1` 截断
- 片段按 `similarity_score` 降序排序
- 文件列表按文件内最高 `similarity_score` 排序
- 同一文件只在 `related_files` 中出现一次

### 推荐默认参数

第一阶段默认参数建议：

- 召回 chunk 数：`top_k = 6`
- 摘要上下文去重后的大块数：`max_context_blocks = 4`
- 文件列表最大返回数：`max_files = 5`

这些参数应配置化，避免写死在代码中。

## OSS 文件返回设计

### 返回目标

检索结果中的相关文件需要可直接下载，而不是只展示元信息。

### 第一阶段实现

优先复用现有 OSS 公网地址能力，返回一个由后端统一控制的下载地址。推荐后端提供：

- `GET /api/uploads/{upload_id}/download`

由该接口校验用户权限后，再重定向到 OSS 公网 URL 或返回受控下载响应。

这样前端不需要感知 OSS bucket/key，也不会绕过当前用户隔离。

该下载接口属于第一阶段交付范围，不延期。

### 返回字段

每个相关文件至少返回：

- `upload_id`
- `file_name`
- `mime_type`
- `created_at`
- `download_url`

文档中涉及上传文件主键时统一使用 `upload_id`，其含义就是 `uploaded_file.id`。

## API 契约

### 请求

`POST /api/ai/assistant/query`

```json
{
  "query": "赔付流程里的理赔审核环节有什么要求？"
}
```

### 响应

```json
{
  "intent": "rag_retrieval",
  "message": null,
  "answer": "系统会基于上传资料总结出的摘要答案。",
  "snippets": [
    {
      "upload_id": 12,
      "file_name": "保险赔付流程规范（标准版）.docx",
      "text": "命中的文本片段",
      "page_start": null,
      "page_end": null,
      "small_chunk_index": 4,
      "score": 0.91
    }
  ],
  "related_files": [
    {
      "upload_id": 12,
      "file_name": "保险赔付流程规范（标准版）.docx",
      "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "created_at": "2026-03-29T10:00:00Z",
      "download_url": "/api/uploads/12/download"
    }
  ]
}
```

其中：

- `page_start`、`page_end` 为可选字段，无分页来源时为 `null`
- `score` 表示归一化后的 `similarity_score`
- `snippets[].text` 固定取自 `small_chunk_text`
- 摘要生成上下文固定取去重后的 `large_chunk_text`
- 无命中时返回 `message = "未检索到相关资料。"`、`answer = ""`、`snippets = []`、`related_files = []`

### 相关下载接口

`GET /api/uploads/{upload_id}/download`

- 要求登录
- 仅允许访问当前用户自己的文件
- 成功时返回 `302`，重定向到 OSS 公网 URL
- 无权限或文件不存在时返回对应错误

### `generate_xml` 占位响应

```json
{
  "intent": "generate_xml",
  "message": "XML 生成功能将在下一阶段开放。",
  "answer": "",
  "snippets": [],
  "related_files": []
}
```

### 错误响应

第一阶段对 AI 查询接口约定两类错误响应：

1. 可降级错误
2. 不可降级错误

可降级错误包括：

- 生成模型未配置
- 摘要生成失败

这类错误仍返回 `200`，并沿用正常响应结构：

```json
{
  "intent": "rag_retrieval",
  "message": "摘要生成能力未配置，已返回检索结果。",
  "answer": "",
  "snippets": [],
  "related_files": []
}
```

不可降级错误包括：

- 查询 embedding 未配置
- pgvector 查询失败
- 数据库不可用

这类错误返回非 `200` 状态码，统一错误结构如下：

```json
{
  "detail": {
    "code": "AI_RETRIEVAL_FAILED",
    "message": "检索失败，请稍后重试。"
  }
}
```

状态码约定：

- 配置缺失使用 `503`
- 检索执行失败使用 `500`
- 鉴权失败使用现有鉴权中间件返回值

## 前端状态设计

前端状态至少包括：

- `popoverOpen`
- `query`
- `submitting`
- `result`
- `error`

交互顺序：

1. 用户打开 AI Popover
2. 输入问题
3. 提交请求
4. 展示加载态
5. 渲染结构化结果或错误

面板关闭后是否保留上次结果，第一阶段保留当前内存态，不做持久化。

## 配置设计

后端新增配置项建议：

- `assistant_retrieval_top_k`
- `assistant_max_context_blocks`
- `assistant_max_related_files`
- `assistant_llm_base_url`
- `assistant_llm_api_key`
- `assistant_llm_model`

若当前环境尚未配置独立推理模型，可先复用现有可用模型配置，但需要在代码层将“embedding 模型”和“生成模型”分开。

查询向量生成不新增独立 embedding 配置，直接复用当前 `EmbeddingService` 的配置与维度：

- `embedding_base_url`
- `embedding_api_key`
- `embedding_model`
- `pgvector_text_vector_dimension`
- `pgvector_distance_operator`

第一阶段允许 `classify_intent` 采用纯规则实现，不强制依赖额外 LLM。

第一阶段要求 `pgvector_distance_operator = vector_cosine_ops`。若环境配置为其他距离算子，则 AI 检索能力视为未正确配置并返回 `503`。

若生成摘要所需的生成模型未配置，系统按以下策略降级：

- 检索仍然正常执行
- `snippets` 与 `related_files` 正常返回
- `answer` 置空字符串
- `message` 返回“摘要生成能力未配置，已返回检索结果。”
- 接口整体返回 `200`

## 安全与隔离

### 用户隔离

- AI 查询接口必须要求登录
- 所有检索都基于 `current_user.user_id`
- 下载接口必须再次校验文件归属

### 提示词边界

- 摘要生成仅基于检索到的上下文
- 没有命中时不得编造文件结论
- 输出中不暴露 OSS bucket、object key 等内部细节

## 错误处理

需要明确处理以下场景：

- 用户没有任何可检索文件
- 文件存在但尚未向量化完成
- embedding 或生成模型未配置
- pgvector 查询失败
- 摘要生成失败

处理原则：

- 检索层错误返回明确错误消息
- 无命中返回空结果，不作为异常
- `generate_xml` 不视为错误，而是正常占位响应
- 若仅摘要生成失败或未配置生成模型，降级返回检索结果，不中断整个接口

## 实现约束

- `generate_xml` 分支不执行检索和摘要生成节点
- `snippets` 的查询与响应映射固定基于 `small_chunk_text`
- `score` 的实现口径固定为 `1 - cosine_distance`，并截断到 `0` 到 `1`
- AI 查询接口的不可降级错误统一返回 `detail.code + detail.message` 结构
- AI 浮层建议宽度 `420px`，最大宽度不超过视口宽度减 `32px`
- AI 浮层高度为“视口高度减去页头上下边距后的可用高度”，结果区独立滚动
- AI 浮层层级高于页头和画布内容，但低于全局确认弹窗

## 测试策略

第一阶段至少覆盖：

### 后端

- 意图分类路由选择
- 用户隔离条件生效
- 检索结果映射为 `snippets` 与 `related_files`
- `generate_xml` 占位响应正确
- 下载接口权限校验

### 前端

- AI 按钮可打开和关闭 Popover
- 提交后渲染加载态
- `rag_retrieval` 结果正确展示
- `generate_xml` 占位提示正确展示
- 错误态与空态渲染

## 里程碑

### M1

- 增加 AI 入口与 Popover 容器
- 接通前端请求和基础结果渲染

### M2

- 实现 LangGraph 二分类与 RAG 检索链路
- 返回摘要、片段、相关文件

### M3

- 增加下载接口
- 补齐测试与错误处理

## 风险与取舍

### 风险 1

当前 `pgvector` 表结构未直接记录 `user_id`，检索时必须联表过滤。这会让查询实现比单表相似度检索更复杂。

### 风险 2

现有 OSS 服务只提供上传和删除，没有下载封装。若直接返回 `public_url`，访问控制会弱化，因此建议补一个受控下载接口。

### 风险 3

若第一阶段就把 Popover 做成完整工作流容器，会导致前端状态迅速膨胀。因此本设计只保留单次问答态。

## 后续扩展

第二阶段可在现有图上继续扩展：

- `generate_xml_with_rag`
- 人工确认与驳回原因回流
- 会话中断与恢复
- XML 和节点信息生成

当前设计的重点是保证这些后续能力可以在同一个 LangGraph 状态图上自然扩展，而不是重做第一阶段接口。
