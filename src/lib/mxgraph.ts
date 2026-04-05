import factory from 'mxgraph';

let instance: ReturnType<typeof factory> | null = null;

export function getMxgraph() {
  if (!instance) {
    instance = factory({
      mxBasePath: 'mxgraph',
      mxImageBasePath: 'mxgraph/images',
      mxLoadResources: false,
      mxLoadStylesheets: false
    });

    if (typeof window !== 'undefined') {
      Object.assign(window as Record<string, unknown>, {
        mxCell: instance.mxCell,
        mxGeometry: instance.mxGeometry,
        mxGraphModel: instance.mxGraphModel,
        mxPoint: instance.mxPoint,
        mxRectangle: instance.mxRectangle,
      });
    }
  }

  return instance;
}
