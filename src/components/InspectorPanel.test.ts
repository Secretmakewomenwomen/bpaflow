// @vitest-environment happy-dom

import { defineComponent, h } from 'vue';
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import InspectorPanel from './InspectorPanel.vue';

function mountInspectorPanel(saving = false) {
  const passthrough = defineComponent({
    name: 'PassThrough',
    setup(_, { slots }) {
      return () => h('div', slots.default?.());
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

  return mount(InspectorPanel, {
    props: {
      selection: {
        id: 'cell-1',
        title: '理赔节点',
        content: '节点内容',
        position: '产品经理',
        department: '理赔部',
        owner: '张三',
        duty: '需求推进',
        tags: ['节点'],
        metrics: [],
        notes: [],
        editable: true
      },
      saving
    },
    global: {
      stubs: {
        'a-space': passthrough,
        'a-typography-text': passthrough,
        'a-form': passthrough,
        'a-form-item': passthrough,
        'a-input': passthrough,
        'a-alert': passthrough,
        'a-tag': passthrough,
        'a-button': buttonStub
      }
    }
  });
}

describe('InspectorPanel', () => {
  it('emits update-selection when the apply button is clicked', async () => {
    const wrapper = mountInspectorPanel(false);

    const buttons = wrapper.findAll('button');
    const submitButton = buttons[1];
    await submitButton.trigger('click');

    expect(wrapper.emitted('update-selection')).toHaveLength(1);
  });

  it('shows a saving state on the submit button while persisting', () => {
    const wrapper = mountInspectorPanel(true);

    const buttons = wrapper.findAll('button');
    const submitButton = buttons[1];

    expect(submitButton.text()).toContain('保存中...');
    expect(submitButton.attributes('disabled')).toBeDefined();
  });
});
