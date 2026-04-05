import { describe, expect, it } from 'vitest';
import {
  createPaletteNodeTemplate,
  paletteItems,
  resolveDropPosition
} from './palette';

describe('paletteItems', () => {
  it('exposes draggable architecture node presets', () => {
    expect(paletteItems.map((item) => item.id)).toEqual([
      'swimlane',
      'service',
      'data-store',
      'external-system',
      'annotation'
    ]);
  });
});

describe('createPaletteNodeTemplate', () => {
  it('builds service metadata scoped to the selected lane', () => {
    const template = createPaletteNodeTemplate('service', '核心服务');

    expect(template.value).toBe('新服务');
    expect(template.meta.metrics[0]).toEqual({
      label: '泳道',
      value: '核心服务'
    });
    expect(template.width).toBe(180);
  });

  it('keeps swimlanes insertable at the root level', () => {
    const template = createPaletteNodeTemplate('swimlane');

    expect(template.parentBehavior).toBe('root-only');
    expect(template.value).toBe('新泳道');
    expect(template.height).toBe(380);
  });
});

describe('resolveDropPosition', () => {
  it('clamps new nodes inside the content area of a swimlane', () => {
    const point = resolveDropPosition(
      { width: 180, height: 72, parentBehavior: 'lane-or-root' },
      { x: 395, y: 110 },
      { x: 380, y: 0, width: 420, height: 660, startSize: 40 }
    );

    expect(point).toEqual({ x: 24, y: 74 });
  });

  it('centers root-level inserts around the drop point', () => {
    const point = resolveDropPosition(
      { width: 180, height: 84, parentBehavior: 'lane-or-root' },
      { x: 500, y: 320 }
    );

    expect(point).toEqual({ x: 410, y: 278 });
  });
});
