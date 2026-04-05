import { describe, expect, it, vi } from 'vitest';
import { createCanvasCellId, isMxReservedCellId } from './canvas-ids';

describe('canvas cell ids', () => {
  it('marks mx root ids as reserved', () => {
    expect(isMxReservedCellId('0')).toBe(true);
    expect(isMxReservedCellId('1')).toBe(true);
    expect(isMxReservedCellId('2')).toBe(false);
  });

  it('uses uuid when randomUUID is available', () => {
    const randomUuid = vi.fn(() => 'uuid-cell-id');
    vi.stubGlobal('crypto', { randomUUID: randomUuid });

    expect(createCanvasCellId()).toBe('uuid-cell-id');
  });
});
