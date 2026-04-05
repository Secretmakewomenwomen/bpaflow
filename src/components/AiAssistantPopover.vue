<script setup lang="ts">
import { computed, nextTick, ref, toRefs, watch } from 'vue';
import {
  clearAiConversation,
  createAiConversation,
  fetchAiConversationMessages,
  fetchLatestAiConversation,
  resumeAiConversationMessage,
  streamAiConversationMessage
} from '../lib/ai';
import { getCurrentUser } from '../lib/auth';
import { buildCanvasSnapshotFromChapterFlow } from '../lib/chapter-flow-import';
import type {
  AiAssistantDebugEvent,
  AiAssistantReasoningStep,
  AiConversationMessage,
  AiConversationMessageReference,
  AiPendingActionCandidate
} from '../types/ai';
import type { CanvasSnapshotPayload } from '../types/canvas';

const props = defineProps<{
  open: boolean;
}>();
const { open } = toRefs(props);

const emit = defineEmits<{
  (event: 'close'): void;
  (event: 'import-flow', snapshot: CanvasSnapshotPayload): void;
}>();

const AI_ASSISTANT_CONVERSATION_KEY = 'ai_assistant_conversation_id';
const conversationId = ref('');
const conversationLoaded = ref(false);
const question = ref('');
const loadingConversation = ref(false);
const clearing = ref(false);
const sending = ref(false);
const error = ref('');
const messages = ref<AiConversationMessage[]>([]);
const assistantDebugEvents = ref<AiAssistantDebugEvent[]>([]);
const assistantReasoningSteps = ref<AiAssistantReasoningStep[]>([]);
const activeAssistantMessageId = ref('');
const expandedReasoningMessageIds = ref<string[]>([]);
const selectedUploadId = ref<number | null>(null);
const selectingFile = ref(false);
const fileSelectionActionId = ref('');
const fileSelectionCandidates = ref<AiPendingActionCandidate[]>([]);
const messagesContainer = ref<HTMLElement | null>(null);
const suggestedQuestions = [
  '梳理当前流程节点之间的审批关系',
  '查找与理赔审核相关的制度文件',
  '汇总上传资料里和归档规则有关的内容'
];

const canSubmit = computed(
  () => question.value.trim().length > 0 && !sending.value && !loadingConversation.value && !clearing.value
);
const activeArtifactMessage = computed(() => {
  for (const message of [...messages.value].reverse()) {
    if (message.role !== 'assistant' || !message.artifact || !message.actions?.length) {
      continue;
    }
    return message;
  }
  return null;
});
const hasVisibleFileSelection = computed(
  () => fileSelectionCandidates.value.length > 0 && fileSelectionActionId.value.length > 0
);
const activeAssistantLoadingState = computed(() => {
  if (!sending.value || !assistantDebugEvents.value.length) {
    return null;
  }

  const latestEvent = assistantDebugEvents.value.at(-1);
  if (!latestEvent) {
    return null;
  }

  if (latestEvent.stage === 'tool_result') {
    return {
      title: '正在生成回答',
      description: `${latestEvent.tool_name} 已返回结果，正在整理答案。`
    };
  }

  if (latestEvent.stage === 'tool_start') {
    return {
      title: '正在调用工具',
      description: `${latestEvent.tool_name} 执行中，请稍候。`
    };
  }

  return {
    title: '正在处理请求',
    description: '正在整理检索结果并生成回答。'
  };
});

const activeAssistantReasoningSteps = computed(() => {
  if (!sending.value || !activeAssistantMessageId.value) {
    return [];
  }
  return assistantReasoningSteps.value;
});

function getConversationStorageKey() {
  const userId = getCurrentUser()?.user_id;
  return userId ? `${AI_ASSISTANT_CONVERSATION_KEY}:${userId}` : AI_ASSISTANT_CONVERSATION_KEY;
}

function readStoredConversationId() {
  if (typeof window === 'undefined') {
    return '';
  }

  return window.localStorage.getItem(getConversationStorageKey()) ?? '';
}

function persistConversationId(value: string) {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(getConversationStorageKey(), value);
}

function clearStoredConversationId() {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.removeItem(getConversationStorageKey());
}

function getErrorStatus(loadError: unknown) {
  if (typeof loadError !== 'object' || loadError === null) {
    return null;
  }

  const status = Reflect.get(loadError, 'status');
  return typeof status === 'number' ? status : null;
}

async function loadConversationMessages(targetConversationId: string) {
  conversationId.value = targetConversationId;
  messages.value = await fetchAiConversationMessages(targetConversationId);
  conversationLoaded.value = true;
  persistConversationId(targetConversationId);
}

function isSnippetReference(reference: AiConversationMessageReference) {
  return reference.reference_type === 'snippet';
}

function isFileReference(reference: AiConversationMessageReference) {
  return reference.reference_type === 'file';
}

function formatReferenceMeta(reference: AiConversationMessageReference) {
  if (reference.reference_type === 'file') {
    return reference.upload_id ? `文件 #${reference.upload_id}` : '相关文件';
  }

  const pageText =
    reference.page_start === null
      ? '未标注页码'
      : reference.page_end !== null && reference.page_end !== reference.page_start
        ? `第 ${reference.page_start}-${reference.page_end} 页`
        : `第 ${reference.page_start} 页`;
  const scoreText = reference.score === null ? '' : ` · 相关度 ${Math.round(reference.score * 100)}%`;
  return `${pageText}${scoreText}`;
}

function extractLatestSelectFileMessage() {
  for (const message of [...messages.value].reverse()) {
    if (
      message.role === 'assistant' &&
      message.pending_action?.action_type === 'select_file'
    ) {
      return message;
    }
  }
  return null;
}

function syncFlowChartUiState() {
  const latestMessage = messages.value.at(-1);
  if (
    latestMessage?.role === 'assistant' &&
    latestMessage.status === 'waiting_input' &&
    latestMessage.pending_action?.action_type === 'select_file'
  ) {
    fileSelectionActionId.value = latestMessage.pending_action.action_id;
    fileSelectionCandidates.value = latestMessage.pending_action.payload.candidates;
    selectedUploadId.value = latestMessage.pending_action.payload.candidates[0]?.upload_id ?? null;
    return;
  }

  if (activeArtifactMessage.value) {
    fileSelectionCandidates.value = [];
    selectedUploadId.value = null;
  }
}

async function scrollToLatestMessage() {
  await nextTick();
  const element = messagesContainer.value;
  if (!element) {
    return;
  }
  element.scrollTop = element.scrollHeight;
}

async function ensureConversationLoaded() {
  if (conversationLoaded.value || loadingConversation.value) {
    return;
  }

  loadingConversation.value = true;
  error.value = '';

  try {
    const storedConversationId = readStoredConversationId();
    if (storedConversationId) {
      try {
        await loadConversationMessages(storedConversationId);
        return;
      } catch (loadError) {
        if (getErrorStatus(loadError) !== 404) {
          throw loadError;
        }

        clearStoredConversationId();
        conversationId.value = '';
        messages.value = [];
      }
    }

    const latestConversation = await fetchLatestAiConversation();
    if (latestConversation) {
      await loadConversationMessages(latestConversation.conversation_id);
      return;
    }

    const conversation = await createAiConversation();
    await loadConversationMessages(conversation.conversation_id);
  } catch (loadError) {
    error.value = loadError instanceof Error ? loadError.message : 'AI 会话初始化失败。';
  } finally {
    loadingConversation.value = false;
  }
}

async function handleClearConversation() {
  if (!conversationId.value || sending.value || loadingConversation.value || clearing.value) {
    return;
  }

  clearing.value = true;
  error.value = '';

  try {
    await clearAiConversation(conversationId.value);
    messages.value = [];
    conversationLoaded.value = false;
    conversationId.value = '';
    clearStoredConversationId();

    const conversation = await createAiConversation();
    await loadConversationMessages(conversation.conversation_id);
  } catch (clearError) {
    error.value = clearError instanceof Error ? clearError.message : '清空历史失败。';
  } finally {
    clearing.value = false;
    await scrollToLatestMessage();
  }
}

async function handleSubmit() {
  const query = question.value.trim();
  if (!query || sending.value || clearing.value || !conversationId.value) {
    return;
  }

  sending.value = true;
  error.value = '';
  const optimisticMessageId = `pending-user-${Date.now()}`;
  const optimisticAssistantId = `pending-assistant-${Date.now()}`;
  let userMessageConfirmed = false;
  assistantDebugEvents.value = [];
  assistantReasoningSteps.value = [];
  activeAssistantMessageId.value = optimisticAssistantId;
  expandedReasoningMessageIds.value = Array.from(new Set([...expandedReasoningMessageIds.value, optimisticAssistantId]));
  messages.value = [
    ...messages.value,
    {
      message_id: optimisticMessageId,
      role: 'user',
      intent: null,
      content: query,
      status: 'completed',
      created_at: new Date().toISOString(),
      references: []
    },
    {
      message_id: optimisticAssistantId,
      role: 'assistant',
      intent: null,
      content: '',
      status: 'streaming',
      created_at: new Date().toISOString(),
      references: []
    }
  ];
  question.value = '';
  await scrollToLatestMessage();

  try {
    await streamAiConversationMessage(conversationId.value, { query }, {
      onUserMessage(message) {
        userMessageConfirmed = true;
        messages.value = messages.value.map((item) =>
          item.message_id === optimisticMessageId ? message : item
        );
      },
      onAssistantStart(payload) {
        messages.value = messages.value.map((item) =>
          item.message_id === optimisticAssistantId
            ? {
                ...item,
                intent: payload.intent ?? item.intent
              }
            : item
        );
      },
      onAssistantDelta(delta) {
        messages.value = messages.value.map((item) =>
          item.message_id === optimisticAssistantId
            ? {
                ...item,
                content: `${item.content}${delta}`
              }
            : item
        );
        void scrollToLatestMessage();
      },
      onAssistantReasoning(step) {
        assistantReasoningSteps.value = [...assistantReasoningSteps.value, step];
      },
      onAssistantDebug(payload) {
        assistantDebugEvents.value = [...assistantDebugEvents.value, payload];
      },
      onAssistantDone(message) {
        activeAssistantMessageId.value = message.message_id;
        expandedReasoningMessageIds.value = Array.from(
          new Set(
            expandedReasoningMessageIds.value.map((id) =>
              id === optimisticAssistantId ? message.message_id : id
            )
          )
        );
        messages.value = messages.value.map((item) =>
          item.message_id === optimisticAssistantId
            ? {
                ...message,
                reasoning_trace:
                  message.reasoning_trace && message.reasoning_trace.length
                    ? message.reasoning_trace
                    : assistantReasoningSteps.value
              }
            : item
        );
        assistantReasoningSteps.value = [];
        syncFlowChartUiState();
      }
    });
  } catch (submitError) {
    messages.value = messages.value
      .filter((message) => userMessageConfirmed || message.message_id !== optimisticMessageId)
      .map((message) =>
        message.message_id === optimisticAssistantId
          ? {
              ...message,
              content: submitError instanceof Error ? submitError.message : 'AI 查询失败。',
              status: 'completed',
              reasoning_trace: assistantReasoningSteps.value
            }
          : message
      );
    if (!userMessageConfirmed) {
      question.value = query;
    }
    error.value = submitError instanceof Error ? submitError.message : 'AI 查询失败。';
  } finally {
    sending.value = false;
    await scrollToLatestMessage();
  }
}

function getMessageReasoningSteps(message: AiConversationMessage) {
  if (message.message_id === activeAssistantMessageId.value && activeAssistantReasoningSteps.value.length) {
    return activeAssistantReasoningSteps.value;
  }
  return message.reasoning_trace ?? [];
}

function hasMessageReasoning(message: AiConversationMessage) {
  return getMessageReasoningSteps(message).length > 0;
}

function isReasoningExpanded(messageId: string) {
  return expandedReasoningMessageIds.value.includes(messageId);
}

function toggleReasoning(messageId: string) {
  if (isReasoningExpanded(messageId)) {
    expandedReasoningMessageIds.value = expandedReasoningMessageIds.value.filter((id) => id !== messageId);
    return;
  }
  expandedReasoningMessageIds.value = [...expandedReasoningMessageIds.value, messageId];
}

function reasoningStepLabel(step: AiAssistantReasoningStep) {
  if (step.step_type === 'thought') {
    return '思考';
  }
  if (step.step_type === 'action') {
    return '动作';
  }
  return '观察';
}

watch(
  open,
  async (isOpen) => {
    if (isOpen) {
      await ensureConversationLoaded();
      return;
    }

    question.value = '';
    error.value = '';
    sending.value = false;
    assistantDebugEvents.value = [];
    assistantReasoningSteps.value = [];
    activeAssistantMessageId.value = '';
    expandedReasoningMessageIds.value = [];
    fileSelectionActionId.value = '';
    fileSelectionCandidates.value = [];
    selectedUploadId.value = null;
  },
  { immediate: true }
);

watch(
  () => messages.value.length,
  () => {
    syncFlowChartUiState();
    void scrollToLatestMessage();
  }
);

async function handleConfirmSelectedFile() {
  if (!conversationId.value || !fileSelectionActionId.value || !selectedUploadId.value || selectingFile.value) {
    return;
  }

  selectingFile.value = true;
  error.value = '';

  try {
    const message = await resumeAiConversationMessage(conversationId.value, {
      actionId: fileSelectionActionId.value,
      decision: 'confirm',
      payload: {
        uploadId: selectedUploadId.value
      }
    });
    messages.value = [...messages.value, message];
    activeAssistantMessageId.value = message.message_id;
    syncFlowChartUiState();
  } catch (resumeError) {
    error.value = resumeError instanceof Error ? resumeError.message : '生成流程图失败。';
  } finally {
    selectingFile.value = false;
    await scrollToLatestMessage();
  }
}

function handleReselectFile() {
  const latestSelectFileMessage = extractLatestSelectFileMessage();
  if (!latestSelectFileMessage?.pending_action) {
    return;
  }
  fileSelectionActionId.value = latestSelectFileMessage.pending_action.action_id;
  fileSelectionCandidates.value = latestSelectFileMessage.pending_action.payload.candidates;
  selectedUploadId.value = latestSelectFileMessage.pending_action.payload.candidates[0]?.upload_id ?? null;
}

function handleImportFlow() {
  const artifact = activeArtifactMessage.value?.artifact;
  if (!artifact?.graph_payload) {
    return;
  }
  emit('import-flow', buildCanvasSnapshotFromChapterFlow(artifact.graph_payload));
}
</script>

<template>
  <aside v-if="open" class="ai-assistant-popover" data-testid="ai-assistant-popover">
    <div class="ai-assistant-popover__header">
      <div class="ai-assistant-popover__title-block">
        <span class="ai-assistant-popover__eyebrow">AI Chatbox</span>
        <strong>AI 助手</strong>
        <p>多轮对话检索助手，会自动保留当前会话历史。</p>
      </div>
      <div class="ai-assistant-popover__header-actions">
        <button
          type="button"
          class="ai-assistant-popover__clear"
          data-testid="ai-clear-conversation"
          :disabled="loadingConversation || sending || clearing || !conversationId"
          @click="handleClearConversation"
        >
          {{ clearing ? '清空中...' : '清空历史' }}
        </button>
        <button type="button" class="ai-assistant-popover__close" data-testid="ai-panel-close" @click="emit('close')">
          关闭
        </button>
      </div>
    </div>

    <div class="ai-assistant-chatbox" data-testid="ai-chatbox">
      <div ref="messagesContainer" class="ai-assistant-chatbox__messages">
        <div v-if="loadingConversation" class="ai-assistant-popover__state-card ai-assistant-popover__state-card--loading">
          <div class="ai-assistant-popover__pulse"></div>
          <div class="ai-assistant-popover__state-copy">
            <strong>正在建立会话</strong>
            <p>初始化聊天线程并读取历史消息。</p>
          </div>
        </div>

        <div v-else-if="!messages.length" class="ai-assistant-popover__empty-state">
          <div class="ai-assistant-popover__empty-copy">
            <span class="ai-assistant-popover__section-label">Ready</span>
            <h3>开始一段新对话</h3>
            <p>你可以直接提问，AI 会返回回答，并附上命中片段和相关文件。</p>
          </div>
          <div class="ai-assistant-popover__suggestions">
            <button
              v-for="suggestion in suggestedQuestions"
              :key="suggestion"
              type="button"
              class="ai-assistant-popover__suggestion"
              @click="question = suggestion"
            >
              {{ suggestion }}
            </button>
          </div>
        </div>

        <article
          v-for="message in messages"
          :key="message.message_id"
          class="ai-assistant-message"
          :class="`ai-assistant-message--${message.role}`"
        >
          <div class="ai-assistant-message__meta">
            <span>{{ message.role === 'user' ? '你' : 'AI 助手' }}</span>
            <span>{{ new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</span>
          </div>
          <div
            class="ai-assistant-message__bubble"
            :class="{ 'ai-assistant-message__bubble--streaming': message.status === 'streaming' }"
          >
            <p>{{ message.content }}</p>

            <section
              v-if="message.role === 'assistant' && hasMessageReasoning(message)"
              class="ai-assistant-message__reasoning"
            >
              <button
                type="button"
                class="ai-assistant-message__reasoning-toggle"
                :data-testid="message.message_id === activeAssistantMessageId ? 'ai-reasoning-toggle-active' : `ai-reasoning-toggle-${message.message_id}`"
                @click="toggleReasoning(message.message_id)"
              >
                <span>思考过程</span>
                <span>{{ isReasoningExpanded(message.message_id) ? '收起' : `展开 ${getMessageReasoningSteps(message).length} 步` }}</span>
              </button>
              <ol
                v-if="isReasoningExpanded(message.message_id)"
                class="ai-assistant-message__reasoning-list"
                :data-testid="message.message_id === activeAssistantMessageId ? 'ai-reasoning-panel' : `ai-reasoning-panel-${message.message_id}`"
              >
                <li
                  v-for="(step, index) in getMessageReasoningSteps(message)"
                  :key="`${message.message_id}-reasoning-${index}`"
                  class="ai-assistant-message__reasoning-step"
                  :class="`ai-assistant-message__reasoning-step--${step.step_type}`"
                >
                  <div class="ai-assistant-message__reasoning-step-head">
                    <span>{{ reasoningStepLabel(step) }}</span>
                    <span v-if="step.status">{{ step.status === 'success' ? '成功' : '失败' }}</span>
                  </div>
                  <p>{{ step.content }}</p>
                </li>
              </ol>
            </section>

            <section
              v-if="
                message.role === 'assistant' &&
                message.message_id === activeArtifactMessage?.message_id &&
                message.actions?.length
              "
              class="ai-assistant-message__debug"
            >
              <span class="ai-assistant-popover__section-label">流程图操作</span>
              <div class="ai-assistant-popover__suggestions">
                <button
                  v-for="action in message.actions"
                  :key="`${message.message_id}-${action.action_type}`"
                  type="button"
                  class="ai-assistant-popover__suggestion"
                  :data-testid="action.action_type === 'import_flow' ? 'ai-import-flow' : 'ai-reselect-file'"
                  @click="action.action_type === 'import_flow' ? handleImportFlow() : handleReselectFile()"
                >
                  {{ action.label }}
                </button>
              </div>
            </section>

            <section
              v-if="message.role === 'assistant' && message.message_id === activeAssistantMessageId && activeAssistantLoadingState"
              class="ai-assistant-message__loading"
              data-testid="ai-assistant-loading"
            >
              <div class="ai-assistant-popover__pulse"></div>
              <div class="ai-assistant-popover__state-copy">
                <strong>{{ activeAssistantLoadingState.title }}</strong>
                <p>{{ activeAssistantLoadingState.description }}</p>
              </div>
            </section>

            <div
              v-if="message.role === 'assistant' && message.references.length"
              class="ai-assistant-message__references"
            >
              <section
                v-if="message.references.some(isSnippetReference)"
                class="ai-assistant-message__reference-section"
              >
                <span class="ai-assistant-popover__section-label">Evidence</span>
                <article
                  v-for="reference in message.references.filter(isSnippetReference)"
                  :key="`${message.message_id}-${reference.file_name}-${reference.snippet_text}`"
                  class="ai-assistant-popover__snippet-card"
                >
                  <div class="ai-assistant-popover__card-head">
                    <strong>{{ reference.file_name }}</strong>
                    <span>{{ formatReferenceMeta(reference) }}</span>
                  </div>
                  <p>{{ reference.snippet_text }}</p>
                </article>
              </section>

              <section
                v-if="message.references.some(isFileReference)"
                class="ai-assistant-message__reference-section"
              >
                <span class="ai-assistant-popover__section-label">Files</span>
                <article
                  v-for="reference in message.references.filter(isFileReference)"
                  :key="`${message.message_id}-${reference.file_name}-${reference.download_url}`"
                  class="ai-assistant-popover__file-card"
                >
                  <div class="ai-assistant-popover__card-head">
                    <strong>{{ reference.file_name }}</strong>
                    <span>{{ formatReferenceMeta(reference) }}</span>
                  </div>
                  <a
                    v-if="reference.download_url"
                    :href="reference.download_url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    打开原始文件
                  </a>
                </article>
              </section>
            </div>
          </div>
        </article>

        <div v-if="error" class="ai-assistant-popover__state-card ai-assistant-popover__state-card--error">
          <div class="ai-assistant-popover__state-copy">
            <strong>请求失败</strong>
            <p class="ai-assistant-popover__error">{{ error }}</p>
          </div>
        </div>

        <div
          v-if="hasVisibleFileSelection"
          class="ai-assistant-popover__state-card"
          data-testid="ai-file-selector"
        >
          <div class="ai-assistant-popover__state-copy">
            <strong>请选择一个文件</strong>
            <p>确认后将根据该文件生成流程图。</p>
          </div>
          <div class="ai-assistant-popover__suggestions">
            <button
              v-for="candidate in fileSelectionCandidates"
              :key="candidate.upload_id"
              type="button"
              class="ai-assistant-popover__suggestion"
              :data-testid="`ai-file-option-${candidate.upload_id}`"
              :data-selected="selectedUploadId === candidate.upload_id ? 'true' : 'false'"
              @click="selectedUploadId = candidate.upload_id"
            >
              {{ candidate.file_name }}
            </button>
          </div>
          <div class="ai-assistant-popover__actions">
            <button
              type="button"
              class="ai-assistant-popover__submit"
              data-testid="ai-file-confirm"
              :disabled="selectedUploadId === null || selectingFile"
              @click="handleConfirmSelectedFile"
            >
              {{ selectingFile ? '生成中...' : '确定' }}
            </button>
          </div>
        </div>
      </div>

      <div class="ai-assistant-popover__form ai-assistant-chatbox__composer">
        <div class="ai-assistant-popover__prompt-head">
          <span>输入消息</span>
          <span class="ai-assistant-popover__prompt-tip">支持普通聊天、文件检索和 XML 占位回复</span>
        </div>
        <textarea
          v-model="question"
          data-testid="ai-question-input"
          class="ai-assistant-popover__input"
          placeholder="输入你的问题，例如：帮我找出上传文件里和合同审批相关的规则"
        />
        <div class="ai-assistant-popover__actions">
          <button
            type="button"
            data-testid="ai-submit"
            class="ai-assistant-popover__submit"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >
            {{ sending ? '发送中...' : '发送' }}
          </button>
          <span class="ai-assistant-popover__helper">当前会话会保留历史消息并继续上下文。</span>
        </div>
      </div>
    </div>
  </aside>
</template>
