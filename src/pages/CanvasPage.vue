<script setup lang="ts">
import { ExclamationCircleOutlined } from '@ant-design/icons-vue';
import { Modal } from 'ant-design-vue';
import { computed, createVNode, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import AiAssistantPopover from '../components/AiAssistantPopover.vue';
import AppHeader from '../components/AppHeader.vue';
import ArchitectureCanvas from '../components/ArchitectureCanvas.vue';
import DocumentRail from '../components/DocumentRail.vue';
import InspectorPanel from '../components/InspectorPanel.vue';
import UploadModal from '../components/UploadModal.vue';
import {
  defaultSelection,
  seedDocument,
  type CanvasSelection
} from '../data/seedDocument';
import { authState, clearAuth } from '../lib/auth';
import { resolveCanvasBootstrapState } from '../lib/canvas-bootstrap';
import { createCanvasNode, fetchCanvas, fetchCanvasNodes, saveCanvas } from '../lib/canvas';
import { toggleTheme, type ThemeMode } from '../lib/theme';
import {
  deleteUploadedFile,
  fetchRecentUploads,
  uploadFile,
  validateUploadFile
} from '../lib/upload';
import type { CanvasSnapshotPayload, CanvasTreeNode } from '../types/canvas';
import type { UploadModalState } from '../types/upload';

const ACTIVE_CANVAS_NODE_KEY = 'active_canvas_node_id';

const emit = defineEmits<{
  (event: 'logout'): void;
}>();
const activeSelection = ref<CanvasSelection>(defaultSelection);
const canvasRef = ref<InstanceType<typeof ArchitectureCanvas> | null>(null);
const theme = ref<ThemeMode>('light');
const inspectorOpen = ref(false);
const aiAssistantOpen = ref(false);
const savingCanvas = ref(false);
const saveStatusText = ref('');
const canvasInitializing = ref(true);
const initialCanvasSnapshot = ref<Pick<CanvasSnapshotPayload, 'xmlContent' | 'nodeInfo'> | null>(null);
const canvasNodes = ref<CanvasTreeNode[]>([]);
const activeNodeId = ref<string | null>(null);
const uploadState = reactive<UploadModalState>({
  open: false,
  uploading: false,
  deletingUploadId: null,
  error: '',
  selectedFile: null,
  successRecord: null,
  recentUploads: []
});

const activeCanvasNode = computed(
  () => canvasNodes.value.find((item) => item.id === activeNodeId.value) ?? null
);

function getActiveNodeStorageKey() {
  return `${ACTIVE_CANVAS_NODE_KEY}:${authState.user?.user_id ?? 'anonymous'}`;
}

function readStoredActiveNodeId() {
  if (typeof window === 'undefined') {
    return null;
  }

  return window.localStorage.getItem(getActiveNodeStorageKey());
}

function persistActiveNodeId(nodeId: string) {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(getActiveNodeStorageKey(), nodeId);
}

function clearStoredActiveNodeId() {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.removeItem(getActiveNodeStorageKey());
}

function handleSelectionChange(selection: CanvasSelection | null) {
  if (!selection) {
    activeSelection.value = defaultSelection;
    inspectorOpen.value = false;
    return;
  }

  activeSelection.value = selection;
}

function handleSelectionUpdate(selection: CanvasSelection) {
  canvasRef.value?.applySelectionDraft(selection);
  void persistCanvasSnapshot('节点修改已保存');
}

function handleToggleTheme() {
  theme.value = toggleTheme(theme.value);
}

function openInspector() {
  inspectorOpen.value = true;
}

function closeInspector() {
  inspectorOpen.value = false;
}

function toggleAiAssistant() {
  aiAssistantOpen.value = !aiAssistantOpen.value;
}

function closeAiAssistant() {
  aiAssistantOpen.value = false;
}

function handleImportFlow(snapshot: CanvasSnapshotPayload) {
  initialCanvasSnapshot.value = {
    xmlContent: snapshot.xmlContent,
    nodeInfo: snapshot.nodeInfo
  };
  canvasRef.value?.loadCanvasSnapshot(initialCanvasSnapshot.value);
  saveStatusText.value = '已导入 AI 生成流程图';
}

async function openUploadModal() {
  uploadState.open = true;
  uploadState.error = '';

  try {
    uploadState.recentUploads = await fetchRecentUploads();
  } catch {
    uploadState.recentUploads = [];
  }
}

function closeUploadModal() {
  uploadState.open = false;
  uploadState.uploading = false;
  uploadState.deletingUploadId = null;
  uploadState.error = '';
  uploadState.selectedFile = null;
  uploadState.successRecord = null;
}

function handleSelectUploadFile(file: File | null) {
  uploadState.selectedFile = file;
  uploadState.successRecord = null;
  uploadState.error = '';
}

async function handleSubmitUpload() {
  if (!uploadState.selectedFile) {
    return;
  }

  const validationError = validateUploadFile(uploadState.selectedFile);
  if (validationError) {
    uploadState.error = validationError;
    return;
  }

  uploadState.uploading = true;
  uploadState.error = '';

  try {
    uploadState.successRecord = await uploadFile(uploadState.selectedFile);
    uploadState.recentUploads = await fetchRecentUploads();
  } catch (error) {
    uploadState.error = error instanceof Error ? error.message : 'Upload failed.';
  } finally {
    uploadState.uploading = false;
  }
}

async function handleDeleteUpload(uploadId: number) {
  if (uploadState.uploading || uploadState.deletingUploadId !== null) {
    return;
  }

  const confirmed = await new Promise<boolean>((resolve) => {
    Modal.confirm({
      title: '确认删除上传记录？',
      content: '删除后会同时清理 OSS、数据库和向量库中的数据。',
      icon: createVNode(ExclamationCircleOutlined),
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => resolve(true),
      onCancel: () => resolve(false)
    });
  });

  if (!confirmed) {
    return;
  }

  uploadState.deletingUploadId = uploadId;
  uploadState.error = '';
  if (uploadState.successRecord?.id === uploadId) {
    uploadState.successRecord = null;
  }

  try {
    await deleteUploadedFile(uploadId);
    uploadState.recentUploads = uploadState.recentUploads.filter((item) => item.id !== uploadId);
  } catch (error) {
    uploadState.error = error instanceof Error ? error.message : '删除失败。';
  } finally {
    uploadState.deletingUploadId = null;
  }
}

function handleLogout() {
  clearAuth();
  emit('logout');
}

async function restoreSavedCanvas() {
  try {
    const nodes = await fetchCanvasNodes();
    canvasNodes.value = nodes;

    if (nodes.length === 0) {
      activeNodeId.value = null;
      initialCanvasSnapshot.value = null;
      clearStoredActiveNodeId();
      saveStatusText.value = '当前账号还没有节点';
      return;
    }

    const storedNodeId = readStoredActiveNodeId();
    const nextNodeId =
      (storedNodeId && nodes.some((item) => item.id === storedNodeId) ? storedNodeId : null) ??
      nodes[0].id;

    await loadCanvasForNode(nextNodeId);
  } catch (error) {
    saveStatusText.value = error instanceof Error ? error.message : '读取画布失败。';
  } finally {
    if (canvasInitializing.value) {
      canvasInitializing.value = false;
      await nextTick();
    }
  }
}

function buildCurrentCanvasSnapshot() {
  return canvasRef.value?.exportCanvasSnapshot(
    activeCanvasNode.value?.name ?? seedDocument.title
  ) as CanvasSnapshotPayload | null;
}

async function persistCanvasSnapshot(successMessage: string) {
  if (!activeNodeId.value) {
    saveStatusText.value = '请先选择节点';
    return;
  }

  const snapshot = buildCurrentCanvasSnapshot();

  if (!snapshot || savingCanvas.value) {
    return;
  }

  savingCanvas.value = true;
  saveStatusText.value = '正在保存画布...';

  try {
    await saveCanvas(activeNodeId.value, snapshot);
    saveStatusText.value = successMessage;
  } catch (error) {
    saveStatusText.value = error instanceof Error ? error.message : '保存画布失败。';
  } finally {
    savingCanvas.value = false;
  }
}

async function handleSaveCanvas() {
  await persistCanvasSnapshot('画布已保存');
}

async function loadCanvasForNode(nodeId: string) {
  canvasInitializing.value = true;
  activeNodeId.value = nodeId;
  persistActiveNodeId(nodeId);
  closeInspector();

  try {
    const canvas = await fetchCanvas(nodeId);
    const bootstrapState = resolveCanvasBootstrapState(canvas);

    initialCanvasSnapshot.value = canvas
      ? {
          xmlContent: canvas.xmlContent,
          nodeInfo: canvas.nodeInfo
        }
      : null;
    saveStatusText.value = bootstrapState.statusText;
  } finally {
    canvasInitializing.value = false;
    await nextTick();
  }
}

function promptNodeName(message: string) {
  const value = window.prompt(message, '');
  if (!value) {
    return null;
  }

  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

async function handleCreateRootNode() {
  const name = promptNodeName('请输入根节点名称');
  if (!name) {
    return;
  }

  try {
    const node = await createCanvasNode({ name });
    canvasNodes.value = [...canvasNodes.value, node];
    await loadCanvasForNode(node.id);
  } catch (error) {
    saveStatusText.value = error instanceof Error ? error.message : '创建节点失败。';
  }
}

async function handleCreateChildNode() {
  if (!activeNodeId.value) {
    saveStatusText.value = '请先选择父节点';
    return;
  }

  const name = promptNodeName('请输入子节点名称');
  if (!name) {
    return;
  }

  try {
    const node = await createCanvasNode({ name, parentId: activeNodeId.value });
    canvasNodes.value = [...canvasNodes.value, node];
    await loadCanvasForNode(node.id);
  } catch (error) {
    saveStatusText.value = error instanceof Error ? error.message : '创建节点失败。';
  }
}

async function handleSelectCanvasNode(nodeId: string) {
  if (!nodeId || nodeId === activeNodeId.value) {
    return;
  }

  try {
    await loadCanvasForNode(nodeId);
  } catch (error) {
    saveStatusText.value = error instanceof Error ? error.message : '切换节点失败。';
  }
}

onMounted(() => {
  document.documentElement.dataset.theme = theme.value;
});

watch(theme, (value) => {
  document.documentElement.dataset.theme = value;
});

function handleWindowKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    closeInspector();
    closeAiAssistant();
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleWindowKeydown);
});

onMounted(() => {
  void restoreSavedCanvas();
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleWindowKeydown);
});
</script>

<template>
  <a-layout class="app-shell">
    <a-layout-header class="app-shell__header">
      <AppHeader
        :ai-assistant-open="aiAssistantOpen"
        :document="seedDocument"
        :saving-canvas="savingCanvas"
        :save-status-text="saveStatusText"
        :theme="theme"
        :user="authState.user"
        @logout="handleLogout"
        @open-upload="openUploadModal"
        @save-canvas="handleSaveCanvas"
        @toggle-ai-assistant="toggleAiAssistant"
        @toggle-theme="handleToggleTheme"
      />
    </a-layout-header>

    <a-layout class="app-shell__body">
      <AiAssistantPopover
        :open="aiAssistantOpen"
        @close="closeAiAssistant"
        @import-flow="handleImportFlow"
      />

      <a-layout-sider width="320" class="app-shell__sider" theme="light">
        <DocumentRail
          :document="seedDocument"
          :nodes="canvasNodes"
          :active-node-id="activeNodeId"
          @create-child-node="handleCreateChildNode"
          @create-root-node="handleCreateRootNode"
          @select-node="handleSelectCanvasNode"
        />
      </a-layout-sider>

      <a-layout-content class="app-shell__content">
        <ArchitectureCanvas
          v-if="!canvasInitializing"
          ref="canvasRef"
          :document-title="activeCanvasNode?.name ?? seedDocument.title"
          :initial-snapshot="initialCanvasSnapshot"
          @close-inspector="closeInspector"
          @open-inspector="openInspector"
          @selection-change="handleSelectionChange"
        />
      </a-layout-content>
    </a-layout>

    <a-drawer
      :open="inspectorOpen"
      title="节点检查器"
      width="360"
      placement="right"
      @close="closeInspector"
    >
      <InspectorPanel
        :selection="activeSelection"
        :saving="savingCanvas"
        @close="closeInspector"
        @update-selection="handleSelectionUpdate"
      />
    </a-drawer>

    <UploadModal
      :open="uploadState.open"
      :uploading="uploadState.uploading"
      :deleting-upload-id="uploadState.deletingUploadId"
      :error="uploadState.error"
      :selected-file="uploadState.selectedFile"
      :success-record="uploadState.successRecord"
      :recent-uploads="uploadState.recentUploads"
      @close="closeUploadModal"
      @delete-upload="handleDeleteUpload"
      @select-file="handleSelectUploadFile"
      @submit="handleSubmitUpload"
    />
  </a-layout>
</template>
