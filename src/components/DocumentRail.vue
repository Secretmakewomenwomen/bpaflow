<script setup lang="ts">
import { computed } from 'vue';
import type { ArchitectureDocument } from '../data/seedDocument';
import type { CanvasTreeNode } from '../types/canvas';
import {
  paletteDragMimeType,
  paletteItems,
  type PaletteItemId
} from '../lib/palette';

const props = defineProps<{
  document: ArchitectureDocument;
  nodes: CanvasTreeNode[];
  activeNodeId: string | null;
}>();

const emit = defineEmits<{
  (event: 'select-node', nodeId: string): void;
  (event: 'create-root-node'): void;
  (event: 'create-child-node'): void;
}>();

function handleDragStart(event: DragEvent, itemId: PaletteItemId) {
  if (!event.dataTransfer) {
    return;
  }

  event.dataTransfer.effectAllowed = 'copy';
  event.dataTransfer.setData(paletteDragMimeType, itemId);
  event.dataTransfer.setData('text/plain', itemId);
}

const treeRows = computed(() => {
  const grouped = new Map<string | null, CanvasTreeNode[]>();

  for (const node of props.nodes) {
    const siblings = grouped.get(node.parentId) ?? [];
    siblings.push(node);
    grouped.set(node.parentId, siblings);
  }

  for (const siblings of grouped.values()) {
    siblings.sort((left, right) => {
      if (left.sortOrder !== right.sortOrder) {
        return left.sortOrder - right.sortOrder;
      }

      return left.createdAt.localeCompare(right.createdAt);
    });
  }

  const rows: Array<CanvasTreeNode & { depth: number }> = [];

  function visit(parentId: string | null, depth: number) {
    const siblings = grouped.get(parentId) ?? [];

    for (const node of siblings) {
      rows.push({
        ...node,
        depth
      });
      visit(node.id, depth + 1);
    }
  }

  visit(null, 0);
  return rows;
});
</script>

<template>
  <div class="rail-shell">
    <a-space direction="vertical" :size="16" class="rail-stack">
      <a-card size="small" title="节点树">
        <a-space direction="vertical" :size="12" class="rail-block">
          <div class="tree-actions">
            <a-button
              type="primary"
              size="small"
              data-testid="canvas-tree-create-root"
              @click="emit('create-root-node')"
            >
              新增根节点
            </a-button>
            <a-button
              size="small"
              :disabled="!activeNodeId"
              data-testid="canvas-tree-create-child"
              @click="emit('create-child-node')"
            >
              新增子节点
            </a-button>
          </div>

          <div v-if="treeRows.length > 0" class="tree-list">
            <button
              v-for="node in treeRows"
              :key="node.id"
              type="button"
              class="tree-node-button"
              :class="{ 'tree-node-button--active': node.id === activeNodeId }"
              :style="{ paddingLeft: `${16 + node.depth * 18}px` }"
              :data-testid="`canvas-tree-node-${node.id}`"
              @click="emit('select-node', node.id)"
            >
              <span class="tree-node-button__marker">{{ node.depth === 0 ? '●' : '└' }}</span>
              <span class="tree-node-button__label">{{ node.name }}</span>
            </button>
          </div>

          <a-typography-text v-else type="secondary">
            当前还没有节点，先创建一个根节点。
          </a-typography-text>
        </a-space>
      </a-card>

      <a-card size="small" title="组件面板">
        <a-space direction="vertical" :size="12" class="rail-block">
          <a-typography-text type="secondary">拖拽到画布</a-typography-text>
          <div class="palette-list">
            <div
              v-for="item in paletteItems"
              :key="item.id"
              class="palette-card"
              draggable="true"
              @dragstart="handleDragStart($event, item.id)"
            >
              <div class="palette-card__title">
                <strong>{{ item.label }}</strong>
                <a-tag color="blue">{{ item.badge }}</a-tag>
              </div>
              <a-typography-text type="secondary">{{ item.description }}</a-typography-text>
            </div>
          </div>
        </a-space>
      </a-card>

      <a-card size="small" title="当前状态">
        <a-descriptions size="small" :column="1">
          <a-descriptions-item v-for="checkpoint in document.checkpoints" :key="checkpoint.label" :label="checkpoint.label">
            {{ checkpoint.value }}
          </a-descriptions-item>
        </a-descriptions>
      </a-card>

      <a-card size="small" title="支持类型">
        <a-space wrap>
          <a-tag v-for="item in document.palette" :key="item">{{ item }}</a-tag>
        </a-space>
      </a-card>
    </a-space>
  </div>
</template>
