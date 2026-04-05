import type { CanvasRecord } from '../types/canvas';

export interface CanvasBootstrapState {
  mode: 'saved' | 'seed';
  statusText: string;
}

export function resolveCanvasBootstrapState(canvas: CanvasRecord | null): CanvasBootstrapState {
  if (canvas) {
    return {
      mode: 'saved',
      statusText: '已加载你的专属画布'
    };
  }

  return {
    mode: 'seed',
    statusText: '当前账号还没有已保存画布'
  };
}
