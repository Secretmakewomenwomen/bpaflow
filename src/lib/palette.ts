import type { CanvasSelection } from '../data/seedDocument';
import { SWIMLANE_STYLE } from './canvas-style';

export type PaletteItemId =
  | 'swimlane'
  | 'service'
  | 'data-store'
  | 'external-system'
  | 'annotation';

export interface PaletteItem {
  id: PaletteItemId;
  label: string;
  description: string;
  badge: string;
}

export interface PaletteNodeTemplate {
  value: string;
  width: number;
  height: number;
  style: string;
  meta: CanvasSelection;
  parentBehavior: 'root-only' | 'lane-or-root';
}

export interface GraphBoundsLike {
  x: number;
  y: number;
  width: number;
  height: number;
  startSize?: number;
}

export const paletteDragMimeType = 'application/x-architecture-node';

export const paletteItems: PaletteItem[] = [
  {
    id: 'swimlane',
    label: '泳道',
    description: '新增一个运行时或归属边界。',
    badge: '边界'
  },
  {
    id: 'service',
    label: '活动',
    description: '核心应用或编排节点。',
    badge: '处理'
  },
  {
    id: 'data-store',
    label: '数据存储',
    description: '数据库、缓存或日志等持久化系统。',
    badge: '有状态'
  },
  {
    id: 'external-system',
    label: '外部系统',
    description: '第三方或跨域依赖边界。',
    badge: '外部'
  },
  {
    id: 'annotation',
    label: '注释',
    description: '用于补充上下文和实现说明。',
    badge: '说明'
  }
];

export function createPaletteNodeTemplate(
  itemId: PaletteItemId,
  laneLabel = '未归属'
): PaletteNodeTemplate {
  switch (itemId) {
    case 'swimlane':
      return {
        value: '新泳道',
        width: 320,
        height: 380,
        style: SWIMLANE_STYLE,
        parentBehavior: 'root-only',
        meta: {
          title: '新泳道',
          content: '用于表达系统、环境或组织归属的纵向边界。',
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
        }
      };
    case 'service':
      return {
        value: '活动',
        width: 180,
        height: 72,
        style:
          'rounded=1;arcSize=18;fillColor=#101726;strokeColor=#3f6ef6;strokeWidth=1.2;fontColor=#f5f7fb;fontSize=14;shadow=0;spacing=12;whiteSpace=wrap;',
        parentBehavior: 'lane-or-root',
        meta: {
          title: '活动',
          content: '新插入到当前架构画布中的应用服务节点。',
          tags: ['服务', '草稿'],
          metrics: [
            { label: '泳道', value: laneLabel },
            { label: '状态', value: '草稿' },
            { label: '归属', value: '架构设计' }
          ],
          notes: [
            '请将该节点连接到上游链路。',
            '如果属于某个运行时边界，请拖入对应泳道。',
            '尽量使用简洁标签保证可读性。'
          ]
        }
      };
    case 'data-store':
      return {
        value: '新存储',
        width: 180,
        height: 84,
        style:
          'shape=cylinder3;boundedLbl=1;size=14;fillColor=#0f1622;strokeColor=#8b94a7;strokeWidth=1.2;fontColor=#ecf0f7;fontSize=13;whiteSpace=wrap;',
        parentBehavior: 'lane-or-root',
        meta: {
          title: '新存储',
          content: '用于持久化、缓存或事件沉淀的有状态端点。',
          tags: ['数据存储', '草稿'],
          metrics: [
            { label: '泳道', value: laneLabel },
            { label: '状态', value: '草稿' },
            { label: '一致性', value: '待确定' }
          ],
          notes: [
            '数据存储应作为链路中的终点节点。',
            '请与服务节点保持明显区分以提升可读性。',
            '异步沉淀系统应与事务数据库分开建模。'
          ]
        }
      };
    case 'external-system':
      return {
        value: '新外部系统',
        width: 190,
        height: 72,
        style:
          'rounded=1;arcSize=22;dashed=1;dashPattern=6 6;fillColor=#0d1320;strokeColor=#6b7486;strokeWidth=1;fontColor=#d9dfeb;fontSize=13;spacing=12;',
        parentBehavior: 'lane-or-root',
        meta: {
          title: '新外部系统',
          content: '新加入到图中的跨团队或第三方依赖边界。',
          tags: ['外部系统', '草稿'],
          metrics: [
            { label: '泳道', value: laneLabel },
            { label: '风险', value: '待确定' },
            { label: '契约', value: '待定义' }
          ],
          notes: [
            '外部系统要与内部服务保持明显视觉差异。',
            '可在检查器中补充 SLA 或归属说明。',
            '仅在契约清晰时才连接该节点。'
          ]
        }
      };
    case 'annotation':
      return {
        value: '架构注释',
        width: 210,
        height: 74,
        style:
          'rounded=1;arcSize=18;fillColor=#11161f;strokeColor=#7c8aa5;strokeWidth=1;dashed=1;dashPattern=4 4;fontColor=#d7e0ef;fontSize=13;whiteSpace=wrap;align=left;spacing=12;',
        parentBehavior: 'lane-or-root',
        meta: {
          title: '架构注释',
          content: '用于在画布上直接解释取舍、约束或后续工作的说明节点。',
          tags: ['注释', '草稿'],
          metrics: [
            { label: '泳道', value: laneLabel },
            { label: '用途', value: '上下文说明' },
            { label: '状态', value: '草稿' }
          ],
          notes: [
            '用注释解释边界，而不是把信息都塞进节点标签。',
            '长文本说明应放在这里，而不是写进服务名称。',
            '当架构已经足够自解释时，可以删除这些注释。'
          ]
        }
      };
  }
}

export function resolveDropPosition(
  template: Pick<PaletteNodeTemplate, 'width' | 'height' | 'parentBehavior'>,
  dropPoint: { x: number; y: number },
  parentBounds?: GraphBoundsLike
) {
  if (!parentBounds || template.parentBehavior === 'root-only') {
    return {
      x: Math.max(40, Math.round(dropPoint.x - template.width / 2)),
      y: Math.max(48, Math.round(dropPoint.y - template.height / 2))
    };
  }

  const startSize = parentBounds.startSize ?? 40;
  const minX = 24;
  const minY = startSize + 16;
  const maxX = Math.max(minX, parentBounds.width - template.width - 24);
  const maxY = Math.max(minY, parentBounds.height - template.height - 24);

  return {
    x: Math.min(
      maxX,
      Math.max(minX, Math.round(dropPoint.x - parentBounds.x - template.width / 2))
    ),
    y: Math.min(
      maxY,
      Math.max(minY, Math.round(dropPoint.y - parentBounds.y - template.height / 2))
    )
  };
}
