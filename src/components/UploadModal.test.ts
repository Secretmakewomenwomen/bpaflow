// @vitest-environment happy-dom

import { defineComponent, h } from 'vue';
import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import UploadModal from './UploadModal.vue';

function mountUploadModal() {
  const passthrough = defineComponent({
    name: 'PassThrough',
    setup(_, { slots }) {
      return () => h('div', slots.default?.());
    }
  });

  const buttonStub = defineComponent({
    name: 'AButtonStub',
    emits: ['click'],
    setup(_, { emit, slots }) {
      return () =>
        h(
          'button',
          {
            type: 'button',
            onClick: () => emit('click')
          },
          slots.default?.()
        );
    }
  });

  return mount(UploadModal, {
    props: {
      open: true,
      uploading: false,
      deletingUploadId: null,
      error: '',
      selectedFile: null,
      successRecord: null,
      recentUploads: []
    },
    global: {
      stubs: {
        'a-modal': passthrough,
        'a-space': passthrough,
        'a-card': passthrough,
        'a-typography-text': passthrough,
        'a-alert': passthrough,
        'a-list': passthrough,
        'a-list-item': passthrough,
        'a-list-item-meta': passthrough,
        'a-button': buttonStub
      }
    }
  });
}

describe('UploadModal', () => {
  it('opens the hidden file input when the select button is clicked', async () => {
    const wrapper = mountUploadModal();
    const input = wrapper.get('input[type="file"]');
    const clickSpy = vi.fn();
    Object.defineProperty(input.element, 'click', {
      value: clickSpy,
      configurable: true
    });

    await wrapper.get('button').trigger('click');

    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted('select-file')).toBeUndefined();
  });

  it('emits the selected file from the native input change event', async () => {
    const wrapper = mountUploadModal();
    const input = wrapper.get('input[type="file"]');
    const file = new File(['content'], 'rule.pdf', { type: 'application/pdf' });

    Object.defineProperty(input.element, 'files', {
      value: [file],
      configurable: true
    });

    await input.trigger('change');

    expect(wrapper.emitted('select-file')).toEqual([[file]]);
  });
});
