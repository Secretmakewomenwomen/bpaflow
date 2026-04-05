import type {
  AiAssistantDebugEvent,
  AiAssistantReasoningStep,
  AiAssistantActionButton,
  AiAssistantArtifact,
  AiConversation,
  AiConversationMessage,
  AiPendingAction,
  ResumeAiConversationMessageRequest,
  SendAiConversationMessageRequest,
  SendAiConversationMessageResponse,
  StreamAiConversationHandlers
} from '../types/ai';
import { apiFetch } from './http';

async function parseError(response: Response) {
  const raw = await response.text();
  let message: string | null = null;

  if (raw) {
    try {
      const payload = JSON.parse(raw);
      message =
        payload?.detail?.message ?? payload?.message ?? payload?.error ?? null;
    } catch {
      message = raw.trim() || null;
    }

    if (!message) {
      const fallback = raw.trim();
      if (fallback) {
        message = fallback;
      }
    }
  }

  const error = new Error(message ?? 'AI 查询失败。') as Error & { status?: number };
  error.status = response.status;
  throw error;
}

function isAiIntent(value: unknown): value is AiConversationMessage['intent'] {
  return (
    value === null ||
    value === 'general_chat' ||
    value === 'rag_retrieval' ||
    value === 'generate_flow_from_file'
  );
}

function isAiMessageRole(value: unknown): value is AiConversationMessage['role'] {
  return value === 'user' || value === 'assistant';
}

function isAiReferenceType(value: unknown): boolean {
  return value === 'snippet' || value === 'file';
}

function assertConversationShape(data: unknown): asserts data is AiConversation {
  if (typeof data !== 'object' || data === null) {
    throw new Error('Unexpected AI response shape.');
  }

  const value = data as Record<string, unknown>;
  if (
    typeof value.conversation_id !== 'string' ||
    typeof value.title !== 'string' ||
    typeof value.created_at !== 'string' ||
    typeof value.updated_at !== 'string' ||
    typeof value.last_message_at !== 'string'
  ) {
    throw new Error('Unexpected AI response shape.');
  }
}

function isMessageReference(item: unknown) {
  if (typeof item !== 'object' || item === null) {
    return false;
  }

  const value = item as Record<string, unknown>;
  return (
    isAiReferenceType(value.reference_type) &&
    (typeof value.upload_id === 'number' || value.upload_id === null) &&
    typeof value.file_name === 'string' &&
    (typeof value.snippet_text === 'string' || value.snippet_text === null) &&
    (typeof value.page_start === 'number' || value.page_start === null) &&
    (typeof value.page_end === 'number' || value.page_end === null) &&
    (typeof value.score === 'number' || value.score === null) &&
    (typeof value.download_url === 'string' || value.download_url === null)
  );
}

function isPendingAction(item: unknown): item is AiPendingAction {
  if (typeof item !== 'object' || item === null) {
    return false;
  }

  const value = item as Record<string, unknown>;
  const payload = value.payload;
  if (typeof payload !== 'object' || payload === null) {
    return false;
  }

  const payloadValue = payload as Record<string, unknown>;
  const candidates = payloadValue.candidates;
  return (
    typeof value.action_id === 'string' &&
    value.action_type === 'select_file' &&
    payloadValue.selection_mode === 'single' &&
    Array.isArray(candidates) &&
    candidates.every(
      (candidate) =>
        typeof candidate === 'object' &&
        candidate !== null &&
        typeof (candidate as Record<string, unknown>).upload_id === 'number' &&
        typeof (candidate as Record<string, unknown>).file_name === 'string'
    )
  );
}

function isAssistantArtifact(item: unknown): item is AiAssistantArtifact {
  if (typeof item !== 'object' || item === null) {
    return false;
  }

  const value = item as Record<string, unknown>;
  const graphPayload = value.graph_payload;
  const payload = value.payload;
  return (
    typeof value.artifact_type === 'string' &&
    (graphPayload === null ||
      (typeof graphPayload === 'object' &&
        graphPayload !== null &&
        !Array.isArray(graphPayload))) &&
    typeof payload === 'object' &&
    payload !== null &&
    !Array.isArray(payload)
  );
}

function isAssistantActionButton(item: unknown): item is AiAssistantActionButton {
  if (typeof item !== 'object' || item === null) {
    return false;
  }

  const value = item as Record<string, unknown>;
  return (
    typeof value.action_id === 'string' &&
    typeof value.action_type === 'string' &&
    typeof value.label === 'string'
  );
}

function isConversationMessage(item: unknown): item is AiConversationMessage {
  if (typeof item !== 'object' || item === null) {
    return false;
  }

  const value = item as Record<string, unknown>;
  const pendingAction = value.pending_action;
  const artifact = value.artifact;
  const actions = value.actions;
  const reasoningTrace = value.reasoning_trace;
  return (
    typeof value.message_id === 'string' &&
    isAiMessageRole(value.role) &&
    isAiIntent(value.intent) &&
    typeof value.content === 'string' &&
    (value.status === 'completed' ||
      value.status === 'streaming' ||
      value.status === 'waiting_input' ||
      value.status === 'processing' ||
      value.status === 'failed') &&
    (typeof pendingAction === 'undefined' ||
      pendingAction === null ||
      isPendingAction(pendingAction)) &&
    (typeof artifact === 'undefined' || artifact === null || isAssistantArtifact(artifact)) &&
    (typeof actions === 'undefined' ||
      (Array.isArray(actions) && actions.every(isAssistantActionButton))) &&
    (typeof reasoningTrace === 'undefined' ||
      (Array.isArray(reasoningTrace) && reasoningTrace.every(isAssistantReasoningStep))) &&
    typeof value.created_at === 'string' &&
    Array.isArray(value.references) &&
    value.references.every(isMessageReference)
  );
}

function isAssistantReasoningStep(item: unknown): item is AiAssistantReasoningStep {
  if (typeof item !== 'object' || item === null) {
    return false;
  }

  const value = item as Record<string, unknown>;
  const toolArgs = value.tool_args;
  return (
    (value.step_type === 'thought' || value.step_type === 'action' || value.step_type === 'observation') &&
    typeof value.content === 'string' &&
    (typeof value.tool_name === 'string' || value.tool_name === null || typeof value.tool_name === 'undefined') &&
    (typeof toolArgs === 'undefined' ||
      toolArgs === null ||
      (typeof toolArgs === 'object' && !Array.isArray(toolArgs))) &&
    (value.status === 'success' ||
      value.status === 'error' ||
      value.status === null ||
      typeof value.status === 'undefined')
  );
}

function parseConversationMessage(data: unknown): AiConversationMessage {
  if (!isConversationMessage(data)) {
    throw new Error('Unexpected AI response shape.');
  }
  return data;
}

function assertMessagesShape(data: unknown): asserts data is AiConversationMessage[] {
  if (!Array.isArray(data) || !data.every(isConversationMessage)) {
    throw new Error('Unexpected AI response shape.');
  }
}

function assertSendMessageShape(data: unknown): asserts data is SendAiConversationMessageResponse {
  if (typeof data !== 'object' || data === null) {
    throw new Error('Unexpected AI response shape.');
  }

  const value = data as Record<string, unknown>;
  if (typeof value.conversation_id !== 'string' || !Array.isArray(value.messages)) {
    throw new Error('Unexpected AI response shape.');
  }

  if (!value.messages.every(isConversationMessage)) {
    throw new Error('Unexpected AI response shape.');
  }
}

export async function createAiConversation(): Promise<AiConversation> {
  const response = await apiFetch('/api/ai/conversations', {
    method: 'POST'
  });

  if (!response.ok) {
    await parseError(response);
  }

  const data = await response.json();
  assertConversationShape(data);
  return data;
}

export async function fetchLatestAiConversation(): Promise<AiConversation | null> {
  const response = await apiFetch('/api/ai/conversations/latest');

  if (!response.ok) {
    await parseError(response);
  }

  const data = await response.json();
  if (data === null) {
    return null;
  }

  assertConversationShape(data);
  return data;
}

export async function fetchAiConversationMessages(
  conversationId: string
): Promise<AiConversationMessage[]> {
  const response = await apiFetch(`/api/ai/conversations/${conversationId}/messages`);

  if (!response.ok) {
    await parseError(response);
  }

  const data = await response.json();
  assertMessagesShape(data);
  return data;
}

export async function clearAiConversation(conversationId: string): Promise<void> {
  const response = await apiFetch(`/api/ai/conversations/${conversationId}/clear`, {
    method: 'POST'
  });

  if (!response.ok) {
    await parseError(response);
  }
}

export async function sendAiConversationMessage(
  conversationId: string,
  payload: SendAiConversationMessageRequest
): Promise<SendAiConversationMessageResponse> {
  const response = await apiFetch(`/api/ai/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    await parseError(response);
  }

  const data = await response.json();
  assertSendMessageShape(data);
  return data;
}

export async function resumeAiConversationMessage(
  conversationId: string,
  payload: ResumeAiConversationMessageRequest
): Promise<AiConversationMessage> {
  const actionId = payload.actionId.trim();
  if (!actionId || payload.payload.uploadId <= 0) {
    throw new Error('Invalid AI resume payload.');
  }
  const response = await apiFetch(`/api/ai/conversations/${conversationId}/messages/resume`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      ...payload,
      actionId
    })
  });

  if (!response.ok) {
    await parseError(response);
  }

  return parseConversationMessage(await response.json());
}

function applyStreamEvent(
  eventName: string,
  data: unknown,
  handlers: StreamAiConversationHandlers
) {
  if (eventName === 'assistant_debug') {
    if (typeof data !== 'object' || data === null) {
      return;
    }

    const value = data as Record<string, unknown>;
    const stage = value.stage;
    const toolName = value.tool_name;
    const toolArgs = value.tool_args;
    const message = value.message;

    if (
      typeof stage !== 'string' ||
      typeof toolName !== 'string' ||
      typeof toolArgs !== 'object' ||
      toolArgs === null ||
      Array.isArray(toolArgs) ||
      (typeof message !== 'string' && typeof message !== 'undefined')
    ) {
      return;
    }

    handlers.onAssistantDebug?.({
      stage,
      tool_name: toolName,
      tool_args: toolArgs as AiAssistantDebugEvent['tool_args'],
      ...(typeof message === 'string' ? { message } : {})
    });
    return;
  }

  if (eventName === 'assistant_reasoning') {
    const step = (data as Record<string, unknown>).step;
    if (!isAssistantReasoningStep(step)) {
      return;
    }
    handlers.onAssistantReasoning?.(step);
    return;
  }

  if (typeof data !== 'object' || data === null) {
    throw new Error('Unexpected AI response shape.');
  }

  const value = data as Record<string, unknown>;
  if (eventName === 'user_message') {
    const message = value.message;
    if (!isConversationMessage(message)) {
      throw new Error('Unexpected AI response shape.');
    }
    handlers.onUserMessage?.(message);
    return;
  }

  if (eventName === 'assistant_start') {
    const intent = typeof value.intent === 'string' ? value.intent : null;
    handlers.onAssistantStart?.({ intent: intent as AiConversationMessage['intent'] });
    return;
  }

  if (eventName === 'assistant_delta') {
    if (typeof value.delta !== 'string') {
      throw new Error('Unexpected AI response shape.');
    }
    handlers.onAssistantDelta?.(value.delta);
    return;
  }

  if (eventName === 'assistant_done') {
    const message = value.message;
    if (!isConversationMessage(message)) {
      throw new Error('Unexpected AI response shape.');
    }
    handlers.onAssistantDone?.(message);
    return;
  }

  if (eventName === 'error') {
    const message = typeof value.message === 'string' ? value.message : 'AI 查询失败。';
    throw new Error(message);
  }
}

export async function streamAiConversationMessage(
  conversationId: string,
  payload: SendAiConversationMessageRequest,
  handlers: StreamAiConversationHandlers
): Promise<void> {
  const response = await apiFetch(`/api/ai/conversations/${conversationId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    await parseError(response);
  }

  if (!response.body) {
    throw new Error('AI 流式响应不可用。');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let hasTerminalEvent = false;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    let boundaryIndex = buffer.indexOf('\n\n');
    while (boundaryIndex >= 0) {
      const block = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);

      if (block.trim()) {
        let eventName = 'message';
        const dataLines: string[] = [];

        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
            continue;
          }
          if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trim());
          }
        }

        const data = dataLines.length ? JSON.parse(dataLines.join('\n')) : {};
        applyStreamEvent(eventName, data, handlers);
        if (eventName === 'assistant_done' || eventName === 'error') {
          hasTerminalEvent = true;
        }
      }

      boundaryIndex = buffer.indexOf('\n\n');
    }

    if (done) {
      break;
    }
  }

  if (!hasTerminalEvent) {
    throw new Error('AI 流式响应意外中断。');
  }
}
