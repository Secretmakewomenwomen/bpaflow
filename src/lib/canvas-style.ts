export const SWIMLANE_STYLE =
  'shape=swimlane;rounded=1;arcSize=14;startSize=40;fillColor=#111826;swimlaneFillColor=#111826;gradientColor=none;strokeColor=#5f7397;fontColor=#e8edf7;fontSize=13;swimlaneLine=1;separatorColor=#334155;spacingLeft=16;horizontal=0;';

export function normalizeCanvasCellStyle(style: string | null | undefined) {
  if (!style) {
    return style ?? '';
  }

  if (style.includes('shape=swimlane')) {
    return SWIMLANE_STYLE;
  }

  return style;
}
