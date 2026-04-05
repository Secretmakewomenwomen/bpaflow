// @vitest-environment happy-dom

import { defineComponent, h } from 'vue';
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AiAssistantPopover from './AiAssistantPopover.vue';
import CanvasPage from '../pages/CanvasPage.vue';
import type {
  AiAssistantReasoningStep,
  AiConversation,
  AiConversationMessage,
  SendAiConversationMessageResponse
} from '../types/ai';

const {
  clearAiConversationMock,
  createAiConversationMock,
  fetchLatestAiConversationMock,
  fetchAiConversationMessagesMock,
  resumeAiConversationMessageMock,
  sendAiConversationMessageMock,
  streamAiConversationMessageMock
} = vi.hoisted(() => ({
  clearAiConversationMock: vi.fn(),
  createAiConversationMock: vi.fn(),
  fetchLatestAiConversationMock: vi.fn(),
  fetchAiConversationMessagesMock: vi.fn(),
  resumeAiConversationMessageMock: vi.fn(),
  sendAiConversationMessageMock: vi.fn(),
  streamAiConversationMessageMock: vi.fn()
}));

vi.mock('../lib/ai', () => ({
  clearAiConversation: clearAiConversationMock,
  createAiConversation: createAiConversationMock,
  fetchLatestAiConversation: fetchLatestAiConversationMock,
  fetchAiConversationMessages: fetchAiConversationMessagesMock,
  resumeAiConversationMessage: resumeAiConversationMessageMock,
  sendAiConversationMessage: sendAiConversationMessageMock,
  streamAiConversationMessage: streamAiConversationMessageMock
}));

vi.mock('../lib/canvas', () => ({
  fetchCanvasNodes: vi.fn(async () => [
    {
      id: 'tree-root-1',
      parentId: null,
      name: '默认节点',
      sortOrder: 0,
      createdAt: '2026-03-30T00:00:00Z',
      updatedAt: '2026-03-30T00:00:00Z'
    }
  ]),
  createCanvasNode: vi.fn(async () => ({
    id: 'tree-root-2',
    parentId: null,
    name: '新节点',
    sortOrder: 1,
    createdAt: '2026-03-30T00:01:00Z',
    updatedAt: '2026-03-30T00:01:00Z'
  })),
  fetchCanvas: vi.fn(async () => null),
  saveCanvas: vi.fn(async () => undefined)
}));

vi.mock('../lib/upload', () => ({
  fetchRecentUploads: vi.fn(async () => []),
  uploadFile: vi.fn(async () => undefined),
  deleteUploadedFile: vi.fn(async () => undefined),
  validateUploadFile: vi.fn(() => '')
}));

vi.mock('../lib/auth', () => ({
  authState: {
    user: {
      user_id: 'user-1',
      username: 'tester'
    }
  },
  clearAuth: vi.fn(),
  getCurrentUser: vi.fn(() => ({
    user_id: 'user-1',
    username: 'tester'
  }))
}));

vi.mock('ant-design-vue', () => ({
  Modal: {
    confirm: vi.fn()
  }
}));

afterEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function emitStreamReply(
  handlers: {
    onUserMessage?: (message: AiConversationMessage) => void;
    onAssistantStart?: (payload: { intent?: string | null }) => void;
    onAssistantReasoning?: (step: AiAssistantReasoningStep) => void;
    onAssistantDebug?: (payload: {
      stage: string;
      tool_name: string;
      tool_args: Record<string, unknown>;
      message?: string;
    }) => void;
    onAssistantDelta?: (delta: string) => void;
    onAssistantDone?: (message: AiConversationMessage) => void;
  },
  payload: SendAiConversationMessageResponse = assistantReply
) {
  handlers.onUserMessage?.(payload.messages[0]);
  handlers.onAssistantStart?.({ intent: payload.messages[1].intent });
  handlers.onAssistantReasoning?.({
    step_type: 'thought',
    content: '先分析是否需要检索知识库'
  });
  handlers.onAssistantReasoning?.({
    step_type: 'action',
    content: '调用工具 search_knowledge_base',
    tool_name: 'search_knowledge_base',
    tool_args: { query: payload.messages[0].content }
  });
  handlers.onAssistantReasoning?.({
    step_type: 'observation',
    content: '工具 search_knowledge_base 调用成功',
    tool_name: 'search_knowledge_base',
    tool_args: { query: payload.messages[0].content },
    status: 'success'
  });
  handlers.onAssistantDebug?.({
    stage: 'tool_start',
    tool_name: 'search_knowledge_base',
    tool_args: { query: payload.messages[0].content },
    message: '开始检索知识库'
  });
  handlers.onAssistantDebug?.({
    stage: 'tool_result',
    tool_name: 'search_knowledge_base',
    tool_args: { query: payload.messages[0].content },
    message: '知识库检索完成'
  });
  handlers.onAssistantDelta?.('已找到');
  handlers.onAssistantDone?.(payload.messages[1]);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
}

function flushPromises() {
  return new Promise<void>((resolve) => {
    setTimeout(resolve);
  });
}

function mountCanvasPage() {
  const passthrough = defineComponent({
    name: 'PassThrough',
    setup(_, { slots }) {
      return () => h('div', slots.default?.());
    }
  });

  const buttonStub = defineComponent({
    name: 'AButtonStub',
    emits: ['click'],
    setup(_, { emit, slots }) {
      return () =>
        h(
          'button',
          {
            type: 'button',
            onClick: () => emit('click')
          },
          slots.default?.()
        );
    }
  });

  return mount(CanvasPage, {
    global: {
      stubs: {
        ArchitectureCanvas: true,
        DocumentRail: true,
        InspectorPanel: true,
        UploadModal: true,
        'a-layout': passthrough,
        'a-layout-header': passthrough,
        'a-layout-sider': passthrough,
        'a-layout-content': passthrough,
        'a-drawer': passthrough,
        'a-tag': passthrough,
        'a-typography-text': passthrough,
        'a-button': buttonStub
      }
    }
  });
}

const baseConversation: AiConversation = {
  conversation_id: 'conv-1',
  title: '新对话',
  created_at: '2026-03-30T00:00:00Z',
  updated_at: '2026-03-30T00:00:00Z',
  last_message_at: '2026-03-30T00:00:00Z'
};

const assistantReply: SendAiConversationMessageResponse = {
  conversation_id: 'conv-1',
  messages: [
    {
      message_id: 'msg-user',
      role: 'user',
      intent: null,
      content: '理赔流程',
      status: 'completed',
      created_at: '2026-03-30T00:00:00Z',
      references: []
    },
    {
      message_id: 'msg-ai',
      role: 'assistant',
      intent: 'rag_retrieval',
      content: '已找到流程定义',
      status: 'completed',
      created_at: '2026-03-30T00:00:01Z',
      references: [
        {
          reference_type: 'snippet',
          upload_id: 10,
          file_name: '流程手册.pdf',
          snippet_text: '审批需要两级复核',
          page_start: 2,
          page_end: 3,
          score: 0.92,
          download_url: null
        },
        {
          reference_type: 'file',
          upload_id: 10,
          file_name: '流程手册.pdf',
          snippet_text: null,
          page_start: null,
          page_end: null,
          score: null,
          download_url: '/api/uploads/10/download'
        }
      ]
    }
  ]
};

const waitingInputMessage: AiConversationMessage = {
  message_id: 'msg-ai-waiting',
  role: 'assistant',
  intent: 'generate_flow_from_file',
  content: '我找到了相关文件，请选择一个文件生成流程图。',
  status: 'waiting_input',
  pending_action: {
    action_id: 'action-1',
    action_type: 'select_file',
    payload: {
      selection_mode: 'single',
      candidates: [
        { upload_id: 101, file_name: '保险产品设计与销售流程手册.docx' },
        { upload_id: 102, file_name: '保险产品培训手册.docx' }
      ]
    }
  },
  artifact: null,
  actions: [],
  created_at: '2026-04-02T00:00:00Z',
  references: []
};

const completedFlowMessage: AiConversationMessage = {
  message_id: 'msg-ai-completed',
  role: 'assistant',
  intent: 'generate_flow_from_file',
  content: '已根据所选文件生成流程图。',
  status: 'completed',
  pending_action: null,
  artifact: {
    artifact_type: 'chapter_flow_json',
    graph_payload: {
      lanes: [
        {
          id: 'chapter-1',
          name: '第一章 总则',
          order: 1,
          children: [
            {
              id: '1.1',
              name: '立项评审',
              summary: '提交立项材料并完成评审',
              metadata: {
                role: '产品经理',
                department: '产品部',
                owner: '张三',
                responsibilities: ['提交申请']
              }
            }
          ]
        }
      ],
      edges: []
    },
    payload: {
      flowType: 'chapter_phase_flow'
    }
  },
  actions: [
    { action_id: 'action-1', action_type: 'import_flow', label: '导入' },
    { action_id: 'action-1', action_type: 'reselect_file', label: '重新选择文件' }
  ],
  created_at: '2026-04-02T00:00:01Z',
  references: []
};

describe('AiAssistantPopover', () => {
  it('opens and closes the AI panel from AppHeader via CanvasPage', async () => {
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);
    const wrapper = mountCanvasPage();

    expect(wrapper.find('[data-testid="ai-assistant-popover"]').exists()).toBe(false);

    await wrapper.get('[data-testid="ai-entry-button"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="ai-assistant-popover"]').exists()).toBe(true);

    await wrapper.get('[data-testid="ai-panel-close"]').trigger('click');
    expect(wrapper.find('[data-testid="ai-assistant-popover"]').exists()).toBe(false);
  });

  it('creates a conversation and loads empty chat state on open', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();

    expect(createAiConversationMock).toHaveBeenCalledTimes(1);
    expect(fetchAiConversationMessagesMock).toHaveBeenCalledWith('conv-1');
    expect(wrapper.text()).toContain('开始一段新对话');
  });

  it('sends a message and appends assistant reply with references', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);
    streamAiConversationMessageMock.mockImplementation(async (_conversationId, _payload, handlers) => {
      emitStreamReply(handlers);
    });

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-question-input"]').setValue('理赔流程');
    await wrapper.get('[data-testid="ai-submit"]').trigger('click');
    await flushPromises();

    expect(streamAiConversationMessageMock).toHaveBeenCalledWith('conv-1', { query: '理赔流程' }, expect.any(Object));
    expect(wrapper.text()).toContain('已找到流程定义');
    expect(wrapper.text()).toContain('审批需要两级复核');
    expect(wrapper.text()).toContain('流程手册.pdf');
  });

  it('renders a loading card during tool execution instead of success logs', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);
    const pending = deferred<void>();
    streamAiConversationMessageMock.mockImplementation(async (_conversationId, _payload, handlers) => {
      handlers.onUserMessage?.(assistantReply.messages[0]);
      handlers.onAssistantStart?.({ intent: assistantReply.messages[1].intent });
      handlers.onAssistantReasoning?.({
        step_type: 'thought',
        content: '先分析是否需要检索知识库'
      });
      handlers.onAssistantReasoning?.({
        step_type: 'action',
        content: '调用工具 search_knowledge_base',
        tool_name: 'search_knowledge_base',
        tool_args: { query: assistantReply.messages[0].content }
      });
      handlers.onAssistantDebug?.({
        stage: 'tool_start',
        tool_name: 'search_knowledge_base',
        tool_args: { query: assistantReply.messages[0].content },
        message: '开始检索知识库'
      });
      handlers.onAssistantDebug?.({
        stage: 'tool_result',
        tool_name: 'search_knowledge_base',
        tool_args: { query: assistantReply.messages[0].content },
        message: '知识库检索完成'
      });
      handlers.onAssistantDelta?.('已找到');
      await pending.promise;
      handlers.onAssistantDone?.(assistantReply.messages[1]);
    });

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-question-input"]').setValue('理赔流程');
    await wrapper.get('[data-testid="ai-submit"]').trigger('click');
    await flushPromises();

    expect(wrapper.get('[data-testid="ai-assistant-loading"]').text()).toContain('正在生成回答');
    expect(wrapper.get('[data-testid="ai-assistant-loading"]').text()).toContain('search_knowledge_base');
    expect(wrapper.text()).not.toContain('工具 search_knowledge_base 调用成功');

    pending.resolve();
    await flushPromises();

    expect(wrapper.find('[data-testid="ai-assistant-loading"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('已找到流程定义');
  });

  it('shows reasoning steps during streaming and preserves them after completion', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);
    const pending = deferred<void>();
    streamAiConversationMessageMock.mockImplementation(async (_conversationId, _payload, handlers) => {
      handlers.onUserMessage?.(assistantReply.messages[0]);
      handlers.onAssistantStart?.({ intent: assistantReply.messages[1].intent });
      handlers.onAssistantReasoning?.({
        step_type: 'thought',
        content: '先分析是否需要检索知识库'
      });
      handlers.onAssistantReasoning?.({
        step_type: 'action',
        content: '调用工具 search_knowledge_base',
        tool_name: 'search_knowledge_base',
        tool_args: { query: assistantReply.messages[0].content }
      });
      handlers.onAssistantDelta?.('已找到');
      await pending.promise;
      handlers.onAssistantReasoning?.({
        step_type: 'observation',
        content: '工具 search_knowledge_base 调用成功',
        tool_name: 'search_knowledge_base',
        tool_args: { query: assistantReply.messages[0].content },
        status: 'success'
      });
      handlers.onAssistantDone?.({
        ...assistantReply.messages[1],
        reasoning_trace: [
          {
            step_type: 'thought',
            content: '先分析是否需要检索知识库'
          },
          {
            step_type: 'action',
            content: '调用工具 search_knowledge_base',
            tool_name: 'search_knowledge_base',
            tool_args: { query: assistantReply.messages[0].content }
          },
          {
            step_type: 'observation',
            content: '工具 search_knowledge_base 调用成功',
            tool_name: 'search_knowledge_base',
            tool_args: { query: assistantReply.messages[0].content },
            status: 'success'
          }
        ]
      });
    });

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-question-input"]').setValue('理赔流程');
    await wrapper.get('[data-testid="ai-submit"]').trigger('click');
    await flushPromises();

    expect(wrapper.get('[data-testid="ai-reasoning-toggle-active"]').text()).toContain('思考过程');
    expect(wrapper.get('[data-testid="ai-reasoning-panel"]').text()).toContain('先分析是否需要检索知识库');
    expect(wrapper.get('[data-testid="ai-reasoning-panel"]').text()).toContain('调用工具 search_knowledge_base');

    pending.resolve();
    await flushPromises();

    expect(wrapper.get('[data-testid="ai-reasoning-toggle-active"]').text()).toContain('思考过程');
    expect(wrapper.get('[data-testid="ai-reasoning-panel"]').text()).toContain('工具 search_knowledge_base 调用成功');
    await wrapper.get('[data-testid="ai-reasoning-toggle-active"]').trigger('click');
    expect(wrapper.find('[data-testid="ai-reasoning-panel"]').exists()).toBe(false);
  });

  it('renders the user message immediately before the assistant reply returns', async () => {
    const pending = deferred<void>();
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);
    streamAiConversationMessageMock.mockImplementationOnce(async (_conversationId, _payload, handlers) => {
      handlers.onAssistantStart?.({ intent: 'general_chat' });
      handlers.onAssistantDelta?.('正在');
      return pending.promise;
    });

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-question-input"]').setValue('理赔流程');
    await wrapper.get('[data-testid="ai-submit"]').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('理赔流程');
    expect(wrapper.text()).toContain('正在');

    pending.resolve();
    await flushPromises();
  });

  it('renders existing message history', async () => {
    const history: AiConversationMessage[] = [assistantReply.messages[1]];
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue(history);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();

    expect(wrapper.text()).toContain('已找到流程定义');
  });

  it('clears the current conversation and creates a fresh one', async () => {
    const nextConversation: AiConversation = {
      ...baseConversation,
      conversation_id: 'conv-2'
    };

    fetchLatestAiConversationMock.mockResolvedValue({
      ...baseConversation,
      conversation_id: 'conv-1'
    });
    fetchAiConversationMessagesMock
      .mockResolvedValueOnce([assistantReply.messages[1]])
      .mockResolvedValueOnce([]);
    clearAiConversationMock.mockResolvedValue(undefined);
    createAiConversationMock.mockResolvedValue(nextConversation);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-clear-conversation"]').trigger('click');
    await flushPromises();

    expect(clearAiConversationMock).toHaveBeenCalledWith('conv-1');
    expect(createAiConversationMock).toHaveBeenCalledTimes(1);
    expect(fetchAiConversationMessagesMock).toHaveBeenNthCalledWith(1, 'conv-1');
    expect(fetchAiConversationMessagesMock).toHaveBeenNthCalledWith(2, 'conv-2');
    expect(window.localStorage.getItem('ai_assistant_conversation_id:user-1')).toBe('conv-2');
    expect(wrapper.text()).toContain('开始一段新对话');
  });

  it('restores the stored conversation and rehydrates history after remount', async () => {
    const history: AiConversationMessage[] = [assistantReply.messages[1]];
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue(history);

    const firstWrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    firstWrapper.unmount();

    const secondWrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();

    expect(createAiConversationMock).toHaveBeenCalledTimes(1);
    expect(fetchAiConversationMessagesMock).toHaveBeenNthCalledWith(1, 'conv-1');
    expect(fetchAiConversationMessagesMock).toHaveBeenNthCalledWith(2, 'conv-1');
    expect(secondWrapper.text()).toContain('已找到流程定义');
  });

  it('falls back to creating a new conversation when the stored one no longer exists', async () => {
    const staleConversationError = Object.assign(new Error('AI 会话不存在。'), { status: 404 });
    const nextConversation = {
      ...baseConversation,
      conversation_id: 'conv-2'
    };

    window.localStorage.setItem('ai_assistant_conversation_id:user-1', 'stale-conv');
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(nextConversation);
    fetchAiConversationMessagesMock
      .mockRejectedValueOnce(staleConversationError)
      .mockResolvedValueOnce([]);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();

    expect(fetchAiConversationMessagesMock).toHaveBeenNthCalledWith(1, 'stale-conv');
    expect(createAiConversationMock).toHaveBeenCalledTimes(1);
    expect(fetchAiConversationMessagesMock).toHaveBeenNthCalledWith(2, 'conv-2');
    expect(window.localStorage.getItem('ai_assistant_conversation_id:user-1')).toBe('conv-2');
    expect(wrapper.text()).toContain('开始一段新对话');
  });

  it('rehydrates the latest conversation when no stored conversation id exists', async () => {
    const history: AiConversationMessage[] = [assistantReply.messages[1]];
    fetchLatestAiConversationMock.mockResolvedValue({
      ...baseConversation,
      conversation_id: 'conv-latest',
      title: '最近会话'
    });
    fetchAiConversationMessagesMock.mockResolvedValue(history);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();

    expect(fetchLatestAiConversationMock).toHaveBeenCalledTimes(1);
    expect(createAiConversationMock).not.toHaveBeenCalled();
    expect(fetchAiConversationMessagesMock).toHaveBeenCalledWith('conv-latest');
    expect(window.localStorage.getItem('ai_assistant_conversation_id:user-1')).toBe('conv-latest');
    expect(wrapper.text()).toContain('已找到流程定义');
  });

  it('renders error text when sending fails', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);
    streamAiConversationMessageMock.mockRejectedValueOnce(new Error('检索服务暂时不可用'));

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-question-input"]').setValue('查询失败案例');
    await wrapper.get('[data-testid="ai-submit"]').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('检索服务暂时不可用');
  });

  it('disables submit for empty or whitespace queries', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([]);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    const button = wrapper.get('[data-testid="ai-submit"]');
    expect(button.element.hasAttribute('disabled')).toBe(true);

    await wrapper.get('[data-testid="ai-question-input"]').setValue('   ');
    await flushPromises();
    expect(button.element.hasAttribute('disabled')).toBe(true);

    await wrapper.get('[data-testid="ai-question-input"]').setValue('有值');
    await flushPromises();
    expect(button.element.hasAttribute('disabled')).toBe(false);
  });

  it('shows a single-select file dialog when assistant returns select_file', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([waitingInputMessage]);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();

    expect(wrapper.text()).toContain('请选择一个文件');
    expect(wrapper.findAll('[data-testid^="ai-file-option-"]')).toHaveLength(2);
  });

  it('resumes flow generation after confirming a selected file', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([waitingInputMessage]);
    resumeAiConversationMessageMock.mockResolvedValue(completedFlowMessage);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-file-option-101"]').trigger('click');
    await wrapper.get('[data-testid="ai-file-confirm"]').trigger('click');
    await flushPromises();

    expect(resumeAiConversationMessageMock).toHaveBeenCalledWith('conv-1', {
      actionId: 'action-1',
      decision: 'confirm',
      payload: { uploadId: 101 }
    });
    expect(wrapper.get('[data-testid="ai-import-flow"]').text()).toContain('导入');
    expect(wrapper.get('[data-testid="ai-reselect-file"]').text()).toContain('重新选择文件');
  });

  it('reopens the selector when clicking reselect', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([waitingInputMessage, completedFlowMessage]);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-reselect-file"]').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('请选择一个文件');
    expect(wrapper.findAll('[data-testid^="ai-file-option-"]')).toHaveLength(2);
  });

  it('emits import-flow when clicking import', async () => {
    fetchLatestAiConversationMock.mockResolvedValue(null);
    createAiConversationMock.mockResolvedValue(baseConversation);
    fetchAiConversationMessagesMock.mockResolvedValue([waitingInputMessage, completedFlowMessage]);

    const wrapper = mount(AiAssistantPopover, {
      props: {
        open: true
      }
    });

    await flushPromises();
    await wrapper.get('[data-testid="ai-import-flow"]').trigger('click');

    expect(wrapper.emitted('import-flow')).toBeTruthy();
  });
});
