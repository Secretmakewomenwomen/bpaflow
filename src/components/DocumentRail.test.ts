// @vitest-environment happy-dom

import { mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { describe, expect, it } from 'vitest';
import DocumentRail from './DocumentRail.vue';
import { seedDocument } from '../data/seedDocument';

const passthrough = defineComponent({
  name: 'PassThrough',
  setup(_, { slots, attrs }) {
    return () => h('div', attrs, slots.default?.());
  }
});

const buttonStub = defineComponent({
  name: 'AButtonStub',
  emits: ['click'],
  setup(_, { emit, slots, attrs }) {
    return () =>
      h(
        'button',
        {
          ...attrs,
          type: 'button',
          onClick: () => emit('click')
        },
        slots.default?.()
      );
  }
});

function mountRail() {
  return mount(DocumentRail, {
    props: {
      document: seedDocument,
      nodes: [
        {
          id: 'root-1',
          parentId: null,
          name: '业务域',
          sortOrder: 0,
          createdAt: '2026-03-30T00:00:00Z',
          updatedAt: '2026-03-30T00:00:00Z'
        },
        {
          id: 'child-1',
          parentId: 'root-1',
          name: '理赔流程',
          sortOrder: 0,
          createdAt: '2026-03-30T00:01:00Z',
          updatedAt: '2026-03-30T00:01:00Z'
        }
      ],
      activeNodeId: 'root-1'
    },
    global: {
      stubs: {
        'a-space': passthrough,
        'a-card': passthrough,
        'a-descriptions': passthrough,
        'a-descriptions-item': passthrough,
        'a-typography-text': passthrough,
        'a-tag': passthrough,
        'a-button': buttonStub
      }
    }
  });
}

describe('DocumentRail', () => {
  it('renders tree nodes and highlights the active one', () => {
    const wrapper = mountRail();

    expect(wrapper.text()).toContain('业务域');
    expect(wrapper.text()).toContain('理赔流程');
    expect(wrapper.get('[data-testid="canvas-tree-node-root-1"]').classes()).toContain(
      'tree-node-button--active'
    );
  });

  it('emits create and select events', async () => {
    const wrapper = mountRail();

    await wrapper.get('[data-testid="canvas-tree-create-root"]').trigger('click');
    await wrapper.get('[data-testid="canvas-tree-create-child"]').trigger('click');
    await wrapper.get('[data-testid="canvas-tree-node-child-1"]').trigger('click');

    expect(wrapper.emitted('create-root-node')).toHaveLength(1);
    expect(wrapper.emitted('create-child-node')).toHaveLength(1);
    expect(wrapper.emitted('select-node')).toEqual([['child-1']]);
  });
});
