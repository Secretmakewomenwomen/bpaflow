import { describe, expect, it } from 'vitest';
import { applySelectionDraft, normalizeSelection } from './selection';

describe('applySelectionDraft', () => {
  it('updates the inspector fields while preserving the rest of the selection', () => {
    const next = applySelectionDraft(
      {
        id: 'cell-1',
        title: 'Checkout Orchestrator',
        content: 'Coordinates transaction state.',
        position: '架构师',
        department: '平台部',
        owner: '张三',
        duty: '编排流程',
        tags: ['Service'],
        metrics: [{ label: 'Lane', value: 'Core Services' }],
        notes: ['Keep this node narrow.']
      },
      {
        title: 'Checkout Core',
        content: 'Coordinates transaction state and downstream dispatch.',
        position: '技术负责人',
        department: '交易中台',
        owner: '李四',
        duty: '协调交易状态'
      }
    );

    expect(next.title).toBe('Checkout Core');
    expect(next.content).toBe('Coordinates transaction state and downstream dispatch.');
    expect(next.position).toBe('技术负责人');
    expect(next.department).toBe('交易中台');
    expect(next.owner).toBe('李四');
    expect(next.duty).toBe('协调交易状态');
    expect(next.tags).toEqual(['Service']);
  });

  it('falls back to existing values when the draft is blank after trimming', () => {
    const next = applySelectionDraft(
      {
        id: 'cell-1',
        title: 'Policy Engine',
        content: 'Evaluates routing rules.',
        position: '工程师',
        department: '规则平台',
        owner: '王五',
        duty: '路由决策',
        tags: ['Service'],
        metrics: [],
        notes: []
      },
      {
        title: '   ',
        content: '  ',
        position: '   ',
        department: '   ',
        owner: '   ',
        duty: '   '
      }
    );

    expect(next.title).toBe('Policy Engine');
    expect(next.content).toBe('Evaluates routing rules.');
    expect(next.position).toBe('工程师');
    expect(next.department).toBe('规则平台');
    expect(next.owner).toBe('王五');
    expect(next.duty).toBe('路由决策');
  });
});

describe('normalizeSelection', () => {
  it('maps legacy summary data into content and fills new inspector fields', () => {
    const next = normalizeSelection({
      id: 'cell-1',
      title: 'Legacy Node',
      summary: 'Legacy summary',
      tags: ['legacy'],
      metrics: [{ label: '状态', value: '已存在' }],
      notes: ['from old payload']
    });

    expect(next.content).toBe('Legacy summary');
    expect(next.position).toBe('');
    expect(next.department).toBe('');
    expect(next.owner).toBe('');
    expect(next.duty).toBe('');
    expect(next.tags).toEqual(['legacy']);
  });
});
