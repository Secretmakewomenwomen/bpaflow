export interface UploadedFileRecord {
  id: number;
  fileName: string;
  fileExt: string;
  mimeType: string;
  fileSize: number;
  url: string;
  vectorStatus: string;
  createdAt: string;
}

export interface UploadModalState {
  open: boolean;
  uploading: boolean;
  deletingUploadId: number | null;
  error: string;
  selectedFile: File | null;
  successRecord: UploadedFileRecord | null;
  recentUploads: UploadedFileRecord[];
}
