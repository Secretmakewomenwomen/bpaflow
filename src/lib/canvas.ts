import type { CanvasRecord, CanvasSnapshotPayload, CanvasTreeNode } from '../types/canvas';
import { apiFetch } from './http';

const canvasApiBase = '/api/canvas';

async function parseCanvasResponse(response: Response, fallbackMessage: string) {
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(payload?.detail ?? fallbackMessage);
  }

  return payload as CanvasRecord;
}

async function parseCanvasNodeResponse(response: Response, fallbackMessage: string) {
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(payload?.detail ?? fallbackMessage);
  }

  return payload as CanvasTreeNode;
}

async function parseCanvasNodesResponse(response: Response, fallbackMessage: string) {
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new Error(payload?.detail ?? fallbackMessage);
  }

  return Array.isArray(payload) ? (payload as CanvasTreeNode[]) : [];
}

export async function saveCanvas(
  nodeId: string,
  payload: CanvasSnapshotPayload
): Promise<CanvasRecord> {
  const response = await apiFetch(`${canvasApiBase}?nodeId=${encodeURIComponent(nodeId)}`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });

  return parseCanvasResponse(response, '保存画布失败。');
}

export async function fetchCanvas(nodeId: string): Promise<CanvasRecord | null> {
  const response = await apiFetch(`${canvasApiBase}?nodeId=${encodeURIComponent(nodeId)}`);
  const payload = await parseCanvasResponse(response, '获取画布失败。');
  return payload.exists ? payload : null;
}

export async function fetchCanvasNodes(): Promise<CanvasTreeNode[]> {
  const response = await apiFetch(`${canvasApiBase}/nodes`);

  return parseCanvasNodesResponse(response, '获取节点树失败。');
}

export async function createCanvasNode(payload: {
  name: string;
  parentId?: string | null;
}): Promise<CanvasTreeNode> {
  const response = await apiFetch(`${canvasApiBase}/nodes`, {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      parentId: payload.parentId ?? null
    })
  });

  return parseCanvasNodeResponse(response, '创建节点失败。');
}
