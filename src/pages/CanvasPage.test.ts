// @vitest-environment happy-dom

import { defineComponent, h } from 'vue';
import { mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CanvasPage from './CanvasPage.vue';
import type { CanvasSelection } from '../data/seedDocument';

const {
  createCanvasNodeMock,
  fetchCanvasMock,
  fetchCanvasNodesMock,
  saveCanvasMock
} = vi.hoisted(() => ({
  createCanvasNodeMock: vi.fn(),
  fetchCanvasMock: vi.fn(),
  fetchCanvasNodesMock: vi.fn(),
  saveCanvasMock: vi.fn()
}));

vi.mock('../lib/canvas', () => ({
  createCanvasNode: createCanvasNodeMock,
  fetchCanvas: fetchCanvasMock,
  fetchCanvasNodes: fetchCanvasNodesMock,
  saveCanvas: saveCanvasMock
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
  clearAuth: vi.fn()
}));

vi.mock('ant-design-vue', () => ({
  Modal: {
    confirm: vi.fn()
  }
}));

function flushPromises() {
  return new Promise<void>((resolve) => {
    setTimeout(resolve);
  });
}

function createPassthrough() {
  return defineComponent({
    name: 'PassThrough',
    setup(_, { slots }) {
      return () => h('div', slots.default?.());
    }
  });
}

const inspectorSelection: CanvasSelection = {
  id: 'cell-1',
  title: '节点A',
  content: '内容A',
  position: '岗位A',
  department: '部门A',
  owner: '责任人A',
  duty: '职责A',
  tags: [],
  metrics: [],
  notes: [],
  editable: true
};

function mountPage() {
  const passthrough = createPassthrough();
  const snapshot = {
    name: '默认节点',
    xmlContent: '<mxGraphModel />',
    nodeInfo: {
      'cell-1': {
        title: '节点A',
        content: '内容A',
        position: '岗位A',
        department: '部门A',
        owner: '责任人A',
        duty: '职责A',
        tags: [],
        metrics: [],
        notes: []
      }
    }
  };
  const architectureCanvasStub = defineComponent({
    name: 'ArchitectureCanvasStub',
    props: {
      initialSnapshot: {
        type: Object,
        default: null
      }
    },
    emits: ['selection-change', 'open-inspector', 'close-inspector'],
    methods: {
      applySelectionDraft(selection: CanvasSelection) {
        snapshot.nodeInfo['cell-1'] = {
          ...snapshot.nodeInfo['cell-1'],
          ...selection
        };
      },
      exportCanvasSnapshot() {
        return snapshot;
      },
      loadCanvasSnapshot: vi.fn()
    },
    render() {
      return h('div');
    }
  });

  const inspectorStub = defineComponent({
    name: 'InspectorPanelStub',
    emits: ['update-selection', 'close'],
    setup(_, { emit }) {
      return () =>
        h(
          'button',
          {
            type: 'button',
            'data-testid': 'emit-update-selection',
            onClick: () => emit('update-selection', inspectorSelection)
          },
          'emit-update-selection'
        );
    }
  });

  const aiAssistantPopoverStub = defineComponent({
    name: 'AiAssistantPopoverStub',
    emits: ['close', 'import-flow'],
    setup(_, { emit }) {
      return () =>
        h(
          'button',
          {
            type: 'button',
            'data-testid': 'emit-import-flow',
            onClick: () =>
              emit('import-flow', {
                name: 'AI 导入流程图',
                xmlContent: '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>',
                nodeInfo: {
                  'chapter-1': {
                    id: 'chapter-1',
                    title: '第一章 总则',
                    content: '',
                    position: '',
                    department: '',
                    owner: '',
                    duty: '',
                    tags: [],
                    metrics: [],
                    notes: []
                  }
                }
              })
          },
          'emit-import-flow'
        );
    }
  });

  return mount(CanvasPage, {
    global: {
      stubs: {
        ArchitectureCanvas: architectureCanvasStub,
        InspectorPanel: inspectorStub,
        DocumentRail: true,
        UploadModal: true,
        AiAssistantPopover: aiAssistantPopoverStub,
        AppHeader: true,
        'a-layout': passthrough,
        'a-layout-header': passthrough,
        'a-layout-sider': passthrough,
        'a-layout-content': passthrough,
        'a-drawer': passthrough
      }
    }
  });
}

describe('CanvasPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('saves the canvas after inspector updates a node', async () => {
    fetchCanvasNodesMock.mockResolvedValue([
      {
        id: 'tree-root-1',
        parentId: null,
        name: '默认节点',
        sortOrder: 0,
        createdAt: '2026-03-30T00:00:00Z',
        updatedAt: '2026-03-30T00:00:00Z'
      }
    ]);
    fetchCanvasMock.mockResolvedValue(null);
    createCanvasNodeMock.mockResolvedValue(undefined);
    saveCanvasMock.mockResolvedValue({
      id: 'canvas-1',
      nodeId: 'tree-root-1',
      exists: true,
      name: '默认节点',
      xmlContent: '<mxGraphModel />',
      nodeInfo: {},
      createdAt: '2026-03-30T00:00:00Z',
      updatedAt: '2026-03-30T00:00:00Z'
    });

    const wrapper = mountPage();
    await flushPromises();
    await flushPromises();

    await wrapper.get('[data-testid="emit-update-selection"]').trigger('click');
    await flushPromises();

    expect(saveCanvasMock).toHaveBeenCalledWith(
      'tree-root-1',
      expect.objectContaining({
        xmlContent: '<mxGraphModel />',
        nodeInfo: expect.objectContaining({
          'cell-1': expect.objectContaining({
            title: '节点A',
            content: '内容A',
            position: '岗位A',
            department: '部门A',
            owner: '责任人A',
            duty: '职责A'
          })
        })
      })
    );
  });

  it('loads imported flow snapshot from AI assistant', async () => {
    fetchCanvasNodesMock.mockResolvedValue([
      {
        id: 'tree-root-1',
        parentId: null,
        name: '默认节点',
        sortOrder: 0,
        createdAt: '2026-03-30T00:00:00Z',
        updatedAt: '2026-03-30T00:00:00Z'
      }
    ]);
    fetchCanvasMock.mockResolvedValue(null);
    createCanvasNodeMock.mockResolvedValue(undefined);
    saveCanvasMock.mockResolvedValue(undefined);

    const wrapper = mountPage();
    await flushPromises();
    await flushPromises();

    await wrapper.get('[data-testid="emit-import-flow"]').trigger('click');
    await flushPromises();

    const canvas = wrapper.findComponent({ name: 'ArchitectureCanvasStub' });
    expect(canvas.props('initialSnapshot')).toEqual({
      xmlContent: '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>',
      nodeInfo: {
        'chapter-1': {
          id: 'chapter-1',
          title: '第一章 总则',
          content: '',
          position: '',
          department: '',
          owner: '',
          duty: '',
          tags: [],
          metrics: [],
          notes: []
        }
      }
    });
  });
});
