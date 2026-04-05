export interface CanvasNodeInfo {
  id?: string;
  title: string;
  content: string;
  summary?: string;
  position: string;
  department: string;
  owner: string;
  duty: string;
  tags: string[];
  metrics: Array<{ label: string; value: string }>;
  notes: string[];
  editable?: boolean;
}

export interface CanvasSnapshotPayload {
  name: string;
  xmlContent: string;
  nodeInfo: Record<string, CanvasNodeInfo>;
}

export interface CanvasTreeNode {
  id: string;
  parentId: string | null;
  name: string;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
}

export interface CanvasRecord extends CanvasSnapshotPayload {
  id: string;
  nodeId: string;
  exists: boolean;
  createdAt: string;
  updatedAt: string;
}
