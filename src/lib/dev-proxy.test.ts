import { afterEach, describe, expect, it, vi } from 'vitest';

import { resolveApiProxyTarget } from './dev-proxy';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('resolveApiProxyTarget', () => {
  it('returns the default local backend target when env is unset', () => {
    expect(resolveApiProxyTarget()).toBe('http://127.0.0.1:8000');
  });

  it('uses the configured env target and trims a trailing slash', () => {
    vi.stubEnv('VITE_API_PROXY_TARGET', 'https://api.example.com/');

    expect(resolveApiProxyTarget()).toBe('https://api.example.com');
  });
});
