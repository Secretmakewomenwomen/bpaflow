<script setup lang="ts">
import { computed } from 'vue';
import type { ArchitectureDocument } from '../data/seedDocument';
import { getThemeToggleLabel, type ThemeMode } from '../lib/theme';

const props = defineProps<{
  document: ArchitectureDocument;
  theme: ThemeMode;
  savingCanvas?: boolean;
  saveStatusText?: string;
  aiAssistantOpen?: boolean;
  user?: {
    username: string;
    tenant_id?: string;
  } | null;
}>();

defineEmits<{
  (event: 'toggle-theme'): void;
  (event: 'open-upload'): void;
  (event: 'logout'): void;
  (event: 'save-canvas'): void;
  (event: 'toggle-ai-assistant'): void;
}>();

const saveStatus = computed(() => props.saveStatusText || '尚未保存');
</script>

<template>
  <div class="app-header">
    <div class="app-header__top">
      <div class="header-brand">
        <a-button
          data-testid="ai-entry-button"
          :type="props.aiAssistantOpen ? 'primary' : 'default'"
          @click="$emit('toggle-ai-assistant')"
        >
          AI 助手
        </a-button>
        <div class="brand-mark">AW</div>
        <div>
          <a-typography-text type="secondary">架构工作台</a-typography-text>
          <h1>{{ document.title }}</h1>
        </div>
      </div>

      <div class="header-actions">
        <a-tag color="processing">{{ saveStatus }}</a-tag>
        <a-button @click="$emit('open-upload')">上传</a-button>
        <a-button @click="$emit('toggle-theme')">
          {{ getThemeToggleLabel(props.theme) }}
        </a-button>
        <a-button v-if="props.user" danger @click="$emit('logout')">退出登录</a-button>
        <a-button>导出 PNG</a-button>
        <a-button type="primary" :loading="props.savingCanvas" @click="$emit('save-canvas')">
          {{ props.savingCanvas ? '保存中...' : '保存画布' }}
        </a-button>
      </div>
    </div>

    <div class="header-status">
      <div v-if="props.user" class="header-stat">
        <span class="header-stat__label">当前用户</span>
        <strong>{{ props.user.username }}</strong>
      </div>
      <div v-if="props.user" class="header-stat">
        <span class="header-stat__label">当前租户</span>
        <strong>{{ props.user.tenant_id || 'default' }}</strong>
      </div>
      <div class="header-stat">
        <span class="header-stat__label">工作区</span>
        <strong>单人草稿</strong>
      </div>
      <div class="header-stat">
        <span class="header-stat__label">最近更新</span>
        <strong>{{ document.updatedAt }}</strong>
      </div>
      <div class="header-stat">
        <span class="header-stat__label">版本</span>
        <strong>{{ document.version }}</strong>
      </div>
    </div>
  </div>
</template>
