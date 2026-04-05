import { describe, expect, it } from 'vitest';
import { resolveCanvasBootstrapState } from './canvas-bootstrap';

describe('resolveCanvasBootstrapState', () => {
  it('uses saved mode when current user has a saved canvas', () => {
    expect(
      resolveCanvasBootstrapState({
        id: '1',
        name: '我的画布',
        xmlContent: '<mxGraphModel />',
        nodeInfo: {},
        createdAt: '2026-03-29T12:00:00',
        updatedAt: '2026-03-29T12:05:00'
      })
    ).toEqual({
      mode: 'saved',
      statusText: '已加载你的专属画布'
    });
  });

  it('falls back to seed mode when current user has no saved canvas', () => {
    expect(resolveCanvasBootstrapState(null)).toEqual({
      mode: 'seed',
      statusText: '当前账号还没有已保存画布'
    });
  });
});
