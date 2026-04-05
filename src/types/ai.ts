export type AiIntent =
  | 'general_chat'
  | 'rag_retrieval'
  | 'generate_flow_from_file';
export type AiMessageRole = 'user' | 'assistant';
export type AiReferenceType = 'snippet' | 'file';
export type AiMessageStatus =
  | 'completed'
  | 'streaming'
  | 'waiting_input'
  | 'processing'
  | 'failed';

export interface AiPendingActionCandidate {
  upload_id: number;
  file_name: string;
}

export interface AiPendingActionPayload {
  selection_mode: 'single';
  candidates: AiPendingActionCandidate[];
}

export interface AiPendingAction {
  action_id: string;
  action_type: 'select_file';
  payload: AiPendingActionPayload;
}

export interface AiAssistantArtifact {
  artifact_type: string;
  graph_payload: Record<string, unknown> | null;
  payload: Record<string, unknown>;
}

export interface AiAssistantActionButton {
  action_id: string;
  action_type: string;
  label: string;
}

export interface AiConversation {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string;
}

export interface AiConversationMessageReference {
  reference_type: AiReferenceType;
  upload_id: number | null;
  file_name: string;
  snippet_text: string | null;
  page_start: number | null;
  page_end: number | null;
  score: number | null;
  download_url: string | null;
}

export interface AiAssistantReasoningStep {
  step_type: 'thought' | 'action' | 'observation';
  content: string;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  status?: 'success' | 'error' | null;
}

export interface AiConversationMessage {
  message_id: string;
  role: AiMessageRole;
  intent: AiIntent | null;
  content: string;
  status: AiMessageStatus;
  pending_action?: AiPendingAction | null;
  artifact?: AiAssistantArtifact | null;
  actions?: AiAssistantActionButton[];
  created_at: string;
  references: AiConversationMessageReference[];
  reasoning_trace?: AiAssistantReasoningStep[];
}

export interface SendAiConversationMessageRequest {
  query: string;
}

export interface ResumeAiConversationMessageRequest {
  actionId: string;
  decision: 'confirm';
  payload: {
    uploadId: number;
  };
}

export interface SendAiConversationMessageResponse {
  conversation_id: string;
  messages: AiConversationMessage[];
}

export interface AiAssistantDebugEvent {
  stage: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  message?: string;
}

export interface StreamAiConversationHandlers {
  onUserMessage?: (message: AiConversationMessage) => void;
  onAssistantStart?: (payload: { intent?: AiIntent | null }) => void;
  onAssistantReasoning?: (step: AiAssistantReasoningStep) => void;
  onAssistantDebug?: (payload: AiAssistantDebugEvent) => void;
  onAssistantDelta?: (delta: string) => void;
  onAssistantDone?: (message: AiConversationMessage) => void;
}
