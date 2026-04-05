# AI RAG 多路召回面试经验

## 这份文档怎么用

这份文档不是设计稿，而是面试口径。目标是回答下面几类问题：

- 你们的多路召回是怎么做的
- 为什么不是只做向量检索
- BM25 为什么选 `pg_search`
- rerank 怎么做，权重怎么定
- 为什么这次没有做降级
- 你在落地过程中踩过什么坑

如果面试时间很短，可以先讲“一分钟版本”；如果面试官继续深挖，再展开后面的细节。

## 一分钟版本

我把原来的单路向量召回升级成了三路召回，全部复用 PostgreSQL 单栈完成。第一路是 `pgvector` 做语义向量检索，第二路是 `pg_search` 做 BM25 关键词检索，第三路是规则召回，主要补文件名、编号、错误码、接口名这类确定性强的场景。三路先各自放大召回，再按 `(file_id, small_chunk_index)` 做 chunk 级去重合并，最后走一层轻量 rerank：主分是向量/BM25/规则的加权融合，附加分只做文件名完全命中、术语命中、最近上传、文件类型匹配这类小幅纠偏，而且 bonus 有上限，避免规则把低质量结果硬顶上来。因为这次业务明确要求 BM25 是正式能力，不是实验能力，所以我没有做静默降级，只要开了 BM25 但扩展或索引没准备好，就在启动期直接失败。

## 项目背景

原来的检索链路只有一条：用户问题先做 embedding，然后去 `pgvector` 表里按相似度找 chunk。

这个方案有两个优点：

- 架构简单
- 语义检索能力好

但缺点也很明显：

- 遇到文件名、错误码、接口名、缩写、英文标识符时容易漏召回
- 用户问“最新的 PDF”“最近上传的架构图”时，向量分数不一定能稳定表达业务意图
- 只靠一个分数维度，排序容易抖动

所以我没有推翻原架构，而是在现有 `PostgreSQL + pgvector` 体系上做增量升级，补上 BM25 和规则召回。

## 1. 多路召回是怎么做的

### 1.1 总体流程

完整链路是：

1. 对 query 做轻量分析
2. 并行执行三路召回
3. 按 chunk 维度合并去重
4. 做统一 rerank
5. 输出 `snippets` 和 `related_files`

这里的关键点是“统一候选结构”。不管数据来自向量、BM25 还是规则召回，最终都会映射成同一种候选对象，字段里至少包含：

- `file_id`
- `file_name`
- `mime_type`
- `created_at`
- `small_chunk_index`
- `text`
- `vector_score`
- `bm25_score`
- `rule_score`
- `final_score`

这样后面的融合和排序逻辑就不会碎成三套。

### 1.2 切片策略怎么做

多路召回的前提不是“先有搜索”，而是“先把文档切成适合检索的粒度”。

我这里没有走复杂的语义切分，而是用了比较稳的双层切片：

- 小块 `small_chunk`：用于 embedding、向量检索、BM25 检索、规则召回
- 大块 `large_chunk`：由连续小块拼出来，主要是为后续上下文扩展预留

当前默认配置是：

- `small_chunk_size = 700`
- `small_chunk_overlap = 120`
- `large_chunk_size = 2100`

可以把它理解成：

- 先按 700 字左右切检索块
- 相邻块保留 120 字 overlap，避免一句话被切断后两边都看不全
- 再把连续小块按不超过 2100 字聚成一个更大的上下文块

这样做的核心目标是把“检索粒度”和“上下文粒度”拆开。

### 1.3 切片前为什么还要先清洗

切片之前，文本不会直接下刀，而是先做一层统一清洗，主要包括：

- 去分页符
- 去 HTML 标签
- 压缩连续空白
- 对分页文档做重复页眉页脚去重

这一步的价值很实际：

- 避免 PDF/OCR 脏数据把 chunk 边界切得很碎
- 避免页眉页脚反复进入 embedding，污染召回结果
- 让 BM25 和向量检索看到更稳定的文本

也就是说，真正进入切片器的不是原始抽取文本，而是清洗后的 `ParsedSegment`。

### 1.4 小块是怎么切的

小块策略不是按句子或标题做语义分段，而是“按清洗后的 segment 做固定窗口滑动切分”。

规则很简单：

- 如果一个 segment 长度不超过 `small_chunk_size`，就直接作为一个小块
- 如果超过上限，就按固定窗口切
- 步长 = `small_chunk_size - small_chunk_overlap`

这么做有几个好处：

- 行为稳定，容易调参
- 不依赖额外模型，不会引入切片不确定性
- 对中英文混合、接口名、错误码、配置项这类内容更稳

为什么这里不直接上“智能语义切片”？因为当前项目目标是把检索链路先做稳，而不是在切片层再引入一套复杂策略。固定窗口虽然朴素，但可解释、可复现、可压测。

### 1.5 大块是怎么来的

大块不是重新对原文再切一遍，而是把连续的小块往后拼，直到接近 `large_chunk_size` 为止。

这样每个小块都会挂上两个字段：

- `large_chunk_id`
- `large_chunk_text`

这么设计的好处是：

- 检索命中仍然保持 chunk 级精度
- 但后续如果需要补更完整上下文，不用再回源重组
- 小块和大块天然有稳定映射关系

这也是为什么表结构里同时保留：

- `small_chunk_text`
- `large_chunk_text`
- `small_chunk_index`
- `large_chunk_id`

### 1.6 这些切片分别用在哪

当前这一版里，真正参与多路召回主流程的是 `small_chunk_text`：

- embedding 输入来自 `small_chunk_text`
- 向量检索查的是 `small_chunk_text`
- BM25 主字段也是 `small_chunk_text`
- 规则召回最终补出来的仍然是 chunk 级结果
- 返回给前端的 `snippets[].text` 也是 `small_chunk_text`

`large_chunk_text` 当前已经落表，但更多是作为后续上下文扩展能力的储备字段，而不是这版多路召回的主排序字段。

换句话说，这一版的设计重点是：

- 检索命中要细
- 证据展示要准
- 上下文扩展能力先把数据结构准备好

### 1.7 为什么这个切片策略适合多路召回

因为三路召回最终都要落到统一候选结构上，而这个统一结构天然就是 chunk 级的。

如果 chunk 太大，会有几个问题：

- 向量检索语义变钝，细节容易被稀释
- BM25 命中范围太宽，关键词相关性会下降
- 规则召回一旦命中文件名，很容易把大段无关文本一起带进来

如果 chunk 太小，也会出问题：

- 语义不完整
- 相邻上下文断裂
- 排序容易抖动

所以我最后选的是：

- 小块负责精确命中
- overlap 负责连续性
- 大块负责上下文兜底

这其实是在检索精度和上下文完整性之间做平衡。

### 1.8 Query 分析怎么做

我没有在召回前引入 LLM query rewrite，只做了轻量特征抽取，目的是稳定、可控、低成本。主要抽四类信息：

- `keywords`：普通关键词
- `identifier_tokens`：编号、缩写、接口名、错误码一类 token
- `wants_recent`：是否有“最近、最新、刚上传”这类时效性意图
- `requested_file_types`：是否明确要 PDF、图片、文档

这些特征后面会同时服务于规则召回和 rerank bonus。

### 1.9 向量召回怎么做

向量召回延续原来的能力：

- query 先生成 embedding
- 到文本 chunk 表里做相似度搜索
- 通过 `JOIN uploaded_file` 做 `user_id` 隔离
- 只查 `text_vector_status = 'VECTORIZED'`
- 把距离转成 `0~1` 的 similarity score
- 低于最小阈值的结果直接过滤

这一路解决的是“语义相近但字面不完全一致”的问题。

### 1.10 BM25 召回怎么做

BM25 这一路使用 `pg_search`，直接建在现有 chunk 表上，不单独维护搜索副本。

核心思路是：

- 主字段是 `small_chunk_text`
- `file_name` 也参与召回，而且额外做 boost
- 查询时仍然 `JOIN uploaded_file`
- 继续沿用用户隔离和状态过滤

我选择 chunk 级 BM25，而不是文件级 BM25，原因是最终要给大模型喂的是证据片段，不是整份文件。

### 1.11 规则召回怎么做

规则召回不是用来替代搜索引擎，而是做“确定性补召回”。

我这次的规则比较克制，核心只做文件名 token 命中：

- 把 `identifier_tokens + keywords` 做去重并集
- 用这些 token 去匹配 `LOWER(file_name) LIKE ...`
- 每个文件只取前几个 chunk
- 文件内部按 `small_chunk_index` 排序
- 文件之间优先 recent

为什么每个文件只取少量 chunk？因为规则路很容易“命中文件名就整份文件都上榜”，如果不限制，每个命中文件会刷出很多重复 chunk，污染最终排序。

### 1.12 合并去重怎么做

三路结果不是按 `file_id` 去重，而是按 `(file_id, small_chunk_index)` 去重。

这是一个很重要的实现点。因为同一个文件经常会有多个 chunk 同时有价值，如果只按文件去重，会直接损失证据片段。

合并时我做两件事：

- 分数取各路最大值
- 元数据缺什么补什么

这一步不排序，只负责把同一个 chunk 的多路命中信息汇总起来。

## 2. 为什么要这样做

### 2.1 为什么不能只靠向量召回

因为向量召回擅长语义，但不擅长“强字面约束”的问题。

典型场景：

- 用户直接问某个文件名
- 用户问接口名、报错码、配置项
- 用户问版本号、英文缩写
- 用户问“最新的 PDF”“最近上传的架构图”

这些场景里，语义接近不等于业务上最相关。

### 2.2 为什么保留 PostgreSQL 单栈

因为这个项目现在还在快速迭代阶段，优先级是：

1. 先把检索质量做上来
2. 但不要把系统复杂度拉爆

如果一上来就拆 Elasticsearch/OpenSearch，会新增很多成本：

- 新服务部署和运维
- 双写一致性
- 查询 DSL 和权限过滤同步
- 两套索引体系的调试成本

当前数据规模和复杂度下，`pgvector + pg_search + SQL 规则` 都能放在 PostgreSQL 里解决，所以单栈是性价比最高的方案。

### 2.3 为什么把融合和重排放在 `AIRagService`

因为 LangGraph 主流程本身没变，变化只发生在 `retrieve_documents` 这一步。把 orchestration 和 rerank 放在 `AIRagService`，能保证：

- 业务边界清晰
- 不用新引入抽象层
- 改动集中，可测性更好

这是一种“贴着现有结构做增量演进”的做法。

## 3. BM25 为什么选择 `pg_search`

先澄清一个面试里的常见口误：通常说的是 `pg_search`，不是 `pb_search`。这里我选的是 ParadeDB 的 PostgreSQL 扩展 `pg_search`。

### 3.1 为什么不是 PostgreSQL 原生全文检索

PostgreSQL 原生全文检索当然能做关键词搜索，但我这次更看重三点：

- BM25 打分模型更贴近搜索场景
- 能直接拿到 `pdb.score(...)` 这种可用于融合的相关性分数
- 和现有 PostgreSQL 表、pgvector 可以共存，不需要引入独立搜索服务

一句话说，原生 FTS 能做“可用”，`pg_search` 更适合做“更像搜索引擎的可解释相关性排序”。

### 3.2 为什么不是独立搜索引擎

不是不能上，而是当前阶段没必要上。

独立搜索引擎更适合下面这些场景：

- 数据量很大
- 查询 DSL 很复杂
- 需要高并发检索集群
- 需要高阶搜索能力，比如复杂聚合、同义词、拼写纠错、多索引治理

但当前项目要解决的是“在已有 PostgreSQL 架构里，把检索质量显著提升”，不是做一个独立搜索平台。

### 3.3 为什么在 chunk 表上直接建 BM25

原因有三个：

- 避免双写，向量和 BM25 共用同一份 chunk 数据
- 省去文件级和 chunk 级之间的二次映射
- 最终喂给大模型的本来就是 chunk

所以我直接在 `uploaded_file_text_vector` 上建 `idx_<table>_bm25` 索引。

### 3.4 为什么不做降级

这次不是“能用最好，不能用就退回向量检索”的实验功能，而是正式的多路召回。

如果启动时发现：

- `pg_search` 扩展没装
- BM25 索引没建

那我就直接让服务失败，而不是静默降级。原因很简单：

- 静默降级会让线上以为自己在跑多路召回，实际上只跑了向量
- 检索质量问题会变得更难排查
- 监控和验收口径都会失真

所以我把 BM25 readiness check 放到启动期做强校验。

## 4. Rerank 重排序策略

### 4.1 主分怎么计算

主分是三路召回的加权和：

```text
base_score =
  vector_weight * vector_score +
  bm25_weight * bm25_score +
  rule_weight * rule_score
```

当前配置思路是：

- 向量分权重最高，因为它仍然是主召回能力
- BM25 很接近向量权重，因为它是字面精确性的核心补充
- 规则权重最低，因为规则只负责补，不负责主导排序

### 4.2 bonus 怎么设计

在主分之外，我又加了四类 bonus：

- 文件名完全命中
- 关键词在 chunk 文本中命中
- 最近上传
- 文件类型匹配

这里 bonus 的原则不是“重新发明一个排序器”，而是做业务纠偏。

比如：

- 用户直接搜文件名时，文件名完全命中的结果应该再往前推一点
- 用户明确说“最近的 PDF”，那 recent 和 file type 需要反映出来

### 4.3 为什么 bonus 要设置上限

我把 bonus 总和做了 cap，防止出现这种情况：

- 某个 chunk 本身语义和关键词都不强
- 但因为文件名或者 recent 命中了几个规则
- 结果被硬顶到第一名

这会让排序变得很“脆”。所以我的思路是：

- 主分决定主体排序
- bonus 只做小幅纠偏

### 4.4 为什么 BM25 分数要归一化

BM25 的原始分数不是天然的 `0~1`，不同 query 下可比性也不一样。

如果不先归一化，直接和向量分相加，会出现某一路分数体系天然更大，导致融合失真。

所以我先对当前批次的 BM25 分数做 min-max 归一化，再参与融合。

### 4.5 为什么 related_files 和 snippets 分开排

`snippets` 是 chunk 级结果，`related_files` 是文件级结果。

同一个文件可能命中多个强 chunk，所以我在文件级排序时采用：

- 先取每个文件命中的最高 chunk 分数
- 再按文件维度输出 `related_files`

这样既保留证据片段，又能给前端一个稳定的文件列表。

## 5. 这次落地时的几个关键实现点

### 5.1 三路统一数据域

不管哪一路召回，都必须满足：

- `uploaded_file.user_id = :user_id`
- `uploaded_file.text_vector_status = 'VECTORIZED'`

也就是说，多路召回不是三套系统各查各的，而是在同一个用户隔离和状态约束下统一检索。

### 5.2 去重粒度是 chunk，不是 file

这是最容易被忽略但很关键的一点。做 RAG 时，大模型真正消费的是证据片段。如果把去重粒度放到文件级，会直接损失有效上下文。

### 5.3 `created_at` 必须来自 `uploaded_file`

recent bonus、文件级 tie-break、related_files 排序，都依赖文件上传时间。

所以检索 SQL 返回的 `created_at` 必须明确来自 `uploaded_file.created_at`，不能混用 chunk 表自己的时间字段，否则“最近上传”的语义会漂掉。

### 5.4 路由 top_k 和最终 top_k 要分开

每一路召回的 `top_k` 我会放得比最终返回量更大。

原因是：

- 召回阶段要尽量把候选捞全
- 融合和 rerank 之后再做最终截断

如果一开始就把每一路都裁得很小，后面很可能没有足够的候选空间去重排。

## 6. 补充一个前端流式输出问题：`stream_invoke` 的 SSE 是怎么走的

这块很容易被问到，尤其是面试官看到项目里既有 LangGraph，又有前端逐字输出时，通常会追问：

- 后端为什么要用 `yield`
- 为什么不直接用 `graph.stream()`
- `assistant_delta`、`assistant_done` 这些事件是谁发的

### 6.1 整体链路

流式接口的入口是 `POST /ai/conversations/{conversation_id}/messages/stream`。

完整顺序可以概括成：

1. 先把用户消息落库
2. 立刻推一条 `user_message` SSE 给前端
3. 进入 `stream_invoke`
4. 先发 `assistant_start`
5. 按意图分支逐步产出 `assistant_delta`
6. 最终把 assistant 消息落库
7. 发 `assistant_done`

前端最常见收到的事件顺序是：

```text
user_message
assistant_start
assistant_delta
assistant_delta
assistant_delta
assistant_done
```

如果中间抛异常，路由层会兜底转成：

```text
error
```

### 6.2 为什么这里一定要用 `yield`

因为 SSE 本质上就是 HTTP 长连接上的分段返回。

FastAPI 的 `StreamingResponse` 需要拿到一个可迭代对象，后端每 `yield` 一次，框架就会往客户端推一段 `text/event-stream` 文本。

所以这里的 `yield` 解决的是“怎么把内容一段一段发给浏览器”，不是 LangGraph 专属能力，而是 Python 生成器配合 HTTP 流式响应的基本实现方式。

一句话说：

- `yield` 是传输层需要
- `graph.stream()` 是工作流执行层的可选能力

两者不是一回事。

### 6.3 为什么当前实现没有直接走 `graph.stream()`

因为这条流式链路实际上没有走 LangGraph runtime，而是手写了一套更贴近前端协议的流式编排。

同步接口 `invoke()` 走的是：

- `build_graph(...)`
- `graph.invoke(...)`

但流式接口 `stream_invoke()` 走的是：

- 先查历史消息
- 再做 `classify_intent`
- 然后按 `generate_xml / general_chat / rag_retrieval` 三种分支分别处理
- 每拿到一段结果就直接 `yield {"event": ..., "data": ...}`

这么做的原因很实际：前端真正关心的不是图里哪个 node 执行完了，而是下面这些稳定事件：

- `user_message`
- `assistant_start`
- `assistant_delta`
- `assistant_done`
- `error`

如果改成 `graph.stream()`，也不是不能做，但你最终还是要在外面再包一层，把 LangGraph 的流式状态更新翻译成上述 SSE 事件，然后继续 `yield` 给 `StreamingResponse`。所以就算用了 `graph.stream()`，最外层的 `yield` 也不会消失。

### 6.4 三种意图分支分别怎么流

`stream_invoke()` 里先统一做两件事：

- 读取最近历史消息，供多轮对话和摘要使用
- `classify_intent(query)` 判定意图

然后固定先发一条：

- `assistant_start`

后面分三支。

`generate_xml`：

- 直接返回占位文案
- 通常只会发一条完整的 `assistant_delta`
- 然后落库 assistant 消息
- 最后发 `assistant_done`

`general_chat`：

- 如果模型没配置，直接降级成一条完整 `assistant_delta`
- 如果模型已配置，就调用 OpenAI 的流式接口
- 每拿到一个 chunk，就转成一条 `assistant_delta`
- 所有 chunk 拼完后，再统一落库
- 最后发 `assistant_done`

`rag_retrieval`：

- 先同步执行文档检索
- 如果检索为空，直接返回一条完整 `assistant_delta`
- 如果检索不为空但总结模型没配，也直接把检索结果整段返回
- 如果总结模型已配置，就基于 snippets 和 related_files 做流式摘要
- 摘要的每个 chunk 都会转成 `assistant_delta`
- 最终统一落库并发 `assistant_done`

这里一个很关键的点是：

- 检索本身不是流式的
- 真正逐段输出的通常是 chat 生成或 summary 生成

所以前端如果感觉“开始有点慢，后面突然开始打字”，往往是卡在检索阶段，而不是 SSE 没生效。

### 6.5 `assistant_done` 为什么重要

很多人只盯着 `assistant_delta`，但真正稳定的数据落点其实是 `assistant_done`。

原因是 assistant 消息不是一开始就写库，而是在最终 `response` 组装完成后统一持久化。也就是说：

- `assistant_delta` 主要用于前端临时渲染打字效果
- `assistant_done` 才代表最终消息已经入库成功

而且 `assistant_done.message` 里通常还会带完整的引用信息，比如：

- `snippets`
- `related_files`
- message id
- created_at

所以更稳妥的前端做法是：

- 收到 `assistant_delta` 时更新临时正文
- 收到 `assistant_done` 后，用最终 message 替换临时态

### 6.6 面试里怎么一句话解释这块设计

可以直接说：

> 我们流式接口没有直接复用 LangGraph 的 `graph.stream()`，而是自己在 service 层手写了事件流。原因是前端真正需要的是 `assistant_start / assistant_delta / assistant_done` 这类稳定的业务事件，而不是图执行过程里的内部 state。`yield` 负责把这些事件一段一段推给 `StreamingResponse`，assistant 最终落库后再通过 `assistant_done` 回给前端，确保展示态和持久化态一致。

## 7. 如果面试官问：你写过哪些 tools

这个问题不要硬答成“我做了很多通用 agent 平台工具”，更稳的讲法是：

> 这个项目一开始不是开放式 agent，而是固定 RAG 编排，所以前期我没有为了上 tools 而上 tools。后面我把最贴业务闭环的能力抽成了 3 个 AI/Agent 可调用的业务工具，分别是知识库检索、最近文件列表和文件详情查询。这样既能保持原来的检索主链路稳定，又给 assistant 增加了 function calling 能力。

### 7.1 为什么这个项目前期没直接上 tools

因为第一阶段的目标是先把：

- 文档上传
- 向量化
- 多路召回
- SSE 输出

这些主链路跑通。

这类场景一开始更像“固定流程助手”，而不是“开放式 agent”。如果太早把所有能力都改成 tools，会有几个问题：

- 结果边界变得更难控
- 时延会增加
- 调试链路会更长
- 业务能力还没稳定时，工具抽象容易变形

所以更合理的节奏是：

1. 先把核心 service 边界做清楚
2. 等能力稳定后，再把高价值能力工具化

### 7.2 我在这个项目里落了哪 3 个 tools

`search_knowledge_base`

- 输入：`query`，可选 `top_k`
- 底层直接复用 `AIRagService.retrieve(...)`
- 输出：`snippets + related_files + answer/message`
- 适合回答“根据知识库总结一下理赔流程”“帮我找相关资料”

`list_recent_files`

- 输入：可选 `limit`、`file_type`
- 底层复用上传域查询能力
- 输出：当前用户最近上传的文件列表，以及文件类型、向量状态、时间
- 适合回答“最近上传了什么”“最近有哪些 PDF”

`get_file_detail`

- 输入：`upload_id`
- 底层复用文件详情查询
- 输出：文件元数据、向量化状态、chunk 数、错误信息、向量化时间
- 适合回答“101 号文件现在什么状态”“这个文件能不能检索”

### 7.3 为什么优先做这三个

因为这三个工具正好覆盖了知识库问答里最常见的三类动作：

- 查知识
- 查文件列表
- 查单个文件状态

它们的特点是：

- 都有明确输入输出
- 都已经有稳定 service 可以复用
- 都跟用户的真实问题直接对应
- 改成 tool 后，不需要推翻现有架构

这类工具化不是重新发明系统，而是把已经稳定的业务能力对 agent 开口。

### 7.4 这三个 tools 是怎么接进 assistant 的

我没有额外起一层 HTTP 转发，而是直接在 assistant 内部加了一个本地 tool registry。

整体流程是：

1. 先把 tool schema 以 OpenAI function calling 格式注册
2. assistant 首轮先判断是直接回答，还是发起 `tool_call`
3. 如果模型选择工具，就在本地 dispatcher 执行对应 service
4. 再把 tool result 回填给模型，生成最终自然语言回答
5. 如果走的是知识库检索工具，还会把 `snippets` 和 `related_files` 保留到最终 `AssistantResponse` 里

这里我特意保留了原来的消息持久化和 SSE 协议，所以前端仍然只看：

- `assistant_delta`
- `assistant_done`

不会因为底层引入了 tools 就把前端协议打碎。

### 7.5 面试里一句话怎么讲这个设计

可以直接说：

> 我没有把这个项目一开始就做成开放式 agent，因为当时优先级是先把 RAG 主链路跑稳。等检索、上传、文件状态这些边界稳定后，我把最有业务价值的三类能力抽成了 tools：`search_knowledge_base`、`list_recent_files`、`get_file_detail`。底层直接复用现有 service，assistant 通过 function calling 做工具选择，本地执行后再让模型组织最终回答。这样既保留了原来的稳定性，又把 assistant 往 agent 方向推进了一步。

## 8. 你可以怎么回答“为什么这样设计”

可以直接说：

> 我的目标不是堆功能点，而是让检索质量和系统复杂度保持一个合理平衡。单路向量检索语义能力强，但对术语、文件名、编号这类强字面场景不稳，所以我补了 BM25 和规则召回。BM25 负责关键词和精确术语，规则召回负责确定性补召回，向量召回继续负责语义覆盖。三路统一在 PostgreSQL 单栈里完成，避免引入独立搜索引擎带来的双写和运维成本。最后通过 chunk 级融合和轻量 rerank，把多路命中信息收敛成一份稳定结果。

## 9. 面试官继续追问时可以展开的点

### 如果问：规则召回是不是很土？

可以回答：

规则召回不是为了替代搜索，而是为了解决那些“只要命中就非常有价值”的确定性场景，比如文件名、错误码、接口标识。它本身权重低，而且 bonus 有上限，所以不会污染主排序。

### 如果问：为什么不直接上 reranker 模型？

可以回答：

当然可以，但我这次优先级不是追求最强排序，而是在现有架构里先把三路召回闭环做稳。外部 reranker 会新增模型依赖、延迟和部署复杂度，所以我先做轻量规则重排，把 80% 的收益先拿到。

### 如果问：这个方案后续怎么演进？

可以回答：

后续可以沿三个方向继续增强：

- query rewrite 或多轮上下文改写
- 外部 reranker / cross-encoder
- 从 PostgreSQL 单栈演进到独立检索引擎

但这些都建立在当前三路召回已经把数据域、召回边界、融合结构定义清楚的前提上。

## 10. 这次实战里踩过的坑

这部分很适合当“真实项目经验”讲：

- `pg_search` 不是 Ruby 的 `pg_search` gem，那是另一个生态，真正需要的是 PostgreSQL 扩展
- 本机 PostgreSQL 真实运行目录不一定是 Homebrew 路径，最后要以实际 `data_directory` 和 `config_file` 为准
- 扩展装好了不代表服务可用，还要确认 `CREATE EXTENSION` 成功、BM25 索引真的建起来
- BM25 分数不能直接和向量分硬加，必须先归一化
- 如果做静默降级，问题会非常隐蔽，验收时很容易误判成“多路召回已经上线”

## 11. 最后一句总结

这次多路召回的核心价值，不是“多加了两个搜索通道”，而是把语义、字面、规则三类信号统一到一个可解释、可调参、可落地的检索框架里，而且整个方案是贴着现有代码结构做的，没有为了追求架构理想化去过度设计。
