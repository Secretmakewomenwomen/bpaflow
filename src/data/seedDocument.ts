import { createCanvasCellId } from '../lib/canvas-ids';
import { SWIMLANE_STYLE } from '../lib/canvas-style';

export interface MetricItem {
  label: string;
  value: string;
}

export interface CanvasSelection {
  id?: string;
  title: string;
  content?: string;
  summary?: string;
  position?: string;
  department?: string;
  owner?: string;
  duty?: string;
  tags: string[];
  metrics: MetricItem[];
  notes: string[];
  editable?: boolean;
}

export interface ArchitectureDocument {
  title: string;
  updatedAt: string;
  version: string;
  sections: Array<{ title: string; summary: string }>;
  checkpoints: MetricItem[];
  palette: string[];
}

export interface GraphCellMetadata {
  meta?: CanvasSelection;
}

export const defaultSelection: CanvasSelection = {
  id: 'board-overview',
  title: '画布概览',
  summary:
    '当前画布预置了一份可编辑的架构文档示例，而不是空白白板。你可以先调整运行时泳道和服务边界。',
  tags: ['画布', '单人模式', '可编辑'],
  metrics: [
    { label: '图表模式', value: '通用架构图' },
    { label: '泳道', value: '已启用' },
    { label: '自动保存', value: '下一步规划' }
  ],
  notes: [
    '拖动节点以调整布局和归属。',
    '可使用泳道表达环境、领域或团队边界。',
    '尽量保持文案简洁，保证一眼可读。'
  ],
  editable: false
};

export const seedDocument: ArchitectureDocument = {
  title: '结算平台',
  updatedAt: '刚刚',
  version: '草稿 01',
  sections: [
    { title: '背景上下文', summary: '业务范围与边界假设' },
    { title: '运行时泳道', summary: '入口、核心服务与数据边界' },
    { title: '请求路径', summary: '请求如何在系统中流转' },
    { title: '风险备注', summary: '运行缺口与后续事项' }
  ],
  checkpoints: [
    { label: '评审状态', value: '内部评审' },
    { label: '关键路径', value: '已梳理 3 条' },
    { label: '归属关系', value: '已对齐' }
  ],
  palette: ['泳道', '服务', '数据存储', '外部系统', '注释']
};

export function createSeedCells(graph: any) {
  const parent = graph.getDefaultParent();
  const model = graph.getModel();

  model.beginUpdate();

  try {
    const laneStyle = SWIMLANE_STYLE;
    const serviceStyle =
      'rounded=1;arcSize=18;fillColor=#101726;strokeColor=#3f6ef6;strokeWidth=1.2;fontColor=#f5f7fb;fontSize=14;shadow=0;spacing=12;whiteSpace=wrap;';
    const supportStyle =
      'rounded=1;arcSize=18;fillColor=#111a20;strokeColor=#4f7d63;strokeWidth=1.2;fontColor=#eaf4ee;fontSize=14;shadow=0;spacing=12;whiteSpace=wrap;';
    const dataStyle =
      'shape=cylinder3;boundedLbl=1;size=14;fillColor=#0f1622;strokeColor=#8b94a7;strokeWidth=1.2;fontColor=#ecf0f7;fontSize=13;whiteSpace=wrap;';
    const externalStyle =
      'rounded=1;arcSize=22;dashed=1;dashPattern=6 6;fillColor=#0d1320;strokeColor=#6b7486;strokeWidth=1;fontColor=#d9dfeb;fontSize=13;spacing=12;';

    const edgeLane = graph.insertVertex(parent, createCanvasCellId(), '入口 / 渠道', 0, 0, 360, 660, laneStyle);
    const coreLane = graph.insertVertex(parent, createCanvasCellId(), '核心服务', 380, 0, 420, 660, laneStyle);
    const dataLane = graph.insertVertex(parent, createCanvasCellId(), '数据与集成', 820, 0, 380, 660, laneStyle);

    (edgeLane as GraphCellMetadata).meta = {
      title: '入口 / 渠道泳道',
      summary: '承接用户请求的入口层，在流量进入核心服务之前完成接入与转发。',
      tags: ['泳道', '入口'],
      metrics: [
        { label: '节点数', value: '3' },
        { label: '区域', value: '外部入口层' },
        { label: '关注点', value: '流量整形' }
      ],
      notes: [
        '这一泳道只放接入层系统。',
        '鉴权和限流应在这里或紧接入口处完成。',
        '避免把数据系统混放到入口边界。'
      ]
    };

    (coreLane as GraphCellMetadata).meta = {
      title: '核心服务泳道',
      summary: '承载下单、支付和履约决策等关键业务编排服务。',
      tags: ['泳道', '应用核心'],
      metrics: [
        { label: '节点数', value: '4' },
        { label: '区域', value: '受保护运行区' },
        { label: '关注点', value: '业务编排' }
      ],
      notes: [
        '这是主要业务域集群。',
        '建议按请求流向从左到右或从上到下排列服务。',
        '泳道过于拥挤时，将辅助 worker 单独分组。'
      ]
    };

    (dataLane as GraphCellMetadata).meta = {
      title: '数据与集成泳道',
      summary: '承载结算平台所依赖的有状态系统和第三方集成。',
      tags: ['泳道', '有状态'],
      metrics: [
        { label: '节点数', value: '4' },
        { label: '区域', value: '持久化层' },
        { label: '关注点', value: '可靠性与外部契约' }
      ],
      notes: [
        '内部存储和外部集成要明确分开。',
        '如有需要，可通过边标签标识同步与异步边界。',
        '数据存储通常作为服务链路终点，而不是起点。'
      ]
    };

    const webApp = graph.insertVertex(edgeLane, createCanvasCellId(), '运营后台', 24, 72, 170, 68, serviceStyle);
    const gateway = graph.insertVertex(edgeLane, createCanvasCellId(), '接入网关', 24, 192, 170, 76, serviceStyle);
    const partner = graph.insertVertex(edgeLane, createCanvasCellId(), '合作方 API', 24, 322, 170, 68, externalStyle);

    const orchestrator = graph.insertVertex(coreLane, createCanvasCellId(), '结算编排服务', 42, 112, 196, 86, serviceStyle);
    const policy = graph.insertVertex(coreLane, createCanvasCellId(), '策略引擎', 42, 266, 196, 72, supportStyle);
    const fulfillment = graph.insertVertex(coreLane, createCanvasCellId(), '履约路由器', 42, 398, 196, 72, serviceStyle);
    const eventWorker = graph.insertVertex(coreLane, createCanvasCellId(), '事件 Worker', 42, 528, 196, 68, supportStyle);

    const orderDb = graph.insertVertex(dataLane, createCanvasCellId(), '订单库', 34, 104, 180, 90, dataStyle);
    const cache = graph.insertVertex(dataLane, createCanvasCellId(), '拓扑缓存', 34, 248, 180, 78, dataStyle);
    const paymentHub = graph.insertVertex(dataLane, createCanvasCellId(), '支付中心', 34, 382, 180, 70, externalStyle);
    const auditBus = graph.insertVertex(dataLane, createCanvasCellId(), '审计流', 34, 520, 180, 72, externalStyle);

    const metadata: Array<[any, CanvasSelection]> = [
      [
        webApp,
        {
          title: '运营后台',
          summary: '面向内部运营人员和商家的主要人工操作界面。',
          tags: ['服务', '界面'],
          metrics: [
            { label: '泳道', value: '入口 / 渠道' },
            { label: '使用方', value: '运营人员' },
            { label: '流量类型', value: '交互式' }
          ],
          notes: [
            '浏览器侧相关能力应收敛在这里。',
            '后台界面不应直接耦合数据存储。',
            '当前草稿中只展示了它对网关的依赖。'
          ]
        }
      ],
      [
        gateway,
        {
          title: '接入网关',
          summary: '负责校验、鉴权和向核心服务转发请求的统一入口。',
          tags: ['服务', '入口'],
          metrics: [
            { label: '泳道', value: '入口 / 渠道' },
            { label: '状态', value: '无状态' },
            { label: '协议', value: 'HTTP / JSON' }
          ],
          notes: [
            '清晰的入口边界可以让下游服务更简单。',
            '适合在这里做限流和粗粒度策略校验。',
            '南北向流量应在这里终止。'
          ]
        }
      ],
      [
        orchestrator,
        {
          title: '结算编排服务',
          summary: '负责结算状态流转和下游调用的核心事务协调器。',
          tags: ['服务', '关键路径'],
          metrics: [
            { label: '泳道', value: '核心服务' },
            { label: '优先级', value: '关键' },
            { label: '状态', value: '有状态工作流' }
          ],
          notes: [
            '这是当前图中的核心业务服务。',
            '避免把合作方分支逻辑直接塞进 UI。',
            '失败路径应降级到重试或审计流。'
          ]
        }
      ],
      [
        policy,
        {
          title: '策略引擎',
          summary: '为每笔结算请求评估路由约束和部署期规则集。',
          tags: ['服务', '规则'],
          metrics: [
            { label: '泳道', value: '核心服务' },
            { label: '时延预算', value: '< 20 ms' },
            { label: '模式', value: '同步' }
          ],
          notes: [
            '独立的策略节点有利于隔离决策逻辑。',
            '规则扩展时无需重画整个架构图。',
            '这个节点应保持纯决策职责。'
          ]
        }
      ],
      [
        fulfillment,
        {
          title: '履约路由器',
          summary: '将已确认的结算事件分发到下游交付或履约系统。',
          tags: ['服务', '路由'],
          metrics: [
            { label: '泳道', value: '核心服务' },
            { label: '耦合度', value: '中等' },
            { label: '流向', value: '异步扇出' }
          ],
          notes: [
            '尽量把异步边从这个服务发出。',
            '路由器职责要保持收敛。',
            '合作方契约应放在编排器之外处理。'
          ]
        }
      ],
      [
        orderDb,
        {
          title: '订单库',
          summary: '用于保存结算状态和提交流水的主记录库。',
          tags: ['数据存储', '事实来源'],
          metrics: [
            { label: '泳道', value: '数据与集成' },
            { label: '一致性', value: '强一致' },
            { label: '保留周期', value: '90 天' }
          ],
          notes: [
            '数据库应作为链路终点展示，而不是处理节点。',
            '写入所有权保持在编排服务侧。',
            '如有需要，后续再补副本和备份拓扑。'
          ]
        }
      ],
      [
        paymentHub,
        {
          title: '支付中心',
          summary: '负责清结算、令牌化和渠道流程的外部系统边界。',
          tags: ['外部系统', '依赖'],
          metrics: [
            { label: '泳道', value: '数据与集成' },
            { label: '契约', value: '外部 SLA' },
            { label: '风险', value: '高' }
          ],
          notes: [
            '外部系统需要与内部服务保持明显视觉区分。',
            '如果支付是核心链路，应在这里标出降级或补偿流程。',
            '不要把契约风险隐藏在通用服务节点里。'
          ]
        }
      ]
    ];

    metadata.forEach(([cell, meta]) => {
      (cell as GraphCellMetadata).meta = meta;
    });

    graph.insertEdge(parent, createCanvasCellId(), '', webApp, gateway);
    graph.insertEdge(parent, createCanvasCellId(), '', partner, gateway);
    graph.insertEdge(parent, createCanvasCellId(), '', gateway, orchestrator);
    graph.insertEdge(parent, createCanvasCellId(), '', orchestrator, policy);
    graph.insertEdge(parent, createCanvasCellId(), '', policy, orchestrator);
    graph.insertEdge(parent, createCanvasCellId(), '', orchestrator, orderDb);
    graph.insertEdge(parent, createCanvasCellId(), '', orchestrator, cache);
    graph.insertEdge(parent, createCanvasCellId(), '', orchestrator, paymentHub);
    graph.insertEdge(parent, createCanvasCellId(), '', orchestrator, fulfillment);
    graph.insertEdge(parent, createCanvasCellId(), '', fulfillment, auditBus);
    graph.insertEdge(parent, createCanvasCellId(), '', fulfillment, eventWorker);
  } finally {
    model.endUpdate();
  }
}
