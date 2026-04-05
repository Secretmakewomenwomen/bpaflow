import { describe, expect, it } from 'vitest';
import { shouldHandleCanvasDeletion } from './keyboard';

describe('shouldHandleCanvasDeletion', () => {
  it('handles Delete on a neutral target', () => {
    const event = { key: 'Delete', target: null } as KeyboardEvent;

    expect(shouldHandleCanvasDeletion(event)).toBe(true);
  });

  it('handles Backspace on a neutral target', () => {
    const event = { key: 'Backspace', target: null } as KeyboardEvent;

    expect(shouldHandleCanvasDeletion(event)).toBe(true);
  });

  it('ignores deletion keys when an input is focused', () => {
    const event = {
      key: 'Delete',
      target: { tagName: 'INPUT', isContentEditable: false }
    } as KeyboardEvent;

    expect(shouldHandleCanvasDeletion(event)).toBe(false);
  });
});
