const textEntryTags = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

export function shouldHandleCanvasDeletion(event: KeyboardEvent): boolean {
  if (event.key !== 'Delete' && event.key !== 'Backspace') {
    return false;
  }

  const target = event.target as HTMLElement | null;
  if (!target) {
    return true;
  }

  if (textEntryTags.has(target.tagName) || target.isContentEditable) {
    return false;
  }

  return true;
}
