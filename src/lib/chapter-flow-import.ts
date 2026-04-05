import { SWIMLANE_STYLE } from './canvas-style';
import type { CanvasSnapshotPayload, CanvasNodeInfo } from '../types/canvas';

type ChapterFlowLane = {
  id: string;
  name: string;
  order?: number;
  children?: ChapterFlowNode[];
};

type ChapterFlowNode = {
  id: string;
  name: string;
  summary?: string;
  metadata?: {
    role?: string | null;
    department?: string | null;
    owner?: string | null;
    responsibilities?: string[] | null;
  };
};

type ChapterFlowEdge = {
  id: string;
  source: string;
  target: string;
};

type ChapterFlowGraphPayload = {
  lanes?: ChapterFlowLane[];
  edges?: ChapterFlowEdge[];
};

const NODE_STYLE =
  'rounded=1;arcSize=18;fillColor=#101726;strokeColor=#3f6ef6;strokeWidth=1.2;fontColor=#f5f7fb;fontSize=14;shadow=0;spacing=12;whiteSpace=wrap;';
const EDGE_STYLE =
  'edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#7c8aa5;strokeWidth=1.2;endArrow=block;endFill=1;';
const LANE_WIDTH = 320;
const LANE_GAP = 40;
const LANE_START_X = 40;
const LANE_START_Y = 40;
const LANE_START_SIZE = 40;
const NODE_X = 24;
const NODE_Y = 72;
const NODE_WIDTH = 220;
const NODE_HEIGHT = 72;
const NODE_GAP_Y = 28;
const LANE_PADDING_BOTTOM = 40;

type CellIdFactory = {
  createLaneId(rawId: string): string;
  createNodeId(rawId: string): string;
  createEdgeId(rawId: string): string;
};

function escapeXml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function normalizeGraphPayload(graphPayload: unknown): ChapterFlowGraphPayload {
  if (typeof graphPayload !== 'object' || graphPayload === null) {
    return {};
  }
  return graphPayload as ChapterFlowGraphPayload;
}

function slugifyId(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return normalized || 'item';
}

function createCellIdFactory(): CellIdFactory {
  const issuedIds = new Set(['0', '1']);

  function issueId(prefix: string, rawId: string) {
    const base = `${prefix}-${slugifyId(rawId)}`;
    let candidate = base;
    let index = 2;

    while (issuedIds.has(candidate)) {
      candidate = `${base}-${index}`;
      index += 1;
    }

    issuedIds.add(candidate);
    return candidate;
  }

  return {
    createLaneId(rawId: string) {
      return issueId('ai-lane', rawId);
    },
    createNodeId(rawId: string) {
      return issueId('ai-node', rawId);
    },
    createEdgeId(rawId: string) {
      return issueId('ai-edge', rawId);
    }
  };
}

function buildLaneXml(
  lane: ChapterFlowLane,
  index: number,
  nodeInfo: CanvasSnapshotPayload['nodeInfo'],
  idFactory: CellIdFactory,
  nodeIdMap: Map<string, string>
): string {
  const children = lane.children ?? [];
  const laneX = LANE_START_X + index * (LANE_WIDTH + LANE_GAP);
  const laneHeight = Math.max(
    220,
    NODE_Y + children.length * (NODE_HEIGHT + NODE_GAP_Y) - NODE_GAP_Y + LANE_PADDING_BOTTOM
  );
  const laneCellId = idFactory.createLaneId(lane.id);

  nodeInfo[laneCellId] = {
    id: laneCellId,
    title: lane.name,
    content: '',
    summary: lane.name,
    position: '',
    department: '',
    owner: '',
    duty: '',
    tags: ['泳道', 'AI 导入'],
    metrics: [{ label: '章节序号', value: String(lane.order ?? index + 1) }],
    notes: []
  };

  const laneXml = [
    `<mxCell id="${escapeXml(laneCellId)}" value="${escapeXml(lane.name)}" style="${escapeXml(SWIMLANE_STYLE)}" vertex="1" parent="1">`,
    `<mxGeometry x="${laneX}" y="${LANE_START_Y}" width="${LANE_WIDTH}" height="${laneHeight}" as="geometry"/>`,
    '</mxCell>'
  ].join('');

  const childXml = children
    .map((child, childIndex) => {
      const y = NODE_Y + childIndex * (NODE_HEIGHT + NODE_GAP_Y);
      const responsibilities = child.metadata?.responsibilities ?? [];
      const duty = responsibilities.join('；');
      const childCellId = idFactory.createNodeId(child.id);
      if (!nodeIdMap.has(child.id)) {
        nodeIdMap.set(child.id, childCellId);
      }
      nodeInfo[childCellId] = {
        id: childCellId,
        title: child.name,
        content: child.summary ?? '',
        summary: child.summary ?? '',
        position: child.metadata?.role ?? '',
        department: child.metadata?.department ?? '',
        owner: child.metadata?.owner ?? '',
        duty,
        tags: ['活动', 'AI 导入'],
        metrics: duty ? [{ label: '职责', value: duty }] : [],
        notes: []
      } satisfies CanvasNodeInfo;

      return [
        `<mxCell id="${escapeXml(childCellId)}" value="${escapeXml(child.name)}" style="${escapeXml(NODE_STYLE)}" vertex="1" parent="${escapeXml(laneCellId)}">`,
        `<mxGeometry x="${NODE_X}" y="${y}" width="${NODE_WIDTH}" height="${NODE_HEIGHT}" as="geometry"/>`,
        '</mxCell>'
      ].join('');
    })
    .join('');

  return `${laneXml}${childXml}`;
}

function buildEdgeXml(edge: ChapterFlowEdge, edgeId: string, sourceId: string, targetId: string): string {
  return [
    `<mxCell id="${escapeXml(edgeId)}" style="${escapeXml(EDGE_STYLE)}" edge="1" parent="1" source="${escapeXml(sourceId)}" target="${escapeXml(targetId)}">`,
    '<mxGeometry relative="1" as="geometry"/>',
    '</mxCell>'
  ].join('');
}

export function buildCanvasSnapshotFromChapterFlow(graphPayload: unknown): CanvasSnapshotPayload {
  const normalized = normalizeGraphPayload(graphPayload);
  const lanes = normalized.lanes ?? [];
  const edges = normalized.edges ?? [];
  const nodeInfo: CanvasSnapshotPayload['nodeInfo'] = {};
  const idFactory = createCellIdFactory();
  const nodeIdMap = new Map<string, string>();

  const laneXml = lanes
    .map((lane, index) => buildLaneXml(lane, index, nodeInfo, idFactory, nodeIdMap))
    .join('');

  const edgeXml = edges
    .flatMap((edge) => {
      const sourceId = nodeIdMap.get(edge.source);
      const targetId = nodeIdMap.get(edge.target);

      if (!sourceId || !targetId) {
        return [];
      }

      return [buildEdgeXml(edge, idFactory.createEdgeId(edge.id), sourceId, targetId)];
    })
    .join('');

  const xmlContent = [
    '<mxGraphModel><root>',
    '<mxCell id="0"/>',
    '<mxCell id="1" parent="0"/>',
    laneXml,
    edgeXml,
    '</root></mxGraphModel>'
  ].join('');

  return {
    name: 'AI 导入流程图',
    xmlContent,
    nodeInfo
  };
}
