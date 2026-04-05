# 画布保存与用户隔离设计

**目标**

为当前架构画布增加保存与读取能力，持久化 `xml` 和节点 `info`，并继续按 JWT 中的 `user_id` 做完全隔离。

**范围**

- 新增独立画布存储模型与接口，不复用现有 `worker_file`
- 每个用户仅保存一份当前画布，重复保存时覆盖更新
- 前端进入画布页时自动加载当前用户画布
- 前端保存时不传 `user_id`，后端从鉴权上下文获取

**数据设计**

- 表名：`canvas_document`
- 字段：
  - `id`: UUID 主键
  - `user_id`: UUID 字符串，索引
  - `name`: 画布名称
  - `xml_content`: 画布 XML
  - `node_info_json`: 节点信息 JSON 字符串
  - `created_at`: 创建时间
  - `updated_at`: 更新时间

**接口设计**

- `GET /api/canvas`
  - 返回当前登录用户的唯一画布
  - 无数据时返回 `404`
- `POST /api/canvas`
  - 请求体包含 `name`、`xmlContent`、`nodeInfo`
  - 若当前用户已有记录则更新，否则创建

**前端设计**

- `ArchitectureCanvas.vue` 暴露：
  - `exportCanvasSnapshot()`
  - `loadCanvasSnapshot(snapshot)`
- `CanvasPage.vue` 增加：
  - 首次加载当前用户画布
  - 保存按钮与保存状态
- 新增 `src/lib/canvas.ts` 统一处理画布 API

**隔离要求**

- 所有查询、更新仅按 `current_user.user_id` 作用于当前用户数据
- 前端不接触也不缓存其他用户的画布标识

**测试**

- 后端：
  - service 测试覆盖创建、更新、跨用户隔离
  - API 测试覆盖鉴权、保存、读取
- 前端：
  - 画布 API 请求结构测试
  - 快照序列化/反序列化测试
