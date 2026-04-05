import type { UploadedFileRecord } from '../types/upload';
import { apiFetch } from './http';

export const allowedUploadExtensions = ['docx', 'png', 'pdf'] as const;
export const maxUploadSize = 10 * 1024 * 1024;
const uploadApiBase = '/api/uploads';
const uploadWorkBase = '/api/work';

function getFileExtension(fileName: string) {
  const segments = fileName.split('.');
  return segments.length > 1 ? segments.at(-1)?.toLowerCase() ?? '' : '';
}

export function validateUploadFile(file: File): string | null {
  const extension = getFileExtension(file.name);
  if (!allowedUploadExtensions.includes(extension as (typeof allowedUploadExtensions)[number])) {
    return '仅支持上传 DOCX、PNG 和 PDF 文件。';
  }

  if (file.size > maxUploadSize) {
    return '文件大小不能超过 10 MB。';
  }

  return null;
}

export function buildUploadFormData(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return formData;
}

async function parseUploadResponse(response: Response) {
  if (response.ok) {
    return response.json() as Promise<UploadedFileRecord>;
  }

  let detail = 'Upload failed.';
  try {
    const payload = await response.json();
    detail = payload.detail ?? detail;
  } catch {
    detail = response.statusText || detail;
  }

  throw new Error(detail === 'Upload failed.' ? '上传失败。' : detail);
}

export async function uploadFile(file: File): Promise<UploadedFileRecord> {
  const response = await apiFetch(uploadApiBase, {
    method: 'POST',
    body: buildUploadFormData(file)
  });

  return parseUploadResponse(response);
}

export async function fetchRecentUploads(): Promise<UploadedFileRecord[]> {
  const response = await apiFetch(uploadApiBase);

  if (!response.ok) {
    throw new Error('获取最近上传记录失败。');
  }

  return response.json() as Promise<UploadedFileRecord[]>;
}

export async function deleteUploadedFile(uploadId: number): Promise<void> {
  const response = await apiFetch(`${uploadApiBase}/${uploadId}`, {
    method: 'DELETE'
  });

  if (response.ok) {
    return;
  }

  let detail = '删除失败。';
  try {
    const payload = await response.json();
    detail = payload.detail ?? detail;
  } catch {
    detail = response.statusText || detail;
  }

  throw new Error(detail);
}

export async function saveWorker(name: string, content: string, id: string | undefined = undefined) {
  const response = await apiFetch(uploadWorkBase, {
    method: 'POST',
    body: JSON.stringify({
      name,
      content,
      id
    }),
  });
  return response
}

export async function get_list_works() {
  const response = await apiFetch(uploadWorkBase, {
    method: 'GET'
  });
  return response;
}
