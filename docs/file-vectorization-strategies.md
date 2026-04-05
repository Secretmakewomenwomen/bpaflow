# 文件向量化策略

本文档记录当前版本对 `docx`、`pdf`、`png` 三种文件的向量化策略。上传成功只表示文件已经完成 `OSS 存储 + 原信息入库`，向量化在后台异步执行。

## 通用流程

文件上传后统一进入后台任务，但会按文件类型进入不同通道：

1. 解析文件内容
2. 数据清洗
3. 文本通道切块
4. 文本通道 embedding
5. 图片通道 embedding
6. 按通道写入 Milvus
7. 更新 MySQL 中的通道状态和聚合状态

其中：

- 文本小块用于 RAG 检索召回
- 文本大块用于后续返回给大模型做生成
- `png` 除了 OCR 文本通道，还会额外进入图片语义通道

## 通用清洗规则

文本通道在切块前都会进行统一清洗：

- 去除分页符，例如 `\f`
- 去除 HTML 标签并展开 HTML 结构
- 统一空白字符和换行
- 对分页内容尝试删除重复页眉和页脚
- 删除空段和近似空段

这样做的目标是减少布局噪音、重复文案、标签结构和扫描脏文本对 embedding 的干扰。

## `docx` 策略

### 解析方式

- 使用 `python-docx`
- 按文档顺序提取正文段落
- 同时提取表格内容
- 表格按“每行一个语义段”处理
- 行内做轻量去重，避免合并单元格导致文本重复

### 向量通道

- 只进入文本通道
- 不进入图片通道

### 切块方式

- 先做清洗
- 再按固定大小生成小块
- 将相邻小块归并成大块

### 写入 Milvus 文本库的元信息

- `file_id`
- `file_name`
- `file_ext`
- `mime_type`
- `small_chunk_index`
- `large_chunk_id`
- `small_chunk_text`
- `large_chunk_text`
- `source_type=docx` 或 `docx_table`

### 当前限制

- 暂未解析批注、页眉页脚部件、文本框
- 当前重点是正文段落和表格正文

## `pdf` 策略

### 解析方式

- 优先使用 `pypdf`
- 按页提取文本
- 保留 `page_start` 和 `page_end`
- 对没有文本层的页，使用 OCR 兜底

### 清洗重点

- 去掉页间分页符
- 去掉重复页眉和页脚
- 合并页内多余换行和空白
- 如果提取结果里带 HTML 结构，同样会被转成纯文本

### 向量通道

- 只进入文本通道
- 不进入图片通道

### 切块方式

- 页级文本清洗后进入统一切块器
- 先生成小块
- 再把连续小块拼成大块
- 小块会保留来源页码范围

### 写入 Milvus 文本库的元信息

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
- `source_type=pdf_text` 或 `pdf_ocr`

### 当前限制

- OCR 质量依赖 `pytesseract`
- 对极复杂版式仍可能需要进一步结构化抽取

## `png` 策略

`png` 当前是双通道。

### 文本通道

- 使用 `Pillow` 读取图片
- 使用 `pytesseract` 做 OCR
- OCR 输出文本后进入统一清洗流程
- 再做小块/大块切分
- 文本小块进入 Milvus 文本库

### 图片通道

- 不依赖 OSS 公网 URL
- 直接把图片字节转成 `data URL`
- 调用 ARK `multimodal_embeddings.create(...)`
- 生成图片语义向量后写入 Milvus 图片库

### 写入 Milvus 文本库的元信息

- `file_id`
- `file_name`
- `file_ext`
- `mime_type`
- `page_start=1`
- `page_end=1`
- `small_chunk_index`
- `large_chunk_id`
- `small_chunk_text`
- `large_chunk_text`
- `source_type=ocr`

### 写入 Milvus 图片库的元信息

- `file_id`
- `file_name`
- `file_ext`
- `mime_type`
- `image_index`
- `source_type=image`

### 当前限制

- OCR 质量依赖 `pytesseract` 和本机语言包
- 复杂图表、流程图中的空间结构暂未保留成显式关系
- 图片通道当前是一张图一个向量，还没有做区域级切分

## 小块 / 大块策略

当前实现是双层切块，仅用于文本通道：

- 小块：固定大小 + overlap，用于向量检索
- 大块：由相邻小块拼接，用于返回给大模型

每条文本小块向量都会保留自己的 `large_chunk_id` 和 `large_chunk_text`，方便后续检索命中后直接扩展上下文。

## Milvus 存储策略

当前使用两个 collection：

### 文本库

用于：

- `docx`
- `pdf`
- `png OCR`

索引策略：

- `index_type=HNSW`
- `metric_type=COSINE`
- `M=16`
- `efConstruction=200`

### 图片库

用于：

- `png` 图片语义向量

索引策略同样为 HNSW，但维度可与文本库独立配置。

同一个文件重新向量化时，会先删除该 `file_id` 的旧向量，再写入新结果。

## 状态流转

MySQL 中的 `uploaded_file` 会记录聚合状态和通道状态。

### 聚合状态

- `PENDING`
- `PROCESSING`
- `VECTORIZED`
- `FAILED`

### 通道状态

- `text_vector_status`
- `image_vector_status`

规则：

- `docx` / `pdf`：聚合状态跟随文本通道
- `png`：文本和图片通道都成功才算 `VECTORIZED`
- `png`：任一通道失败即聚合为 `FAILED`

失败时会把错误摘要写入：

- `vector_error`
- `text_vector_error`
- `image_vector_error`

这样上传成功状态不会被回滚，但可以明确看到是哪条通道失败。
