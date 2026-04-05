import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  allowedUploadExtensions,
  buildUploadFormData,
  deleteUploadedFile,
  maxUploadSize,
  validateUploadFile
} from './upload';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('upload helpers', () => {
  it('declares the supported upload extensions', () => {
    expect(allowedUploadExtensions).toEqual(['docx', 'png', 'pdf']);
  });

  it('rejects files larger than 10 MB', () => {
    const file = new File([new Uint8Array(maxUploadSize + 1)], 'diagram.pdf', {
      type: 'application/pdf'
    });

    expect(validateUploadFile(file)).toBe('文件大小不能超过 10 MB。');
  });

  it('builds a form data payload with the file field', () => {
    const file = new File(['demo'], 'diagram.pdf', { type: 'application/pdf' });
    const payload = buildUploadFormData(file);

    expect(payload.get('file')).toBe(file);
  });

  it('deletes uploaded file records through the backend api', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 204 })
    );

    await deleteUploadedFile(9);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0]?.[0]).toBe('/api/uploads/9');
    expect(fetchSpy.mock.calls[0]?.[1]).toMatchObject({
      method: 'DELETE'
    });
  });
});
