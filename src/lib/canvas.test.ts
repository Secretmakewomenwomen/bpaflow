import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createCanvasNode, fetchCanvas, fetchCanvasNodes, saveCanvas } from './canvas';
import { apiFetch } from './http';

vi.mock('./http', () => ({
  apiFetch: vi.fn()
}));

describe('canvas api helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('posts xml and node info to the canvas api', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          id: '1',
          nodeId: 'tree-node-1',
          exists: true,
          name: '我的画布',
          xmlContent: '<mxGraphModel />',
          nodeInfo: { 'node-1': { title: '服务A', content: '节点内容', position: '', department: '', owner: '', duty: '' } },
          createdAt: '2026-03-29T12:00:00',
          updatedAt: '2026-03-29T12:05:00'
        }),
        { status: 200 }
      )
    );

    await saveCanvas('tree-node-1', {
      name: '我的画布',
      xmlContent: '<mxGraphModel />',
      nodeInfo: {
        'node-1': {
          title: '服务A',
          content: '节点内容',
          position: '',
          department: '',
          owner: '',
          duty: ''
        }
      }
    });

    expect(apiFetch).toHaveBeenCalledWith('/api/canvas?nodeId=tree-node-1', {
      method: 'POST',
      body: JSON.stringify({
        name: '我的画布',
        xmlContent: '<mxGraphModel />',
        nodeInfo: {
          'node-1': {
            title: '服务A',
            content: '节点内容',
            position: '',
            department: '',
            owner: '',
            duty: ''
          }
        }
      })
    });
  });

  it('returns null when the current user has no saved canvas', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          id: '',
          nodeId: 'tree-node-1',
          exists: false,
          name: '',
          xmlContent: '',
          nodeInfo: {},
          createdAt: '2026-03-29T12:00:00',
          updatedAt: '2026-03-29T12:05:00'
        }),
        { status: 200 }
      )
    );

    const result = await fetchCanvas('tree-node-1');

    expect(result).toBeNull();
  });

  it('loads canvas tree nodes for the current user', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: 'tree-root-1',
            parentId: null,
            name: '根节点',
            sortOrder: 0,
            createdAt: '2026-03-30T00:00:00Z',
            updatedAt: '2026-03-30T00:00:00Z'
          },
          {
            id: 'tree-child-1',
            parentId: 'tree-root-1',
            name: '子节点',
            sortOrder: 0,
            createdAt: '2026-03-30T00:01:00Z',
            updatedAt: '2026-03-30T00:01:00Z'
          }
        ]),
        { status: 200 }
      )
    );

    const result = await fetchCanvasNodes();

    expect(apiFetch).toHaveBeenCalledWith('/api/canvas/nodes');
    expect(result[1].parentId).toBe('tree-root-1');
  });

  it('creates a child tree node', async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 'tree-child-2',
          parentId: 'tree-root-1',
          name: '理赔流程',
          sortOrder: 1,
          createdAt: '2026-03-30T00:02:00Z',
          updatedAt: '2026-03-30T00:02:00Z'
        }),
        { status: 200 }
      )
    );

    const result = await createCanvasNode({ name: '理赔流程', parentId: 'tree-root-1' });

    expect(apiFetch).toHaveBeenCalledWith('/api/canvas/nodes', {
      method: 'POST',
      body: JSON.stringify({
        name: '理赔流程',
        parentId: 'tree-root-1'
      })
    });
    expect(result.parentId).toBe('tree-root-1');
  });
});
