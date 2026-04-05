# Ant Design Vue Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前前端页面迁移到 `ant-design-vue@4.2.6` 组件体系，并重构为更标准的后台布局，同时保持现有业务逻辑与画布能力不变。

**Architecture:** 在入口注册 Ant Design Vue 与样式，登录页改为认证卡片布局，工作台页改为 `Layout/Sider/Header/Content` 结构，左侧素材区、右侧检查器、上传弹窗与头部操作统一切换为 Ant Design Vue 组件。mxGraph 画布内部逻辑不改，只调整外围容器和工具栏承载方式。

**Tech Stack:** Vue 3, TypeScript, ant-design-vue 4.2.6, @ant-design/icons-vue, rsbuild, mxGraph

---

### Task 1: 接入组件库

**Files:**
- Modify: `package.json`
- Modify: `src/main.ts`

- [ ] 安装 `ant-design-vue@4.2.6` 与 `@ant-design/icons-vue`
- [ ] 在 `src/main.ts` 注册 `Antd` 并引入样式
- [ ] 确认应用可以正常启动和编译

### Task 2: 重做认证页

**Files:**
- Modify: `src/pages/AuthPage.vue`
- Modify: `src/styles/auth.css`

- [ ] 用 `Card`、`Tabs`、`Form`、`Input`、`Button`、`Alert` 重写登录注册页
- [ ] 保留现有登录/注册业务逻辑与错误处理
- [ ] 清理旧认证页样式，保留必要布局样式

### Task 3: 重构工作台骨架

**Files:**
- Modify: `src/pages/CanvasPage.vue`
- Modify: `src/components/AppHeader.vue`
- Modify: `src/styles/workbench.css`

- [ ] 用 `Layout` 重构工作台整体布局
- [ ] 将头部操作改为 Ant Design Vue 按钮、空间布局和状态展示
- [ ] 让画布区域在新布局下保持正确尺寸

### Task 4: 替换左右面板与弹窗

**Files:**
- Modify: `src/components/DocumentRail.vue`
- Modify: `src/components/InspectorPanel.vue`
- Modify: `src/components/UploadModal.vue`
- Modify: `src/components/ArchitectureCanvas.vue`

- [ ] 左侧素材区改成 `Card`、`List`、`Tag`
- [ ] 右侧检查器改成 `Drawer` 或面板式表单
- [ ] 上传改成 `Modal`、`Alert`、`List`
- [ ] 画布工具栏切到 Ant Design Vue 按钮体系

### Task 5: 清理样式并验证

**Files:**
- Modify: `src/styles/base.css`
- Modify: `src/styles/workbench.css`
- Modify: `src/components/ArchitectureCanvas.vue`

- [ ] 移除深色主题默认视觉，切到 AntD 默认浅色基调
- [ ] 删除不再需要的旧按钮/输入/面板样式
- [ ] 清理 `ArchitectureCanvas.vue` 中现有调试日志
- [ ] 运行构建和测试，验证登录、注册、画布保存/加载和上传交互
