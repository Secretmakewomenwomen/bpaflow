import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  AiAssistantReasoningStep,
  AiConversation,
  AiConversationMessage,
  SendAiConversationMessageResponse
} from '../types/ai';
import {
  clearAiConversation,
  createAiConversation,
  fetchLatestAiConversation,
  fetchAiConversationMessages,
  resumeAiConversationMessage,
  sendAiConversationMessage,
  streamAiConversationMessage
} from './ai';
import * as http from './http';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ai conversation api', () => {
  it('creates a conversation', async () => {
    const responsePayload: AiConversation = {
      conversation_id: 'conv-1',
      title: '新对话',
      created_at: '2026-03-30T00:00:00Z',
      updated_at: '2026-03-30T00:00:00Z',
      last_message_at: '2026-03-30T00:00:00Z'
    };

    const apiFetchSpy = vi
      .spyOn(http, 'apiFetch')
      .mockResolvedValue(new Response(JSON.stringify(responsePayload), { status: 200 }));

    await expect(createAiConversation()).resolves.toEqual(responsePayload);
    expect(apiFetchSpy).toHaveBeenCalledWith('/api/ai/conversations', {
      method: 'POST'
    });
  });

  it('loads message history', async () => {
    const responsePayload: AiConversationMessage[] = [
      {
        message_id: 'msg-1',
        role: 'assistant',
        intent: 'rag_retrieval',
        content: '已找到资料',
        status: 'completed',
        created_at: '2026-03-30T00:00:00Z',
        references: []
      }
    ];

    vi.spyOn(http, 'apiFetch').mockResolvedValue(
      new Response(JSON.stringify(responsePayload), { status: 200 })
    );

    await expect(fetchAiConversationMessages('conv-1')).resolves.toEqual(responsePayload);
  });

  it('parses assistant messages with pending actions and artifacts', async () => {
    const responsePayload: AiConversationMessage[] = [
      {
        message_id: 'msg-ai',
        role: 'assistant',
        intent: 'generate_flow_from_file',
        content: '请选择文件。',
        status: 'waiting_input',
        pending_action: {
          action_id: 'action-1',
          action_type: 'select_file',
          payload: {
            selection_mode: 'single',
            candidates: [{ upload_id: 101, file_name: '手册.docx' }]
          }
        },
        artifact: null,
        actions: [],
        created_at: '2026-04-02T00:00:00Z',
        references: []
      }
    ];

    vi.spyOn(http, 'apiFetch').mockResolvedValue(
      new Response(JSON.stringify(responsePayload), { status: 200 })
    );

    await expect(fetchAiConversationMessages('conv-1')).resolves.toEqual(responsePayload);
  });

  it('clears a conversation', async () => {
    const apiFetchSpy = vi
      .spyOn(http, 'apiFetch')
      .mockResolvedValue(new Response(null, { status: 204 }));

    await expect(clearAiConversation('conv-1')).resolves.toBeUndefined();
    expect(apiFetchSpy).toHaveBeenCalledWith('/api/ai/conversations/conv-1/clear', {
      method: 'POST'
    });
  });

  it('loads the latest conversation when available', async () => {
    const responsePayload: AiConversation = {
      conversation_id: 'conv-latest',
      title: '最近会话',
      created_at: '2026-03-30T00:00:00Z',
      updated_at: '2026-03-30T00:10:00Z',
      last_message_at: '2026-03-30T00:10:00Z'
    };

    const apiFetchSpy = vi
      .spyOn(http, 'apiFetch')
      .mockResolvedValue(new Response(JSON.stringify(responsePayload), { status: 200 }));

    await expect(fetchLatestAiConversation()).resolves.toEqual(responsePayload);
    expect(apiFetchSpy).toHaveBeenCalledWith('/api/ai/conversations/latest');
  });

  it('sends a message and returns the new turn', async () => {
    const responsePayload: SendAiConversationMessageResponse = {
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
          references: []
        }
      ]
    };

    const apiFetchSpy = vi
      .spyOn(http, 'apiFetch')
      .mockResolvedValue(new Response(JSON.stringify(responsePayload), { status: 200 }));

    await expect(sendAiConversationMessage('conv-1', { query: '理赔流程' })).resolves.toEqual(
      responsePayload
    );

    expect(apiFetchSpy).toHaveBeenCalledWith(
      '/api/ai/conversations/conv-1/messages',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json'
        }),
        body: JSON.stringify({ query: '理赔流程' })
      })
    );
  });

  it('posts a single uploadId to the resume endpoint', async () => {
    const responsePayload: AiConversationMessage = {
      message_id: 'msg-ai',
      role: 'assistant',
      intent: 'generate_flow_from_file',
      content: '已生成流程图',
      status: 'completed',
      pending_action: null,
      artifact: {
        artifact_type: 'chapter_flow_json',
        graph_payload: {
          nodes: [],
          edges: []
        },
        payload: {
          flowType: 'chapter_phase_flow'
        }
      },
      actions: [{ action_id: 'action-1', action_type: 'import_flow', label: '导入' }],
      created_at: '2026-04-02T00:00:01Z',
      references: []
    };

    const apiFetchSpy = vi
      .spyOn(http, 'apiFetch')
      .mockResolvedValue(new Response(JSON.stringify(responsePayload), { status: 200 }));

    await expect(
      resumeAiConversationMessage('conv-1', {
        actionId: 'action-1',
        decision: 'confirm',
        payload: { uploadId: 101 }
      })
    ).resolves.toEqual(responsePayload);

    expect(apiFetchSpy).toHaveBeenCalledWith(
      '/api/ai/conversations/conv-1/messages/resume',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json'
        }),
        body: JSON.stringify({
          actionId: 'action-1',
          decision: 'confirm',
          payload: { uploadId: 101 }
        })
      })
    );
  });

  it('throws the backend error message when the request fails', async () => {
    const errorPayload = { detail: { code: 'AI_RETRIEVAL_FAILED', message: '检索失败，请稍后再试。' } };
    vi
      .spyOn(http, 'apiFetch')
      .mockResolvedValue(new Response(JSON.stringify(errorPayload), { status: 503 }));

    await expect(createAiConversation()).rejects.toThrow('检索失败，请稍后再试。');
  });

  it('rejects malformed success payloads', async () => {
    vi.spyOn(http, 'apiFetch').mockResolvedValue(
      new Response(JSON.stringify({ conversation_id: 1 }), { status: 200 })
    );

    await expect(createAiConversation()).rejects.toThrow('Unexpected AI response shape.');
  });

  it('rejects conversation messages with invalid enum fields', async () => {
    vi.spyOn(http, 'apiFetch').mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            message_id: 'msg-ai',
            role: 'bot',
            intent: 'unknown_intent',
            content: 'bad payload',
            status: 'completed',
            created_at: '2026-04-02T00:00:00Z',
            references: [
              {
                reference_type: 'unknown',
                upload_id: 1,
                file_name: 'bad.pdf',
                snippet_text: null,
                page_start: null,
                page_end: null,
                score: null,
                download_url: null
              }
            ]
          }
        ]),
        { status: 200 }
      )
    );

    await expect(fetchAiConversationMessages('conv-1')).rejects.toThrow(
      'Unexpected AI response shape.'
    );
  });

  it('rejects invalid resume payloads before sending the request', async () => {
    const apiFetchSpy = vi.spyOn(http, 'apiFetch');

    await expect(
      resumeAiConversationMessage('conv-1', {
        actionId: '   ',
        decision: 'confirm',
        payload: { uploadId: 0 }
      })
    ).rejects.toThrow('Invalid AI resume payload.');

    expect(apiFetchSpy).not.toHaveBeenCalled();
  });

  it('parses SSE stream events for AI conversation messages', async () => {
    const encoder = new TextEncoder();
    const reasoningSteps: AiAssistantReasoningStep[] = [];
    const chunks = [
      'event: user_message\n',
      'data: {"message":{"message_id":"msg-user","role":"user","intent":null,"content":"你好","status":"completed","created_at":"2026-03-30T00:00:00Z","references":[]}}\n\n',
      'event: assistant_start\n',
      'data: {"intent":"general_chat"}\n\n',
      'event: assistant_reasoning\n',
      'data: {"step":{"step_type":"action","content":"调用工具 search_knowledge_base","tool_name":"search_knowledge_base","tool_args":{"query":"你好"}}}\n\n',
      'event: assistant_delta\n',
      'data: {"delta":"你"}\n\n',
      'event: assistant_delta\n',
      'data: {"delta":"好"}\n\n',
      'event: assistant_done\n',
      'data: {"message":{"message_id":"msg-ai","role":"assistant","intent":"general_chat","content":"你好","status":"completed","created_at":"2026-03-30T00:00:01Z","references":[]}}\n\n'
    ];
    const response = new Response(
      new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
          controller.close();
        }
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream'
        }
      }
    );

    vi.spyOn(http, 'apiFetch').mockResolvedValue(response);
    const events: string[] = [];

    await streamAiConversationMessage('conv-1', { query: '你好' }, {
      onUserMessage(message) {
        events.push(`user:${message.content}`);
      },
      onAssistantStart() {
        events.push('start');
      },
      onAssistantReasoning(step) {
        reasoningSteps.push(step);
      },
      onAssistantDelta(delta) {
        events.push(`delta:${delta}`);
      },
      onAssistantDone(message) {
        events.push(`done:${message.content}`);
      }
    });

    expect(reasoningSteps).toEqual([
      {
        step_type: 'action',
        content: '调用工具 search_knowledge_base',
        tool_name: 'search_knowledge_base',
        tool_args: { query: '你好' }
      }
    ]);
    expect(events).toEqual(['user:你好', 'start', 'delta:你', 'delta:好', 'done:你好']);
  });

  it('ignores malformed assistant_reasoning events without aborting the stream', async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'event: assistant_reasoning\n',
      'data: {"step":{"step_type":"invalid","content":1}}\n\n',
      'event: assistant_delta\n',
      'data: {"delta":"你"}\n\n',
      'event: assistant_done\n',
      'data: {"message":{"message_id":"msg-ai","role":"assistant","intent":"general_chat","content":"你","status":"completed","created_at":"2026-03-30T00:00:01Z","references":[]}}\n\n'
    ];
    const response = new Response(
      new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
          controller.close();
        }
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream'
        }
      }
    );

    vi.spyOn(http, 'apiFetch').mockResolvedValue(response);
    const events: string[] = [];

    await streamAiConversationMessage('conv-1', { query: '你好' }, {
      onAssistantReasoning() {
        events.push('reasoning');
      },
      onAssistantDelta(delta) {
        events.push(`delta:${delta}`);
      },
      onAssistantDone(message) {
        events.push(`done:${message.content}`);
      }
    });

    expect(events).toEqual(['delta:你', 'done:你']);
  });

  it('ignores malformed assistant_debug events without aborting the stream', async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'event: user_message\n',
      'data: {"message":{"message_id":"msg-user","role":"user","intent":null,"content":"你好","status":"completed","created_at":"2026-03-30T00:00:00Z","references":[]}}\n\n',
      'event: assistant_debug\n',
      'data: {"stage":"tool_start","tool_name":"search_docs","tool_args":"invalid"}\n\n',
      'event: assistant_delta\n',
      'data: {"delta":"你"}\n\n',
      'event: assistant_done\n',
      'data: {"message":{"message_id":"msg-ai","role":"assistant","intent":"general_chat","content":"你好","status":"completed","created_at":"2026-03-30T00:00:01Z","references":[]}}\n\n'
    ];
    const response = new Response(
      new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
          controller.close();
        }
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream'
        }
      }
    );

    vi.spyOn(http, 'apiFetch').mockResolvedValue(response);
    const events: string[] = [];

    await streamAiConversationMessage('conv-1', { query: '你好' }, {
      onUserMessage(message) {
        events.push(`user:${message.content}`);
      },
      onAssistantDebug() {
        events.push('debug');
      },
      onAssistantDelta(delta) {
        events.push(`delta:${delta}`);
      },
      onAssistantDone(message) {
        events.push(`done:${message.content}`);
      }
    });

    expect(events).toEqual(['user:你好', 'delta:你', 'done:你好']);
  });

  it('parses SSE assistant_done messages with waiting_input pending_action payloads', async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'event: assistant_start\n',
      'data: {"intent":"general_chat"}\n\n',
      'event: assistant_done\n',
      'data: {"message":{"message_id":"msg-ai","role":"assistant","intent":"general_chat","content":"请选择文件。","status":"waiting_input","pending_action":{"action_id":"action-1","action_type":"select_file","payload":{"selection_mode":"single","candidates":[{"upload_id":101,"file_name":"手册.docx"}]}},"artifact":null,"actions":[],"created_at":"2026-04-02T00:00:01Z","references":[]}}\n\n'
    ];
    const response = new Response(
      new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
          controller.close();
        }
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream'
        }
      }
    );

    vi.spyOn(http, 'apiFetch').mockResolvedValue(response);
    const events: string[] = [];

    await streamAiConversationMessage('conv-1', { query: '根据文件生成流程图' }, {
      onAssistantDone(message) {
        events.push(`${message.status}:${message.pending_action?.action_type ?? 'none'}`);
      }
    });

    expect(events).toEqual(['waiting_input:select_file']);
  });

  it('throws when the SSE stream ends without assistant_done or error', async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'event: assistant_start\n',
      'data: {"intent":"general_chat"}\n\n',
      'event: assistant_delta\n',
      'data: {"delta":"我可以为你提供这些类型的服务与能力："}\n\n'
    ];
    const response = new Response(
      new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
          controller.close();
        }
      }),
      {
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream'
        }
      }
    );

    vi.spyOn(http, 'apiFetch').mockResolvedValue(response);
    const events: string[] = [];

    await expect(
      streamAiConversationMessage('conv-1', { query: '你有哪些能力' }, {
        onAssistantStart() {
          events.push('start');
        },
        onAssistantDelta(delta) {
          events.push(`delta:${delta}`);
        }
      })
    ).rejects.toThrow('AI 流式响应意外中断。');

    expect(events).toEqual(['start', 'delta:我可以为你提供这些类型的服务与能力：']);
  });
});
