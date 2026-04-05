import type { CanvasSelection } from '../data/seedDocument';

export interface SelectionDraft {
  title: string;
  content: string;
  position: string;
  department: string;
  owner: string;
  duty: string;
}

export function normalizeSelection(selection: CanvasSelection): CanvasSelection {
  return {
    ...selection,
    title: selection.title ?? '',
    content: selection.content ?? selection.summary ?? '',
    position: selection.position ?? '',
    department: selection.department ?? '',
    owner: selection.owner ?? '',
    duty: selection.duty ?? '',
    tags: selection.tags ?? [],
    metrics: selection.metrics ?? [],
    notes: selection.notes ?? []
  };
}

export function applySelectionDraft(
  selection: CanvasSelection,
  draft: SelectionDraft
): CanvasSelection {
  const normalizedSelection = normalizeSelection(selection);
  const title = draft.title.trim() || normalizedSelection.title;
  const content = draft.content.trim() || normalizedSelection.content || '';
  const position = draft.position.trim() || normalizedSelection.position || '';
  const department = draft.department.trim() || normalizedSelection.department || '';
  const owner = draft.owner.trim() || normalizedSelection.owner || '';
  const duty = draft.duty.trim() || normalizedSelection.duty || '';

  return {
    ...normalizedSelection,
    title,
    content,
    position,
    department,
    owner,
    duty
  };
}
