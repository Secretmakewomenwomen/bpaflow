import { describe, expect, it } from 'vitest';
import { SWIMLANE_STYLE, normalizeCanvasCellStyle } from './canvas-style';

describe('normalizeCanvasCellStyle', () => {
  it('upgrades swimlane styles to the visible default style', () => {
    expect(
      normalizeCanvasCellStyle(
        'shape=swimlane;rounded=1;arcSize=14;startSize=40;fillColor=transparent;strokeColor=#2a3448;fontColor=#000000;'
      )
    ).toBe(SWIMLANE_STYLE);
  });

  it('keeps non-swimlane styles unchanged', () => {
    expect(normalizeCanvasCellStyle('rounded=1;fillColor=#101726;')).toBe(
      'rounded=1;fillColor=#101726;'
    );
  });
});
