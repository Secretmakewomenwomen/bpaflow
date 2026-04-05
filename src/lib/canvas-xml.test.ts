import { describe, expect, it } from 'vitest';
import { normalizeCanvasXmlContent, sanitizeCanvasXmlForDecode } from './canvas-xml';

describe('normalizeCanvasXmlContent', () => {
  it('unwraps xml content when it was stored as a quoted json string', () => {
    const xml = '"<mxGraphModel><root><mxCell id=\\"0\\"/></root></mxGraphModel>"';

    expect(normalizeCanvasXmlContent(xml)).toBe(
      '<mxGraphModel><root><mxCell id="0"/></root></mxGraphModel>'
    );
  });
});

describe('sanitizeCanvasXmlForDecode', () => {
  it('removes duplicate ids from non-mxCell elements', () => {
    const xml =
      '<mxGraphModel><root><Object id="same-id"><mxCell id="same-id" value="A" vertex="1" parent="1" /></Object></root></mxGraphModel>';

    const sanitized = sanitizeCanvasXmlForDecode(xml);

    expect(sanitized).toContain('<mxCell id="same-id"');
    expect(sanitized).not.toContain('<Object id="same-id"');
  });
});
