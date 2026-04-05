<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  defaultSelection,
  type CanvasSelection,
  type GraphCellMetadata
} from '../data/seedDocument';
import { createCanvasCellId } from '../lib/canvas-ids';
import { normalizeCanvasCellStyle, SWIMLANE_STYLE } from '../lib/canvas-style';
import { sanitizeCanvasXmlForDecode } from '../lib/canvas-xml';
import { shouldHandleCanvasDeletion } from '../lib/keyboard';
import { getMxgraph } from '../lib/mxgraph';
import {
  createPaletteNodeTemplate,
  paletteDragMimeType,
  resolveDropPosition,
  type PaletteItemId
} from '../lib/palette';
import { applySelectionDraft, normalizeSelection } from '../lib/selection';
import type { CanvasSnapshotPayload } from '../types/canvas';

const props = defineProps<{
  documentTitle: string;
  initialSnapshot?: Pick<CanvasSnapshotPayload, 'xmlContent' | 'nodeInfo'> | null;
}>();

const emit = defineEmits<{
  (event: 'close-inspector'): void;
  (event: 'open-inspector'): void;
  (event: 'selection-change', payload: CanvasSelection | null): void;
}>();

const graphContainer = ref<HTMLDivElement | null>(null);
const graphInstance = ref<any>(null);
const zoomLevel = ref(100);
const isDropActive = ref(false);

const canvasLabel = computed(() => `${props.documentTitle} canvas`);

function syncSelection(cell: any) {
  const meta = (cell as GraphCellMetadata | undefined)?.meta;
  if (!meta) {
    emit('selection-change', null);
    return;
  }

  emit('selection-change', {
    ...normalizeSelection(meta),
    id: cell.getId?.() ?? meta.id,
    editable: true
  });
}

function updateZoom() {
  if (!graphInstance.value) {
    return;
  }

  zoomLevel.value = Math.round(graphInstance.value.view.scale * 100);
}

function findSwimlane(cell: any) {
  const graph = graphInstance.value;
  let current = cell;

  while (graph && current) {
    if (graph.isSwimlane(current)) {
      return current;
    }

    current = current.getParent?.();
  }

  return null;
}

function resolveInsertParent() {
  const graph = graphInstance.value;

  if (!graph) {
    return null;
  }

  const selection = graph.getSelectionCell();

  if (selection && graph.isSwimlane(selection)) {
    return selection;
  }

  if (selection?.getParent && graph.isSwimlane(selection.getParent())) {
    return selection.getParent();
  }

  return graph.getDefaultParent();
}

function addService() {
  if (!graphInstance.value) {
    return;
  }

  const graph = graphInstance.value;
  const parent = resolveInsertParent();

  if (!parent) {
    return;
  }

  graph.getModel().beginUpdate();

  try {
    const cell = graph.insertVertex(
      parent,
      createCanvasCellId(),
      '新服务',
      220,
      540,
      180,
      72,
      'rounded=1;arcSize=18;fillColor=#101726;strokeColor=#3f6ef6;strokeWidth=1.2;fontColor=#f5f7fb;fontSize=14;shadow=0;spacing=12;whiteSpace=wrap;'
    );

    (cell as GraphCellMetadata).meta = {
      title: '新服务',
      summary: '新插入到当前架构画布中的应用服务节点。',
      tags: ['服务', '草稿'],
      metrics: [
        { label: '泳道', value: parent === graph.getDefaultParent() ? '未归属' : '当前泳道' },
        { label: '状态', value: '草稿' },
        { label: '归属', value: '架构设计' }
      ],
      notes: [
        '请将该节点连接到上游链路。',
        '如果属于某个运行时边界，请拖入对应泳道。',
        '尽量使用简洁标签保证可读性。'
      ]
    };

    graph.setSelectionCell(cell);
  } finally {
    graph.getModel().endUpdate();
  }
}

function addStore() {
  if (!graphInstance.value) {
    return;
  }

  const graph = graphInstance.value;
  const parent = resolveInsertParent();

  if (!parent) {
    return;
  }

  graph.getModel().beginUpdate();

  try {
    const cell = graph.insertVertex(
      parent,
      createCanvasCellId(),
      '新存储',
      440,
      540,
      180,
      84,
      'shape=cylinder3;boundedLbl=1;size=14;fillColor=#0f1622;strokeColor=#8b94a7;strokeWidth=1.2;fontColor=#ecf0f7;fontSize=13;whiteSpace=wrap;'
    );

    (cell as GraphCellMetadata).meta = {
      title: '新存储',
      summary: '用于持久化、缓存或事件沉淀的有状态端点。',
      tags: ['数据存储', '草稿'],
      metrics: [
        { label: '泳道', value: parent === graph.getDefaultParent() ? '未归属' : '当前泳道' },
        { label: '状态', value: '草稿' },
        { label: '一致性', value: '待确定' }
      ],
      notes: [
        '数据存储应作为链路中的终点节点。',
        '请与服务节点保持明显区分以提升可读性。',
        '异步沉淀系统应与事务数据库分开建模。'
      ]
    };

    graph.setSelectionCell(cell);
  } finally {
    graph.getModel().endUpdate();
  }
}

function addSwimlane() {
  if (!graphInstance.value) {
    return;
  }

  const graph = graphInstance.value;
  const parent = graph.getDefaultParent();

  graph.getModel().beginUpdate();

  try {
    const lane = graph.insertVertex(
      parent,
      createCanvasCellId(),
      '新泳道',
      1180,
      80,
      320,
      380,
      SWIMLANE_STYLE
    );

    (lane as GraphCellMetadata).meta = {
      title: '新泳道',
      summary: '用于表达系统、环境或组织归属的纵向边界。',
      tags: ['泳道', '边界'],
      metrics: [
        { label: '宽度', value: '320 px' },
        { label: '用途', value: '待定义' },
        { label: '状态', value: '草稿' }
      ],
      notes: [
        '泳道数量应尽量克制，保证结构清晰。',
        '泳道更适合表达归属或运行上下文，而不是所有分类。',
        '建议将同一泳道内的服务保持对齐。'
      ]
    };

    graph.setSelectionCell(lane);
  } finally {
    graph.getModel().endUpdate();
  }
}

function insertDraggedNode(itemId: PaletteItemId, event: DragEvent) {
  if (!graphInstance.value || !graphContainer.value) {
    return;
  }

  const graph = graphInstance.value;
  const { mxUtils } = getMxgraph();
  const containerPoint = mxUtils.convertPoint(
    graph.container,
    event.clientX,
    event.clientY
  );
  const hoveredCell = graph.getCellAt(containerPoint.x, containerPoint.y);
  const swimlane = findSwimlane(hoveredCell);
  const translate = graph.getView().translate;
  const scale = graph.getView().scale;
  const graphPoint = {
    x: containerPoint.x / scale - translate.x,
    y: containerPoint.y / scale - translate.y
  };
  const laneLabel =
    swimlane && typeof swimlane.value === 'string' ? swimlane.value : '未归属';
  const template = createPaletteNodeTemplate(itemId, laneLabel);
  const parent =
    template.parentBehavior === 'root-only'
      ? graph.getDefaultParent()
      : (swimlane ?? graph.getDefaultParent());
  const geometry = swimlane?.getGeometry?.();
  const point = resolveDropPosition(
    template,
    graphPoint,
    geometry
      ? {
          x: geometry.x,
          y: geometry.y,
          width: geometry.width,
          height: geometry.height,
          startSize: 40
        }
      : undefined
  );

  graph.getModel().beginUpdate();

  try {
    const cell = graph.insertVertex(
      parent,
      createCanvasCellId(),
      template.value,
      point.x,
      point.y,
      template.width,
      template.height,
      template.style
    );

    (cell as GraphCellMetadata).meta = {
      ...template.meta,
      id: cell.getId?.(),
      editable: true
    };
    graph.setSelectionCell(cell);
    graph.scrollCellToVisible(cell);
    syncSelection(cell);
  } finally {
    graph.getModel().endUpdate();
  }
}

function handlePaletteDragOver(event: DragEvent) {
  event.preventDefault();
  isDropActive.value = true;

  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy';
  }
}

function handlePaletteDragLeave(event: DragEvent) {
  if (event.currentTarget === event.target) {
    isDropActive.value = false;
  }
}

function handlePaletteDrop(event: DragEvent) {
  event.preventDefault();
  isDropActive.value = false;

  const itemId = event.dataTransfer?.getData(paletteDragMimeType) as PaletteItemId | '';

  if (!itemId) {
    return;
  }

  insertDraggedNode(itemId, event);
}

function zoomIn() {
  graphInstance.value?.zoomIn();
  updateZoom();
}

function zoomOut() {
  graphInstance.value?.zoomOut();
  updateZoom();
}

function fitCanvas() {
  graphInstance.value?.fit();
  updateZoom();
}

function removeSelectedCells() {
  const graph = graphInstance.value;
  const selectedCells = graph?.getSelectionCells?.() ?? [];

  if (!graph || selectedCells.length === 0) {
    return;
  }

  graph.removeCells(selectedCells);
  emit('selection-change', null);
  emit('close-inspector');
}

function handleWindowKeydown(event: KeyboardEvent) {
  if (!shouldHandleCanvasDeletion(event)) {
    return;
  }

  const graph = graphInstance.value;
  if (!graph?.getSelectionCount?.()) {
    return;
  }

  event.preventDefault();
  removeSelectedCells();
}

onMounted(() => {
  if (!graphContainer.value) {
    return;
  }

  const {
    mxConstants,
    mxEdgeStyle,
    mxEvent,
    mxGraph,
    mxRubberband
  } = getMxgraph();

  const graph = new mxGraph(graphContainer.value);
  graphInstance.value = graph;

  new mxRubberband(graph);

  graph.setPanning(true);
  graph.setTooltips(true);
  graph.setConnectable(true);
  graph.setAllowDanglingEdges(false);
  graph.setCellsResizable(true);
  graph.setHtmlLabels(true);
  graph.setAutoSizeCells(true);
  graph.panningHandler.useLeftButtonForPanning = false;
  graph.centerZoom = false;
  graph.setCellsBendable(false);
  graph.setCellsEditable(false);
  graph.getView().setTranslate(30, 18);
  mxEvent.disableContextMenu(graphContainer.value);

  graph.setVertexLabelsMovable(false);
  graph.setEdgeLabelsMovable(false);

  const defaultEdgeStyle = graph.getStylesheet().getDefaultEdgeStyle();
  defaultEdgeStyle[mxConstants.STYLE_STROKECOLOR] = '#7f8da3';
  defaultEdgeStyle[mxConstants.STYLE_STROKEWIDTH] = 1.3;
  defaultEdgeStyle[mxConstants.STYLE_EDGE] = mxEdgeStyle.OrthConnector;
  defaultEdgeStyle[mxConstants.STYLE_ROUNDED] = 1;
  defaultEdgeStyle[mxConstants.STYLE_CURVED] = 0;
  defaultEdgeStyle[mxConstants.STYLE_ENDARROW] = mxConstants.ARROW_BLOCK;
  defaultEdgeStyle[mxConstants.STYLE_ENDSIZE] = 8;

  if (props.initialSnapshot) {
    loadCanvasSnapshot(props.initialSnapshot);
  } else {
    // createSeedCells(graph);
  }
  graph.getSelectionModel().addListener(mxEvent.CHANGE, () => {
    const cell = graph.getSelectionCell();
    syncSelection(cell);
  });
  graph.addListener(mxEvent.DOUBLE_CLICK, (_sender: unknown, eventObject: any) => {
    const cell = eventObject.getProperty('cell');

    if (!cell || !graph.getModel().isVertex(cell)) {
      return;
    }

    syncSelection(cell);
    emit('open-inspector');
    eventObject.consume();
  });
  window.addEventListener('keydown', handleWindowKeydown);

  emit('selection-change', null);
  updateZoom();
});

function applySelectionToGraph(selection: CanvasSelection) {
  const graph = graphInstance.value;
  const cell = graph?.getSelectionCell?.();

  if (!graph || !cell || selection.id !== cell.getId?.()) {
    return;
  }

  const currentMeta = normalizeSelection((cell as GraphCellMetadata).meta ?? defaultSelection);
  const nextMeta = {
    ...applySelectionDraft(currentMeta, selection),
    id: cell.getId?.(),
    editable: true
  };

  graph.getModel().beginUpdate();

  try {
    graph.cellLabelChanged(cell, nextMeta.title, false);
    (cell as GraphCellMetadata).meta = nextMeta;
  } finally {
    graph.getModel().endUpdate();
  }

  syncSelection(cell);
}

function collectNodeInfo(): CanvasSnapshotPayload['nodeInfo'] {
  const graph = graphInstance.value;
  const cells = graph?.getModel?.().cells;
  const nodeInfo: CanvasSnapshotPayload['nodeInfo'] = {};

  if (!cells) {
    return nodeInfo;
  }

  for (const cell of Object.values(cells)) {
    const typedCell = cell as GraphCellMetadata & { getId?: () => string };
    const cellId = typedCell.getId?.();

    if (!cellId || !typedCell.meta) {
      continue;
    }

    nodeInfo[cellId] = {
      ...normalizeSelection(typedCell.meta),
      id: cellId
    };
  }

  return nodeInfo;
}

function exportCanvasSnapshot(documentTitle: string): CanvasSnapshotPayload | null {
  const graph = graphInstance.value;

  if (!graph) {
    return null;
  }

  const cells = Object.values(graph.getModel().cells ?? {}) as Array<GraphCellMetadata>;
  const metaSnapshots = new Map<GraphCellMetadata, CanvasSelection>();

  for (const cell of cells) {
    if (!cell.meta) {
      continue;
    }

    metaSnapshots.set(cell, cell.meta);
    delete cell.meta;
  }

  const { mxCodec, mxUtils } = getMxgraph();
  let xmlContent = '';

  try {
    const codec = new mxCodec();
    const node = codec.encode(graph.getModel());
    xmlContent = mxUtils.getXml(node);
  } finally {
    for (const [cell, meta] of metaSnapshots.entries()) {
      cell.meta = meta;
    }
  }

  return {
    name: documentTitle,
    xmlContent,
    nodeInfo: collectNodeInfo()
  };
}

function loadCanvasSnapshot(snapshot: Pick<CanvasSnapshotPayload, 'xmlContent' | 'nodeInfo'>) {
  const graph = graphInstance.value;
  if (!graph) {
    return;
  }

  const { mxCodec, mxCodecRegistry, mxGraphModel, mxUtils } = getMxgraph();
  const normalizedXmlContent = sanitizeCanvasXmlForDecode(snapshot.xmlContent);
  const xml = mxUtils.parseXml(normalizedXmlContent);
  const nextModel = new mxGraphModel();
  const codec = new mxCodec(xml);
  const modelCodec = mxCodecRegistry.getCodec(mxGraphModel);
  modelCodec.decode(codec, xml.documentElement, nextModel);

  const model = graph.getModel();
  model.setRoot(nextModel.getRoot());

  const cells = model.cells ?? {};

  for (const cell of Object.values(cells)) {
    const typedCell = cell as GraphCellMetadata & { getId?: () => string };
    const cellId = typedCell.getId?.();

    if ('style' in typedCell) {
      typedCell.style = normalizeCanvasCellStyle((typedCell as { style?: string }).style);
    }

    if (!cellId || !snapshot.nodeInfo[cellId]) {
      continue;
    }

    typedCell.meta = {
      ...normalizeSelection(snapshot.nodeInfo[cellId]),
      id: cellId
    };
  }

  graph.clearSelection();
  graph.view.revalidate();
  graph.view.validate();
  graph.sizeDidChange();
  graph.refresh();

  emit('selection-change', null);
  updateZoom();
}

defineExpose({
  applySelectionDraft(selection: CanvasSelection) {
    applySelectionToGraph(selection);
  },
  exportCanvasSnapshot(documentTitle: string) {
    return exportCanvasSnapshot(documentTitle);
  },
  loadCanvasSnapshot(snapshot: Pick<CanvasSnapshotPayload, 'xmlContent' | 'nodeInfo'>) {
    loadCanvasSnapshot(snapshot);
  }
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleWindowKeydown);
  graphInstance.value?.destroy();
  graphInstance.value = null;
});
</script>

<template>
  <section class="canvas-shell">
    <header class="canvas-header">
      <div>
        <a-typography-text type="secondary">架构画布</a-typography-text>
        <h2>{{ documentTitle }}</h2>
      </div>

      <div class="canvas-toolbar">
        <a-button @click="addSwimlane">新增泳道</a-button>
        <a-button @click="addService">新增服务</a-button>
        <a-button @click="addStore">新增存储</a-button>
        <a-button @click="zoomOut">-</a-button>
        <span class="zoom-readout">{{ zoomLevel }}%</span>
        <a-button @click="zoomIn">+</a-button>
        <a-button type="primary" ghost @click="fitCanvas">适配画布</a-button>
      </div>
    </header>

    <div class="canvas-frame">
      <div
        class="canvas-grid"
        :class="{ 'canvas-grid--drop-active': isDropActive }"
        @dragover="handlePaletteDragOver"
        @dragenter.prevent="isDropActive = true"
        @dragleave="handlePaletteDragLeave"
        @drop="handlePaletteDrop"
      >
        <div ref="graphContainer" class="graph-surface" :aria-label="canvasLabel" />
      </div>
    </div>
  </section>
</template>
