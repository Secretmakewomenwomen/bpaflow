import { describe, expect, it } from 'vitest';
import { buildCanvasSnapshotFromChapterFlow } from './chapter-flow-import';

describe('chapter flow import adapter', () => {
  it('imports graphPayload into a canvas snapshot', () => {
    const graphPayload = {
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
                responsibilities: ['提交申请', '补充材料']
              }
            },
            {
              id: '1.2',
              name: '方案评估',
              summary: '评估方案风险',
              metadata: {
                role: '评审委员',
                department: '风控部',
                owner: '李四',
                responsibilities: ['风险评估']
              }
            }
          ]
        }
      ],
      edges: [{ id: 'edge-1.1-1.2', source: '1.1', target: '1.2' }]
    };

    const snapshot = buildCanvasSnapshotFromChapterFlow(graphPayload);
    expect(snapshot.name).toBe('AI 导入流程图');
    expect(snapshot.xmlContent).toContain('<mxGraphModel');
    expect(snapshot.xmlContent).toContain('id="ai-lane-chapter-1"');
    expect(snapshot.xmlContent).toContain('id="ai-node-1-1"');
    expect(snapshot.xmlContent).toContain('id="ai-edge-edge-1-1-1-2"');
    expect(Object.keys(snapshot.nodeInfo)).toHaveLength(3);
    expect(snapshot.nodeInfo['ai-node-1-1']).toEqual(
      expect.objectContaining({
        title: '立项评审',
        position: '产品经理',
        department: '产品部',
        owner: '张三'
      })
    );
  });

  it('rewrites reserved and duplicate ids into unique mxGraph-safe ids', () => {
    const snapshot = buildCanvasSnapshotFromChapterFlow({
      lanes: [
        {
          id: '1',
          name: '第一章',
          children: [
            { id: '1', name: '步骤一' },
            { id: '1', name: '步骤二' }
          ]
        }
      ],
      edges: [{ id: '1', source: '1', target: '1' }]
    });

    expect(snapshot.xmlContent).toContain('id="0"');
    expect(snapshot.xmlContent).toContain('id="1" parent="0"');
    expect(snapshot.xmlContent).toContain('id="ai-lane-1"');
    expect(snapshot.xmlContent).toContain('id="ai-node-1"');
    expect(snapshot.xmlContent).toContain('id="ai-node-1-2"');
    expect(snapshot.xmlContent).toContain('id="ai-edge-1"');
    expect(snapshot.xmlContent).not.toContain('<mxCell id="1" value="第一章"');
    expect(snapshot.xmlContent).not.toContain('<mxCell id="1" value="步骤一"');
    expect(Object.keys(snapshot.nodeInfo)).toEqual(['ai-lane-1', 'ai-node-1', 'ai-node-1-2']);
  });
});
