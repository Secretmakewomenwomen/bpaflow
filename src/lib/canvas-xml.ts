export function normalizeCanvasXmlContent(xmlContent: string) {
  const trimmed = xmlContent.trim();

  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try {
      const parsed = JSON.parse(trimmed);
      if (typeof parsed === 'string') {
        return parsed;
      }
    } catch {
      return xmlContent;
    }
  }

  return xmlContent;
}

export function sanitizeCanvasXmlForDecode(xmlContent: string) {
  return normalizeCanvasXmlContent(xmlContent).replace(
    /<(?!mxCell\b)([A-Za-z_][\w:.-]*)([^>]*)\sid="[^"]*"([^>]*)>/g,
    (_match, tagName: string, beforeId: string, afterId: string) =>
      `<${tagName}${beforeId}${afterId}>`
  );
}
