<script setup lang="ts">
import { ref } from 'vue';
import type { UploadedFileRecord } from '../types/upload';

defineProps<{
  open: boolean;
  uploading: boolean;
  deletingUploadId: number | null;
  error: string;
  selectedFile: File | null;
  successRecord: UploadedFileRecord | null;
  recentUploads: UploadedFileRecord[];
}>();

defineEmits<{
  (event: 'close'): void;
  (event: 'delete-upload', uploadId: number): void;
  (event: 'select-file', file: File | null): void;
  (event: 'submit'): void;
}>();

const fileInputRef = ref<HTMLInputElement | null>(null);

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = '';
  return file;
}

function openFilePicker() {
  fileInputRef.value?.click();
}

function formatSize(size: number) {
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  return `${Math.round(size / 1024)} KB`;
}
</script>

<template>
  <a-modal
    :open="open"
    title="上传文件"
    width="760px"
    :confirm-loading="uploading"
    ok-text="开始上传"
    cancel-text="取消"
    :ok-button-props="{ disabled: !selectedFile }"
    @cancel="$emit('close')"
    @ok="$emit('submit')"
  >
    <a-space direction="vertical" :size="16" class="upload-modal-stack">
      <a-card size="small" title="选择文件">
        <a-space direction="vertical">
          <a-typography-text type="secondary">支持 DOCX、PNG、PDF，最大 10 MB。</a-typography-text>
          <div class="upload-select">
            <input
              ref="fileInputRef"
              class="upload-input"
              type="file"
              accept=".docx,.png,.pdf"
              @change="$emit('select-file', handleFileChange($event))"
            />
            <a-button @click="openFilePicker">选择文件</a-button>
          </div>
        </a-space>
      </a-card>

      <a-card size="small" title="当前文件">
        <a-space direction="vertical" :size="4">
          <strong>{{ selectedFile?.name ?? '未选择文件' }}</strong>
          <a-typography-text type="secondary">
            {{ selectedFile ? formatSize(selectedFile.size) : '请选择一个文档、图片或 PDF 文件。' }}
          </a-typography-text>
        </a-space>
      </a-card>

      <a-alert v-if="error" type="error" show-icon :message="error" />
      <a-alert v-if="successRecord" type="success" show-icon :message="successRecord.fileName" :description="successRecord.url" />

      <a-card size="small" title="历史记录">
        <a-list
          class="upload-recent"
          :data-source="recentUploads"
          size="small"
          :locale="{ emptyText: '暂无上传记录。' }"
        >
          <template #renderItem="{ item }">
            <a-list-item>
              <template #actions>
                <a-button
                  danger
                  size="small"
                  :loading="deletingUploadId === item.id"
                  :disabled="uploading || deletingUploadId !== null || item.vectorStatus === 'PROCESSING'"
                  @click="$emit('delete-upload', item.id)"
                >
                  {{ item.vectorStatus === 'PROCESSING' ? '处理中' : '删除' }}
                </a-button>
              </template>
              <a-list-item-meta
                :title="item.fileName"
                :description="`${item.fileExt.toUpperCase()} · ${formatSize(item.fileSize)} · ${item.vectorStatus}`"
              />
            </a-list-item>
          </template>
        </a-list>
      </a-card>
    </a-space>
  </a-modal>
</template>
<style>
.upload-recent {
  max-height: 200px;
  overflow: auto;
}

.upload-select {
  display: inline-flex;
}

.upload-input {
  display: none;
}
</style>
