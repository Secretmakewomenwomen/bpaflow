import { clearAuth, getToken } from './auth';
import { getCurrentTenantId } from './tenant';

export async function apiFetch(input: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  const token = getToken();

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  headers.set('X-Tenant-Id', getCurrentTenantId());

  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(input, {
    ...init,
    headers
  });

  if (response.status === 401) {
    clearAuth();
  }

  return response;
}
