const ROOT_CELL_IDS = new Set(['0', '1']);

export function isMxReservedCellId(id: string) {
  return ROOT_CELL_IDS.has(id);
}

export function createCanvasCellId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `cell-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}
