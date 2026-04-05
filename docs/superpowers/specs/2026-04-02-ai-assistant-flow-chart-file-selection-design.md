# AI 助手流程图文件选择中断设计

## 背景

当前后端已经具备一条确定性的文档转流程图 JSON 能力：

- 上传文件通过 `uploadId` 可定位到用户文件
- `backend/app/services/chapter_flow_service.py` 可以把 `docx` 解析成 `chapter_phase_flow`
- 返回结果同时包含：
  - `flowJson`
  - `graphPayload`

这条能力已经适合“按章节分阶段”的流程图生成，但它还是一个独立解析接口，不在 AI 助手对话流内。

用户的目标不是“手动调用解析接口”，而是：

1. 在 AI 助手输入“根据 xxx 文件生成流程图”
2. 助手识别意图并检索候选文件
3. 命中候选文件后暂停，等待用户选定文件
4. 用户确认后再生成流程图 JSON
5. 生成完成后，前端可选择“导入”或“重新选择文件”

本次设计要把这条能力接入 AI 助手主流程，并采用 human-in-the-loop interrupt，而不是让模型自行规划多步执行。

## 目标

本次改造完成后，AI 助手需要支持以下行为：

- 识别“根据文件生成流程图”类请求
- 在命中意图后检索候选文件
- 命中候选文件后进入 `waiting_input` 状态
- 向前端返回单选文件的 pending action
- 用户确认单个 `uploadId` 后生成流程图 JSON
- 生成完成后在 AI 助手面板展示：
  - `导入`
  - `重新选择文件`
- 前端点击 `导入` 后直接用返回的 `graphPayload` 渲染流程图
- 前端点击 `重新选择文件` 后复用上次候选列表重新打开选择框

## 非目标

本次不做以下内容：

- 多文件合并生成流程图
- 非 `docx` 文件的章节流程图解析
- 真正按岗位/部门分泳道的复杂流程图
- BPMN 式分支条件推理
- `Plan-Execute` agent 编排
- 后端直接生成 `mxGraph XML` 并强制导入画布

## 设计原则

- 采用 human-in-the-loop interrupt，不把文件选择交给模型隐式决策
- 文件选择只支持单选，避免第一版交互和协议复杂化
- AI 助手负责会话状态与动作编排，章节流程图生成仍由确定性 pipeline 执行
- `artifact` 直接返回前端可消费的 `graphPayload`，降低前端导入门槛
- `重新选择文件` 优先复用候选列表，不重新走自然语言输入

## 方案对比

### 方案一：纯工具调用式 ReAct

让模型通过工具自行：

- 找文件
- 选择文件
- 生成流程图

问题在于“选择文件”本质上是前端用户动作，不是模型可以代替完成的步骤。即使模型能发出工具调用，也仍然需要中断等待用户。把这层交互塞进 ReAct 只会让协议更混乱。

### 方案二：Plan-Execute

让后端先规划：

1. 检索候选文件
2. 等待用户选择
3. 生成流程图 JSON
4. 等待导入

这种方式对当前需求来说过重。这里的流程不是自主规划问题，而是显式的 UI 交互步骤。引入 `Plan-Execute` 只会增加状态机复杂度，没有明显收益。

### 方案三：Human-in-the-loop interrupt

助手识别意图后进入 `waiting_input`，返回 pending action 给前端，用户选择单个文件后再恢复执行。

这是本次推荐方案，因为它：

- 与实际交互模型一致
- 明确区分“系统自动做的事”和“必须用户确认的事”
- 可以直接复用现有 AI 助手会话与消息持久化能力
- 可以复用现有 `chapter_flow_service.py`

## 推荐方案

采用 human-in-the-loop interrupt，且文件选择仅支持单选。

总体链路如下：

```text
用户输入“根据 xxx 文件生成流程图”
  -> AI 助手识别意图 generate_flow_from_file
  -> 检索候选文件
  -> 返回 waiting_input + pendingAction(select_file)
  -> 前端弹单选文件框
  -> 用户确认 uploadId
  -> 前端调用 resume
  -> 后端调用 ChapterFlowService 生成 flowJson + graphPayload
  -> AI 助手返回 completed + artifact + actions
  -> 用户点击导入 / 重新选择文件
```

## 交互设计

### 第一步：用户发起请求

用户在 AI 助手输入：

```text
根据保险产品设计与销售流程手册生成流程图
```

后端识别 `intent = generate_flow_from_file`。

### 第二步：助手检索并中断

如果找到候选文件，后端不立即生成流程图，而是返回：

- `status = waiting_input`
- `pendingAction.actionType = select_file`
- `pendingAction.payload.selectionMode = single`
- `pendingAction.payload.candidates = [...]`

前端据此弹出单选文件框。

### 第三步：用户确认文件

用户只能选择一个文件，点击“确定”后，前端调用 `resume`，把该 `uploadId` 传回后端。

### 第四步：生成 artifact

后端恢复执行，调用 `ChapterFlowService.parse_upload(upload_id, user_id)`，生成：

- `flowJson`
- `graphPayload`

### 第五步：前端二次动作

AI 助手完成消息中展示两个按钮：

- `导入`
- `重新选择文件`

其中：

- `导入`：前端直接拿 `graphPayload` 渲染流程图
- `重新选择文件`：前端使用上次返回的候选列表重新打开单选弹窗

## 消息协议

### 中断消息

建议 AI 助手消息结构如下：

```json
{
  "intent": "generate_flow_from_file",
  "status": "waiting_input",
  "content": "我找到了相关文件，请选择一个文件生成流程图。",
  "pendingAction": {
    "actionId": "action-123",
    "actionType": "select_file",
    "payload": {
      "selectionMode": "single",
      "candidates": [
        {
          "uploadId": 101,
          "fileName": "保险产品设计与销售流程手册（标准版）.docx",
          "fileExt": "docx",
          "createdAt": "2026-04-02T10:00:00"
        }
      ]
    }
  },
  "artifact": null,
  "actions": []
}
```

### Resume 请求

```json
{
  "actionId": "action-123",
  "decision": "confirm",
  "payload": {
    "uploadId": 101
  }
}
```

由于第一版只支持单选，不允许传 `uploadIds` 数组。

### 完成消息

```json
{
  "intent": "generate_flow_from_file",
  "status": "completed",
  "content": "流程图 JSON 已生成，你可以导入到画布，或重新选择文件。",
  "pendingAction": null,
  "artifact": {
    "artifactType": "chapter_flow_json",
    "uploadId": 101,
    "flowJson": {
      "documentTitle": "保险产品设计与销售流程手册（标准版）",
      "chapters": []
    },
    "graphPayload": {
      "lanes": [],
      "edges": []
    }
  },
  "actions": [
    { "id": "import", "label": "导入" },
    { "id": "reselect", "label": "重新选择文件" }
  ]
}
```

## 后端架构

### AI 助手主入口

继续复用：

- `backend/app/ai/services/langgraph_assistant.py`

不新增第二套顶层 agent 服务。

### 文件候选检索

第一版优先复用现有上传文件能力与 RAG 检索能力：

- 候选文件来源可以是：
  - 文件名匹配
  - 最近上传文件
  - AI 助手已有文件检索链路的结果

这一层的目标不是做复杂排序，而是给出可选候选集。

### 流程图 JSON 生成

文件确认后，统一调用：

- `backend/app/services/chapter_flow_service.py`

该服务负责：

- 按 `uploadId` 拉取 `docx`
- 解析成 `chapter_phase_flow`
- 返回 `flowJson + graphPayload`

### 画布导入

第一版不把“导入”做成后端动作。

前端直接使用 `artifact.graphPayload` 渲染图即可。如后续需要保存进画布，再单独调用现有 `CanvasService` 保存。

## 状态设计

建议在 AI 助手会话状态中新增或持久化以下信息：

- `intent`
- `status`
- `pendingAction`
- `candidateFiles`
- `selectedUploadId`
- `artifact`

其中：

- `candidateFiles` 用于 `重新选择文件`
- `selectedUploadId` 用于记录当前已确认文件
- `artifact` 用于前端点击 `导入` 时直接消费

第一版推荐状态枚举：

- `waiting_input`
- `processing`
- `completed`
- `failed`

## 前端行为设计

### 选择文件弹窗

- 单选
- 只展示候选文件列表
- 提供“确定 / 取消”

### 助手消息动作

收到 `completed + artifact` 后，AI 助手消息区域展示：

- `导入`
- `重新选择文件`

### 导入

点击 `导入`：

- 直接把 `artifact.graphPayload` 传给画布渲染层
- 不再请求后端二次转换

### 重新选择文件

点击 `重新选择文件`：

- 复用上一轮 `candidateFiles`
- 再次弹出单选文件框
- 用户重新确认后重新调用 `resume`

## 错误处理

### 未找到候选文件

如果检索不到候选文件，AI 助手不进入 `waiting_input`，而是直接返回失败提示，例如：

```text
我没有找到可用于生成流程图的相关文件，请先上传 docx 文件，或换一个文件名描述。
```

### 用户选择了非 docx 文件

如果候选集中混入非 `docx` 文件，后端在 resume 后统一拒绝，返回明确错误：

```text
当前仅支持 DOCX 章节流程解析。
```

### 解析失败

如果 `ChapterFlowService` 解析失败，返回：

- `status = failed`
- 明确错误提示
- 保留 `重新选择文件` 动作

## 测试设计

后续实现需要覆盖以下测试：

- 意图命中后返回 `waiting_input + select_file`
- 候选文件列表只允许单选
- resume 仅接受单个 `uploadId`
- 选中文件后成功生成 `chapter_flow_json`
- 生成完成消息包含 `导入 / 重新选择文件`
- `重新选择文件` 可以复用上次候选集
- 非 `docx` 文件被拒绝
- 未找到文件时直接返回失败消息

## 实施顺序

建议按以下顺序实施：

1. 扩展 AI 助手消息 schema，支持 `pendingAction / artifact / actions`
2. 在 AI 助手主链路中新增 `generate_flow_from_file` 意图
3. 增加文件候选检索与 `waiting_input` 返回
4. 增加 `resume` 接口与单选文件协议
5. 接入 `ChapterFlowService`
6. 前端实现单选文件弹窗
7. 前端接入 `导入 / 重新选择文件`

## 结论

第一版采用 human-in-the-loop interrupt 是合适的。

原因是：

- 文件选择是显式用户动作，不适合交给模型隐式完成
- `Plan-Execute` 对当前需求过重
- 现有 `chapter_flow_service.py` 已经足够承担“文件确认后生成流程图 JSON”的执行职责

因此，推荐架构是：

- AI 助手负责意图识别、状态切换和中断恢复
- 文件确认后走确定性章节流程图生成 pipeline
- 前端负责导入和重新选择文件动作
