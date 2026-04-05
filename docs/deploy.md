# 部署说明

本文档覆盖两种部署方式：

- Docker 部署
- 裸机部署

当前项目的数据库、OSS、pgvector 都通过环境变量连接外部服务，因此下面的部署步骤默认只部署 `backend` 服务本身。

## 1. 部署前准备

确保 `backend/.env` 已配置以下关键项：

- `POSTGRES_DATABASE_URL`
- `OSS_REGION`
- `OSS_BUCKET`
- `OSS_ENDPOINT`
- `OSS_ACCESS_KEY_ID`
- `OSS_ACCESS_KEY_SECRET`
- `OSS_PUBLIC_BASE_URL`
- `ARK_API_KEY`
- `ARK_BASE_URL`
- `ARK_EMBEDDING_ENDPOINT_ID`
- `ARK_MULTIMODAL_EMBEDDING_ENDPOINT_ID`
- `DOUBAO_EMBEDDING_BASE_URL`
- `DOUBAO_EMBEDDING_API_KEY`
- `DOUBAO_EMBEDDING_MODEL`
- `DOUBAO_EMBEDDING_DIMENSION`
- `PGVECTOR_TEXT_TABLE`
- `PGVECTOR_IMAGE_TABLE`
- `PGVECTOR_TEXT_VECTOR_DIMENSION`
- `PGVECTOR_IMAGE_VECTOR_DIMENSION`
- `PGVECTOR_DISTANCE_OPERATOR`
- `SMALL_CHUNK_SIZE`
- `SMALL_CHUNK_OVERLAP`
- `LARGE_CHUNK_SIZE`
- `OCR_LANGUAGE`
- `ASSISTANT_ENABLE_BM25`
- `ASSISTANT_ENABLE_RULE_RETRIEVAL`

推荐：

```env
OCR_LANGUAGE=chi_sim+eng
```

如果要启用 AI 助手多路召回，还需要在 `backend/.env` 中补充：

```env
ASSISTANT_ENABLE_BM25=true
ASSISTANT_ENABLE_RULE_RETRIEVAL=true
ASSISTANT_VECTOR_RETRIEVAL_TOP_K=18
ASSISTANT_BM25_RETRIEVAL_TOP_K=18
ASSISTANT_RULE_RETRIEVAL_TOP_K=12
```

## 2. Docker 部署

项目内已提供：

- `backend/Dockerfile`
- `docker-compose.yml`

### 2.1 构建并启动

在项目根目录执行：

```bash
docker compose up -d --build
```

### 2.2 查看日志

```bash
docker compose logs -f backend
```

### 2.3 停止服务

```bash
docker compose down
```

### 2.4 容器内验证 OCR

```bash
docker compose exec backend tesseract --version
docker compose exec backend tesseract --list-langs
docker compose exec backend python -c "import shutil; print(shutil.which('tesseract'))"
```

如果输出中包含 `chi_sim` 和 `eng`，说明 OCR 依赖已经齐全。

## 3. 裸机部署

以下示例以 Ubuntu / Debian 为主；CentOS / Rocky / AlmaLinux 的命令也一并给出。

### 3.1 安装系统依赖

Ubuntu / Debian:

```bash
apt-get update
apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  postgresql-client \
  tesseract-ocr \
  tesseract-ocr-chi-sim \
  tesseract-ocr-eng \
  libgl1 \
  libglib2.0-0
```

CentOS / Rocky / AlmaLinux:

```bash
yum install -y \
  python3 \
  python3-pip \
  postgresql \
  tesseract \
  tesseract-langpack-chi_sim \
  tesseract-langpack-eng
```

### 3.2 安装 Python 依赖

在项目根目录执行：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2.1 初始化 pg_search BM25

如果启用了 `ASSISTANT_ENABLE_BM25=true`，部署前还必须完成 `pg_search` 和 BM25 索引初始化。

数据库前置条件：

- PostgreSQL 17+ 可直接使用 `pg_search`
- PostgreSQL 15/16 需要先安装 `pg_search`，并在 `postgresql.conf` 中配置 `shared_preload_libraries = 'pg_search'`
- 修改 `postgresql.conf` 后必须重启 PostgreSQL
- 需要使用有扩展权限和 DDL 权限的账号执行初始化

执行顺序：

- 先确认数据库已经安装并启用 `pg_search` 扩展
- 再执行 `backend/sql/004_add_pg_search_bm25.sql`
- 最后再启动 `backend`

注意：

- `004_add_pg_search_bm25.sql` 里使用了 `CREATE INDEX CONCURRENTLY`
- 该脚本必须在事务外执行，不能包在事务块里
- 执行时要把 `pgvector_text_table` 变量传成当前真实表名

示例：

```bash
cd backend
psql "$POSTGRES_DATABASE_URL" \
  -v pgvector_text_table="uploaded_file_text_vector" \
  -f sql/004_add_pg_search_bm25.sql
```

### 3.3 启动服务

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如果希望常驻运行，建议再配 `systemd` 或进程管理工具。

### 3.4 验证 OCR

```bash
tesseract --version
tesseract --list-langs
python -c "import shutil; print(shutil.which('tesseract'))"
```

如果系统返回了类似 `/usr/bin/tesseract` 的路径，且语言列表里有 `chi_sim` 和 `eng`，说明 OCR 可用。

## 4. 启动后验证

### 4.1 健康检查

```bash
curl http://127.0.0.1:8000/health
```

预期返回：

```json
{"status":"ok"}
```

### 4.2 上传验证

上传一个 `docx`、`pdf` 或 `png` 文件，确认：

- OSS 中出现文件
- PostgreSQL `uploaded_file` 生成记录
- 文本向量表写入 chunk 向量
- `png` 会额外写入图片向量表
- `vector_status` 最终更新为 `VECTORIZED` 或 `FAILED`

### 4.3 多路召回验证

如果启用了 BM25 和规则召回，启动后还应额外确认：

- 启动日志没有出现 `pg_search extension is required` 或 BM25 索引缺失报错
- AI 检索查询可以同时命中文件名、术语和最近上传文件
- 关闭 `ASSISTANT_ENABLE_BM25` 后服务仍可正常启动

## 5. 关键说明

### 5.1 为什么必须安装 tesseract

`pytesseract` 只是 Python 封装，它会调用系统里的 `tesseract` 可执行程序。

所以无论 Docker 还是裸机，都必须同时满足：

- 安装 Python 包 `pytesseract`
- 安装系统命令 `tesseract`
- 安装对应语言包 `chi_sim`、`eng`

缺一项，图片 OCR 都会失败。

### 5.2 当前部署边界

这份部署文件默认不包含：

- PostgreSQL 容器
- pgvector 扩展
- OSS 服务
- 前端服务

因为当前项目代码已经按外部服务地址连接这些资源。

如果后续要把前端、PostgreSQL、pgvector 一起编排进 `docker-compose`，可以再单独补完整的多服务部署文件。
