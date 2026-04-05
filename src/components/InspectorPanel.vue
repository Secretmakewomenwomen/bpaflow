<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import type { CanvasSelection } from '../data/seedDocument';
import { applySelectionDraft, normalizeSelection } from '../lib/selection';

const props = defineProps<{
  selection: CanvasSelection;
  saving?: boolean;
}>();

const emit = defineEmits<{
  (event: 'close'): void;
  (event: 'update-selection', payload: CanvasSelection): void;
}>();

const form = reactive({
  title: '',
  content: '',
  position: '',
  department: '',
  owner: '',
  duty: ''
});

const canEdit = computed(() => props.selection.editable !== false);

watch(
  () => props.selection,
  (selection) => {
    const normalizedSelection = normalizeSelection(selection);
    form.title = normalizedSelection.title;
    form.content = normalizedSelection.content ?? '';
    form.position = normalizedSelection.position ?? '';
    form.department = normalizedSelection.department ?? '';
    form.owner = normalizedSelection.owner ?? '';
    form.duty = normalizedSelection.duty ?? '';
  },
  { immediate: true }
);

function handleSubmit() {
  if (!canEdit.value || props.saving) {
    return;
  }

  emit('update-selection', applySelectionDraft(props.selection, form));
}
</script>

<template>
  <div class="inspector-shell">
    <a-space direction="vertical" :size="16" class="inspector-stack">
      <div class="inspector-topbar">
        <div>
          <a-typography-text type="secondary">检查器</a-typography-text>
          <h2>{{ selection.title }}</h2>
        </div>
        <a-button @click="$emit('close')">关闭</a-button>
      </div>

      <a-form layout="vertical" class="inspector-form">
        <a-form-item label="标题">
          <a-input
            v-model:value="form.title"
            :disabled="!canEdit"
            placeholder="请输入节点标题"
          />
        </a-form-item>
        <a-form-item label="内容">
          <a-input
            v-model:value="form.content"
            :disabled="!canEdit"
            placeholder="请输入节点内容"
          />
        </a-form-item>
        <a-form-item label="岗位">
          <a-input
            v-model:value="form.position"
            :disabled="!canEdit"
            placeholder="请输入岗位"
          />
        </a-form-item>
        <a-form-item label="部门">
          <a-input
            v-model:value="form.department"
            :disabled="!canEdit"
            placeholder="请输入部门"
          />
        </a-form-item>
        <a-form-item label="责任人">
          <a-input
            v-model:value="form.owner"
            :disabled="!canEdit"
            placeholder="请输入责任人"
          />
        </a-form-item>
        <a-form-item label="职责">
          <a-input
            v-model:value="form.duty"
            :disabled="!canEdit"
            placeholder="请输入职责"
          />
        </a-form-item>
        <a-button
          v-if="canEdit"
          type="primary"
          block
          :loading="props.saving"
          :disabled="props.saving"
          @click="handleSubmit"
        >
          {{ props.saving ? '保存中...' : '应用修改' }}
        </a-button>
        <a-alert
          v-else
          type="info"
          show-icon
          message="请选择节点或泳道后再编辑节点信息。"
        />
      </a-form>

      <a-space wrap>
        <a-tag v-for="tag in selection.tags" :key="tag" color="blue">{{ tag }}</a-tag>
      </a-space>
    </a-space>
  </div>
</template>
