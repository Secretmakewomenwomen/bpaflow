# AI 助手多路召回设计

## 背景

当前 AI 助手的 RAG 检索链路已经具备以下基础能力：

- 用户上传文件后，文本内容会被解析、清洗、切块并写入 PostgreSQL
- 文本 chunk 会同步生成 embedding，并写入 pgvector 文本表
- AI 助手可以对查询问题生成 embedding，并基于 pgvector 做单路向量召回
- 检索范围已经按 `user_id` 和 `text_vector_status = 'VECTORIZED'` 做用户隔离与状态过滤

现状问题是召回路径单一，只依赖向量相似度，容易在以下场景漏召回或排序不稳：

- 用户问题包含明确术语、文件名、缩写、错误码、接口名
- 用户要求“最新”“最近”“刚上传”的资料
- 用户明确希望找某一类文件，例如 PDF、图片、架构图、附件

本次要在现有 PostgreSQL + pgvector 架构上，把检索升级为三路召回：

1. 向量召回
2. BM25 召回，使用 `pg_search`
3. 规则召回

同时增加轻量 query 分析、候选融合和规则加权重排，使检索结果更稳。

## 目标

本次交付后，AI 助手在 `rag_retrieval` 场景下应具备以下能力：

- 对同一个 query 同时执行向量召回、BM25 召回和规则召回
- 将三路候选合并、去重、重排后生成统一检索结果
- 继续只返回当前登录用户自己上传且文本向量化成功的资料
- 保持现有 `AssistantResponse`、`AssistantSnippet`、`RelatedFile` 的外部响应结构稳定
- 允许通过配置调节各路召回数量、阈值和融合权重

## 非目标

本次不做以下内容：

- 独立检索引擎，例如 Elasticsearch/OpenSearch
- 外部 reranker 模型或 Cross Encoder 重排
- 图片向量召回接入 AI 助手主检索链路
- 查询改写、多轮上下文查询扩展、复杂意图分类升级
- 面向前端暴露详细召回命中原因

## 设计原则

- 优先复用现有表结构和服务边界，不为第一版多路召回引入新基础设施
- 召回与融合逻辑集中在 `AIRagService` 附近，避免把编排散落到 LangGraph 节点
- 第一版以稳定可控为主，规则用于补强，不允许单一路径完全压制其他路径
- 三路召回命中后统一映射到同一种候选结构，避免后续排序逻辑碎片化

## 总体架构

### 检索流程

`rag_retrieval` 的检索流程调整为：

1. `query` 分析
2. 三路召回
3. 候选融合与去重
4. 轻量 rerank
5. 生成 `snippets` 和 `related_files`
6. 若摘要模型可用，则基于重排后的结果生成摘要

其中 LangGraph 主流程保持不变：

- `classify_intent`
- `retrieve_documents`
- `synthesize_answer`
- `build_response`

变化只发生在 `retrieve_documents` 内部的 RAG 检索实现。

### 模块边界

保留现有服务拆分，并在现有模块内做增量扩展：

- `backend/app/ai/services/ai_rag_service.py`
  - 负责 query 分析
  - 负责三路召回 orchestration
  - 负责候选融合、规则加权和最终结果构造
- `backend/app/services/pgvector_service.py`
  - 继续负责向量查询
  - 新增 BM25 查询和规则召回所需的数据库查询
- `backend/app/core/database.py`
  - 新增 `pg_search` 就绪检查
  - 新增 BM25 索引初始化
- `backend/app/core/config.py`
  - 新增多路召回相关配置

第一版不新增新的顶层编排服务，不拆独立 `Retriever` 抽象层，避免为当前项目引入不必要的重构成本。

## 数据层设计

### 复用现有 chunk 表

继续复用当前配置中的文本向量表 `settings.pgvector_text_table`，不新增专门的 BM25 存储表。当前默认表名是 `uploaded_file_text_vector`，但本设计中的所有 DDL/SQL 都必须通过 `Settings.pgvector_text_table` 动态解析真实表名。原因如下：

- 当前向量召回已经依赖这张表
- 该表已经具备 chunk 级文本、页码、文件名、chunk 序号等检索所需字段
- 复用同一份数据可以避免双写和一致性问题

`settings.pgvector_text_table` 与 `uploaded_file` 的关系固定为：

- `<pgvector_text_table>.file_id = uploaded_file.id`
- `uploaded_file_text_vector` 不存 `user_id`
- 用户隔离、向量化状态过滤、文件新近性判断都必须通过 `JOIN uploaded_file` 完成

表中的以下字段会继续作为检索核心字段：

- `file_id`
- `file_name`
- `file_ext`
- `mime_type`
- `page_start`
- `page_end`
- `small_chunk_index`
- `large_chunk_id`
- `small_chunk_text`
- `large_chunk_text`
- `source_type`
- `created_at`
- `embedding`

### 选型与版本

本次 BM25 选型固定为 ParadeDB 的 PostgreSQL 扩展 `pg_search`，不使用 PostgreSQL 原生全文检索替代，也不引入独立搜索服务。

实现边界固定如下：

- 目标扩展：`pg_search`
- 实现策略：按本地实际安装版本实现，不做多版本兼容分支
- 目标查询模型：ParadeDB BM25
- 目标数据库：PostgreSQL 15+
- 首选运行环境：PostgreSQL 17+

原因如下：

- `pg_search` 提供表内 BM25 索引、`pdb.score(...)` 打分和与 `pgvector` 共存的能力
- PostgreSQL 17+ 下不需要为 `pg_search` 额外配置 `shared_preload_libraries`
- PostgreSQL 15/16 也可支持，但需要由部署侧修改 `postgresql.conf` 并重启数据库

安装完成后，先读取数据库中的实际 `pg_search` 版本，再按该版本落最终 SQL。第一版交付范围不包含“版本探测后自动切换多套语法”，而是固定为“锁定当前安装版本并围绕该版本实现”。

当前规划按 v2 风格语法设计，核心 DDL 形态如下：

```sql
CREATE INDEX uploaded_file_text_vector_bm25_idx
ON <pgvector_text_table>
USING bm25 (
  id,
  file_id,
  file_name,
  small_chunk_index,
  created_at,
  small_chunk_text
)
WITH (key_field = 'id');
```

其中：

- `id` 是 chunk 表主键，满足 `pg_search` 对 `key_field` 唯一且排在首列的要求
- `file_name` 和 `small_chunk_text` 参与 BM25 检索
- `file_id`、`small_chunk_index`、`created_at` 一并纳入 BM25 覆盖索引，便于过滤、排序和结果构造

### pg_search 扩展

数据库层新增 `pg_search` 扩展依赖。部署和应用的职责边界固定如下：

- 部署/安装步骤负责：
  - 安装 `pg_search` 二进制
  - PostgreSQL 15/16 下配置 `shared_preload_libraries = 'pg_search'`
  - 重启 PostgreSQL
  - 以具备扩展权限的账号执行 `CREATE EXTENSION IF NOT EXISTS pg_search`
  - 以具备 DDL 权限的账号执行 BM25 索引创建脚本
- 应用启动负责：
  - 校验 `pg_search` 扩展已经存在
  - 校验 BM25 索引已经存在
  - 在配置要求启用 BM25 时，对缺失扩展直接启动失败

应用启动不负责安装二进制，也不负责修改 `postgresql.conf`。

当前项目不引入新的迁移框架。BM25 相关数据库变更统一通过 `backend/sql/003_add_pg_search_bm25.sql` 手工执行。

安装与启用失败时，应用应明确暴露数据库初始化错误，不允许静默退化为“看似有 BM25，实际没生效”的状态。

### BM25 索引设计

BM25 第一版直接建在 `settings.pgvector_text_table` 上，索引字段包括：

- `small_chunk_text`，作为主全文字段
- `file_name`，作为高权重字段

索引目标是让以下场景得到更稳定的字面命中：

- 文件名、标题、缩写、英文标识符
- 精确术语、接口名、错误码、版本号
- 向量语义相近但字面相关性更强的 query

核心查询形态固定为：

```sql
SELECT
  vectors.file_id,
  vectors.file_name,
  vectors.mime_type,
  vectors.created_at,
  vectors.small_chunk_index,
  vectors.small_chunk_text,
  vectors.page_start,
  vectors.page_end,
  pdb.score(vectors.id) AS bm25_score
FROM <pgvector_text_table> AS vectors
JOIN uploaded_file AS uf ON uf.id = vectors.file_id
WHERE (
  vectors.small_chunk_text ||| :query
  OR vectors.file_name ||| :query::pdb.boost(2)
)
  AND uf.user_id = :user_id
  AND uf.text_vector_status = 'VECTORIZED'
ORDER BY pdb.score(vectors.id) DESC, uf.id DESC, vectors.small_chunk_index ASC
LIMIT :top_k;
```

第一版把 `file_name` 查询权重提高到 `small_chunk_text` 之上，以增强文件名、标题、缩写命中能力。最终使用的索引名固定为：

- `idx_<pgvector_text_table>_bm25`

应用启动时按这个命名规则检查索引是否存在，不做模糊发现。

### 过滤范围

三路召回统一维持当前数据域限制：

- `uploaded_file.user_id = :user_id`
- `uploaded_file.text_vector_status = 'VECTORIZED'`

任何召回方式都不允许绕过用户隔离和向量化状态过滤。由于这些字段位于 `uploaded_file`，因此：

- 向量召回 SQL 必须 `JOIN uploaded_file`
- BM25 查询 SQL 必须 `JOIN uploaded_file`
- 规则召回查文件名、新近性和类型时也必须以 `uploaded_file` 作为过滤主表

## Query 分析设计

### 目标

在不引入 LLM query rewrite 的前提下，对用户 query 做轻量结构化分析，为三路召回和重排提供稳定特征。

### 产出结构

建议在 `AIRagService` 内部新增轻量数据结构 `QueryFeatures`，至少包含：

- `normalized_query`
- `keywords`
- `identifier_tokens`
- `wants_recent`
- `requested_file_types`
- `wants_image`
- `wants_pdf`
- `wants_document`

### 分析规则

第一版规则如下：

- 对中文和英文 query 做基础规范化
- 保留英文 token、数字串、下划线/中划线标识符，用于文件名命中和术语命中
- 命中“最新、最近、刚上传、新增”时，置 `wants_recent = True`
- 命中“pdf、图片、架构图、文档、附件”等词时，记录目标文件类型偏好

query 分析不做业务词典扩展，不依赖外部服务。

## 三路召回设计

### 1. 向量召回

沿用现有 `EmbeddingService + PgVectorService` 链路：

- 使用现有 embedding 模型和归一化逻辑生成 query embedding
- 在文本向量表中按余弦距离升序检索
- 返回 chunk 级命中结果

为给融合和重排留下空间，向量召回候选数不再等于最终返回数。第一版建议：

- `vector_top_k = final_top_k * 3`

向量分仍基于当前公式：

- `vector_score = clamp(1 - cosine_distance, 0, 1)`

同时保留最低相似度阈值，避免过低语义相关度的片段混入最终候选集。

### 2. BM25 召回

新增 `pg_search` 查询分支：

- 查询对象仍为 chunk 级文本
- `small_chunk_text` 提供主文本匹配
- `file_name` 提供更强的字面提示能力
- 返回原始 BM25 分值以及命中的 chunk 信息

第一版 BM25 召回同样取放大量候选，建议：

- `bm25_top_k = final_top_k * 3`

如果 query 为空、纯噪声或无法形成有效搜索条件，则 BM25 召回返回空集合。

### 3. 规则召回

规则召回第一版只覆盖以下三类规则。

#### 文件名/标题命中

当 query 中出现以下 token 时，规则召回应优先命中与文件名字面相关的文件：

- 英文 token
- 数字串
- 下划线/中划线标识符
- 明显的文件标题片段

文件名命中是第一版规则召回里唯一负责“补候选”的规则，生成候选的固定策略如下：

- Python 侧先对 query 做小写规范化和 token 提取，不做 `NFKC`
- 仅使用满足以下条件的 token 参与文件名匹配：
  - ASCII token 长度 `>= 2`
  - 中文词片段长度 `>= 2`
- 匹配方式固定为“大小写不敏感的子串包含”，SQL 层使用 `LOWER(file_name) LIKE %token%` 语义实现，不引入 `pg_trgm`、正则或额外索引
- 命中阈值固定为“至少 1 个有效 token 命中文件名”
- 先按文件名命中筛出文件
- 文件按 `uploaded_file.created_at DESC, uploaded_file.id DESC` 排序
- 每个命中文件固定补充 `rule_chunks_per_file` 个 chunk
- chunk 选择规则固定为 `small_chunk_index ASC`
- 规则召回总候选数受 `assistant_rule_retrieval_top_k` 截断

这样设计的原因是可预测、可测试，且不额外依赖向量或 BM25 结果。

#### 新近性规则

当 `wants_recent = True` 时，对最近上传的文件做加权。第一版不单独补 chunk，只对已有候选做分值补强。

“最近”的定义通过配置控制，例如：

- 最近 3 天
- 最近 7 天

#### 类型规则

当 query 明确提到某一类文件时，对对应文件类型做加权。第一版不单独补 chunk，只对已有候选做分值补强。类型判断只使用以下数据来源：

- `settings.pgvector_text_table.file_ext`
- `settings.pgvector_text_table.mime_type`
- `uploaded_file.file_name`

第一版优先支持：

- `pdf`
- `png` / 图片 / 架构图
- 通用文档 / 附件

类型规则以 `mime_type`、`file_ext`、文件名词面为基础判断，不新增额外标签体系。

## 候选模型与融合设计

### 统一候选结构

三路召回结果统一映射为内部候选结构 `RetrievedCandidate`，建议字段包括：

- `file_id`
- `file_name`
- `mime_type`
- `created_at`
- `small_chunk_index`
- `text`
- `page_start`
- `page_end`
- `vector_score`
- `bm25_score`
- `rule_score`
- `final_score`
- `hit_reasons`

`hit_reasons` 仅用于日志、调试和内部排序解释，不进入对外 API 结构。

### 去重键

chunk 级去重键固定为：

- `file_id + small_chunk_index`

同一 chunk 被多路命中时：

- 合并命中原因
- 合并各路分值
- 保留最高可信的元数据

### 分数归一化

三路分数量纲不同，因此在融合前需要统一归一化：

- 向量分已在 `0~1`
- BM25 分对当前 BM25 结果集做 min-max 归一化
- 规则分直接定义在 `0~1`

若某一路结果只有单个候选，归一化后按 `1.0` 处理，避免被异常压低。若某一路所有分数相等、全为 `0` 或缺失，则该路所有候选统一按 `0.0` 处理，不制造伪差异。

### 初始融合公式

第一版采用可配置的加权求和公式：

`final_score = vector_weight * vector_score + bm25_weight * bm25_score + rule_weight * rule_score + bonuses`

推荐默认权重：

- `vector_weight = 0.45`
- `bm25_weight = 0.40`
- `rule_weight = 0.15`

若显式配置了 `assistant_vector_retrieval_top_k`、`assistant_bm25_retrieval_top_k`、`assistant_rule_retrieval_top_k`，则以配置值为准；文档中的 `final_top_k * 3` 仅作为默认建议，不构成硬编码要求。

其中规则分的来源固定为：

- 文件名命中召回产生的 `rule_recall_score`
- 新近性 bonus
- 类型匹配 bonus

也就是说，规则路径内部同时包含“补候选”和“补分”两类能力，但只有文件名命中会主动补候选。

### 规则 bonus

在基础权重之外，增加有限度的 bonus：

- 文件名精确命中：`+0.12`
- query 中明确术语在 chunk 文本命中：`+0.08`
- 新近性意图且文件较新：`+0.05`
- 类型偏好命中：`+0.05`

bonus 的作用是补强排序，而不是替代主召回分。第一版总 bonus 建议做上限截断，避免规则把结果完全拉偏。

## 最终结果构造

### snippets

最终 `snippets` 由重排后的 chunk 候选构造：

- 按 `final_score` 降序排序
- 若分数相同，则按 `uploaded_file.created_at DESC, file_id DESC, small_chunk_index ASC` 稳定打破并列
- 按配置截断最终返回数量
- `text` 仍返回 `small_chunk_text`
- `score` 对外统一返回 `final_score`
- 对外响应中的 `upload_id` 字段继续映射自内部 `file_id`

### related_files

`related_files` 的生成规则保持稳定：

- 按文件聚合
- 每个文件只保留一次
- 文件分取该文件下最高 `final_score` 的 chunk 分
- 按文件分降序截断
- 聚合键固定为内部 `file_id`，对外仍输出 `upload_id`

新近性判断使用 `uploaded_file.created_at`，不使用 chunk 表 `created_at`。chunk 表 `created_at` 只用于构造 BM25 索引覆盖字段，不参与“最新资料”语义判断。

### 摘要上下文

AI 摘要生成继续基于检索结果做，但上下文选择调整为：

- 优先使用重排后的高分 `snippets`
- 继续受 `assistant_max_context_blocks` 限制

第一版不把多路召回命中原因拼到 LLM 上下文中，避免无谓增加噪声。

## 配置设计

建议在 `Settings` 中新增以下配置项：

- `assistant_enable_bm25`
- `assistant_enable_rule_retrieval`
- `assistant_vector_retrieval_top_k`
- `assistant_bm25_retrieval_top_k`
- `assistant_rule_retrieval_top_k`
- `assistant_rule_chunks_per_file`
- `assistant_min_similarity_score`
- `assistant_vector_weight`
- `assistant_bm25_weight`
- `assistant_rule_weight`
- `assistant_bonus_file_name_exact`
- `assistant_bonus_term_hit`
- `assistant_bonus_recent`
- `assistant_bonus_type_match`
- `assistant_recent_window_days`

同时保留现有：

- `assistant_retrieval_top_k`
- `assistant_max_context_blocks`
- `assistant_max_related_files`

`assistant_retrieval_top_k` 用作最终返回数，三路各自候选数单独配置。

BM25 的启用判定固定为：

- `assistant_enable_bm25 = true` 时，应用启动必须校验 `pg_search` 已安装可用
- `assistant_enable_bm25 = false` 时，跳过 BM25 初始化与查询

规则召回同理：

- `assistant_enable_rule_retrieval = true` 时启用规则召回
- `assistant_enable_rule_retrieval = false` 时仅保留向量和 BM25

## 代码改造范围

### backend/app/ai/services/ai_rag_service.py

新增或调整以下职责：

- `retrieve()` 改造成三路召回总入口
- `_analyze_query()`
- `_retrieve_vector_candidates()`
- `_retrieve_bm25_candidates()`
- `_retrieve_rule_candidates()`
- `_merge_candidates()`
- `_rerank_candidates()`
- `_build_response_from_candidates()`

### backend/app/services/pgvector_service.py

新增数据库查询能力：

- BM25 查询
- 文件名命中查询
- 规则召回辅助查询

若单文件职责开始变重，允许拆出 `pg_search_service.py`，但第一版默认不强制拆分。

### backend/app/core/database.py

新增：

- `ensure_pg_search_ready()`
- BM25 索引初始化逻辑

其中 `ensure_pg_search_ready()` 只做以下两件事：

- 验证数据库中已存在 `pg_search`
- 在 BM25 开关开启时校验索引已经存在

它不负责安装系统二进制，也不负责修改数据库服务端配置。

### backend/sql/

新增 SQL 脚本用于：

- 由具备权限的数据库账号执行 `CREATE EXTENSION IF NOT EXISTS pg_search`
- 以 `CREATE INDEX CONCURRENTLY` 的方式创建 BM25 索引

生产和已有数据环境下，BM25 索引创建固定放在 SQL 迁移步骤中，不放在应用启动阶段，避免启动阻塞和潜在锁表风险。空库本地环境也复用同一 SQL 脚本，避免出现两套初始化逻辑。

该 SQL 脚本的执行方式固定为：

- 本地开发：手工执行一次
- CI：增加独立步骤执行该脚本
- 生产：发布前由 DBA 或发布脚本执行

由于 `CREATE INDEX CONCURRENTLY` 不能放在事务块中，该脚本必须以非事务方式执行；若索引创建失败，回滚策略为手工 `DROP INDEX CONCURRENTLY IF EXISTS idx_<pgvector_text_table>_bm25` 后重试。

## 错误处理与退化策略

### 安装和初始化

如果 `assistant_enable_bm25 = true` 且数据库未安装 `pg_search`，或 BM25 初始化失败：

- 应用启动直接失败
- 不允许在“配置要求开启 BM25”的情况下静默忽略该能力

### 查询执行

单次请求中，如果某一路召回异常，第一版不建议整体失败。更稳妥的策略是：

- 记录异常日志
- 该路召回返回空结果
- 其他召回路径继续执行

但以下情况例外：

- 向量召回前的 query embedding 生成失败
- 检索主数据源不可用

这两类错误仍视为整体检索失败。

## 验证方案

### 单元测试

新增或补充以下测试：

- query 分析规则测试
- 规则召回命中测试
- 候选融合去重测试
- 分数归一化和加权排序测试

### 集成测试

覆盖以下场景：

- 向量命中但 BM25 不强的 query
- BM25 精确术语命中场景
- “最新文档”场景
- “找 pdf”“找架构图”场景
- 同一 chunk 被多路同时命中的去重场景

### 人工回归

至少准备以下 query 做手工验证：

- 精确术语
- 文件名片段
- 自然语言描述
- 最新资料检索
- 类型限定检索

## 风险与权衡

### pg_search 版本差异

`pg_search` 的安装方式和 DDL 语法与版本相关，必须以实际安装版本为准实现 schema 初始化，不能预设固定语法后再回滚修补。

### 分值尺度不一致

BM25 分、向量分和规则分来自不同路径，若不统一归一化，最终排序会失真。因此归一化和 bonus 上限属于本设计的必要部分，不是可选优化。

### 规则过强导致排序偏置

规则只负责补强，不负责接管主检索。任何 bonus 都必须受上限控制，避免把低质量候选推到前面。

### 性能开销上升

三路召回会增加单次查询开销。第一版通过以下手段控制：

- 各路召回只取有限候选集
- 先数据库过滤，再 Python 层融合
- 不在第一版引入复杂二次排序模型

## 实施建议

实施顺序建议如下：

1. 确认 PostgreSQL 版本并安装 `pg_search`
2. 增加数据库初始化与 BM25 索引
3. 实现 BM25 查询
4. 实现 query 分析和规则召回
5. 实现候选融合与重排
6. 补齐测试并做手工回归

该顺序的目的是先打通数据库能力，再逐步把多路召回接入现有 RAG 主链路，降低排障成本。
