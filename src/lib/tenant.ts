import type { TenantCreatePayload, TenantRecord } from '../types/tenant';

const TENANT_KEY = 'current_tenant_id';
const TENANT_API_BASE = '/api/tenants';
const DEFAULT_TENANT_ID = 'default';

function getStorage() {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.localStorage;
}

export function getCurrentTenantId() {
  return getStorage()?.getItem(TENANT_KEY) ?? DEFAULT_TENANT_ID;
}

export function setCurrentTenantId(tenantId: string) {
  const normalized = tenantId.trim();
  if (!normalized) {
    return;
  }
  getStorage()?.setItem(TENANT_KEY, normalized);
}

export function buildTenantHeaders(init?: HeadersInit) {
  const headers = new Headers(init);
  headers.set('X-Tenant-Id', getCurrentTenantId());
  return headers;
}

async function parseTenantResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail ?? '租户请求失败。');
  }
  return payload as T;
}

export async function listTenants() {
  const response = await fetch(TENANT_API_BASE, {
    headers: buildTenantHeaders()
  });
  return parseTenantResponse<TenantRecord[]>(response);
}

export async function createTenant(payload: TenantCreatePayload) {
  const response = await fetch(TENANT_API_BASE, {
    method: 'POST',
    headers: buildTenantHeaders({
      'Content-Type': 'application/json'
    }),
    body: JSON.stringify(payload)
  });
  return parseTenantResponse<TenantRecord>(response);
}
