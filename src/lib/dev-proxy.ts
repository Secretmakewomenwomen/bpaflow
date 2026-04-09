const DEFAULT_API_PROXY_TARGET = 'http://127.0.0.1:8000';

export function resolveApiProxyTarget(): string {
  const target = import.meta.env.VITE_API_PROXY_TARGET?.trim();
  if (!target) {
    return DEFAULT_API_PROXY_TARGET;
  }

  return target.replace(/\/+$/, '');
}
